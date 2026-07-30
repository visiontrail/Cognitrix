from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.agent_runtime import get_agent_runtime
from apps.api.main import app
from tests.agent_test_utils import install_scripted_sdk_client, read_sse_events, set_agent_env, upload_dataset
from tests.auth_utils import auth_headers

QUERY_CASES = [
    "柱状图显示入职年份统计",
    "按地区看离职人数趋势",
    "展示项目延期率并标出高风险项目",
]


def _evaluate_queries(client: TestClient, *, dataset_table: str, user_id: str, project_id: str) -> tuple[int, list[str]]:
    headers = auth_headers(
        client,
        user_id=user_id,
        project_id=project_id,
        role="admin",
        department="HR",
        clearance=9,
    )
    successes = 0
    final_texts: list[str] = []

    for index, query in enumerate(QUERY_CASES, start=1):
        with client.stream(
            "POST",
            "/chat/stream",
            json={
                "conversation_id": f"eval-conv-{index}",
                "request_id": f"eval-req-{index}",
                "user_id": user_id,
                "project_id": project_id,
                "dataset_table": dataset_table,
                "message": query,
            },
            headers=headers,
        ) as response:
            assert response.status_code == 200
            events, _ = read_sse_events(response)

        final_event = events[-1]["data"]
        final_text = str(final_event.get("text", ""))
        final_texts.append(final_text)
        if final_event.get("status") == "completed":
            successes += 1

    return successes, final_texts


def test_agent_prompting_long_tail_queries_complete(monkeypatch, tmp_path: Path) -> None:
    rows = [
        {
            "employee_id": "E-001",
            "department": "HR",
            "status": "active",
            "hire_year": 2022,
            "region": "East",
            "termination_date": None,
            "project": "Apollo",
            "is_delayed": False,
            "risk_level": "medium",
        },
        {
            "employee_id": "E-002",
            "department": "HR",
            "status": "inactive",
            "hire_year": 2023,
            "region": "East",
            "termination_date": "2026-03-01",
            "project": "Apollo",
            "is_delayed": True,
            "risk_level": "high",
        },
        {
            "employee_id": "E-003",
            "department": "PM",
            "status": "inactive",
            "hire_year": 2023,
            "region": "West",
            "termination_date": "2026-03-15",
            "project": "Nova",
            "is_delayed": True,
            "risk_level": "critical",
        },
        {
            "employee_id": "E-004",
            "department": "PM",
            "status": "active",
            "hire_year": 2024,
            "region": "West",
            "termination_date": None,
            "project": "Nova",
            "is_delayed": False,
            "risk_level": "low",
        },
    ]

    # This eval scores the single-answer contract (grounded answer carrying 口径 /
    # 异常说明). "按地区看离职人数趋势" is also a valid multi-chart candidate, and
    # that flow pauses for confirmation instead of answering — it has its own
    # coverage in tests/integration/test_multi_chart_generation.py.
    monkeypatch.setenv("MULTI_CHART_GENERATION_ENABLED", "false")
    set_agent_env(monkeypatch, tmp_path / "agent")
    with TestClient(app) as agent_client:
        agent_table = upload_dataset(
            agent_client,
            rows=rows,
            user_id="admin",
            project_id="north",
            role="admin",
            department="HR",
            clearance=9,
            filename="agent.xlsx",
        )
        runtime = get_agent_runtime()

        def scenario(prompt: str, options) -> dict[str, object]:  # type: ignore[no-untyped-def]
            _ = options
            if "地区" in prompt:
                chart_rows = [
                    {"region": "East", "metric_value": 1},
                    {"region": "West", "metric_value": 1},
                ]
                title = "按地区离职人数"
                x_key = "region"
                metric_name = "terminations_by_region"
            elif "延期率" in prompt:
                chart_rows = [
                    {"project": "Apollo", "metric_value": 0.5},
                    {"project": "Nova", "metric_value": 0.5},
                ]
                title = "项目延期率"
                x_key = "project"
                metric_name = "delay_rate"
            else:
                chart_rows = [
                    {"hire_year": 2022, "metric_value": 1},
                    {"hire_year": 2023, "metric_value": 2},
                    {"hire_year": 2024, "metric_value": 1},
                ]
                title = "入职年份统计"
                x_key = "hire_year"
                metric_name = "headcount_by_hire_year"
            return {
                "tool_calls": [
                    {
                        "name": "execute_readonly_sql",
                        "arguments": {"sql": "SELECT ...", "max_rows": 200},
                        "result": {"rows": chart_rows},
                    }
                ],
                "final_answer": {
                    "chart_type": "bar",
                    "title": title,
                    "x_key": x_key,
                    "y_key": "metric_value",
                    "series_key": None,
                    "metric_name": metric_name,
                    "rows": chart_rows,
                    "conclusion": "测试场景已通过 SDK 工具观测生成。",
                    "scope": "当前测试数据集",
                    "anomalies": "none",
                },
            }

        install_scripted_sdk_client(runtime, scenario)
        agent_successes, final_texts = _evaluate_queries(
            agent_client,
            dataset_table=agent_table,
            user_id="admin",
            project_id="north",
        )

    assert agent_successes == len(QUERY_CASES)
    assert all("口径:" in text for text in final_texts)
    assert all("异常说明:" in text for text in final_texts)
