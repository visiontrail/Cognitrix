from __future__ import annotations

from pathlib import Path

import anyio
import pytest
from claude_agent_sdk import (
    AssistantMessage,
    PermissionResultDeny,
    ResultMessage,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from apps.api.chart_query_agent import (
    ChartQueryAgent,
    ChartQueryAgentError,
    SNAPSHOT_ALLOWED_TOOL_NAMES,
    SnapshotDuckDBCache,
    SnapshotMCPTools,
)
from apps.api.published_pages import PublishedChartSnapshot, PublishedPage, SnapshotWriter


def test_snapshot_duckdb_cache_evicts_least_recently_used_page(tmp_path: Path) -> None:
    cache = SnapshotDuckDBCache(max_entries=1, ttl_seconds=1800)
    first_page = _write_page(tmp_path, page_id="page-a", workspace_id="workspace-a", chart_id="employees")
    second_page = _write_page(tmp_path, page_id="page-b", workspace_id="workspace-b", chart_id="finance")

    first_entry = cache.get(page=first_page)
    assert first_entry.tables["employees"].table_name == "employees"

    second_entry = cache.get(page=second_page)
    assert second_entry.tables["finance"].table_name == "finance"
    assert list(cache._entries) == ["page-b:1"]  # noqa: SLF001


def test_snapshot_duckdb_cache_keys_by_page_id_and_version(tmp_path: Path) -> None:
    cache = SnapshotDuckDBCache(max_entries=10, ttl_seconds=1800)
    first = _write_page(tmp_path, page_id="page-a", workspace_id="workspace-a", chart_id="employees", version=1)
    second = _write_page(tmp_path, page_id="page-a", workspace_id="workspace-a", chart_id="employees", version=2)

    assert cache.get(page=first).version == 1
    assert cache.get(page=second).version == 2
    assert list(cache._entries) == ["page-a:1", "page-a:2"]  # noqa: SLF001


def test_snapshot_duckdb_cache_reuses_and_expires_entries(tmp_path: Path) -> None:
    cache = SnapshotDuckDBCache(max_entries=10, ttl_seconds=60)
    page = _write_page(tmp_path, page_id="page-a", workspace_id="workspace-a", chart_id="employees")

    first = cache.get(page=page)
    immediate = cache.get(page=page)
    assert immediate is first

    first.last_accessed_at -= 120
    reloaded = cache.get(page=page)
    assert reloaded is not first


def test_chart_query_agent_injects_selected_chart_context(tmp_path: Path) -> None:
    page = _write_page(tmp_path, page_id="page-a", workspace_id="workspace-a", chart_id="employees")
    cache = SnapshotDuckDBCache(max_entries=10, ttl_seconds=1800)
    agent = ChartQueryAgent(tools=SnapshotMCPTools(cache=cache))

    prompt = agent.build_system_prompt(page=page, chart_id="employees")

    assert "Active chart context" in prompt
    assert "table_name: employees" in prompt
    assert "department, headcount" in prompt


def test_snapshot_query_tool_rejects_write_sql(tmp_path: Path) -> None:
    page = _write_page(tmp_path, page_id="page-a", workspace_id="workspace-a", chart_id="employees")
    tools = SnapshotMCPTools(cache=SnapshotDuckDBCache(max_entries=10, ttl_seconds=1800))

    result = tools.query_snapshot_table(page=page, sql="SELECT department, headcount FROM employees")
    assert result["rows"] == [{"department": "HR", "headcount": 4}]

    with pytest.raises(ChartQueryAgentError) as exc_info:
        tools.query_snapshot_table(page=page, sql="DELETE FROM employees")
    assert exc_info.value.code == "READ_ONLY_ONLY_SELECT"


def test_chart_query_agent_streams_sdk_events_with_snapshot_allowlist(tmp_path: Path) -> None:
    async def run() -> None:
        await _assert_chart_query_agent_streams_sdk_events_with_snapshot_allowlist(tmp_path)

    anyio.run(run)


async def _assert_chart_query_agent_streams_sdk_events_with_snapshot_allowlist(tmp_path: Path) -> None:
    page = _write_page(tmp_path, page_id="page-a", workspace_id="workspace-a", chart_id="employees")
    seen_options = []

    class FakeClaudeClient:
        def __init__(self, *, options):
            self.options = options
            seen_options.append(options)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def query(self, prompt: str) -> None:
            assert prompt == "How many employees?"

        async def receive_response(self):
            yield AssistantMessage(
                content=[
                    ThinkingBlock(thinking="Inspecting snapshot tables.", signature="sig"),
                    ToolUseBlock(
                        id="tool-1",
                        name="mcp__cognitrix_snapshot__list_snapshot_tables",
                        input={},
                    ),
                ],
                model="fake",
            )
            yield UserMessage(
                content=[
                    ToolResultBlock(
                        tool_use_id="tool-1",
                        content='{"tables":[{"table_name":"employees"}]}',
                        is_error=False,
                    )
                ]
            )
            yield ResultMessage(
                subtype="success",
                duration_ms=1,
                duration_api_ms=1,
                is_error=False,
                num_turns=1,
                session_id="public-session",
                result="There are 4 employees in HR.",
            )

    agent = ChartQueryAgent(
        tools=SnapshotMCPTools(cache=SnapshotDuckDBCache(max_entries=10, ttl_seconds=1800)),
        client_factory=FakeClaudeClient,
    )

    events = await agent.run_turn(
        page=page,
        message="How many employees?",
        request_id="req-1",
        conversation_id="conv-1",
    )

    assert [event for event, _ in events] == ["planning", "tool_use", "tool_result", "final"]
    tool_use = events[1][1]
    tool_result = events[2][1]
    assert tool_use["step_id"]
    assert tool_result["step_id"] == tool_use["step_id"]
    assert tool_result["completed_at"] >= tool_result["started_at"]
    assert seen_options[0].allowed_tools == list(SNAPSHOT_ALLOWED_TOOL_NAMES)
    denied = await seen_options[0].can_use_tool("mcp__cognitrix_snapshot__save_view", {}, None)
    assert isinstance(denied, PermissionResultDeny)


def _write_page(
    tmp_path: Path,
    *,
    page_id: str,
    workspace_id: str,
    chart_id: str,
    version: int = 1,
) -> PublishedPage:
    writer = SnapshotWriter(upload_dir=tmp_path / "uploads", max_rows=200)
    result = writer.write(
        workspace_id=workspace_id,
        version=version,
        canvas_format_id="web-design",
        layout={"grid": {"columns": 3}},
        sidebar=[],
        charts=[
            PublishedChartSnapshot(
                chart_id=chart_id,
                title="Headcount",
                chart_type="bar",
                spec={"chart_type": "bar", "title": "Headcount"},
                rows=[{"department": "HR", "headcount": 4}],
                assistant_rows=[{"department": "HR", "headcount": 4}],
                assistant_rows_complete=True,
            )
        ],
        actor_role="viewer",
        published_at="2026-04-24T00:00:00+00:00",
    )
    return PublishedPage(
        id=page_id,
        workspace_id=workspace_id,
        version=version,
        published_at="2026-04-24T00:00:00+00:00",
        published_by="alice",
        manifest_path=str(result.manifest_path),
    )
