from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from apps.api.agent_canvas import (
    clear_agent_canvas_run_store_cache,
    get_agent_canvas_run_store,
)
from apps.api.agent_guardrails import AgentGuardrailContext, AgentGuardrailError, AgentGuardrails
from apps.api.audit import get_audit_logger
from apps.api.config import get_settings
from apps.api.datasets import get_dataset_service
from apps.api.tool_calling import (
    ToolCall,
    ToolCallRequest,
    get_tool_calling_service,
)
from apps.api.workspace_state import clear_workspace_state_store_cache, get_workspace_state_store
from tests.agent_test_utils import set_agent_env

WORKSPACE_ID = "ws-canvas-test"
GUARD_CONTEXT = AgentGuardrailContext(role="admin", user_id="admin", project_id="north")


def _set_canvas_env(monkeypatch, tmp_path: Path, *, enabled: bool = True) -> None:
    monkeypatch.setenv("AGENT_CANVAS_MODE_ENABLED", "true" if enabled else "false")
    set_agent_env(monkeypatch, tmp_path)
    clear_agent_canvas_run_store_cache()
    clear_workspace_state_store_cache()


def _seed_dataset(*, user_id: str = "admin", project_id: str = "north") -> str:
    dataframe = pd.DataFrame(
        [
            {"employee_id": "E-001", "department": "HR", "entry_date": "2026-01-02 00:00:00"},
            {"employee_id": "E-002", "department": "HR", "entry_date": "2026-02-03 00:00:00"},
            {"employee_id": "E-003", "department": "PM", "entry_date": "2025-03-04 00:00:00"},
        ]
    )
    service = get_dataset_service(get_settings().upload_dir)
    with service.session_manager.connection(user_id, project_id, workspace_id=WORKSPACE_ID) as conn:
        conn.register("seed_df", dataframe)
        conn.execute('CREATE OR REPLACE TABLE "employees" AS SELECT * FROM seed_df')
        conn.unregister("seed_df")
    return "employees"


def _create_run() -> dict:
    return get_agent_canvas_run_store().create_run(
        conversation_id="conv-1",
        workspace_id=WORKSPACE_ID,
        user_id="admin",
        canvas_format="web-design",
        status="running",
    )


def _invoke(tool_name: str, arguments: dict, *, idempotency_key: str | None = None):
    return get_tool_calling_service().invoke(
        ToolCallRequest(
            conversation_id="conv-1",
            request_id="req-1",
            idempotency_key=idempotency_key or f"key-{tool_name}-{json.dumps(arguments, default=str)[:60]}",
            user_id="admin",
            project_id="north",
            workspace_id=WORKSPACE_ID,
            dataset_table="employees",
            role="admin",
            department="HR",
            clearance=9,
            emit_debug_blocks=False,
            tool=ToolCall(name=tool_name, arguments=arguments),
        )
    )


def _run_arguments(run: dict, extra: dict) -> dict:
    return {
        **extra,
        "_agent_run": {
            "run_id": run["run_id"],
            "page_id": run["page_id"],
            "workspace_id": run["workspace_id"],
            "conversation_id": "conv-1",
        },
    }


def test_canvas_tools_require_agent_run_context(monkeypatch, tmp_path: Path) -> None:
    _set_canvas_env(monkeypatch, tmp_path)
    response = _invoke("add_section", {"title": "概览"})
    assert response.status == "error"
    assert response.error is not None
    assert response.error["code"] == "AGENT_CANVAS_RUN_REQUIRED"


def test_canvas_tools_rejected_when_flag_off(monkeypatch, tmp_path: Path) -> None:
    _set_canvas_env(monkeypatch, tmp_path, enabled=False)
    response = _invoke("add_section", {"title": "概览", "_agent_run": {"run_id": "r1"}})
    assert response.status == "error"
    assert response.error is not None
    assert response.error["code"] == "AGENT_CANVAS_MODE_DISABLED"


def test_place_chart_rejects_unknown_size_preset(monkeypatch, tmp_path: Path) -> None:
    _set_canvas_env(monkeypatch, tmp_path)
    run = _create_run()
    response = _invoke(
        "place_chart",
        _run_arguments(
            run,
            {
                "title": "部门人数",
                "chart_type": "bar",
                "size_preset": "gigantic",
                "sql": "SELECT department AS segment, COUNT(*) AS metric_value FROM employees GROUP BY 1",
            },
        ),
    )
    assert response.status == "error"
    assert response.error is not None
    assert response.error["code"] == "AGENT_CANVAS_SIZE_PRESET_INVALID"
    assert get_agent_canvas_run_store().count_ops(run_id=run["run_id"]) == 0


def test_geometry_fields_rejected_by_guardrails(monkeypatch, tmp_path: Path) -> None:
    _set_canvas_env(monkeypatch, tmp_path)
    guardrails = AgentGuardrails()
    with pytest.raises(AgentGuardrailError) as exc_info:
        guardrails.validate_tool_call(
            tool_name="place_chart",
            arguments={
                "title": "部门人数",
                "chart_type": "bar",
                "size_preset": "half",
                "sql": "SELECT 1",
                "x": 3,
                "width": 6,
            },
            context=GUARD_CONTEXT,
            agent_mode=True,
        )
    assert exc_info.value.code == "AGENT_CANVAS_GEOMETRY_FORBIDDEN"


def test_canvas_tools_whitelisted_only_for_agent_mode(monkeypatch, tmp_path: Path) -> None:
    _set_canvas_env(monkeypatch, tmp_path)
    guardrails = AgentGuardrails()
    assert "place_chart" not in guardrails.allowed_tools
    assert "place_chart" in guardrails.agent_mode_allowed_tools
    with pytest.raises(AgentGuardrailError) as exc_info:
        guardrails.validate_tool_call(
            tool_name="place_chart",
            arguments={"title": "t", "chart_type": "bar", "size_preset": "half", "sql": "SELECT 1"},
            context=GUARD_CONTEXT,
        )
    assert exc_info.value.code == "TOOL_NOT_ALLOWED"


def test_canvas_tools_excluded_when_flag_off(monkeypatch, tmp_path: Path) -> None:
    _set_canvas_env(monkeypatch, tmp_path, enabled=False)
    guardrails = AgentGuardrails()
    assert "place_chart" not in guardrails.agent_mode_allowed_tools
    assert guardrails.agent_mode_allowed_tools == guardrails.allowed_tools


def test_place_chart_success_is_atomic_and_metadata_only(monkeypatch, tmp_path: Path) -> None:
    _set_canvas_env(monkeypatch, tmp_path)
    _seed_dataset()
    run = _create_run()
    response = _invoke(
        "place_chart",
        _run_arguments(
            run,
            {
                "section_id": "sec-1",
                "title": "部门人数",
                "chart_type": "bar",
                "size_preset": "half",
                "sql": "SELECT department AS segment, COUNT(*) AS metric_value FROM employees GROUP BY 1",
            },
        ),
    )
    assert response.status == "success", response.error
    result = response.result or {}
    assert result["status"] == "placed"
    assert result["row_count"] == 2
    assert "rows" not in result  # data never returns into the model context

    op = result["op"]
    assert op["seq"] == 1
    assert op["op_type"] == "place_chart"
    payload = op["payload"]
    assert payload["block_id"].endswith("-1")
    assert payload["size_preset"] == "half"
    assert payload["spec"]["title"] == "部门人数"

    # Op is durably persisted for replay.
    stored_ops = get_agent_canvas_run_store().list_ops_after(run_id=run["run_id"], after_seq=0)
    assert [item["op_type"] for item in stored_ops] == ["place_chart"]

    # Chart asset persisted server-side, scoped to user + workspace.
    assets = get_workspace_state_store().list_chart_assets(
        workspace_id=WORKSPACE_ID, user_id="admin"
    )
    assert len(assets) == 1
    assert assets[0]["id"] == result["asset_id"]
    assert assets[0]["title"] == "部门人数"


def test_place_chart_failure_appends_error_placeholder(monkeypatch, tmp_path: Path) -> None:
    _set_canvas_env(monkeypatch, tmp_path)
    _seed_dataset()
    run = _create_run()
    response = _invoke(
        "place_chart",
        _run_arguments(
            run,
            {
                "section_id": "sec-1",
                "title": "坏图表",
                "chart_type": "bar",
                "size_preset": "half",
                "sql": "SELECT nonexistent_column AS segment, COUNT(*) AS metric_value FROM employees GROUP BY 1",
            },
        ),
    )
    assert response.status == "success"
    result = response.result or {}
    assert result["status"] == "error_placeholder"
    assert result["error"]["code"]

    stored_ops = get_agent_canvas_run_store().list_ops_after(run_id=run["run_id"], after_seq=0)
    assert [item["op_type"] for item in stored_ops] == ["error_placeholder"]
    placeholder = stored_ops[0]["payload"]
    assert placeholder["title"] == "坏图表"
    assert placeholder["args"]["sql"].startswith("SELECT nonexistent_column")

    # No asset persisted for the failed item.
    assets = get_workspace_state_store().list_chart_assets(
        workspace_id=WORKSPACE_ID, user_id="admin"
    )
    assert assets == []


def test_corrected_place_chart_retry_replaces_error_placeholder(
    monkeypatch, tmp_path: Path
) -> None:
    _set_canvas_env(monkeypatch, tmp_path)
    _seed_dataset()
    run = _create_run()
    item = {
        "section_id": "sec-1",
        "title": "今年入职趋势",
        "chart_type": "line",
        "size_preset": "half",
    }

    failed = _invoke(
        "place_chart",
        _run_arguments(
            run,
            {
                **item,
                "sql": (
                    "SELECT strftime(entry_date, '%Y-%m') AS segment, "
                    "COUNT(*) AS metric_value FROM employees GROUP BY 1"
                ),
            },
        ),
        idempotency_key="place-chart-temporal-failure",
    )
    failed_result = failed.result or {}
    assert failed_result["status"] == "error_placeholder"
    assert "Binder Error" in failed_result["error"]["message"]
    placeholder_id = failed_result["block_id"]

    corrected = _invoke(
        "place_chart",
        _run_arguments(
            run,
            {
                **item,
                "sql": (
                    "SELECT SUBSTRING(entry_date, 1, 7) AS segment, "
                    "COUNT(*) AS metric_value FROM employees "
                    "WHERE entry_date LIKE '2026%' GROUP BY 1 ORDER BY 1"
                ),
            },
        ),
        idempotency_key="place-chart-temporal-corrected",
    )
    corrected_result = corrected.result or {}
    assert corrected_result["status"] == "placed"
    assert corrected_result["block_id"] == placeholder_id
    assert corrected_result["replaced_error_placeholder"] is True
    assert corrected_result["row_count"] == 2
    assert corrected_result["op"]["payload"]["replaces_block_id"] == placeholder_id

    stored_ops = get_agent_canvas_run_store().list_ops_after(
        run_id=run["run_id"], after_seq=0
    )
    assert [item["op_type"] for item in stored_ops] == [
        "error_placeholder",
        "place_chart",
    ]


def test_deterministic_readonly_sql_error_is_not_retried_and_has_detail(
    monkeypatch, tmp_path: Path
) -> None:
    _set_canvas_env(monkeypatch, tmp_path)
    _seed_dataset()

    response = _invoke(
        "execute_readonly_sql",
        {
            "sql": (
                "SELECT strftime(entry_date, '%Y-%m') AS month "
                "FROM employees"
            )
        },
        idempotency_key="readonly-temporal-binder-error",
    )

    assert response.status == "error"
    assert response.attempts == 1
    assert response.error is not None
    assert response.error["code"] == "QUERY_EXECUTION_FAILED"
    assert response.error["retryable"] is False
    assert "Binder Error" in response.error["message"]
    assert "VARCHAR" in response.error["message"]


def test_canvas_budget_enforcement(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_MODE_MAX_CHARTS", "2")
    _set_canvas_env(monkeypatch, tmp_path)
    guardrails = AgentGuardrails()
    guardrails.enforce_canvas_chart_budget(1)
    with pytest.raises(AgentGuardrailError) as chart_exc:
        guardrails.enforce_canvas_chart_budget(2)
    assert chart_exc.value.code == "AGENT_MODE_CHART_BUDGET_EXCEEDED"

    guardrails.enforce_canvas_block_budget(3)
    with pytest.raises(AgentGuardrailError) as block_exc:
        guardrails.enforce_canvas_block_budget(4)
    assert block_exc.value.code == "AGENT_MODE_BLOCK_BUDGET_EXCEEDED"


def test_canvas_audit_events_are_metadata_only(monkeypatch, tmp_path: Path) -> None:
    _set_canvas_env(monkeypatch, tmp_path)
    _seed_dataset()
    run = _create_run()
    _invoke(
        "place_chart",
        _run_arguments(
            run,
            {
                "section_id": "sec-1",
                "title": "部门人数",
                "chart_type": "bar",
                "size_preset": "half",
                "sql": "SELECT department AS segment, COUNT(*) AS metric_value FROM employees GROUP BY 1",
            },
        ),
    )
    events = get_audit_logger().query(action="agent_canvas_op", limit=10)
    assert events, "expected an agent_canvas_op audit event"
    detail = events[0]["detail"]
    assert set(detail.keys()) <= {"run_id", "op_type", "duration_ms"}
    serialized = json.dumps(events[0], ensure_ascii=False)
    assert "部门人数" not in serialized
    assert "SELECT" not in serialized
