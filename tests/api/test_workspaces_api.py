from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.audit import clear_audit_logger_cache
from apps.api.auth import clear_auth_cache
from apps.api.chat import clear_chat_stream_service_cache
from apps.api.config import get_settings
from apps.api.datasets import clear_dataset_service_cache
from apps.api.main import app
from apps.api.semantic import clear_semantic_cache
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


def test_create_and_list_workspaces(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        owner_headers = auth_headers(client, user_id="alice", project_id="north", role="hr", clearance=5)

        create_response = client.post(
            "/workspaces",
            json={"name": "North Team Workspace"},
            headers=owner_headers,
        )
        assert create_response.status_code == 200
        created = create_response.json()
        assert created["name"] == "North Team Workspace"
        assert created["role"] == "owner"

        list_response = client.get("/workspaces", headers=owner_headers)
        assert list_response.status_code == 200
        listed = list_response.json()
        assert listed["count"] == 1
        assert listed["workspaces"][0]["workspace_id"] == created["workspace_id"]

        members_response = client.get(
            f"/workspaces/{created['workspace_id']}/members",
            headers=owner_headers,
        )
        assert members_response.status_code == 200
        members_payload = members_response.json()
        assert members_payload["count"] == 1
        assert members_payload["members"][0]["user_id"] == "alice"
        assert members_payload["members"][0]["role"] == "owner"


def test_non_member_cannot_access_workspace_resources(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        owner_headers = auth_headers(client, user_id="alice", project_id="north", role="admin", clearance=9)
        outsider_headers = auth_headers(client, user_id="bob", project_id="north", role="pm", clearance=5)

        create_response = client.post(
            "/workspaces",
            json={"name": "Restricted Workspace"},
            headers=owner_headers,
        )
        assert create_response.status_code == 200
        workspace_id = create_response.json()["workspace_id"]

        workspace_response = client.get(f"/workspaces/{workspace_id}", headers=outsider_headers)
        expect_error_code(workspace_response, "WORKSPACE_FORBIDDEN", status_code=403)

        chat_response = client.post(
            "/chat/stream",
            headers=outsider_headers,
            json={
                "user_id": "bob",
                "project_id": "north",
                "workspace_id": workspace_id,
                "dataset_table": "employees_wide",
                "message": "hello",
            },
        )
        expect_error_code(chat_response, "WORKSPACE_FORBIDDEN", status_code=403)


def test_owner_can_add_member_and_member_can_bind_chat_workspace(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        owner_headers = auth_headers(client, user_id="alice", project_id="north", role="admin", clearance=9)
        member_headers = auth_headers(client, user_id="bob", project_id="north", role="viewer", clearance=1)

        create_response = client.post(
            "/workspaces",
            json={"name": "Shared Workspace"},
            headers=owner_headers,
        )
        assert create_response.status_code == 200
        workspace_id = create_response.json()["workspace_id"]

        add_member_response = client.post(
            f"/workspaces/{workspace_id}/members",
            headers=owner_headers,
            json={"user_id": "bob", "role": "viewer", "display_name": "Bob Viewer"},
        )
        assert add_member_response.status_code == 200
        assert add_member_response.json()["role"] == "viewer"

        member_workspace_response = client.get(f"/workspaces/{workspace_id}", headers=member_headers)
        assert member_workspace_response.status_code == 200
        assert member_workspace_response.json()["workspace_id"] == workspace_id

        chat_response = client.post(
            "/chat/stream",
            headers=member_headers,
            json={
                "user_id": "bob",
                "project_id": "north",
                "workspace_id": workspace_id,
                "dataset_table": "employees_wide",
                "message": None,
            },
        )
        assert chat_response.status_code == 200
        assert "text/event-stream" in chat_response.headers.get("content-type", "")


def test_viewer_cannot_manage_workspace_members(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        owner_headers = auth_headers(client, user_id="alice", project_id="north", role="admin", clearance=9)
        viewer_headers = auth_headers(client, user_id="bob", project_id="north", role="viewer", clearance=1)

        create_response = client.post(
            "/workspaces",
            json={"name": "Role Guard Workspace"},
            headers=owner_headers,
        )
        assert create_response.status_code == 200
        workspace_id = create_response.json()["workspace_id"]

        owner_add_viewer = client.post(
            f"/workspaces/{workspace_id}/members",
            headers=owner_headers,
            json={"user_id": "bob", "role": "viewer"},
        )
        assert owner_add_viewer.status_code == 200

        viewer_add_member = client.post(
            f"/workspaces/{workspace_id}/members",
            headers=viewer_headers,
            json={"user_id": "carol", "role": "viewer"},
        )
        expect_error_code(viewer_add_member, "WORKSPACE_FORBIDDEN", status_code=403)


def test_delete_workspace_cascade(monkeypatch, tmp_path: Path) -> None:
    """DELETE /workspaces/{id} must hard-delete the workspace and every row
    in dependent ingestion + catalog tables, plus clean up DuckDB / upload
    files on disk."""
    _set_minimal_env(monkeypatch, tmp_path)

    import sqlite3 as _sqlite
    from apps.api.workspaces import get_workspace_service

    with TestClient(app) as client:
        owner_headers = auth_headers(client, user_id="alice", project_id="north", role="admin", clearance=9)

        create_response = client.post(
            "/workspaces",
            json={"name": "Cascade Workspace"},
            headers=owner_headers,
        )
        assert create_response.status_code == 200
        workspace_id = create_response.json()["workspace_id"]

        # ai_views tables are created lazily by ViewStorageService — materialise
        # them BEFORE we open our own connection so the bootstrap doesn't collide
        # with our held lock.
        from apps.api.views import get_view_storage_service as _get_view_storage_service
        _get_view_storage_service()

        # Seed every workspace-keyed table with at least one row, plus the
        # filesystem artifacts (DuckDB file + uploads directory) the cascade
        # should reap.
        service = get_workspace_service()
        with service._connect() as conn:  # noqa: SLF001
            conn.execute(
                "INSERT INTO table_catalog (id, workspace_id, table_name, human_label, business_type, "
                "write_mode, time_grain, primary_keys, match_columns, is_active_target, description, "
                "created_by, updated_by) VALUES ('cat-1', ?, 'employees', 'Employees', 'roster', "
                "'new_table', 'none', '[]', '[]', 1, '', 'alice', 'alice')",
                (workspace_id,),
            )
            conn.execute(
                "INSERT INTO table_column_metadata (workspace_id, table_name, column_name, ordinal_position) "
                "VALUES (?, 'employees', 'employee_id', 1)",
                (workspace_id,),
            )
            conn.execute(
                "INSERT INTO ingestion_uploads (id, workspace_id, uploaded_by, file_name, storage_path, "
                "size_bytes, file_hash) VALUES ('up-1', ?, 'alice', 'f.xlsx', '/tmp/f.xlsx', 0, 'h')",
                (workspace_id,),
            )
            conn.execute(
                "INSERT INTO ingestion_jobs (id, workspace_id, upload_id, created_by, status) "
                "VALUES ('job-1', ?, 'up-1', 'alice', 'awaiting_user_approval')",
                (workspace_id,),
            )
            conn.execute(
                "INSERT INTO ingestion_proposals (id, job_id, workspace_id, proposal_version, "
                "proposal_json, recommended_action) VALUES ('prop-1', 'job-1', ?, 1, '{}', 'update_existing')",
                (workspace_id,),
            )
            conn.execute(
                "INSERT INTO ingestion_executions (id, job_id, proposal_id, workspace_id, executed_by, "
                "execution_mode, validated_sql, status) VALUES ('exec-1', 'job-1', 'prop-1', ?, 'alice', "
                "'update_existing', 'MERGE ...', 'succeeded')",
                (workspace_id,),
            )
            conn.execute(
                "INSERT INTO ingestion_events (id, job_id, event_type, payload) "
                "VALUES ('evt-1', 'job-1', 'planning', '{}')",
            )
            # Saved view scoped to this workspace + its version history row.
            conn.execute(
                "INSERT INTO ai_views (view_id, owner_user_id, owner_project_id, workspace_id, "
                "dataset_table, title, rbac_scope, ai_state, current_version, created_at, updated_at) "
                "VALUES ('view-1', 'alice', 'north', ?, 'employees', 'My Saved View', '{}', '{}', 1, "
                "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
                (workspace_id,),
            )
            conn.execute(
                "INSERT INTO ai_view_versions (view_id, version, ai_state, metadata, created_by, created_at) "
                "VALUES ('view-1', 1, '{}', '{}', 'alice', '2026-01-01T00:00:00Z')",
            )
            conn.commit()

        # Create the per-workspace filesystem artefacts the deletion should reap.
        upload_dir = tmp_path / "uploads"
        duckdb_dir = upload_dir / "agentic_ingestion" / "duckdb"
        duckdb_dir.mkdir(parents=True, exist_ok=True)
        duckdb_file = duckdb_dir / f"{workspace_id}.duckdb"
        duckdb_file.write_bytes(b"fake-duckdb")
        uploads_root = upload_dir / "agentic_ingestion" / "raw" / workspace_id / "up-1"
        uploads_root.mkdir(parents=True, exist_ok=True)
        (uploads_root / "f.xlsx").write_bytes(b"fake-excel")

        # Seed an agent_sessions row tied to this workspace in the OTHER sqlite
        # file (state/agent_sessions.sqlite3). The cascade must reach across.
        agent_sessions_path = upload_dir / "state" / "agent_sessions.sqlite3"
        agent_sessions_path.parent.mkdir(parents=True, exist_ok=True)
        _ac = __import__("sqlite3").connect(agent_sessions_path)
        try:
            _ac.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_sessions (
                    conversation_id TEXT PRIMARY KEY,
                    agent_session_id TEXT NOT NULL,
                    workspace_id TEXT,
                    state_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            _ac.execute(
                "INSERT INTO agent_sessions VALUES "
                "('conv-1', 'agent-1', ?, '{}', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
                (workspace_id,),
            )
            # An unrelated session belonging to another workspace must survive.
            _ac.execute(
                "INSERT INTO agent_sessions VALUES "
                "('conv-other', 'agent-other', 'other-workspace', '{}', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
            )
            _ac.commit()
        finally:
            _ac.close()

        # No confirmation provided — backward compat path still deletes.
        delete_response = client.request(
            "DELETE",
            f"/workspaces/{workspace_id}",
            headers=owner_headers,
        )
        assert delete_response.status_code == 200, delete_response.text
        body = delete_response.json()
        assert body["status"] == "deleted"
        counts = body["deleted_counts"]
        # Every cascaded table must report exactly the rows we seeded.
        assert counts["ingestion_executions"] == 1
        assert counts["ingestion_proposals"] == 1
        assert counts["ingestion_events"] == 1
        assert counts["ingestion_jobs"] == 1
        assert counts["ingestion_uploads"] == 1
        assert counts["table_column_metadata"] == 1
        assert counts["table_catalog"] == 1
        assert counts["ai_view_versions"] == 1
        assert counts["ai_views"] == 1
        assert counts["workspace_members"] == 1
        assert counts["workspaces"] == 1
        assert counts.get("agent_sessions") == 1

        # SQL state: no row of the deleted workspace_id remains anywhere.
        with service._connect() as conn:  # noqa: SLF001
            assert conn.execute("SELECT COUNT(*) FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM table_catalog WHERE workspace_id = ?", (workspace_id,)).fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM ingestion_jobs WHERE workspace_id = ?", (workspace_id,)).fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM ingestion_events").fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM ai_views WHERE workspace_id = ?", (workspace_id,)).fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM ai_view_versions WHERE view_id = 'view-1'").fetchone()[0] == 0

        # agent_sessions cross-database: the deleted workspace's session is
        # gone, the unrelated workspace's session survives.
        _ac = __import__("sqlite3").connect(agent_sessions_path)
        try:
            assert _ac.execute(
                "SELECT COUNT(*) FROM agent_sessions WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchone()[0] == 0
            assert _ac.execute(
                "SELECT COUNT(*) FROM agent_sessions WHERE workspace_id = ?",
                ("other-workspace",),
            ).fetchone()[0] == 1
        finally:
            _ac.close()

        # Filesystem state.
        assert not duckdb_file.exists()
        assert not (upload_dir / "agentic_ingestion" / "raw" / workspace_id).exists()

        # And the workspace is gone from the API listing.
        list_response = client.get("/workspaces", headers=owner_headers)
        assert list_response.status_code == 200
        assert list_response.json()["count"] == 0


def test_delete_workspace_confirm_name_mismatch_rejects(monkeypatch, tmp_path: Path) -> None:
    """Typed-confirmation guardrail: when a wrong name is supplied, the
    delete must be rejected with WORKSPACE_DELETE_CONFIRM_MISMATCH and
    nothing on disk or in SQL is touched."""
    _set_minimal_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        owner_headers = auth_headers(client, user_id="alice", project_id="north", role="admin", clearance=9)
        create_response = client.post(
            "/workspaces",
            json={"name": "Guarded Workspace"},
            headers=owner_headers,
        )
        assert create_response.status_code == 200
        workspace_id = create_response.json()["workspace_id"]

        bad_confirm = client.request(
            "DELETE",
            f"/workspaces/{workspace_id}",
            headers=owner_headers,
            json={"confirm_workspace_name": "Not The Right Name"},
        )
        expect_error_code(bad_confirm, "WORKSPACE_DELETE_CONFIRM_MISMATCH", status_code=422)

        # Workspace still listed because nothing was deleted.
        listing = client.get("/workspaces", headers=owner_headers).json()
        assert listing["count"] == 1

        # Correct confirmation goes through.
        good_confirm = client.request(
            "DELETE",
            f"/workspaces/{workspace_id}",
            headers=owner_headers,
            json={"confirm_workspace_name": "Guarded Workspace"},
        )
        assert good_confirm.status_code == 200
        assert good_confirm.json()["status"] == "deleted"
