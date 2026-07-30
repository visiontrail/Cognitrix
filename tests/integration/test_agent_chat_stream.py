from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from claude_agent_sdk import AssistantMessage, ResultMessage, ToolUseBlock
from fastapi.testclient import TestClient

from apps.api.agent_runtime import AgentSessionState, SDK_MCP_SERVER_NAME, get_agent_runtime
from apps.api.main import app
from tests.agent_test_utils import (
    install_scripted_sdk_client,
    read_sse_events,
    set_agent_env,
    upload_dataset,
)
from tests.auth_utils import auth_headers


def _install_success_sdk_client() -> None:
    runtime = get_agent_runtime()
    rows = [{"hire_year": 2022, "metric_value": 1}, {"hire_year": 2023, "metric_value": 2}]

    def scenario(prompt: str, options) -> dict[str, object]:  # type: ignore[no-untyped-def]
        _ = (prompt, options)
        return {
            "tool_calls": [
                {
                    "name": "list_tables",
                    "arguments": {},
                    "result": {"tables": ["dataset"]},
                },
                {
                    "name": "describe_table",
                    "arguments": {"table": "dataset"},
                    "result": {"sample_rows": rows},
                },
                {
                    "name": "execute_readonly_sql",
                    "arguments": {"sql": 'SELECT "hire_year", COUNT(*) AS metric_value FROM dataset GROUP BY 1'},
                    "result": {"rows": rows},
                },
            ],
            "final_answer": {
                "chart_type": "bar",
                "title": "入职年份统计",
                "x_key": "hire_year",
                "y_key": "metric_value",
                "series_key": None,
                "metric_name": "headcount",
                "rows": rows,
                "conclusion": "按入职年份统计员工数。",
                "scope": "当前数据集",
                "anomalies": "none",
            },
        }

    install_scripted_sdk_client(runtime, scenario)


def _install_failing_sdk_client() -> None:
    runtime = get_agent_runtime()

    class _FailingSDKClient:
        def __init__(self, *, options):  # type: ignore[no-untyped-def]
            _ = options

        async def __aenter__(self):  # type: ignore[no-untyped-def]
            raise RuntimeError("sdk failed")

        async def __aexit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
            return False

    runtime._sdk_client_factory = _FailingSDKClient


def _install_missing_resume_then_success_sdk_client() -> None:
    runtime = get_agent_runtime()
    rows = [{"department": "基站部", "metric_value": 12}]

    class _MissingResumeThenFreshSDKClient:
        def __init__(self, *, options: Any) -> None:
            self.options = options
            self.prompt = ""
            self.session_id = ""

        async def __aenter__(self) -> "_MissingResumeThenFreshSDKClient":
            if getattr(self.options, "resume", None) == "stale-claude-session":
                stderr = getattr(self.options, "stderr", None)
                if stderr is not None:
                    stderr("No conversation found with session ID: stale-claude-session")
                raise RuntimeError("Command failed with exit code 1")
            return self

        async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
            return False

        async def query(self, prompt: str, session_id: str = "default") -> None:
            self.prompt = prompt
            self.session_id = session_id

        async def receive_response(self):  # type: ignore[no-untyped-def]
            tool_name = f"mcp__{SDK_MCP_SERVER_NAME}__execute_readonly_sql"
            arguments = {
                "sql": (
                    "SELECT department, COUNT(*) AS metric_value "
                    'FROM dataset WHERE department = "基站部" GROUP BY 1'
                )
            }
            result = {"rows": rows}
            tool_use_id = "toolu_resume_recovery"
            await self._run_hooks(
                "PreToolUse",
                {
                    "hook_event_name": "PreToolUse",
                    "tool_name": tool_name,
                    "tool_input": arguments,
                    "tool_use_id": tool_use_id,
                },
                tool_use_id,
            )
            yield AssistantMessage(
                content=[ToolUseBlock(id=tool_use_id, name=tool_name, input=arguments)],
                model="claude-test",
                session_id="fresh-claude-session",
            )
            await self._run_hooks(
                "PostToolUse",
                {
                    "hook_event_name": "PostToolUse",
                    "tool_name": tool_name,
                    "tool_input": arguments,
                    "tool_use_id": tool_use_id,
                    "tool_response": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(result, ensure_ascii=False),
                            }
                        ]
                    },
                },
                tool_use_id,
            )
            final_answer = {
                "chart_type": "gauge",
                "title": "基站部人员总数",
                "x_key": "department",
                "y_key": "metric_value",
                "series_key": None,
                "metric_name": "headcount",
                "rows": rows,
                "conclusion": "基站部共有 12 人。",
                "scope": "基站部",
                "anomalies": "none",
            }
            yield ResultMessage(
                subtype="success",
                duration_ms=1,
                duration_api_ms=1,
                is_error=False,
                num_turns=1,
                session_id="fresh-claude-session",
                result=json.dumps(final_answer, ensure_ascii=False),
                structured_output=final_answer,
            )

        async def _run_hooks(self, event: str, input_data: dict[str, Any], tool_use_id: str) -> None:
            for matcher in (self.options.hooks or {}).get(event, []):
                for hook in matcher.hooks:
                    await hook(input_data, tool_use_id, {"signal": None})

    runtime._sdk_client_factory = _MissingResumeThenFreshSDKClient


def test_agent_chat_stream_emits_planning_tool_trace_spec_and_final(monkeypatch, tmp_path: Path) -> None:
    set_agent_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        dataset_table = upload_dataset(
            client,
            rows=[
                {"employee_id": "E-001", "department": "HR", "hire_year": 2022},
                {"employee_id": "E-002", "department": "HR", "hire_year": 2023},
                {"employee_id": "E-003", "department": "PM", "hire_year": 2023},
            ],
            user_id="admin",
            role="admin",
            department="HR",
            clearance=9,
        )
        headers = auth_headers(
            client,
            user_id="admin",
            project_id="north",
            role="admin",
            department="HR",
            clearance=9,
        )
        _install_success_sdk_client()

        start = time.perf_counter()
        with client.stream(
            "POST",
            "/chat/stream",
            json={
                "conversation_id": "agent-chat-stream-conv-1",
                "request_id": "agent-chat-stream-req-1",
                "user_id": "admin",
                "project_id": "north",
                "dataset_table": dataset_table,
                "message": "柱状图显示入职年份统计",
            },
            headers=headers,
        ) as response:
            assert response.status_code == 200
            events, first_chunk_at = read_sse_events(response)

    assert first_chunk_at is not None
    assert first_chunk_at - start < 2.0
    event_names = [item["event"] for item in events]
    assert "planning" in event_names
    assert "tool_use" in event_names
    assert "tool_result" in event_names
    assert event_names[-2:] == ["spec", "final"]
    final_payload = events[-1]["data"]
    assert final_payload["status"] == "completed"
    assert final_payload["tool_steps"] >= 3
    spec_payload = events[-2]["data"]
    assert spec_payload["spec"]["chart_type"] == "bar"


def test_agent_chat_stream_replays_agent_events(monkeypatch, tmp_path: Path) -> None:
    set_agent_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        dataset_table = upload_dataset(
            client,
            rows=[
                {"employee_id": "E-001", "department": "HR", "hire_year": 2022},
                {"employee_id": "E-002", "department": "HR", "hire_year": 2023},
            ],
            user_id="admin",
            role="admin",
            department="HR",
            clearance=9,
        )
        headers = auth_headers(
            client,
            user_id="admin",
            project_id="north",
            role="admin",
            department="HR",
            clearance=9,
        )
        _install_success_sdk_client()

        with client.stream(
            "POST",
            "/chat/stream",
            json={
                "conversation_id": "agent-chat-stream-conv-2",
                "request_id": "agent-chat-stream-req-2",
                "user_id": "admin",
                "project_id": "north",
                "dataset_table": dataset_table,
                "message": "柱状图显示入职年份统计",
            },
            headers=headers,
        ) as first_response:
            assert first_response.status_code == 200
            first_events, _ = read_sse_events(first_response)

        replay_from = first_events[2]["id"]
        with client.stream(
            "POST",
            "/chat/stream",
            json={
                "conversation_id": "agent-chat-stream-conv-2",
                "request_id": "agent-chat-stream-req-2-replay",
                "user_id": "admin",
                "project_id": "north",
                "dataset_table": dataset_table,
                "message": None,
                "last_event_id": replay_from,
            },
            headers=headers,
        ) as replay_response:
            assert replay_response.status_code == 200
            replay_events, _ = read_sse_events(replay_response)

    assert replay_events
    assert replay_events[0]["id"] == replay_from + 1
    assert replay_events[-1]["event"] == "final"


def test_agent_runtime_returns_failure_on_runtime_error(
    monkeypatch, tmp_path: Path
) -> None:
    # A chart request like this one is a multi-chart candidate, which would pause
    # for confirmation before the SDK is ever reached. This test is about the
    # AGENT_SDK_FAILED path, so take multi-chart planning out of the way
    # (set_agent_env clears the settings/service caches afterwards).
    monkeypatch.setenv("MULTI_CHART_GENERATION_ENABLED", "false")
    set_agent_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        dataset_table = upload_dataset(
            client,
            rows=[
                {"employee_id": "E-001", "department": "HR"},
                {"employee_id": "E-002", "department": "PM"},
            ],
            user_id="admin",
            role="admin",
            department="HR",
            clearance=9,
        )
        headers = auth_headers(
            client,
            user_id="admin",
            project_id="north",
            role="admin",
            department="HR",
            clearance=9,
        )
        _install_failing_sdk_client()

        with client.stream(
            "POST",
            "/chat/stream",
            json={
                "conversation_id": "agent-chat-stream-conv-no-fallback",
                "request_id": "agent-chat-stream-req-no-fallback",
                "user_id": "admin",
                "project_id": "north",
                "dataset_table": dataset_table,
                "message": "画一个福利等级热力图",
            },
            headers=headers,
        ) as response:
            assert response.status_code == 200
            events, _ = read_sse_events(response)

    assert [item["event"] for item in events][-2:] == ["error", "final"]
    assert events[-2]["data"]["status"] == "failed"
    assert events[-1]["data"]["status"] == "failed"


def test_agent_chat_stream_retries_fresh_session_when_resume_missing_on_stderr(
    monkeypatch,
    tmp_path: Path,
) -> None:
    set_agent_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        dataset_table = upload_dataset(
            client,
            rows=[
                {"employee_id": "E-001", "department": "基站部"},
                {"employee_id": "E-002", "department": "基站部"},
            ],
            user_id="admin",
            role="admin",
            department="HR",
            clearance=9,
        )
        headers = auth_headers(
            client,
            user_id="admin",
            project_id="north",
            role="admin",
            department="HR",
            clearance=9,
        )
        runtime = get_agent_runtime()
        runtime._store.save(  # noqa: SLF001 - integration test seeds persisted runtime state.
            AgentSessionState(
                conversation_id="agent-chat-stream-conv-stale-resume",
                agent_session_id="stale-claude-session",
                turn_count=1,
            )
        )
        _install_missing_resume_then_success_sdk_client()

        with client.stream(
            "POST",
            "/chat/stream",
            json={
                "conversation_id": "agent-chat-stream-conv-stale-resume",
                "request_id": "agent-chat-stream-req-stale-resume",
                "user_id": "admin",
                "project_id": "north",
                "dataset_table": dataset_table,
                "message": "请用 #gauge 帮我输出基站部的人员总数",
                "preferred_chart_type": "gauge",
            },
            headers=headers,
        ) as response:
            assert response.status_code == 200
            events, _ = read_sse_events(response)

    event_names = [item["event"] for item in events]
    assert "error" not in event_names
    assert event_names[-2:] == ["spec", "final"]
    assert events[-2]["data"]["spec"]["chart_type"] == "gauge"
    assert events[-1]["data"]["status"] == "completed"
    persisted = get_agent_runtime().get_persisted_session("agent-chat-stream-conv-stale-resume")
    assert persisted is not None
    assert persisted.agent_session_id == "fresh-claude-session"
