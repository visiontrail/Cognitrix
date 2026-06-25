from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.audit import clear_audit_logger_cache
from apps.api.auth import clear_auth_cache
from apps.api.chat import clear_chat_stream_service_cache
from apps.api.config import get_settings
from apps.api.datasets import clear_dataset_service_cache
from apps.api.main import app
from apps.api.published_pages import clear_published_page_store_cache
from apps.api.semantic import clear_semantic_cache
from apps.api.tool_calling import clear_tool_calling_service_cache
from apps.api.views import clear_view_storage_service_cache
from apps.api.workspaces import clear_workspace_service_cache, get_workspace_service
from tests.auth_utils import auth_headers


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
    clear_published_page_store_cache()


def test_legacy_viewer_member_is_neutralized_on_startup(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        owner_headers = auth_headers(client, user_id="alice", project_id="north", role="admin", clearance=9)
        workspace_id = client.post(
            "/workspaces", json={"name": "Legacy"}, headers=owner_headers
        ).json()["workspace_id"]

        # Add bob as a legitimate editor first (ensures the user row exists),
        # then rewrite the row to the legacy 'viewer' role to simulate old state.
        client.post(
            f"/workspaces/{workspace_id}/members",
            headers=owner_headers,
            json={"user_id": "bob", "role": "editor"},
        )
        service = get_workspace_service()
        conn = service._connect()
        try:
            conn.execute(
                "UPDATE workspace_members SET role = 'viewer' WHERE workspace_id = ? AND user_id = ?",
                (workspace_id, "bob"),
            )
            conn.commit()
        finally:
            conn.close()

        # Re-run the schema migration (idempotent) to neutralize the viewer row.
        clear_workspace_service_cache()
        service = get_workspace_service()

        conn = service._connect()
        try:
            row = conn.execute(
                "SELECT role FROM workspace_members WHERE workspace_id = ? AND user_id = ?",
                (workspace_id, "bob"),
            ).fetchone()
        finally:
            conn.close()

        # The viewer row must be removed, not upgraded to editor.
        assert row is None

        # bob therefore has no workspace access.
        bob_headers = auth_headers(client, user_id="bob", project_id="north", role="hr", clearance=1)
        assert client.get(f"/workspaces/{workspace_id}", headers=bob_headers).status_code == 403
