from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from apps.api.audit import clear_audit_logger_cache
from apps.api.auth import (
    AuthIdentity,
    clear_auth_cache,
    get_role_directory,
    has_permission,
    require_permission,
    ROLE_PERMISSIONS,
)
from apps.api.config import get_settings
from apps.api.db_migrations import _bootstrap_superadmin


def _reset_settings(monkeypatch, tmp_path: Path, *, superadmin_email: str = "") -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'views.db'}")
    monkeypatch.setenv("MODEL_PROVIDER_URL", "http://localhost:11434")
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("AUTH_BOOTSTRAP_SUPERADMIN_EMAIL", superadmin_email)
    monkeypatch.setenv("AUTH_BOOTSTRAP_ADMIN_EMAIL", "")
    monkeypatch.setenv("AUTH_BOOTSTRAP_ADMIN_PASSWORD", "")
    get_settings.cache_clear()
    clear_auth_cache()
    clear_audit_logger_cache()


def _make_identity(role: str) -> AuthIdentity:
    return AuthIdentity(
        user_id="alice",
        project_id="north",
        role=role,
        department=None,
        clearance=0,
        token_id="t",
        expires_at=9_999_999_999,
    )


def test_superadmin_role_is_registered_and_has_skills_admin() -> None:
    assert "superadmin" in ROLE_PERMISSIONS
    assert "skills:admin" in ROLE_PERMISSIONS["superadmin"]
    # admin must NOT have skills:admin — that's the whole point of the new role.
    assert "skills:admin" not in ROLE_PERMISSIONS["admin"]


def test_has_permission_skills_admin() -> None:
    assert has_permission("superadmin", "skills:admin") is True
    assert has_permission("admin", "skills:admin") is False
    assert has_permission("hr", "skills:admin") is False
    assert has_permission("viewer", "skills:admin") is False


def test_require_permission_denies_non_superadmin(monkeypatch, tmp_path: Path) -> None:
    _reset_settings(monkeypatch, tmp_path)
    from fastapi import HTTPException, Request

    dependency = require_permission("skills:admin")
    scope = {"type": "http", "method": "GET", "path": "/admin/skills", "headers": []}
    request = Request(scope)

    with pytest.raises(HTTPException) as exc_info:
        dependency(request=request, identity=_make_identity("admin"))
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "RBAC_FORBIDDEN"


def test_require_permission_allows_superadmin(monkeypatch, tmp_path: Path) -> None:
    _reset_settings(monkeypatch, tmp_path)
    from fastapi import Request

    dependency = require_permission("skills:admin")
    scope = {"type": "http", "method": "GET", "path": "/admin/skills", "headers": []}
    request = Request(scope)

    identity = _make_identity("superadmin")
    result = dependency(request=request, identity=identity)
    assert result is identity


def _seed_user(db_path: Path, *, user_id: str, email: str) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL,
                email_lower TEXT,
                display_name TEXT NOT NULL DEFAULT '',
                password_hash TEXT,
                job_id INTEGER,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_login_at TIMESTAMP
            )
            """
        )
        conn.execute(
            "INSERT INTO users (id, email, email_lower, password_hash) VALUES (?, ?, ?, ?)",
            (user_id, email, email.lower(), "hashed-placeholder"),
        )
        conn.commit()
    finally:
        conn.close()


def test_env_var_promotion_path(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "views.db"
    _reset_settings(monkeypatch, tmp_path, superadmin_email="root@example.com")
    _seed_user(db_path, user_id="user-root", email="root@example.com")

    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        _bootstrap_superadmin(conn)
    finally:
        conn.close()

    override = get_role_directory().get_override("user-root")
    assert override is not None
    assert override["role"] == "superadmin"


def test_env_var_missing_user_does_not_promote_anyone(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "views.db"
    _reset_settings(monkeypatch, tmp_path, superadmin_email="nobody@example.com")
    _seed_user(db_path, user_id="user-other", email="other@example.com")

    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        _bootstrap_superadmin(conn)
    finally:
        conn.close()

    assert get_role_directory().has_any_with_role("superadmin") is False


def test_fallback_promotes_bootstrap_admin_when_no_superadmin_exists(
    monkeypatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "views.db"
    _reset_settings(monkeypatch, tmp_path, superadmin_email="")
    monkeypatch.setenv("AUTH_BOOTSTRAP_ADMIN_EMAIL", "admin@example.com")
    get_settings.cache_clear()
    clear_auth_cache()
    _seed_user(db_path, user_id="user-admin", email="admin@example.com")

    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        _bootstrap_superadmin(conn)
    finally:
        conn.close()

    override = get_role_directory().get_override("user-admin")
    assert override is not None
    assert override["role"] == "superadmin"


def test_fallback_skipped_when_superadmin_already_exists(
    monkeypatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "views.db"
    _reset_settings(monkeypatch, tmp_path, superadmin_email="")
    monkeypatch.setenv("AUTH_BOOTSTRAP_ADMIN_EMAIL", "admin@example.com")
    get_settings.cache_clear()
    clear_auth_cache()
    _seed_user(db_path, user_id="user-admin", email="admin@example.com")

    # Pre-seed an existing superadmin override for a different user.
    role_dir = get_role_directory()
    role_dir.set_override(
        user_id="user-existing",
        role="superadmin",
        department=None,
        clearance=0,
        updated_by="test",
    )

    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        _bootstrap_superadmin(conn)
    finally:
        conn.close()

    # The bootstrap admin should NOT have been auto-promoted.
    admin_override = get_role_directory().get_override("user-admin")
    assert admin_override is None
