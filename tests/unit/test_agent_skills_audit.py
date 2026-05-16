"""Audit event coverage for admin skill mutations (section 6 of the change).

Drives the API via TestClient and then reads the on-disk audit log to assert
that every mutation produces the spec-defined event type with the correct
actor + skill context.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient


SKILL_MD = """---
name: cognitrix/audit-skill
description: Used for audit emission tests
version: 0.0.1
---

# audit skill
"""


def _make_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("SKILL.md", SKILL_MD.encode("utf-8"))
    return buffer.getvalue()


def _set_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'state.db'}")
    monkeypatch.setenv("MODEL_PROVIDER_URL", "http://localhost:11434")
    monkeypatch.setenv("AUTH_SECRET", "test-secret-audit-skills")
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
    _set_env(monkeypatch, tmp_path)

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


def _superadmin_headers() -> dict[str, str]:
    from apps.api.auth import issue_user_token

    token, _ = issue_user_token(user_id="ops-root", role="superadmin")
    return {"Authorization": f"Bearer {token}"}


def _audit_events(tmp_path: Path) -> list[dict[str, Any]]:
    log_path = tmp_path / "uploads" / "audit" / "security_events.log"
    if not log_path.exists():
        return []
    events = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def _last_with_action(events: list[dict[str, Any]], action: str) -> dict[str, Any]:
    for event in reversed(events):
        if event.get("action") == action:
            return event
    raise AssertionError(f"no audit event with action={action}; got {[e['action'] for e in events]}")


def test_full_lifecycle_emits_expected_audit_events(
    client: TestClient, tmp_path: Path
) -> None:
    headers = _superadmin_headers()

    # Upload — emits skill_upload
    upload = client.post(
        "/admin/skills",
        headers=headers,
        files={"file": ("skill.zip", _make_zip(), "application/zip")},
    )
    assert upload.status_code == 201
    skill_id = upload.json()["id"]

    # Patch status to disabled and back — emits skill_disable, skill_enable
    client.patch(f"/admin/skills/{skill_id}", headers=headers, json={"status": "disabled"})
    client.patch(f"/admin/skills/{skill_id}", headers=headers, json={"status": "enabled"})

    # Assign and unassign — emits skill_assign, skill_unassign
    client.post(
        f"/admin/skills/{skill_id}/assignments",
        headers=headers,
        json={"agent_name": "QueryAgent"},
    )
    client.delete(
        f"/admin/skills/{skill_id}/assignments/QueryAgent",
        headers=headers,
    )

    # Delete — emits skill_delete
    client.delete(f"/admin/skills/{skill_id}", headers=headers)

    events = _audit_events(tmp_path)
    seen_actions = {e["action"] for e in events}
    for required in (
        "skill_upload",
        "skill_enable",
        "skill_disable",
        "skill_assign",
        "skill_unassign",
        "skill_delete",
    ):
        assert required in seen_actions, f"missing audit action {required!r} in {seen_actions}"

    upload_event = _last_with_action(events, "skill_upload")
    assert upload_event["user_id"] == "ops-root"
    assert upload_event["status"] == "success"
    assert upload_event["event_type"] == "agent_skills"
    assert upload_event["detail"]["skill_id"] == skill_id
    assert upload_event["detail"]["name"] == "cognitrix/audit-skill"
    assert len(upload_event["detail"]["sha256"]) == 64

    assign_event = _last_with_action(events, "skill_assign")
    assert assign_event["detail"]["agent_name"] == "QueryAgent"
    assert assign_event["detail"]["skill_id"] == skill_id


def test_rejected_upload_emits_skill_upload_rejected(
    client: TestClient, tmp_path: Path
) -> None:
    headers = _superadmin_headers()

    # Send junk bytes — not a zip.
    resp = client.post(
        "/admin/skills",
        headers=headers,
        files={"file": ("evil.zip", b"this is not a zip", "application/zip")},
    )
    assert resp.status_code == 400

    events = _audit_events(tmp_path)
    rejection = _last_with_action(events, "skill_upload_rejected")
    assert rejection["status"] == "denied"
    assert rejection["severity"] == "ALERT"
    assert rejection["detail"]["reason"] == "not_a_zip"
    assert rejection["user_id"] == "ops-root"


def test_unknown_agent_assignment_does_not_emit_skill_assign(
    client: TestClient, tmp_path: Path
) -> None:
    headers = _superadmin_headers()
    upload = client.post(
        "/admin/skills",
        headers=headers,
        files={"file": ("skill.zip", _make_zip(), "application/zip")},
    )
    skill_id = upload.json()["id"]

    # Wipe the audit log of all prior events for clarity in the assertion below.
    log_path = tmp_path / "uploads" / "audit" / "security_events.log"
    log_path.write_text("", encoding="utf-8")

    bad = client.post(
        f"/admin/skills/{skill_id}/assignments",
        headers=headers,
        json={"agent_name": "NotARealAgent"},
    )
    assert bad.status_code == 400

    # No skill_assign event should have been written.
    events = _audit_events(tmp_path)
    assert all(e["action"] != "skill_assign" for e in events), events
