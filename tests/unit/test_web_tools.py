from __future__ import annotations

import pytest

from apps.api.agent_guardrails import (
    AgentGuardrailContext,
    AgentGuardrailError,
    AgentGuardrails,
)
from apps.api.agent_runtime import (
    AgentRequest,
    AgentRuntime,
    AgentSessionState,
    SDKRunContext,
    clear_agent_runtime_cache,
)
from apps.api.config import get_settings
from apps.api.table_catalog import clear_table_catalog_service_cache
from apps.api.tool_calling import (
    ToolContext,
    clear_tool_calling_service_cache,
    get_tool_calling_service,
)
from apps.api.workspaces import clear_workspace_service_cache

from tests.agent_test_utils import set_agent_env


def _enable_web(monkeypatch, tmp_path, **overrides) -> None:
    set_agent_env(monkeypatch, tmp_path)
    monkeypatch.setenv("WEB_SEARCH_ENABLED", "true")
    monkeypatch.setenv("WEB_SEARCH_API_KEY", "test-key")
    for key, value in overrides.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    clear_tool_calling_service_cache()
    clear_agent_runtime_cache()
    clear_workspace_service_cache()
    clear_table_catalog_service_cache()


def test_system_prompt_includes_web_guidance_only_when_enabled():
    from apps.api.agent_prompting import build_agent_system_prompt

    disabled = build_agent_system_prompt(web_search_enabled=False)
    enabled = build_agent_system_prompt(web_search_enabled=True)
    assert "Web research" not in disabled
    assert "web_search" not in disabled
    assert "Web research" in enabled
    assert "Citation discipline" in enabled
    assert "save_web_research" in enabled


def _ctx() -> AgentGuardrailContext:
    return AgentGuardrailContext(role="admin", user_id="u1", project_id="p1")


def _tool_ctx() -> ToolContext:
    return ToolContext(
        user_id="u1",
        project_id="p1",
        workspace_id=None,
        dataset_table="web_research_ev_sales_2026h1",
        role="admin",
        department=None,
        clearance=9,
    )


# ---------------------------------------------------------------------------
# Guardrail switch + budget
# ---------------------------------------------------------------------------


def test_web_tools_absent_from_whitelist_when_disabled(monkeypatch, tmp_path):
    set_agent_env(monkeypatch, tmp_path)  # WEB_SEARCH_ENABLED=false
    guardrails = AgentGuardrails()
    assert "web_search" not in guardrails.allowed_tools
    with pytest.raises(AgentGuardrailError) as exc:
        guardrails.validate_tool_call(tool_name="web_search", arguments={}, context=_ctx())
    assert exc.value.code == "TOOL_NOT_ALLOWED"


def test_web_tools_in_whitelist_when_enabled(monkeypatch, tmp_path):
    _enable_web(monkeypatch, tmp_path)
    guardrails = AgentGuardrails()
    assert {"web_search", "web_fetch", "save_web_research"} <= set(guardrails.allowed_tools)
    # No exception for a valid web tool call.
    guardrails.validate_tool_call(tool_name="web_search", arguments={"query": "x"}, context=_ctx())


def test_web_call_budget_rejects_over_limit(monkeypatch, tmp_path):
    _enable_web(monkeypatch, tmp_path, WEB_SEARCH_MAX_CALLS_PER_TURN="2")
    guardrails = AgentGuardrails()
    guardrails.enforce_web_call_budget(0)
    guardrails.enforce_web_call_budget(1)
    with pytest.raises(AgentGuardrailError) as exc:
        guardrails.enforce_web_call_budget(2)
    assert exc.value.code == "WEB_SEARCH_BUDGET_EXCEEDED"
    assert guardrails.is_network_tool("web_fetch") is True
    assert guardrails.is_network_tool("save_web_research") is False


def test_runtime_active_tool_names_toggle(monkeypatch, tmp_path):
    _enable_web(monkeypatch, tmp_path)
    runtime = AgentRuntime()
    assert {"web_search", "web_fetch", "save_web_research"} <= runtime._active_tool_names

    clear_agent_runtime_cache()
    monkeypatch.setenv("WEB_SEARCH_ENABLED", "false")
    get_settings.cache_clear()
    disabled_runtime = AgentRuntime()
    assert "web_search" not in disabled_runtime._active_tool_names
    assert "save_web_research" not in disabled_runtime._active_tool_names


def _system_text_request(*, web_search_requested: bool) -> AgentRequest:
    return AgentRequest(
        conversation_id="c",
        request_id="r",
        user_id="u1",
        project_id="p1",
        dataset_table="t",
        message="compare 2024 salaries across regions",
        role="admin",
        department=None,
        clearance=9,
        web_search_requested=web_search_requested,
    )


def test_system_text_directive_when_user_requests_web_search(monkeypatch, tmp_path):
    _enable_web(monkeypatch, tmp_path)
    runtime = AgentRuntime()
    session = AgentSessionState(conversation_id="c", agent_session_id="s")

    requested = runtime._build_system_text(
        request=_system_text_request(web_search_requested=True), session=session
    )
    assert "Web search explicitly enabled by the user" in requested

    not_requested = runtime._build_system_text(
        request=_system_text_request(web_search_requested=False), session=session
    )
    assert "Web search explicitly enabled by the user" not in not_requested


def test_system_text_notes_unavailable_when_requested_but_disabled(monkeypatch, tmp_path):
    set_agent_env(monkeypatch, tmp_path)  # WEB_SEARCH_ENABLED=false
    get_settings.cache_clear()
    clear_tool_calling_service_cache()
    clear_agent_runtime_cache()
    runtime = AgentRuntime()
    session = AgentSessionState(conversation_id="c", agent_session_id="s")

    text = runtime._build_system_text(
        request=_system_text_request(web_search_requested=True), session=session
    )
    assert "web research tools are disabled" in text
    assert "Web search explicitly enabled by the user" not in text


# ---------------------------------------------------------------------------
# save_web_research: namespace, identifiers, scale, provenance, interop
# ---------------------------------------------------------------------------


def test_save_web_research_persists_with_provenance(monkeypatch, tmp_path):
    _enable_web(monkeypatch, tmp_path)
    service = get_tool_calling_service()
    ctx = _tool_ctx()
    result = service._tool_save_web_research(
        ctx,
        {
            "table_name": "ev_sales_2026h1",
            "columns": [
                {"name": "brand", "type": "VARCHAR"},
                {"name": "units", "type": "INTEGER"},
            ],
            "rows": [
                {"brand": "BYD", "units": 100},
                {"brand": "Tesla", "units": 80},
            ],
            "sources": [{"url": "https://example.com/ev", "title": "EV Report"}],
        },
    )
    assert result["table"] == "web_research_ev_sales_2026h1"
    assert result["row_count"] == 2
    assert result["column_count"] == 2

    tables = service._tool_list_tables(ctx, {})
    assert "web_research_ev_sales_2026h1" in tables["tables"]

    described = service._tool_describe_table(ctx, {"table": "web_research_ev_sales_2026h1"})
    column_names = {str(col.get("name")) for col in described["columns"]}
    assert {"_source_url", "_source_title", "_retrieved_at"} <= column_names

    distinct = service._tool_execute_readonly_sql(
        ctx,
        {"sql": 'SELECT DISTINCT _source_url FROM "web_research_ev_sales_2026h1"'},
    )
    urls = {row.get("_source_url") for row in distinct["rows"]}
    assert urls == {"https://example.com/ev"}


def test_save_web_research_without_workspace_skips_catalog(monkeypatch, tmp_path):
    _enable_web(monkeypatch, tmp_path)
    service = get_tool_calling_service()
    result = service._tool_save_web_research(
        _tool_ctx(),  # workspace_id=None
        {
            "table_name": "no_ws",
            "columns": [{"name": "x", "type": "INTEGER"}],
            "rows": [{"x": 1}],
            "sources": [{"url": "https://example.com/x"}],
        },
    )
    assert result["catalog_id"] is None


def test_save_web_research_registers_catalog_entry(monkeypatch, tmp_path):
    _enable_web(monkeypatch, tmp_path)
    from apps.api.db_migrations import apply_migrations
    from apps.api.table_catalog import get_table_catalog_service
    from apps.api.workspaces import get_workspace_service

    apply_migrations()  # relaxes the business_type CHECK so 'web_research' is accepted
    workspace = get_workspace_service().create_workspace(owner_user_id="u1", name="Research WS")
    workspace_id = workspace["workspace_id"]
    ctx = ToolContext(
        user_id="u1",
        project_id="p1",
        workspace_id=workspace_id,
        dataset_table="",
        role="admin",
        department=None,
        clearance=9,
    )
    service = get_tool_calling_service()
    arguments = {
        "table_name": "nev_top10",
        "human_label": "新能源销量前十",
        "columns": [
            {"name": "brand", "type": "VARCHAR"},
            {"name": "units", "type": "INTEGER"},
        ],
        "rows": [{"brand": "BYD", "units": 100}],
        "sources": [{"url": "https://example.com/ev", "title": "EV Report"}],
    }
    result = service._tool_save_web_research(ctx, arguments)
    assert result["catalog_id"]

    catalog = get_table_catalog_service()
    entries = catalog.list_entries(workspace_id=workspace_id)
    matches = [e for e in entries if e["table_name"] == "web_research_nev_top10"]
    assert len(matches) == 1
    entry = matches[0]
    assert entry["id"] == result["catalog_id"]
    assert entry["business_type"] == "web_research"
    assert entry["write_mode"] == "new_table"
    assert entry["time_grain"] == "none"
    assert entry["is_active_target"] is False
    assert entry["human_label"] == "新能源销量前十"
    assert "EV Report" in entry["description"]

    # Repeated save into the same table refreshes the entry instead of duplicating.
    again = service._tool_save_web_research(ctx, {**arguments, "human_label": "NEV Top 10"})
    assert again["catalog_id"] == result["catalog_id"]
    entries = catalog.list_entries(workspace_id=workspace_id)
    matches = [e for e in entries if e["table_name"] == "web_research_nev_top10"]
    assert len(matches) == 1
    assert matches[0]["human_label"] == "NEV Top 10"

    # Column metadata covers data + provenance columns for the catalog preview.
    import sqlite3

    with sqlite3.connect(catalog.db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT column_name, description FROM table_column_metadata "
            "WHERE workspace_id = ? AND table_name = ?",
            (workspace_id, "web_research_nev_top10"),
        ).fetchall()
    by_name = {str(row["column_name"]): row for row in rows}
    assert {"brand", "units", "_source_url", "_source_title", "_retrieved_at"} <= set(by_name)
    assert by_name["_source_url"]["description"] == "Source URL"


def test_save_web_research_rejects_bad_identifier(monkeypatch, tmp_path):
    _enable_web(monkeypatch, tmp_path)
    service = get_tool_calling_service()
    from apps.api.tool_calling import ToolExecutionError

    with pytest.raises(ToolExecutionError) as exc:
        service._tool_save_web_research(
            _tool_ctx(),
            {
                "table_name": "ev-sales; DROP",
                "columns": [{"name": "x", "type": "VARCHAR"}],
                "rows": [{"x": "1"}],
                "sources": [{"url": "https://e/1"}],
            },
        )
    assert exc.value.code == "INVALID_IDENTIFIER"


def test_save_web_research_rejects_reserved_and_bad_type(monkeypatch, tmp_path):
    _enable_web(monkeypatch, tmp_path)
    service = get_tool_calling_service()
    from apps.api.tool_calling import ToolExecutionError

    with pytest.raises(ToolExecutionError) as reserved:
        service._tool_save_web_research(
            _tool_ctx(),
            {
                "table_name": "t",
                "columns": [{"name": "_source_url", "type": "VARCHAR"}],
                "rows": [],
                "sources": [{"url": "https://e/1"}],
            },
        )
    assert reserved.value.code == "RESERVED_COLUMN_NAME"

    with pytest.raises(ToolExecutionError) as bad_type:
        service._tool_save_web_research(
            _tool_ctx(),
            {
                "table_name": "t",
                "columns": [{"name": "x", "type": "VARCHAR); DROP TABLE t; --"}],
                "rows": [],
                "sources": [{"url": "https://e/1"}],
            },
        )
    assert bad_type.value.code == "INVALID_COLUMN_TYPE"


def test_save_web_research_rejects_row_limit(monkeypatch, tmp_path):
    _enable_web(monkeypatch, tmp_path)
    service = get_tool_calling_service()
    from apps.api.tool_calling import ToolExecutionError

    with pytest.raises(ToolExecutionError) as exc:
        service._tool_save_web_research(
            _tool_ctx(),
            {
                "table_name": "big",
                "columns": [{"name": "x", "type": "INTEGER"}],
                "rows": [{"x": i} for i in range(1001)],
                "sources": [{"url": "https://e/1"}],
            },
        )
    assert exc.value.code == "WEB_RESEARCH_ROW_LIMIT_EXCEEDED"


def test_save_web_research_requires_sources(monkeypatch, tmp_path):
    _enable_web(monkeypatch, tmp_path)
    service = get_tool_calling_service()
    from apps.api.tool_calling import ToolExecutionError

    with pytest.raises(ToolExecutionError) as exc:
        service._tool_save_web_research(
            _tool_ctx(),
            {
                "table_name": "t",
                "columns": [{"name": "x", "type": "INTEGER"}],
                "rows": [{"x": 1}],
            },
        )
    assert exc.value.code == "WEB_RESEARCH_SOURCES_REQUIRED"


def test_web_search_success_path_returns_results(monkeypatch, tmp_path):
    _enable_web(monkeypatch, tmp_path)
    from apps.api import tool_calling as tool_calling_module
    from apps.api.web_research import SearchResult

    def _fake_search_web(query, *, top_k=None, settings=None):
        return [SearchResult(title="EV Report", url="https://example.com/ev", snippet="BYD leads")]

    monkeypatch.setattr(tool_calling_module, "search_web", _fake_search_web)
    service = get_tool_calling_service()
    result = service._tool_web_search(_tool_ctx(), {"query": "2026 H1 NEV sales", "top_k": 5})
    assert result["count"] == 1
    assert result["results"][0]["url"] == "https://example.com/ev"


def test_web_fetch_success_path_returns_content(monkeypatch, tmp_path):
    _enable_web(monkeypatch, tmp_path)
    from apps.api import tool_calling as tool_calling_module

    def _fake_fetch_page(url, *, settings=None):
        return {
            "url": url,
            "title": "EV Report",
            "content": "BYD leads the 2026 H1 ranking.",
            "truncated": False,
            "byte_size": 120,
            "char_count": 30,
        }

    monkeypatch.setattr(tool_calling_module, "fetch_page", _fake_fetch_page)
    service = get_tool_calling_service()
    result = service._tool_web_fetch(
        _tool_ctx(), {"url": "https://example.com/ev", "purpose": "ranking data"}
    )
    assert result["url"] == "https://example.com/ev"
    assert result["content"] == "BYD leads the 2026 H1 ranking."
    assert result["purpose"] == "ranking data"


def test_web_tools_disabled_raise_when_invoked_directly(monkeypatch, tmp_path):
    set_agent_env(monkeypatch, tmp_path)  # disabled
    service = get_tool_calling_service()
    from apps.api.tool_calling import ToolExecutionError

    with pytest.raises(ToolExecutionError) as exc:
        service._tool_web_search(_tool_ctx(), {"query": "x"})
    assert exc.value.code == "WEB_SEARCH_DISABLED"


# ---------------------------------------------------------------------------
# D5 sources assembly / accumulation
# ---------------------------------------------------------------------------


def _run_context() -> SDKRunContext:
    request = AgentRequest(
        conversation_id="c",
        request_id="r",
        user_id="u1",
        project_id="p1",
        dataset_table="t",
        message="external market data",
        role="admin",
        department=None,
        clearance=9,
    )
    session = AgentSessionState(conversation_id="c", agent_session_id="s")
    return SDKRunContext(request=request, session=session, events=[], tool_trace=[])


def test_accumulate_and_build_sources_backfills_fetched_pages():
    run_context = _run_context()
    AgentRuntime._accumulate_web_sources(
        run_context,
        "web_search",
        {"results": [{"url": "https://a.com", "title": "A"}, {"url": "https://b.com", "title": "B"}]},
    )
    AgentRuntime._accumulate_web_sources(
        run_context,
        "web_fetch",
        {"url": "https://b.com", "title": "B page"},
    )
    # Model declared only one source, omitting the fetched page b.com.
    final_answer = {"sources": [{"id": 1, "title": "A", "url": "https://a.com"}]}
    sources = AgentRuntime._build_sources_for_final(run_context, final_answer)
    urls = {item["url"] for item in sources}
    assert "https://b.com" in urls  # fetched page force-included
    assert "https://a.com" in urls
    assert [item["id"] for item in sources] == list(range(1, len(sources) + 1))


def test_build_sources_falls_back_to_accessed_when_model_silent():
    run_context = _run_context()
    AgentRuntime._accumulate_web_sources(
        run_context,
        "web_fetch",
        {"url": "https://x.com/report", "title": "Report"},
    )
    sources = AgentRuntime._build_sources_for_final(run_context, {"sources": []})
    assert sources == [{"id": 1, "title": "Report", "url": "https://x.com/report"}]


def test_build_sources_empty_without_web_usage():
    run_context = _run_context()
    assert AgentRuntime._build_sources_for_final(run_context, {"sources": []}) == []
    # A hallucinated sources field with no actual web access is dropped.
    assert AgentRuntime._build_sources_for_final(
        run_context, {"sources": [{"id": 1, "title": "x", "url": "https://y"}]}
    ) == []
