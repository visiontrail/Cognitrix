from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.agent_runtime import AgentRequest, clear_agent_runtime_cache, get_agent_runtime
from apps.api.config import get_settings
from apps.api.main import app
from apps.api.tool_calling import clear_tool_calling_service_cache
from tests.agent_test_utils import install_scripted_sdk_client, set_agent_env, upload_dataset


def _enable_web(monkeypatch, tmp_path: Path) -> None:
    set_agent_env(monkeypatch, tmp_path)
    monkeypatch.setenv("WEB_SEARCH_ENABLED", "true")
    monkeypatch.setenv("WEB_SEARCH_API_KEY", "test-key")
    get_settings.cache_clear()
    clear_tool_calling_service_cache()
    clear_agent_runtime_cache()


def test_web_research_chain_emits_sources_and_grounds_answer(monkeypatch, tmp_path: Path) -> None:
    _enable_web(monkeypatch, tmp_path)

    with TestClient(app) as client:
        dataset_table = upload_dataset(
            client,
            rows=[{"employee_id": "E-001", "department": "Sales", "hire_year": 2024}],
        )

        runtime = get_agent_runtime()

        def scenario(prompt: str, options) -> dict[str, object]:  # type: ignore[no-untyped-def]
            _ = (prompt, options)
            return {
                "tool_calls": [
                    {
                        "name": "web_search",
                        "arguments": {"query": "2026 上半年中国新能源车销量"},
                        "result": {
                            "query": "2026 上半年中国新能源车销量",
                            "provider": "bocha",
                            "count": 2,
                            "results": [
                                {"title": "EV Report", "url": "https://a.example.com/ev", "snippet": "BYD 100"},
                                {"title": "Auto News", "url": "https://b.example.com/ev", "snippet": "Tesla 80"},
                            ],
                        },
                    },
                    {
                        "name": "web_fetch",
                        "arguments": {"url": "https://a.example.com/ev"},
                        "result": {
                            "url": "https://a.example.com/ev",
                            "title": "EV Report",
                            "content": "BYD sold 100 (万辆); Tesla sold 80 (万辆).",
                            "truncated": False,
                            "byte_size": 60,
                            "char_count": 42,
                        },
                    },
                    {
                        "name": "save_web_research",
                        "arguments": {
                            "table_name": "ev_sales_2026h1",
                            "columns": [
                                {"name": "brand", "type": "VARCHAR"},
                                {"name": "units", "type": "INTEGER"},
                            ],
                            "rows": [{"brand": "BYD", "units": 100}, {"brand": "Tesla", "units": 80}],
                            "sources": [{"url": "https://a.example.com/ev", "title": "EV Report"}],
                        },
                        "result": {
                            "table": "web_research_ev_sales_2026h1",
                            "row_count": 2,
                            "column_count": 2,
                            "columns": ["brand", "units"],
                            "source_urls": ["https://a.example.com/ev"],
                        },
                    },
                    {
                        "name": "execute_readonly_sql",
                        "arguments": {
                            "sql": 'SELECT brand, units FROM "web_research_ev_sales_2026h1" ORDER BY units DESC'
                        },
                        "result": {
                            "rows": [{"brand": "BYD", "units": 100}, {"brand": "Tesla", "units": 80}],
                            "sql": "SELECT brand, units FROM web_research_ev_sales_2026h1",
                        },
                    },
                ],
                "final_answer": {
                    "chart_type": "bar",
                    "title": "2026 H1 China EV sales",
                    "x_key": "brand",
                    "y_key": "units",
                    "series_key": None,
                    "metric_name": "units",
                    "rows": [{"brand": "BYD", "units": 100}, {"brand": "Tesla", "units": 80}],
                    "conclusion": "BYD leads with 100 vs Tesla 80 [1].",
                    "scope": "Public web data, units in 万辆.",
                    "anomalies": "none",
                    "sources": [
                        {"id": 1, "title": "EV Report", "url": "https://a.example.com/ev"},
                    ],
                },
            }

        install_scripted_sdk_client(runtime, scenario)
        result = runtime.run_turn(
            AgentRequest(
                conversation_id="web-chain-conv-1",
                request_id="web-chain-req-1",
                user_id="alice",
                project_id="north",
                dataset_table=dataset_table,
                message="2026 上半年中国新能源车销量各品牌对比",
                role="admin",
                department=None,
                clearance=9,
            )
        )

    assert result.final_status == "completed"

    tool_names = [
        payload.get("tool_name")
        for event_type, payload in result.events
        if event_type == "tool_use"
    ]
    assert "web_search" in tool_names
    assert "web_fetch" in tool_names
    assert "save_web_research" in tool_names

    final_events = [payload for event_type, payload in result.events if event_type == "final"]
    assert final_events, "expected a final event"
    sources = final_events[-1].get("sources")
    assert sources, "final event must carry sources when web tools were used"
    urls = {item["url"] for item in sources}
    assert "https://a.example.com/ev" in urls  # fetched page force-included
    assert all({"id", "title", "url"} <= set(item) for item in sources)

    # Answer stays grounded (rows survive) because web tools count as grounding.
    assert result.spec["chart_type"] == "bar"
    assert len(result.spec["data"]) == 2


def test_web_disabled_emits_no_sources(monkeypatch, tmp_path: Path) -> None:
    set_agent_env(monkeypatch, tmp_path)  # WEB_SEARCH_ENABLED=false

    with TestClient(app) as client:
        dataset_table = upload_dataset(
            client,
            rows=[{"employee_id": "E-001", "department": "Sales", "hire_year": 2024}],
        )
        runtime = get_agent_runtime()

        def scenario(prompt: str, options) -> dict[str, object]:  # type: ignore[no-untyped-def]
            _ = (prompt, options)
            return {
                "tool_calls": [
                    {
                        "name": "execute_readonly_sql",
                        "arguments": {"sql": 'SELECT department, COUNT(*) AS c FROM "dataset" GROUP BY department'},
                        "result": {"rows": [{"department": "Sales", "c": 1}], "sql": "SELECT ..."},
                    }
                ],
                "final_answer": {
                    "chart_type": "bar",
                    "title": "Headcount",
                    "x_key": "department",
                    "y_key": "c",
                    "rows": [{"department": "Sales", "c": 1}],
                    "conclusion": "One employee in Sales.",
                    "scope": "Local data.",
                    "anomalies": "none",
                },
            }

        install_scripted_sdk_client(runtime, scenario)
        result = runtime.run_turn(
            AgentRequest(
                conversation_id="web-off-conv-1",
                request_id="web-off-req-1",
                user_id="alice",
                project_id="north",
                dataset_table=dataset_table,
                message="按部门统计人数",
                role="admin",
                department=None,
                clearance=9,
            )
        )

    final_events = [payload for event_type, payload in result.events if event_type == "final"]
    assert final_events
    assert "sources" not in final_events[-1]
