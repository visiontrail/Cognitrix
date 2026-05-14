from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient


def _setup_env(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'state.db'}")
    monkeypatch.setenv("MODEL_PROVIDER_URL", "http://localhost:11434")
    monkeypatch.setenv("AUTH_SECRET", "test-secret-for-chat-reset")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("USER_ACCOUNTS_ENABLED", "true")
    monkeypatch.setenv("AUTH_REGISTRATION_ENABLED", "true")
    monkeypatch.setenv("PASSWORD_MIN_LENGTH", "8")
    monkeypatch.setenv("ACCESS_TOKEN_TTL_MIN", "120")
    monkeypatch.setenv("INVITE_LINK_TTL_DAYS", "14")
    monkeypatch.setenv("LEGACY_SERVICE_LOGIN_ENABLED", "true")
    monkeypatch.setenv("AUTH_BOOTSTRAP_ADMIN_EMAIL", "")
    monkeypatch.setenv("AUTH_BOOTSTRAP_ADMIN_PASSWORD", "")
    monkeypatch.setenv("APP_URL", "http://localhost:3000")


def test_chat_session_reset_clears_requested_conversation(monkeypatch: Any, tmp_path: Path) -> None:
    _setup_env(monkeypatch, tmp_path)

    from apps.api.auth import clear_auth_cache
    from apps.api.config import get_settings
    from apps.api.published_pages import clear_published_page_store_cache
    from apps.api.workspaces import clear_workspace_service_cache

    get_settings.cache_clear()
    clear_auth_cache()
    clear_workspace_service_cache()
    clear_published_page_store_cache()

    from apps.api.db_migrations import apply_migrations

    apply_migrations()

    from apps.api import main

    reset_calls: list[str] = []

    class FakeChatService:
        def reset_conversation(self, conversation_id: str) -> None:
            reset_calls.append(conversation_id)

    monkeypatch.setattr(main, "get_chat_stream_service", lambda: FakeChatService())

    with TestClient(main.app, raise_server_exceptions=True) as client:
        login = client.post(
            "/auth/login",
            json={
                "user_id": "demo-user",
                "project_id": "demo-project",
                "role": "hr",
                "department": "HR",
                "clearance": 1,
            },
        )
        assert login.status_code == 200, login.json()
        token = login.json()["access_token"]

        response = client.post(
            "/chat/session/reset",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "user_id": "demo-user",
                "project_id": "demo-project",
                "conversation_id": "session-123",
            },
        )

    assert response.status_code == 200, response.json()
    assert response.json() == {"status": "reset", "conversation_id": "session-123"}
    assert reset_calls == ["session-123"]
