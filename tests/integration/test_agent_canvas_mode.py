from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

import pandas as pd
import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock
from fastapi.testclient import TestClient

from apps.api.agent_canvas import (
    clear_agent_canvas_run_store_cache,
    get_agent_canvas_run_store,
)
from apps.api.agent_canvas_mode import (
    clear_agent_canvas_mode_service_cache,
    get_agent_canvas_mode_service,
)
from apps.api.config import get_settings
from apps.api.datasets import get_dataset_service
from apps.api.main import app
from apps.api.workspace_state import clear_workspace_state_store_cache, get_workspace_state_store
from apps.api.workspaces import clear_workspace_service_cache
from tests.agent_test_utils import read_sse_events, set_agent_env
from tests.auth_utils import auth_headers

ScriptFn = Callable[..., Awaitable[dict[str, Any] | None]]


def _set_canvas_env(monkeypatch, tmp_path: Path, **overrides: str) -> None:
    monkeypatch.setenv("AGENT_CANVAS_MODE_ENABLED", "true")
    for key, value in overrides.items():
        monkeypatch.setenv(key, value)
    set_agent_env(monkeypatch, tmp_path)
    clear_agent_canvas_run_store_cache()
    clear_workspace_state_store_cache()
    clear_workspace_service_cache()
    clear_agent_canvas_mode_service_cache()


def _create_workspace(client: TestClient, headers: dict[str, str], name: str = "Canvas WS") -> str:
    response = client.post("/workspaces", json={"name": name}, headers=headers)
    assert response.status_code == 200, response.text
    return str(response.json()["workspace_id"])


def _seed_workspace_dataset(workspace_id: str, *, user_id: str = "admin", project_id: str = "north") -> None:
    dataframe = pd.DataFrame(
        [
            {"employee_id": "E-001", "department": "HR"},
            {"employee_id": "E-002", "department": "HR"},
            {"employee_id": "E-003", "department": "PM"},
        ]
    )
    service = get_dataset_service(get_settings().upload_dir)
    with service.session_manager.connection(user_id, project_id, workspace_id=workspace_id) as conn:
        conn.register("seed_df", dataframe)
        conn.execute('CREATE OR REPLACE TABLE "employees" AS SELECT * FROM seed_df')
        conn.unregister("seed_df")


def _install_scripted_canvas_client(scripts: list[ScriptFn]) -> None:
    """Fake SDK client that drives the REAL tool pipeline: each script receives
    an `invoke(tool_name, args)` that goes through guardrails, ToolCallingService,
    the op log, and SSE emission — exactly like a live provider's tool calls."""
    service = get_agent_canvas_mode_service()
    queue = list(scripts)

    class _ScriptedCanvasClient:
        def __init__(self, *, options: Any) -> None:
            self.options = options
            self.prompt = ""

        async def __aenter__(self) -> "_ScriptedCanvasClient":
            return self

        async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
            return False

        async def query(self, prompt: str, session_id: str = "default") -> None:
            self.prompt = prompt

        async def receive_response(self):  # type: ignore[no-untyped-def]
            script = queue.pop(0)
            invoker = self.options._cognitrix_tool_invoker  # noqa: SLF001 - test seam

            async def invoke(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
                raw = await invoker(tool_name, arguments)
                text = raw["content"][0]["text"]
                return json.loads(text)

            final = await script(invoke)
            yield ResultMessage(
                subtype="success",
                duration_ms=1,
                duration_api_ms=1,
                is_error=False,
                num_turns=1,
                session_id="canvas-session",
                result=json.dumps(final or {}, ensure_ascii=False),
                structured_output=final,
            )

    service._sdk_client_factory = _ScriptedCanvasClient  # noqa: SLF001 - test seam


OUTLINE = {
    "title": "员工概览",
    "sections": [
        {
            "key": "s1",
            "title": "概览",
            "items": [
                {
                    "key": "c1",
                    "kind": "chart",
                    "title": "总人数",
                    "description": "员工总数",
                    "chart_type": "single_value",
                    "size_preset": "kpi",
                },
                {
                    "key": "c2",
                    "kind": "chart",
                    "title": "部门人数",
                    "description": "按部门统计",
                    "chart_type": "bar",
                    "size_preset": "half",
                },
                {"key": "t1", "kind": "text", "style": "body", "content": "说明文字"},
            ],
        }
    ],
}


async def _outline_script(invoke) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    await invoke("list_tables", {})
    return OUTLINE


async def _execution_script(invoke) -> None:  # type: ignore[no-untyped-def]
    section = await invoke("add_section", {"title": "概览"})
    section_id = section["section_id"]
    await invoke(
        "place_chart",
        {
            "section_id": section_id,
            "title": "总人数",
            "chart_type": "single_value",
            "size_preset": "kpi",
            "sql": "SELECT 'total' AS segment, COUNT(*) AS metric_value FROM employees",
        },
    )
    await invoke(
        "place_chart",
        {
            "section_id": section_id,
            "title": "部门人数",
            "chart_type": "bar",
            "size_preset": "half",
            "sql": "SELECT department AS segment, COUNT(*) AS metric_value FROM employees GROUP BY 1",
        },
    )
    await invoke("add_text_block", {"section_id": section_id, "content": "说明文字", "style": "body"})
    await invoke("finish_dashboard", {"summary": "已完成 2 个图表。"})
    return None


def _agent_mode_body(workspace_id: str, **extra: Any) -> dict[str, Any]:
    return {
        "conversation_id": "canvas-conv-1",
        "request_id": f"canvas-req-{time.time_ns()}",
        "user_id": "admin",
        "project_id": "north",
        "workspace_id": workspace_id,
        "dataset_table": "employees",
        "message": "生成员工数据仪表盘",
        "agent_mode": True,
        "canvas_format": "web-design",
        **extra,
    }


@pytest.mark.parametrize(
    "canvas_format",
    [
        "infinite",
        "web-design",
        "a4-portrait",
        "a4-landscape",
        "a3-portrait",
        "letter-portrait",
        "wide-16-9",
    ],
)
def test_outline_accepts_every_publishable_canvas_format(
    monkeypatch, tmp_path: Path, canvas_format: str
) -> None:
    _set_canvas_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        headers = auth_headers(client, user_id="admin", project_id="north", role="admin")
        workspace_id = _create_workspace(client, headers, name=f"Canvas {canvas_format}")
        _seed_workspace_dataset(workspace_id)
        _install_scripted_canvas_client([_outline_script])

        with client.stream(
            "POST",
            "/chat/stream",
            json=_agent_mode_body(workspace_id, canvas_format=canvas_format),
            headers=headers,
        ) as response:
            assert response.status_code == 200
            events, _ = read_sse_events(response)

    assert not [event for event in events if event["event"] == "error"]
    confirmation = next(
        event["data"] for event in events if event["event"] == "confirmation_required"
    )
    assert confirmation["canvas_format"] == canvas_format


def test_outline_rejects_unknown_canvas_format_before_planning(monkeypatch, tmp_path: Path) -> None:
    _set_canvas_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        headers = auth_headers(client, user_id="admin", project_id="north", role="admin")
        workspace_id = _create_workspace(client, headers, name="Unsupported Canvas")
        with client.stream(
            "POST",
            "/chat/stream",
            json=_agent_mode_body(workspace_id, canvas_format="poster-custom"),
            headers=headers,
        ) as response:
            events, _ = read_sse_events(response)

    assert events[0]["event"] == "error"
    assert events[0]["data"]["code"] == "AGENT_CANVAS_FORMAT_UNSUPPORTED"


def test_full_outline_approve_run_completed(monkeypatch, tmp_path: Path) -> None:
    _set_canvas_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        headers = auth_headers(client, user_id="admin", project_id="north", role="admin")
        workspace_id = _create_workspace(client, headers)
        _seed_workspace_dataset(workspace_id)
        _install_scripted_canvas_client([_outline_script, _execution_script])

        # ---- Phase 1: outline pauses for approval; no canvas_op yet ----
        with client.stream(
            "POST", "/chat/stream", json=_agent_mode_body(workspace_id), headers=headers
        ) as response:
            assert response.status_code == 200
            outline_events, _ = read_sse_events(response)

        event_names = [item["event"] for item in outline_events]
        assert "canvas_op" not in event_names
        confirmation = next(
            item["data"] for item in outline_events if item["event"] == "confirmation_required"
        )
        assert confirmation["confirmation_type"] == "dashboard_outline"
        assert confirmation["proposed_chart_count"] == 2
        assert confirmation["sections"][0]["items"][0]["key"] == "c1"
        final_payload = outline_events[-1]["data"]
        assert final_payload["status"] == "awaiting_confirmation"

        # ---- Phase 2: approve → detached run streams canvas ops ----
        with client.stream(
            "POST",
            "/chat/stream",
            json={
                "conversation_id": "canvas-conv-1",
                "request_id": "canvas-req-confirm",
                "user_id": "admin",
                "project_id": "north",
                "workspace_id": workspace_id,
                "dataset_table": "employees",
                "message": None,
                "agent_run_confirmation": {
                    "confirmation_id": confirmation["confirmation_id"],
                    "action": "confirm",
                },
            },
            headers=headers,
        ) as response:
            assert response.status_code == 200
            run_events, _ = read_sse_events(response)

        canvas_ops = [item["data"] for item in run_events if item["event"] == "canvas_op"]
        op_types = [op["op_type"] for op in canvas_ops]
        assert op_types == [
            "create_page",
            "add_section",
            "place_chart",
            "place_chart",
            "add_text_block",
        ]
        seqs = [op["seq"] for op in canvas_ops]
        assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
        run_id = canvas_ops[0]["run_id"]
        page_id = canvas_ops[0]["page_id"]
        assert page_id == f"agent-{run_id}"
        for op in canvas_ops:
            assert op["run_id"] == run_id
            assert op["payload"]["block_id"]

        spec_events = [item["data"] for item in run_events if item["event"] == "spec"]
        assert len(spec_events) == 2

        final_payload = run_events[-1]["data"]
        assert final_payload["status"] == "completed"
        assert final_payload["placed_count"] == 2
        assert final_payload["failed_count"] == 0
        assert final_payload["page_id"] == page_id

        # ---- Server-side state: run record, op log, chart assets ----
        run = get_agent_canvas_run_store().get_run(run_id)
        assert run is not None and run["status"] == "completed"
        assets = get_workspace_state_store().list_chart_assets(
            workspace_id=workspace_id, user_id="admin"
        )
        assert len(assets) == 2

        # ---- Re-attach surface ----
        active = client.get(
            "/chat/agent-runs/active", params={"workspace_id": workspace_id}, headers=headers
        )
        assert active.status_code == 200
        described = active.json()["run"]
        assert described["run_id"] == run_id
        assert described["status"] == "completed"
        assert described["last_seq"] == 5

        ops_response = client.get(
            f"/chat/agent-runs/{run_id}/ops", params={"after_seq": 2}, headers=headers
        )
        assert ops_response.status_code == 200
        tail_ops = ops_response.json()["ops"]
        assert [op["seq"] for op in tail_ops] == [3, 4, 5]


def test_corrected_chart_retry_replaces_placeholder_and_clears_failure_count(
    monkeypatch, tmp_path: Path
) -> None:
    _set_canvas_env(monkeypatch, tmp_path)

    async def outline(invoke) -> dict[str, Any]:  # type: ignore[no-untyped-def]
        await invoke("list_tables", {})
        return {
            "title": "员工概览",
            "sections": [
                {
                    "key": "s1",
                    "title": "概览",
                    "items": [
                        {
                            "key": "c1",
                            "kind": "chart",
                            "title": "部门人数",
                            "description": "按部门统计",
                            "chart_type": "bar",
                            "size_preset": "half",
                        }
                    ],
                }
            ],
        }

    async def execution(invoke) -> None:  # type: ignore[no-untyped-def]
        section = await invoke("add_section", {"title": "概览"})
        chart_args = {
            "section_id": section["section_id"],
            "title": "部门人数",
            "chart_type": "bar",
            "size_preset": "half",
        }
        failed = await invoke(
            "place_chart",
            {
                **chart_args,
                "sql": (
                    "SELECT missing_department AS segment, "
                    "COUNT(*) AS metric_value FROM employees GROUP BY 1"
                ),
            },
        )
        assert failed["status"] == "error_placeholder"
        corrected = await invoke(
            "place_chart",
            {
                **chart_args,
                "sql": (
                    "SELECT department AS segment, COUNT(*) AS metric_value "
                    "FROM employees GROUP BY 1"
                ),
            },
        )
        assert corrected["status"] == "placed"
        assert corrected["replaced_error_placeholder"] is True
        await invoke("finish_dashboard", {"summary": "已完成。"})
        return None

    with TestClient(app) as client:
        headers = auth_headers(client, user_id="admin", project_id="north", role="admin")
        workspace_id = _create_workspace(client, headers, name="Retry Replace WS")
        _seed_workspace_dataset(workspace_id)
        _install_scripted_canvas_client([outline, execution])

        with client.stream(
            "POST",
            "/chat/stream",
            json=_agent_mode_body(workspace_id, auto_approve=True),
            headers=headers,
        ) as response:
            events, _ = read_sse_events(response)

    chart_ops = [
        item["data"]
        for item in events
        if item["event"] == "canvas_op"
        and item["data"]["op_type"] in {"error_placeholder", "place_chart"}
    ]
    assert [item["op_type"] for item in chart_ops] == [
        "error_placeholder",
        "place_chart",
    ]
    assert chart_ops[0]["payload"]["block_id"] == chart_ops[1]["payload"]["block_id"]
    final_payload = events[-1]["data"]
    assert final_payload["status"] == "completed"
    assert final_payload["placed_count"] == 1
    assert final_payload["failed_count"] == 0
    assert final_payload["skipped_count"] == 0


def test_tail_endpoint_replays_ops_and_terminal(monkeypatch, tmp_path: Path) -> None:
    _set_canvas_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        headers = auth_headers(client, user_id="admin", project_id="north", role="admin")
        workspace_id = _create_workspace(client, headers, name="Tail WS")
        _seed_workspace_dataset(workspace_id)
        _install_scripted_canvas_client([_outline_script, _execution_script])

        with client.stream(
            "POST",
            "/chat/stream",
            json=_agent_mode_body(workspace_id, auto_approve=True),
            headers=headers,
        ) as response:
            events, _ = read_sse_events(response)
        run_id = events[-1]["data"]["run_id"]

        with client.stream(
            "GET",
            f"/chat/agent-runs/{run_id}/tail",
            params={"after_seq": 2},
            headers=headers,
        ) as tail_response:
            assert tail_response.status_code == 200
            tail_events, _ = read_sse_events(tail_response)

        tail_names = [item["event"] for item in tail_events]
        assert tail_names[:-1] == ["canvas_op"] * (len(tail_names) - 1)
        assert tail_names[-1] == "final"
        assert [item["data"]["seq"] for item in tail_events[:-1]] == [3, 4, 5]
        assert tail_events[-1]["data"]["status"] == "completed"


def test_stop_mid_run_keeps_partial_results(monkeypatch, tmp_path: Path) -> None:
    _set_canvas_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        headers = auth_headers(client, user_id="admin", project_id="north", role="admin")
        workspace_id = _create_workspace(client, headers, name="Stop WS")
        _seed_workspace_dataset(workspace_id)

        async def stopping_execution(invoke) -> None:  # type: ignore[no-untyped-def]
            section = await invoke("add_section", {"title": "概览"})
            await invoke(
                "place_chart",
                {
                    "section_id": section["section_id"],
                    "title": "总人数",
                    "chart_type": "single_value",
                    "size_preset": "kpi",
                    "sql": "SELECT 'total' AS segment, COUNT(*) AS metric_value FROM employees",
                },
            )
            # User presses stop (the endpoint sets the same cancel flag).
            service = get_agent_canvas_mode_service()
            run = get_agent_canvas_run_store().get_active_run(
                workspace_id=workspace_id, user_id="admin"
            )
            assert run is not None
            service.stop_run(run["run_id"])
            blocked = await invoke(
                "place_chart",
                {
                    "section_id": section["section_id"],
                    "title": "部门人数",
                    "chart_type": "bar",
                    "size_preset": "half",
                    "sql": "SELECT department AS segment, COUNT(*) AS metric_value FROM employees GROUP BY 1",
                },
            )
            assert blocked["error"]["code"] == "AGENT_RUN_STOPPED"
            return None

        _install_scripted_canvas_client([_outline_script, stopping_execution])

        with client.stream(
            "POST",
            "/chat/stream",
            json=_agent_mode_body(workspace_id, auto_approve=True),
            headers=headers,
        ) as response:
            assert response.status_code == 200
            events, _ = read_sse_events(response)

        final_payload = events[-1]["data"]
        assert final_payload["status"] == "stopped"
        assert final_payload["placed_count"] == 1

        run_id = final_payload["run_id"]
        ops = get_agent_canvas_run_store().list_ops_after(run_id=run_id, after_seq=0)
        assert [op["op_type"] for op in ops] == ["create_page", "add_section", "place_chart"]


def test_disconnect_mid_run_keeps_appending_ops(monkeypatch, tmp_path: Path) -> None:
    _set_canvas_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        headers = auth_headers(client, user_id="admin", project_id="north", role="admin")
        workspace_id = _create_workspace(client, headers, name="Disc WS")
        _seed_workspace_dataset(workspace_id)

        async def slow_execution(invoke) -> None:  # type: ignore[no-untyped-def]
            section = await invoke("add_section", {"title": "概览"})
            section_id = section["section_id"]
            await invoke(
                "place_chart",
                {
                    "section_id": section_id,
                    "title": "总人数",
                    "chart_type": "single_value",
                    "size_preset": "kpi",
                    "sql": "SELECT 'total' AS segment, COUNT(*) AS metric_value FROM employees",
                },
            )
            # Give the client time to disconnect before the run continues.
            await asyncio.sleep(0.3)
            await invoke(
                "place_chart",
                {
                    "section_id": section_id,
                    "title": "部门人数",
                    "chart_type": "bar",
                    "size_preset": "half",
                    "sql": "SELECT department AS segment, COUNT(*) AS metric_value FROM employees GROUP BY 1",
                },
            )
            await invoke("finish_dashboard", {"summary": "完成"})
            return None

        _install_scripted_canvas_client([_outline_script, slow_execution])

        # Disconnect after the first few frames.
        with client.stream(
            "POST",
            "/chat/stream",
            json=_agent_mode_body(workspace_id, auto_approve=True),
            headers=headers,
        ) as response:
            assert response.status_code == 200
            seen = 0
            for _line in response.iter_lines():
                seen += 1
                if seen >= 8:
                    break

        # The detached run keeps appending ops and finalizes on its own.
        run_id: str | None = None
        deadline = time.time() + 10
        while time.time() < deadline:
            active = client.get(
                "/chat/agent-runs/active", params={"workspace_id": workspace_id}, headers=headers
            )
            run = active.json()["run"]
            if run is not None:
                run_id = run["run_id"]
                if run["status"] == "completed":
                    break
            time.sleep(0.1)

        assert run_id is not None
        run = get_agent_canvas_run_store().get_run(run_id)
        assert run is not None and run["status"] == "completed"
        ops = get_agent_canvas_run_store().list_ops_after(run_id=run_id, after_seq=0)
        assert [op["op_type"] for op in ops] == [
            "create_page",
            "add_section",
            "place_chart",
            "place_chart",
        ]


def test_budget_exhaustion_finalizes_partial(monkeypatch, tmp_path: Path) -> None:
    _set_canvas_env(monkeypatch, tmp_path, AGENT_MODE_MAX_CHARTS="1")

    with TestClient(app) as client:
        headers = auth_headers(client, user_id="admin", project_id="north", role="admin")
        workspace_id = _create_workspace(client, headers, name="Budget WS")
        _seed_workspace_dataset(workspace_id)

        async def greedy_execution(invoke) -> None:  # type: ignore[no-untyped-def]
            section = await invoke("add_section", {"title": "概览"})
            section_id = section["section_id"]
            first = await invoke(
                "place_chart",
                {
                    "section_id": section_id,
                    "title": "总人数",
                    "chart_type": "single_value",
                    "size_preset": "kpi",
                    "sql": "SELECT 'total' AS segment, COUNT(*) AS metric_value FROM employees",
                },
            )
            assert first["status"] == "placed"
            second = await invoke(
                "place_chart",
                {
                    "section_id": section_id,
                    "title": "部门人数",
                    "chart_type": "bar",
                    "size_preset": "half",
                    "sql": "SELECT department AS segment, COUNT(*) AS metric_value FROM employees GROUP BY 1",
                },
            )
            assert second["error"]["code"] == "AGENT_MODE_CHART_BUDGET_EXCEEDED"
            await invoke("finish_dashboard", {"summary": "预算内完成"})
            return None

        _install_scripted_canvas_client([_outline_script, greedy_execution])

        with client.stream(
            "POST",
            "/chat/stream",
            json=_agent_mode_body(workspace_id, auto_approve=True),
            headers=headers,
        ) as response:
            assert response.status_code == 200
            events, _ = read_sse_events(response)

        final_payload = events[-1]["data"]
        assert final_payload["status"] == "partial"
        assert final_payload["code"] == "AGENT_MODE_BUDGET_EXCEEDED"
        assert final_payload["placed_count"] == 1


def test_confirmation_validation_rejects_stale_and_unknown_items(monkeypatch, tmp_path: Path) -> None:
    _set_canvas_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        headers = auth_headers(client, user_id="admin", project_id="north", role="admin")
        workspace_id = _create_workspace(client, headers, name="Confirm WS")
        _seed_workspace_dataset(workspace_id)
        _install_scripted_canvas_client([_outline_script])

        with client.stream(
            "POST", "/chat/stream", json=_agent_mode_body(workspace_id), headers=headers
        ) as response:
            outline_events, _ = read_sse_events(response)
        confirmation = next(
            item["data"] for item in outline_events if item["event"] == "confirmation_required"
        )

        def confirm(body_extra: dict[str, Any]) -> list[dict[str, Any]]:
            with client.stream(
                "POST",
                "/chat/stream",
                json={
                    "conversation_id": "canvas-conv-1",
                    "request_id": f"confirm-{time.time_ns()}",
                    "user_id": "admin",
                    "project_id": "north",
                    "workspace_id": workspace_id,
                    "dataset_table": "employees",
                    "message": None,
                    **body_extra,
                },
                headers=headers,
            ) as confirm_response:
                events, _ = read_sse_events(confirm_response)
            return events

        # Unknown confirmation id.
        events = confirm(
            {"agent_run_confirmation": {"confirmation_id": "dash-unknown", "action": "confirm"}}
        )
        assert events[0]["data"]["code"] == "AGENT_CANVAS_CONFIRMATION_MISSING"

        # Unknown selected item keys.
        events = confirm(
            {
                "agent_run_confirmation": {
                    "confirmation_id": confirmation["confirmation_id"],
                    "action": "confirm",
                    "selected_item_keys": ["c1", "nonexistent"],
                }
            }
        )
        assert events[0]["data"]["code"] == "AGENT_CANVAS_CONFIRMATION_ITEM_MISMATCH"

        # Cancel discards the run without any canvas mutation.
        events = confirm(
            {
                "agent_run_confirmation": {
                    "confirmation_id": confirmation["confirmation_id"],
                    "action": "cancel",
                }
            }
        )
        assert events[-1]["data"]["status"] == "canceled"
        run = get_agent_canvas_run_store().get_run_by_confirmation(
            confirmation["confirmation_id"]
        )
        assert run is not None and run["status"] == "canceled"
        assert get_agent_canvas_run_store().count_ops(run_id=run["run_id"]) == 0

        # A canceled confirmation can no longer start a run (stale).
        events = confirm(
            {
                "agent_run_confirmation": {
                    "confirmation_id": confirmation["confirmation_id"],
                    "action": "confirm",
                }
            }
        )
        assert events[0]["data"]["code"] == "AGENT_CANVAS_CONFIRMATION_STALE"


def _install_failing_canvas_client(
    *,
    text: str,
    is_error: bool,
    api_error_status: int | None,
    terminal_reason: str | None = None,
    subtype: str = "success",
    num_turns: int = 1,
    observed_options: list[Any] | None = None,
) -> None:
    """Fake SDK client reproducing a provider-level rejection.

    The real SDK does not raise on HTTP 4xx from the gateway: it emits the
    provider's message as a synthetic assistant TextBlock plus a ResultMessage
    with is_error=True, so the outline phase sees unparseable text.
    """
    service = get_agent_canvas_mode_service()
    # `api_error_status`/`terminal_reason` only exist on newer claude-agent-sdk
    # releases (the container runs one, the test venv may not), so attach them
    # out-of-band rather than pinning the test to one SDK version.
    result_extras = {"api_error_status": api_error_status, "terminal_reason": terminal_reason}

    def _make_result() -> ResultMessage:
        message = ResultMessage(
            subtype=subtype,
            duration_ms=607,
            duration_api_ms=0,
            is_error=is_error,
            num_turns=num_turns,
            session_id="canvas-session",
            result=text,
            structured_output=None,
        )
        for key, value in result_extras.items():
            setattr(message, key, value)
        return message

    class _FailingCanvasClient:
        def __init__(self, *, options: Any) -> None:
            self.options = options
            if observed_options is not None:
                observed_options.append(options)

        async def __aenter__(self) -> "_FailingCanvasClient":
            return self

        async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
            return False

        async def query(self, prompt: str, session_id: str = "default") -> None:
            return None

        async def receive_response(self):  # type: ignore[no-untyped-def]
            yield AssistantMessage(content=[TextBlock(text=text)], model="<synthetic>")
            yield _make_result()

    service._sdk_client_factory = _FailingCanvasClient  # noqa: SLF001 - test seam


def test_provider_auth_failure_reports_provider_error(monkeypatch, tmp_path: Path, caplog) -> None:
    """A 401 from the gateway must not masquerade as a bad user prompt."""
    _set_canvas_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        headers = auth_headers(client, user_id="admin", project_id="north", role="admin")
        workspace_id = _create_workspace(client, headers, name="Auth Fail WS")
        _seed_workspace_dataset(workspace_id)
        _install_failing_canvas_client(
            text="Invalid API key · Fix external API key",
            is_error=True,
            api_error_status=401,
            terminal_reason="api_error",
        )

        with caplog.at_level(logging.WARNING, logger="cognitrix.agent_canvas"):
            with client.stream(
                "POST", "/chat/stream", json=_agent_mode_body(workspace_id), headers=headers
            ) as response:
                assert response.status_code == 200
                events, _ = read_sse_events(response)

    error_payload = next(item["data"] for item in events if item["event"] == "error")
    assert error_payload["code"] == "AGENT_CANVAS_PROVIDER_ERROR"
    assert "401" in error_payload["message"]
    assert "Invalid API key" in error_payload["message"]
    assert events[-1]["data"]["code"] == "AGENT_CANVAS_PROVIDER_ERROR"

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "agent_canvas_provider_error" in logged
    assert "api_error_status=401" in logged
    assert "agent_canvas_outline_no_json" in logged


def test_outline_without_json_reports_outline_failed(monkeypatch, tmp_path: Path, caplog) -> None:
    """A model that answers in prose keeps the retry-your-prompt message."""
    _set_canvas_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        headers = auth_headers(client, user_id="admin", project_id="north", role="admin")
        workspace_id = _create_workspace(client, headers, name="No JSON WS")
        _seed_workspace_dataset(workspace_id)
        _install_failing_canvas_client(
            text="抱歉，我需要更多信息才能规划仪表盘。",
            is_error=False,
            api_error_status=None,
        )

        with caplog.at_level(logging.WARNING, logger="cognitrix.agent_canvas"):
            with client.stream(
                "POST", "/chat/stream", json=_agent_mode_body(workspace_id), headers=headers
            ) as response:
                events, _ = read_sse_events(response)

    error_payload = next(item["data"] for item in events if item["event"] == "error")
    assert error_payload["code"] == "AGENT_CANVAS_OUTLINE_FAILED"
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "agent_canvas_no_final_json" in logged
    assert "抱歉，我需要更多信息才能规划仪表盘。" in logged


def test_outline_step_budget_comes_from_settings(monkeypatch, tmp_path: Path) -> None:
    """The planning turn's max_turns is configurable, not a hard-coded constant."""
    _set_canvas_env(monkeypatch, tmp_path, AGENT_MODE_OUTLINE_MAX_STEPS="23")

    observed: list[Any] = []
    with TestClient(app) as client:
        headers = auth_headers(client, user_id="admin", project_id="north", role="admin")
        workspace_id = _create_workspace(client, headers, name="Budget Cfg WS")
        _seed_workspace_dataset(workspace_id)
        _install_failing_canvas_client(
            text="prose only",
            is_error=False,
            api_error_status=None,
            observed_options=observed,
        )

        with client.stream(
            "POST", "/chat/stream", json=_agent_mode_body(workspace_id), headers=headers
        ) as response:
            read_sse_events(response)

    assert [options.max_turns for options in observed] == [23]
    assert get_settings().agent_mode_outline_max_steps == 23


def test_outline_max_turns_exhaustion_is_not_a_provider_error(
    monkeypatch, tmp_path: Path, caplog
) -> None:
    """Spending the outline step budget must not read as a bad prompt or a 401."""
    _set_canvas_env(monkeypatch, tmp_path, AGENT_MODE_OUTLINE_MAX_STEPS="9")

    with TestClient(app) as client:
        headers = auth_headers(client, user_id="admin", project_id="north", role="admin")
        workspace_id = _create_workspace(client, headers, name="Max Turns WS")
        _seed_workspace_dataset(workspace_id)
        _install_failing_canvas_client(
            text="我先看看有哪些表……",
            is_error=True,
            api_error_status=None,
            subtype="error_max_turns",
            num_turns=9,
        )

        with caplog.at_level(logging.WARNING, logger="cognitrix.agent_canvas"):
            with client.stream(
                "POST", "/chat/stream", json=_agent_mode_body(workspace_id), headers=headers
            ) as response:
                events, _ = read_sse_events(response)

    error_payload = next(item["data"] for item in events if item["event"] == "error")
    assert error_payload["code"] == "AGENT_CANVAS_OUTLINE_BUDGET_EXCEEDED"
    assert "9/9" in error_payload["message"]
    assert "AGENT_MODE_OUTLINE_MAX_STEPS" in error_payload["message"]
    assert events[-1]["data"]["code"] == "AGENT_CANVAS_OUTLINE_BUDGET_EXCEEDED"

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "agent_canvas_max_turns_exhausted" in logged
    assert "agent_canvas_provider_error" not in logged


def test_deselected_items_are_skipped(monkeypatch, tmp_path: Path) -> None:
    _set_canvas_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        headers = auth_headers(client, user_id="admin", project_id="north", role="admin")
        workspace_id = _create_workspace(client, headers, name="Select WS")
        _seed_workspace_dataset(workspace_id)

        async def single_chart_execution(invoke) -> None:  # type: ignore[no-untyped-def]
            service = get_agent_canvas_mode_service()
            run = get_agent_canvas_run_store().get_active_run(
                workspace_id=workspace_id, user_id="admin"
            )
            assert run is not None
            approved = (run["outline"] or {}).get("outline") or {}
            chart_items = [
                item
                for section in approved.get("sections", [])
                for item in section.get("items", [])
                if item.get("kind") == "chart"
            ]
            # Only the selected chart item survived the approval filter.
            assert [item["key"] for item in chart_items] == ["c2"]
            _ = service
            section = await invoke("add_section", {"title": "概览"})
            await invoke(
                "place_chart",
                {
                    "section_id": section["section_id"],
                    "title": "部门人数",
                    "chart_type": "bar",
                    "size_preset": "half",
                    "sql": "SELECT department AS segment, COUNT(*) AS metric_value FROM employees GROUP BY 1",
                },
            )
            await invoke("finish_dashboard", {"summary": "完成"})
            return None

        _install_scripted_canvas_client([_outline_script, single_chart_execution])

        with client.stream(
            "POST", "/chat/stream", json=_agent_mode_body(workspace_id), headers=headers
        ) as response:
            outline_events, _ = read_sse_events(response)
        confirmation = next(
            item["data"] for item in outline_events if item["event"] == "confirmation_required"
        )

        with client.stream(
            "POST",
            "/chat/stream",
            json={
                "conversation_id": "canvas-conv-1",
                "request_id": "canvas-req-select",
                "user_id": "admin",
                "project_id": "north",
                "workspace_id": workspace_id,
                "dataset_table": "employees",
                "message": None,
                "agent_run_confirmation": {
                    "confirmation_id": confirmation["confirmation_id"],
                    "action": "confirm",
                    "selected_item_keys": ["c2"],
                },
            },
            headers=headers,
        ) as response:
            run_events, _ = read_sse_events(response)

        final_payload = run_events[-1]["data"]
        assert final_payload["status"] == "completed"
        assert final_payload["placed_count"] == 1


# ---------------------------------------------------------------------------
# Multi-page runs: an outline that breaks down by entity produces one canvas
# page (sidebar entry) per entity instead of one flat page.
# ---------------------------------------------------------------------------

MULTI_PAGE_OUTLINE = {
    "title": "部门人力概览",
    "pages": [
        {
            "key": "p1",
            "title": "总览",
            "sections": [
                {
                    "key": "s1",
                    "title": "整体",
                    "items": [
                        {
                            "key": "c1",
                            "kind": "chart",
                            "title": "总人数",
                            "chart_type": "single_value",
                            "size_preset": "kpi",
                        }
                    ],
                }
            ],
        },
        {
            "key": "p2",
            "title": "HR",
            "sections": [
                {
                    "key": "s2",
                    "title": "人员结构",
                    "level": 2,
                    "items": [
                        {
                            "key": "c2",
                            "kind": "chart",
                            "title": "HR 人数",
                            "chart_type": "bar",
                            "size_preset": "half",
                        }
                    ],
                }
            ],
        },
    ],
}


async def _multi_page_outline_script(invoke) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    await invoke("list_tables", {})
    return MULTI_PAGE_OUTLINE


async def _multi_page_execution_script(invoke) -> None:  # type: ignore[no-untyped-def]
    first = await invoke("add_section", {"title": "整体"})
    await invoke(
        "place_chart",
        {
            "section_id": first["section_id"],
            "title": "总人数",
            "chart_type": "single_value",
            "size_preset": "kpi",
            "sql": "SELECT 'total' AS segment, COUNT(*) AS metric_value FROM employees",
        },
    )
    page = await invoke("add_page", {"title": "HR"})
    second = await invoke("add_section", {"title": "人员结构", "level": 2})
    assert second["page_id"] == page["page_id"]
    await invoke(
        "place_chart",
        {
            "section_id": second["section_id"],
            "title": "HR 人数",
            "chart_type": "bar",
            "size_preset": "half",
            "sql": "SELECT department AS segment, COUNT(*) AS metric_value FROM employees WHERE department = 'HR' GROUP BY 1",
        },
    )
    await invoke("finish_dashboard", {"summary": "已生成 2 个页面。"})
    return None


def test_multi_page_run_creates_one_page_per_outline_page(monkeypatch, tmp_path: Path) -> None:
    _set_canvas_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        headers = auth_headers(client, user_id="admin", project_id="north", role="admin")
        workspace_id = _create_workspace(client, headers)
        _seed_workspace_dataset(workspace_id)
        _install_scripted_canvas_client(
            [_multi_page_outline_script, _multi_page_execution_script]
        )

        with client.stream(
            "POST",
            "/chat/stream",
            json=_agent_mode_body(workspace_id, auto_approve=True),
            headers=headers,
        ) as response:
            assert response.status_code == 200
            events, _ = read_sse_events(response)

        outline_payload = next(item["data"] for item in events if item["event"] == "outline")
        assert outline_payload["proposed_page_count"] == 2
        assert [page["title"] for page in outline_payload["pages"]] == ["总览", "HR"]
        assert [section["page_key"] for section in outline_payload["sections"]] == ["p1", "p2"]
        assert outline_payload["sections"][1]["level"] == 2

        canvas_ops = [item["data"] for item in events if item["event"] == "canvas_op"]
        assert [op["op_type"] for op in canvas_ops] == [
            "create_page",
            "add_section",
            "place_chart",
            "create_page",
            "add_section",
            "place_chart",
        ]
        run_id = canvas_ops[0]["run_id"]
        root_page_id = f"agent-{run_id}"
        second_page_id = canvas_ops[3]["page_id"]
        assert second_page_id != root_page_id
        # Every op carries the page it belongs to, so replay reproduces the split.
        assert [op["page_id"] for op in canvas_ops] == [
            root_page_id,
            root_page_id,
            root_page_id,
            second_page_id,
            second_page_id,
            second_page_id,
        ]
        assert canvas_ops[0]["payload"]["parent_page_id"] == ""
        assert canvas_ops[3]["payload"]["parent_page_id"] == root_page_id
        assert canvas_ops[0]["payload"]["title"] == "总览"
        assert canvas_ops[3]["payload"]["title"] == "HR"
        assert canvas_ops[4]["payload"]["level"] == 2

        final_payload = events[-1]["data"]
        assert final_payload["status"] == "completed"
        assert final_payload["placed_count"] == 2
        assert final_payload["page_count"] == 2

        # The op log replays the same page split after a disconnect.
        ops_response = client.get(
            f"/chat/agent-runs/{run_id}/ops", params={"after_seq": 0}, headers=headers
        )
        assert ops_response.status_code == 200
        replayed = ops_response.json()["ops"]
        assert [op["page_id"] for op in replayed] == [op["page_id"] for op in canvas_ops]


def test_outline_pages_are_folded_down_to_the_page_budget(monkeypatch, tmp_path: Path) -> None:
    from apps.api.agent_canvas_mode import _normalize_outline

    raw = {
        "title": "部门概览",
        "pages": [
            {
                "key": f"p{index}",
                "title": f"部门 {index}",
                "sections": [
                    {
                        "key": f"s{index}",
                        "title": "结构",
                        "items": [
                            {
                                "key": f"c{index}",
                                "kind": "chart",
                                "title": f"部门 {index} 人数",
                                "chart_type": "bar",
                                "size_preset": "half",
                            }
                        ],
                    }
                ],
            }
            for index in range(1, 6)
        ],
    }
    outline = _normalize_outline(raw, max_charts=12, max_pages=2)
    assert outline["page_count"] == 2
    assert outline["pages_truncated"] is True
    # No chart is dropped — the overflow pages' sections are folded onto the last
    # page the budget allows.
    assert outline["chart_count"] == 5
    assert {section["page_key"] for section in outline["sections"]} == {"p1", "p2"}


def test_legacy_flat_outline_still_normalizes_to_one_page(monkeypatch, tmp_path: Path) -> None:
    from apps.api.agent_canvas_mode import _normalize_outline

    outline = _normalize_outline(OUTLINE, max_charts=12, max_pages=6)
    assert outline["page_count"] == 1
    assert outline["sections"][0]["page_title"] == "员工概览"
    assert outline["sections"][0]["level"] == 1
