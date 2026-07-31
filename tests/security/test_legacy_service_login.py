"""POST /auth/login must not hand out privileged tokens to anonymous callers.

The endpoint issues a token for whatever `role` the request names and asks for
no credential at all, so an instance that answers it grants `superadmin` — and
with it the whole /admin/control surface, including the stored model API key —
to anyone who can reach the port. It is kept only for local development and the
smoke flow, so it must be off unless explicitly enabled, and unreachable in
production whatever the flag says.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.audit import clear_audit_logger_cache
from apps.api.auth import clear_auth_cache
from apps.api.config import get_settings
from apps.api.main import app

ESCALATION_PAYLOAD = {
    "user_id": "anonymous-attacker",
    "project_id": "default",
    "role": "superadmin",
}


def _set_env(monkeypatch, tmp_path: Path, *, app_env: str, legacy: str | None) -> None:
    # Point at an absent env file so the developer's own apps/api/.env cannot
    # decide the outcome of a security assertion.
    monkeypatch.setenv("API_ENV_FILE", str(tmp_path / "absent.env"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'views.db'}")
    monkeypatch.setenv("MODEL_PROVIDER_URL", "http://localhost:11434")
    monkeypatch.setenv("AUTH_SECRET", "x" * 64)
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("APP_ENV", app_env)
    if legacy is None:
        monkeypatch.delenv("LEGACY_SERVICE_LOGIN_ENABLED", raising=False)
    else:
        monkeypatch.setenv("LEGACY_SERVICE_LOGIN_ENABLED", legacy)
    get_settings.cache_clear()
    clear_auth_cache()
    clear_audit_logger_cache()


@pytest.mark.parametrize(
    ("app_env", "legacy"),
    [
        ("production", None),
        ("production", "false"),
        # The flag is deliberately ignored in production: an operator who flips
        # it on must not be able to expose credential-free role escalation.
        ("production", "true"),
        ("development", None),
        ("development", "false"),
    ],
)
def test_anonymous_role_escalation_is_refused(monkeypatch, tmp_path, app_env, legacy) -> None:
    _set_env(monkeypatch, tmp_path, app_env=app_env, legacy=legacy)

    with TestClient(app) as client:
        response = client.post("/auth/login", json=ESCALATION_PAYLOAD)

    assert response.status_code == 404
    assert "access_token" not in response.text


def test_disabled_endpoint_does_not_advertise_itself(monkeypatch, tmp_path) -> None:
    """The refusal must not leak that a different configuration would answer."""

    _set_env(monkeypatch, tmp_path, app_env="production", legacy="true")

    with TestClient(app) as client:
        response = client.post("/auth/login", json=ESCALATION_PAYLOAD)

    body = response.text.lower()
    assert response.status_code == 404
    for leak in ("legacy", "disabled", "app_env", "production", "enable"):
        assert leak not in body


def test_development_opt_in_still_serves_the_smoke_flow(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, tmp_path, app_env="development", legacy="true")

    with TestClient(app) as client:
        response = client.post(
            "/auth/login",
            json={"user_id": "smoke-hr", "project_id": "smoke-project", "role": "hr"},
        )

    assert response.status_code == 200
    assert response.json()["user"]["role"] == "hr"


def test_admin_control_stays_unreachable_without_the_endpoint(monkeypatch, tmp_path) -> None:
    """The escalation's payoff — reading every setting, including the API key."""

    _set_env(monkeypatch, tmp_path, app_env="production", legacy="true")

    with TestClient(app) as client:
        login = client.post("/auth/login", json=ESCALATION_PAYLOAD)
        assert login.status_code == 404

        for path in ("/admin/control/meta", "/admin/control/settings"):
            assert client.get(path).status_code in {401, 403}
