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
from apps.api.workspaces import clear_workspace_service_cache
from tests.auth_utils import auth_headers


def _set_minimal_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'workspace-state.db'}")
    monkeypatch.setenv("MODEL_PROVIDER_URL", "http://localhost:11434")
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("AGENT_MAX_SQL_ROWS", "5")
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


def test_publish_flow_writes_snapshot_files_and_redacts_sensitive_columns(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        headers = auth_headers(client, user_id="alice", project_id="north", role="viewer", clearance=1)
        workspace_response = client.post("/workspaces", json={"name": "Publish Flow"}, headers=headers)
        workspace_response.raise_for_status()
        workspace_id = workspace_response.json()["workspace_id"]

        publish_response = client.post(
            f"/workspaces/{workspace_id}/publish",
            headers=headers,
            json={
                "layout": {
                    "grid": {"columns": 2, "rows": [{"id": "row-1", "height": 320}]},
                    "zones": [{"id": "zone-1", "chart_id": "chart-1", "column": 0, "row": 0}],
                },
                "sidebar": [{"id": "overview", "label": "Overview", "anchorRowId": "row-1", "children": []}],
                "charts": [
                    {
                        "chart_id": "chart-1",
                        "title": "Sensitive Headcount",
                        "chart_type": "bar",
                        "spec": {"chart_type": "bar", "title": "Sensitive Headcount"},
                        "rows": [{"department": "HR", "headcount": 4, "salary": 100}],
                    }
                ],
            },
        )
        publish_response.raise_for_status()
        body = publish_response.json()
        assert body["is_active"] is True
        assert body["published_page_id"]
        token = body["token"]
        assert token
        assert body["public_url"].endswith(f"/p/{token}")

        # Public reads use the token only, with no auth headers.
        manifest_response = client.get(f"/public/pages/{token}/manifest")
        manifest_response.raise_for_status()
        manifest = manifest_response.json()["manifest"]
        assert manifest["charts"][0]["chart_id"] == "chart-1"

        data_response = client.get(f"/public/pages/{token}/charts/chart-1/data")
        data_response.raise_for_status()
        rows = data_response.json()["rows"]
        assert rows == [{"department": "HR", "headcount": 4}]
