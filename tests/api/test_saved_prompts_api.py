from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.audit import clear_audit_logger_cache, get_audit_logger
from apps.api.auth import clear_auth_cache
from apps.api.config import get_settings
from apps.api.main import app
from apps.api.saved_prompts import clear_saved_prompt_store_cache
from tests.auth_utils import auth_headers, expect_error_code


def _set_minimal_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'views.db'}")
    monkeypatch.setenv("MODEL_PROVIDER_URL", "http://localhost:11434")
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    get_settings.cache_clear()
    clear_auth_cache()
    clear_audit_logger_cache()
    clear_saved_prompt_store_cache()


def test_requires_authentication(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path)
    with TestClient(app) as client:
        response = client.get("/saved-prompts")
    assert response.status_code == 401


def test_create_list_get_update_use_delete_happy_path(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path)
    with TestClient(app) as client:
        headers = auth_headers(client, user_id="alice", project_id="north", role="hr")

        created = client.post(
            "/saved-prompts",
            json={
                "name": "Travel vaccine",
                "body": "What is the travel vaccine recommendation for {country}",
                "capabilities": ["multi_chart"],
            },
            headers=headers,
        )
        assert created.status_code == 200, created.text
        prompt = created.json()["prompt"]
        assert prompt["variables"] == ["country"]
        assert prompt["capabilities"] == ["multi_chart"]
        prompt_id = prompt["id"]

        listed = client.get("/saved-prompts", params={"query": "travel"}, headers=headers)
        assert listed.status_code == 200
        assert [p["id"] for p in listed.json()["prompts"]] == [prompt_id]

        fetched = client.get(f"/saved-prompts/{prompt_id}", headers=headers)
        assert fetched.status_code == 200
        assert fetched.json()["prompt"]["id"] == prompt_id

        updated = client.patch(
            f"/saved-prompts/{prompt_id}",
            json={"body": "Recommend for {country} in {month}"},
            headers=headers,
        )
        assert updated.status_code == 200
        assert updated.json()["prompt"]["variables"] == ["country", "month"]

        used = client.post(f"/saved-prompts/{prompt_id}/use", headers=headers)
        assert used.status_code == 200
        assert used.json()["prompt"]["usage_count"] == 1

        deleted = client.delete(f"/saved-prompts/{prompt_id}", headers=headers)
        assert deleted.status_code == 200
        assert deleted.json()["status"] == "archived"

        # Archived prompts are hidden from default list and cannot be used.
        assert client.get("/saved-prompts", headers=headers).json()["prompts"] == []
        rejected = client.post(f"/saved-prompts/{prompt_id}/use", headers=headers)
        assert rejected.status_code == 409


def test_validation_rejects_empty_and_invalid(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path)
    with TestClient(app) as client:
        headers = auth_headers(client, user_id="alice", project_id="north", role="hr")

        empty = client.post("/saved-prompts", json={"name": "", "body": "x"}, headers=headers)
        assert empty.status_code == 422

        bad_var = client.post(
            "/saved-prompts",
            json={"name": "Bad", "body": "Compare {2026_month}"},
            headers=headers,
        )
        expect_error_code(bad_var, "PROMPT_VARIABLE_INVALID", status_code=422)

        bad_cap = client.post(
            "/saved-prompts",
            json={"name": "Bad cap", "body": "ok", "capabilities": ["raw_execute_sql"]},
            headers=headers,
        )
        expect_error_code(bad_cap, "PROMPT_CAPABILITY_INVALID", status_code=422)


def test_duplicate_active_name_rejected(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path)
    with TestClient(app) as client:
        headers = auth_headers(client, user_id="alice", project_id="north", role="hr")
        client.post("/saved-prompts", json={"name": "Report", "body": "body"}, headers=headers)
        dup = client.post("/saved-prompts", json={"name": "report", "body": "body2"}, headers=headers)
        expect_error_code(dup, "PROMPT_NAME_TAKEN", status_code=409)


def test_user_isolation(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path)
    with TestClient(app) as client:
        alice = auth_headers(client, user_id="alice", project_id="north", role="hr")
        bob = auth_headers(client, user_id="bob", project_id="north", role="hr")

        created = client.post(
            "/saved-prompts",
            json={"name": "Secret", "body": "secret {x}"},
            headers=alice,
        )
        prompt_id = created.json()["prompt"]["id"]

        # Bob cannot read, update, use, or delete Alice's prompt.
        assert client.get(f"/saved-prompts/{prompt_id}", headers=bob).status_code == 404
        assert client.patch(
            f"/saved-prompts/{prompt_id}", json={"name": "hijack"}, headers=bob
        ).status_code == 404
        assert client.post(f"/saved-prompts/{prompt_id}/use", headers=bob).status_code == 404
        assert client.delete(f"/saved-prompts/{prompt_id}", headers=bob).status_code == 404

        # Bob's list never contains Alice's prompt.
        bob_list = client.get("/saved-prompts", headers=bob).json()["prompts"]
        assert bob_list == []


def test_audit_events_exclude_prompt_content(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path)
    with TestClient(app) as client:
        headers = auth_headers(client, user_id="alice", project_id="north", role="hr")
        created = client.post(
            "/saved-prompts",
            json={
                "name": "Confidential strategy",
                "body": "Analyze {department} attrition secret-detail",
                "capabilities": ["data_labels"],
            },
            headers=headers,
        )
        prompt_id = created.json()["prompt"]["id"]
        client.post(f"/saved-prompts/{prompt_id}/use", headers=headers)
        client.delete(f"/saved-prompts/{prompt_id}", headers=headers)

    events = get_audit_logger().query(action=None, limit=200)
    prompt_events = [e for e in events if e["event_type"] == "saved_prompt"]
    actions = {e["action"] for e in prompt_events}
    assert {"saved_prompt_create", "saved_prompt_use", "saved_prompt_delete"} <= actions

    serialized = json.dumps(prompt_events, ensure_ascii=False)
    assert "Confidential strategy" not in serialized
    assert "secret-detail" not in serialized
    assert "attrition" not in serialized
    # Metadata is still present.
    create_event = next(e for e in prompt_events if e["action"] == "saved_prompt_create")
    assert create_event["detail"]["variable_count"] == 1
    assert create_event["detail"]["capabilities"] == ["data_labels"]
    assert create_event["detail"]["prompt_id"] == prompt_id
