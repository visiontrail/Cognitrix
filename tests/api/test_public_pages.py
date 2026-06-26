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
    monkeypatch.setenv("AUTH_BOOTSTRAP_ADMIN_EMAIL", "")
    monkeypatch.setenv("AUTH_BOOTSTRAP_ADMIN_PASSWORD", "")
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
    from apps.api.db_migrations import apply_migrations

    apply_migrations()


_PUBLISH_BODY = {
    "layout": {
        "grid": {"columns": 2, "rows": [{"id": "row-1", "height": 320}]},
        "zones": [{"id": "zone-1", "chart_id": "chart-1", "column": 0, "row": 0}],
    },
    "sidebar": [{"id": "overview", "label": "Overview", "anchorRowId": "row-1", "children": []}],
    "charts": [
        {
            "chart_id": "chart-1",
            "title": "Headcount",
            "chart_type": "bar",
            "spec": {"chart_type": "bar", "title": "Headcount"},
            "rows": [{"department": "HR", "headcount": 4, "salary": 100}],
        }
    ],
}


def _publish(client: TestClient, headers, workspace_id: str):
    resp = client.post(f"/workspaces/{workspace_id}/publish", headers=headers, json=_PUBLISH_BODY)
    resp.raise_for_status()
    return resp.json()


def _make_workspace(client: TestClient, headers) -> str:
    resp = client.post("/workspaces", json={"name": "Public Pages"}, headers=headers)
    resp.raise_for_status()
    return resp.json()["workspace_id"]


def _register_user(client: TestClient, *, email: str, display_name: str) -> tuple[str, dict[str, str]]:
    resp = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "password123",
            "display_name": display_name,
            "job_id": 1,
        },
    )
    resp.raise_for_status()
    payload = resp.json()
    return payload["user"]["id"], {"Authorization": f"Bearer {payload['access_token']}"}


def test_publish_returns_public_link_and_status_and_revoke(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path)
    with TestClient(app) as client:
        headers = auth_headers(client, user_id="alice", project_id="north", role="admin", clearance=9)
        workspace_id = _make_workspace(client, headers)

        published = _publish(client, headers, workspace_id)
        token = published["token"]
        assert published["is_active"] is True
        assert published["public_url"].endswith(f"/p/{token}")

        # Status endpoint reports the active publication.
        status = client.get(f"/workspaces/{workspace_id}/publish", headers=headers)
        assert status.status_code == 200
        assert status.json()["is_active"] is True
        assert status.json()["token"] == token

        # Update publish reuses the same token.
        republished = _publish(client, headers, workspace_id)
        assert republished["token"] == token
        assert republished["version"] == published["version"] + 1

        # Revoke makes the public read 404 and status inactive.
        revoke = client.delete(f"/workspaces/{workspace_id}/publish", headers=headers)
        assert revoke.status_code == 200
        assert revoke.json()["is_active"] is False

        inactive_status = client.get(f"/workspaces/{workspace_id}/publish", headers=headers).json()
        assert inactive_status["is_active"] is False
        assert "token" not in inactive_status
        assert inactive_status["canvas_kind"] == "web_page"
        assert client.get(f"/public/pages/{token}/manifest").status_code == 404


def test_publish_accepts_registered_visibility_payload(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path)
    with TestClient(app) as client:
        headers = auth_headers(client, user_id="alice", project_id="north", role="admin", clearance=9)
        workspace_id = _make_workspace(client, headers)

        body = {**_PUBLISH_BODY, "visibility_mode": "registered", "visibility_user_ids": ["ignored"]}
        resp = client.post(f"/workspaces/{workspace_id}/publish", headers=headers, json=body)
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["visibility_mode"] == "registered"
        assert payload["visibility_user_ids"] == []
        assert payload["is_active"] is True


def test_public_manifest_unauthenticated_and_no_leakage(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path)
    with TestClient(app) as client:
        # A non-privileged BI role so sensitive columns are redacted at publish.
        headers = auth_headers(client, user_id="alice", project_id="north", role="viewer", clearance=1)
        workspace_id = _make_workspace(client, headers)
        token = _publish(client, headers, workspace_id)["token"]

        # No auth headers required.
        resp = client.get(f"/public/pages/{token}/manifest")
        assert resp.status_code == 200
        assert resp.headers.get("cache-control", "").startswith("no-store")
        body = resp.json()
        text = resp.text
        for leaked in (
            "workspace_members",
            "visibility_mode",
            "visibility_user_ids",
            "owner_email",
            "database_path",
            "published_by",
        ):
            assert leaked not in text
        assert "page_id" not in body  # internal page id not exposed
        assert body["manifest"]["charts"][0]["chart_id"] == "chart-1"

        # Chart data comes from the redacted snapshot (salary stripped at publish).
        data = client.get(f"/public/pages/{token}/charts/chart-1/data")
        assert data.status_code == 200
        assert data.json()["rows"] == [{"department": "HR", "headcount": 4}]


def test_unknown_token_returns_404(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path)
    with TestClient(app) as client:
        assert client.get("/public/pages/never-existed/manifest").status_code == 404
        assert client.get("/public/pages/never-existed/charts/x/data").status_code == 404


def test_publish_history_includes_visibility_summary(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path)
    with TestClient(app) as client:
        headers = auth_headers(client, user_id="alice", project_id="north", role="admin", clearance=9)
        workspace_id = _make_workspace(client, headers)
        published = client.post(
            f"/workspaces/{workspace_id}/publish",
            headers=headers,
            json={**_PUBLISH_BODY, "visibility_mode": "registered"},
        )
        published.raise_for_status()

        history = client.get(f"/workspaces/{workspace_id}/published", headers=headers)
        assert history.status_code == 200
        items = history.json()["published_pages"]
        assert len(items) == 1
        item = items[0]
        assert {"page_id", "version", "published_at", "published_by"} <= set(item.keys())
        assert item["visibility_mode"] == "registered"
        assert item["visibility_user_count"] is None
        assert item["visibility_user_ids"] == []


def test_registered_publication_requires_real_registered_login(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path)
    with TestClient(app) as client:
        owner_id, owner_headers = _register_user(
            client, email="owner@example.com", display_name="Owner"
        )
        assert owner_id
        workspace_id = _make_workspace(client, owner_headers)
        publish = client.post(
            f"/workspaces/{workspace_id}/publish",
            headers=owner_headers,
            json={**_PUBLISH_BODY, "visibility_mode": "registered"},
        )
        publish.raise_for_status()
        token = publish.json()["token"]

        client.cookies.clear()
        assert client.get(f"/public/pages/{token}/manifest").status_code == 401

        viewer_id, viewer_headers = _register_user(
            client, email="viewer@example.com", display_name="Viewer"
        )
        assert viewer_id
        registered = client.get(f"/public/pages/{token}/manifest", headers=viewer_headers)
        assert registered.status_code == 200

        legacy_headers = auth_headers(
            client, user_id="legacy-only", project_id="north", role="viewer", clearance=1
        )
        legacy = client.get(f"/public/pages/{token}/manifest", headers=legacy_headers)
        assert legacy.status_code == 401


def test_allowlist_publication_is_limited_to_selected_registered_users(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path)
    with TestClient(app) as client:
        _, owner_headers = _register_user(client, email="owner@example.com", display_name="Owner")
        allowed_id, allowed_headers = _register_user(
            client, email="allowed@example.com", display_name="Allowed"
        )
        _, blocked_headers = _register_user(
            client, email="blocked@example.com", display_name="Blocked"
        )
        workspace_id = _make_workspace(client, owner_headers)

        publish = client.post(
            f"/workspaces/{workspace_id}/publish",
            headers=owner_headers,
            json={
                **_PUBLISH_BODY,
                "visibility_mode": "allowlist",
                "visibility_user_ids": [allowed_id],
            },
        )
        publish.raise_for_status()
        payload = publish.json()
        token = payload["token"]
        assert payload["visibility_mode"] == "allowlist"
        assert payload["visibility_user_ids"] == [allowed_id]

        client.cookies.clear()
        assert client.get(f"/public/pages/{token}/manifest").status_code == 401
        assert client.get(f"/public/pages/{token}/manifest", headers=allowed_headers).status_code == 200
        assert client.get(
            f"/public/pages/{token}/charts/chart-1/data",
            headers=allowed_headers,
        ).status_code == 200
        assert client.get(f"/public/pages/{token}/manifest", headers=blocked_headers).status_code == 403


def test_allowlist_publish_rejects_unknown_user_ids(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path)
    with TestClient(app) as client:
        _, owner_headers = _register_user(client, email="owner@example.com", display_name="Owner")
        workspace_id = _make_workspace(client, owner_headers)

        empty = client.post(
            f"/workspaces/{workspace_id}/publish",
            headers=owner_headers,
            json={
                **_PUBLISH_BODY,
                "visibility_mode": "allowlist",
                "visibility_user_ids": [],
            },
        )
        assert empty.status_code == 422
        assert empty.json()["detail"]["code"] == "PUBLISH_VISIBILITY_USERS_REQUIRED"

        resp = client.post(
            f"/workspaces/{workspace_id}/publish",
            headers=owner_headers,
            json={
                **_PUBLISH_BODY,
                "visibility_mode": "allowlist",
                "visibility_user_ids": ["missing-user"],
            },
        )
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "PUBLISH_VISIBILITY_USERS_INVALID"
