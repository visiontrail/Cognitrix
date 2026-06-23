from __future__ import annotations

import time
import uuid
from pathlib import Path

import anyio
from fastapi.testclient import TestClient

from apps.api.agent_runtime import AgentRequest, AgentSessionState, SDK_RUNTIME_BACKEND, SDKRunContext, get_agent_runtime
from apps.api.main import app
from tests.agent_test_utils import install_scripted_sdk_client, read_sse_events, set_agent_env, upload_dataset
from tests.auth_utils import auth_headers


def _seed_dataset(client: TestClient) -> str:
    return upload_dataset(
        client,
        rows=[
            {"employee_id": "E-001", "department": "HR", "status": "active"},
            {"employee_id": "E-002", "department": "HR", "status": "inactive"},
            {"employee_id": "E-003", "department": "PM", "status": "active"},
            {"employee_id": "E-004", "department": "ENG", "status": "active"},
        ],
        user_id="admin",
        project_id="north",
        role="admin",
        department="HR",
        clearance=9,
    )


def _seed_gender_dataset(client: TestClient) -> str:
    return upload_dataset(
        client,
        rows=[
            {"employee_id": "E-001", "department": "HR", "gender": "女", "status": "active"},
            {"employee_id": "E-002", "department": "HR", "gender": "男", "status": "active"},
            {"employee_id": "E-003", "department": "PM", "gender": "女", "status": "active"},
            {"employee_id": "E-004", "department": "PM", "gender": "女", "status": "active"},
            {"employee_id": "E-005", "department": "ENG", "gender": "男", "status": "active"},
            {"employee_id": "E-006", "department": "ENG", "gender": "男", "status": "active"},
        ],
        user_id="admin",
        project_id="north",
        role="admin",
        department="HR",
        clearance=9,
    )


def _headers(client: TestClient) -> dict[str, str]:
    return auth_headers(
        client,
        user_id="admin",
        project_id="north",
        role="admin",
        department="HR",
        clearance=9,
    )


def _request_payload(conversation_id: str, request_id: str, dataset_table: str, message: str) -> dict[str, object]:
    return {
        "conversation_id": conversation_id,
        "request_id": request_id,
        "user_id": "admin",
        "project_id": "north",
        "role": "admin",
        "department": "HR",
        "clearance": 9,
        "dataset_table": dataset_table,
        "message": message,
    }


def _stream_events(client: TestClient, *, payload: dict[str, object], headers: dict[str, str]) -> list[dict[str, object]]:
    with client.stream("POST", "/chat/stream", json=payload, headers=headers) as response:
        assert response.status_code == 200
        events, _ = read_sse_events(response)
    return events


def _start_confirmation(client: TestClient, dataset_table: str, headers: dict[str, str], conversation_id: str) -> dict[str, object]:
    events = _stream_events(
        client,
        payload=_request_payload(
            conversation_id,
            f"{conversation_id}-request-plan",
            dataset_table,
            "Create one headcount chart for each department",
        ),
        headers=headers,
    )
    event_names = [event["event"] for event in events]
    assert "confirmation_required" in event_names
    assert "spec" not in event_names[: event_names.index("final")]
    assert events[-1]["event"] == "final"
    assert events[-1]["data"]["status"] == "awaiting_confirmation"
    return next(event["data"] for event in events if event["event"] == "confirmation_required")


def test_multi_chart_prompt_emits_confirmation_before_any_spec(monkeypatch, tmp_path: Path) -> None:
    set_agent_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        dataset_table = _seed_dataset(client)
        confirmation = _start_confirmation(client, dataset_table, _headers(client), "multi-chart-confirm-before-spec")

    assert confirmation["confirmation_type"] == "multi_chart_generation"
    assert confirmation["grouping_dimension"] == "department"
    assert confirmation["proposed_count"] == 3
    assert confirmation["max_chart_count"] == 8
    assert [item["label"] for item in confirmation["items"]] == ["HR", "ENG", "PM"]


def test_confirmed_multi_chart_generation_streams_grouped_specs(monkeypatch, tmp_path: Path) -> None:
    set_agent_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        dataset_table = _seed_dataset(client)
        headers = _headers(client)
        confirmation = _start_confirmation(client, dataset_table, headers, "multi-chart-confirmed")
        selected = confirmation["items"][:2]
        events = _stream_events(
            client,
            payload={
                **_request_payload(
                    "multi-chart-confirmed",
                    "multi-chart-confirmed-request-generate",
                    dataset_table,
                    "Generate selected charts",
                ),
                "multi_chart_confirmation": {
                    "confirmation_id": confirmation["confirmation_id"],
                    "action": "adjust",
                    "selected_items": [{"key": item["key"], "label": item["label"]} for item in selected],
                },
            },
            headers=headers,
        )

    spec_events = [event["data"] for event in events if event["event"] == "spec"]
    assert len(spec_events) == 2
    assert {payload["multi_chart_group_id"] for payload in spec_events} == {f"mcg-{confirmation['confirmation_id']}"}
    assert [payload["chart_index"] for payload in spec_events] == [0, 1]
    assert all(payload["chart_count"] == 2 for payload in spec_events)
    assert all(payload["chart_id"] for payload in spec_events)
    assert all(payload["spec"]["chart_type"] == "bar" for payload in spec_events)
    assert events[-1]["event"] == "final"
    assert events[-1]["data"]["status"] == "completed"
    assert len(events[-1]["data"]["charts"]) == 2


def test_chinese_requested_pie_charts_use_gender_breakdown(monkeypatch, tmp_path: Path) -> None:
    set_agent_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        dataset_table = _seed_gender_dataset(client)
        headers = _headers(client)
        conversation_id = "multi-chart-chinese-gender-pie"
        confirmation_events = _stream_events(
            client,
            payload={
                **_request_payload(
                    conversation_id,
                    f"{conversation_id}-request-plan",
                    dataset_table,
                    "请你输出三张 #pie 来统计各个部门的性别分布",
                ),
                "preferred_chart_type": "pie",
            },
            headers=headers,
        )
        confirmation = next(event["data"] for event in confirmation_events if event["event"] == "confirmation_required")
        selected = next(item for item in confirmation["items"] if item["label"] == "HR")
        generation_events = _stream_events(
            client,
            payload={
                **_request_payload(
                    conversation_id,
                    f"{conversation_id}-request-generate",
                    dataset_table,
                    "Generate selected charts",
                ),
                "preferred_chart_type": "pie",
                "multi_chart_confirmation": {
                    "confirmation_id": confirmation["confirmation_id"],
                    "action": "adjust",
                    "selected_items": [{"key": selected["key"], "label": selected["label"]}],
                },
            },
            headers=headers,
        )

    assert confirmation["grouping_dimension"] == "department"
    assert confirmation["breakdown_dimension"] == "gender"
    assert confirmation["proposed_count"] == 3

    spec_payload = next(event["data"] for event in generation_events if event["event"] == "spec")
    assert spec_payload["chart_label"] == "HR"
    assert spec_payload["spec"]["chart_type"] == "pie"
    assert spec_payload["spec"]["engine"] == "recharts"
    assert spec_payload["spec"]["config"]["xKey"] == "segment"
    assert spec_payload["spec"]["config"]["yKey"] == "metric_value"
    assert sorted(spec_payload["spec"]["data"], key=lambda row: row["segment"]) == [
        {"segment": "女", "metric_value": 1},
        {"segment": "男", "metric_value": 1},
    ]


def test_multi_chart_limit_mismatch_expiry_and_cancel_validation(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_MAX_MULTI_CHARTS", "2")
    set_agent_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        dataset_table = _seed_dataset(client)
        headers = _headers(client)
        confirmation = _start_confirmation(client, dataset_table, headers, "multi-chart-validation")

        over_limit_events = _stream_events(
            client,
            payload={
                **_request_payload(
                    "multi-chart-validation",
                    "multi-chart-validation-over-limit",
                    dataset_table,
                    "Generate all charts",
                ),
                "multi_chart_confirmation": {
                    "confirmation_id": confirmation["confirmation_id"],
                    "action": "confirm",
                },
            },
            headers=headers,
        )
        assert "spec" not in [event["event"] for event in over_limit_events]
        assert over_limit_events[0]["event"] == "error"
        assert over_limit_events[0]["data"]["code"] == "MULTI_CHART_LIMIT_EXCEEDED"

        mismatch_events = _stream_events(
            client,
            payload={
                **_request_payload(
                    "multi-chart-validation",
                    "multi-chart-validation-mismatch",
                    dataset_table,
                    "Generate selected charts",
                ),
                "multi_chart_confirmation": {
                    "confirmation_id": "wrong-id",
                    "action": "adjust",
                    "selected_items": [{"key": confirmation["items"][0]["key"]}],
                },
            },
            headers=headers,
        )
        assert "spec" not in [event["event"] for event in mismatch_events]
        assert mismatch_events[0]["data"]["code"] == "MULTI_CHART_CONFIRMATION_MISMATCH"

        confirmation = _start_confirmation(client, dataset_table, headers, "multi-chart-cancel")
        cancel_events = _stream_events(
            client,
            payload={
                **_request_payload(
                    "multi-chart-cancel",
                    "multi-chart-cancel-request",
                    dataset_table,
                    "Cancel",
                ),
                "multi_chart_confirmation": {
                    "confirmation_id": confirmation["confirmation_id"],
                    "action": "cancel",
                },
            },
            headers=headers,
        )
        assert "spec" not in [event["event"] for event in cancel_events]
        assert cancel_events[-1]["data"]["status"] == "canceled"

        expired_confirmation = _start_confirmation(client, dataset_table, headers, "multi-chart-expired")
        runtime = get_agent_runtime()
        session = runtime.get_persisted_session("multi-chart-expired")
        assert session is not None
        assert session.pending_multi_chart_confirmation is not None
        session.pending_multi_chart_confirmation["expires_at"] = 0
        runtime._store.save(session)  # noqa: SLF001
        runtime._hot_sessions.pop("multi-chart-expired", None)  # noqa: SLF001
        expired_events = _stream_events(
            client,
            payload={
                **_request_payload(
                    "multi-chart-expired",
                    "multi-chart-expired-request",
                    dataset_table,
                    "Generate selected charts",
                ),
                "multi_chart_confirmation": {
                    "confirmation_id": expired_confirmation["confirmation_id"],
                    "action": "adjust",
                    "selected_items": [{"key": expired_confirmation["items"][0]["key"]}],
                },
            },
            headers=headers,
        )
        assert "spec" not in [event["event"] for event in expired_events]
        assert expired_events[0]["data"]["code"] == "MULTI_CHART_CONFIRMATION_EXPIRED"


def test_multi_chart_partial_failure_keeps_successful_specs(monkeypatch, tmp_path: Path) -> None:
    set_agent_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        dataset_table = _seed_dataset(client)
        headers = _headers(client)
        confirmation = _start_confirmation(client, dataset_table, headers, "multi-chart-partial")
        runtime = get_agent_runtime()
        session = runtime.get_persisted_session("multi-chart-partial")
        assert session is not None
        assert session.pending_multi_chart_confirmation is not None
        session.pending_multi_chart_confirmation["items"][1]["filter_field"] = "missing_field"
        runtime._store.save(session)  # noqa: SLF001
        runtime._hot_sessions.pop("multi-chart-partial", None)  # noqa: SLF001

        events = _stream_events(
            client,
            payload={
                **_request_payload(
                    "multi-chart-partial",
                    "multi-chart-partial-generate",
                    dataset_table,
                    "Generate selected charts",
                ),
                "multi_chart_confirmation": {
                    "confirmation_id": confirmation["confirmation_id"],
                    "action": "adjust",
                    "selected_items": [
                        {"key": confirmation["items"][0]["key"]},
                        {"key": confirmation["items"][1]["key"]},
                    ],
                },
            },
            headers=headers,
        )

    assert len([event for event in events if event["event"] == "spec"]) == 1
    assert events[-1]["data"]["status"] == "partial"
    assert len(events[-1]["data"]["failed_charts"]) == 1


def test_single_chart_prompt_bypasses_multi_chart_flow(monkeypatch, tmp_path: Path) -> None:
    set_agent_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        dataset_table = _seed_dataset(client)
        runtime = get_agent_runtime()
        rows = [{"department": "HR", "metric_value": 2}]

        def scenario(prompt: str, options) -> dict[str, object]:  # type: ignore[no-untyped-def]
            _ = (prompt, options)
            return {
                "tool_calls": [
                    {
                        "name": "execute_readonly_sql",
                        "arguments": {"sql": f'SELECT department, COUNT(*) AS metric_value FROM "{dataset_table}" GROUP BY department'},
                        "result": {"rows": rows},
                    }
                ],
                "final_answer": {
                    "chart_type": "bar",
                    "title": "Headcount",
                    "x_key": "department",
                    "y_key": "metric_value",
                    "series_key": None,
                    "metric_name": "headcount",
                    "rows": rows,
                    "conclusion": "Headcount by department.",
                    "scope": "Current dataset",
                    "anomalies": "none",
                },
            }

        install_scripted_sdk_client(runtime, scenario)
        result = runtime.run_turn(
            AgentRequest(
                conversation_id="single-chart-bypass",
                request_id="single-chart-bypass-request",
                user_id="admin",
                project_id="north",
                dataset_table=dataset_table,
                message="Show one headcount chart by department",
                role="admin",
                department="HR",
                clearance=9,
            )
        )

    assert result.final_status == "completed"
    assert "confirmation_required" not in [event_type for event_type, _ in result.events]
    assert result.spec["title"] == "Headcount"


def test_multi_chart_planner_distinct_values_respect_rls(monkeypatch, tmp_path: Path) -> None:
    set_agent_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        dataset_table = upload_dataset(
            client,
            rows=[
                {"employee_id": "E-001", "department": "HR", "status": "active"},
                {"employee_id": "E-002", "department": "PM", "status": "active"},
                {"employee_id": "E-003", "department": "ENG", "status": "active"},
            ],
            user_id="viewer",
            project_id="north",
            role="viewer",
            department="HR",
            clearance=1,
        )

    runtime = get_agent_runtime()
    session = AgentSessionState(
        conversation_id="rls-planner",
        agent_session_id=str(uuid.uuid4()),
        runtime_backend=SDK_RUNTIME_BACKEND,
    )
    request = AgentRequest(
        conversation_id="rls-planner",
        request_id="rls-planner-request",
        user_id="viewer",
        project_id="north",
        dataset_table=dataset_table,
        message="Create one chart for every department",
        role="viewer",
        department="HR",
        clearance=1,
    )
    run_context = SDKRunContext(
        request=request,
        session=session,
        events=[],
        tool_trace=[],
    )

    async def run_plan():
        return await runtime.multi_chart_planner.plan(
            request=request,
            run_context=run_context,
            append_event=runtime._append_event,  # noqa: SLF001
        )

    result = anyio.run(run_plan)

    assert result is None
    distinct_result = next(
        event["result"]
        for event in run_context.tool_trace
        if event.get("event") == "tool_result" and event.get("tool_name") == "get_distinct_values"
    )
    assert [row["value"] for row in distinct_result["values"]] == ["HR"]


def test_explicit_chinese_multi_chart_count_does_not_fall_back_when_only_one_value_visible(monkeypatch, tmp_path: Path) -> None:
    set_agent_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        dataset_table = upload_dataset(
            client,
            rows=[
                {"employee_id": "E-001", "department": "HR", "gender": "女", "status": "active"},
                {"employee_id": "E-002", "department": "PM", "gender": "男", "status": "active"},
                {"employee_id": "E-003", "department": "ENG", "gender": "男", "status": "active"},
            ],
            user_id="viewer",
            project_id="north",
            role="viewer",
            department="HR",
            clearance=1,
        )

    runtime = get_agent_runtime()
    session = AgentSessionState(
        conversation_id="rls-explicit-count",
        agent_session_id=str(uuid.uuid4()),
        runtime_backend=SDK_RUNTIME_BACKEND,
    )
    request = AgentRequest(
        conversation_id="rls-explicit-count",
        request_id="rls-explicit-count-request",
        user_id="viewer",
        project_id="north",
        dataset_table=dataset_table,
        message="请你输出三张 #pie 来统计各个部门的性别分布",
        preferred_chart_type="pie",
        role="viewer",
        department="HR",
        clearance=1,
    )
    run_context = SDKRunContext(
        request=request,
        session=session,
        events=[],
        tool_trace=[],
    )

    async def run_plan():
        return await runtime.multi_chart_planner.plan(
            request=request,
            run_context=run_context,
            append_event=runtime._append_event,  # noqa: SLF001
        )

    result = anyio.run(run_plan)

    assert result is not None
    assert result.grouping_dimension == "department"
    assert result.breakdown_dimension == "gender"
    assert result.chart_type == "pie"
    assert [item.label for item in result.items] == ["HR"]
    assert result.truncated is True


def test_multi_chart_sensitive_column_prompt_is_blocked_before_confirmation(monkeypatch, tmp_path: Path) -> None:
    set_agent_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        dataset_table = upload_dataset(
            client,
            rows=[
                {"employee_id": "E-001", "department": "HR", "salary": 100},
                {"employee_id": "E-002", "department": "PM", "salary": 200},
            ],
            user_id="viewer",
            project_id="north",
            role="viewer",
            department="HR",
            clearance=1,
        )
        headers = auth_headers(
            client,
            user_id="viewer",
            project_id="north",
            role="viewer",
            department="HR",
            clearance=1,
        )
        events = _stream_events(
            client,
            payload={
                "conversation_id": "multi-chart-sensitive",
                "request_id": "multi-chart-sensitive-request",
                "user_id": "viewer",
                "project_id": "north",
                "role": "viewer",
                "department": "HR",
                "clearance": 1,
                "dataset_table": dataset_table,
                "message": "Create one chart for every salary",
            },
            headers=headers,
        )

    event_names = [event["event"] for event in events]
    assert "confirmation_required" not in event_names
    assert "spec" not in event_names
    assert events[0]["event"] == "error"
    assert events[0]["data"]["code"] == "SENSITIVE_FIELD_FORBIDDEN"
