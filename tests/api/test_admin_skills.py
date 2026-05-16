"""Integration tests for the /admin/skills router (section 5 of OpenSpec change).

Covers RBAC enforcement, happy paths for every endpoint, and unknown-agent
rejection. The route table is gated by ``AGENT_SKILLS_ENABLED`` so the fixture
sets the env, clears caches, and re-runs the mount helper.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient


SKILL_MD = """---
name: cognitrix/test-skill
description: A skill used in the admin API test suite
version: 0.0.1
---

# Test skill
"""


def _make_zip(extra: list[tuple[str, bytes]] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("SKILL.md", SKILL_MD.encode("utf-8"))
        for name, body in extra or []:
            zf.writestr(name, body)
    return buffer.getvalue()


def _setup_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'state.db'}")
    monkeypatch.setenv("MODEL_PROVIDER_URL", "http://localhost:11434")
    monkeypatch.setenv("AUTH_SECRET", "test-secret-admin-skills")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("AGENT_SKILLS_ENABLED", "true")
    monkeypatch.setenv("AGENT_SKILLS_DIR", str(tmp_path / "skills"))
    monkeypatch.setenv("AGENT_SKILLS_MAX_UPLOAD_MB", "1")
    monkeypatch.setenv("AUTH_BOOTSTRAP_ADMIN_EMAIL", "")
    monkeypatch.setenv("AUTH_BOOTSTRAP_ADMIN_PASSWORD", "")
    monkeypatch.setenv("AUTH_BOOTSTRAP_SUPERADMIN_EMAIL", "")


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    _setup_env(monkeypatch, tmp_path)

    from apps.api.config import get_settings
    from apps.api.auth import clear_auth_cache
    from apps.api.audit import clear_audit_logger_cache
    from apps.api.agent_skills.registry import clear_skill_registry_cache

    get_settings.cache_clear()
    clear_auth_cache()
    clear_audit_logger_cache()
    clear_skill_registry_cache()

    from apps.api.main import app, register_admin_skills_router_if_enabled

    register_admin_skills_router_if_enabled()
    return TestClient(app, raise_server_exceptions=True)


def _token(role: str = "superadmin", user_id: str = "ops-root") -> str:
    from apps.api.auth import issue_user_token

    token, _expires = issue_user_token(user_id=user_id, role=role)
    return token


def _auth_headers(role: str = "superadmin", user_id: str = "ops-root") -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(role=role, user_id=user_id)}"}


# ----------------------------------------------------------------------
# RBAC
# ----------------------------------------------------------------------


def test_non_superadmin_is_forbidden_from_listing_skills(client: TestClient) -> None:
    resp = client.get("/admin/skills", headers=_auth_headers(role="admin"))
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["code"] == "RBAC_FORBIDDEN"


def test_no_auth_returns_401(client: TestClient) -> None:
    resp = client.get("/admin/skills")
    assert resp.status_code == 401


# ----------------------------------------------------------------------
# Upload
# ----------------------------------------------------------------------


def test_upload_then_list_then_get(client: TestClient) -> None:
    payload = _make_zip([("assets/note.txt", b"hello")])
    resp = client.post(
        "/admin/skills",
        headers=_auth_headers(),
        files={"file": ("skill.zip", payload, "application/zip")},
    )
    assert resp.status_code == 201, resp.text
    skill = resp.json()
    skill_id = skill["id"]
    assert skill["name"] == "cognitrix/test-skill"
    assert skill["status"] == "enabled"
    assert skill["assignments"] == []
    assert skill["sha256"] and len(skill["sha256"]) == 64

    # List includes the new skill
    listed = client.get("/admin/skills", headers=_auth_headers()).json()
    assert listed["count"] == 1
    assert listed["skills"][0]["id"] == skill_id

    # GET single
    detail = client.get(f"/admin/skills/{skill_id}", headers=_auth_headers()).json()
    assert detail["id"] == skill_id
    assert detail["manifest"]["name"] == "cognitrix/test-skill"


def test_upload_oversized_rejected_with_413(client: TestClient) -> None:
    # MAX_UPLOAD_MB is 1 in the fixture; pad past 1 MiB. Random bytes are
    # incompressible so the resulting zip stays above the limit.
    import os as _os

    big_payload = _make_zip([("big.bin", _os.urandom(1024 * 1024 + 64 * 1024))])
    assert len(big_payload) > 1024 * 1024
    resp = client.post(
        "/admin/skills",
        headers=_auth_headers(),
        files={"file": ("skill.zip", big_payload, "application/zip")},
    )
    assert resp.status_code == 413
    assert resp.json()["detail"]["code"] == "bundle_too_large"


def test_upload_empty_body_rejected(client: TestClient) -> None:
    resp = client.post(
        "/admin/skills",
        headers=_auth_headers(),
        files={"file": ("skill.zip", b"", "application/zip")},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "empty_upload"


def test_upload_non_zip_rejected(client: TestClient) -> None:
    resp = client.post(
        "/admin/skills",
        headers=_auth_headers(),
        files={"file": ("skill.txt", b"not a zip at all", "text/plain")},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "not_a_zip"


def test_upload_missing_skill_md_rejected(client: TestClient) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as zf:
        zf.writestr("README.md", b"hi")
    resp = client.post(
        "/admin/skills",
        headers=_auth_headers(),
        files={"file": ("skill.zip", buffer.getvalue(), "application/zip")},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "missing_skill_md"


# ----------------------------------------------------------------------
# Status toggle / delete
# ----------------------------------------------------------------------


def _upload(client: TestClient) -> dict[str, Any]:
    resp = client.post(
        "/admin/skills",
        headers=_auth_headers(),
        files={"file": ("skill.zip", _make_zip(), "application/zip")},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_patch_status_disables_and_reenables(client: TestClient) -> None:
    skill = _upload(client)
    skill_id = skill["id"]
    disabled = client.patch(
        f"/admin/skills/{skill_id}",
        headers=_auth_headers(),
        json={"status": "disabled"},
    )
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "disabled"

    re_enabled = client.patch(
        f"/admin/skills/{skill_id}",
        headers=_auth_headers(),
        json={"status": "enabled"},
    )
    assert re_enabled.status_code == 200
    assert re_enabled.json()["status"] == "enabled"


def test_patch_status_invalid_value_returns_422(client: TestClient) -> None:
    skill = _upload(client)
    resp = client.patch(
        f"/admin/skills/{skill['id']}",
        headers=_auth_headers(),
        json={"status": "not-a-real-status"},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "invalid_status"


def test_delete_removes_skill_and_bundle(client: TestClient, tmp_path: Path) -> None:
    skill = _upload(client)
    skill_id = skill["id"]
    bundle_dir = Path(skill["bundle_dir"])
    assert bundle_dir.exists()

    resp = client.delete(f"/admin/skills/{skill_id}", headers=_auth_headers())
    assert resp.status_code == 204
    assert not bundle_dir.exists()

    # Subsequent GET is 404.
    missing = client.get(f"/admin/skills/{skill_id}", headers=_auth_headers())
    assert missing.status_code == 404


# ----------------------------------------------------------------------
# Assignments
# ----------------------------------------------------------------------


def test_assign_and_unassign(client: TestClient) -> None:
    skill = _upload(client)
    skill_id = skill["id"]

    assign = client.post(
        f"/admin/skills/{skill_id}/assignments",
        headers=_auth_headers(),
        json={"agent_name": "WriteIngestionAgent"},
    )
    assert assign.status_code == 201, assign.text
    assert assign.json()["agent_name"] == "WriteIngestionAgent"

    agent_view = client.get(
        "/admin/skills/agents/WriteIngestionAgent",
        headers=_auth_headers(),
    ).json()
    assert agent_view["count"] == 1
    assert agent_view["skills"][0]["id"] == skill_id

    detail = client.get(f"/admin/skills/{skill_id}", headers=_auth_headers()).json()
    assert detail["assignments"] == ["WriteIngestionAgent"]

    unassign = client.delete(
        f"/admin/skills/{skill_id}/assignments/WriteIngestionAgent",
        headers=_auth_headers(),
    )
    assert unassign.status_code == 204

    detail_after = client.get(f"/admin/skills/{skill_id}", headers=_auth_headers()).json()
    assert detail_after["assignments"] == []


def test_assign_unknown_agent_is_rejected(client: TestClient) -> None:
    skill = _upload(client)
    resp = client.post(
        f"/admin/skills/{skill['id']}/assignments",
        headers=_auth_headers(),
        json={"agent_name": "NotARealAgent"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "unknown_agent"


def test_list_skills_for_unknown_agent_is_rejected(client: TestClient) -> None:
    resp = client.get(
        "/admin/skills/agents/NotARealAgent",
        headers=_auth_headers(),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "unknown_agent"


def test_assign_to_missing_skill_returns_404(client: TestClient) -> None:
    resp = client.post(
        "/admin/skills/does-not-exist/assignments",
        headers=_auth_headers(),
        json={"agent_name": "QueryAgent"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "skill_not_found"


def test_unassign_missing_assignment_returns_404(client: TestClient) -> None:
    skill = _upload(client)
    resp = client.delete(
        f"/admin/skills/{skill['id']}/assignments/QueryAgent",
        headers=_auth_headers(),
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "assignment_not_found"
