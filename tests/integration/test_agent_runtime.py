from __future__ import annotations
import json
from pathlib import Path

import anyio
from fastapi.testclient import TestClient
from claude_agent_sdk import AssistantMessage, ResultMessage, ToolResultBlock, ToolUseBlock, UserMessage

from apps.api.agent_runtime import (
    SDK_MCP_SERVER_NAME,
    AgentRequest,
    AgentSessionState,
    SDKRunContext,
    clear_agent_runtime_cache,
    get_agent_runtime,
)
from apps.api.main import app
from tests.agent_test_utils import install_scripted_sdk_client, set_agent_env, upload_dataset


def _sql_tool_call(rows: list[dict[str, object]], sql: str) -> dict[str, object]:
    return {
        "name": "execute_readonly_sql",
        "arguments": {"sql": sql, "max_rows": 200},
        "result": {"rows": rows, "sql": sql},
    }


def test_agent_runtime_supports_single_turn_follow_up_and_restart_recovery(monkeypatch, tmp_path: Path) -> None:
    set_agent_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        dataset_table = upload_dataset(
            client,
            rows=[
                {"employee_id": "E-001", "department": "HR", "hire_year": 2022},
                {"employee_id": "E-002", "department": "HR", "hire_year": 2023},
                {"employee_id": "E-003", "department": "PM", "hire_year": 2023},
            ],
        )

        runtime = get_agent_runtime()
        first_rows = [
            {"hire_year": 2022, "metric_value": 1},
            {"hire_year": 2023, "metric_value": 1},
        ]

        def scenario(prompt: str, options) -> dict[str, object]:  # type: ignore[no-untyped-def]
            _ = options
            if "折线图" in prompt:
                return {
                    "tool_calls": [],
                    "final_answer": {
                        "chart_type": "line",
                        "title": "入职年份统计",
                        "x_key": "hire_year",
                        "y_key": "metric_value",
                        "series_key": None,
                        "metric_name": "headcount",
                        "rows": first_rows,
                        "conclusion": "沿用上一轮查询结果并切换为折线图。",
                        "scope": "当前数据集按入职年份统计",
                        "anomalies": "none",
                    },
                }
            return {
                "tool_calls": [
                    _sql_tool_call(
                        first_rows,
                        'SELECT "hire_year", COUNT(*) AS metric_value FROM dataset GROUP BY "hire_year"',
                    )
                ],
                "final_answer": {
                    "chart_type": "bar",
                    "title": "入职年份统计",
                    "x_key": "hire_year",
                    "y_key": "metric_value",
                    "series_key": None,
                    "metric_name": "headcount",
                    "rows": first_rows,
                    "conclusion": "按入职年份统计员工数。",
                    "scope": "当前数据集按入职年份统计",
                    "anomalies": "none",
                },
            }

        install_scripted_sdk_client(runtime, scenario)
        first = runtime.run_turn(
            AgentRequest(
                conversation_id="agent-runtime-conv-1",
                request_id="agent-runtime-req-1",
                user_id="alice",
                project_id="north",
                dataset_table=dataset_table,
                message="柱状图显示入职年份统计",
                role="viewer",
                department="HR",
                clearance=1,
            )
        )

        follow_up = runtime.run_turn(
            AgentRequest(
                conversation_id="agent-runtime-conv-1",
                request_id="agent-runtime-req-2",
                user_id="alice",
                project_id="north",
                dataset_table=dataset_table,
                message="改成折线图",
                role="viewer",
                department="HR",
                clearance=1,
            )
        )

    assert first.final_status == "completed"
    assert first.agent_session_id
    tool_use_events = [payload for event_type, payload in first.events if event_type == "tool_use"]
    tool_result_events = [payload for event_type, payload in first.events if event_type == "tool_result"]
    assert tool_use_events, "expected at least one tool_use event"
    for tu in tool_use_events:
        assert "step_id" in tu and tu["step_id"], "tool_use missing step_id"
        assert "started_at" in tu and isinstance(tu["started_at"], float), "tool_use missing started_at"
    for tr in tool_result_events:
        assert "step_id" in tr and tr["step_id"], "tool_result missing step_id"
        assert "started_at" in tr and isinstance(tr["started_at"], float), "tool_result missing started_at"
        assert "completed_at" in tr and tr["completed_at"] >= tr["started_at"], "tool_result completed_at invalid"
    # verify call/result pairs share step_id
    use_ids = {tu["step_id"] for tu in tool_use_events}
    result_ids = {tr["step_id"] for tr in tool_result_events}
    assert result_ids.issubset(use_ids), "tool_result step_ids not a subset of tool_use step_ids"
    assert first.spec["chart_type"] == "bar"
    assert first.ai_state["turn_count"] == 1

    assert follow_up.agent_session_id == first.agent_session_id
    assert follow_up.spec["chart_type"] == "line"
    assert "沿用上一轮查询结果" in follow_up.final_text

    clear_agent_runtime_cache()
    recovered_runtime = get_agent_runtime()
    install_scripted_sdk_client(recovered_runtime, scenario)
    recovered = recovered_runtime.run_turn(
        AgentRequest(
            conversation_id="agent-runtime-conv-1",
            request_id="agent-runtime-req-3",
            user_id="alice",
            project_id="north",
            dataset_table=dataset_table,
            message="再改成柱状图",
            role="viewer",
            department="HR",
            clearance=1,
        )
    )

    assert recovered.agent_session_id == first.agent_session_id
    assert recovered.spec["chart_type"] == "bar"
    assert recovered_runtime.get_persisted_session("agent-runtime-conv-1") is not None


def test_agent_runtime_casts_string_hire_dates_before_extracting_year(
    monkeypatch, tmp_path: Path
) -> None:
    set_agent_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        dataset_table = upload_dataset(
            client,
            rows=[
                {"employee_id": "E-101", "department": "HR", "hire_date": "2024-03-18"},
                {"employee_id": "E-102", "department": "HR", "hire_date": "2026-01-12"},
                {"employee_id": "E-103", "department": "PM", "hire_date": "unknown"},
            ],
        )

        runtime = get_agent_runtime()
        rows = [
            {"hire_year": 2024, "metric_value": 1},
            {"hire_year": 2026, "metric_value": 1},
        ]
        sql = (
            'SELECT EXTRACT(year FROM TRY_CAST("hire_date" AS DATE)) AS hire_year, '
            'COUNT(*) AS metric_value FROM dataset GROUP BY hire_year'
        )
        install_scripted_sdk_client(
            runtime,
            lambda prompt, options: {  # type: ignore[no-untyped-def]
                "tool_calls": [_sql_tool_call(rows, sql)],
                "final_answer": {
                    "chart_type": "bar",
                    "title": "入职年份统计",
                    "x_key": "hire_year",
                    "y_key": "metric_value",
                    "series_key": None,
                    "metric_name": "headcount",
                    "rows": rows,
                    "conclusion": "按字符串日期转日期后统计。",
                    "scope": "当前数据集按入职年份统计",
                    "anomalies": "none",
                    "sql": sql,
                },
            },
        )
        result = runtime.run_turn(
            AgentRequest(
                conversation_id="agent-runtime-conv-string-dates",
                request_id="agent-runtime-req-string-dates",
                user_id="alice",
                project_id="north",
                dataset_table=dataset_table,
                message="柱状图显示入职年份统计",
                role="viewer",
                department="HR",
                clearance=1,
            )
        )

    assert result.final_status == "completed"
    assert result.spec["chart_type"] == "bar"
    assert result.spec["data"] == [
        {"hire_year": 2024, "metric_value": 1},
        {"hire_year": 2026, "metric_value": 1},
    ]
    assert 'TRY_CAST("hire_date" AS DATE)' in str(result.ai_state["latest_result"]["sql"])


def test_agent_runtime_passes_selected_response_locale_to_sdk_prompt(monkeypatch, tmp_path: Path) -> None:
    set_agent_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        dataset_table = upload_dataset(
            client,
            rows=[
                {"employee_id": "E-001", "rank_job_level": "L3"},
                {"employee_id": "E-002", "rank_job_level": "L4"},
            ],
        )

        runtime = get_agent_runtime()
        seen_system_prompts: list[str] = []

        def scenario(prompt: str, options) -> dict[str, object]:  # type: ignore[no-untyped-def]
            _ = prompt
            seen_system_prompts.append(str(options.system_prompt))
            rows = [{"rank_job_level": "L3", "headcount": 1}, {"rank_job_level": "L4", "headcount": 1}]
            return {
                "tool_calls": [
                    {
                        "name": "get_distinct_values",
                        "arguments": {"table": dataset_table, "field": "rank_job_level"},
                        "result": {"field": "rank_job_level", "values": rows, "row_count": 2},
                    }
                ],
                "final_answer": {
                    "chart_type": "bar",
                    "title": "各职级人数分布",
                    "x_key": "rank_job_level",
                    "y_key": "headcount",
                    "series_key": None,
                    "metric_name": "headcount",
                    "rows": rows,
                    "conclusion": "L3 和 L4 各有 1 人。",
                    "scope": "当前数据集全部记录。",
                    "anomalies": None,
                },
            }

        install_scripted_sdk_client(runtime, scenario)
        result = runtime.run_turn(
            AgentRequest(
                conversation_id="agent-runtime-conv-locale",
                request_id="agent-runtime-req-locale",
                user_id="alice",
                project_id="north",
                dataset_table=dataset_table,
                message="Please use #bar to summarize @rank_job_level",
                role="viewer",
                department="HR",
                clearance=1,
                response_locale="en-US",
            )
        )

    assert seen_system_prompts
    assert "selected locale is `en-US`" in seen_system_prompts[0]
    assert "Write every user-visible natural-language field in English" in seen_system_prompts[0]
    assert "rank_job_level value distribution has been generated" in result.final_text
    assert "Conclusion:" in result.final_text
    assert "口径:" not in result.final_text
    assert result.spec["title"] == "rank_job_level value distribution"


def test_agent_runtime_builds_salary_distribution_with_bucketed_sql(
    monkeypatch, tmp_path: Path
) -> None:
    set_agent_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        dataset_table = upload_dataset(
            client,
            rows=[
                {"employee_id": "E-201", "department": "HR", "salary": 8200},
                {"employee_id": "E-202", "department": "HR", "salary": 9900},
                {"employee_id": "E-203", "department": "PM", "salary": 15200},
                {"employee_id": "E-204", "department": "PM", "salary": 17900},
            ],
        )

        runtime = get_agent_runtime()
        rows = [
            {"salary_band": "5000-9999", "metric_value": 2},
            {"salary_band": "15000-19999", "metric_value": 2},
        ]
        sql = (
            'SELECT CONCAT(CAST(FLOOR("salary" / 5000) * 5000 AS VARCHAR), '
            '\'-\', CAST(FLOOR("salary" / 5000) * 5000 + 4999 AS VARCHAR)) AS salary_band, '
            'COUNT(*) AS metric_value FROM dataset GROUP BY salary_band'
        )
        install_scripted_sdk_client(
            runtime,
            lambda prompt, options: {  # type: ignore[no-untyped-def]
                "tool_calls": [_sql_tool_call(rows, sql)],
                "final_answer": {
                    "chart_type": "bar",
                    "title": "Salary Distribution",
                    "x_key": "salary_band",
                    "y_key": "metric_value",
                    "series_key": None,
                    "metric_name": "salary_distribution",
                    "rows": rows,
                    "conclusion": "薪资按区间聚合。",
                    "scope": "当前数据集薪资分布",
                    "anomalies": "none",
                    "sql": sql,
                },
            },
        )
        result = runtime.run_turn(
            AgentRequest(
                conversation_id="agent-runtime-conv-salary-distribution",
                request_id="agent-runtime-req-salary-distribution",
                user_id="alice",
                project_id="north",
                dataset_table=dataset_table,
                message="柱状图显示薪资分布统计",
                role="admin",
                department="HR",
                clearance=9,
            )
        )

    assert result.final_status == "completed"
    assert result.spec["chart_type"] == "bar"
    assert result.spec["title"] == "Salary Distribution"
    assert result.spec["data"] == [
        {"salary_band": "5000-9999", "metric_value": 2},
        {"salary_band": "15000-19999", "metric_value": 2},
    ]
    assert 'FLOOR("salary" / 5000)' in str(result.ai_state["latest_result"]["sql"])


def test_agent_runtime_builds_distribution_for_generic_numeric_columns(
    monkeypatch, tmp_path: Path
) -> None:
    set_agent_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        dataset_table = upload_dataset(
            client,
            rows=[
                {"employee_id": "E-301", "department": "HR", "score": 62},
                {"employee_id": "E-302", "department": "HR", "score": 68},
                {"employee_id": "E-303", "department": "PM", "score": 91},
                {"employee_id": "E-304", "department": "PM", "score": 95},
            ],
        )

        runtime = get_agent_runtime()
        rows = [
            {"score_band": "60-69", "metric_value": 2},
            {"score_band": "90-99", "metric_value": 2},
        ]
        sql = (
            'SELECT CONCAT(CAST(FLOOR("score" / 10) * 10 AS VARCHAR), '
            '\'-\', CAST(FLOOR("score" / 10) * 10 + 9 AS VARCHAR)) AS score_band, '
            'COUNT(*) AS metric_value FROM dataset GROUP BY score_band'
        )
        install_scripted_sdk_client(
            runtime,
            lambda prompt, options: {  # type: ignore[no-untyped-def]
                "tool_calls": [_sql_tool_call(rows, sql)],
                "final_answer": {
                    "chart_type": "bar",
                    "title": "Score Distribution",
                    "x_key": "score_band",
                    "y_key": "metric_value",
                    "series_key": None,
                    "metric_name": "score_distribution",
                    "rows": rows,
                    "conclusion": "score 按区间聚合。",
                    "scope": "当前数据集 score 分布",
                    "anomalies": "none",
                    "sql": sql,
                },
            },
        )
        result = runtime.run_turn(
            AgentRequest(
                conversation_id="agent-runtime-conv-score-distribution",
                request_id="agent-runtime-req-score-distribution",
                user_id="alice",
                project_id="north",
                dataset_table=dataset_table,
                message="柱状图显示 score 分布统计",
                role="admin",
                department="HR",
                clearance=9,
            )
        )

    assert result.final_status == "completed"
    assert result.spec["chart_type"] == "bar"
    assert result.spec["title"] == "Score Distribution"
    assert result.spec["data"] == [
        {"score_band": "60-69", "metric_value": 2},
        {"score_band": "90-99", "metric_value": 2},
    ]


def test_agent_runtime_rejects_ungrounded_final_answer_without_sdk_tool_use(
    monkeypatch, tmp_path: Path
) -> None:
    set_agent_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        dataset_table = upload_dataset(
            client,
            rows=[
                {"employee_id": "E-401", "department": "HR", "age": 29},
                {"employee_id": "E-402", "department": "PM", "age": 34},
            ],
        )

        runtime = get_agent_runtime()
        install_scripted_sdk_client(
            runtime,
            lambda prompt, options: {  # type: ignore[no-untyped-def]
                "tool_calls": [],
                "final_answer": {
                    "chart_type": "bar",
                    "title": "各部门员工年龄分布",
                    "x_key": "department",
                    "y_key": "age",
                    "series_key": None,
                    "metric_name": "avg_age_by_dept",
                    "rows": [{"department": "人力资源部", "age": 32.0}],
                    "conclusion": "未经过工具观测的答案。",
                    "scope": "未知",
                    "anomalies": "none",
                },
            },
        )
        result = runtime.run_turn(
            AgentRequest(
                conversation_id="agent-runtime-conv-ungrounded-answer",
                request_id="agent-runtime-req-ungrounded-answer",
                user_id="alice",
                project_id="north",
                dataset_table=dataset_table,
                message="请使用柱状图呈现部门员工年龄分布",
                role="viewer",
                department="HR",
                clearance=1,
            )
        )

    assert result.final_status == "completed"
    assert result.spec["chart_type"] == "empty"
    assert result.ai_state["latest_result"]["anomalies"] == "no_tool_observation"
    assert not any(item.get("event") == "tool_use" for item in result.tool_trace)


def test_sdk_tool_execution_errors_are_model_visible_observations(monkeypatch, tmp_path: Path) -> None:
    set_agent_env(monkeypatch, tmp_path)
    runtime = get_agent_runtime()
    request = AgentRequest(
        conversation_id="agent-runtime-conv-tool-error-observation",
        request_id="agent-runtime-req-tool-error-observation",
        user_id="alice",
        project_id="north",
        dataset_table="employees_wide",
        message="hi",
        role="viewer",
        department="HR",
        clearance=1,
    )
    run_context = SDKRunContext(
        request=request,
        session=AgentSessionState(
            conversation_id=request.conversation_id,
            agent_session_id="session-tool-error-observation",
        ),
        events=[],
        tool_trace=[],
    )

    async def invoke() -> dict[str, object]:
        return await runtime._invoke_sdk_tool(
            run_context=run_context,
            tool_name="describe_table",
            arguments={"table": "employees_wide"},
        )

    payload = anyio.run(invoke)

    assert payload["is_error"] is False
    content = payload["content"]
    assert isinstance(content, list)
    parsed = json.loads(str(content[0]["text"]))
    assert parsed["error"]["code"] == "NO_DATASET_TABLES"


def test_agent_runtime_retries_fresh_session_when_claude_resume_is_missing(
    monkeypatch, tmp_path: Path
) -> None:
    set_agent_env(monkeypatch, tmp_path)
    runtime = get_agent_runtime()
    stored = AgentSessionState(
        conversation_id="agent-runtime-conv-stale-claude-session",
        agent_session_id="stale-claude-session",
        turn_count=1,
        last_tool_trace=[
            {
                "event": "tool_result",
                "tool_name": "execute_readonly_sql",
                "status": "success",
                "result": {"rows": [{"level": "P6", "metric_value": 2}]},
            }
        ],
    )
    runtime._store.save(stored)

    class _MissingResumeThenFreshSDKClient:
        def __init__(self, *, options):  # type: ignore[no-untyped-def]
            self.options = options

        async def __aenter__(self):  # type: ignore[no-untyped-def]
            if self.options.resume == "stale-claude-session":
                raise RuntimeError("No conversation found with session ID: stale-claude-session")
            return self

        async def __aexit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
            return False

        async def query(self, prompt: str, session_id: str = "default") -> None:
            _ = (prompt, session_id)

        async def receive_response(self):  # type: ignore[no-untyped-def]
            final_answer = {
                "chart_type": "funnel",
                "title": "职级分布",
                "x_key": "level",
                "y_key": "metric_value",
                "series_key": None,
                "metric_name": "headcount",
                "rows": [{"level": "P6", "metric_value": 2}],
                "conclusion": "已基于保留的上下文恢复回答。",
                "scope": "NTN中心",
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

    runtime._sdk_client_factory = _MissingResumeThenFreshSDKClient
    result = runtime.run_turn(
        AgentRequest(
            conversation_id="agent-runtime-conv-stale-claude-session",
            request_id="agent-runtime-req-stale-claude-session",
            user_id="alice",
            project_id="north",
            dataset_table="employees_wide",
            message="请用漏斗图输出NTN中心所有人员的职级分布",
            role="viewer",
            department="HR",
            clearance=1,
            preferred_chart_type="funnel",
        )
    )

    assert result.final_status == "completed"
    assert result.agent_session_id == "fresh-claude-session"
    assert result.spec["chart_type"] == "funnel"
    assert result.ai_state["turn_count"] == 2


def test_agent_runtime_builds_multiple_funnel_echarts_spec(monkeypatch, tmp_path: Path) -> None:
    set_agent_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        dataset_table = upload_dataset(
            client,
            rows=[
                {"stage": "Show", "conversion": 100},
                {"stage": "Click", "conversion": 80},
                {"stage": "Visit", "conversion": 60},
                {"stage": "Inquiry", "conversion": 30},
                {"stage": "Order", "conversion": 10},
            ],
        )

        runtime = get_agent_runtime()
        rows = [
            {"stage": "Show", "metric_value": 100},
            {"stage": "Click", "metric_value": 80},
            {"stage": "Visit", "metric_value": 60},
            {"stage": "Inquiry", "metric_value": 30},
            {"stage": "Order", "metric_value": 10},
        ]
        install_scripted_sdk_client(
            runtime,
            lambda prompt, options: {  # type: ignore[no-untyped-def]
                "tool_calls": [
                    _sql_tool_call(
                        rows,
                        'SELECT "stage", "metric_value" FROM dataset',
                    )
                ],
                "final_answer": {
                    "chart_type": "funnel",
                    "title": "阶段转化多漏斗",
                    "x_key": "stage",
                    "y_key": "metric_value",
                    "series_key": None,
                    "metric_name": "conversion",
                    "rows": rows,
                    "conclusion": "转化随阶段推进递减。",
                    "scope": "按转化阶段统计",
                    "anomalies": "none",
                },
            },
        )
        result = runtime.run_turn(
            AgentRequest(
                conversation_id="agent-runtime-conv-multiple-funnel",
                request_id="agent-runtime-req-multiple-funnel",
                user_id="alice",
                project_id="north",
                dataset_table=dataset_table,
                message="请用 ECharts funnel-mutiple 展示阶段转化",
                role="viewer",
                department="HR",
                clearance=1,
                preferred_chart_type="funnel-mutiple",
            )
        )

    assert result.final_status == "completed"
    assert result.spec["engine"] == "echarts"
    assert result.spec["chart_type"] == "multiple_funnel"
    option = result.spec["config"]["option"]
    assert option["legend"]["data"] == ["Show", "Click", "Visit", "Inquiry", "Order"]
    assert len(option["series"]) == 4
    assert all(item["type"] == "funnel" for item in option["series"])
    assert option["series"][1]["sort"] == "ascending"
    assert option["series"][3]["label"]["position"] == "left"


def test_agent_runtime_builds_stacked_line_echarts_spec(monkeypatch, tmp_path: Path) -> None:
    set_agent_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        dataset_table = upload_dataset(
            client,
            rows=[
                {"month": "2026-01", "department": "HR", "headcount": 8},
                {"month": "2026-01", "department": "PM", "headcount": 5},
                {"month": "2026-02", "department": "HR", "headcount": 9},
                {"month": "2026-02", "department": "PM", "headcount": 6},
            ],
        )

        runtime = get_agent_runtime()
        rows = [
            {"month": "2026-01", "department": "HR", "metric_value": 8},
            {"month": "2026-01", "department": "PM", "metric_value": 5},
            {"month": "2026-02", "department": "HR", "metric_value": 9},
            {"month": "2026-02", "department": "PM", "metric_value": 6},
        ]
        install_scripted_sdk_client(
            runtime,
            lambda prompt, options: {  # type: ignore[no-untyped-def]
                "tool_calls": [
                    _sql_tool_call(
                        rows,
                        'SELECT "month", "department", "metric_value" FROM dataset',
                    )
                ],
                "final_answer": {
                    "chart_type": "stacked_line",
                    "title": "月度人力堆叠趋势",
                    "x_key": "month",
                    "y_key": "metric_value",
                    "series_key": "department",
                    "metric_name": "headcount",
                    "rows": rows,
                    "conclusion": "HR 与 PM 的人数趋势均上涨。",
                    "scope": "按月和部门统计",
                    "anomalies": "none",
                },
            },
        )
        result = runtime.run_turn(
            AgentRequest(
                conversation_id="agent-runtime-conv-stacked-line",
                request_id="agent-runtime-req-stacked-line",
                user_id="alice",
                project_id="north",
                dataset_table=dataset_table,
                message="请用堆叠折线图看部门月度人数趋势",
                role="viewer",
                department="HR",
                clearance=1,
                preferred_chart_type="stacked_line",
            )
        )

    assert result.final_status == "completed"
    assert result.spec["engine"] == "echarts"
    assert result.spec["chart_type"] == "stacked_line"
    option = result.spec["config"]["option"]
    assert option["series"]
    assert all(item["type"] == "line" for item in option["series"])
    assert all(item.get("stack") == "total" for item in option["series"])


def test_agent_runtime_builds_grouped_bar_echarts_spec(monkeypatch, tmp_path: Path) -> None:
    set_agent_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        dataset_table = upload_dataset(
            client,
            rows=[
                {"department": "HR", "period": "2026-Q1", "headcount": 8},
                {"department": "HR", "period": "2026-Q2", "headcount": 10},
                {"department": "PM", "period": "2026-Q1", "headcount": 5},
                {"department": "PM", "period": "2026-Q2", "headcount": 7},
            ],
        )

        runtime = get_agent_runtime()
        rows = [
            {"department": "HR", "period": "2026-Q1", "metric_value": 8},
            {"department": "HR", "period": "2026-Q2", "metric_value": 10},
            {"department": "PM", "period": "2026-Q1", "metric_value": 5},
            {"department": "PM", "period": "2026-Q2", "metric_value": 7},
        ]
        install_scripted_sdk_client(
            runtime,
            lambda prompt, options: {  # type: ignore[no-untyped-def]
                "tool_calls": [
                    _sql_tool_call(
                        rows,
                        'SELECT "department", "period", "metric_value" FROM dataset',
                    )
                ],
                "final_answer": {
                    "chart_type": "grouped_bar",
                    "title": "部门季度人数对比",
                    "x_key": "department",
                    "y_key": "metric_value",
                    "series_key": "period",
                    "metric_name": "headcount",
                    "rows": rows,
                    "conclusion": "Q2 各部门人数均高于 Q1。",
                    "scope": "按部门和季度统计",
                    "anomalies": "none",
                },
            },
        )
        result = runtime.run_turn(
            AgentRequest(
                conversation_id="agent-runtime-conv-grouped-bar",
                request_id="agent-runtime-req-grouped-bar",
                user_id="alice",
                project_id="north",
                dataset_table=dataset_table,
                message="请用分组条形图对比各部门不同季度人数",
                role="viewer",
                department="HR",
                clearance=1,
                preferred_chart_type="bar-y-category",
            )
        )

    assert result.final_status == "completed"
    assert result.spec["engine"] == "echarts"
    assert result.spec["chart_type"] == "grouped_bar"
    option = result.spec["config"]["option"]
    assert option["xAxis"]["type"] == "value"
    assert option["yAxis"]["type"] == "category"
    assert option["yAxis"]["data"] == ["HR", "PM"]
    assert [item["name"] for item in option["series"]] == ["2026-Q1", "2026-Q2"]
    assert all(item["type"] == "bar" for item in option["series"])
    assert all("stack" not in item for item in option["series"])
    assert option["series"][0]["data"] == [8, 5]
    assert option["series"][1]["data"] == [10, 7]


def test_agent_runtime_builds_negative_bar_echarts_spec(monkeypatch, tmp_path: Path) -> None:
    set_agent_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        dataset_table = upload_dataset(
            client,
            rows=[
                {"department": "HR", "delta": -3},
                {"department": "PM", "delta": 5},
            ],
        )

        runtime = get_agent_runtime()
        rows = [
            {"department": "HR", "metric_value": -3},
            {"department": "PM", "metric_value": 5},
        ]
        install_scripted_sdk_client(
            runtime,
            lambda prompt, options: {  # type: ignore[no-untyped-def]
                "tool_calls": [
                    _sql_tool_call(
                        rows,
                        'SELECT "department", "metric_value" FROM dataset',
                    )
                ],
                "final_answer": {
                    "chart_type": "negative_bar",
                    "title": "部门人数净变化",
                    "x_key": "department",
                    "y_key": "metric_value",
                    "series_key": None,
                    "metric_name": "headcount_delta",
                    "rows": rows,
                    "conclusion": "HR 减少，PM 增加。",
                    "scope": "按部门统计净变化",
                    "anomalies": "none",
                },
            },
        )
        result = runtime.run_turn(
            AgentRequest(
                conversation_id="agent-runtime-conv-negative-bar",
                request_id="agent-runtime-req-negative-bar",
                user_id="alice",
                project_id="north",
                dataset_table=dataset_table,
                message="请用负数柱状图看部门人数净变化",
                role="viewer",
                department="HR",
                clearance=1,
                preferred_chart_type="negative_bar",
            )
        )

    assert result.final_status == "completed"
    assert result.spec["engine"] == "echarts"
    assert result.spec["chart_type"] == "negative_bar"
    option = result.spec["config"]["option"]
    assert option["xAxis"]["type"] == "value"
    assert option["xAxis"]["position"] == "top"
    assert option["xAxis"]["splitLine"]["lineStyle"]["type"] == "dashed"
    assert option["yAxis"]["type"] == "category"
    assert option["yAxis"]["axisLabel"]["show"] is False
    assert option["series"][0]["type"] == "bar"
    assert option["series"][0]["label"]["formatter"] == "{b}"
    assert option["series"][0]["data"][0]["value"] == -3
    assert option["series"][0]["data"][0]["label"]["position"] == "right"
    assert option["series"][0]["data"][1]["value"] == 5


def test_agent_runtime_builds_scatter_clustering_echarts_spec(monkeypatch, tmp_path: Path) -> None:
    set_agent_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        dataset_table = upload_dataset(
            client,
            rows=[
                {"employee": "A", "tenure": 1, "salary": 10},
                {"employee": "B", "tenure": 2, "salary": 12},
                {"employee": "C", "tenure": 8, "salary": 30},
                {"employee": "D", "tenure": 9, "salary": 32},
            ],
        )

        runtime = get_agent_runtime()
        rows = [
            {"employee": "A", "tenure": 1, "salary": 10},
            {"employee": "B", "tenure": 2, "salary": 12},
            {"employee": "C", "tenure": 8, "salary": 30},
            {"employee": "D", "tenure": 9, "salary": 32},
        ]
        install_scripted_sdk_client(
            runtime,
            lambda prompt, options: {  # type: ignore[no-untyped-def]
                "tool_calls": [
                    _sql_tool_call(
                        rows,
                        'SELECT "employee", "tenure", "salary" FROM dataset',
                    )
                ],
                "final_answer": {
                    "chart_type": "scatter_clustering",
                    "title": "员工任期薪资聚类",
                    "x_key": "tenure",
                    "y_key": "salary",
                    "name_key": "employee",
                    "series_key": None,
                    "metric_name": "salary",
                    "rows": rows,
                    "conclusion": "样本可按任期与薪资分成两个主要点群。",
                    "scope": "按员工任期与薪资聚类",
                    "anomalies": "none",
                },
            },
        )
        result = runtime.run_turn(
            AgentRequest(
                conversation_id="agent-runtime-conv-scatter-clustering",
                request_id="agent-runtime-req-scatter-clustering",
                user_id="alice",
                project_id="north",
                dataset_table=dataset_table,
                message="请用 ECharts scatter-clustering 看任期和薪资的聚类",
                role="viewer",
                department="HR",
                clearance=1,
                preferred_chart_type="scatter-clustering",
            )
        )

    assert result.final_status == "completed"
    assert result.spec["engine"] == "echarts"
    assert result.spec["chart_type"] == "scatter_clustering"
    option = result.spec["config"]["option"]
    assert option["__requiresEchartsStat__"] == {"transforms": ["clustering"]}
    assert option["dataset"][1]["transform"]["type"] == "ecStat:clustering"
    assert option["dataset"][1]["transform"]["config"]["dimensions"] == [0, 1]
    assert option["dataset"][1]["transform"]["config"]["outputClusterIndexDimension"] == {
        "index": 3,
        "name": "cluster",
    }
    assert option["visualMap"]["type"] == "piecewise"
    assert option["visualMap"]["dimension"] == 3
    assert option["series"][0]["type"] == "scatter"
    assert option["series"][0]["datasetIndex"] == 1


def test_agent_runtime_surfaces_llm_summary_after_failed_tool_observation(
    monkeypatch, tmp_path: Path
) -> None:
    set_agent_env(monkeypatch, tmp_path)
    runtime = get_agent_runtime()

    class _ToolErrorThenSummarySDKClient:
        def __init__(self, *, options):  # type: ignore[no-untyped-def]
            self.options = options
            self.prompt = ""
            self.session_id = ""

        async def __aenter__(self):  # type: ignore[no-untyped-def]
            return self

        async def __aexit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
            return False

        async def query(self, prompt: str, session_id: str = "default") -> None:
            self.prompt = prompt
            self.session_id = session_id

        async def receive_response(self):  # type: ignore[no-untyped-def]
            tool_use_id = "toolu_failed_describe"
            tool_name = f"mcp__{SDK_MCP_SERVER_NAME}__describe_table"
            yield AssistantMessage(
                content=[
                    ToolUseBlock(
                        id=tool_use_id,
                        name=tool_name,
                        input={"table": "employees_wide"},
                    )
                ],
                model="claude-test",
                session_id=self.session_id,
            )
            yield UserMessage(
                content=[
                    ToolResultBlock(
                        tool_use_id=tool_use_id,
                        content=[
                            {
                                "type": "text",
                                "text": json.dumps(
                                    {
                                        "error": {
                                            "code": "NO_DATASET_TABLES",
                                            "message": "No dataset tables are available. Upload a dataset first.",
                                            "retryable": False,
                                        }
                                    },
                                    ensure_ascii=False,
                                ),
                            }
                        ],
                        is_error=True,
                    )
                ]
            )
            final_answer = {
                "chart_type": "table",
                "title": "数据集未就绪",
                "x_key": None,
                "y_key": None,
                "series_key": None,
                "metric_name": None,
                "rows": [{"should_not": "be rendered"}],
                "conclusion": "当前项目没有可用数据表，暂时无法回答分析问题。",
                "scope": "未执行数据分析查询。",
                "anomalies": "NO_DATASET_TABLES",
            }
            yield ResultMessage(
                subtype="success",
                duration_ms=1,
                duration_api_ms=1,
                is_error=False,
                num_turns=1,
                session_id=self.session_id,
                result=json.dumps(final_answer, ensure_ascii=False),
                structured_output=final_answer,
            )

    runtime._sdk_client_factory = _ToolErrorThenSummarySDKClient
    result = runtime.run_turn(
        AgentRequest(
            conversation_id="agent-runtime-conv-failed-tool-summary",
            request_id="agent-runtime-req-failed-tool-summary",
            user_id="alice",
            project_id="north",
            dataset_table="employees_wide",
            message="hi",
            role="viewer",
            department="HR",
            clearance=1,
        )
    )

    assert result.final_status == "completed"
    assert result.spec["chart_type"] == "empty"
    assert result.spec["data"] == []
    assert "当前项目没有可用数据表" in result.final_text
    assert result.ai_state["latest_result"]["rows"] == []
