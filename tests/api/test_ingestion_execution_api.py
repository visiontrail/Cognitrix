from __future__ import annotations

import sqlite3
from io import BytesIO
from pathlib import Path

import duckdb
import pandas as pd
from fastapi.testclient import TestClient

from apps.api.agentic_ingestion.runtime import WriteIngestionAgentRuntime
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
from tests.agentic_ingestion_fakes import install_mock_ingestion_agents
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
    install_mock_ingestion_agents(monkeypatch)

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


def _excel_bytes_with_numeric_timestamp() -> bytes:
    roster = pd.DataFrame(
        [
            {"Employee ID": "E-001", "Snapshot At": 45292},
            {"Employee ID": "E-002", "Snapshot At": 45293},
        ]
    )

    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        roster.to_excel(writer, index=False, sheet_name="Roster")
    return buffer.getvalue()


def _upload_file_payload(
    *,
    file_name: str = "roster.xlsx",
    file_bytes: bytes | None = None,
) -> list[tuple[str, tuple[str, bytes, str]]]:
    content = file_bytes if file_bytes is not None else _excel_bytes()
    return [
        (
            "files",
            (
                file_name,
                content,
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


def _prepare_approval_job(
    client: TestClient,
    headers: dict[str, str],
    *,
    workspace_id: str,
) -> tuple[str, str]:
    catalog_response = client.post(
        f"/workspaces/{workspace_id}/catalog",
        headers=headers,
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

    upload_payload = _create_upload(client, headers, workspace_id=workspace_id)
    job_id = upload_payload["job_id"]
    plan_response = client.post(
        "/ingestion/plan",
        json={
            "workspace_id": workspace_id,
            "job_id": job_id,
            "conversation_id": "conv-exec-1",
            "message": "请更新花名册",
        },
        headers=headers,
    )
    assert plan_response.status_code == 200
    plan_payload = plan_response.json()
    assert plan_payload["status"] == "awaiting_user_approval"
    return job_id, plan_payload["proposal_id"]


def test_ingestion_approve_and_execute_persist_receipt(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path, ingestion_enabled=True)

    with TestClient(app) as client:
        owner_headers = auth_headers(client, user_id="alice", project_id="north", role="admin")
        workspace_id = _create_workspace(client, owner_headers, name="Execution Workspace")
        job_id, proposal_id = _prepare_approval_job(client, owner_headers, workspace_id=workspace_id)

        approve_response = client.post(
            "/ingestion/approve",
            json={
                "workspace_id": workspace_id,
                "job_id": job_id,
                "proposal_id": proposal_id,
                "approved_action": "new_table",
            },
            headers=owner_headers,
        )
        assert approve_response.status_code == 200
        approve_payload = approve_response.json()
        assert approve_payload["status"] == "approved"
        assert approve_payload["target_table"].startswith("employee_roster_")
        assert approve_payload["dry_run_summary"]["predicted_affected_rows"] >= 0

        execute_response = client.post(
            "/ingestion/execute",
            json={
                "workspace_id": workspace_id,
                "job_id": job_id,
                "proposal_id": proposal_id,
            },
            headers=owner_headers,
        )

    assert execute_response.status_code == 200
    execute_payload = execute_response.json()
    assert execute_payload["status"] == "succeeded"
    assert execute_payload["execution_id"]
    assert execute_payload["receipt"]["success"] is True
    assert execute_payload["receipt"]["target_table"].startswith("employee_roster_")

    db_path = tmp_path / "workspace-state.db"
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        job_row = conn.execute(
            "SELECT status FROM ingestion_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        assert job_row is not None
        assert str(job_row["status"]) == "succeeded"

        execution_row = conn.execute(
            """
            SELECT status, execution_mode, execution_receipt
            FROM ingestion_executions
            WHERE id = ?
            """,
            (execute_payload["execution_id"],),
        ).fetchone()
        assert execution_row is not None
        assert str(execution_row["status"]) == "succeeded"
        assert str(execution_row["execution_mode"]) == "new_table"

        event_rows = conn.execute(
            "SELECT event_type FROM ingestion_events WHERE job_id = ?",
            (job_id,),
        ).fetchall()
        event_types = {str(item["event_type"]) for item in event_rows}
        assert "proposal_approved" in event_types
        assert "execution_succeeded" in event_types

    duckdb_path = Path(execute_payload["receipt"]["duckdb_path"])
    assert duckdb_path.exists()
    conn = duckdb.connect(str(duckdb_path))
    try:
        target_table = execute_payload["receipt"]["target_table"]
        count = int(conn.execute(f"SELECT COUNT(*) FROM {target_table}").fetchone()[0])
    finally:
        conn.close()
    assert count > 0


def test_execute_syncs_catalog_after_business_intent_import(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path, ingestion_enabled=True)

    with TestClient(app) as client:
        owner_headers = auth_headers(client, user_id="alice", project_id="north", role="admin")
        workspace_id = _create_workspace(client, owner_headers, name="Catalog Sync Workspace")

        catalog_response = client.post(
            f"/workspaces/{workspace_id}/catalog",
            headers=owner_headers,
            json={
                "table_name": "employee_roster",
                "human_label": "Employee Roster",
                "business_type": "roster",
                "description": "Stores employee master uploads.",
            },
        )
        assert catalog_response.status_code == 200

        upload_payload = _create_upload(client, owner_headers, workspace_id=workspace_id)
        plan_response = client.post(
            "/ingestion/plan",
            json={
                "workspace_id": workspace_id,
                "job_id": upload_payload["job_id"],
                "message": "导入花名册",
            },
            headers=owner_headers,
        )
        assert plan_response.status_code == 200
        plan_payload = plan_response.json()
        assert plan_payload["status"] == "awaiting_user_approval"

        approve_response = client.post(
            "/ingestion/approve",
            json={
                "workspace_id": workspace_id,
                "job_id": upload_payload["job_id"],
                "proposal_id": plan_payload["proposal_id"],
                "approved_action": "new_table",
            },
            headers=owner_headers,
        )
        assert approve_response.status_code == 200

        execute_response = client.post(
            "/ingestion/execute",
            json={
                "workspace_id": workspace_id,
                "job_id": upload_payload["job_id"],
                "proposal_id": plan_payload["proposal_id"],
            },
            headers=owner_headers,
        )

        assert execute_response.status_code == 200
        execute_payload = execute_response.json()
        assert execute_payload["receipt"]["inserted_rows"] > 0
        assert execute_payload["receipt"]["affected_rows"] > 0

        catalog_list_response = client.get(
            f"/workspaces/{workspace_id}/catalog",
            headers=owner_headers,
        )
        assert catalog_list_response.status_code == 200
        catalog_entry = catalog_list_response.json()["entries"][0]
        preview_response = client.get(
            f"/workspaces/{workspace_id}/catalog/{catalog_entry['id']}/data",
            headers=owner_headers,
        )
        assert preview_response.status_code == 200
        preview_payload = preview_response.json()
        assert preview_payload["row_count"] > 0
        assert preview_payload["table"] == execute_payload["receipt"]["target_table"]

    db_path = tmp_path / "workspace-state.db"
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        catalog_row = conn.execute(
            """
            SELECT table_name, business_type, write_mode, is_active_target
            FROM table_catalog
            WHERE workspace_id = ? AND id = ?
            """,
            (workspace_id, catalog_entry["id"]),
        ).fetchone()
        assert catalog_row is not None
        assert str(catalog_row["table_name"]) == execute_payload["receipt"]["target_table"]
        assert str(catalog_row["business_type"]) == "roster"
        assert str(catalog_row["write_mode"]) == "new_table"
        assert int(catalog_row["is_active_target"]) == 1


def test_ingestion_execute_handles_numeric_timestamp_values(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path, ingestion_enabled=True)

    with TestClient(app) as client:
        owner_headers = auth_headers(client, user_id="alice", project_id="north", role="admin")
        workspace_id = _create_workspace(client, owner_headers, name="Execution Timestamp Workspace")
        catalog_response = client.post(
            f"/workspaces/{workspace_id}/catalog",
            headers=owner_headers,
            json={
                "table_name": "employee_roster_ts",
                "human_label": "Employee Roster Timestamp",
                "business_type": "roster",
                "write_mode": "update_existing",
                "time_grain": "none",
                "primary_keys": ["employee_id"],
                "match_columns": ["employee_id"],
                "is_active_target": True,
                "description": "Timestamp casting regression guard",
            },
        )
        assert catalog_response.status_code == 200

        runtime = WriteIngestionAgentRuntime()
        duckdb_path = runtime._workspace_duckdb_path(workspace_id=workspace_id)  # noqa: SLF001
        duckdb_path.parent.mkdir(parents=True, exist_ok=True)
        conn = duckdb.connect(str(duckdb_path))
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS employee_roster_ts (
                    employee_id VARCHAR,
                    snapshot_at TIMESTAMP
                )
                """
            )
        finally:
            conn.close()

        upload_response = client.post(
            "/ingestion/uploads",
            data={"workspace_id": workspace_id},
            headers=owner_headers,
            files=_upload_file_payload(
                file_name="roster_timestamp.xlsx",
                file_bytes=_excel_bytes_with_numeric_timestamp(),
            ),
        )
        assert upload_response.status_code == 200
        upload_payload = upload_response.json()
        job_id = upload_payload["job_id"]

        plan_response = client.post(
            "/ingestion/plan",
            json={
                "workspace_id": workspace_id,
                "job_id": job_id,
                "conversation_id": "conv-exec-ts",
                "message": "请更新花名册并写入时间戳",
            },
            headers=owner_headers,
        )
        assert plan_response.status_code == 200
        plan_payload = plan_response.json()
        assert plan_payload["status"] == "awaiting_user_approval"

        approve_response = client.post(
            "/ingestion/approve",
            json={
                "workspace_id": workspace_id,
                "job_id": job_id,
                "proposal_id": plan_payload["proposal_id"],
                "approved_action": "update_existing",
            },
            headers=owner_headers,
        )
        assert approve_response.status_code == 200

        execute_response = client.post(
            "/ingestion/execute",
            json={
                "workspace_id": workspace_id,
                "job_id": job_id,
                "proposal_id": plan_payload["proposal_id"],
            },
            headers=owner_headers,
        )
        assert execute_response.status_code == 200

    conn = duckdb.connect(str(duckdb_path))
    try:
        row_count, non_null_snapshot_count = conn.execute(
            "SELECT COUNT(*), COUNT(snapshot_at) FROM employee_roster_ts"
        ).fetchone()
    finally:
        conn.close()
    assert int(row_count) > 0
    assert int(non_null_snapshot_count) > 0


def test_ingestion_execute_requires_approval(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path, ingestion_enabled=True)

    with TestClient(app) as client:
        owner_headers = auth_headers(client, user_id="alice", project_id="north", role="admin")
        workspace_id = _create_workspace(client, owner_headers, name="Execution Guard Workspace")
        job_id, proposal_id = _prepare_approval_job(client, owner_headers, workspace_id=workspace_id)

        execute_response = client.post(
            "/ingestion/execute",
            json={
                "workspace_id": workspace_id,
                "job_id": job_id,
                "proposal_id": proposal_id,
            },
            headers=owner_headers,
        )

    expect_error_code(execute_response, "INGESTION_EXECUTION_NOT_ALLOWED", status_code=409)


def test_ingestion_approve_workspace_role_guard(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path, ingestion_enabled=True)

    with TestClient(app) as client:
        owner_headers = auth_headers(client, user_id="alice", project_id="north", role="admin")
        viewer_headers = auth_headers(client, user_id="bob", project_id="north", role="hr")
        workspace_id = _create_workspace(client, owner_headers, name="Execution Role Guard")
        add_member_response = client.post(
            f"/workspaces/{workspace_id}/members",
            headers=owner_headers,
            json={"user_id": "bob", "role": "viewer", "display_name": "Bob Viewer"},
        )
        # Viewer membership is no longer a valid role; bob stays a non-member.
        assert add_member_response.status_code == 422

        job_id, proposal_id = _prepare_approval_job(client, owner_headers, workspace_id=workspace_id)
        approve_response = client.post(
            "/ingestion/approve",
            json={
                "workspace_id": workspace_id,
                "job_id": job_id,
                "proposal_id": proposal_id,
                "approved_action": "update_existing",
            },
            headers=viewer_headers,
        )

    expect_error_code(approve_response, "WORKSPACE_FORBIDDEN", status_code=403)


def test_ingestion_approve_ignores_disabled_feature_flag(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path, ingestion_enabled=False)

    with TestClient(app) as client:
        owner_headers = auth_headers(client, user_id="alice", project_id="north", role="admin")
        workspace_id = _create_workspace(client, owner_headers, name="Execution Flag Guard")
        response = client.post(
            "/ingestion/approve",
            json={
                "workspace_id": workspace_id,
                "job_id": "job-demo",
                "proposal_id": "proposal-demo",
                "approved_action": "update_existing",
            },
            headers=owner_headers,
        )

    expect_error_code(response, "INGESTION_JOB_NOT_FOUND", status_code=404)
