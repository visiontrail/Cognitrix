from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.audit import clear_audit_logger_cache
from apps.api.auth import clear_auth_cache
from apps.api.config import get_settings
from apps.api.main import app
from apps.api.workspace_state import clear_workspace_state_store_cache
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
    clear_workspace_service_cache()
    clear_workspace_state_store_cache()


def _create_workspace(client: TestClient, headers: dict[str, str], name: str = "WS") -> str:
    response = client.post("/workspaces", json={"name": name}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["workspace_id"]


def test_chat_session_and_messages_round_trip(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        headers = auth_headers(client, user_id="alice", project_id="north", role="hr", clearance=5)
        workspace_id = _create_workspace(client, headers)

        # Upsert a session
        put = client.put(
            f"/workspaces/{workspace_id}/chat/sessions/sess-1",
            headers=headers,
            json={
                "title": "Headcount analysis",
                "lastMessage": "Show me headcount by dept",
                "messageCount": 2,
                "createdAt": "2026-06-01T00:00:00+00:00",
                "updatedAt": "2026-06-02T00:00:00+00:00",
            },
        )
        assert put.status_code == 200, put.text
        assert put.json()["session"]["title"] == "Headcount analysis"

        # Replace messages, including a rich chart reference that must survive verbatim
        messages = [
            {"id": "m1", "sessionId": "sess-1", "role": "user", "content": "hi", "timestamp": "t1"},
            {
                "id": "m2",
                "sessionId": "sess-1",
                "role": "assistant",
                "content": "here",
                "timestamp": "t2",
                "chartAsset": {"assetId": "a1", "title": "Headcount", "chartType": "bar"},
            },
        ]
        put_msgs = client.put(
            f"/workspaces/{workspace_id}/chat/sessions/sess-1/messages",
            headers=headers,
            json={"messages": messages},
        )
        assert put_msgs.status_code == 200, put_msgs.text
        assert put_msgs.json()["count"] == 2

        # A *second device* for the same account fetches everything from the server
        list_sessions = client.get(f"/workspaces/{workspace_id}/chat/sessions", headers=headers)
        assert list_sessions.status_code == 200
        sessions = list_sessions.json()["sessions"]
        assert len(sessions) == 1
        assert sessions[0]["id"] == "sess-1"
        assert sessions[0]["messageCount"] == 2

        list_msgs = client.get(
            f"/workspaces/{workspace_id}/chat/sessions/sess-1/messages", headers=headers
        )
        assert list_msgs.status_code == 200
        fetched = list_msgs.json()["messages"]
        assert [m["id"] for m in fetched] == ["m1", "m2"]
        # Rich payload preserved verbatim
        assert fetched[1]["chartAsset"] == {"assetId": "a1", "title": "Headcount", "chartType": "bar"}


def test_chart_assets_round_trip(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        headers = auth_headers(client, user_id="alice", project_id="north", role="hr", clearance=5)
        workspace_id = _create_workspace(client, headers)

        asset = {
            "id": "a1",
            "title": "Headcount by dept",
            "chartType": "bar",
            "spec": {"chartType": "bar", "title": "Headcount", "echartsOption": {"series": []}},
            "sourceMeta": {"sessionId": "sess-1", "messageId": "m2", "prompt": "headcount"},
            "createdAt": "2026-06-01T00:00:00+00:00",
            "updatedAt": "2026-06-01T00:00:00+00:00",
        }
        put = client.put(
            f"/workspaces/{workspace_id}/chart-assets/a1", headers=headers, json={"asset": asset}
        )
        assert put.status_code == 200, put.text

        listed = client.get(f"/workspaces/{workspace_id}/chart-assets", headers=headers)
        assert listed.status_code == 200
        assets = listed.json()["assets"]
        assert len(assets) == 1
        assert assets[0]["id"] == "a1"
        assert assets[0]["spec"]["echartsOption"] == {"series": []}


def test_canvas_snapshot_round_trip_and_editor_required(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        owner = auth_headers(client, user_id="alice", project_id="north", role="admin", clearance=9)
        workspace_id = _create_workspace(client, owner)

        # Empty before first save
        empty = client.get(f"/workspaces/{workspace_id}/canvas-snapshot", headers=owner)
        assert empty.status_code == 200
        assert empty.json()["snapshot"] is None

        snapshot = {
            "workspaceId": workspace_id,
            "nodes": [{"id": "n1", "data": {"type": "chart", "assetId": "a1"}}],
            "edges": [],
            "viewport": {"x": 0, "y": 0, "zoom": 1},
            "canvasFormat": {"id": "free"},
        }
        saved = client.put(
            f"/workspaces/{workspace_id}/canvas-snapshot", headers=owner, json={"snapshot": snapshot}
        )
        assert saved.status_code == 200, saved.text

        got = client.get(f"/workspaces/{workspace_id}/canvas-snapshot", headers=owner)
        assert got.json()["snapshot"]["nodes"][0]["id"] == "n1"

        # Viewer is no longer a valid membership role.
        rejected = client.post(
            f"/workspaces/{workspace_id}/members",
            headers=owner,
            json={"user_id": "carol", "role": "viewer"},
        )
        assert rejected.status_code == 422

        # An editor member can both read and write the snapshot.
        client.post(
            f"/workspaces/{workspace_id}/members",
            headers=owner,
            json={"user_id": "carol", "role": "editor"},
        )
        editor = auth_headers(client, user_id="carol", project_id="north", role="pm", clearance=1)
        assert client.get(f"/workspaces/{workspace_id}/canvas-snapshot", headers=editor).status_code == 200
        editor_write = client.put(
            f"/workspaces/{workspace_id}/canvas-snapshot", headers=editor, json={"snapshot": snapshot}
        )
        assert editor_write.status_code == 200, editor_write.text

        # A non-member cannot read the snapshot.
        outsider = auth_headers(client, user_id="mallory", project_id="north", role="pm", clearance=1)
        forbidden = client.get(f"/workspaces/{workspace_id}/canvas-snapshot", headers=outsider)
        expect_error_code(forbidden, "WORKSPACE_FORBIDDEN", status_code=403)


def test_chat_history_is_per_user_and_non_member_blocked(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        owner = auth_headers(client, user_id="alice", project_id="north", role="admin", clearance=9)
        workspace_id = _create_workspace(client, owner)

        # Add bob as a member of the workspace (workspace role "editor" is
        # independent of the auth login role, which must be a valid auth role).
        client.post(
            f"/workspaces/{workspace_id}/members",
            headers=owner,
            json={"user_id": "bob", "role": "editor"},
        )
        bob = auth_headers(client, user_id="bob", project_id="north", role="pm", clearance=5)

        # Alice creates a session; bob (same workspace, different user) must not see it
        client.put(
            f"/workspaces/{workspace_id}/chat/sessions/sess-alice",
            headers=owner,
            json={"title": "Alice only", "messageCount": 0},
        )
        assert len(client.get(f"/workspaces/{workspace_id}/chat/sessions", headers=owner).json()["sessions"]) == 1
        assert client.get(f"/workspaces/{workspace_id}/chat/sessions", headers=bob).json()["sessions"] == []

        # A non-member is rejected outright
        outsider = auth_headers(client, user_id="mallory", project_id="north", role="pm", clearance=5)
        expect_error_code(
            client.get(f"/workspaces/{workspace_id}/chat/sessions", headers=outsider),
            "WORKSPACE_FORBIDDEN",
            status_code=403,
        )


def test_session_id_cannot_be_hijacked_across_users(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        owner = auth_headers(client, user_id="alice", project_id="north", role="admin", clearance=9)
        workspace_id = _create_workspace(client, owner)
        client.post(
            f"/workspaces/{workspace_id}/members",
            headers=owner,
            json={"user_id": "bob", "role": "editor"},
        )
        bob = auth_headers(client, user_id="bob", project_id="north", role="pm", clearance=5)

        client.put(
            f"/workspaces/{workspace_id}/chat/sessions/shared-id",
            headers=owner,
            json={"title": "Alice", "messageCount": 0},
        )
        # Bob trying to upsert the same session id must not clobber Alice's row
        conflict = client.put(
            f"/workspaces/{workspace_id}/chat/sessions/shared-id",
            headers=bob,
            json={"title": "Bob", "messageCount": 0},
        )
        assert conflict.status_code == 409
        # Alice's copy is intact
        alice_sessions = client.get(
            f"/workspaces/{workspace_id}/chat/sessions", headers=owner
        ).json()["sessions"]
        assert alice_sessions[0]["title"] == "Alice"


def test_workspace_delete_cascades_state(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        owner = auth_headers(client, user_id="alice", project_id="north", role="admin", clearance=9)
        workspace_id = _create_workspace(client, owner, name="Disposable")

        client.put(
            f"/workspaces/{workspace_id}/chat/sessions/sess-1",
            headers=owner,
            json={"title": "x", "messageCount": 1},
        )
        client.put(
            f"/workspaces/{workspace_id}/chat/sessions/sess-1/messages",
            headers=owner,
            json={"messages": [{"id": "m1", "role": "user", "content": "hi"}]},
        )
        client.put(
            f"/workspaces/{workspace_id}/chart-assets/a1",
            headers=owner,
            json={"asset": {"id": "a1", "title": "t", "chartType": "bar"}},
        )
        client.put(
            f"/workspaces/{workspace_id}/canvas-snapshot",
            headers=owner,
            json={"snapshot": {"workspaceId": workspace_id, "nodes": []}},
        )

        delete = client.request(
            "DELETE",
            f"/workspaces/{workspace_id}",
            headers=owner,
            json={"confirm_workspace_name": "Disposable"},
        )
        assert delete.status_code == 200, delete.text

        # Rows are gone: the store reports nothing for this workspace id
        from apps.api.workspace_state import get_workspace_state_store

        store = get_workspace_state_store()
        assert store.list_sessions(workspace_id=workspace_id, user_id="alice") == []
        assert store.list_messages(workspace_id=workspace_id, user_id="alice", session_id="sess-1") == []
        assert store.list_chart_assets(workspace_id=workspace_id, user_id="alice") == []
        assert store.get_snapshot(workspace_id=workspace_id) is None
