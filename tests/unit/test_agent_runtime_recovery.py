from __future__ import annotations

from apps.api.agent_runtime import (
    AgentRequest,
    AgentSessionState,
    SDKRunContext,
    _recover_final_answer_from_tool_trace,
    clear_agent_runtime_cache,
    get_agent_runtime,
)
from apps.api.config import get_settings


def test_recover_final_answer_prefers_sql_result_over_later_distinct_values() -> None:
    tool_trace = [
        {
            "event": "tool_result",
            "tool_name": "execute_readonly_sql",
            "status": "success",
            "result": {
                "row_count": 3,
                "rows": [
                    {"age_group": "25-30岁", "employee_count": 8},
                    {"age_group": "30-35岁", "employee_count": 14},
                    {"age_group": "35-40岁", "employee_count": 6},
                ],
            },
        },
        {
            "event": "tool_result",
            "tool_name": "get_distinct_values",
            "status": "success",
            "result": {
                "field": "department",
                "row_count": 2,
                "values": [
                    {"value": "NTN中心", "frequency": 20},
                    {"value": "平台研发", "frequency": 18},
                ],
            },
        },
    ]

    # Production always passes the resolved response locale (derived from the
    # request message when the client did not choose one), so a Chinese question
    # arrives here as zh-CN.
    answer = _recover_final_answer_from_tool_trace(
        tool_trace=tool_trace,
        request_message="按年龄段统计员工人数",
        locale="zh-CN",
    )

    assert answer is not None
    assert answer["chart_type"] == "bar"
    assert answer["title"] == "SQL 查询结果"
    assert answer["x_key"] == "age_group"
    assert answer["y_key"] == "employee_count"
    assert answer["rows"] == tool_trace[0]["result"]["rows"]
    # The marker was replaced by a localized, user-facing note (it is rendered
    # into the final answer text as "异常说明: ...").
    assert answer["anomalies"] == "已基于成功工具结果自动生成。"


def test_sdk_options_target_deepseek_anthropic_gateway(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'views.db'}")
    monkeypatch.setenv("MODEL_PROVIDER_URL", "https://api.deepseek.com")
    monkeypatch.setenv("AI_API_KEY", "deepseek-test-key")
    monkeypatch.setenv("AI_MODEL", "deepseek-chat")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.deepseek.com/anthropic")
    monkeypatch.setenv("AUTH_SECRET", "secret")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    get_settings.cache_clear()
    clear_agent_runtime_cache()

    runtime = get_agent_runtime()
    request = AgentRequest(
        conversation_id="conv-deepseek",
        request_id="req-deepseek",
        user_id="alice",
        project_id="north",
        dataset_table="employees",
        message="按部门统计人数",
        role="viewer",
        department="HR",
        clearance=1,
    )
    session = AgentSessionState(
        conversation_id="conv-deepseek",
        agent_session_id="session-deepseek",
    )
    run_context = SDKRunContext(
        request=request,
        session=session,
        events=[],
        tool_trace=[],
    )

    options = runtime._build_sdk_options(
        request=request,
        session=session,
        system_text="system",
        run_context=run_context,
    )

    assert options.model == "deepseek-chat"
    assert options.env["ANTHROPIC_BASE_URL"] == "https://api.deepseek.com/anthropic"
    assert options.env["ANTHROPIC_API_KEY"] == "deepseek-test-key"
    assert options.env["ANTHROPIC_AUTH_TOKEN"] == "deepseek-test-key"
    assert options.env["ANTHROPIC_MODEL"] == "deepseek-chat"
    assert options.env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "deepseek-chat"
    assert options.env["API_TIMEOUT_MS"] == "600000"
    assert options.env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"
    assert options.session_id is None
    assert options.resume is None

    session.turn_count = 1
    resumed_options = runtime._build_sdk_options(
        request=request,
        session=session,
        system_text="system",
        run_context=run_context,
    )
    assert resumed_options.session_id is None
    assert resumed_options.resume == "session-deepseek"

    fresh_options = runtime._build_sdk_options(
        request=request,
        session=session,
        system_text="system",
        run_context=run_context,
        force_fresh_session=True,
    )
    assert fresh_options.session_id is None
    assert fresh_options.resume is None
    clear_agent_runtime_cache()
    get_settings.cache_clear()


def test_recover_final_answer_returns_none_without_successful_grounding() -> None:
    answer = _recover_final_answer_from_tool_trace(
        tool_trace=[
            {
                "event": "tool_result",
                "tool_name": "execute_readonly_sql",
                "status": "failed",
                "result": {"error": "QUERY_EXECUTION_FAILED"},
            }
        ],
        request_message="按部门统计人数",
    )

    assert answer is None


def test_recover_final_answer_prefers_non_empty_semantic_result_over_empty_sql() -> None:
    tool_trace = [
        {
            "event": "tool_result",
            "tool_name": "execute_readonly_sql",
            "status": "success",
            "result": {
                "row_count": 0,
                "rows": [],
            },
        },
        {
            "event": "tool_result",
            "tool_name": "run_semantic_query",
            "status": "success",
            "result": {
                "metric": "avg_age",
                "row_count": 1,
                "rows": [{"metric_value": None}],
            },
        },
    ]

    answer = _recover_final_answer_from_tool_trace(
        tool_trace=tool_trace,
        request_message="统计平均年龄",
        locale="zh-CN",
    )

    assert answer is not None
    assert answer["title"] == "avg_age 查询结果"
    assert answer["rows"] == [{"metric_value": None}]
