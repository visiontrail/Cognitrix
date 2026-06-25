from __future__ import annotations

import sqlite3
from io import BytesIO
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from apps.api.agentic_ingestion.uploads import clear_ingestion_upload_service_cache
from apps.api.audit import clear_audit_logger_cache
from apps.api.auth import clear_auth_cache
from apps.api.chat import clear_chat_stream_service_cache
from apps.api.config import get_settings
from apps.api.datasets import clear_dataset_service_cache
from apps.api.main import app
from apps.api.semantic import clear_semantic_cache
from apps.api.table_catalog import clear_table_catalog_service_cache
from apps.api.tool_calling import clear_tool_calling_service_cache
from apps.api.views import clear_view_storage_service_cache
from apps.api.workspaces import clear_workspace_service_cache
from tests.agentic_ingestion_fakes import install_mock_planning_agent
from tests.auth_utils import auth_headers, expect_error_code


def _set_minimal_env(monkeypatch, tmp_path: Path, *, ingestion_enabled: bool) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'workspace-state.db'}")
    monkeypatch.setenv("MODEL_PROVIDER_URL", "http://localhost:11434")
    monkeypatch.setenv("AI_API_KEY", "test-ai-key")
    monkeypatch.setenv("AI_MODEL", "deepseek-chat")
    monkeypatch.setenv("AI_TIMEOUT_SECONDS", "20")
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("AGENTIC_INGESTION_ENABLED", "true" if ingestion_enabled else "false")
    install_mock_planning_agent(monkeypatch)

    get_settings.cache_clear()
    clear_auth_cache()
    clear_audit_logger_cache()
    clear_chat_stream_service_cache()
    clear_dataset_service_cache()
    clear_semantic_cache()
    clear_tool_calling_service_cache()
    clear_view_storage_service_cache()
    clear_workspace_service_cache()
    clear_table_catalog_service_cache()
    clear_ingestion_upload_service_cache()


def _excel_bytes() -> bytes:
    roster = pd.DataFrame(
        [
            {"Employee ID": "E-001", "Name": "Alice", "Department": "HR"},
            {"Employee ID": "E-002", "Name": "Bob", "Department": "PM"},
            {"Employee ID": "E-003", "Name": "Cathy", "Department": "Finance"},
        ]
    )

    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        roster.to_excel(writer, index=False, sheet_name="Roster")
    return buffer.getvalue()


def _upload_file_payload() -> list[tuple[str, tuple[str, bytes, str]]]:
    return [
        (
            "files",
            (
                "roster.xlsx",
                _excel_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        )
    ]


def _create_workspace(client: TestClient, headers: dict[str, str], *, name: str) -> str:
    response = client.post("/workspaces", json={"name": name}, headers=headers)
    assert response.status_code == 200
    return response.json()["workspace_id"]


def _create_upload(client: TestClient, headers: dict[str, str], *, workspace_id: str) -> dict[str, str]:
    response = client.post(
        "/ingestion/uploads",
        data={"workspace_id": workspace_id},
        headers=headers,
        files=_upload_file_payload(),
    )
    assert response.status_code == 200
    return response.json()


def _create_setup_required_plan(
    client: TestClient,
    headers: dict[str, str],
    *,
    workspace_id: str,
    job_id: str,
) -> dict[str, object]:
    response = client.post(
        "/ingestion/plan",
        json={
            "workspace_id": workspace_id,
            "job_id": job_id,
            "conversation_id": "conv-setup-plan",
            "message": "请先初始化写入规则再导入",
        },
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "awaiting_catalog_setup"
    return payload


def test_setup_confirm_creates_catalog_and_returns_proposal(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path, ingestion_enabled=True)

    with TestClient(app) as client:
        owner_headers = auth_headers(client, user_id="alice", project_id="north", role="admin")
        workspace_id = _create_workspace(client, owner_headers, name="Setup Confirm Workspace")
        upload_payload = _create_upload(client, owner_headers, workspace_id=workspace_id)
        setup_required_payload = _create_setup_required_plan(
            client,
            owner_headers,
            workspace_id=workspace_id,
            job_id=upload_payload["job_id"],
        )
        seed = setup_required_payload["suggested_catalog_seed"]
        assert isinstance(seed, dict)
        seed["human_label"] = "Employee Roster M5"

        confirm_response = client.post(
            "/ingestion/setup/confirm",
            json={
                "workspace_id": workspace_id,
                "job_id": upload_payload["job_id"],
                "conversation_id": "conv-setup-confirm",
                "message": "继续生成 proposal",
                "setup": seed,
            },
            headers=owner_headers,
        )

    assert confirm_response.status_code == 200
    payload = confirm_response.json()
    assert payload["status"] == "awaiting_user_approval"
    assert payload["setup"]["status"] == "confirmed"
    assert payload["setup"]["catalog_entry"]["workspace_id"] == workspace_id
    assert payload["setup"]["catalog_entry"]["table_name"] == seed["table_name"]
    assert payload["proposal_id"]
    assert payload["proposal_json"]["target_table"] == seed["table_name"]

    db_path = tmp_path / "workspace-state.db"
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        catalog_rows = conn.execute(
            """
            SELECT table_name, business_type, is_active_target
            FROM table_catalog
            WHERE workspace_id = ? AND business_type = ?
            """,
            (workspace_id, seed["business_type"]),
        ).fetchall()
        assert len(catalog_rows) == 1
        assert str(catalog_rows[0]["table_name"]) == seed["table_name"]
        assert int(catalog_rows[0]["is_active_target"]) == 1

        job_row = conn.execute(
            "SELECT status FROM ingestion_jobs WHERE id = ?",
            (upload_payload["job_id"],),
        ).fetchone()
        assert job_row is not None
        assert str(job_row["status"]) == "awaiting_user_approval"

        event_rows = conn.execute(
            "SELECT event_type FROM ingestion_events WHERE job_id = ?",
            (upload_payload["job_id"],),
        ).fetchall()
        event_types = {str(item["event_type"]) for item in event_rows}
        assert "setup_confirmed" in event_types
        assert "proposal_generated" in event_types


def test_setup_confirm_accepts_business_intent_only_seed(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path, ingestion_enabled=True)

    with TestClient(app) as client:
        owner_headers = auth_headers(client, user_id="alice", project_id="north", role="admin")
        workspace_id = _create_workspace(client, owner_headers, name="Intent Only Setup Workspace")
        upload_payload = _create_upload(client, owner_headers, workspace_id=workspace_id)
        setup_required_payload = _create_setup_required_plan(
            client,
            owner_headers,
            workspace_id=workspace_id,
            job_id=upload_payload["job_id"],
        )
        seed = setup_required_payload["suggested_catalog_seed"]
        assert isinstance(seed, dict)
        seed["primary_keys"] = []
        seed["match_columns"] = []
        seed["write_mode"] = "new_table"

        confirm_response = client.post(
            "/ingestion/setup/confirm",
            json={
                "workspace_id": workspace_id,
                "job_id": upload_payload["job_id"],
                "setup": seed,
            },
            headers=owner_headers,
        )

    assert confirm_response.status_code == 200
    payload = confirm_response.json()
    assert payload["status"] == "awaiting_user_approval"
    assert payload["setup"]["catalog_entry"]["primary_keys"] == []
    assert payload["setup"]["catalog_entry"]["match_columns"] == []


def test_setup_confirm_prevents_repeat_setup_for_same_business_type(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path, ingestion_enabled=True)

    with TestClient(app) as client:
        owner_headers = auth_headers(client, user_id="alice", project_id="north", role="admin")
        workspace_id = _create_workspace(client, owner_headers, name="Setup Repeat Guard")

        first_upload = _create_upload(client, owner_headers, workspace_id=workspace_id)
        setup_required_payload = _create_setup_required_plan(
            client,
            owner_headers,
            workspace_id=workspace_id,
            job_id=first_upload["job_id"],
        )
        seed = setup_required_payload["suggested_catalog_seed"]
        assert isinstance(seed, dict)
        confirm_response = client.post(
            "/ingestion/setup/confirm",
            json={
                "workspace_id": workspace_id,
                "job_id": first_upload["job_id"],
                "setup": seed,
            },
            headers=owner_headers,
        )
        assert confirm_response.status_code == 200

        second_upload = _create_upload(client, owner_headers, workspace_id=workspace_id)
        second_plan_response = client.post(
            "/ingestion/plan",
            json={
                "workspace_id": workspace_id,
                "job_id": second_upload["job_id"],
                "message": "继续导入同类花名册",
            },
            headers=owner_headers,
        )

    assert second_plan_response.status_code == 200
    second_payload = second_plan_response.json()
    assert second_payload["status"] == "awaiting_user_approval"
    assert second_payload["proposal_id"]
    assert "setup_questions" not in second_payload


def test_setup_confirm_workspace_role_guard(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path, ingestion_enabled=True)

    with TestClient(app) as client:
        owner_headers = auth_headers(client, user_id="alice", project_id="north", role="admin")
        viewer_headers = auth_headers(client, user_id="bob", project_id="north", role="hr")
        workspace_id = _create_workspace(client, owner_headers, name="Setup Role Guard")
        add_member_response = client.post(
            f"/workspaces/{workspace_id}/members",
            headers=owner_headers,
            json={"user_id": "bob", "role": "viewer", "display_name": "Bob Viewer"},
        )
        # Viewer membership is no longer a valid role; bob stays a non-member.
        assert add_member_response.status_code == 422

        upload_payload = _create_upload(client, owner_headers, workspace_id=workspace_id)
        setup_required_payload = _create_setup_required_plan(
            client,
            owner_headers,
            workspace_id=workspace_id,
            job_id=upload_payload["job_id"],
        )
        seed = setup_required_payload["suggested_catalog_seed"]
        assert isinstance(seed, dict)
        response = client.post(
            "/ingestion/setup/confirm",
            json={
                "workspace_id": workspace_id,
                "job_id": upload_payload["job_id"],
                "setup": seed,
            },
            headers=viewer_headers,
        )

    expect_error_code(response, "WORKSPACE_FORBIDDEN", status_code=403)


def test_setup_confirm_ignores_disabled_feature_flag(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path, ingestion_enabled=False)

    with TestClient(app) as client:
        owner_headers = auth_headers(client, user_id="alice", project_id="north", role="admin")
        workspace_id = _create_workspace(client, owner_headers, name="Setup Flag Guard")
        response = client.post(
            "/ingestion/setup/confirm",
            json={
                "workspace_id": workspace_id,
                "job_id": "job-demo",
                "setup": {
                    "business_type": "roster",
                    "table_name": "employee_roster",
                    "human_label": "Employee Roster",
                    "write_mode": "update_existing",
                    "time_grain": "none",
                    "primary_keys": ["employee_id"],
                    "match_columns": ["employee_id"],
                    "is_active_target": True,
                    "description": "",
                },
            },
            headers=owner_headers,
        )

    expect_error_code(response, "INGESTION_JOB_NOT_FOUND", status_code=404)
