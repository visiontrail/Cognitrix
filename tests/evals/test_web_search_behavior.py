from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.agent_runtime import clear_agent_runtime_cache, get_agent_runtime
from apps.api.config import get_settings
from apps.api.main import app
from apps.api.tool_calling import clear_tool_calling_service_cache
from tests.agent_test_utils import install_scripted_sdk_client, read_sse_events, set_agent_env, upload_dataset
from tests.auth_utils import auth_headers


def _enable_web(monkeypatch, tmp_path: Path) -> None:
    set_agent_env(monkeypatch, tmp_path)
    monkeypatch.setenv("WEB_SEARCH_ENABLED", "true")
    monkeypatch.setenv("WEB_SEARCH_API_KEY", "test-key")
    get_settings.cache_clear()
    clear_tool_calling_service_cache()
    clear_agent_runtime_cache()


_ROWS = [{"employee_id": "E-001", "department": "Sales", "hire_year": 2024}]


def _search_scenario(prompt: str, options):  # type: ignore[no-untyped-def]
    _ = (prompt, options)
    return {
        "tool_calls": [
            {
                "name": "web_search",
                "arguments": {"query": "2026 上半年中国新能源车销量"},
                "result": {
                    "provider": "bocha",
                    "count": 1,
                    "results": [{"title": "EV Report", "url": "https://a.example.com/ev", "snippet": "BYD 100"}],
                },
            },
            {
                "name": "web_fetch",
                "arguments": {"url": "https://a.example.com/ev"},
                "result": {"url": "https://a.example.com/ev", "title": "EV Report", "content": "BYD 100万辆", "truncated": False, "byte_size": 20, "char_count": 8},
            },
        ],
        "final_answer": {
            "chart_type": "single_value",
            "title": "China EV sales",
            "x_key": None,
            "y_key": "units",
            "rows": [{"units": 100}],
            "conclusion": "China H1 2026 EV leader BYD sold 100万辆 [1].",
            "scope": "Public web data (万辆).",
            "anomalies": "none",
            "sources": [{"id": 1, "title": "EV Report", "url": "https://a.example.com/ev"}],
        },
    }


def _local_scenario(prompt: str, options):  # type: ignore[no-untyped-def]
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
            "title": "Headcount by department",
            "x_key": "department",
            "y_key": "c",
            "rows": [{"department": "Sales", "c": 1}],
            "conclusion": "Sales has 1 employee.",
            "scope": "Uploaded dataset.",
            "anomalies": "none",
        },
    }


def _run_turn(client: TestClient, dataset_table: str, message: str, conv: str):
    headers = auth_headers(client, user_id="alice", project_id="north", role="admin", department="HR", clearance=9)
    with client.stream(
        "POST",
        "/chat/stream",
        json={
            "conversation_id": conv,
            "request_id": f"{conv}-req",
            "user_id": "alice",
            "project_id": "north",
            "dataset_table": dataset_table,
            "message": message,
        },
        headers=headers,
    ) as response:
        assert response.status_code == 200
        events, _ = read_sse_events(response)
    return events


def test_eval_searches_and_cites_for_external_question(monkeypatch, tmp_path: Path) -> None:
    _enable_web(monkeypatch, tmp_path)
    with TestClient(app) as client:
        dataset_table = upload_dataset(client, rows=_ROWS, user_id="alice", project_id="north", role="admin", department="HR", clearance=9)
        install_scripted_sdk_client(get_agent_runtime(), _search_scenario)
        events = _run_turn(client, dataset_table, "2026 上半年中国新能源车销量第一是谁", "eval-web-1")

    tool_names = [e["data"].get("tool_name") for e in events if e["event"] == "tool_use"]
    assert "web_search" in tool_names  # searched when the answer needs external data

    final = [e["data"] for e in events if e["event"] == "final"][-1]
    assert final.get("status") == "completed"
    sources = final.get("sources") or []
    assert sources, "external answer must cite sources"

    # Every [n] citation in the prose resolves to a declared source id.
    source_ids = {int(item["id"]) for item in sources}
    cited = {int(n) for n in re.findall(r"\[(\d+)\]", str(final.get("text", "")))}
    assert cited, "prose should contain at least one [n] citation"
    assert cited.issubset(source_ids)


def test_eval_does_not_search_for_local_question(monkeypatch, tmp_path: Path) -> None:
    _enable_web(monkeypatch, tmp_path)
    with TestClient(app) as client:
        dataset_table = upload_dataset(client, rows=_ROWS, user_id="alice", project_id="north", role="admin", department="HR", clearance=9)
        install_scripted_sdk_client(get_agent_runtime(), _local_scenario)
        events = _run_turn(client, dataset_table, "按部门统计在职人数", "eval-web-2")

    tool_names = [e["data"].get("tool_name") for e in events if e["event"] == "tool_use"]
    assert "web_search" not in tool_names
    assert "web_fetch" not in tool_names

    final = [e["data"] for e in events if e["event"] == "final"][-1]
    assert "sources" not in final  # pure-local answers carry no citation区
