from __future__ import annotations

import json
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
from tests.auth_utils import auth_headers, expect_error_code
from tests.agentic_ingestion_fakes import install_failing_planning_agent, install_mock_planning_agent


def _set_minimal_env(
    monkeypatch,
    tmp_path: Path,
    *,
    ingestion_enabled: bool,
    model_provider_url: str = "http://localhost:11434",
    ai_api_key: str = "test-ai-key",
    ai_timeout_seconds: str = "20",
    mock_llm_success: bool = True,
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'workspace-state.db'}")
    monkeypatch.setenv("MODEL_PROVIDER_URL", model_provider_url)
    monkeypatch.setenv("AI_API_KEY", ai_api_key)
    monkeypatch.setenv("AI_MODEL", "deepseek-chat")
    monkeypatch.setenv("AI_TIMEOUT_SECONDS", ai_timeout_seconds)
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("AGENTIC_INGESTION_ENABLED", "true" if ingestion_enabled else "false")
    if mock_llm_success:
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


def test_ingestion_plan_returns_setup_when_catalog_missing(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path, ingestion_enabled=True)

    with TestClient(app) as client:
        owner_headers = auth_headers(client, user_id="alice", project_id="north", role="admin")
        workspace_id = _create_workspace(client, owner_headers, name="Plan Setup Workspace")
        upload_payload = _create_upload(client, owner_headers, workspace_id=workspace_id)

        plan_response = client.post(
            "/ingestion/plan",
            json={
                "workspace_id": workspace_id,
                "job_id": upload_payload["job_id"],
                "conversation_id": "conv-setup-1",
                "message": "请帮我导入这份花名册",
            },
            headers=owner_headers,
        )

    assert plan_response.status_code == 200
    payload = plan_response.json()
    assert payload["status"] == "awaiting_catalog_setup"
    assert payload["job_id"] == upload_payload["job_id"]
    assert payload["agent_guess"]["business_type"] in {
        "roster",
        "project_progress",
        "attendance",
        "other",
    }
    assert payload["setup_questions"]
    assert payload["suggested_catalog_seed"]["table_name"]
    assert payload["route"]["route"] == "write_ingestion"
    assert payload["tool_trace"]

    db_path = tmp_path / "workspace-state.db"
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        job_row = conn.execute(
            "SELECT status, business_type_guess, agent_session_id FROM ingestion_jobs WHERE id = ?",
            (upload_payload["job_id"],),
        ).fetchone()
        assert job_row is not None
        assert str(job_row["status"]) == "awaiting_catalog_setup"
        assert str(job_row["agent_session_id"]) == "conv-setup-1"

        setup_event = conn.execute(
            "SELECT event_type, payload FROM ingestion_events WHERE job_id = ? ORDER BY created_at DESC LIMIT 1",
            (upload_payload["job_id"],),
        ).fetchone()
        assert setup_event is not None
        assert str(setup_event["event_type"]) in {"setup_required", "tool_result"}


def test_ingestion_plan_persists_proposal(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path, ingestion_enabled=True)

    with TestClient(app) as client:
        owner_headers = auth_headers(client, user_id="alice", project_id="north", role="admin")
        workspace_id = _create_workspace(client, owner_headers, name="Plan Proposal Workspace")

        catalog_response = client.post(
            f"/workspaces/{workspace_id}/catalog",
            headers=owner_headers,
            json={
                "table_name": "employee_roster",
                "human_label": "Employee Roster",
                "business_type": "roster",
                "write_mode": "update_existing",
                "time_grain": "none",
                "primary_keys": ["employee_id"],
                "match_columns": ["employee_id"],
                "is_active_target": True,
                "description": "Primary roster table",
            },
        )
        assert catalog_response.status_code == 200

        upload_payload = _create_upload(client, owner_headers, workspace_id=workspace_id)
        plan_response = client.post(
            "/ingestion/plan",
            json={
                "workspace_id": workspace_id,
                "job_id": upload_payload["job_id"],
                "conversation_id": "conv-proposal-1",
                "message": "导入最新花名册并更新现有表",
            },
            headers=owner_headers,
        )

    assert plan_response.status_code == 200
    payload = plan_response.json()
    assert payload["status"] == "awaiting_user_approval"
    assert payload["proposal_id"]
    proposal_json = payload["proposal_json"]
    assert proposal_json["target_table"] == "employee_roster"
    assert proposal_json["recommended_action"] in {
        "update_existing",
        "time_partitioned_new_table",
        "new_table",
        "cancel",
    }
    assert proposal_json["diff_preview"]["predicted_insert_count"] >= 0
    assert payload["route"]["route"] == "write_ingestion"

    db_path = tmp_path / "workspace-state.db"
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        job_row = conn.execute(
            "SELECT status, business_type_guess FROM ingestion_jobs WHERE id = ?",
            (upload_payload["job_id"],),
        ).fetchone()
        assert job_row is not None
        assert str(job_row["status"]) == "awaiting_user_approval"
        assert str(job_row["business_type_guess"]) == proposal_json["business_type"]

        proposal_row = conn.execute(
            """
            SELECT id, proposal_version, proposal_json, recommended_action, target_table
            FROM ingestion_proposals
            WHERE id = ?
            """,
            (payload["proposal_id"],),
        ).fetchone()
        assert proposal_row is not None
        assert int(proposal_row["proposal_version"]) == 1
        assert str(proposal_row["recommended_action"]) == proposal_json["recommended_action"]
        assert str(proposal_row["target_table"]) == "employee_roster"
        persisted_json = json.loads(str(proposal_row["proposal_json"]))
        assert persisted_json["target_table"] == "employee_roster"

        event_rows = conn.execute(
            "SELECT event_type FROM ingestion_events WHERE job_id = ?",
            (upload_payload["job_id"],),
        ).fetchall()
        event_types = {str(item["event_type"]) for item in event_rows}
        assert "tool_use" in event_types
        assert "tool_result" in event_types
        assert "business_type_inferred" in event_types
        assert "human_approval_requested" in event_types
        assert "proposal_generated" in event_types


def test_ingestion_plan_reports_agent_loop_audit(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path, ingestion_enabled=True)

    with TestClient(app) as client:
        owner_headers = auth_headers(client, user_id="alice", project_id="north", role="admin")
        workspace_id = _create_workspace(client, owner_headers, name="Plan Audit Rules Workspace")
        upload_payload = _create_upload(client, owner_headers, workspace_id=workspace_id)
        plan_response = client.post(
            "/ingestion/plan",
            json={
                "workspace_id": workspace_id,
                "job_id": upload_payload["job_id"],
                "conversation_id": "conv-audit-rules",
                "message": "请帮我分析导入类型",
            },
            headers=owner_headers,
        )

    assert plan_response.status_code == 200
    payload = plan_response.json()
    audit = payload["analysis_audit"]["agent_planning"]
    assert audit["engine"] == "write_ingestion_agent_loop"
    assert audit["runtime_backend"] == "claude-agent-sdk"
    assert audit["human_approval_tool_required"] is False

    tool_names = {item.get("tool_name") for item in payload["tool_trace"]}
    assert "AskUserQuestion" not in tool_names
    assert payload["human_approval"]["stage"] in {"catalog_setup", "proposal_approval"}
    assert payload["human_approval"]["required"] is True

    db_path = tmp_path / "workspace-state.db"
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT payload
            FROM ingestion_events
            WHERE job_id = ? AND event_type = 'business_type_inferred'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (upload_payload["job_id"],),
        ).fetchone()
        assert row is not None
        payload_json = json.loads(str(row["payload"]))
        assert payload_json["analysis_audit"]["engine"] == "write_ingestion_agent_loop"


def test_ingestion_plan_fails_when_ai_not_configured(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(
        monkeypatch,
        tmp_path,
        ingestion_enabled=True,
        ai_api_key="",
        mock_llm_success=False,
    )

    with TestClient(app) as client:
        owner_headers = auth_headers(client, user_id="alice", project_id="north", role="admin")
        workspace_id = _create_workspace(client, owner_headers, name="Plan AI Missing Workspace")
        upload_payload = _create_upload(client, owner_headers, workspace_id=workspace_id)
        plan_response = client.post(
            "/ingestion/plan",
            json={
                "workspace_id": workspace_id,
                "job_id": upload_payload["job_id"],
                "conversation_id": "conv-audit-fallback",
                "message": "请帮我分析导入类型",
            },
            headers=owner_headers,
        )

    expect_error_code(plan_response, "INGESTION_AI_NOT_CONFIGURED", status_code=503)


def test_ingestion_plan_fails_when_ai_service_unavailable(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(
        monkeypatch,
        tmp_path,
        ingestion_enabled=True,
        model_provider_url="http://127.0.0.1:9",
        ai_api_key="demo-key",
        ai_timeout_seconds="0.2",
        mock_llm_success=False,
    )
    install_failing_planning_agent(
        monkeypatch,
        code="INGESTION_AI_UNAVAILABLE",
        message="mock agent unavailable",
        status_code=503,
    )

    with TestClient(app) as client:
        owner_headers = auth_headers(client, user_id="alice", project_id="north", role="admin")
        workspace_id = _create_workspace(client, owner_headers, name="Plan AI Unavailable Workspace")
        upload_payload = _create_upload(client, owner_headers, workspace_id=workspace_id)
        plan_response = client.post(
            "/ingestion/plan",
            json={
                "workspace_id": workspace_id,
                "job_id": upload_payload["job_id"],
                "conversation_id": "conv-ai-down",
                "message": "请帮我分析导入类型",
            },
            headers=owner_headers,
        )

    expect_error_code(plan_response, "INGESTION_AI_UNAVAILABLE", status_code=503)

def test_ingestion_plan_workspace_role_guard(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path, ingestion_enabled=True)

    with TestClient(app) as client:
        owner_headers = auth_headers(client, user_id="alice", project_id="north", role="admin")
        viewer_headers = auth_headers(client, user_id="bob", project_id="north", role="hr")
        workspace_id = _create_workspace(client, owner_headers, name="Plan Guard Workspace")
        add_member_response = client.post(
            f"/workspaces/{workspace_id}/members",
            headers=owner_headers,
            json={"user_id": "bob", "role": "viewer", "display_name": "Bob Viewer"},
        )
        # Viewer membership is no longer a valid role; bob stays a non-member.
        assert add_member_response.status_code == 422
        upload_payload = _create_upload(client, owner_headers, workspace_id=workspace_id)

        plan_response = client.post(
            "/ingestion/plan",
            json={"workspace_id": workspace_id, "job_id": upload_payload["job_id"]},
            headers=viewer_headers,
        )

    expect_error_code(plan_response, "WORKSPACE_FORBIDDEN", status_code=403)


def test_ingestion_plan_ignores_disabled_feature_flag(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path, ingestion_enabled=False)

    with TestClient(app) as client:
        owner_headers = auth_headers(client, user_id="alice", project_id="north", role="admin")
        workspace_id = _create_workspace(client, owner_headers, name="Plan Flag Workspace")

        response = client.post(
            "/ingestion/plan",
            json={"workspace_id": workspace_id, "job_id": "job-demo"},
            headers=owner_headers,
        )

    expect_error_code(response, "INGESTION_JOB_NOT_FOUND", status_code=404)
