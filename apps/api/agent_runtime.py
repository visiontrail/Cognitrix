from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any, AsyncGenerator

import anyio
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

from .agent_guardrails import AgentGuardrailContext, AgentGuardrailError, AgentGuardrails
from .agent_logging import format_agent_debug_blocks
from .agent_prompting import build_agent_system_prompt
from .audit import get_audit_logger
from .chart_strategy import ChartStrategyRouter
from .config import get_settings
from .tool_calling import ToolCall, ToolCallRequest, ToolCallResponse, get_tool_calling_service

logger = logging.getLogger("cognitrix.agent")

# ---------------------------------------------------------------------------
# Tool definitions exposed as Claude Agent SDK in-process MCP tools.
# ---------------------------------------------------------------------------

AGENT_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_tables",
            "description": "List all dataset tables available in the current project.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "describe_table",
            "description": (
                "Inspect a table's column names, types, and sample rows. "
                "Always call this before writing SQL."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table": {"type": "string", "description": "Table name to inspect"},
                    "sample_limit": {
                        "type": "integer",
                        "description": "Number of sample rows to return (1-50, default 8)",
                    },
                },
                "required": ["table"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sample_rows",
            "description": (
                "Fetch sample rows from a table to inspect actual data values. "
                "Use this to see real values in categorical columns before filtering."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table": {"type": "string"},
                    "limit": {"type": "integer", "description": "Number of rows (1-50, default 8)"},
                },
                "required": ["table"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_distinct_values",
            "description": (
                "Return the distinct values and their frequency for a categorical column. "
                "Call this before applying any filter on a column when you are unsure of the "
                "exact stored values (e.g. the user says 'HR' but the data might store '人力资源')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "field": {"type": "string", "description": "Column name"},
                    "table": {"type": "string", "description": "Table name (optional, defaults to active dataset)"},
                    "limit": {"type": "integer", "description": "Max distinct values to return (default 20)"},
                },
                "required": ["field"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_metric_catalog",
            "description": "Return the list of pre-defined semantic metrics available in the catalog.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_semantic_query",
            "description": (
                "Execute a semantic/metric query using the catalog. "
                "Prefer this over raw SQL when a matching metric exists."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "metric": {"type": "string", "description": "Metric name from catalog"},
                    "intent": {"type": "string", "description": "Natural language intent if metric name unknown"},
                    "group_by": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Columns to group by",
                    },
                    "filters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "field": {"type": "string"},
                                "op": {"type": "string"},
                                "value": {},
                            },
                        },
                        "description": "Filter conditions",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_readonly_sql",
            "description": (
                "Execute a readonly DuckDB SQL query against the dataset. "
                "Use only when the semantic catalog cannot satisfy the request. "
                "Row-level security and column redaction are automatically applied."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "SELECT statement to execute"},
                    "max_rows": {
                        "type": "integer",
                        "description": "Maximum rows to return (default 200)",
                    },
                },
                "required": ["sql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_view",
            "description": "Save the current chart/SQL as a named view (only when user explicitly requests it).",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "chart_spec": {"type": "object"},
                    "sql": {"type": "string"},
                    "conversation_id": {"type": "string"},
                },
                "required": ["title"],
            },
        },
    },
]

GROUNDING_TOOL_NAMES = frozenset(
    {
        "list_tables",
        "describe_table",
        "sample_rows",
        "get_metric_catalog",
        "run_semantic_query",
        "execute_readonly_sql",
        "get_distinct_values",
        "query_metrics",
        "describe_dataset",
    }
)

TOOL_RESULT_RECOVERY_PRIORITY = (
    "execute_readonly_sql",
    "run_semantic_query",
    "get_distinct_values",
    "sample_rows",
    "describe_table",
    "list_tables",
)

SDK_MCP_SERVER_NAME = "cognitrix"
SDK_RUNTIME_BACKEND = "claude-agent-sdk"
SDK_TOOL_DEFINITIONS = AGENT_TOOL_DEFINITIONS
SDK_TOOL_NAMES = tuple(
    str(item.get("function", {}).get("name") or "")
    for item in SDK_TOOL_DEFINITIONS
    if item.get("function", {}).get("name")
)
SDK_ALLOWED_TOOL_NAMES = tuple(
    f"mcp__{SDK_MCP_SERVER_NAME}__{name}" for name in SDK_TOOL_NAMES
)
FINAL_ANSWER_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "chart_type": {
            "type": "string",
            "enum": [
                "bar",
                "line",
                "pie",
                "area",
                "stacked_bar",
                "scatter",
                "radar",
                "treemap",
                "funnel",
                "radialBar",
                "composed",
                "heatmap",
                "gauge",
                "sankey",
                "sunburst",
                "boxplot",
                "candlestick",
                "graph",
                "map",
                "parallel",
                "wordCloud",
                "table",
                "single_value",
            ],
            "description": "Chart type for visualization",
        },
        "title": {"type": "string", "description": "Human-readable title"},
        "x_key": {"type": ["string", "null"], "description": "Dimension / grouping column name"},
        "y_key": {"type": ["string", "null"], "description": "Metric / size column name"},
        "name_key": {
            "type": ["string", "null"],
            "description": (
                "Label column name shown inside each element "
                "(e.g. employee name in treemap boxes). Only used for treemap/graph."
            ),
        },
        "series_key": {
            "type": ["string", "null"],
            "description": "Series column name for multi-series charts, or null",
        },
        "metric_name": {"type": ["string", "null"], "description": "Short internal metric name"},
        "rows": {
            "type": "array",
            "items": {"type": "object"},
            "description": "Array of data objects for the chart",
        },
        "conclusion": {"type": "string", "description": "1-2 sentence insight from the data"},
        "scope": {"type": ["string", "null"], "description": "What the query covers, filters applied"},
        "anomalies": {
            "type": ["string", "null"],
            "description": "Empty result reason, access restriction, or 'none'",
        },
    },
    "required": ["chart_type", "title", "rows", "conclusion"],
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


class AgentRuntimeError(Exception):
    def __init__(self, *, code: str, message: str, should_fallback: bool = True) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.should_fallback = should_fallback

    def to_detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "should_fallback": self.should_fallback,
        }


@dataclass(slots=True)
class AgentRequest:
    conversation_id: str
    request_id: str
    user_id: str
    project_id: str
    dataset_table: str
    message: str
    role: str
    department: str | None
    clearance: int
    workspace_id: str | None = None
    preferred_chart_type: str | None = None
    response_locale: str | None = None


@dataclass(slots=True)
class AgentSessionState:
    conversation_id: str
    agent_session_id: str
    history: list[dict[str, Any]] = field(default_factory=list)
    last_result: dict[str, Any] | None = None
    last_spec: dict[str, Any] | None = None
    last_tool_trace: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: _utc_now())
    updated_at: str = field(default_factory=lambda: _utc_now())
    turn_count: int = 0
    runtime_backend: str = SDK_RUNTIME_BACKEND

    def to_record(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "agent_session_id": self.agent_session_id,
            "history": self.history,
            "last_result": self.last_result,
            "last_spec": self.last_spec,
            "last_tool_trace": self.last_tool_trace,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "turn_count": self.turn_count,
            "runtime_backend": self.runtime_backend,
        }

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "AgentSessionState":
        return cls(
            conversation_id=str(record.get("conversation_id") or ""),
            agent_session_id=str(record.get("agent_session_id") or uuid.uuid4().hex),
            history=list(record.get("history") or []),
            last_result=record.get("last_result") if isinstance(record.get("last_result"), dict) else None,
            last_spec=record.get("last_spec") if isinstance(record.get("last_spec"), dict) else None,
            last_tool_trace=list(record.get("last_tool_trace") or []),
            created_at=str(record.get("created_at") or _utc_now()),
            updated_at=str(record.get("updated_at") or _utc_now()),
            turn_count=int(record.get("turn_count") or 0),
            runtime_backend=str(record.get("runtime_backend") or SDK_RUNTIME_BACKEND),
        )


@dataclass(slots=True)
class AgentTurnResult:
    conversation_id: str
    request_id: str
    agent_session_id: str
    events: list[tuple[str, dict[str, Any]]]
    tool_trace: list[dict[str, Any]]
    final_text: str
    final_status: str
    spec: dict[str, Any]
    ai_state: dict[str, Any]


@dataclass(slots=True)
class SDKToolInvocationRecord:
    tool_name: str
    arguments: dict[str, Any]
    step: int
    tool_use_id: str | None = None
    tool_use_emitted: bool = False
    tool_result_emitted: bool = False
    status: str = "pending"
    result_data: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    from_cache: bool = False
    step_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    started_at: float = field(default_factory=time.time)


@dataclass(slots=True)
class SDKRunContext:
    request: AgentRequest
    session: AgentSessionState
    events: list[tuple[str, dict[str, Any]]]
    tool_trace: list[dict[str, Any]]
    next_tool_step: int = 1
    planning_emitted: bool = False
    text_blocks: list[str] = field(default_factory=list)
    result_message: ResultMessage | None = None
    records_by_key: dict[str, SDKToolInvocationRecord] = field(default_factory=dict)
    records_by_tool_use_id: dict[str, SDKToolInvocationRecord] = field(default_factory=dict)
    event_queue: asyncio.Queue | None = None


# ---------------------------------------------------------------------------
# Session persistence
# ---------------------------------------------------------------------------


class AgentSessionStore:
    def __init__(self, *, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._init_schema()

    def load(self, conversation_id: str) -> AgentSessionState | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT state_json FROM agent_sessions WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row["state_json"]))
        if not isinstance(payload, dict):
            return None
        return AgentSessionState.from_record(payload)

    def save(self, state: AgentSessionState) -> None:
        state.updated_at = _utc_now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_sessions (
                    conversation_id,
                    agent_session_id,
                    state_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    agent_session_id = excluded.agent_session_id,
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
                """,
                (
                    state.conversation_id,
                    state.agent_session_id,
                    json.dumps(
                        state.to_record(),
                        ensure_ascii=False,
                        default=str,
                        separators=(",", ":"),
                    ),
                    state.created_at,
                    state.updated_at,
                ),
            )
            conn.commit()

    def clear(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM agent_sessions")
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_sessions (
                    conversation_id TEXT PRIMARY KEY,
                    agent_session_id TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()


# ---------------------------------------------------------------------------
# Agent runtime — Claude Agent SDK client and MCP tools
# ---------------------------------------------------------------------------


class AgentRuntime:
    def __init__(self) -> None:
        settings = get_settings()
        self.settings = settings
        self.guardrails = AgentGuardrails()
        self.tool_service = get_tool_calling_service()
        self.router = ChartStrategyRouter()
        self.system_prompt = build_agent_system_prompt()
        self._store = AgentSessionStore(
            db_path=(settings.upload_dir / "state" / "agent_sessions.sqlite3").resolve()
        )
        self._hot_sessions: dict[str, AgentSessionState] = {}
        self._lock = Lock()
        self._sdk_client_factory = ClaudeSDKClient

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run_turn(self, request: AgentRequest) -> AgentTurnResult:
        return anyio.run(self._run_turn_with_sdk, request)

    async def run_turn_stream(self, request: AgentRequest) -> AsyncGenerator[tuple[str, dict[str, Any]], None]:  # type: ignore[override]
        """Async generator that yields (event_type, payload) tuples in real-time."""
        queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()

        async def _run_and_signal() -> AgentTurnResult:
            result = await self._run_turn_with_sdk(request, event_queue=queue)
            queue.put_nowait(None)  # sentinel — signals end of stream
            return result

        task = asyncio.ensure_future(_run_and_signal())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            if not task.done():
                task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    async def _run_turn_with_sdk(
        self,
        request: AgentRequest,
        event_queue: asyncio.Queue | None = None,
    ) -> AgentTurnResult:
        started = time.perf_counter()
        session = self._load_session(request.conversation_id)
        guard_context = AgentGuardrailContext(
            role=request.role,
            user_id=request.user_id,
            project_id=request.project_id,
        )
        self.guardrails.validate_user_message(message=request.message, context=guard_context)
        resolved_dataset_table = self._resolve_request_dataset_table(request=request)
        if resolved_dataset_table and resolved_dataset_table != request.dataset_table:
            logger.warning(
                "agent_dataset_table_fallback conversation_id=%s request_id=%s requested=%s resolved=%s",
                request.conversation_id,
                request.request_id,
                request.dataset_table,
                resolved_dataset_table,
            )
            request.dataset_table = resolved_dataset_table

        tool_trace: list[dict[str, Any]] = []
        events: list[tuple[str, dict[str, Any]]] = []
        response_locale = _normalize_response_locale(request.response_locale, request.message)
        system_text = self._build_system_text(request=request, session=session)
        run_context = SDKRunContext(
            request=request,
            session=session,
            events=events,
            tool_trace=tool_trace,
            event_queue=event_queue,
        )
        self._emit_planning_event(
            run_context,
            f"Analyzing request for dataset `{request.dataset_table}`.",
        )

        logger.info(
            "agent_turn_start_debug conversation_id=%s request_id=%s agent_session_id=%s\n%s",
            request.conversation_id,
            request.request_id,
            session.agent_session_id,
            format_agent_debug_blocks(
                ai_input={
                    "conversation_id": request.conversation_id,
                    "request_id": request.request_id,
                    "agent_session_id": session.agent_session_id,
                    "dataset_table": request.dataset_table,
                    "message": request.message,
                    "response_locale": response_locale,
                    "runtime_backend": SDK_RUNTIME_BACKEND,
                    "sdk_tools": list(SDK_ALLOWED_TOOL_NAMES),
                },
            ),
        )

        final_answer: dict[str, Any] | None = None
        options = self._build_sdk_options(
            request=request,
            session=session,
            system_text=system_text,
            run_context=run_context,
        )

        async def execute_sdk_turn(sdk_options: ClaudeAgentOptions) -> None:
            nonlocal final_answer
            async with self._sdk_client_factory(options=sdk_options) as client:
                await client.query(request.message)
                async for message in client.receive_response():
                    candidate = self._consume_sdk_message(message=message, run_context=run_context)
                    if candidate is not None:
                        final_answer = candidate

        try:
            await execute_sdk_turn(options)
        except Exception as exc:
            self._flush_pending_sdk_tool_results(run_context)
            if _is_missing_claude_session_error(exc) and session.turn_count > 0 and not tool_trace:
                logger.warning(
                    "agent_sdk_resume_missing conversation_id=%s request_id=%s agent_session_id=%s; retrying with fresh SDK session",
                    request.conversation_id,
                    request.request_id,
                    session.agent_session_id,
                )
                session.agent_session_id = str(uuid.uuid4())
                retry_options = self._build_sdk_options(
                    request=request,
                    session=session,
                    system_text=system_text,
                    run_context=run_context,
                    force_fresh_session=True,
                )
                try:
                    await execute_sdk_turn(retry_options)
                except Exception as retry_exc:
                    self._flush_pending_sdk_tool_results(run_context)
                    if _has_tool_observation(tool_trace):
                        recovered = _recover_final_answer_from_tool_trace(
                            tool_trace=tool_trace,
                            request_message=request.message,
                            locale=response_locale,
                        )
                        final_answer = recovered if recovered is not None else _recover_failed_final_answer_from_tool_trace(
                            tool_trace=tool_trace,
                            request_message=request.message,
                            sdk_error=str(retry_exc),
                            locale=response_locale,
                        )
                    else:
                        raise AgentRuntimeError(
                            code="AGENT_SDK_FAILED",
                            message=f"Claude Agent SDK failed: {retry_exc}",
                            should_fallback=False,
                        ) from retry_exc
            elif _has_tool_observation(tool_trace):
                recovered = _recover_final_answer_from_tool_trace(
                    tool_trace=tool_trace,
                    request_message=request.message,
                    locale=response_locale,
                )
                final_answer = recovered if recovered is not None else _recover_failed_final_answer_from_tool_trace(
                    tool_trace=tool_trace,
                    request_message=request.message,
                    sdk_error=str(exc),
                    locale=response_locale,
                )
            else:
                raise AgentRuntimeError(
                    code="AGENT_SDK_FAILED",
                    message=f"Claude Agent SDK failed: {exc}",
                    should_fallback=False,
                ) from exc

        self._flush_pending_sdk_tool_results(run_context)

        if final_answer is None and run_context.text_blocks:
            final_answer = _parse_final_answer("\n".join(run_context.text_blocks))
        if final_answer is None and run_context.result_message and run_context.result_message.is_error:
            details = run_context.result_message.errors or [run_context.result_message.result or "unknown SDK error"]
            if _has_tool_observation(tool_trace):
                final_answer = _recover_failed_final_answer_from_tool_trace(
                    tool_trace=tool_trace,
                    request_message=request.message,
                    sdk_error="; ".join(str(item) for item in details),
                    locale=response_locale,
                )
            else:
                raise AgentRuntimeError(
                    code="AGENT_SDK_FAILED",
                    message="Claude Agent SDK returned an error: " + "; ".join(str(item) for item in details),
                    should_fallback=False,
                )

        if run_context.result_message and run_context.result_message.session_id:
            session.agent_session_id = run_context.result_message.session_id
        session.runtime_backend = SDK_RUNTIME_BACKEND

        # ------ Build chart spec from final answer ------
        has_current_observation = _has_tool_observation(tool_trace)
        has_current_grounding = _has_grounding_tool_observation(tool_trace)
        has_prior_grounding = _has_grounding_tool_observation(session.last_tool_trace)
        if final_answer is not None and (has_current_observation or has_prior_grounding):
            if has_current_observation and not has_current_grounding and not has_prior_grounding:
                final_answer = _empty_rows_final_answer(final_answer, locale=response_locale)
            final_answer = _repair_answer_locale_if_needed(
                answer=final_answer,
                locale=response_locale,
                tool_trace=tool_trace,
                request_message=request.message,
            )
            spec = self._spec_from_final_answer(final_answer, request=request)
            final_text = _compose_final_text(final_answer, locale=response_locale)
            result_payload = final_answer
        else:
            spec = self._empty_spec(request=request)
            if has_current_grounding:
                recovered_answer = _recover_final_answer_from_tool_trace(
                    tool_trace=tool_trace,
                    request_message=request.message,
                    locale=response_locale,
                )
                if recovered_answer is not None:
                    spec = self._spec_from_final_answer(recovered_answer, request=request)
                    final_text = _compose_final_text(recovered_answer, locale=response_locale)
                    result_payload = recovered_answer
                else:
                    final_text = _localized_text(
                        response_locale,
                        en="Agent collected tool observations but did not return a usable structured answer.",
                        zh="Agent 已收集工具观测结果，但未返回可用的结构化答案。",
                    )
                    result_payload = {"rows": [], "conclusion": "", "anomalies": "final_answer_parse_failed"}
            elif has_current_observation:
                recovered_answer = _recover_failed_final_answer_from_tool_trace(
                    tool_trace=tool_trace,
                    request_message=request.message,
                    locale=response_locale,
                )
                spec = self._spec_from_final_answer(recovered_answer, request=request)
                final_text = _compose_final_text(recovered_answer, locale=response_locale)
                result_payload = recovered_answer
            else:
                final_text = _localized_text(
                    response_locale,
                    en="Agent stopped to avoid ungrounded output because no BI tool observation was produced.",
                    zh="Agent 已停止，以避免在没有 BI 工具观测结果的情况下输出未验证内容。",
                )
                result_payload = {"rows": [], "conclusion": "", "anomalies": "no_tool_observation"}

        return self._finalize_turn(
            request=request,
            session=session,
            events=events,
            run_context=run_context,
            tool_trace=tool_trace,
            spec=spec,
            final_text=final_text,
            result_payload=result_payload,
            started=started,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def clear_runtime_state(self, *, clear_persisted: bool = False) -> None:
        with self._lock:
            self._hot_sessions.clear()
        if clear_persisted:
            self._store.clear()

    def get_persisted_session(self, conversation_id: str) -> AgentSessionState | None:
        return self._store.load(conversation_id)

    def _build_sdk_options(
        self,
        *,
        request: AgentRequest,
        session: AgentSessionState,
        system_text: str,
        run_context: SDKRunContext,
        force_fresh_session: bool = False,
    ) -> ClaudeAgentOptions:
        async def can_use_tool(
            tool_name: str,
            input_data: dict[str, Any],
            permission_context: Any,
        ) -> PermissionResultAllow | PermissionResultDeny:
            return await self._sdk_can_use_tool(
                tool_name=tool_name,
                input_data=input_data,
                permission_context=permission_context,
                run_context=run_context,
            )

        async def pre_tool_use(
            input_data: dict[str, Any],
            tool_use_id: str | None,
            hook_context: dict[str, Any],
        ) -> dict[str, Any]:
            return await self._sdk_pre_tool_use_hook(
                input_data=input_data,
                tool_use_id=tool_use_id,
                hook_context=hook_context,
                run_context=run_context,
            )

        async def post_tool_use(
            input_data: dict[str, Any],
            tool_use_id: str | None,
            hook_context: dict[str, Any],
        ) -> dict[str, Any]:
            return await self._sdk_post_tool_use_hook(
                input_data=input_data,
                tool_use_id=tool_use_id,
                hook_context=hook_context,
                run_context=run_context,
            )

        async def post_tool_failure(
            input_data: dict[str, Any],
            tool_use_id: str | None,
            hook_context: dict[str, Any],
        ) -> dict[str, Any]:
            return await self._sdk_post_tool_failure_hook(
                input_data=input_data,
                tool_use_id=tool_use_id,
                hook_context=hook_context,
                run_context=run_context,
            )

        server = create_sdk_mcp_server(
            name=SDK_MCP_SERVER_NAME,
            version="1.0.0",
            tools=self._build_sdk_tools(run_context=run_context),
        )
        env: dict[str, str] = {
            "API_TIMEOUT_MS": str(self.settings.api_timeout_ms),
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        }
        auth_token_source = self.settings.anthropic_auth_token or self.settings.ai_api_key
        auth_token = auth_token_source.strip()
        if auth_token:
            env["ANTHROPIC_API_KEY"] = auth_token
            env["ANTHROPIC_AUTH_TOKEN"] = auth_token
        if self.settings.anthropic_base_url.strip():
            env["ANTHROPIC_BASE_URL"] = self.settings.anthropic_base_url.strip()
        model = self.settings.ai_model.strip() or None
        if model:
            env["ANTHROPIC_MODEL"] = model
            env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = (
                self.settings.anthropic_default_haiku_model.strip() or model
            )
        resume_session = (
            session.agent_session_id
            if session.turn_count > 0 and session.agent_session_id and not force_fresh_session
            else None
        )

        return ClaudeAgentOptions(
            tools=[],
            system_prompt=system_text,
            mcp_servers={SDK_MCP_SERVER_NAME: server},
            can_use_tool=can_use_tool,
            hooks={
                "PreToolUse": [HookMatcher(matcher=None, hooks=[pre_tool_use])],
                "PostToolUse": [HookMatcher(matcher=None, hooks=[post_tool_use])],
                "PostToolUseFailure": [HookMatcher(matcher=None, hooks=[post_tool_failure])],
            },
            permission_mode="default",
            session_id=None,
            resume=resume_session,
            max_turns=self.settings.agent_max_tool_steps,
            model=model,
            cwd=str(Path.cwd()),
            env=env,
            output_format=None,
        )

    def _build_sdk_tools(self, *, run_context: SDKRunContext) -> list[Any]:
        sdk_tools: list[Any] = []
        for definition in SDK_TOOL_DEFINITIONS:
            function_def = definition.get("function", {})
            tool_name = str(function_def.get("name") or "")
            if not tool_name:
                continue
            description = str(function_def.get("description") or tool_name)
            input_schema = function_def.get("parameters") or {"type": "object", "properties": {}}
            is_read_only = tool_name != "save_view"
            annotations = ToolAnnotations(
                readOnlyHint=is_read_only,
                destructiveHint=not is_read_only,
                idempotentHint=is_read_only,
                openWorldHint=False,
            )

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

    async def _sdk_can_use_tool(
        self,
        *,
        tool_name: str,
        input_data: dict[str, Any],
        permission_context: Any,
        run_context: SDKRunContext,
    ) -> PermissionResultAllow | PermissionResultDeny:
        _ = permission_context
        try:
            self._validate_sdk_tool_call(
                run_context=run_context,
                tool_name=tool_name,
                arguments=input_data,
            )
        except AgentGuardrailError as exc:
            return PermissionResultDeny(message=exc.message)
        return PermissionResultAllow()

    async def _sdk_pre_tool_use_hook(
        self,
        *,
        input_data: dict[str, Any],
        tool_use_id: str | None,
        hook_context: dict[str, Any],
        run_context: SDKRunContext,
    ) -> dict[str, Any]:
        _ = hook_context
        tool_name = str(input_data.get("tool_name") or "")
        arguments = input_data.get("tool_input")
        if not isinstance(arguments, dict):
            arguments = {}
        resolved_tool_use_id = tool_use_id or str(input_data.get("tool_use_id") or "") or None

        try:
            self._validate_sdk_tool_call(
                run_context=run_context,
                tool_name=tool_name,
                arguments=arguments,
            )
        except AgentGuardrailError as exc:
            get_audit_logger().log(
                event_type="agent",
                action="agent_pre_tool_use",
                status="failed",
                severity="ALERT",
                user_id=run_context.request.user_id,
                project_id=run_context.request.project_id,
                detail={
                    "tool_name": tool_name,
                    "conversation_id": run_context.request.conversation_id,
                    "code": exc.code,
                },
            )
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": exc.message,
                }
            }

        self._record_sdk_tool_use(
            run_context=run_context,
            tool_name=tool_name,
            arguments=arguments,
            tool_use_id=resolved_tool_use_id,
        )
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "permissionDecisionReason": "Cognitrix BI tool call allowed.",
            }
        }

    async def _sdk_post_tool_use_hook(
        self,
        *,
        input_data: dict[str, Any],
        tool_use_id: str | None,
        hook_context: dict[str, Any],
        run_context: SDKRunContext,
    ) -> dict[str, Any]:
        _ = hook_context
        tool_name = str(input_data.get("tool_name") or "")
        arguments = input_data.get("tool_input")
        if not isinstance(arguments, dict):
            arguments = {}
        resolved_tool_use_id = tool_use_id or str(input_data.get("tool_use_id") or "") or None
        record = self._get_or_create_sdk_tool_record(
            run_context=run_context,
            tool_name=tool_name,
            arguments=arguments,
            tool_use_id=resolved_tool_use_id,
        )
        if record.result_data is None:
            record.result_data = _extract_sdk_tool_response_payload(input_data.get("tool_response"))
            record.status = "success"
        self._record_sdk_tool_result(run_context=run_context, record=record)
        return {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": "Cognitrix recorded the BI tool result for audit and SSE trace.",
            }
        }

    async def _sdk_post_tool_failure_hook(
        self,
        *,
        input_data: dict[str, Any],
        tool_use_id: str | None,
        hook_context: dict[str, Any],
        run_context: SDKRunContext,
    ) -> dict[str, Any]:
        _ = hook_context
        tool_name = str(input_data.get("tool_name") or "")
        arguments = input_data.get("tool_input")
        if not isinstance(arguments, dict):
            arguments = {}
        resolved_tool_use_id = tool_use_id or str(input_data.get("tool_use_id") or "") or None
        record = self._get_or_create_sdk_tool_record(
            run_context=run_context,
            tool_name=tool_name,
            arguments=arguments,
            tool_use_id=resolved_tool_use_id,
        )
        error_message = str(input_data.get("error") or "Tool execution failed")
        record.status = "error"
        record.error = {
            "code": "SDK_TOOL_FAILED",
            "message": error_message,
            "retryable": False,
        }
        record.result_data = {"error": record.error}
        self._record_sdk_tool_result(run_context=run_context, record=record)
        return {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUseFailure",
                "additionalContext": error_message,
            }
        }

    async def _invoke_sdk_tool(
        self,
        *,
        run_context: SDKRunContext,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(arguments, dict):
            arguments = {}
        canonical_name = _canonical_sdk_tool_name(tool_name)
        record = self._record_sdk_tool_use(
            run_context=run_context,
            tool_name=canonical_name,
            arguments=arguments,
            tool_use_id=None,
        )
        try:
            self._validate_sdk_tool_call(
                run_context=run_context,
                tool_name=canonical_name,
                arguments=arguments,
            )
        except AgentGuardrailError as exc:
            record.status = "error"
            record.error = {
                "code": exc.code,
                "message": exc.message,
                "retryable": False,
            }
            record.result_data = {"error": record.error}
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(record.result_data, ensure_ascii=False, default=str),
                    }
                ],
                # Treat expected BI guardrail denials as model-visible observations so
                # the assistant can summarize the outcome for the user.
                "is_error": False,
            }

        def invoke() -> ToolCallResponse:
            return self.tool_service.invoke(
                ToolCallRequest(
                    conversation_id=run_context.request.conversation_id,
                    request_id=run_context.request.request_id,
                    idempotency_key=(
                        f"{run_context.request.request_id}:{canonical_name}:{record.step}"
                    ),
                    user_id=run_context.request.user_id,
                    project_id=run_context.request.project_id,
                    workspace_id=run_context.request.workspace_id,
                    dataset_table=run_context.request.dataset_table,
                    role=run_context.request.role,
                    department=run_context.request.department,
                    clearance=run_context.request.clearance,
                    emit_debug_blocks=False,
                    tool=ToolCall(name=canonical_name, arguments=arguments),
                )
            )

        response = await anyio.to_thread.run_sync(invoke)
        result_data = response.result if response.status == "success" else {"error": response.error}
        record.status = response.status
        record.result_data = result_data or {}
        record.error = response.error
        record.from_cache = response.from_cache
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(record.result_data, ensure_ascii=False, default=str),
                }
            ],
            # Business/data execution failures are returned as JSON observations.
            # Marking them as MCP-level errors can terminate the SDK loop before
            # the model has a chance to produce the required final summary.
            "is_error": False,
        }

    def _validate_sdk_tool_call(
        self,
        *,
        run_context: SDKRunContext,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> None:
        canonical_name = _canonical_sdk_tool_name(tool_name)
        if canonical_name not in SDK_TOOL_NAMES:
            raise AgentGuardrailError(
                code="TOOL_NOT_ALLOWED",
                message=f"Tool '{tool_name}' is outside the allowed Cognitrix BI tool surface.",
            )
        guard_context = AgentGuardrailContext(
            role=run_context.request.role,
            user_id=run_context.request.user_id,
            project_id=run_context.request.project_id,
        )
        self.guardrails.validate_tool_call(
            tool_name=canonical_name,
            arguments=arguments,
            context=guard_context,
        )

    def _consume_sdk_message(
        self,
        *,
        message: Any,
        run_context: SDKRunContext,
    ) -> dict[str, Any] | None:
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    if block.text:
                        run_context.text_blocks.append(block.text)
                elif isinstance(block, ThinkingBlock):
                    if block.thinking and not run_context.planning_emitted:
                        self._emit_planning_event(run_context, block.thinking)
                elif isinstance(block, ToolUseBlock):
                    self._record_sdk_tool_use(
                        run_context=run_context,
                        tool_name=block.name,
                        arguments=block.input,
                        tool_use_id=block.id,
                    )
            return None

        if isinstance(message, UserMessage) and isinstance(message.content, list):
            for block in message.content:
                if not isinstance(block, ToolResultBlock):
                    continue
                record = run_context.records_by_tool_use_id.get(block.tool_use_id)
                if record is None:
                    continue
                if record.result_data is None:
                    record.result_data = _extract_sdk_tool_response_payload(block.content)
                    record.status = "error" if block.is_error else "success"
                self._record_sdk_tool_result(run_context=run_context, record=record)
            return None

        if isinstance(message, ResultMessage):
            run_context.result_message = message
            if isinstance(message.structured_output, dict):
                return message.structured_output
            if message.result:
                return _parse_final_answer(message.result)
        return None

    @staticmethod
    def _append_event(run_context: SDKRunContext, event_type: str, payload: dict[str, Any]) -> None:
        """Append event to the events list and optionally forward to the live-stream queue."""
        item: tuple[str, dict[str, Any]] = (event_type, payload)
        run_context.events.append(item)
        if run_context.event_queue is not None:
            run_context.event_queue.put_nowait(item)

    def _emit_planning_event(self, run_context: SDKRunContext, text: str) -> None:
        if run_context.planning_emitted:
            return
        planning_text = text.strip() or f"Analyzing request for dataset `{run_context.request.dataset_table}`."
        payload = {
            "conversation_id": run_context.request.conversation_id,
            "request_id": run_context.request.request_id,
            "agent_session_id": run_context.session.agent_session_id,
            "text": planning_text,
        }
        compatibility = {
            **payload,
            "compatibility_mirror": True,
        }
        self._append_event(run_context, "planning", payload)
        self._append_event(run_context, "reasoning", compatibility)
        run_context.planning_emitted = True

    def _record_sdk_tool_use(
        self,
        *,
        run_context: SDKRunContext,
        tool_name: str,
        arguments: dict[str, Any],
        tool_use_id: str | None,
    ) -> SDKToolInvocationRecord:
        record = self._get_or_create_sdk_tool_record(
            run_context=run_context,
            tool_name=tool_name,
            arguments=arguments,
            tool_use_id=tool_use_id,
        )
        if record.tool_use_emitted:
            return record

        tool_use_payload = {
            "conversation_id": run_context.request.conversation_id,
            "request_id": run_context.request.request_id,
            "agent_session_id": run_context.session.agent_session_id,
            "tool_name": record.tool_name,
            "step": record.step,
            "arguments": record.arguments,
            "step_id": record.step_id,
            "started_at": record.started_at,
        }
        self._append_event(run_context, "tool_use", tool_use_payload)
        run_context.tool_trace.append({"event": "tool_use", **tool_use_payload})
        record.tool_use_emitted = True
        get_audit_logger().log(
            event_type="agent",
            action="agent_pre_tool_use",
            status="success",
            user_id=run_context.request.user_id,
            project_id=run_context.request.project_id,
            detail={
                "tool_name": record.tool_name,
                "step": record.step,
                "conversation_id": run_context.request.conversation_id,
            },
        )
        return record

    def _record_sdk_tool_result(
        self,
        *,
        run_context: SDKRunContext,
        record: SDKToolInvocationRecord,
    ) -> None:
        if record.tool_result_emitted:
            return
        result_data = record.result_data or {}
        tool_result_payload = {
            "conversation_id": run_context.request.conversation_id,
            "request_id": run_context.request.request_id,
            "agent_session_id": run_context.session.agent_session_id,
            "tool_name": record.tool_name,
            "step": record.step,
            "status": record.status if record.status in {"success", "error"} else "success",
            "result": result_data,
            "error": record.error,
            "from_cache": record.from_cache,
            "step_id": record.step_id,
            "started_at": record.started_at,
            "completed_at": time.time(),
        }
        self._append_event(run_context, "tool_result", tool_result_payload)
        self._append_event(
            run_context,
            "tool",
            {
                "conversation_id": run_context.request.conversation_id,
                "request_id": run_context.request.request_id,
                "tool_name": record.tool_name,
                "status": tool_result_payload["status"],
                "result": result_data,
                "error": record.error,
                "compatibility_mirror": True,
            },
        )
        run_context.tool_trace.append({"event": "tool_result", **tool_result_payload})
        record.tool_result_emitted = True
        get_audit_logger().log(
            event_type="agent",
            action="agent_post_tool_use",
            status="success" if tool_result_payload["status"] == "success" else "failed",
            severity="INFO" if tool_result_payload["status"] == "success" else "ALERT",
            user_id=run_context.request.user_id,
            project_id=run_context.request.project_id,
            detail={
                "tool_name": record.tool_name,
                "step": record.step,
                "conversation_id": run_context.request.conversation_id,
            },
        )

    def _get_or_create_sdk_tool_record(
        self,
        *,
        run_context: SDKRunContext,
        tool_name: str,
        arguments: dict[str, Any],
        tool_use_id: str | None,
    ) -> SDKToolInvocationRecord:
        canonical_name = _canonical_sdk_tool_name(tool_name)
        clean_arguments = dict(arguments or {})
        if tool_use_id and tool_use_id in run_context.records_by_tool_use_id:
            return run_context.records_by_tool_use_id[tool_use_id]

        key = _sdk_tool_record_key(canonical_name, clean_arguments)
        record = run_context.records_by_key.get(key)
        if record is not None and record.tool_result_emitted:
            is_same_sdk_call = bool(tool_use_id and record.tool_use_id == tool_use_id)
            if not is_same_sdk_call:
                record = None

        if record is None:
            record = SDKToolInvocationRecord(
                tool_name=canonical_name,
                arguments=clean_arguments,
                step=run_context.next_tool_step,
                tool_use_id=tool_use_id,
            )
            run_context.next_tool_step += 1
            run_context.records_by_key[key] = record

        if tool_use_id:
            record.tool_use_id = tool_use_id
            run_context.records_by_tool_use_id[tool_use_id] = record
        return record

    def _flush_pending_sdk_tool_results(self, run_context: SDKRunContext) -> None:
        for record in list(run_context.records_by_key.values()):
            if record.result_data is not None and not record.tool_result_emitted:
                self._record_sdk_tool_result(run_context=run_context, record=record)

    def _load_session(self, conversation_id: str) -> AgentSessionState:
        with self._lock:
            session = self._hot_sessions.get(conversation_id)
        if session is not None:
            return session

        stored = self._store.load(conversation_id)
        if stored is not None:
            with self._lock:
                self._hot_sessions[conversation_id] = stored
            return stored

        session = AgentSessionState(
            conversation_id=conversation_id,
            agent_session_id=str(uuid.uuid4()),
            runtime_backend=SDK_RUNTIME_BACKEND,
        )
        with self._lock:
            self._hot_sessions[conversation_id] = session
        self._store.save(session)
        return session

    def _resolve_request_dataset_table(self, *, request: AgentRequest) -> str:
        try:
            all_tables = self.tool_service.dataset_service.list_tables(
                user_id=request.user_id,
                project_id=request.project_id,
                workspace_id=request.workspace_id,
            )
        except Exception:
            return request.dataset_table

        if not all_tables:
            return request.dataset_table

        canonical = self._match_table_name(request.dataset_table, all_tables)
        if canonical is not None:
            return canonical

        if len(all_tables) == 1:
            return all_tables[0]
        return request.dataset_table

    @staticmethod
    def _match_table_name(table_name: str, candidates: list[str]) -> str | None:
        target = table_name.strip().lower()
        if not target:
            return None
        candidate_map = {item.lower(): item for item in candidates}
        return candidate_map.get(target)

    def _build_system_text(
        self,
        *,
        request: AgentRequest,
        session: AgentSessionState,
    ) -> str:
        """Compose the system prompt with per-request context.

        Claude Agent SDK takes a system prompt in options, so per-request
        context is appended here while the SDK owns the conversation transcript.
        """
        parts = [self.system_prompt]

        try:
            all_tables = self.tool_service.dataset_service.list_tables(
                user_id=request.user_id,
                project_id=request.project_id,
                workspace_id=request.workspace_id,
            )
        except Exception:
            all_tables = [request.dataset_table]

        if len(all_tables) > 1:
            other_tables = [t for t in all_tables if t != request.dataset_table]
            tables_hint = (
                f"Active dataset table: `{request.dataset_table}`. "
                f"Other tables in this session: {', '.join(f'`{t}`' for t in other_tables)}. "
                "You may JOIN across these tables in execute_readonly_sql when answering cross-table questions."
            )
        else:
            tables_hint = f"Active dataset table: `{request.dataset_table}`."

        context_hint = (
            tables_hint
            + f" User role: {request.role}."
            + " Row-level security is enforced automatically on all queries."
        )
        parts.append(context_hint)

        preferred_chart_type = self._normalize_chart_type(request.preferred_chart_type)
        if preferred_chart_type:
            parts.append(
                "User-selected chart_type preference: "
                f"`{preferred_chart_type}`. Honour this exact chart_type in the final JSON answer "
                "unless the query returns no rows."
            )

        if session.last_result and isinstance(session.last_result, dict):
            prior_summary = json.dumps(session.last_result, ensure_ascii=False, default=str)
            if len(prior_summary) > 2000:
                prior_summary = prior_summary[:2000] + "..."
            parts.append(
                f"Previous turn result is available for context: {prior_summary}"
            )

        locale = _normalize_response_locale(request.response_locale, request.message)
        language_name = "English" if locale == "en-US" else "Simplified Chinese"
        parts.append(
            "## Response language\n"
            f"The user interface selected locale is `{locale}`. "
            f"Write every user-visible natural-language field in {language_name}: "
            "`title`, `conclusion`, `scope`, and `anomalies`, plus any prose you emit. "
            "Do not follow the language of previous turns, examples, table names, column names, "
            "or stored data values when choosing answer language. Keep JSON keys, column names, "
            "metric names, chart_type, and raw data values unchanged."
        )

        return "\n\n".join(parts)

    # Chart types rendered via frontend fallback option builders (no backend config.option needed)
    RECHARTS_TYPES = frozenset({
        "bar", "line", "pie", "area", "scatter", "radar",
        "funnel", "radialBar", "composed",
        "single_value", "note", "empty",
    })

    # Chart types that must be routed to ECharts (backend builds config.option)
    ECHARTS_ONLY_TYPES = frozenset({
        "stacked_bar", "treemap", "heatmap", "gauge", "sankey", "sunburst",
        "boxplot", "candlestick", "graph", "map", "parallel", "wordCloud",
        "table",
    })

    # All valid chart types (union of both)
    ALL_CHART_TYPES = RECHARTS_TYPES | ECHARTS_ONLY_TYPES

    def _spec_from_final_answer(
        self,
        answer: dict[str, Any],
        *,
        request: AgentRequest,
    ) -> dict[str, Any]:
        rows = list(answer.get("rows") or [])
        chart_type = str(answer.get("chart_type") or "bar")
        preferred_chart_type = self._normalize_chart_type(request.preferred_chart_type)
        if preferred_chart_type:
            chart_type = preferred_chart_type
        if chart_type not in self.ALL_CHART_TYPES:
            chart_type = "bar"
        if not rows:
            chart_type = "empty"

        x_key = str(answer.get("x_key") or _guess_dimension_key(rows, fallback="dimension"))
        y_key = str(answer.get("y_key") or _guess_metric_key(rows, fallback="metric_value"))
        name_key = answer.get("name_key") or None
        series_key = answer.get("series_key") or None
        metric_name = str(answer.get("metric_name") or "metric")
        title = str(answer.get("title") or request.message[:60])

        # Decide engine: ECharts-only types always use echarts; multi-series line also
        if chart_type in self.ECHARTS_ONLY_TYPES:
            engine = "echarts"
        elif chart_type == "line" and series_key:
            engine = "echarts"
        else:
            engine = "recharts"

        if engine == "echarts":
            option = _build_echarts_option(
                chart_type=chart_type,
                rows=rows,
                x_key=x_key,
                y_key=y_key,
                name_key=str(name_key) if name_key else None,
                series_key=str(series_key) if series_key else None,
                title=title,
                metric_name=metric_name,
            )
            # Normalise echarts chart_type to a valid catalog value
            echarts_catalog = {
                "bar", "line", "pie", "area", "stacked_bar", "scatter", "treemap", "heatmap",
                "radar", "funnel", "gauge", "sankey", "sunburst",
                "boxplot", "candlestick", "graph", "map", "parallel", "wordCloud", "table",
            }
            echarts_ct = chart_type if chart_type in echarts_catalog else "bar"
            config: dict[str, Any] = {"option": option}
        else:
            echarts_ct = chart_type  # unused, but keeps typing simple
            config = {"xKey": x_key, "yKey": y_key, "metricName": metric_name}
            if name_key:
                config["nameKey"] = name_key
            if series_key:
                config["seriesKey"] = series_key

        final_chart_type = echarts_ct if engine == "echarts" else chart_type

        return {
            "engine": engine,
            "chart_type": final_chart_type,
            "title": title,
            "data": rows,
            "config": config,
            "route": {
                "complexity_score": len(rows) + (3 if series_key else 1),
                "threshold": self.router.COMPLEXITY_THRESHOLD,
                "reasons": ["claude_agent_sdk"],
                "selected_engine": engine,
            },
            "meta": {"intent": request.message, "generated_by": SDK_RUNTIME_BACKEND},
        }

    def _normalize_chart_type(self, value: str | None) -> str | None:
        if not value:
            return None
        chart_type = str(value).strip()
        if chart_type in self.ALL_CHART_TYPES:
            return chart_type
        lower_catalog = {item.lower(): item for item in self.ALL_CHART_TYPES}
        return lower_catalog.get(chart_type.lower())

    def _empty_spec(self, *, request: AgentRequest) -> dict[str, Any]:
        locale = _normalize_response_locale(request.response_locale, request.message)
        return {
            "engine": "recharts",
            "chart_type": "empty",
            "title": _localized_text(locale, en="No data", zh="无数据"),
            "data": [],
            "config": {},
            "route": {
                "complexity_score": 0,
                "threshold": self.router.COMPLEXITY_THRESHOLD,
                "reasons": ["agent_no_answer"],
                "selected_engine": "recharts",
            },
            "meta": {"intent": request.message, "generated_by": SDK_RUNTIME_BACKEND},
        }

    def _finalize_turn(
        self,
        *,
        request: AgentRequest,
        session: AgentSessionState,
        events: list[tuple[str, dict[str, Any]]],
        run_context: SDKRunContext,
        tool_trace: list[dict[str, Any]],
        spec: dict[str, Any],
        final_text: str,
        result_payload: dict[str, Any],
        started: float,
    ) -> AgentTurnResult:
        spec_payload: dict[str, Any] = {
            "conversation_id": request.conversation_id,
            "request_id": request.request_id,
            "agent_session_id": session.agent_session_id,
            "spec": spec,
        }
        self._append_event(run_context, "spec", spec_payload)
        duration_ms = int((time.perf_counter() - started) * 1000)
        final_payload = {
            "conversation_id": request.conversation_id,
            "request_id": request.request_id,
            "agent_session_id": session.agent_session_id,
            "status": "completed",
            "text": final_text,
            "duration_ms": duration_ms,
            "tool_steps": len([item for item in tool_trace if item.get("event") == "tool_use"]),
        }
        self._append_event(run_context, "final", final_payload)

        session.turn_count += 1
        session.history.append({"role": "user", "content": request.message})
        session.history.append({"role": "assistant", "content": final_text})
        session.last_result = result_payload
        session.last_spec = spec
        session.last_tool_trace = tool_trace
        self._store.save(session)
        with self._lock:
            self._hot_sessions[request.conversation_id] = session

        ai_state = {
            "conversation_id": request.conversation_id,
            "agent_session_id": session.agent_session_id,
            "tool_trace": tool_trace,
            "latest_result": result_payload,
            "latest_spec": spec,
            "turn_count": session.turn_count,
            "runtime_backend": session.runtime_backend,
        }
        tool_use_trace = [item for item in tool_trace if item.get("event") == "tool_use"]
        tool_result_trace = [item for item in tool_trace if item.get("event") == "tool_result"]
        logger.info(
            "agent_turn_final_debug conversation_id=%s request_id=%s agent_session_id=%s\n%s",
            request.conversation_id,
            request.request_id,
            session.agent_session_id,
            format_agent_debug_blocks(
                ai_output={
                    "conversation_id": request.conversation_id,
                    "request_id": request.request_id,
                    "agent_session_id": session.agent_session_id,
                    "status": "completed",
                    "final_text": final_text,
                    "result_payload": result_payload,
                    "spec": spec,
                },
                tool_trace=tool_use_trace,
                tool_result=tool_result_trace,
            ),
        )
        return AgentTurnResult(
            conversation_id=request.conversation_id,
            request_id=request.request_id,
            agent_session_id=session.agent_session_id,
            events=events,
            tool_trace=tool_trace,
            final_text=final_text,
            final_status="completed",
            spec=spec,
            ai_state=ai_state,
        )


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


@lru_cache(maxsize=2)
def _cached_agent_runtime(settings_key: str) -> AgentRuntime:
    _ = settings_key
    return AgentRuntime()


def get_agent_runtime() -> AgentRuntime:
    settings = get_settings()
    key = "|".join(
        [
            str(settings.upload_dir.resolve()),
            str(settings.agent_max_tool_steps),
            str(settings.agent_max_sql_rows),
            str(settings.agent_max_sql_scan_rows),
        ]
    )
    return _cached_agent_runtime(key)


def clear_agent_runtime_cache() -> None:
    _cached_agent_runtime.cache_clear()


# ---------------------------------------------------------------------------
# SDK message helpers
# ---------------------------------------------------------------------------


def _canonical_sdk_tool_name(tool_name: str) -> str:
    name = tool_name.strip()
    prefix = f"mcp__{SDK_MCP_SERVER_NAME}__"
    if name.startswith(prefix):
        return name[len(prefix):]
    return name


def _sdk_tool_record_key(tool_name: str, arguments: dict[str, Any]) -> str:
    return json.dumps(
        {
            "tool_name": _canonical_sdk_tool_name(tool_name),
            "arguments": arguments or {},
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )


def _extract_sdk_tool_response_payload(value: Any) -> dict[str, Any]:
    if value is None:
        return {}

    if isinstance(value, dict):
        if "content" in value:
            return _extract_sdk_tool_response_payload(value.get("content"))
        if "text" in value:
            return _parse_sdk_tool_response_text(str(value.get("text") or ""))
        return dict(value)

    if isinstance(value, list):
        for item in value:
            parsed = _extract_sdk_tool_response_payload(item)
            if parsed:
                return parsed
        return {}

    text_attr = getattr(value, "text", None)
    if isinstance(text_attr, str):
        return _parse_sdk_tool_response_text(text_attr)

    content_attr = getattr(value, "content", None)
    if content_attr is not None:
        return _extract_sdk_tool_response_payload(content_attr)

    if isinstance(value, str):
        return _parse_sdk_tool_response_text(value)

    return {"value": str(value)}


def _parse_sdk_tool_response_text(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        return {}
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return {"text": stripped}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


# ---------------------------------------------------------------------------
# LLM message helpers
# ---------------------------------------------------------------------------


def _is_missing_claude_session_error(error: Exception) -> bool:
    message = str(error)
    return "No conversation found with session ID" in message



def _parse_final_answer(content: str) -> dict[str, Any] | None:
    """Try to extract a structured JSON final answer from LLM content."""
    text = content.strip()
    if not text:
        return None

    # Direct JSON
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict) and ("rows" in parsed or "chart_type" in parsed):
            return parsed
    except json.JSONDecodeError:
        pass

    # ```json ... ``` code fence (preferred format from system prompt)
    import re
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        try:
            parsed = json.loads(fence_match.group(1))
            if isinstance(parsed, dict) and ("rows" in parsed or "chart_type" in parsed):
                return parsed
        except json.JSONDecodeError:
            pass

    # Bare JSON object anywhere in the text
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            if isinstance(parsed, dict) and ("rows" in parsed or "chart_type" in parsed):
                return parsed
        except json.JSONDecodeError:
            pass

    return None


def _has_grounding_tool_observation(tool_trace: list[dict[str, Any]]) -> bool:
    for item in tool_trace:
        if item.get("event") != "tool_result":
            continue
        if item.get("status") != "success":
            continue
        result = item.get("result")
        if isinstance(result, dict) and isinstance(result.get("error"), dict):
            continue
        if str(item.get("tool_name") or "") in GROUNDING_TOOL_NAMES:
            return True
    return False


def _has_tool_observation(tool_trace: list[dict[str, Any]]) -> bool:
    return any(item.get("event") == "tool_result" for item in tool_trace)


def _normalize_response_locale(locale: str | None, message: str | None = None) -> str:
    raw = str(locale or "").strip().lower().replace("_", "-")
    if raw.startswith("zh"):
        return "zh-CN"
    if raw.startswith("en"):
        return "en-US"
    if message and any("\u4e00" <= char <= "\u9fff" for char in message):
        return "zh-CN"
    return "en-US"


def _localized_text(locale: str, *, en: str, zh: str) -> str:
    return zh if _normalize_response_locale(locale) == "zh-CN" else en


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _repair_answer_locale_if_needed(
    *,
    answer: dict[str, Any],
    locale: str,
    tool_trace: list[dict[str, Any]],
    request_message: str,
) -> dict[str, Any]:
    normalized_locale = _normalize_response_locale(locale)
    text_fields = ("title", "conclusion", "scope", "anomalies")
    field_values = {
        key: str(answer.get(key) or "")
        for key in text_fields
        if answer.get(key) not in (None, "")
    }
    if not field_values:
        return answer

    if normalized_locale == "en-US":
        needs_repair = any(_contains_cjk(value) for value in field_values.values())
    else:
        needs_repair = not any(_contains_cjk(value) for value in field_values.values())
    if not needs_repair:
        return answer

    recovered = _recover_final_answer_from_tool_trace(
        tool_trace=tool_trace,
        request_message=request_message,
        locale=normalized_locale,
    )
    fallback = recovered or {
        "title": _localized_text(normalized_locale, en="Analysis result", zh="分析结果"),
        "conclusion": _localized_text(
            normalized_locale,
            en="The analysis completed based on the available BI tool results.",
            zh="已基于可用的 BI 工具结果完成分析。",
        ),
        "scope": _localized_text(
            normalized_locale,
            en=f"User question: {request_message}",
            zh=f"用户问题: {request_message}",
        ),
        "anomalies": None,
    }

    repaired = dict(answer)
    for key in text_fields:
        fallback_value = fallback.get(key)
        if fallback_value not in (None, ""):
            repaired[key] = fallback_value
    return repaired


def _empty_rows_final_answer(answer: dict[str, Any], *, locale: str = "en-US") -> dict[str, Any]:
    normalized = dict(answer)
    normalized["rows"] = []
    normalized.setdefault("chart_type", "table")
    normalized.setdefault(
        "title",
        _localized_text(locale, en="Analysis incomplete", zh="分析未完成"),
    )
    normalized.setdefault(
        "conclusion",
        _localized_text(
            locale,
            en="This analysis did not return displayable data.",
            zh="本次分析未能返回可展示数据。",
        ),
    )
    normalized.setdefault(
        "scope",
        _localized_text(locale, en="No result data was generated.", zh="未生成数据结果。"),
    )
    normalized.setdefault(
        "anomalies",
        _localized_text(
            locale,
            en="Tool execution did not complete successfully; the explanation was generated from the tool error.",
            zh="工具执行未成功，已按工具返回的错误信息生成说明。",
        ),
    )
    return normalized


def _recover_failed_final_answer_from_tool_trace(
    *,
    tool_trace: list[dict[str, Any]],
    request_message: str,
    sdk_error: str | None = None,
    locale: str = "en-US",
) -> dict[str, Any]:
    failed_results = [
        item
        for item in tool_trace
        if item.get("event") == "tool_result"
        and (
            item.get("status") == "error"
            or (
                isinstance(item.get("result"), dict)
                and isinstance(item.get("result", {}).get("error"), dict)
            )
        )
    ]
    last_failure = failed_results[-1] if failed_results else {}
    tool_name = str(last_failure.get("tool_name") or "BI tool")
    error = _extract_tool_error(last_failure.get("result"), last_failure.get("error"))
    code = str(error.get("code") or "TOOL_EXECUTION_FAILED")
    message = str(error.get("message") or sdk_error or "Tool execution failed")

    if code == "NO_DATASET_TABLES":
        conclusion = _localized_text(
            locale,
            en=(
                "No dataset tables are available in the current session, so this analysis "
                "cannot be completed. Upload a dataset first, or confirm that data exists "
                "for the current user and project."
            ),
            zh="当前会话没有可用数据表，因此无法完成这次分析。请先上传数据集，或确认当前用户和项目下已有数据。",
        )
    else:
        conclusion = _localized_text(
            locale,
            en=f"This analysis could not be completed while calling {tool_name}: {message}",
            zh=f"本次分析在调用 {tool_name} 时未能完成：{message}",
        )

    anomalies = f"{code}: {message}"
    if sdk_error:
        anomalies = f"{anomalies}; SDK: {sdk_error}"

    return {
        "chart_type": "table",
        "title": _localized_text(locale, en="Analysis incomplete", zh="分析未完成"),
        "x_key": None,
        "y_key": None,
        "series_key": None,
        "metric_name": None,
        "rows": [],
        "conclusion": conclusion,
        "scope": _localized_text(locale, en=f"User question: {request_message}", zh=f"用户问题: {request_message}"),
        "anomalies": anomalies,
    }


def _extract_tool_error(result: Any, direct_error: Any) -> dict[str, Any]:
    if isinstance(direct_error, dict):
        return direct_error
    if isinstance(result, dict) and isinstance(result.get("error"), dict):
        return dict(result["error"])
    return {}


def _recover_final_answer_from_tool_trace(
    *,
    tool_trace: list[dict[str, Any]],
    request_message: str,
    locale: str = "en-US",
) -> dict[str, Any] | None:
    successful_results = [
        item
        for item in tool_trace
        if item.get("event") == "tool_result"
        and item.get("status") == "success"
        and str(item.get("tool_name") or "") in GROUNDING_TOOL_NAMES
    ]
    if not successful_results:
        return None

    non_empty = _recover_final_answer_from_results(
        successful_results=successful_results,
        request_message=request_message,
        require_non_empty_rows=True,
        locale=locale,
    )
    if non_empty is not None:
        return non_empty

    return _recover_final_answer_from_results(
        successful_results=successful_results,
        request_message=request_message,
        require_non_empty_rows=False,
        locale=locale,
    )


def _recover_final_answer_from_results(
    *,
    successful_results: list[dict[str, Any]],
    request_message: str,
    require_non_empty_rows: bool,
    locale: str = "en-US",
) -> dict[str, Any] | None:
    for tool_name in TOOL_RESULT_RECOVERY_PRIORITY:
        for item in reversed(successful_results):
            current_tool = str(item.get("tool_name") or "")
            if current_tool != tool_name:
                continue
            result = item.get("result")
            if not isinstance(result, dict):
                continue
            rows = _extract_rows_from_tool_result(tool_name=current_tool, result=result)
            if rows is None:
                continue
            if require_non_empty_rows and not rows:
                continue

            dimension_key, metric_key = _guess_dimension_and_metric_keys(rows)
            chart_type = "table"
            if rows and dimension_key and metric_key:
                chart_type = "bar"
            elif len(rows) == 1 and metric_key and not dimension_key:
                chart_type = "single_value"

            metric_name = str(result.get("metric") or metric_key or current_tool or "metric")
            return {
                "chart_type": chart_type,
                "title": _title_from_tool_result(
                    tool_name=current_tool,
                    result=result,
                    request_message=request_message,
                    locale=locale,
                ),
                "x_key": dimension_key or "dimension",
                "y_key": metric_key or "metric_value",
                "series_key": None,
                "metric_name": metric_name,
                "rows": rows,
                "conclusion": _conclusion_from_tool_rows(
                    rows=rows,
                    dimension_key=dimension_key,
                    metric_key=metric_key,
                    locale=locale,
                ),
                "scope": _scope_from_tool_result(tool_name=current_tool, result=result, locale=locale),
                "anomalies": _localized_text(
                    locale,
                    en="Auto-composed from successful tool results.",
                    zh="已基于成功工具结果自动生成。",
                ),
            }
    return None


def _extract_rows_from_tool_result(*, tool_name: str, result: dict[str, Any]) -> list[dict[str, Any]] | None:
    if tool_name in {"execute_readonly_sql", "run_semantic_query", "sample_rows"}:
        return _coerce_rows(result.get("rows"))
    if tool_name == "get_distinct_values":
        return _coerce_rows(result.get("values"))
    if tool_name == "describe_table":
        return _coerce_rows(result.get("sample_rows"))
    if tool_name == "list_tables":
        tables = result.get("tables")
        if isinstance(tables, list):
            return [{"table": str(item)} for item in tables]
        return []
    return None


def _coerce_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            rows.append(dict(item))
    return rows


def _guess_dimension_and_metric_keys(rows: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    if not rows:
        return None, None

    first_row = rows[0]
    if not isinstance(first_row, dict) or not first_row:
        return None, None

    keys = [str(key) for key in first_row.keys()]
    metric_candidates = ("metric_value", "frequency", "count", "employee_count")
    metric_key = next((key for key in metric_candidates if key in first_row and _is_number(first_row.get(key))), None)
    if metric_key is None:
        metric_key = next((key for key in keys if _is_number(first_row.get(key))), None)

    dimension_key = next((key for key in keys if key != metric_key and not _is_number(first_row.get(key))), None)
    return dimension_key, metric_key


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _title_from_tool_result(
    *,
    tool_name: str,
    result: dict[str, Any],
    request_message: str,
    locale: str = "en-US",
) -> str:
    if tool_name == "execute_readonly_sql":
        return _localized_text(locale, en="SQL query result", zh="SQL 查询结果")
    if tool_name == "run_semantic_query":
        metric = str(result.get("metric") or "").strip()
        if metric:
            return _localized_text(locale, en=f"{metric} query result", zh=f"{metric} 查询结果")
        return _localized_text(locale, en="Semantic query result", zh="语义查询结果")
    if tool_name == "get_distinct_values":
        field = str(result.get("field") or "").strip()
        if _normalize_response_locale(locale) == "zh-CN":
            return f"{field or '字段'} 值分布"
        return f"{field or 'Field'} value distribution"
    if tool_name == "sample_rows":
        table = str(result.get("table") or "").strip()
        if table:
            return _localized_text(locale, en=f"{table} sample rows", zh=f"{table} 样本记录")
        return _localized_text(locale, en="Sample rows", zh="样本记录")
    if tool_name == "describe_table":
        table = str(result.get("table") or "").strip()
        if table:
            return _localized_text(locale, en=f"{table} schema and sample", zh=f"{table} 表结构与样本")
        return _localized_text(locale, en="Schema and sample", zh="表结构与样本")
    if tool_name == "list_tables":
        return _localized_text(locale, en="Available tables", zh="可用数据表")
    trimmed = request_message.strip()
    return trimmed[:60] if trimmed else _localized_text(locale, en="Query result", zh="查询结果")


def _scope_from_tool_result(*, tool_name: str, result: dict[str, Any], locale: str = "en-US") -> str:
    row_count = result.get("row_count")
    if isinstance(row_count, int):
        return _localized_text(
            locale,
            en=f"Source tool: {tool_name}; returned {row_count} rows.",
            zh=f"来源工具: {tool_name}，返回 {row_count} 行。",
        )
    return _localized_text(locale, en=f"Source tool: {tool_name}.", zh=f"来源工具: {tool_name}。")


def _conclusion_from_tool_rows(
    *,
    rows: list[dict[str, Any]],
    dimension_key: str | None,
    metric_key: str | None,
    locale: str = "en-US",
) -> str:
    if not rows:
        return _localized_text(
            locale,
            en="The answer was generated from successful tool results, but the current result is empty.",
            zh="已基于成功工具结果自动生成答案，但当前结果为空。",
        )

    if dimension_key and metric_key:
        ranked = [row for row in rows if _is_number(row.get(metric_key))]
        if ranked:
            top_row = max(ranked, key=lambda row: float(row.get(metric_key) or 0))
            return _localized_text(
                locale,
                en=(
                    "The answer was generated from successful tool results. "
                    f"{dimension_key}={top_row.get(dimension_key)} has the highest {metric_key}: "
                    f"{top_row.get(metric_key)}."
                ),
                zh=(
                    "已基于成功工具结果自动生成答案。"
                    f" {dimension_key}={top_row.get(dimension_key)} 的 {metric_key} 最高，为 {top_row.get(metric_key)}。"
                ),
            )
        return _localized_text(
            locale,
            en=f"The answer was generated from successful tool results with {len(rows)} rows returned.",
            zh=f"已基于成功工具结果自动生成答案，共返回 {len(rows)} 行。",
        )

    if metric_key:
        numeric_values = [float(row.get(metric_key) or 0) for row in rows if _is_number(row.get(metric_key))]
        if numeric_values:
            return _localized_text(
                locale,
                en=(
                    "The answer was generated from successful tool results. "
                    f"{len(rows)} rows returned; {metric_key} totals {round(sum(numeric_values), 2)}."
                ),
                zh=(
                    "已基于成功工具结果自动生成答案。"
                    f" 共返回 {len(rows)} 行，{metric_key} 合计 {round(sum(numeric_values), 2)}。"
                ),
            )

    return _localized_text(
        locale,
        en=f"The answer was generated from successful tool results with {len(rows)} rows returned.",
        zh=f"已基于成功工具结果自动生成答案，共返回 {len(rows)} 行。",
    )




# ---------------------------------------------------------------------------
# Chart helpers
# ---------------------------------------------------------------------------


def _compose_final_text(answer: dict[str, Any], *, locale: str = "en-US") -> str:
    title = str(answer.get("title") or "Result")
    rows = list(answer.get("rows") or [])
    conclusion = str(answer.get("conclusion") or "")
    scope = str(answer.get("scope") or "")
    anomalies = str(answer.get("anomalies") or "")

    if not rows:
        parts = [
            _localized_text(
                locale,
                en=f"{title} returned no displayable data.",
                zh=f"{title} 没有返回可展示数据。",
            )
        ]
        if conclusion:
            parts.append(_localized_text(locale, en=f"Conclusion: {conclusion}", zh=f"结论: {conclusion}"))
        if scope:
            parts.append(_localized_text(locale, en=f"Scope: {scope}", zh=f"口径: {scope}"))
        if anomalies:
            parts.append(_localized_text(locale, en=f"Notes: {anomalies}", zh=f"异常说明: {anomalies}"))
        else:
            parts.append(
                _localized_text(
                    locale,
                    en="Possible reason: filters, permission scope, or source data distribution produced an empty result.",
                    zh="可能原因: 过滤条件、权限范围或源数据分布导致结果为空。",
                )
            )
        return " ".join(parts)

    parts = [
        _localized_text(
            locale,
            en=f"{title} has been generated with {len(rows)} rows.",
            zh=f"{title} 已生成，共 {len(rows)} 行。",
        )
    ]
    if conclusion:
        parts.append(_localized_text(locale, en=f"Conclusion: {conclusion}", zh=f"结论: {conclusion}"))
    if scope:
        parts.append(_localized_text(locale, en=f"Scope: {scope}", zh=f"口径: {scope}"))
    if anomalies:
        parts.append(_localized_text(locale, en=f"Notes: {anomalies}", zh=f"异常说明: {anomalies}"))
    return " ".join(parts)


def _build_echarts_option(
    *,
    chart_type: str,
    rows: list[dict[str, Any]],
    x_key: str,
    y_key: str,
    name_key: str | None,
    series_key: str | None,
    title: str,
    metric_name: str,
) -> dict[str, Any]:
    """Build a complete ECharts option dict from flat rows."""

    if chart_type == "table":
        return _echarts_table_option(rows=rows, title=title)
    if chart_type == "map":
        return _echarts_map_option(rows=rows, x_key=x_key, y_key=y_key, title=title, metric_name=metric_name)
    if chart_type == "treemap":
        return _echarts_treemap_option(rows=rows, x_key=x_key, y_key=y_key, name_key=name_key, title=title)
    if chart_type == "heatmap":
        return _echarts_heatmap_option(rows=rows, x_key=x_key, y_key=y_key, series_key=series_key)
    if chart_type == "radar":
        return _echarts_radar_option(rows=rows, x_key=x_key, y_key=y_key, metric_name=metric_name)
    if chart_type == "funnel":
        return _echarts_funnel_option(rows=rows, x_key=x_key, y_key=y_key)
    if chart_type == "gauge":
        return _echarts_gauge_option(rows=rows, y_key=y_key, title=title)
    if chart_type == "sankey":
        return _echarts_sankey_option(rows=rows)
    if chart_type == "sunburst":
        return _echarts_sunburst_option(rows=rows, x_key=x_key, y_key=y_key)
    if chart_type == "boxplot":
        return _echarts_boxplot_option(rows=rows, x_key=x_key, y_key=y_key)
    if chart_type == "candlestick":
        return _echarts_candlestick_option(rows=rows, x_key=x_key)
    if chart_type == "parallel":
        return _echarts_parallel_option(rows=rows)
    if chart_type == "wordCloud":
        return _echarts_wordcloud_option(rows=rows, x_key=x_key, y_key=y_key)
    if chart_type == "graph":
        return _echarts_graph_option(rows=rows, x_key=x_key, y_key=y_key)
    if chart_type == "pie":
        return _echarts_pie_option(rows=rows, x_key=x_key, y_key=y_key)
    if chart_type == "scatter":
        return _echarts_scatter_option(rows=rows, x_key=x_key, y_key=y_key)

    # Default: category axis bar/line/stacked_bar/area
    if chart_type == "stacked_bar":
        return _echarts_cartesian_option(
            rows=rows, x_key=x_key, y_key=y_key,
            series_key=series_key, series_type="bar",
            metric_name=metric_name, stacked=True,
        )
    return _echarts_cartesian_option(
        rows=rows, x_key=x_key, y_key=y_key,
        series_key=series_key, series_type=chart_type if chart_type in {"line", "bar", "area"} else "bar",
        metric_name=metric_name,
    )


def _echarts_cartesian_option(
    *,
    rows: list[dict[str, Any]],
    x_key: str,
    y_key: str,
    series_key: str | None,
    series_type: str,
    metric_name: str,
    stacked: bool = False,
) -> dict[str, Any]:
    is_line = series_type in {"line", "area"}
    render_type = "line" if is_line else series_type
    area_style: dict[str, Any] = {"opacity": 0.4} if series_type == "area" else {}

    if series_key:
        categories_set: list[str] = []
        series_groups: dict[str, dict[str, Any]] = {}
        for row in rows:
            cat = str(row.get(x_key, ""))
            if cat not in categories_set:
                categories_set.append(cat)
            sg = str(row.get(series_key, ""))
            series_groups.setdefault(sg, {})[cat] = row.get(y_key, 0)

        series_list = []
        for sg_name, cat_map in series_groups.items():
            s: dict[str, Any] = {
                "name": sg_name,
                "type": render_type,
                "smooth": is_line,
                "data": [cat_map.get(c, 0) for c in categories_set],
            }
            if stacked:
                s["stack"] = "total"
            if area_style:
                s["areaStyle"] = area_style
            series_list.append(s)
        return {
            "tooltip": {"trigger": "axis"},
            "legend": {},
            "grid": {"left": "3%", "right": "4%", "bottom": "3%", "containLabel": True},
            "xAxis": {"type": "category", "data": categories_set, "axisLabel": {"interval": 0, "rotate": 30}},
            "yAxis": {"type": "value"},
            "series": series_list,
        }

    categories = [str(r.get(x_key, f"item-{i+1}")) for i, r in enumerate(rows)]
    values = [r.get(y_key, 0) for r in rows]
    s_single: dict[str, Any] = {
        "name": metric_name,
        "type": render_type,
        "smooth": is_line,
        "data": values,
    }
    if stacked:
        s_single["stack"] = "total"
    if area_style:
        s_single["areaStyle"] = area_style
    return {
        "tooltip": {"trigger": "axis"},
        "grid": {"left": "3%", "right": "4%", "bottom": "3%", "containLabel": True},
        "xAxis": {"type": "category", "data": categories, "axisLabel": {"interval": 0, "rotate": 30}},
        "yAxis": {"type": "value"},
        "series": [s_single],
    }


def _echarts_treemap_option(
    *,
    rows: list[dict[str, Any]],
    x_key: str,
    y_key: str,
    name_key: str | None,
    title: str,
) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        group = str(row.get(x_key, "other"))
        label = str(row.get(name_key, "")) if name_key else group
        size = row.get(y_key, 1)
        size = size if isinstance(size, (int, float)) else 1
        groups.setdefault(group, []).append({"name": label, "value": size})

    tree_data: list[dict[str, Any]]
    if len(groups) <= 1 and not name_key:
        tree_data = [{"name": str(r.get(x_key, f"item-{i+1}")), "value": r.get(y_key, 1)} for i, r in enumerate(rows)]
    else:
        tree_data = [{"name": g, "children": children} for g, children in groups.items()]

    return {
        "tooltip": {"trigger": "item"},
        "series": [{
            "type": "treemap",
            "data": tree_data,
            "label": {"show": True, "formatter": "{b}"},
            "upperLabel": {"show": True, "height": 30},
            "breadcrumb": {"show": True},
            "levels": [
                {"itemStyle": {"borderColor": "#555", "borderWidth": 4, "gapWidth": 4}},
                {"colorSaturation": [0.3, 0.6], "itemStyle": {"borderColorSaturation": 0.7, "gapWidth": 2, "borderWidth": 2}},
            ],
        }],
    }


def _echarts_heatmap_option(
    *,
    rows: list[dict[str, Any]],
    x_key: str,
    y_key: str,
    series_key: str | None,
) -> dict[str, Any]:
    value_key = series_key or "value"
    x_cats = sorted(set(str(r.get(x_key, "")) for r in rows))
    y_cats = sorted(set(str(r.get(y_key, "")) for r in rows))
    x_map = {v: i for i, v in enumerate(x_cats)}
    y_map = {v: i for i, v in enumerate(y_cats)}
    data = []
    for r in rows:
        xi = x_map.get(str(r.get(x_key, "")), 0)
        yi = y_map.get(str(r.get(y_key, "")), 0)
        val = r.get(value_key, 0)
        data.append([xi, yi, val])
    return {
        "tooltip": {"position": "top"},
        "grid": {"left": "3%", "right": "4%", "bottom": "8%", "containLabel": True},
        "xAxis": {"type": "category", "data": x_cats},
        "yAxis": {"type": "category", "data": y_cats},
        "visualMap": {"min": 0, "max": max((d[2] for d in data), default=1), "calculable": True, "orient": "horizontal", "left": "center", "bottom": "0%"},
        "series": [{"type": "heatmap", "data": data, "label": {"show": True}}],
    }


def _echarts_radar_option(
    *,
    rows: list[dict[str, Any]],
    x_key: str,
    y_key: str,
    metric_name: str,
) -> dict[str, Any]:
    indicators = [{"name": str(r.get(x_key, f"dim-{i+1}")), "max": 100} for i, r in enumerate(rows)]
    values = [r.get(y_key, 0) for r in rows]
    max_val = max(values, default=100) if values else 100
    for ind in indicators:
        ind["max"] = max_val * 1.2 if max_val > 0 else 100
    return {
        "tooltip": {},
        "radar": {"indicator": indicators},
        "series": [{"type": "radar", "data": [{"name": metric_name, "value": values}]}],
    }


def _echarts_funnel_option(
    *,
    rows: list[dict[str, Any]],
    x_key: str,
    y_key: str,
) -> dict[str, Any]:
    data = [{"name": str(r.get(x_key, f"stage-{i+1}")), "value": r.get(y_key, 0)} for i, r in enumerate(rows)]
    return {
        "tooltip": {"trigger": "item"},
        "legend": {},
        "series": [{"type": "funnel", "left": "10%", "width": "80%", "data": data, "label": {"show": True, "position": "inside"}}],
    }


def _echarts_gauge_option(
    *,
    rows: list[dict[str, Any]],
    y_key: str,
    title: str,
) -> dict[str, Any]:
    value = rows[0].get(y_key, 0) if rows else 0
    return {
        "tooltip": {},
        "series": [{"type": "gauge", "data": [{"value": value, "name": title}], "detail": {"formatter": "{value}"}}],
    }


def _echarts_sankey_option(*, rows: list[dict[str, Any]]) -> dict[str, Any]:
    nodes_set: set[str] = set()
    links: list[dict[str, Any]] = []
    for r in rows:
        src = str(r.get("source", ""))
        tgt = str(r.get("target", ""))
        val = r.get("value", 1)
        if src and tgt:
            nodes_set.add(src)
            nodes_set.add(tgt)
            links.append({"source": src, "target": tgt, "value": val})
    return {
        "tooltip": {"trigger": "item"},
        "series": [{"type": "sankey", "data": [{"name": n} for n in sorted(nodes_set)], "links": links, "emphasis": {"focus": "adjacency"}}],
    }


def _echarts_sunburst_option(
    *,
    rows: list[dict[str, Any]],
    x_key: str,
    y_key: str,
) -> dict[str, Any]:
    if rows and "children" in rows[0]:
        data = rows
    else:
        groups: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            g = str(r.get(x_key, "other"))
            groups.setdefault(g, []).append({"name": str(r.get("name", g)), "value": r.get(y_key, 1)})
        data = [{"name": g, "children": c} for g, c in groups.items()]
    return {
        "tooltip": {},
        "series": [{"type": "sunburst", "data": data, "radius": ["15%", "90%"], "label": {"rotate": "radial"}}],
    }


def _echarts_boxplot_option(
    *,
    rows: list[dict[str, Any]],
    x_key: str,
    y_key: str,
) -> dict[str, Any]:
    categories = [str(r.get(x_key, f"cat-{i+1}")) for i, r in enumerate(rows)]
    data = []
    for r in rows:
        val = r.get(y_key)
        if isinstance(val, list):
            data.append(val)
        else:
            v = val if isinstance(val, (int, float)) else 0
            data.append([v, v, v, v, v])
    return {
        "tooltip": {"trigger": "item"},
        "xAxis": {"type": "category", "data": categories, "axisLabel": {"interval": 0, "rotate": 30}},
        "yAxis": {"type": "value"},
        "series": [{"type": "boxplot", "data": data}],
    }


def _echarts_graph_option(
    *,
    rows: list[dict[str, Any]],
    x_key: str,
    y_key: str,
) -> dict[str, Any]:
    nodes_set: set[str] = set()
    links: list[dict[str, Any]] = []
    for r in rows:
        src = str(r.get("source", r.get(x_key, "")))
        tgt = str(r.get("target", r.get(y_key, "")))
        if src and tgt:
            nodes_set.add(src)
            nodes_set.add(tgt)
            links.append({"source": src, "target": tgt})
    return {
        "tooltip": {},
        "series": [{
            "type": "graph",
            "layout": "force",
            "data": [{"name": n, "symbolSize": 30} for n in sorted(nodes_set)],
            "links": links,
            "roam": True,
            "label": {"show": True},
            "force": {"repulsion": 200},
        }],
    }


def _echarts_pie_option(
    *,
    rows: list[dict[str, Any]],
    x_key: str,
    y_key: str,
) -> dict[str, Any]:
    data = [{"name": str(r.get(x_key, f"item-{i+1}")), "value": r.get(y_key, 0)} for i, r in enumerate(rows)]
    return {
        "tooltip": {"trigger": "item", "formatter": "{b}: {c} ({d}%)"},
        "legend": {"orient": "vertical", "left": "left"},
        "series": [{
            "type": "pie",
            "radius": "50%",
            "data": data,
            "label": {
                "show": True,
                "formatter": "{b}\n{d}%",
            },
            "labelLine": {"show": True},
            "emphasis": {
                "itemStyle": {
                    "shadowBlur": 10,
                    "shadowOffsetX": 0,
                    "shadowColor": "rgba(0, 0, 0, 0.5)",
                },
            },
        }],
    }


def _echarts_scatter_option(
    *,
    rows: list[dict[str, Any]],
    x_key: str,
    y_key: str,
) -> dict[str, Any]:
    data = [[r.get(x_key, 0), r.get(y_key, 0)] for r in rows]
    return {
        "tooltip": {"trigger": "item"},
        "xAxis": {"type": "value", "name": x_key},
        "yAxis": {"type": "value", "name": y_key},
        "series": [{"type": "scatter", "data": data, "symbolSize": 10}],
    }


def _echarts_map_option(
    *,
    rows: list[dict[str, Any]],
    x_key: str,
    y_key: str,
    title: str,
    metric_name: str,
) -> dict[str, Any]:
    """Build an ECharts map option for China province-level choropleth."""
    data = [
        {"name": str(r.get(x_key, "")), "value": r.get(y_key, 0)}
        for r in rows
    ]
    values = [r.get(y_key, 0) for r in rows]
    numeric_values = [v for v in values if isinstance(v, (int, float))]
    min_val = min(numeric_values) if numeric_values else 0
    max_val = max(numeric_values) if numeric_values else 100

    return {
        "tooltip": {
            "trigger": "item",
            "formatter": "{b}<br/>" + metric_name + ": {c}",
        },
        "visualMap": {
            "min": min_val,
            "max": max_val,
            "left": "left",
            "top": "bottom",
            "text": ["高", "低"],
            "calculable": True,
            "inRange": {"color": ["#e0f3db", "#a8ddb5", "#43a2ca", "#0868ac"]},
        },
        "series": [
            {
                "name": title,
                "type": "map",
                "map": "china",
                "roam": True,
                "label": {"show": True, "fontSize": 10},
                "emphasis": {
                    "label": {"show": True, "fontSize": 14, "fontWeight": "bold"},
                    "itemStyle": {"areaColor": "#fdd49e"},
                },
                "data": data,
            }
        ],
    }


def _echarts_table_option(*, rows: list[dict[str, Any]], title: str) -> dict[str, Any]:
    """Produce a special marker that the frontend renders as an HTML data table."""
    columns = list(rows[0].keys()) if rows else []
    return {
        "__table__": True,
        "__columns__": columns,
        "__rows__": rows,
        "__title__": title,
        "series": [],
    }


def _echarts_candlestick_option(*, rows: list[dict[str, Any]], x_key: str) -> dict[str, Any]:
    categories = [str(r.get(x_key, f"item-{i+1}")) for i, r in enumerate(rows)]
    data = []
    for r in rows:
        y_val = r.get("y")
        if isinstance(y_val, list) and len(y_val) == 4:
            data.append(y_val)
        else:
            o = r.get("open", r.get("o", 0))
            c = r.get("close", r.get("c", 0))
            l = r.get("low", r.get("l", 0))  # noqa: E741
            h = r.get("high", r.get("h", 0))
            data.append([o, c, l, h])
    return {
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "cross"}},
        "grid": {"left": "5%", "right": "5%", "bottom": "8%", "containLabel": True},
        "xAxis": {"type": "category", "data": categories, "boundaryGap": True},
        "yAxis": {"type": "value", "scale": True},
        "series": [{"type": "candlestick", "data": data}],
    }


def _echarts_parallel_option(*, rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"series": []}
    all_keys = list(rows[0].keys())
    numeric_keys = [k for k in all_keys if isinstance(rows[0].get(k), (int, float))]
    axes = numeric_keys if numeric_keys else all_keys
    parallel_axis = [{"dim": i, "name": k} for i, k in enumerate(axes)]
    data = [[r.get(k, 0) for k in axes] for r in rows]
    return {
        "parallelAxis": parallel_axis,
        "tooltip": {"trigger": "item"},
        "parallel": {"left": "5%", "right": "13%", "bottom": "10%", "top": "10%"},
        "series": [{"type": "parallel", "smooth": True, "data": data}],
    }


def _echarts_wordcloud_option(*, rows: list[dict[str, Any]], x_key: str, y_key: str) -> dict[str, Any]:
    data = [
        {"name": str(r.get(x_key, f"word-{i+1}")), "value": max(1, int(r.get(y_key, 1)))}
        for i, r in enumerate(rows)
    ]
    return {
        "tooltip": {},
        "series": [{
            "type": "wordCloud",
            "gridSize": 8,
            "sizeRange": [14, 60],
            "rotationRange": [-45, 45],
            "shape": "circle",
            "width": "100%",
            "height": "100%",
            "textStyle": {"color": "random"},
            "data": data,
        }],
    }


def _guess_dimension_key(rows: list[dict[str, Any]], *, fallback: str) -> str:
    if not rows:
        return fallback
    for key, value in rows[0].items():
        if not isinstance(value, (int, float)):
            return str(key)
    return fallback


def _guess_metric_key(rows: list[dict[str, Any]], *, fallback: str) -> str:
    if not rows:
        return fallback
    sample = rows[0]
    if "metric_value" in sample:
        return "metric_value"
    for key, value in sample.items():
        if isinstance(value, (int, float)):
            return str(key)
    return fallback


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
