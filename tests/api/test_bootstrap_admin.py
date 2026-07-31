"""First-boot admin bootstrap.

A deployment that configures nothing must still end up with an account somebody
can log in with, without that account's password being a constant anyone who can
read this repository already knows. The password is therefore generated per
deployment and written to the log exactly once, at creation.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.audit import clear_audit_logger_cache
from apps.api.auth import clear_auth_cache
from apps.api.config import DEFAULT_BOOTSTRAP_ADMIN_EMAIL, get_settings
from apps.api.main import app

PASSWORD_LINE = re.compile(r"password:\s*(\S+)")


def _set_env(monkeypatch, tmp_path: Path, **overrides: str) -> None:
    monkeypatch.setenv("API_ENV_FILE", str(tmp_path / "absent.env"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'views.db'}")
    monkeypatch.setenv("AUTH_SECRET", "x" * 64)
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("APP_ENV", "production")
    for key in ("AUTH_BOOTSTRAP_ADMIN_EMAIL", "AUTH_BOOTSTRAP_ADMIN_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    for key, value in overrides.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    clear_auth_cache()
    clear_audit_logger_cache()


def _boot(caplog) -> str | None:
    """Start the app once and return the generated password, if any."""

    with caplog.at_level(logging.WARNING, logger="cognitrix.db_migrations"):
        with TestClient(app):
            pass
    for record in caplog.records:
        match = PASSWORD_LINE.search(record.getMessage())
        if match:
            return match.group(1)
    return None


def test_zero_configuration_boot_creates_a_usable_admin(monkeypatch, tmp_path, caplog) -> None:
    _set_env(monkeypatch, tmp_path)

    password = _boot(caplog)
    assert password, "a deployment that configures nothing must still get an account"

    with TestClient(app) as client:
        response = client.post(
            "/auth/email-login",
            json={"email": DEFAULT_BOOTSTRAP_ADMIN_EMAIL, "password": password},
        )

    assert response.status_code == 200


def test_generated_password_is_not_a_repository_constant(monkeypatch, tmp_path, caplog) -> None:
    """Two deployments must not share a password. That is the whole point."""

    _set_env(monkeypatch, tmp_path / "a")
    first = _boot(caplog)
    caplog.clear()
    _set_env(monkeypatch, tmp_path / "b")
    second = _boot(caplog)

    assert first and second
    assert first != second
    assert len(first) >= 16


def test_password_is_logged_only_at_creation(monkeypatch, tmp_path, caplog) -> None:
    _set_env(monkeypatch, tmp_path)
    assert _boot(caplog)

    caplog.clear()
    # Second boot finds the account already there and must stay quiet.
    assert _boot(caplog) is None


def test_configured_password_is_used_verbatim_and_never_logged(
    monkeypatch, tmp_path, caplog
) -> None:
    _set_env(monkeypatch, tmp_path, AUTH_BOOTSTRAP_ADMIN_PASSWORD="OperatorChosen123")

    assert _boot(caplog) is None
    assert "OperatorChosen123" not in caplog.text

    with TestClient(app) as client:
        response = client.post(
            "/auth/email-login",
            json={"email": DEFAULT_BOOTSTRAP_ADMIN_EMAIL, "password": "OperatorChosen123"},
        )

    assert response.status_code == 200


def test_empty_email_opts_out_of_bootstrapping(monkeypatch, tmp_path, caplog) -> None:
    _set_env(monkeypatch, tmp_path, AUTH_BOOTSTRAP_ADMIN_EMAIL="")

    assert _boot(caplog) is None

    with TestClient(app) as client:
        response = client.post(
            "/auth/email-login",
            json={"email": DEFAULT_BOOTSTRAP_ADMIN_EMAIL, "password": "anything-at-all"},
        )

    assert response.status_code != 200


def test_bootstrap_admin_reaches_the_admin_console(monkeypatch, tmp_path, caplog) -> None:
    """Without superadmin the account cannot configure the model key, which is
    the entire deploy-then-configure flow."""

    _set_env(monkeypatch, tmp_path)
    password = _boot(caplog)
    assert password

    with TestClient(app) as client:
        login = client.post(
            "/auth/email-login",
            json={"email": DEFAULT_BOOTSTRAP_ADMIN_EMAIL, "password": password},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        assert client.get("/admin/control/meta", headers=headers).status_code == 200


@pytest.mark.parametrize("existing_password", ["AlreadyHere123", "AnotherOne456"])
def test_existing_account_is_never_overwritten(
    monkeypatch, tmp_path, caplog, existing_password
) -> None:
    _set_env(monkeypatch, tmp_path, AUTH_BOOTSTRAP_ADMIN_PASSWORD=existing_password)
    _boot(caplog)

    # A later boot without a configured password must not mint a new credential
    # for an account that already exists.
    _set_env(monkeypatch, tmp_path)
    assert _boot(caplog) is None

    with TestClient(app) as client:
        response = client.post(
            "/auth/email-login",
            json={"email": DEFAULT_BOOTSTRAP_ADMIN_EMAIL, "password": existing_password},
        )

    assert response.status_code == 200
