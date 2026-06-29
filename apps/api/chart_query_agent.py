from __future__ import annotations

import json
import re
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, AsyncGenerator, Callable

import duckdb
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolAnnotations,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    create_sdk_mcp_server,
    tool,
)

from .config import get_settings
from .published_pages import PublishedPage, read_manifest
from .security import SQLGuardError, SQLReadOnlyValidator

SNAPSHOT_MCP_SERVER_NAME = "cognitrix_snapshot"
SNAPSHOT_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "list_snapshot_tables",
        "description": "List assistant-enabled tables in the immutable published snapshot.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "describe_snapshot_table",
        "description": "Describe columns and sample rows for one published snapshot table.",
        "parameters": {
            "type": "object",
            "properties": {
                "table_name": {"type": "string"},
                "sample_limit": {"type": "integer", "description": "Sample rows to return, 1-50."},
            },
            "required": ["table_name"],
        },
    },
    {
        "name": "query_snapshot_table",
        "description": "Run one read-only SELECT query against published snapshot tables.",
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {"type": "string"},
                "max_rows": {"type": "integer", "description": "Rows to return, capped by server settings."},
            },
            "required": ["sql"],
        },
    },
]
SNAPSHOT_TOOL_NAMES = tuple(item["name"] for item in SNAPSHOT_TOOL_DEFINITIONS)
SNAPSHOT_ALLOWED_TOOL_NAMES = tuple(
    f"mcp__{SNAPSHOT_MCP_SERVER_NAME}__{name}" for name in SNAPSHOT_TOOL_NAMES
)


class ChartQueryAgentError(Exception):
    def __init__(self, *, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code

    def to_detail(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
        }


@dataclass(slots=True)
class SnapshotTable:
    chart_id: str
    table_name: str
    title: str
    chart_type: str | None
    row_count: int
    columns: list[dict[str, str]]
    node_ids: list[str]
    pages: list[str]


@dataclass(slots=True)
class SnapshotDuckDBEntry:
    cache_key: str
    page_id: str
    version: int
    connection: duckdb.DuckDBPyConnection
    tables: dict[str, SnapshotTable]
    created_at: float
    last_accessed_at: float


@dataclass(slots=True)
class SnapshotToolInvocationRecord:
    tool_name: str
    arguments: dict[str, Any]
    step: int
    step_id: str
    started_at: float
    tool_use_id: str | None = None
    result_data: dict[str, Any] | None = None
    status: str = "success"
    error: dict[str, Any] | None = None
    tool_use_emitted: bool = False
    tool_result_emitted: bool = False


@dataclass(slots=True)
class ChartQueryRunContext:
    page: PublishedPage
    conversation_id: str
    request_id: str
    message: str
    chart_id: str | None
    events: list[tuple[str, dict[str, Any]]]
    text_blocks: list[str]
    records_by_tool_use_id: dict[str, SnapshotToolInvocationRecord]
    records: list[SnapshotToolInvocationRecord]
    tool_step_count: int = 0
    planning_emitted: bool = False


class SnapshotDuckDBCache:
    def __init__(self, *, max_entries: int = 10, ttl_seconds: int = 30 * 60) -> None:
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self._entries: OrderedDict[str, SnapshotDuckDBEntry] = OrderedDict()
        self._lock = Lock()

    def get(self, *, page: PublishedPage) -> SnapshotDuckDBEntry:
        now = time.monotonic()
        cache_key = _snapshot_cache_key(page)
        with self._lock:
            self._evict_expired(now=now)
            cached = self._entries.get(cache_key)
            if cached is not None:
                cached.last_accessed_at = now
                self._entries.move_to_end(cache_key)
                return cached

        loaded = self._load_page(page=page, now=now)
        with self._lock:
            existing = self._entries.get(cache_key)
            if existing is not None:
                loaded.connection.close()
                existing.last_accessed_at = now
                self._entries.move_to_end(cache_key)
                return existing
            self._entries[cache_key] = loaded
            self._entries.move_to_end(cache_key)
            self._evict_over_capacity()
            return loaded

    def clear(self) -> None:
        with self._lock:
            for entry in self._entries.values():
                entry.connection.close()
            self._entries.clear()

    def _load_page(self, *, page: PublishedPage, now: float) -> SnapshotDuckDBEntry:
        manifest = read_manifest(page, include_internal_paths=True)
        assistant = manifest.get("assistant") if isinstance(manifest.get("assistant"), dict) else {}
        if not assistant.get("available"):
            raise ChartQueryAgentError(
                code="SNAPSHOT_ASSISTANT_UNAVAILABLE",
                message="This published snapshot does not include assistant data.",
                status_code=404,
            )

        manifest_dir = Path(page.manifest_path).parent
        charts = manifest.get("charts")
        if not isinstance(charts, list):
            charts = []
        chart_context = _chart_context_by_id(manifest)

        connection = duckdb.connect(database=":memory:")
        tables: dict[str, SnapshotTable] = {}
        used_table_names: set[str] = set()
        try:
            for index, chart in enumerate(charts, start=1):
                if not isinstance(chart, dict) or not chart.get("assistant_data_available"):
                    continue
                chart_id = str(chart.get("chart_id") or f"chart_{index}")
                assistant_path = manifest_dir / str(chart.get("assistant_data_path") or "")
                if not assistant_path.exists():
                    raise ChartQueryAgentError(
                        code="SNAPSHOT_ASSISTANT_DATA_NOT_FOUND",
                        message=f"Assistant data for chart '{chart_id}' was not found.",
                        status_code=404,
                    )
                table_name = _dedupe_table_name(
                    _safe_table_name(chart_id, fallback=f"chart_{index}"),
                    used_table_names,
                )
                connection.execute(
                    f'CREATE TABLE "{table_name}" AS SELECT * FROM read_json_auto(?)',
                    [str(assistant_path)],
                )
                columns = [
                    {"name": str(row[1]), "type": str(row[2])}
                    for row in connection.execute(f'PRAGMA table_info("{table_name}")').fetchall()
                ]
                metadata = chart_context.get(chart_id, {})
                tables[chart_id] = SnapshotTable(
                    chart_id=chart_id,
                    table_name=table_name,
                    title=str(chart.get("title") or chart_id),
                    chart_type=str(chart.get("chart_type")) if chart.get("chart_type") else None,
                    row_count=int(chart.get("assistant_row_count") or 0),
                    columns=columns,
                    node_ids=[str(item) for item in metadata.get("node_ids", [])],
                    pages=[str(item) for item in metadata.get("pages", [])],
                )
        except Exception:
            connection.close()
            raise

        if not tables:
            connection.close()
            raise ChartQueryAgentError(
                code="SNAPSHOT_ASSISTANT_UNAVAILABLE",
                message="This published snapshot does not include assistant data.",
                status_code=404,
            )

        return SnapshotDuckDBEntry(
            cache_key=_snapshot_cache_key(page),
            page_id=page.id,
            version=page.version,
            connection=connection,
            tables=tables,
            created_at=now,
            last_accessed_at=now,
        )

    def _evict_expired(self, *, now: float) -> None:
        expired = [
            cache_key
            for cache_key, entry in self._entries.items()
            if now - entry.last_accessed_at > self.ttl_seconds
        ]
        for cache_key in expired:
            entry = self._entries.pop(cache_key)
            entry.connection.close()

    def _evict_over_capacity(self) -> None:
        while len(self._entries) > self.max_entries:
            _, entry = self._entries.popitem(last=False)
            entry.connection.close()


class SnapshotMCPTools:
    def __init__(self, *, cache: SnapshotDuckDBCache, max_query_rows: int | None = None) -> None:
        self.cache = cache
        self.max_query_rows = max_query_rows or get_settings().public_assistant_max_query_rows

    def list_snapshot_tables(self, *, page: PublishedPage) -> dict[str, Any]:
        entry = self.cache.get(page=page)
        return {
            "tables": [
                {
                    "chart_id": table.chart_id,
                    "table_name": table.table_name,
                    "title": table.title,
                    "chart_type": table.chart_type,
                    "row_count": table.row_count,
                    "columns": [column["name"] for column in table.columns],
                    "node_ids": table.node_ids,
                    "pages": table.pages,
                }
                for table in entry.tables.values()
            ]
        }

    def describe_snapshot_table(
        self,
        *,
        page: PublishedPage,
        table_name: str,
        sample_limit: int = 8,
    ) -> dict[str, Any]:
        entry = self.cache.get(page=page)
        table = _find_table(entry, table_name=table_name)
        limit = max(1, min(int(sample_limit), 50))
        rows = entry.connection.execute(
            f'SELECT * FROM "{table.table_name}" LIMIT ?',
            [limit],
        ).fetchall()
        column_names = [item["name"] for item in table.columns]
        return {
            "chart_id": table.chart_id,
            "table_name": table.table_name,
            "title": table.title,
            "chart_type": table.chart_type,
            "row_count": table.row_count,
            "columns": table.columns,
            "sample_rows": [dict(zip(column_names, row, strict=False)) for row in rows],
        }

    def query_snapshot_table(
        self,
        *,
        page: PublishedPage,
        sql: str,
        max_rows: int | None = None,
    ) -> dict[str, Any]:
        entry = self.cache.get(page=page)
        table_names = {table.table_name for table in entry.tables.values()}
        columns_by_table = {
            table.table_name: {column["name"] for column in table.columns}
            for table in entry.tables.values()
        }
        validator = SQLReadOnlyValidator(
            allowed_tables=table_names,
            allowed_columns_by_table=columns_by_table,
        )
        try:
            validator.validate(sql)
        except SQLGuardError as exc:
            raise ChartQueryAgentError(
                code=exc.code,
                message=exc.message,
                status_code=400,
            ) from exc

        limit = max(1, min(int(max_rows or self.max_query_rows), self.max_query_rows))
        cursor = entry.connection.execute(sql)
        column_names = [item[0] for item in cursor.description or []]
        rows = cursor.fetchmany(limit)
        return {
            "columns": column_names,
            "rows": [dict(zip(column_names, row, strict=False)) for row in rows],
            "row_count": len(rows),
            "max_rows": limit,
        }


class ChartQueryAgent:
    def __init__(
        self,
        *,
        tools: SnapshotMCPTools | None = None,
        client_factory: Callable[..., Any] = ClaudeSDKClient,
    ) -> None:
        self.tools = tools or SnapshotMCPTools(cache=get_snapshot_duckdb_cache())
        self.client_factory = client_factory

    def load_skill_plugins(self) -> list[dict[str, str]]:
        """Return ``plugins=`` configs for skills assigned to ChartQueryAgent."""
        from .agent_skills.agents import CHART_QUERY_AGENT
        from .agent_skills.loader import load_skill_plugins_for_agent

        return load_skill_plugins_for_agent(CHART_QUERY_AGENT)

    def build_system_prompt(self, *, page: PublishedPage, chart_id: str | None = None) -> str:
        entry = self.tools.cache.get(page=page)
        table_summaries = [
            f"- {table.table_name}: {table.title}"
            + (f" ({table.chart_type})" if table.chart_type else "")
            + f"; rows: {table.row_count}; columns: {', '.join(column['name'] for column in table.columns)}"
            for table in entry.tables.values()
        ]
        prompt = (
            "You are the Cognitrix public published-page AI assistant. "
            "Use only immutable published snapshot data. "
            "You may call only list_snapshot_tables, describe_snapshot_table, and query_snapshot_table. "
            "Never mention filesystem paths, internal page ids, workspace membership, bearer tokens, "
            "agent session ids, live DuckDB sessions, unpublished workspace state, or tool configuration. "
            "If the answer cannot be derived from the published snapshot tables, say that plainly.\n\n"
            "Snapshot tables:\n"
            + "\n".join(table_summaries)
        )
        if chart_id:
            table = entry.tables.get(chart_id)
            if table is None:
                raise ChartQueryAgentError(
                    code="SNAPSHOT_CHART_NOT_FOUND",
                    message="Selected chart is not part of this published page.",
                    status_code=404,
                )
            prompt += (
                "\n\nActive chart context:\n"
                f"table_name: {table.table_name}\n"
                f"chart_title: {table.title}\n"
                f"chart_type: {table.chart_type or 'unknown'}\n"
                f"row_count: {table.row_count}\n"
                f"columns: {', '.join(column['name'] for column in table.columns)}"
            )
        return prompt

    async def run_turn(
        self,
        *,
        page: PublishedPage,
        message: str,
        request_id: str,
        conversation_id: str,
        chart_id: str | None = None,
    ) -> list[tuple[str, dict[str, Any]]]:
        events: list[tuple[str, dict[str, Any]]] = []
        async for event in self.run_turn_stream(
            page=page,
            message=message,
            request_id=request_id,
            conversation_id=conversation_id,
            chart_id=chart_id,
        ):
            events.append(event)
        return events

    async def run_turn_stream(
        self,
        *,
        page: PublishedPage,
        message: str,
        request_id: str,
        conversation_id: str,
        chart_id: str | None = None,
    ) -> AsyncGenerator[tuple[str, dict[str, Any]], None]:
        if not message.strip():
            raise ChartQueryAgentError(
                code="PUBLIC_ASSISTANT_MESSAGE_REQUIRED",
                message="message is required",
                status_code=422,
            )
        system_prompt = self.build_system_prompt(page=page, chart_id=chart_id)
        context = ChartQueryRunContext(
            page=page,
            conversation_id=conversation_id,
            request_id=request_id,
            message=message,
            chart_id=chart_id,
            events=[],
            text_blocks=[],
            records_by_tool_use_id={},
            records=[],
        )
        options = self._build_sdk_options(system_prompt=system_prompt, run_context=context)
        final_emitted = False
        try:
            async with self.client_factory(options=options) as client:
                await client.query(message)
                while context.events:
                    event = context.events.pop(0)
                    final_emitted = final_emitted or event[0] == "final"
                    yield event
                async for sdk_message in client.receive_response():
                    while context.events:
                        event = context.events.pop(0)
                        final_emitted = final_emitted or event[0] == "final"
                        yield event
                    for event in self._consume_sdk_message(message=sdk_message, run_context=context):
                        final_emitted = final_emitted or event[0] == "final"
                        yield event
                    while context.events:
                        event = context.events.pop(0)
                        final_emitted = final_emitted or event[0] == "final"
                        yield event
        except ChartQueryAgentError:
            raise
        except Exception as exc:
            yield (
                "error",
                {
                    "conversation_id": conversation_id,
                    "request_id": request_id,
                    "status": "failed",
                    "code": "PUBLIC_ASSISTANT_AGENT_FAILED",
                    "message": "Public assistant failed. Please retry.",
                },
            )
            yield (
                "final",
                {
                    "conversation_id": conversation_id,
                    "request_id": request_id,
                    "status": "failed",
                    "text": "Public assistant failed. Please retry.",
                },
            )
            _ = exc
            return

        self._flush_pending_tool_results(run_context=context)
        while context.events:
            event = context.events.pop(0)
            final_emitted = final_emitted or event[0] == "final"
            yield event
        if not final_emitted:
            text = "\n".join(item.strip() for item in context.text_blocks if item.strip()).strip()
            if text:
                yield (
                    "final",
                    {
                        "conversation_id": conversation_id,
                        "request_id": request_id,
                        "status": "completed",
                        "text": text,
                    },
                )

    def _build_sdk_options(
        self,
        *,
        system_prompt: str,
        run_context: ChartQueryRunContext,
    ) -> ClaudeAgentOptions:
        async def can_use_tool(
            tool_name: str,
            input_data: dict[str, Any],
            permission_context: Any,
        ) -> PermissionResultAllow | PermissionResultDeny:
            _ = (input_data, permission_context)
            canonical = _canonical_snapshot_tool_name(tool_name)
            if canonical not in SNAPSHOT_TOOL_NAMES:
                return PermissionResultDeny(message="Tool is outside the published snapshot surface.")
            return PermissionResultAllow()

        async def pre_tool_use(
            input_data: dict[str, Any],
            tool_use_id: str | None,
            hook_context: dict[str, Any],
        ) -> dict[str, Any]:
            _ = hook_context
            tool_name = _canonical_snapshot_tool_name(str(input_data.get("tool_name") or ""))
            arguments = input_data.get("tool_input")
            if not isinstance(arguments, dict):
                arguments = {}
            if tool_name in SNAPSHOT_TOOL_NAMES:
                self._record_tool_use(
                    run_context=run_context,
                    tool_name=tool_name,
                    arguments=arguments,
                    tool_use_id=tool_use_id or str(input_data.get("tool_use_id") or "") or None,
                )
                return {}
            return {
                "hookSpecificOutput": {
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "Tool is outside the published snapshot surface.",
                }
            }

        async def post_tool_use(
            input_data: dict[str, Any],
            tool_use_id: str | None,
            hook_context: dict[str, Any],
        ) -> dict[str, Any]:
            _ = hook_context
            resolved_tool_use_id = tool_use_id or str(input_data.get("tool_use_id") or "") or None
            record = run_context.records_by_tool_use_id.get(resolved_tool_use_id or "")
            if record is None:
                tool_name = _canonical_snapshot_tool_name(str(input_data.get("tool_name") or ""))
                arguments = input_data.get("tool_input") if isinstance(input_data.get("tool_input"), dict) else {}
                record = self._record_tool_use(
                    run_context=run_context,
                    tool_name=tool_name,
                    arguments=arguments,
                    tool_use_id=resolved_tool_use_id,
                )
            if record.result_data is None:
                record.result_data = _extract_hook_tool_response(input_data)
                record.status = "error" if bool(input_data.get("is_error")) else record.status
            self._record_tool_result(run_context=run_context, record=record)
            return {}

        server = create_sdk_mcp_server(
            name=SNAPSHOT_MCP_SERVER_NAME,
            version="1.0.0",
            tools=self._build_sdk_tools(run_context=run_context),
        )
        settings = get_settings()
        env: dict[str, str] = {
            "API_TIMEOUT_MS": str(settings.api_timeout_ms),
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        }
        auth_token_source = settings.anthropic_auth_token or settings.ai_api_key
        auth_token = auth_token_source.strip()
        if auth_token:
            env["ANTHROPIC_API_KEY"] = auth_token
            env["ANTHROPIC_AUTH_TOKEN"] = auth_token
        if settings.anthropic_base_url.strip():
            env["ANTHROPIC_BASE_URL"] = settings.anthropic_base_url.strip()
        model = settings.ai_model.strip() or None
        if model:
            env["ANTHROPIC_MODEL"] = model
            env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = (
                settings.anthropic_default_haiku_model.strip() or model
            )

        return ClaudeAgentOptions(
            tools=[],
            allowed_tools=list(SNAPSHOT_ALLOWED_TOOL_NAMES),
            system_prompt=system_prompt,
            mcp_servers={SNAPSHOT_MCP_SERVER_NAME: server},
            can_use_tool=can_use_tool,
            hooks={
                "PreToolUse": [HookMatcher(matcher=None, hooks=[pre_tool_use])],
                "PostToolUse": [HookMatcher(matcher=None, hooks=[post_tool_use])],
            },
            permission_mode="default",
            session_id=None,
            max_turns=settings.agent_max_tool_steps,
            model=model,
            cwd=str(Path.cwd()),
            env=env,
            plugins=self.load_skill_plugins(),
            output_format=None,
        )

    def _build_sdk_tools(self, *, run_context: ChartQueryRunContext) -> list[Any]:
        sdk_tools: list[Any] = []
        annotations = ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        )
        for definition in SNAPSHOT_TOOL_DEFINITIONS:
            tool_name = str(definition["name"])
            description = str(definition["description"])
            input_schema = definition["parameters"]

            async def handler(args: dict[str, Any], _tool_name: str = tool_name) -> dict[str, Any]:
                return await self._invoke_sdk_tool(
                    run_context=run_context,
                    tool_name=_tool_name,
                    arguments=args,
                )

            sdk_tools.append(
                tool(
                    tool_name,
                    description,
                    input_schema,
                    annotations=annotations,
                )(handler)
            )
        return sdk_tools

    async def _invoke_sdk_tool(
        self,
        *,
        run_context: ChartQueryRunContext,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        canonical = _canonical_snapshot_tool_name(tool_name)
        record = self._record_tool_use(
            run_context=run_context,
            tool_name=canonical,
            arguments=arguments,
            tool_use_id=None,
        )
        try:
            result = self._invoke_tool(page=run_context.page, tool_name=canonical, arguments=arguments)
            record.status = "success"
            record.result_data = result
            record.error = None
        except ChartQueryAgentError as exc:
            record.status = "error"
            record.error = {"code": exc.code, "message": exc.message}
            record.result_data = {"error": record.error}
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(record.result_data or {}, ensure_ascii=False, default=str),
                }
            ],
            "is_error": False,
        }

    def _invoke_tool(
        self,
        *,
        page: PublishedPage,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        if tool_name == "list_snapshot_tables":
            return self.tools.list_snapshot_tables(page=page)
        if tool_name == "describe_snapshot_table":
            return self.tools.describe_snapshot_table(
                page=page,
                table_name=str(arguments.get("table_name") or arguments.get("table") or ""),
                sample_limit=int(arguments.get("sample_limit") or 8),
            )
        if tool_name == "query_snapshot_table":
            return self.tools.query_snapshot_table(
                page=page,
                sql=str(arguments.get("sql") or ""),
                max_rows=int(arguments.get("max_rows") or self.tools.max_query_rows),
            )
        raise ChartQueryAgentError(
            code="TOOL_NOT_ALLOWED",
            message="Tool is outside the published snapshot surface.",
            status_code=400,
        )

    def _consume_sdk_message(
        self,
        *,
        message: Any,
        run_context: ChartQueryRunContext,
    ) -> list[tuple[str, dict[str, Any]]]:
        events: list[tuple[str, dict[str, Any]]] = []
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    if block.text:
                        run_context.text_blocks.append(block.text)
                elif isinstance(block, ThinkingBlock):
                    events.extend(self._emit_planning_event(run_context, block.thinking))
                elif isinstance(block, ToolUseBlock):
                    self._record_tool_use(
                        run_context=run_context,
                        tool_name=_canonical_snapshot_tool_name(block.name),
                        arguments=block.input,
                        tool_use_id=block.id,
                    )
            return [event for event in events if event[0]]

        if isinstance(message, UserMessage) and isinstance(message.content, list):
            for block in message.content:
                if not isinstance(block, ToolResultBlock):
                    continue
                record = run_context.records_by_tool_use_id.get(block.tool_use_id)
                if record is None:
                    continue
                if record.result_data is None:
                    record.result_data = _extract_sdk_tool_response_payload(block.content)
                    record.status = "error" if block.is_error else record.status
                self._record_tool_result(run_context=run_context, record=record)
            return events

        if isinstance(message, ResultMessage):
            text = ""
            if isinstance(message.structured_output, dict):
                text = str(message.structured_output.get("text") or "")
            if not text and message.result:
                text = str(message.result)
            if text:
                events.append(
                    (
                        "final",
                        {
                            "conversation_id": run_context.conversation_id,
                            "request_id": run_context.request_id,
                            "status": "failed" if message.is_error else "completed",
                            "text": text,
                        },
                    )
                )
            if message.is_error and not text:
                events.append(
                    (
                        "error",
                        {
                            "conversation_id": run_context.conversation_id,
                            "request_id": run_context.request_id,
                            "status": "failed",
                            "code": "PUBLIC_ASSISTANT_AGENT_FAILED",
                            "message": "Public assistant failed. Please retry.",
                        },
                    )
                )
            return events

        return events

    def _emit_planning_event(
        self,
        run_context: ChartQueryRunContext,
        text: str,
    ) -> list[tuple[str, dict[str, Any]]]:
        if run_context.planning_emitted:
            return []
        payload = {
            "conversation_id": run_context.conversation_id,
            "request_id": run_context.request_id,
            "status": "running",
            "text": text.strip() or "Planning against the published snapshot.",
        }
        run_context.planning_emitted = True
        return [("planning", payload)]

    def _record_tool_use(
        self,
        *,
        run_context: ChartQueryRunContext,
        tool_name: str,
        arguments: dict[str, Any],
        tool_use_id: str | None,
    ) -> SnapshotToolInvocationRecord:
        record = self._get_or_create_tool_record(
            run_context=run_context,
            tool_name=tool_name,
            arguments=arguments,
            tool_use_id=tool_use_id,
        )
        if record.tool_use_emitted:
            return record
        payload = {
            "conversation_id": run_context.conversation_id,
            "request_id": run_context.request_id,
            "tool_name": record.tool_name,
            "step": record.step,
            "arguments": record.arguments,
            "step_id": record.step_id,
            "started_at": record.started_at,
        }
        record.tool_use_emitted = True
        run_context.events.append(("tool_use", payload))
        return record

    def _record_tool_result(
        self,
        *,
        run_context: ChartQueryRunContext,
        record: SnapshotToolInvocationRecord,
    ) -> None:
        if record.tool_result_emitted:
            return
        payload = {
            "conversation_id": run_context.conversation_id,
            "request_id": run_context.request_id,
            "tool_name": record.tool_name,
            "step": record.step,
            "status": record.status if record.status in {"success", "error"} else "success",
            "result": record.result_data or {},
            "error": record.error,
            "step_id": record.step_id,
            "started_at": record.started_at,
            "completed_at": time.time(),
        }
        record.tool_result_emitted = True
        run_context.events.append(("tool_result", payload))

    def _get_or_create_tool_record(
        self,
        *,
        run_context: ChartQueryRunContext,
        tool_name: str,
        arguments: dict[str, Any],
        tool_use_id: str | None,
    ) -> SnapshotToolInvocationRecord:
        if tool_use_id and tool_use_id in run_context.records_by_tool_use_id:
            record = run_context.records_by_tool_use_id[tool_use_id]
            if not record.arguments:
                record.arguments = arguments
            return record

        for record in reversed(run_context.records):
            if record.tool_name == tool_name and record.arguments == arguments and not record.tool_use_id:
                if tool_use_id:
                    record.tool_use_id = tool_use_id
                    run_context.records_by_tool_use_id[tool_use_id] = record
                return record

        run_context.tool_step_count += 1
        record = SnapshotToolInvocationRecord(
            tool_name=tool_name,
            arguments=arguments,
            step=run_context.tool_step_count,
            step_id=str(uuid.uuid4()),
            started_at=time.time(),
            tool_use_id=tool_use_id,
        )
        run_context.records.append(record)
        if tool_use_id:
            run_context.records_by_tool_use_id[tool_use_id] = record
        return record

    def _flush_pending_tool_results(self, *, run_context: ChartQueryRunContext) -> None:
        for record in run_context.records:
            if record.result_data is not None and not record.tool_result_emitted:
                self._record_tool_result(run_context=run_context, record=record)


_snapshot_duckdb_cache: SnapshotDuckDBCache | None = None
_snapshot_cache_lock = Lock()
_chart_query_agent: ChartQueryAgent | None = None
_chart_query_agent_lock = Lock()


def get_snapshot_duckdb_cache() -> SnapshotDuckDBCache:
    settings = get_settings()
    with _snapshot_cache_lock:
        global _snapshot_duckdb_cache
        if (
            _snapshot_duckdb_cache is None
            or _snapshot_duckdb_cache.max_entries != settings.public_assistant_cache_max_entries
            or _snapshot_duckdb_cache.ttl_seconds != settings.public_assistant_cache_ttl_seconds
        ):
            if _snapshot_duckdb_cache is not None:
                _snapshot_duckdb_cache.clear()
            _snapshot_duckdb_cache = SnapshotDuckDBCache(
                max_entries=settings.public_assistant_cache_max_entries,
                ttl_seconds=settings.public_assistant_cache_ttl_seconds,
            )
        return _snapshot_duckdb_cache


def clear_snapshot_duckdb_cache() -> None:
    with _snapshot_cache_lock:
        global _snapshot_duckdb_cache
        if _snapshot_duckdb_cache is not None:
            _snapshot_duckdb_cache.clear()
        _snapshot_duckdb_cache = None


def get_chart_query_agent() -> ChartQueryAgent:
    with _chart_query_agent_lock:
        global _chart_query_agent
        if _chart_query_agent is None:
            _chart_query_agent = ChartQueryAgent()
        return _chart_query_agent


def clear_chart_query_agent_cache() -> None:
    with _chart_query_agent_lock:
        global _chart_query_agent
        _chart_query_agent = None
    clear_snapshot_duckdb_cache()


def format_sse(event_type: str, payload: dict[str, Any]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def _find_table(entry: SnapshotDuckDBEntry, *, table_name: str) -> SnapshotTable:
    normalized = table_name.strip()
    for table in entry.tables.values():
        if table.table_name == normalized or table.chart_id == normalized:
            return table
    raise ChartQueryAgentError(
        code="SNAPSHOT_TABLE_NOT_FOUND",
        message="Snapshot table not found.",
        status_code=404,
    )


def _snapshot_cache_key(page: PublishedPage) -> str:
    return f"{page.id}:{page.version}"


def _safe_table_name(value: str, *, fallback: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip().lower()).strip("_")
    if not normalized:
        normalized = fallback
    if normalized[0].isdigit():
        normalized = f"chart_{normalized}"
    return normalized


def _dedupe_table_name(table_name: str, used: set[str]) -> str:
    candidate = table_name
    suffix = 2
    while candidate in used:
        candidate = f"{table_name}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def _canonical_snapshot_tool_name(tool_name: str) -> str:
    prefix = f"mcp__{SNAPSHOT_MCP_SERVER_NAME}__"
    if tool_name.startswith(prefix):
        return tool_name[len(prefix):]
    return tool_name


def _extract_hook_tool_response(input_data: dict[str, Any]) -> dict[str, Any]:
    for key in ("tool_response", "response", "result"):
        value = input_data.get(key)
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            parsed = _try_parse_json(value)
            if isinstance(parsed, dict):
                return parsed
    return {}


def _extract_sdk_tool_response_payload(content: Any) -> dict[str, Any]:
    if isinstance(content, str):
        parsed = _try_parse_json(content)
        return parsed if isinstance(parsed, dict) else {"text": content}
    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                text_parts.append(str(item.get("text") or ""))
        parsed = _try_parse_json("\n".join(text_parts).strip())
        return parsed if isinstance(parsed, dict) else {"text": "\n".join(text_parts).strip()}
    if isinstance(content, dict):
        return content
    return {}


def _try_parse_json(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _chart_context_by_id(manifest: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    context: dict[str, dict[str, list[str]]] = {}
    content = manifest.get("content") if isinstance(manifest.get("content"), dict) else {}
    nodes = content.get("nodes") if isinstance(content.get("nodes"), list) else []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        if data.get("type") != "chart":
            continue
        chart_id = str(data.get("assetId") or "").strip()
        node_id = str(node.get("id") or "").strip()
        if chart_id and node_id:
            context.setdefault(chart_id, {"node_ids": [], "pages": []})["node_ids"].append(node_id)

    web_design = content.get("web_design") if isinstance(content.get("web_design"), dict) else {}
    layout = web_design.get("layout") if isinstance(web_design.get("layout"), dict) else {}
    pages = layout.get("pages") if isinstance(layout.get("pages"), list) else []
    for page in pages:
        if not isinstance(page, dict):
            continue
        page_label = str(page.get("title") or page.get("id") or "").strip()
        zones = page.get("zones") if isinstance(page.get("zones"), list) else []
        for zone in zones:
            if not isinstance(zone, dict):
                continue
            chart_id = str(zone.get("chartId") or zone.get("chart_id") or "").strip()
            if chart_id and page_label:
                context.setdefault(chart_id, {"node_ids": [], "pages": []})["pages"].append(page_label)
    return context
