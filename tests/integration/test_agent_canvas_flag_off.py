from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.agent_canvas import CANVAS_TOOL_NAMES, get_agent_canvas_run_store
from apps.api.agent_guardrails import AgentGuardrails
from apps.api.agent_prompting import build_agent_system_prompt
from apps.api.agent_runtime import get_agent_runtime
from apps.api.main import app
from tests.agent_test_utils import read_sse_events, set_agent_env
from tests.auth_utils import auth_headers

# Regression guard for the rollout contract (proposal "No breaking changes"):
# with AGENT_CANVAS_MODE_ENABLED=false, no canvas tools are registered, no new
# SSE event types are emitted, the system prompt is unchanged, and agent-mode
# requests fail with a typed error without creating any run state.


def test_flag_off_excludes_canvas_tools_everywhere(monkeypatch, tmp_path: Path) -> None:
    set_agent_env(monkeypatch, tmp_path)  # AGENT_CANVAS_MODE_ENABLED defaults to false

    guardrails = AgentGuardrails()
    for tool_name in CANVAS_TOOL_NAMES:
        assert tool_name not in guardrails.allowed_tools
        assert tool_name not in guardrails.agent_mode_allowed_tools

    runtime = get_agent_runtime()
    for tool_name in CANVAS_TOOL_NAMES:
        assert tool_name not in runtime._active_tool_names  # noqa: SLF001
        assert all(tool_name not in sdk_name for sdk_name in runtime._sdk_tool_names)  # noqa: SLF001


def test_flag_off_leaves_system_prompt_unchanged(monkeypatch, tmp_path: Path) -> None:
    set_agent_env(monkeypatch, tmp_path)
    prompt = build_agent_system_prompt(web_search_enabled=False)
    for marker in ("add_section", "place_chart", "finish_dashboard", "add_text_block", "canvas"):
        assert marker not in prompt


def test_flag_off_rejects_agent_mode_requests_with_typed_error(monkeypatch, tmp_path: Path) -> None:
    set_agent_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        headers = auth_headers(client, user_id="admin", project_id="north", role="admin")
        created = client.post("/workspaces", json={"name": "Off WS"}, headers=headers)
        workspace_id = str(created.json()["workspace_id"])

        with client.stream(
            "POST",
            "/chat/stream",
            json={
                "conversation_id": "flag-off-conv",
                "request_id": "flag-off-req",
                "user_id": "admin",
                "project_id": "north",
                "workspace_id": workspace_id,
                "dataset_table": "",
                "message": "生成销售仪表盘",
                "agent_mode": True,
                "canvas_format": "web-design",
            },
            headers=headers,
        ) as response:
            assert response.status_code == 200
            events, _ = read_sse_events(response)

        event_names = [item["event"] for item in events]
        assert "canvas_op" not in event_names
        assert "outline" not in event_names
        assert event_names == ["error", "final"]
        assert events[0]["data"]["code"] == "AGENT_CANVAS_MODE_DISABLED"
        assert events[-1]["data"]["status"] == "failed"

        # No run state was created and the run endpoints stay dark (404).
        store = get_agent_canvas_run_store()
        assert store.get_latest_run(workspace_id=workspace_id, user_id="admin") is None
        assert (
            client.get(
                "/chat/agent-runs/active", params={"workspace_id": workspace_id}, headers=headers
            ).status_code
            == 404
        )
        assert client.post("/chat/agent-runs/any-id/stop", headers=headers).status_code == 404


def test_flag_off_normal_turn_emits_only_legacy_event_types(monkeypatch, tmp_path: Path) -> None:
    from tests.integration.test_agent_chat_stream import _install_success_sdk_client
    from tests.agent_test_utils import upload_dataset

    set_agent_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        dataset_table = upload_dataset(
            client,
            rows=[{"employee_id": "E-001", "department": "HR", "hire_year": 2022}],
            user_id="admin",
            role="admin",
            department="HR",
            clearance=9,
        )
        headers = auth_headers(client, user_id="admin", project_id="north", role="admin")
        _install_success_sdk_client()

        with client.stream(
            "POST",
            "/chat/stream",
            json={
                "conversation_id": "flag-off-normal-conv",
                "request_id": "flag-off-normal-req",
                "user_id": "admin",
                "project_id": "north",
                "dataset_table": dataset_table,
                "message": "柱状图显示入职年份统计",
            },
            headers=headers,
        ) as response:
            events, _ = read_sse_events(response)

    legacy_event_types = {
        "planning",
        "reasoning",
        "tool_use",
        "tool_result",
        "tool",
        "confirmation_required",
        "spec",
        "final",
        "error",
    }
    assert {item["event"] for item in events} <= legacy_event_types
