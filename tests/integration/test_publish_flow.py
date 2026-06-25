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
        assert manifest["schema_version"] == 2
        assert manifest["canvas"]["format_id"] == "web-design"
        assert manifest["canvas"]["kind"] == "web_page"
        assert manifest["charts"][0]["chart_id"] == "chart-1"
        assert "spec_path" not in manifest["charts"][0]
        assert "data_path" not in manifest["charts"][0]

        data_response = client.get(f"/public/pages/{token}/charts/chart-1/data")
        data_response.raise_for_status()
        rows = data_response.json()["rows"]
        assert rows == [{"department": "HR", "headcount": 4}]


def test_publish_flow_supports_free_and_fixed_canvas_modes(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        headers = auth_headers(client, user_id="alice", project_id="north", role="viewer", clearance=1)
        workspace_response = client.post("/workspaces", json={"name": "Canvas Modes"}, headers=headers)
        workspace_response.raise_for_status()
        workspace_id = workspace_response.json()["workspace_id"]

        free_response = client.post(
            f"/workspaces/{workspace_id}/publish",
            headers=headers,
            json={
                "canvas_format": {"id": "infinite"},
                "viewport": {"x": -100, "y": -80, "zoom": 0.8},
                "nodes": [
                    {
                        "id": "chart-node",
                        "type": "chartNode",
                        "position": {"x": 40, "y": 60},
                        "width": 420,
                        "height": 280,
                        "data": {
                            "type": "chart",
                            "assetId": "chart-free",
                            "title": "Free Chart",
                            "chartType": "bar",
                            "spec": {"should": "be stripped"},
                            "width": 420,
                            "height": 280,
                        },
                    },
                    {
                        "id": "text-node",
                        "type": "textNode",
                        "position": {"x": -20, "y": 20},
                        "width": 240,
                        "height": 120,
                        "data": {"type": "text", "content": "Snapshot note", "width": 240, "height": 120},
                    },
                ],
                "edges": [{"id": "edge-1", "source": "text-node", "target": "chart-node"}],
                "charts": [
                    {
                        "chart_id": "chart-free",
                        "title": "Free Chart",
                        "chart_type": "bar",
                        "spec": {"chart_type": "bar", "title": "Free Chart"},
                        "rows": [{"department": "HR", "headcount": 4}],
                    }
                ],
            },
        )
        free_response.raise_for_status()
        free_body = free_response.json()
        token = free_body["token"]
        assert free_body["canvas_format_id"] == "infinite"
        assert free_body["canvas_kind"] == "free_layout"

        free_manifest_response = client.get(f"/public/pages/{token}/manifest")
        free_manifest_response.raise_for_status()
        free_manifest = free_manifest_response.json()["manifest"]
        assert free_manifest["canvas"]["kind"] == "free_layout"
        assert free_manifest["canvas"]["bounds"]["width"] >= 480
        assert free_manifest["content"]["nodes"][0]["data"] == {
            "type": "chart",
            "assetId": "chart-free",
            "title": "Free Chart",
            "chartType": "bar",
            "width": 420,
            "height": 280,
        }
        assert free_manifest["content"]["edges"][0]["source"] == "text-node"

        fixed_response = client.post(
            f"/workspaces/{workspace_id}/publish",
            headers=headers,
            json={
                "canvas_format": {"id": "a4-portrait"},
                "viewport": {"x": 999, "y": 999, "zoom": 9},
                "nodes": [
                    {
                        "id": "fixed-note",
                        "type": "textNode",
                        "position": {"x": 20, "y": 30},
                        "width": 240,
                        "height": 120,
                        "data": {"type": "text", "content": "On page", "width": 240, "height": 120},
                    }
                ],
                "edges": [],
                "charts": [],
            },
        )
        fixed_response.raise_for_status()
        fixed_body = fixed_response.json()
        # Each canvas kind owns an independent public link: publishing the
        # fixed-size canvas must not overwrite the free-layout publication.
        fixed_token = fixed_body["token"]
        assert fixed_token != token
        assert fixed_body["canvas_format_id"] == "a4-portrait"
        assert fixed_body["canvas_kind"] == "fixed_size"

        # The free-layout link is still live and still serves its own manifest.
        free_still_live = client.get(f"/public/pages/{token}/manifest")
        free_still_live.raise_for_status()
        assert free_still_live.json()["manifest"]["canvas"]["kind"] == "free_layout"

        fixed_manifest_response = client.get(f"/public/pages/{fixed_token}/manifest")
        fixed_manifest_response.raise_for_status()
        fixed_manifest = fixed_manifest_response.json()["manifest"]
        assert fixed_manifest["canvas"]["kind"] == "fixed_size"
        assert fixed_manifest["canvas"]["page"] == {
            "preset_id": "a4-portrait",
            "width": 794,
            "height": 1123,
        }
        assert fixed_manifest["canvas"]["viewport"] == {"x": 999.0, "y": 999.0, "zoom": 9.0}


def test_publish_creates_independent_links_per_canvas_kind(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        headers = auth_headers(client, user_id="alice", project_id="north", role="viewer", clearance=1)
        workspace_response = client.post("/workspaces", json={"name": "Independent Links"}, headers=headers)
        workspace_response.raise_for_status()
        workspace_id = workspace_response.json()["workspace_id"]

        web_response = client.post(
            f"/workspaces/{workspace_id}/publish",
            headers=headers,
            json={
                "canvas_format": {"id": "web-design"},
                "web_design": {
                    "layout": {
                        "grid": {"columns": 1, "rows": [{"id": "row-1", "height": 240}]},
                        "zones": [],
                    },
                    "sidebar": [],
                },
                "charts": [],
            },
        )
        web_response.raise_for_status()
        web_token = web_response.json()["token"]
        assert web_response.json()["canvas_kind"] == "web_page"

        fixed_response = client.post(
            f"/workspaces/{workspace_id}/publish",
            headers=headers,
            json={"canvas_format": {"id": "a4-portrait"}, "nodes": [], "edges": [], "charts": []},
        )
        fixed_response.raise_for_status()
        fixed_token = fixed_response.json()["token"]
        assert fixed_response.json()["canvas_kind"] == "fixed_size"

        infinite_response = client.post(
            f"/workspaces/{workspace_id}/publish",
            headers=headers,
            json={"canvas_format": {"id": "infinite"}, "nodes": [], "edges": [], "charts": []},
        )
        infinite_response.raise_for_status()
        free_token = infinite_response.json()["token"]
        assert infinite_response.json()["canvas_kind"] == "free_layout"

        # Three distinct canvas kinds → three distinct, simultaneously-live links.
        assert len({web_token, fixed_token, free_token}) == 3
        for token, expected_kind, expected_format in (
            (web_token, "web_page", "web-design"),
            (fixed_token, "fixed_size", "a4-portrait"),
            (free_token, "free_layout", "infinite"),
        ):
            manifest_response = client.get(f"/public/pages/{token}/manifest")
            manifest_response.raise_for_status()
            manifest = manifest_response.json()["manifest"]
            assert manifest["canvas"]["kind"] == expected_kind
            assert manifest["canvas"]["format_id"] == expected_format

        # Re-publishing within the same kind (another fixed-size preset) refreshes
        # in place and keeps the existing token.
        landscape_response = client.post(
            f"/workspaces/{workspace_id}/publish",
            headers=headers,
            json={"canvas_format": {"id": "a4-landscape"}, "nodes": [], "edges": [], "charts": []},
        )
        landscape_response.raise_for_status()
        assert landscape_response.json()["token"] == fixed_token
        assert landscape_response.json()["canvas_kind"] == "fixed_size"

        # Status reads are scoped by canvas format and return per-kind tokens.
        free_status = client.get(
            f"/workspaces/{workspace_id}/publish",
            params={"canvas_format_id": "infinite"},
            headers=headers,
        )
        free_status.raise_for_status()
        assert free_status.json()["token"] == free_token

        # Revoking one kind leaves the other kinds' links untouched.
        revoke = client.delete(
            f"/workspaces/{workspace_id}/publish",
            params={"canvas_format_id": "a4-landscape"},
            headers=headers,
        )
        revoke.raise_for_status()
        assert revoke.json()["is_active"] is False

        assert client.get(f"/public/pages/{fixed_token}/manifest").status_code == 404
        client.get(f"/public/pages/{web_token}/manifest").raise_for_status()
        client.get(f"/public/pages/{free_token}/manifest").raise_for_status()


def test_publish_rejects_unsupported_format_and_fixed_out_of_bounds(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        headers = auth_headers(client, user_id="alice", project_id="north", role="viewer", clearance=1)
        workspace_response = client.post("/workspaces", json={"name": "Validation"}, headers=headers)
        workspace_response.raise_for_status()
        workspace_id = workspace_response.json()["workspace_id"]

        unsupported = client.post(
            f"/workspaces/{workspace_id}/publish",
            headers=headers,
            json={"canvas_format": {"id": "poster-custom"}, "nodes": [], "edges": [], "charts": []},
        )
        assert unsupported.status_code == 422
        assert unsupported.json()["detail"]["code"] == "PUBLISH_UNSUPPORTED_CANVAS_FORMAT"

        out_of_bounds = client.post(
            f"/workspaces/{workspace_id}/publish",
            headers=headers,
            json={
                "canvas_format": {"id": "a4-portrait"},
                "nodes": [
                    {
                        "id": "too-wide",
                        "type": "textNode",
                        "position": {"x": 780, "y": 20},
                        "width": 80,
                        "height": 100,
                        "data": {"type": "text", "content": "Outside", "width": 80, "height": 100},
                    }
                ],
                "edges": [],
                "charts": [],
            },
        )
        assert out_of_bounds.status_code == 422
        detail = out_of_bounds.json()["detail"]
        assert detail["code"] == "PUBLISH_FIXED_NODE_OUT_OF_BOUNDS"
        assert detail["node_ids"] == ["too-wide"]

        status = client.get(f"/workspaces/{workspace_id}/published", headers=headers)
        status.raise_for_status()
        assert status.json()["published_pages"] == []


def test_legacy_web_design_manifest_normalizes_to_schema_v2(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        headers = auth_headers(client, user_id="alice", project_id="north", role="viewer", clearance=1)
        workspace_response = client.post("/workspaces", json={"name": "Legacy"}, headers=headers)
        workspace_response.raise_for_status()
        workspace_id = workspace_response.json()["workspace_id"]

        publish_response = client.post(
            f"/workspaces/{workspace_id}/publish",
            headers=headers,
            json={
                "layout": {
                    "grid": {"columns": 1, "rows": [{"id": "row-1", "height": 200}]},
                    "zones": [],
                },
                "sidebar": [],
                "charts": [],
            },
        )
        publish_response.raise_for_status()
        token = publish_response.json()["token"]

        from apps.api.published_pages import get_published_page_store

        store = get_published_page_store()
        publication = store.resolve_active_publication(token=token)
        assert publication is not None
        page = store.get(page_id=publication.active_page_id)
        Path(page.manifest_path).write_text(
            '{"workspace_id":"legacy","version":1,"published_at":"now",'
            '"layout":{"grid":{"columns":1,"rows":[{"id":"row-1","height":200}]},"zones":[]},'
            '"sidebar":[],"charts":[]}',
            encoding="utf-8",
        )

        manifest_response = client.get(f"/public/pages/{token}/manifest")
        manifest_response.raise_for_status()
        manifest = manifest_response.json()["manifest"]
        assert manifest["schema_version"] == 2
        assert manifest["canvas"]["kind"] == "web_page"
        assert manifest["canvas"]["format_id"] == "web-design"
