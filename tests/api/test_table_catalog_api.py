from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import duckdb
from fastapi.testclient import TestClient

from apps.api.audit import clear_audit_logger_cache
from apps.api.auth import clear_auth_cache
from apps.api.chat import clear_chat_stream_service_cache
from apps.api.config import get_settings
from apps.api.datasets import clear_dataset_service_cache
from apps.api.main import app
from apps.api import table_catalog
from apps.api.semantic import clear_semantic_cache
from apps.api.table_catalog import clear_table_catalog_service_cache
from apps.api.tool_calling import clear_tool_calling_service_cache
from apps.api.views import clear_view_storage_service_cache
from apps.api.workspaces import clear_workspace_service_cache
from tests.auth_utils import auth_headers, expect_error_code


def _set_minimal_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'workspace-state.db'}")
    monkeypatch.setenv("MODEL_PROVIDER_URL", "http://localhost:11434")
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
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


def test_table_catalog_crud_and_active_target(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        owner_headers = auth_headers(client, user_id="alice", project_id="north", role="admin", clearance=9)

        workspace_response = client.post(
            "/workspaces",
            json={"name": "Catalog Workspace"},
            headers=owner_headers,
        )
        assert workspace_response.status_code == 200
        workspace_id = workspace_response.json()["workspace_id"]

        first_create_response = client.post(
            f"/workspaces/{workspace_id}/catalog",
            headers=owner_headers,
            json={
                "table_name": "employees_roster",
                "human_label": "Employees Roster",
                "business_type": "roster",
                "write_mode": "update_existing",
                "time_grain": "none",
                "primary_keys": ["employee_id"],
                "match_columns": ["employee_id", "email"],
                "is_active_target": True,
                "description": "Primary roster table",
            },
        )
        assert first_create_response.status_code == 200
        first_entry = first_create_response.json()["entry"]
        assert first_entry["table_name"] == "employees_roster"
        assert first_entry["primary_keys"] == ["employee_id"]
        assert first_entry["is_active_target"] is True

        second_create_response = client.post(
            f"/workspaces/{workspace_id}/catalog",
            headers=owner_headers,
            json={
                "table_name": "employees_roster_2026",
                "human_label": "Employees Roster 2026",
                "business_type": "roster",
                "write_mode": "time_partitioned_new_table",
                "time_grain": "year",
                "primary_keys": ["employee_id"],
                "match_columns": ["employee_id"],
                "is_active_target": True,
                "description": "Yearly roster table",
            },
        )
        assert second_create_response.status_code == 200
        second_entry = second_create_response.json()["entry"]
        assert second_entry["is_active_target"] is True

        list_response = client.get(f"/workspaces/{workspace_id}/catalog", headers=owner_headers)
        assert list_response.status_code == 200
        listed_entries = {entry["id"]: entry for entry in list_response.json()["entries"]}
        assert list_response.json()["count"] == 2
        assert listed_entries[first_entry["id"]]["is_active_target"] is False
        assert listed_entries[second_entry["id"]]["is_active_target"] is True

        active_target_response = client.get(
            f"/workspaces/{workspace_id}/catalog/active-target",
            headers=owner_headers,
            params={"business_type": "roster"},
        )
        assert active_target_response.status_code == 200
        assert active_target_response.json()["entry"]["id"] == second_entry["id"]

        update_response = client.patch(
            f"/workspaces/{workspace_id}/catalog/{first_entry['id']}",
            headers=owner_headers,
            json={
                "human_label": "Employees Master",
                "is_active_target": True,
                "description": "Switched to master table",
            },
        )
        assert update_response.status_code == 200
        assert update_response.json()["entry"]["human_label"] == "Employees Master"
        assert update_response.json()["entry"]["is_active_target"] is True

        active_target_after_update = client.get(
            f"/workspaces/{workspace_id}/catalog/active-target",
            headers=owner_headers,
            params={"business_type": "roster"},
        )
        assert active_target_after_update.status_code == 200
        assert active_target_after_update.json()["entry"]["id"] == first_entry["id"]

        delete_response = client.delete(
            f"/workspaces/{workspace_id}/catalog/{second_entry['id']}",
            headers=owner_headers,
        )
        assert delete_response.status_code == 200
        assert delete_response.json()["status"] == "deleted"

        final_list_response = client.get(f"/workspaces/{workspace_id}/catalog", headers=owner_headers)
        assert final_list_response.status_code == 200
        assert final_list_response.json()["count"] == 1
        assert final_list_response.json()["entries"][0]["id"] == first_entry["id"]


def test_table_catalog_create_accepts_business_intent_only(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        owner_headers = auth_headers(client, user_id="alice", project_id="north", role="admin", clearance=9)

        workspace_response = client.post(
            "/workspaces",
            json={"name": "Intent Only Catalog"},
            headers=owner_headers,
        )
        assert workspace_response.status_code == 200
        workspace_id = workspace_response.json()["workspace_id"]

        create_response = client.post(
            f"/workspaces/{workspace_id}/catalog",
            headers=owner_headers,
            json={
                "table_name": "employee_master",
                "human_label": "Employee Master",
                "description": "Stores the employee master sheet used for workforce analysis.",
            },
        )
        assert create_response.status_code == 200
        entry = create_response.json()["entry"]
        assert entry["business_type"] == "other"
        assert entry["write_mode"] == "new_table"
        assert entry["primary_keys"] == []
        assert entry["match_columns"] == []
        assert entry["is_active_target"] is False
        assert entry["description"] == "Stores the employee master sheet used for workforce analysis."


def test_table_catalog_data_preview_reads_workspace_duckdb(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        owner_headers = auth_headers(client, user_id="alice", project_id="north", role="admin", clearance=9)

        workspace_response = client.post(
            "/workspaces",
            json={"name": "Data Preview Catalog"},
            headers=owner_headers,
        )
        assert workspace_response.status_code == 200
        workspace_id = workspace_response.json()["workspace_id"]

        create_response = client.post(
            f"/workspaces/{workspace_id}/catalog",
            headers=owner_headers,
            json={
                "table_name": "employee_master",
                "human_label": "Employee Master",
                "description": "Stores employee master rows.",
            },
        )
        assert create_response.status_code == 200
        catalog_id = create_response.json()["entry"]["id"]

        db_path = get_settings().upload_dir / "agentic_ingestion" / "duckdb" / f"{workspace_id}.duckdb"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = duckdb.connect(str(db_path))
        try:
            conn.execute(
                """
                CREATE TABLE employee_master (
                    employee_id VARCHAR,
                    employee_name VARCHAR,
                    department VARCHAR
                )
                """
            )
            conn.execute(
                "INSERT INTO employee_master VALUES ('E001', 'Ava Chen', 'HR'), ('E002', 'Noah Lin', 'R&D')"
            )
        finally:
            conn.close()

        preview_response = client.get(
            f"/workspaces/{workspace_id}/catalog/{catalog_id}/data",
            headers=owner_headers,
            params={"limit": 1, "offset": 1},
        )
        assert preview_response.status_code == 200
        payload = preview_response.json()
        assert payload["table"] == "employee_master"
        assert payload["row_count"] == 2
        assert payload["limit"] == 1
        assert payload["offset"] == 1
        assert payload["has_more"] is False
        assert [column["name"] for column in payload["columns"]] == [
            "employee_id",
            "employee_name",
            "department",
        ]
        assert payload["rows"] == [
            {
                "employee_id": "E002",
                "employee_name": "Noah Lin",
                "department": "R&D",
            }
        ]


def test_table_catalog_data_preview_resolves_recent_execution_table(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _set_minimal_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        owner_headers = auth_headers(client, user_id="alice", project_id="north", role="admin", clearance=9)

        workspace_response = client.post(
            "/workspaces",
            json={"name": "Recent Execution Preview Catalog"},
            headers=owner_headers,
        )
        assert workspace_response.status_code == 200
        workspace_id = workspace_response.json()["workspace_id"]

        create_response = client.post(
            f"/workspaces/{workspace_id}/catalog",
            headers=owner_headers,
            json={
                "table_name": "employee_master",
                "human_label": "Employee Master",
                "description": "Stores employee master rows.",
            },
        )
        assert create_response.status_code == 200
        catalog_id = create_response.json()["entry"]["id"]

        db_path = get_settings().upload_dir / "agentic_ingestion" / "duckdb" / f"{workspace_id}.duckdb"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = duckdb.connect(str(db_path))
        try:
            conn.execute(
                """
                CREATE TABLE employee_master_202605 (
                    employee_id VARCHAR,
                    employee_name VARCHAR
                )
                """
            )
            conn.execute("INSERT INTO employee_master_202605 VALUES ('E001', 'Ava Chen')")
        finally:
            conn.close()

        with sqlite3.connect(tmp_path / "workspace-state.db") as sqlite_conn:
            sqlite_conn.execute("PRAGMA foreign_keys = ON")
            sqlite_conn.execute(
                """
                INSERT INTO ingestion_uploads (
                    id, workspace_id, uploaded_by, file_name, storage_path, size_bytes, file_hash
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                ("upload-1", workspace_id, "alice", "employees.csv", "/tmp/employees.csv", 1, "hash-1"),
            )
            sqlite_conn.execute(
                """
                INSERT INTO ingestion_jobs (
                    id, workspace_id, upload_id, created_by, status
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                ("job-1", workspace_id, "upload-1", "alice", "succeeded"),
            )
            sqlite_conn.execute(
                """
                INSERT INTO ingestion_proposals (
                    id,
                    job_id,
                    workspace_id,
                    proposal_version,
                    proposal_json,
                    recommended_action,
                    target_table
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "proposal-1",
                    "job-1",
                    workspace_id,
                    1,
                    json.dumps({"target_table": "employee_master"}),
                    "new_table",
                    "employee_master",
                ),
            )
            sqlite_conn.execute(
                """
                INSERT INTO ingestion_executions (
                    id,
                    job_id,
                    proposal_id,
                    workspace_id,
                    executed_by,
                    execution_mode,
                    validated_sql,
                    execution_receipt,
                    status,
                    finished_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    "execution-1",
                    "job-1",
                    "proposal-1",
                    workspace_id,
                    "alice",
                    "execute",
                    "",
                    json.dumps({"target_table": "employee_master_202605"}),
                    "succeeded",
                ),
            )

        preview_response = client.get(
            f"/workspaces/{workspace_id}/catalog/{catalog_id}/data",
            headers=owner_headers,
            params={"limit": 1, "offset": 0},
        )
        assert preview_response.status_code == 200
        payload = preview_response.json()
        assert payload["table"] == "employee_master_202605"
        assert payload["row_count"] == 1
        assert payload["rows"] == [{"employee_id": "E001", "employee_name": "Ava Chen"}]


def test_table_catalog_create_generates_missing_table_name_with_ai(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path)
    monkeypatch.setenv("AI_API_KEY", "test-ai-key")
    monkeypatch.setenv("AI_MODEL", "test-model")
    get_settings.cache_clear()

    observed_payloads: list[dict[str, object]] = []

    def fake_ai_request(**kwargs) -> dict[str, object]:  # type: ignore[no-untyped-def]
        observed_payloads.append(kwargs["payload"])
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"table_name":"employee_master_snapshot"}',
                    },
                },
            ],
        }

    monkeypatch.setattr(table_catalog, "_post_table_name_ai_request", fake_ai_request)

    with TestClient(app) as client:
        owner_headers = auth_headers(client, user_id="alice", project_id="north", role="admin", clearance=9)

        workspace_response = client.post(
            "/workspaces",
            json={"name": "AI Named Catalog"},
            headers=owner_headers,
        )
        assert workspace_response.status_code == 200
        workspace_id = workspace_response.json()["workspace_id"]

        create_response = client.post(
            f"/workspaces/{workspace_id}/catalog",
            headers=owner_headers,
            json={
                "human_label": "员工主数据",
                "description": "存放员工主数据，用于人数、组织、职级等分析。",
            },
        )
        assert create_response.status_code == 200
        entry = create_response.json()["entry"]
        assert entry["table_name"] == "employee_master_snapshot"
        assert observed_payloads
        user_message = observed_payloads[0]["messages"][1]["content"]  # type: ignore[index]
        assert "员工主数据" in str(user_message)
        assert "职级" in str(user_message)


def test_table_catalog_workspace_role_checks(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        owner_headers = auth_headers(client, user_id="alice", project_id="north", role="admin", clearance=9)
        viewer_headers = auth_headers(client, user_id="bob", project_id="north", role="hr", clearance=5)
        outsider_headers = auth_headers(client, user_id="charlie", project_id="north", role="hr", clearance=5)

        workspace_response = client.post(
            "/workspaces",
            json={"name": "Role Guard Catalog"},
            headers=owner_headers,
        )
        assert workspace_response.status_code == 200
        workspace_id = workspace_response.json()["workspace_id"]

        add_member_response = client.post(
            f"/workspaces/{workspace_id}/members",
            headers=owner_headers,
            json={"user_id": "bob", "role": "viewer", "display_name": "Bob Viewer"},
        )
        assert add_member_response.status_code == 200

        viewer_create_response = client.post(
            f"/workspaces/{workspace_id}/catalog",
            headers=viewer_headers,
            json={
                "table_name": "attendance_daily",
                "human_label": "Attendance Daily",
                "business_type": "attendance",
                "write_mode": "append_only",
                "time_grain": "month",
            },
        )
        expect_error_code(viewer_create_response, "WORKSPACE_FORBIDDEN", status_code=403)

        viewer_list_response = client.get(f"/workspaces/{workspace_id}/catalog", headers=viewer_headers)
        assert viewer_list_response.status_code == 200
        assert viewer_list_response.json()["count"] == 0

        outsider_list_response = client.get(f"/workspaces/{workspace_id}/catalog", headers=outsider_headers)
        expect_error_code(outsider_list_response, "WORKSPACE_FORBIDDEN", status_code=403)


def test_table_catalog_delete_requires_workspace_admin(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        owner_headers = auth_headers(client, user_id="alice", project_id="north", role="admin", clearance=9)
        editor_headers = auth_headers(client, user_id="dora", project_id="north", role="hr", clearance=5)

        workspace_response = client.post(
            "/workspaces",
            json={"name": "Catalog Delete Guard"},
            headers=owner_headers,
        )
        assert workspace_response.status_code == 200
        workspace_id = workspace_response.json()["workspace_id"]

        add_editor_response = client.post(
            f"/workspaces/{workspace_id}/members",
            headers=owner_headers,
            json={"user_id": "dora", "role": "editor", "display_name": "Dora Editor"},
        )
        assert add_editor_response.status_code == 200

        create_response = client.post(
            f"/workspaces/{workspace_id}/catalog",
            headers=owner_headers,
            json={
                "table_name": "project_progress_monthly",
                "human_label": "Project Progress Monthly",
                "business_type": "project_progress",
                "write_mode": "append_only",
                "time_grain": "month",
            },
        )
        assert create_response.status_code == 200
        catalog_id = create_response.json()["entry"]["id"]

        editor_delete_response = client.delete(
            f"/workspaces/{workspace_id}/catalog/{catalog_id}",
            headers=editor_headers,
        )
        expect_error_code(editor_delete_response, "WORKSPACE_FORBIDDEN", status_code=403)
