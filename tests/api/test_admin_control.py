from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient


def _setup_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'state.db'}")
    monkeypatch.setenv("MODEL_PROVIDER_URL", "http://provider.test")
    monkeypatch.setenv("AI_API_KEY", "secret-provider-key")
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.setenv("AUTH_SECRET", "admin-control-test-secret")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("AUTH_BOOTSTRAP_ADMIN_EMAIL", "root@example.com")
    monkeypatch.setenv("AUTH_BOOTSTRAP_ADMIN_PASSWORD", "strong-test-password")
    monkeypatch.setenv("AUTH_BOOTSTRAP_SUPERADMIN_EMAIL", "root@example.com")
    monkeypatch.setenv("AGENT_SKILLS_ENABLED", "false")


@pytest.fixture()
def admin_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[TestClient, dict[str, str]]:
    _setup_env(monkeypatch, tmp_path)
    from apps.api.admin_store import clear_admin_store_cache
    from apps.api.agent_skills.registry import clear_skill_registry_cache
    from apps.api.audit import clear_audit_logger_cache
    from apps.api.auth import clear_auth_cache
    from apps.api.config import get_settings

    get_settings.cache_clear()
    clear_admin_store_cache()
    clear_auth_cache()
    clear_audit_logger_cache()
    clear_skill_registry_cache()

    from apps.api.main import app

    with TestClient(app, raise_server_exceptions=True) as client:
        login = client.post(
            "/auth/email-login",
            json={"email": "root@example.com", "password": "strong-test-password"},
        )
        assert login.status_code == 200, login.text
        assert login.json()["user"]["role"] == "superadmin"
        token = login.json()["access_token"]
        yield client, {"Authorization": f"Bearer {token}"}


def _register_user(client: TestClient, *, email: str = "user@example.com") -> dict[str, Any]:
    response = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "password123",
            "display_name": "Test User",
            "job_id": 1,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_admin_control_is_superadmin_only(
    admin_client: tuple[TestClient, dict[str, str]]
) -> None:
    client, headers = admin_client
    assert client.get("/admin/control/meta", headers=headers).status_code == 200

    from apps.api.auth import issue_user_token

    token, _ = issue_user_token(user_id="service-admin", role="admin")
    denied = client.get(
        "/admin/control/meta",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "RBAC_FORBIDDEN"


def test_settings_inventory_masks_secrets_and_covers_model(
    admin_client: tuple[TestClient, dict[str, str]]
) -> None:
    client, headers = admin_client
    response = client.get("/admin/control/settings", headers=headers)
    assert response.status_code == 200
    items = {item["key"]: item for item in response.json()["settings"]}
    assert len(items) == len(__import__("apps.api.config", fromlist=["Settings"]).Settings.model_fields)
    assert items["AI_API_KEY"]["value"] is None
    assert items["AI_API_KEY"]["configured"] is True
    assert "secret-provider-key" not in response.text
    assert items["AI_API_KEY"]["masked_value"].endswith("-key")
    assert items["ACCESS_TOKEN_TTL_MIN"]["secret"] is False
    assert items["PASSWORD_MIN_LENGTH"]["secret"] is False
    assert items["DATABASE_URL"]["restart_required"] is True
    assert items["AGENT_SKILLS_ENABLED"]["restart_required"] is True


def test_setting_update_validation_persistence_and_reset(
    admin_client: tuple[TestClient, dict[str, str]]
) -> None:
    client, headers = admin_client
    updated = client.patch(
        "/admin/control/settings/AGENT_MAX_TOOL_STEPS",
        headers=headers,
        json={"value": 11},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["value"] == 11
    assert updated.json()["source"] == "override"

    invalid = client.patch(
        "/admin/control/settings/AGENT_MAX_TOOL_STEPS",
        headers=headers,
        json={"value": 0},
    )
    assert invalid.status_code == 422

    listed = client.get("/admin/control/settings", headers=headers).json()
    item = next(row for row in listed["settings"] if row["key"] == "AGENT_MAX_TOOL_STEPS")
    assert item["value"] == 11

    reset = client.delete(
        "/admin/control/settings/AGENT_MAX_TOOL_STEPS", headers=headers
    )
    assert reset.status_code == 200
    assert reset.json()["has_override"] is False

    history = client.get("/admin/control/settings/history", headers=headers).json()
    assert [row["action"] for row in history["history"][:2]] == ["reset", "set"]


def test_agent_mode_outline_budget_is_tunable_and_reaches_the_canvas_service(
    admin_client: tuple[TestClient, dict[str, str]]
) -> None:
    """An override of the outline budget must apply without an API restart.

    The canvas-mode service used to snapshot Settings in its constructor, so a
    control-plane edit stayed invisible until the process was restarted.
    """
    from apps.api.agent_canvas_mode import get_agent_canvas_mode_service

    client, headers = admin_client
    listed = client.get("/admin/control/settings?category=agent", headers=headers).json()
    item = next(row for row in listed["settings"] if row["key"] == "AGENT_MODE_OUTLINE_MAX_STEPS")
    assert item["value"] == 24
    assert item["type"] == "integer"
    assert item["restart_required"] is False

    service = get_agent_canvas_mode_service()
    assert service.settings.agent_mode_outline_max_steps == 24

    rejected = client.patch(
        "/admin/control/settings/AGENT_MODE_OUTLINE_MAX_STEPS",
        headers=headers,
        json={"value": 0},
    )
    assert rejected.status_code == 422

    updated = client.patch(
        "/admin/control/settings/AGENT_MODE_OUTLINE_MAX_STEPS",
        headers=headers,
        json={"value": 32},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["value"] == 32
    assert service.settings.agent_mode_outline_max_steps == 32


def test_empty_secret_keeps_existing_and_clear_is_explicit(
    admin_client: tuple[TestClient, dict[str, str]]
) -> None:
    client, headers = admin_client
    kept = client.patch(
        "/admin/control/settings/AI_API_KEY",
        headers=headers,
        json={"value": ""},
    )
    assert kept.status_code == 200
    assert kept.json()["configured"] is True

    cleared = client.patch(
        "/admin/control/settings/AI_API_KEY",
        headers=headers,
        json={"clear": True},
    )
    assert cleared.status_code == 200
    assert cleared.json()["configured"] is False
    assert "secret-provider-key" not in cleared.text


def test_user_inventory_role_and_suspension_invalidate_token(
    admin_client: tuple[TestClient, dict[str, str]]
) -> None:
    client, headers = admin_client
    registered = _register_user(client)
    user_id = registered["user"]["id"]
    token = registered["access_token"]

    inventory = client.get("/admin/control/users?q=user", headers=headers)
    assert inventory.status_code == 200
    row = next(item for item in inventory.json()["users"] if item["id"] == user_id)
    assert row["role"] == "admin"
    assert row["status"] == "active"
    assert "password_hash" not in inventory.text

    promoted = client.patch(
        f"/admin/control/users/{user_id}/role",
        headers=headers,
        json={"role": "hr"},
    )
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "hr"

    suspended = client.patch(
        f"/admin/control/users/{user_id}/status",
        headers=headers,
        json={"status": "suspended"},
    )
    assert suspended.status_code == 200

    rejected = client.get(
        "/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert rejected.status_code == 401
    assert rejected.json()["detail"]["code"] == "ACCOUNT_INACTIVE"

    login = client.post(
        "/auth/email-login",
        json={"email": "user@example.com", "password": "password123"},
    )
    assert login.status_code == 401


def test_self_suspension_and_last_superadmin_demotion_are_blocked(
    admin_client: tuple[TestClient, dict[str, str]]
) -> None:
    client, headers = admin_client
    me = client.get("/auth/me", headers=headers).json()
    self_suspend = client.patch(
        f"/admin/control/users/{me['id']}/status",
        headers=headers,
        json={"status": "suspended"},
    )
    assert self_suspend.status_code == 409
    assert self_suspend.json()["detail"]["code"] == "self_lockout"

    demote = client.patch(
        f"/admin/control/users/{me['id']}/role",
        headers=headers,
        json={"role": "admin"},
    )
    assert demote.status_code == 409
    assert demote.json()["detail"]["code"] == "last_superadmin"


def test_usage_overview_and_user_breakdown(
    admin_client: tuple[TestClient, dict[str, str]]
) -> None:
    client, headers = admin_client
    me = client.get("/auth/me", headers=headers).json()

    from apps.api.admin_control import record_usage_event

    record_usage_event(
        user_id=me["id"],
        project_id="default",
        event_type="chat_turn",
        status_code=200,
    )
    record_usage_event(
        user_id=me["id"],
        project_id="default",
        event_type="tool_call",
        status_code=200,
        input_tokens=10,
        output_tokens=4,
        metadata={"tool_name": "list_tables"},
    )

    overview = client.get(
        "/admin/control/usage/overview?days=7", headers=headers
    )
    assert overview.status_code == 200
    payload = overview.json()
    assert payload["summary"]["chat_turns"] >= 1
    assert payload["summary"]["tool_calls"] >= 1
    assert payload["summary"]["input_tokens"] >= 10
    assert len(payload["trend"]) >= 7

    users = client.get(
        "/admin/control/usage/users?days=7&sort=tool_calls", headers=headers
    )
    assert users.status_code == 200
    row = next(item for item in users.json()["users"] if item["id"] == me["id"])
    assert row["tool_calls"] >= 1
    assert row["tokens"] >= 14


def test_skills_meta_visible_when_runtime_disabled(
    admin_client: tuple[TestClient, dict[str, str]]
) -> None:
    client, headers = admin_client
    response = client.get("/admin/control/skills/meta", headers=headers)
    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert response.json()["known_agents"] == [
        "WriteIngestionAgent",
        "QueryAgent",
        "ChartQueryAgent",
    ]


def test_model_connection_test_is_sanitized(
    admin_client: tuple[TestClient, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, headers = admin_client

    class _Response:
        status_code = 200

    class _Client:
        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, *args: Any, **kwargs: Any) -> _Response:
            assert kwargs["headers"]["Authorization"] == "Bearer secret-provider-key"
            return _Response()

    monkeypatch.setattr(
        "apps.api.admin_control.httpx.AsyncClient",
        lambda **kwargs: _Client(),
    )
    response = client.post("/admin/control/models/test", headers=headers, json={})
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["model"] == "test-model"
    assert "secret-provider-key" not in response.text


def test_documented_default_password_rejected_in_production(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _setup_env(monkeypatch, tmp_path)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_BOOTSTRAP_ADMIN_PASSWORD", "Admin@123456")
    from apps.api.config import get_settings

    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="development Admin password"):
        get_settings()
