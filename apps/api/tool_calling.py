from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from threading import Lock
from typing import Any, Callable, Literal

import duckdb
from pydantic import BaseModel, Field

from urllib.parse import urlparse

from .agent_canvas import (
    AgentCanvasError,
    block_id_for,
    get_agent_canvas_run_store,
    validate_canvas_tool_arguments,
)
from .agent_logging import format_agent_debug_blocks
from .audit import get_audit_logger
from .chart_strategy import ChartStrategyRouter
from .column_metadata import enrich_column_with_metadata, load_table_column_metadata
from .config import get_settings
from .web_research import WebResearchError, fetch_page, search_web
from .data_policy import (
    filter_schema_columns,
    forbidden_sensitive_columns,
    redact_rows,
    redact_structure,
)
from .datasets import get_dataset_service
from .security import (
    AccessContext,
    QueryAccessError,
    RLSInjector,
    RLSError,
    SQLGuardError,
    SQLReadOnlyValidator,
    secure_query_sql,
)
from .semantic import (
    IntentParser,
    MetricCompileError,
    MetricCompiler,
    QueryFilter,
    SemanticQueryAST,
    SemanticRegistry,
    get_metric_compiler,
    get_semantic_registry,
)
from .sqlite_support import connect as sqlite_connect
from .table_catalog import get_table_catalog_service
from .views import SaveViewInput, ViewStorageError, get_view_storage_service
from .workspace_state import get_workspace_state_store
from .workspaces import get_workspace_service

SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SAFE_DUCKDB_TYPE_RE = re.compile(r"^[A-Za-z0-9_(),\s]+$")
logger = logging.getLogger("cognitrix.tool_calling")

# save_web_research namespace + write limits (see design D4).
WEB_RESEARCH_TABLE_PREFIX = "web_research_"
WEB_RESEARCH_MAX_ROWS = 1000
WEB_RESEARCH_MAX_COLUMNS = 30
WEB_RESEARCH_SOURCE_COLUMNS = ("_source_url", "_source_title", "_retrieved_at")
# Base DuckDB types accepted for web-research columns (parameters like
# DECIMAL(18,2) are allowed; only the leading type token is checked).
ALLOWED_DUCKDB_BASE_TYPES = frozenset(
    {
        "VARCHAR",
        "TEXT",
        "CHAR",
        "BOOLEAN",
        "TINYINT",
        "SMALLINT",
        "INTEGER",
        "INT",
        "BIGINT",
        "HUGEINT",
        "UTINYINT",
        "USMALLINT",
        "UINTEGER",
        "UBIGINT",
        "FLOAT",
        "REAL",
        "DOUBLE",
        "DECIMAL",
        "NUMERIC",
        "DATE",
        "TIME",
        "TIMESTAMP",
    }
)

TOOLS_REQUIRE_ACTIVE_DATASET = frozenset(
    {
        "query_metrics",
        "describe_dataset",
        "run_semantic_query",
    }
)

# Tools that benefit from a resolved dataset_table (e.g. for column-level
# access checks) but can still function when the caller-supplied table name
# doesn't match any table in the session.  Resolution is best-effort: the
# first available table is used as a fallback.
TOOLS_SOFT_DATASET = frozenset(
    {
        "execute_readonly_sql",
        "get_distinct_values",
    }
)
TOOLS_WITH_OPTIONAL_TABLE_ARGUMENT = frozenset(
    {
        "describe_table",
        "sample_rows",
        "get_distinct_values",
    }
)


class ToolCall(BaseModel):
    name: Literal[
        "query_metrics",
        "describe_dataset",
        "save_view",
        "list_tables",
        "describe_table",
        "sample_rows",
        "get_metric_catalog",
        "run_semantic_query",
        "execute_readonly_sql",
        "get_distinct_values",
        "web_search",
        "web_fetch",
        "save_web_research",
        "add_section",
        "add_text_block",
        "place_chart",
        "finish_dashboard",
    ]
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolCallRequest(BaseModel):
    conversation_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    idempotency_key: str = Field(default_factory=lambda: uuid.uuid4().hex)
    user_id: str
    project_id: str
    workspace_id: str | None = None
    dataset_table: str
    role: str = "viewer"
    department: str | None = None
    clearance: int = 0
    retry_limit: int = Field(default=2, ge=0, le=2)
    emit_debug_blocks: bool = True
    tool: ToolCall


class ToolCallResponse(BaseModel):
    conversation_id: str
    request_id: str
    idempotency_key: str
    tool_name: str
    status: Literal["success", "error"]
    attempts: int
    from_cache: bool = False
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class ToolExecutionError(Exception):
    def __init__(self, *, code: str, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable

    def to_detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }


@dataclass(slots=True)
class ToolContext:
    user_id: str
    project_id: str
    workspace_id: str | None
    dataset_table: str
    role: str
    department: str | None
    clearance: int


class ToolCallingService:
    def __init__(self) -> None:
        settings = get_settings()
        self.dataset_service = get_dataset_service(
            settings.upload_dir,
            ai_api_key=settings.ai_api_key,
            ai_model=settings.ai_model,
            ai_timeout=settings.ai_timeout_seconds,
        )
        self.registry = get_semantic_registry()
        self.compiler = get_metric_compiler()
        self.intent_parser = IntentParser(self.registry)
        self.view_storage = get_view_storage_service()

        self._idempotency_cache: dict[str, ToolCallResponse] = {}
        self._transient_failures: dict[str, int] = {}
        self._lock = Lock()

        self._tools: dict[str, Callable[[ToolContext, dict[str, Any]], dict[str, Any]]] = {
            "query_metrics": self._tool_query_metrics,
            "describe_dataset": self._tool_describe_dataset,
            "save_view": self._tool_save_view,
            "list_tables": self._tool_list_tables,
            "describe_table": self._tool_describe_table,
            "sample_rows": self._tool_sample_rows,
            "get_metric_catalog": self._tool_get_metric_catalog,
            "run_semantic_query": self._tool_run_semantic_query,
            "execute_readonly_sql": self._tool_execute_readonly_sql,
            "get_distinct_values": self._tool_get_distinct_values,
            "web_search": self._tool_web_search,
            "web_fetch": self._tool_web_fetch,
            "save_web_research": self._tool_save_web_research,
            "add_section": self._tool_add_section,
            "add_text_block": self._tool_add_text_block,
            "place_chart": self._tool_place_chart,
            "finish_dashboard": self._tool_finish_dashboard,
        }
        self.chart_router = ChartStrategyRouter()

        self._tool_specs: dict[str, dict[str, Any]] = {
            "list_tables": {"readOnlyHint": True},
            "describe_table": {"readOnlyHint": True},
            "sample_rows": {"readOnlyHint": True},
            "get_metric_catalog": {"readOnlyHint": True},
            "run_semantic_query": {"readOnlyHint": True},
            "execute_readonly_sql": {"readOnlyHint": True},
            "get_distinct_values": {"readOnlyHint": True},
            "save_view": {"readOnlyHint": False},
            "query_metrics": {"readOnlyHint": True},
            "describe_dataset": {"readOnlyHint": True},
            "web_search": {"readOnlyHint": True},
            "web_fetch": {"readOnlyHint": True},
            "save_web_research": {"readOnlyHint": False},
            "add_section": {"readOnlyHint": False},
            "add_text_block": {"readOnlyHint": False},
            "place_chart": {"readOnlyHint": False},
            "finish_dashboard": {"readOnlyHint": False},
        }

    def invoke(self, request: ToolCallRequest) -> ToolCallResponse:
        with self._lock:
            cached = self._idempotency_cache.get(request.idempotency_key)
        if cached is not None:
            logger.info(
                "tool_call_cache_hit conversation_id=%s request_id=%s tool_name=%s idempotency_key=%s",
                request.conversation_id,
                request.request_id,
                request.tool.name,
                request.idempotency_key,
            )
            if request.emit_debug_blocks:
                logger.info(
                    "tool_call_cache_hit_debug conversation_id=%s request_id=%s tool_name=%s\n%s",
                    request.conversation_id,
                    request.request_id,
                    request.tool.name,
                    format_agent_debug_blocks(
                        tool_result={
                            "conversation_id": request.conversation_id,
                            "request_id": request.request_id,
                            "tool_name": request.tool.name,
                            "idempotency_key": request.idempotency_key,
                            "status": "cache_hit",
                            "arguments": request.tool.arguments,
                            "cached_result": cached.result,
                            "cached_error": cached.error,
                        }
                    ),
                )
            return cached.model_copy(update={"from_cache": True})

        tool = self._tools.get(request.tool.name)
        if tool is None:
            response = ToolCallResponse(
                conversation_id=request.conversation_id,
                request_id=request.request_id,
                idempotency_key=request.idempotency_key,
                tool_name=request.tool.name,
                status="error",
                attempts=0,
                error={
                    "code": "TOOL_NOT_FOUND",
                    "message": f"Unsupported tool: {request.tool.name}",
                    "retryable": False,
                },
            )
            with self._lock:
                self._idempotency_cache[request.idempotency_key] = response
            return response

        context = ToolContext(
            user_id=request.user_id,
            project_id=request.project_id,
            workspace_id=request.workspace_id,
            dataset_table=request.dataset_table,
            role=request.role,
            department=request.department,
            clearance=request.clearance,
        )

        max_attempts = request.retry_limit + 1
        attempts = 0
        for attempt in range(1, max_attempts + 1):
            attempts = attempt
            resolved_context = context
            resolved_arguments = dict(request.tool.arguments)
            try:
                resolved_context, resolved_arguments = self._prepare_tool_scope(
                    context=context,
                    tool_name=request.tool.name,
                    arguments=request.tool.arguments,
                )
            except ToolExecutionError as exc:
                if exc.retryable and attempt < max_attempts:
                    logger.warning(
                        "tool_call_retry conversation_id=%s request_id=%s tool_name=%s attempt=%s code=%s message=%s",
                        request.conversation_id,
                        request.request_id,
                        request.tool.name,
                        attempt,
                        exc.code,
                        exc.message,
                    )
                    continue

                detail = (
                    {
                        "code": "TOOL_RETRY_EXHAUSTED",
                        "message": "Tool failed after retry attempts",
                        "retryable": False,
                        "last_error": exc.to_detail(),
                    }
                    if exc.retryable
                    else exc.to_detail()
                )

                logger.warning(
                    "tool_call_error conversation_id=%s request_id=%s tool_name=%s attempt=%s error=%s",
                    request.conversation_id,
                    request.request_id,
                    request.tool.name,
                    attempt,
                    json.dumps(detail, ensure_ascii=False, default=str),
                )
                if request.emit_debug_blocks:
                    logger.warning(
                        "tool_call_error_debug conversation_id=%s request_id=%s tool_name=%s attempt=%s\n%s",
                        request.conversation_id,
                        request.request_id,
                        request.tool.name,
                        attempt,
                        format_agent_debug_blocks(
                            tool_result={
                                "conversation_id": request.conversation_id,
                                "request_id": request.request_id,
                                "tool_name": request.tool.name,
                                "attempt": attempt,
                                "status": "error",
                                "arguments": request.tool.arguments,
                                "error": detail,
                            }
                        ),
                    )

                response = ToolCallResponse(
                    conversation_id=request.conversation_id,
                    request_id=request.request_id,
                    idempotency_key=request.idempotency_key,
                    tool_name=request.tool.name,
                    status="error",
                    attempts=attempt,
                    error=detail,
                )
                with self._lock:
                    self._idempotency_cache[request.idempotency_key] = response
                return response

            if resolved_context.dataset_table != context.dataset_table:
                logger.warning(
                    "tool_context_dataset_table_fallback conversation_id=%s request_id=%s tool_name=%s requested=%s resolved=%s",
                    request.conversation_id,
                    request.request_id,
                    request.tool.name,
                    context.dataset_table,
                    resolved_context.dataset_table,
                )
            if resolved_arguments != request.tool.arguments:
                logger.info(
                    "tool_arguments_normalized conversation_id=%s request_id=%s tool_name=%s normalized_arguments=%s",
                    request.conversation_id,
                    request.request_id,
                    request.tool.name,
                    json.dumps(resolved_arguments, ensure_ascii=False, default=str),
                )

            logger.info(
                "tool_call_attempt conversation_id=%s request_id=%s tool_name=%s attempt=%s arguments=%s",
                request.conversation_id,
                request.request_id,
                request.tool.name,
                attempt,
                json.dumps(resolved_arguments, ensure_ascii=False, default=str),
            )
            if request.emit_debug_blocks:
                logger.info(
                    "tool_call_attempt_debug conversation_id=%s request_id=%s tool_name=%s attempt=%s\n%s",
                    request.conversation_id,
                    request.request_id,
                    request.tool.name,
                    attempt,
                    format_agent_debug_blocks(
                        tool_trace={
                            "conversation_id": request.conversation_id,
                            "request_id": request.request_id,
                            "tool_name": request.tool.name,
                            "attempt": attempt,
                            "arguments": resolved_arguments,
                        }
                    ),
                )
            try:
                result = tool(resolved_context, resolved_arguments)
                logger.info(
                    "tool_call_success conversation_id=%s request_id=%s tool_name=%s attempt=%s result_summary=%s",
                    request.conversation_id,
                    request.request_id,
                    request.tool.name,
                    attempt,
                    json.dumps(_summarize_tool_result(result), ensure_ascii=False, default=str),
                )
                if request.emit_debug_blocks:
                    logger.info(
                        "tool_call_success_debug conversation_id=%s request_id=%s tool_name=%s attempt=%s\n%s",
                        request.conversation_id,
                        request.request_id,
                        request.tool.name,
                        attempt,
                        format_agent_debug_blocks(
                            tool_result={
                                "conversation_id": request.conversation_id,
                                "request_id": request.request_id,
                                "tool_name": request.tool.name,
                                "attempt": attempt,
                                "status": "success",
                                "arguments": resolved_arguments,
                                "result": result,
                            }
                        ),
                    )
                response = ToolCallResponse(
                    conversation_id=request.conversation_id,
                    request_id=request.request_id,
                    idempotency_key=request.idempotency_key,
                    tool_name=request.tool.name,
                    status="success",
                    attempts=attempt,
                    result=result,
                )
                with self._lock:
                    self._idempotency_cache[request.idempotency_key] = response
                return response
            except ToolExecutionError as exc:
                if exc.retryable and attempt < max_attempts:
                    logger.warning(
                        "tool_call_retry conversation_id=%s request_id=%s tool_name=%s attempt=%s code=%s message=%s",
                        request.conversation_id,
                        request.request_id,
                        request.tool.name,
                        attempt,
                        exc.code,
                        exc.message,
                    )
                    continue

                if exc.retryable:
                    detail = {
                        "code": "TOOL_RETRY_EXHAUSTED",
                        "message": "Tool failed after retry attempts",
                        "retryable": False,
                        "last_error": exc.to_detail(),
                    }
                else:
                    detail = exc.to_detail()

                logger.warning(
                    "tool_call_error conversation_id=%s request_id=%s tool_name=%s attempt=%s error=%s",
                    request.conversation_id,
                    request.request_id,
                    request.tool.name,
                    attempt,
                    json.dumps(detail, ensure_ascii=False, default=str),
                )
                if request.emit_debug_blocks:
                    logger.warning(
                        "tool_call_error_debug conversation_id=%s request_id=%s tool_name=%s attempt=%s\n%s",
                        request.conversation_id,
                        request.request_id,
                        request.tool.name,
                        attempt,
                        format_agent_debug_blocks(
                            tool_result={
                                "conversation_id": request.conversation_id,
                                "request_id": request.request_id,
                                "tool_name": request.tool.name,
                                "attempt": attempt,
                                "status": "error",
                                "arguments": resolved_arguments,
                                "error": detail,
                            }
                        ),
                    )
                response = ToolCallResponse(
                    conversation_id=request.conversation_id,
                    request_id=request.request_id,
                    idempotency_key=request.idempotency_key,
                    tool_name=request.tool.name,
                    status="error",
                    attempts=attempt,
                    error=detail,
                )
                with self._lock:
                    self._idempotency_cache[request.idempotency_key] = response
                return response
            except Exception:
                logger.exception(
                    "tool_call_unexpected_error conversation_id=%s request_id=%s tool_name=%s attempt=%s",
                    request.conversation_id,
                    request.request_id,
                    request.tool.name,
                    attempt,
                )
                if request.emit_debug_blocks:
                    logger.error(
                        "tool_call_unexpected_error_debug conversation_id=%s request_id=%s tool_name=%s attempt=%s\n%s",
                        request.conversation_id,
                        request.request_id,
                        request.tool.name,
                        attempt,
                        format_agent_debug_blocks(
                            tool_result={
                                "conversation_id": request.conversation_id,
                                "request_id": request.request_id,
                                "tool_name": request.tool.name,
                                "attempt": attempt,
                                "status": "unexpected_error",
                                "arguments": resolved_arguments,
                            }
                        ),
                    )
                response = ToolCallResponse(
                    conversation_id=request.conversation_id,
                    request_id=request.request_id,
                    idempotency_key=request.idempotency_key,
                    tool_name=request.tool.name,
                    status="error",
                    attempts=attempt,
                    error={
                        "code": "TOOL_INTERNAL_ERROR",
                        "message": "Unexpected tool failure",
                        "retryable": False,
                    },
                )
                with self._lock:
                    self._idempotency_cache[request.idempotency_key] = response
                return response

        # Defensive fallback (should never happen because the loop always returns).
        response = ToolCallResponse(
            conversation_id=request.conversation_id,
            request_id=request.request_id,
            idempotency_key=request.idempotency_key,
            tool_name=request.tool.name,
            status="error",
            attempts=attempts,
            error={
                "code": "TOOL_INTERNAL_ERROR",
                "message": "Unexpected execution path",
                "retryable": False,
            },
        )
        with self._lock:
            self._idempotency_cache[request.idempotency_key] = response
        return response

    def clear_runtime_state(self) -> None:
        with self._lock:
            self._idempotency_cache.clear()
            self._transient_failures.clear()

    def list_tool_specs(self) -> list[dict[str, Any]]:
        return [
            {"name": name, **spec}
            for name, spec in sorted(self._tool_specs.items())
        ]

    def _tool_query_metrics(self, context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            compiler = self._effective_compiler(context)
            query_ast = self._build_query_ast(arguments, registry=compiler.registry)
            compiled = compiler.compile(query_ast, table_override=context.dataset_table)
            logger.info(
                "query_metrics_compiled user_id=%s project_id=%s dataset_table=%s metric=%s query_ast=%s explain=%s",
                context.user_id,
                context.project_id,
                context.dataset_table,
                compiled.metric,
                json.dumps(
                    {
                        "metric": query_ast.metric,
                        "group_by": query_ast.group_by,
                        "filters": [
                            {"field": item.field, "op": item.op, "value": item.value}
                            for item in query_ast.filters
                        ],
                        "limit": query_ast.limit,
                    },
                    ensure_ascii=False,
                    default=str,
                ),
                json.dumps(compiled.explain, ensure_ascii=False, default=str),
            )
        except MetricCompileError as exc:
            logger.warning(
                "query_metrics_compile_failed user_id=%s project_id=%s dataset_table=%s error=%s",
                context.user_id,
                context.project_id,
                context.dataset_table,
                json.dumps(exc.to_detail(), ensure_ascii=False, default=str),
            )
            raise ToolExecutionError(
                code=exc.code,
                message=exc.message,
                retryable=False,
            ) from exc

        guard = SQLReadOnlyValidator(
            allowed_tables=self._all_session_tables(context),
            sensitive_tables={"raw_payroll", "security_audit_log"},
            sensitive_columns=forbidden_sensitive_columns(context.role),
        )
        rls_injector = RLSInjector()
        access_context = AccessContext(
            user_id=context.user_id,
            role=context.role,
            department=context.department,
            clearance=context.clearance,
        )

        try:
            secure_sql = secure_query_sql(
                compiled.sql,
                context=access_context,
                guard=guard,
                rls_injector=rls_injector,
            )
            logger.info(
                "query_metrics_sql_secured user_id=%s project_id=%s dataset_table=%s metric=%s sql=%s",
                context.user_id,
                context.project_id,
                context.dataset_table,
                compiled.metric,
                secure_sql,
            )
        except QueryAccessError as exc:
            logger.warning(
                "query_metrics_access_denied user_id=%s project_id=%s dataset_table=%s code=%s message=%s",
                context.user_id,
                context.project_id,
                context.dataset_table,
                exc.code,
                exc.message,
            )
            raise ToolExecutionError(
                code=exc.code,
                message=exc.message,
                retryable=False,
            ) from exc
        except (SQLGuardError, RLSError) as exc:
            logger.warning(
                "query_metrics_sql_rejected user_id=%s project_id=%s dataset_table=%s code=%s message=%s",
                context.user_id,
                context.project_id,
                context.dataset_table,
                exc.code,
                exc.message,
            )
            raise ToolExecutionError(
                code=exc.code,
                message=exc.message,
                retryable=False,
            ) from exc

        try:
            with self.dataset_service.session_manager.connection(
                context.user_id,
                context.project_id,
                workspace_id=context.workspace_id,
            ) as conn:
                cursor = conn.execute(secure_sql)
                columns = [column[0] for column in (cursor.description or [])]
                rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        except duckdb.Error as exc:
            logger.warning(
                "query_metrics_execution_failed user_id=%s project_id=%s dataset_table=%s metric=%s error=%s",
                context.user_id,
                context.project_id,
                context.dataset_table,
                compiled.metric,
                str(exc),
            )
            raise ToolExecutionError(
                code="QUERY_EXECUTION_FAILED",
                message="Failed to execute semantic query",
                retryable=True,
            ) from exc

        safe_rows = redact_rows(rows, role=context.role)
        logger.info(
            "query_metrics_rows_returned user_id=%s project_id=%s dataset_table=%s metric=%s row_count=%s columns=%s",
            context.user_id,
            context.project_id,
            context.dataset_table,
            compiled.metric,
            len(safe_rows),
            json.dumps(columns, ensure_ascii=False, default=str),
        )

        return {
            "metric": compiled.metric,
            "query_ast": {
                "metric": query_ast.metric,
                "group_by": query_ast.group_by,
                "filters": [
                    {"field": item.field, "op": item.op, "value": item.value}
                    for item in query_ast.filters
                ],
                "limit": query_ast.limit,
            },
            "sql": secure_sql,
            "explain": compiled.explain,
            "row_count": len(safe_rows),
            "rows": safe_rows,
        }

    def _tool_describe_dataset(self, context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._tool_describe_table(
            context,
            {
                "table": context.dataset_table,
                "sample_limit": arguments.get("sample_limit", 5),
            },
        )

    def _tool_list_tables(self, context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
        _ = arguments
        tables = self._fetch_session_tables(context)
        active_table = self._resolve_table_reference(
            context=context,
            requested_table=context.dataset_table,
            available_tables=tables,
            strict=False,
        )
        ordered_tables = sorted(tables, key=lambda item: (item != active_table, item))
        return {
            "tables": ordered_tables,
            "active_dataset_table": active_table,
            "count": len(ordered_tables),
        }

    def _tool_describe_table(self, context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
        sample_limit = int(arguments.get("sample_limit", 5))
        sample_limit = max(1, min(sample_limit, 50))
        table = self._resolve_table_reference(
            context=context,
            requested_table=arguments.get("table") or context.dataset_table,
            strict=True,
        )

        try:
            with self.dataset_service.session_manager.connection(
                context.user_id,
                context.project_id,
                workspace_id=context.workspace_id,
            ) as conn:
                column_rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
                row_count = int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
                cursor = conn.execute(f'SELECT * FROM "{table}" LIMIT {sample_limit}')
                columns = [column[0] for column in (cursor.description or [])]
                sample_rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        except duckdb.Error as exc:
            raise ToolExecutionError(
                code="DATASET_DESCRIBE_FAILED",
                message="Failed to inspect dataset table",
                retryable=True,
            ) from exc

        column_metadata = self._load_column_metadata(context=context, table=table)
        typed_columns = [
            enrich_column_with_metadata(
                {
                    "name": str(item[1]),
                    "type": str(item[2]),
                    "nullable": not bool(item[3]),
                    "primary_key": bool(item[5]),
                },
                column_metadata,
            )
            for item in column_rows
        ]
        safe_columns = filter_schema_columns(typed_columns, role=context.role)
        safe_rows = redact_rows(sample_rows, role=context.role)

        return {
            "table": table,
            "row_count": row_count,
            "sample_limit": sample_limit,
            "columns": safe_columns,
            "sample_rows": safe_rows,
        }

    def _tool_sample_rows(self, context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
        limit = int(arguments.get("limit", 5))
        limit = max(1, min(limit, 50))
        table = self._resolve_table_reference(
            context=context,
            requested_table=arguments.get("table") or context.dataset_table,
            strict=True,
        )

        try:
            with self.dataset_service.session_manager.connection(
                context.user_id,
                context.project_id,
                workspace_id=context.workspace_id,
            ) as conn:
                cursor = conn.execute(f'SELECT * FROM "{table}" LIMIT {limit}')
                columns = [column[0] for column in (cursor.description or [])]
                rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        except duckdb.Error as exc:
            raise ToolExecutionError(
                code="SAMPLE_ROWS_FAILED",
                message="Failed to sample rows from dataset table",
                retryable=True,
            ) from exc

        safe_rows = redact_rows(rows, role=context.role)
        safe_columns = filter_schema_columns(
            [{"name": name} for name in columns],
            role=context.role,
        )
        return {
            "table": table,
            "row_count": len(safe_rows),
            "columns": [str(item.get("name")) for item in safe_columns if isinstance(item, dict)],
            "rows": safe_rows,
        }

    def _tool_get_metric_catalog(self, context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
        _ = arguments
        compiler = self._effective_compiler(context)
        metrics = compiler.registry.list_metrics()
        return {
            "count": len(metrics),
            "metrics": metrics,
        }

    def _tool_run_semantic_query(self, context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._tool_query_metrics(context, arguments)

    def _tool_execute_readonly_sql(self, context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
        sql = str(arguments.get("sql", "")).strip()
        if not sql:
            raise ToolExecutionError(
                code="SQL_REQUIRED",
                message="execute_readonly_sql requires sql",
                retryable=False,
            )

        max_rows = int(arguments.get("max_rows", get_settings().agent_max_sql_rows))
        max_rows = max(1, min(max_rows, get_settings().agent_max_sql_rows))
        allowed_columns = self._allowed_columns_for_role(context)
        access_context = AccessContext(
            user_id=context.user_id,
            role=context.role,
            department=context.department,
            clearance=context.clearance,
        )
        guard = SQLReadOnlyValidator(
            allowed_tables=self._all_session_tables(context),
            sensitive_tables={"raw_payroll", "security_audit_log"},
            sensitive_columns=forbidden_sensitive_columns(context.role),
        )
        rls_injector = RLSInjector(enforce_viewer_status="status" in allowed_columns)

        try:
            secure_sql = secure_query_sql(
                sql,
                context=access_context,
                guard=guard,
                rls_injector=rls_injector,
            )
        except QueryAccessError as exc:
            raise ToolExecutionError(code=exc.code, message=exc.message, retryable=False) from exc
        except (SQLGuardError, RLSError) as exc:
            raise ToolExecutionError(code=exc.code, message=exc.message, retryable=False) from exc

        limited_sql = f"SELECT * FROM ({secure_sql}) AS scoped_query LIMIT {max_rows}"
        try:
            with self.dataset_service.session_manager.connection(
                context.user_id,
                context.project_id,
                workspace_id=context.workspace_id,
            ) as conn:
                cursor = conn.execute(limited_sql)
                columns = [column[0] for column in (cursor.description or [])]
                rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        except duckdb.Error as exc:
            logger.warning(
                "readonly_sql_execution_failed user_id=%s project_id=%s dataset_table=%s sql=%s error_type=%s error=%s",
                context.user_id,
                context.project_id,
                context.dataset_table,
                limited_sql,
                type(exc).__name__,
                str(exc),
            )
            raise ToolExecutionError(
                code="QUERY_EXECUTION_FAILED",
                message="Failed to execute readonly SQL",
                retryable=True,
            ) from exc

        safe_rows = redact_rows(rows, role=context.role)
        return {
            "sql": secure_sql,
            "row_count": len(safe_rows),
            "columns": columns,
            "rows": safe_rows,
            "truncated": len(safe_rows) >= max_rows,
        }

    def _tool_get_distinct_values(self, context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
        field_name = str(arguments.get("field", "")).strip()
        if not field_name:
            raise ToolExecutionError(
                code="FIELD_REQUIRED",
                message="get_distinct_values requires field",
                retryable=False,
            )

        safe_field = _safe_identifier(field_name).lower()
        allowed_columns = self._allowed_columns_for_role(context)
        if safe_field not in allowed_columns:
            raise ToolExecutionError(
                code="COLUMN_NOT_ALLOWED",
                message="Column is not available for this role",
                retryable=False,
            )

        limit = int(arguments.get("limit", 20))
        limit = max(1, min(limit, 50))
        table = self._resolve_table_reference(
            context=context,
            requested_table=arguments.get("table") or context.dataset_table,
            strict=True,
        )
        sql = (
            f'SELECT "{safe_field}" AS value, COUNT(*) AS frequency '
            f'FROM "{table}" '
            f'GROUP BY "{safe_field}" '
            f'ORDER BY 2 DESC, 1 ASC '
            f'LIMIT {limit}'
        )
        result = self._tool_execute_readonly_sql(
            context,
            {"sql": sql, "max_rows": limit},
        )
        return {
            "field": safe_field,
            "values": result["rows"],
            "row_count": result["row_count"],
            "sql": result["sql"],
        }

    def _tool_save_view(self, context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
        failure_key = str(arguments.get("failure_key", "")).strip()
        failure_times = int(arguments.get("simulate_retryable_failures", 0))
        if failure_key and failure_times > 0:
            current = self._transient_failures.get(failure_key, 0)
            if current < failure_times:
                self._transient_failures[failure_key] = current + 1
                raise ToolExecutionError(
                    code="SAVE_VIEW_TEMPORARY_FAILURE",
                    message="Temporary view storage error",
                    retryable=True,
                )

        chart_spec = arguments.get("chart_spec")
        sql = arguments.get("sql")
        if chart_spec is None and sql is None:
            raise ToolExecutionError(
                code="INVALID_VIEW_PAYLOAD",
                message="save_view requires at least one of chart_spec or sql",
                retryable=False,
            )

        title = str(arguments.get("title") or "Saved View").strip() or "Saved View"
        metadata = arguments.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ToolExecutionError(
                code="INVALID_VIEW_PAYLOAD",
                message="metadata must be an object",
                retryable=False,
            )

        ai_state = {
            "conversation_id": arguments.get("conversation_id"),
            "chart_spec": chart_spec,
            "sql": sql,
            "metadata": metadata,
        }
        safe_ai_state = redact_structure(ai_state, role=context.role)

        try:
            result = self.view_storage.save_view(
                SaveViewInput(
                    user_id=context.user_id,
                    project_id=context.project_id,
                    dataset_table=context.dataset_table,
                    role=context.role,
                    department=context.department,
                    clearance=context.clearance,
                    title=title,
                    ai_state=safe_ai_state,
                    conversation_id=arguments.get("conversation_id"),
                    view_id=arguments.get("view_id"),
                    metadata=metadata,
                    workspace_id=context.workspace_id,
                )
            )
        except ViewStorageError as exc:
            raise ToolExecutionError(
                code=exc.code,
                message=exc.message,
                retryable=False,
            ) from exc

        return {
            "view_id": result["view_id"],
            "title": result["title"],
            "version": result["version"],
            "share_path": result["share_path"],
            "saved_at": result["saved_at"],
        }

    # ------------------------------------------------------------------
    # Web research tools (search / fetch / persist). Enabled only when
    # WEB_SEARCH_ENABLED=true; every one is metadata-audited (never body).
    # ------------------------------------------------------------------

    def _tool_web_search(self, context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
        settings = get_settings()
        self._require_web_search_enabled(settings)
        query = str(arguments.get("query", "")).strip()
        if not query:
            raise ToolExecutionError(
                code="QUERY_REQUIRED",
                message="web_search requires a non-empty query.",
                retryable=False,
            )
        requested_top_k = arguments.get("top_k")
        top_k = int(requested_top_k) if requested_top_k not in (None, "") else None
        started = time.perf_counter()
        try:
            results = search_web(query, top_k=top_k, settings=settings)
        except WebResearchError as exc:
            self._audit_web_event(
                action="web_search",
                context=context,
                status="error",
                detail={"provider": settings.web_search_provider, "code": exc.code},
            )
            raise ToolExecutionError(code=exc.code, message=exc.message, retryable=False) from exc

        payload_results = [item.to_dict() for item in results]
        duration_ms = int((time.perf_counter() - started) * 1000)
        self._audit_web_event(
            action="web_search",
            context=context,
            status="success",
            detail={
                "provider": settings.web_search_provider,
                "result_count": len(payload_results),
                "domains": sorted({_url_domain(str(item.get("url", ""))) for item in payload_results}),
                "query_length": len(query),
                "duration_ms": duration_ms,
            },
        )
        return {
            "query": query,
            "provider": settings.web_search_provider,
            "count": len(payload_results),
            "results": payload_results,
        }

    def _tool_web_fetch(self, context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
        settings = get_settings()
        self._require_web_search_enabled(settings)
        url = str(arguments.get("url", "")).strip()
        if not url:
            raise ToolExecutionError(
                code="URL_REQUIRED",
                message="web_fetch requires a url.",
                retryable=False,
            )
        started = time.perf_counter()
        try:
            fetched = fetch_page(url, settings=settings)
        except WebResearchError as exc:
            self._audit_web_event(
                action="web_fetch",
                context=context,
                status="error",
                detail={"domain": _url_domain(url), "code": exc.code},
            )
            raise ToolExecutionError(code=exc.code, message=exc.message, retryable=False) from exc

        duration_ms = int((time.perf_counter() - started) * 1000)
        self._audit_web_event(
            action="web_fetch",
            context=context,
            status="success",
            detail={
                "domain": _url_domain(str(fetched.get("url", url))),
                "byte_size": fetched.get("byte_size"),
                "char_count": fetched.get("char_count"),
                "truncated": bool(fetched.get("truncated")),
                "duration_ms": duration_ms,
            },
        )
        return {
            "url": fetched.get("url"),
            "title": fetched.get("title"),
            "content": fetched.get("content"),
            "truncated": bool(fetched.get("truncated")),
            "byte_size": fetched.get("byte_size"),
            "char_count": fetched.get("char_count"),
            "fetched_at": _utc_now(),
            "purpose": str(arguments.get("purpose") or "").strip() or None,
        }

    def _tool_save_web_research(self, context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
        settings = get_settings()
        self._require_web_search_enabled(settings)

        raw_table = str(arguments.get("table_name", "")).strip()
        if not raw_table:
            raise ToolExecutionError(
                code="TABLE_NAME_REQUIRED",
                message="save_web_research requires table_name.",
                retryable=False,
            )
        safe_table = _safe_identifier(raw_table)
        full_table = f"{WEB_RESEARCH_TABLE_PREFIX}{safe_table}"

        columns = self._normalize_web_research_columns(arguments.get("columns"))
        rows = arguments.get("rows")
        if not isinstance(rows, list):
            raise ToolExecutionError(
                code="INVALID_ROWS",
                message="save_web_research requires rows as a list of objects.",
                retryable=False,
            )
        if len(rows) > WEB_RESEARCH_MAX_ROWS:
            raise ToolExecutionError(
                code="WEB_RESEARCH_ROW_LIMIT_EXCEEDED",
                message=f"save_web_research accepts at most {WEB_RESEARCH_MAX_ROWS} rows (got {len(rows)}).",
                retryable=False,
            )

        round_sources = arguments.get("_round_sources")
        normalized_sources = _normalize_web_sources(arguments.get("sources"), round_sources)
        if not normalized_sources:
            raise ToolExecutionError(
                code="WEB_RESEARCH_SOURCES_REQUIRED",
                message="save_web_research requires at least one source URL for provenance.",
                retryable=False,
            )

        retrieved_at = datetime.now(timezone.utc)
        column_names = [column["name"] for column in columns]
        all_columns = column_names + list(WEB_RESEARCH_SOURCE_COLUMNS)
        column_ddl = ", ".join(f'"{column["name"]}" {column["type"]}' for column in columns)
        source_ddl = '"_source_url" VARCHAR, "_source_title" VARCHAR, "_retrieved_at" TIMESTAMP'
        create_sql = f'CREATE OR REPLACE TABLE "{full_table}" ({column_ddl}, {source_ddl})'
        insert_columns = ", ".join(f'"{name}"' for name in all_columns)
        placeholders = ", ".join(["?"] * len(all_columns))
        insert_sql = f'INSERT INTO "{full_table}" ({insert_columns}) VALUES ({placeholders})'

        params: list[list[Any]] = []
        per_row = len(normalized_sources) == len(rows) and len(rows) > 0
        joined_url = ";".join(dict.fromkeys(item["url"] for item in normalized_sources))[:1000]
        joined_title = ";".join(dict.fromkeys(item["title"] for item in normalized_sources if item["title"]))[:1000]
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ToolExecutionError(
                    code="INVALID_ROWS",
                    message="Each row must be an object.",
                    retryable=False,
                )
            values: list[Any] = [row.get(name) for name in column_names]
            if per_row:
                values.append(normalized_sources[index]["url"])
                values.append(normalized_sources[index]["title"])
            else:
                values.append(joined_url)
                values.append(joined_title)
            values.append(retrieved_at)
            params.append(values)

        try:
            with self.dataset_service.session_manager.connection(
                context.user_id,
                context.project_id,
                workspace_id=context.workspace_id,
            ) as conn:
                conn.execute(create_sql)
                if params:
                    conn.executemany(insert_sql, params)
        except duckdb.Error as exc:
            logger.warning(
                "save_web_research_failed user_id=%s project_id=%s table=%s error=%s",
                context.user_id,
                context.project_id,
                full_table,
                str(exc),
            )
            raise ToolExecutionError(
                code="WEB_RESEARCH_WRITE_FAILED",
                message="Failed to persist web research data.",
                retryable=False,
            ) from exc

        source_urls = list(dict.fromkeys(item["url"] for item in normalized_sources))
        catalog_id = self._register_web_research_catalog_entry(
            context=context,
            table_name=full_table,
            human_label=str(arguments.get("human_label") or "").strip()
            or safe_table.replace("_", " "),
            description="Saved by AI web research. Sources: "
            + "; ".join(dict.fromkeys(item["title"] or item["url"] for item in normalized_sources)),
            columns=columns,
        )
        self._audit_web_event(
            action="save_web_research",
            context=context,
            status="success",
            detail={
                "table": full_table,
                "row_count": len(rows),
                "column_count": len(columns),
                "source_domains": sorted({_url_domain(url) for url in source_urls}),
                "catalog_registered": catalog_id is not None,
            },
        )
        return {
            "table": full_table,
            "row_count": len(rows),
            "column_count": len(columns),
            "columns": column_names,
            "source_urls": source_urls,
            "catalog_id": catalog_id,
        }

    def _register_web_research_catalog_entry(
        self,
        *,
        context: ToolContext,
        table_name: str,
        human_label: str,
        description: str,
        columns: list[dict[str, str]],
    ) -> str | None:
        """Mirror the uploaded-data behavior: expose the saved table in the
        workspace data catalog. Best-effort — the DuckDB write already
        succeeded, so a catalog failure (missing workspace, legacy login
        without workspace_id, un-migrated schema) must never fail the tool."""
        workspace_id = str(context.workspace_id or "").strip()
        if not workspace_id:
            return None
        try:
            entry = get_table_catalog_service().register_web_research_entry(
                workspace_id=workspace_id,
                actor_user_id=context.user_id,
                table_name=table_name,
                human_label=human_label,
                description=description,
                columns=columns,
            )
            return str(entry["id"])
        except Exception:  # noqa: BLE001
            logger.warning(
                "web_research_catalog_register_failed workspace_id=%s table=%s",
                workspace_id,
                table_name,
                exc_info=True,
            )
            return None

    # ------------------------------------------------------------------
    # Agent canvas tools (add_section / add_text_block / place_chart /
    # finish_dashboard). Only callable during an agent-mode run: the runtime
    # injects the `_agent_run` context; without it (or with the feature flag
    # off) every call is rejected. Every op is appended to the run's op log
    # BEFORE the tool returns, so a disconnected client can always replay it.
    # ------------------------------------------------------------------

    @staticmethod
    def _require_agent_canvas_run(arguments: dict[str, Any]) -> dict[str, Any]:
        if not get_settings().agent_canvas_mode_enabled:
            raise ToolExecutionError(
                code="AGENT_CANVAS_MODE_DISABLED",
                message="Agent canvas mode is disabled (AGENT_CANVAS_MODE_ENABLED=false).",
                retryable=False,
            )
        run_context = arguments.get("_agent_run")
        if not isinstance(run_context, dict) or not str(run_context.get("run_id") or "").strip():
            raise ToolExecutionError(
                code="AGENT_CANVAS_RUN_REQUIRED",
                message="Canvas tools are only available during an agent-mode dashboard run.",
                retryable=False,
            )
        return run_context

    @staticmethod
    def _canvas_model_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in arguments.items() if not key.startswith("_")}

    @staticmethod
    def _validate_canvas_arguments(tool_name: str, model_arguments: dict[str, Any]) -> None:
        try:
            validate_canvas_tool_arguments(tool_name, model_arguments)
        except AgentCanvasError as exc:
            raise ToolExecutionError(code=exc.code, message=exc.message, retryable=False) from exc

    def _audit_canvas_op(
        self,
        *,
        context: ToolContext,
        run_id: str,
        op_type: str,
        status: str,
        duration_ms: int,
    ) -> None:
        # Metadata only — never chart titles, SQL, text content, or data values.
        self._audit_web_event(
            action="agent_canvas_op",
            context=context,
            status=status,
            detail={
                "run_id": run_id,
                "op_type": op_type,
                "duration_ms": duration_ms,
            },
        )

    def _tool_add_section(self, context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        run_context = self._require_agent_canvas_run(arguments)
        model_arguments = self._canvas_model_arguments(arguments)
        self._validate_canvas_arguments("add_section", model_arguments)

        run_id = str(run_context["run_id"])
        page_id = str(run_context.get("page_id") or "")
        title = str(model_arguments["title"]).strip()[:120]
        op = get_agent_canvas_run_store().append_op(
            run_id=run_id,
            op_type="add_section",
            payload=lambda seq: {
                "block_id": block_id_for(run_id, seq),
                "section_id": block_id_for(run_id, seq),
                "page_id": page_id,
                "title": title,
            },
        )
        self._audit_canvas_op(
            context=context,
            run_id=run_id,
            op_type="add_section",
            status="success",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        return {
            "status": "ok",
            "section_id": op["payload"]["section_id"],
            "op": op,
        }

    def _tool_add_text_block(self, context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        run_context = self._require_agent_canvas_run(arguments)
        model_arguments = self._canvas_model_arguments(arguments)
        self._validate_canvas_arguments("add_text_block", model_arguments)

        run_id = str(run_context["run_id"])
        page_id = str(run_context.get("page_id") or "")
        content = str(model_arguments["content"]).strip()[:2000]
        style = str(model_arguments.get("style") or "body").strip()
        section_id = str(model_arguments.get("section_id") or "").strip()
        op = get_agent_canvas_run_store().append_op(
            run_id=run_id,
            op_type="add_text_block",
            payload=lambda seq: {
                "block_id": block_id_for(run_id, seq),
                "section_id": section_id,
                "page_id": page_id,
                "content": content,
                "style": style,
            },
        )
        self._audit_canvas_op(
            context=context,
            run_id=run_id,
            op_type="add_text_block",
            status="success",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        return {
            "status": "ok",
            "block_id": op["payload"]["block_id"],
            "op": op,
        }

    def _tool_place_chart(self, context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        run_context = self._require_agent_canvas_run(arguments)
        model_arguments = self._canvas_model_arguments(arguments)
        self._validate_canvas_arguments("place_chart", model_arguments)

        run_id = str(run_context["run_id"])
        page_id = str(run_context.get("page_id") or "")
        workspace_id = str(context.workspace_id or run_context.get("workspace_id") or "").strip()
        title = str(model_arguments["title"]).strip()[:120]
        chart_type = str(model_arguments["chart_type"]).strip() or "bar"
        size_preset = str(model_arguments["size_preset"]).strip()
        section_id = str(model_arguments.get("section_id") or "").strip()
        description = str(model_arguments.get("description") or "").strip()
        replaces_block_id = str(arguments.get("_replaces_block_id") or "").strip() or None
        store = get_agent_canvas_run_store()

        sql = str(model_arguments.get("sql") or "").strip()
        try:
            if sql:
                max_rows = min(200, int(get_settings().agent_max_sql_rows))
                query_result = self._tool_execute_readonly_sql(
                    context, {"sql": sql, "max_rows": max_rows}
                )
            else:
                query_result = self._tool_run_semantic_query(
                    context,
                    {
                        "metric": model_arguments.get("metric"),
                        "group_by": model_arguments.get("group_by") or [],
                        "filters": model_arguments.get("filters") or [],
                    },
                )
        except ToolExecutionError as exc:
            # Failure isolation (design/spec): the failed item becomes a visible,
            # retryable error placeholder and the run continues with the next item.
            op = store.append_op(
                run_id=run_id,
                op_type="error_placeholder",
                payload=lambda seq: {
                    "block_id": replaces_block_id or block_id_for(run_id, seq),
                    "section_id": section_id,
                    "page_id": page_id,
                    "title": title,
                    "chart_type": chart_type,
                    "size_preset": size_preset,
                    "error": {"code": exc.code, "message": exc.message},
                    "args": model_arguments,
                },
            )
            self._audit_canvas_op(
                context=context,
                run_id=run_id,
                op_type="error_placeholder",
                status="failed",
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
            return {
                "status": "error_placeholder",
                "block_id": op["payload"]["block_id"],
                "section_id": section_id,
                "title": title,
                "error": {"code": exc.code, "message": exc.message},
                "op": op,
            }

        rows = [row for row in (query_result.get("rows") or []) if isinstance(row, dict)]
        spec = self.chart_router.build_spec(
            metric=title,
            intent=description or title,
            rows=rows,
            group_by=list(model_arguments.get("group_by") or ["segment"]),
            chart_type=chart_type,
        )
        spec["title"] = title
        meta = spec.setdefault("meta", {})
        if isinstance(meta, dict):
            meta.update({"generated_by": "agent_canvas_mode", "run_id": run_id})

        asset_id = f"asset-agent-{run_id[-12:]}-{uuid.uuid4().hex[:8]}"
        now = _utc_now()
        asset = {
            "id": asset_id,
            "title": title,
            "chartType": spec.get("chart_type") or chart_type,
            "spec": {
                "chartType": spec.get("chart_type") or chart_type,
                "title": title,
                "echartsOption": (spec.get("config") or {}).get("option") or {},
            },
            "assistantRows": rows,
            "assistantRowsComplete": True,
            "sourceMeta": {
                "sessionId": run_context.get("conversation_id") or "",
                "messageId": run_id,
                "prompt": description or title,
            },
            "rawSpec": spec,
            "createdAt": now,
            "updatedAt": now,
        }
        if workspace_id:
            get_workspace_state_store().upsert_chart_asset(
                workspace_id=workspace_id,
                user_id=context.user_id,
                asset_id=asset_id,
                asset=asset,
            )

        op = store.append_op(
            run_id=run_id,
            op_type="place_chart",
            payload=lambda seq: {
                "block_id": replaces_block_id or block_id_for(run_id, seq),
                "section_id": section_id,
                "page_id": page_id,
                "title": title,
                "chart_type": str(spec.get("chart_type") or chart_type),
                "size_preset": size_preset,
                "asset_id": asset_id,
                "spec": spec,
                **({"replaces_block_id": replaces_block_id} if replaces_block_id else {}),
            },
        )
        self._audit_canvas_op(
            context=context,
            run_id=run_id,
            op_type="place_chart",
            status="success",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        # Metadata only back to the model — never the data rows (design D3).
        return {
            "status": "placed",
            "block_id": op["payload"]["block_id"],
            "section_id": section_id,
            "title": title,
            "chart_type": str(spec.get("chart_type") or chart_type),
            "size_preset": size_preset,
            "asset_id": asset_id,
            "row_count": len(rows),
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "op": op,
        }

    def _tool_finish_dashboard(self, context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
        _ = context
        run_context = self._require_agent_canvas_run(arguments)
        model_arguments = self._canvas_model_arguments(arguments)
        self._validate_canvas_arguments("finish_dashboard", model_arguments)
        return {
            "status": "finished",
            "run_id": str(run_context["run_id"]),
            "summary": str(model_arguments["summary"]).strip()[:1000],
        }

    @staticmethod
    def _require_web_search_enabled(settings: Any) -> None:
        if not settings.web_search_enabled:
            raise ToolExecutionError(
                code="WEB_SEARCH_DISABLED",
                message="Web search tools are disabled (WEB_SEARCH_ENABLED=false).",
                retryable=False,
            )

    @staticmethod
    def _normalize_web_research_columns(raw_columns: Any) -> list[dict[str, str]]:
        if not isinstance(raw_columns, list) or not raw_columns:
            raise ToolExecutionError(
                code="INVALID_COLUMNS",
                message="save_web_research requires columns as a non-empty list of {name, type}.",
                retryable=False,
            )
        if len(raw_columns) > WEB_RESEARCH_MAX_COLUMNS:
            raise ToolExecutionError(
                code="WEB_RESEARCH_COLUMN_LIMIT_EXCEEDED",
                message=f"save_web_research accepts at most {WEB_RESEARCH_MAX_COLUMNS} columns.",
                retryable=False,
            )
        seen: set[str] = set()
        normalized: list[dict[str, str]] = []
        for item in raw_columns:
            if not isinstance(item, dict):
                raise ToolExecutionError(
                    code="INVALID_COLUMNS",
                    message="Each column must be an object with name and type.",
                    retryable=False,
                )
            name = str(item.get("name", "")).strip()
            if not SAFE_IDENTIFIER_RE.match(name):
                raise ToolExecutionError(
                    code="INVALID_IDENTIFIER",
                    message=f"Invalid column name: {name}",
                    retryable=False,
                )
            if name.lower() in {column.lower() for column in WEB_RESEARCH_SOURCE_COLUMNS}:
                raise ToolExecutionError(
                    code="RESERVED_COLUMN_NAME",
                    message=f"Column '{name}' is reserved for provenance metadata.",
                    retryable=False,
                )
            if name.lower() in seen:
                raise ToolExecutionError(
                    code="DUPLICATE_COLUMN",
                    message=f"Duplicate column name: {name}",
                    retryable=False,
                )
            seen.add(name.lower())
            normalized.append({"name": name, "type": _normalize_duckdb_type(item.get("type"))})
        return normalized

    def _audit_web_event(
        self,
        *,
        action: str,
        context: ToolContext,
        status: str,
        detail: dict[str, Any],
    ) -> None:
        try:
            get_audit_logger().log(
                event_type="agent",
                action=action,
                status=status,
                severity="INFO" if status == "success" else "WARNING",
                user_id=context.user_id,
                project_id=context.project_id,
                detail=detail,
            )
        except Exception:  # noqa: BLE001 - auditing must never break a tool call
            logger.debug("web_audit_failed action=%s", action, exc_info=True)

    def _prepare_tool_scope(
        self,
        *,
        context: ToolContext,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> tuple[ToolContext, dict[str, Any]]:
        resolved_arguments = dict(arguments)
        needs_table_resolution = (
            tool_name in TOOLS_REQUIRE_ACTIVE_DATASET
            or tool_name in TOOLS_SOFT_DATASET
            or tool_name in TOOLS_WITH_OPTIONAL_TABLE_ARGUMENT
            or tool_name in {"list_tables", "save_view"}
        )
        if not needs_table_resolution:
            return context, resolved_arguments

        available_tables = self._fetch_session_tables(context)

        # Strict resolution for tools that genuinely require the dataset_table
        # to exist (semantic queries, distinct values).  Best-effort for tools
        # in TOOLS_SOFT_DATASET (execute_readonly_sql) — fall back to the
        # first available table so the agent can always run raw SQL even when
        # the caller-supplied dataset_table is stale or wrong.
        strict = tool_name in TOOLS_REQUIRE_ACTIVE_DATASET
        resolved_dataset_table = self._resolve_table_reference(
            context=context,
            requested_table=context.dataset_table,
            available_tables=available_tables,
            strict=strict,
        )

        # For soft-dataset tools, if resolution returned a name that doesn't
        # match any available table (non-strict resolve returns the raw
        # candidate), pick the first available table so column-level role
        # checks still work.
        if (
            tool_name in TOOLS_SOFT_DATASET
            and available_tables
            and resolved_dataset_table.lower() not in {t.lower() for t in available_tables}
        ):
            resolved_dataset_table = available_tables[0]

        if tool_name in TOOLS_WITH_OPTIONAL_TABLE_ARGUMENT:
            requested_table = resolved_arguments.get("table")
            if requested_table is None or not str(requested_table).strip():
                if resolved_dataset_table:
                    resolved_arguments["table"] = resolved_dataset_table
            else:
                resolved_table = self._resolve_table_reference(
                    context=context,
                    requested_table=requested_table,
                    available_tables=available_tables,
                    strict=True,
                    fallback_table=resolved_dataset_table,
                )
                resolved_arguments["table"] = resolved_table
                if tool_name == "get_distinct_values":
                    resolved_dataset_table = resolved_table

        resolved_context = ToolContext(
            user_id=context.user_id,
            project_id=context.project_id,
            workspace_id=context.workspace_id,
            dataset_table=resolved_dataset_table or context.dataset_table,
            role=context.role,
            department=context.department,
            clearance=context.clearance,
        )
        return resolved_context, resolved_arguments

    def _fetch_session_tables(self, context: ToolContext) -> list[str]:
        try:
            with self.dataset_service.session_manager.connection(
                context.user_id,
                context.project_id,
                workspace_id=context.workspace_id,
            ) as conn:
                rows = conn.execute("SHOW TABLES").fetchall()
        except duckdb.Error as exc:
            raise ToolExecutionError(
                code="LIST_TABLES_FAILED",
                message="Failed to list dataset tables",
                retryable=True,
            ) from exc
        return sorted(str(item[0]) for item in rows)

    def _resolve_table_reference(
        self,
        *,
        context: ToolContext,
        requested_table: Any,
        strict: bool,
        available_tables: list[str] | None = None,
        fallback_table: str | None = None,
    ) -> str:
        tables = available_tables if available_tables is not None else self._fetch_session_tables(context)
        candidate = str(requested_table or "").strip()
        if candidate.startswith('"') and candidate.endswith('"') and len(candidate) >= 2:
            candidate = candidate[1:-1].strip()

        normalized_candidate = ""
        if candidate:
            try:
                normalized_candidate = _safe_identifier(candidate)
            except ToolExecutionError:
                if len(tables) == 1:
                    return tables[0]
                if not strict:
                    return ""
                raise

        canonical = self._match_table_name(normalized_candidate, tables)
        if canonical is not None:
            return canonical

        canonical_fallback = self._match_table_name(fallback_table or "", tables)
        if canonical_fallback is not None:
            return canonical_fallback

        if len(tables) == 1:
            return tables[0]

        if not tables:
            if strict:
                raise ToolExecutionError(
                    code="NO_DATASET_TABLES",
                    message="No dataset tables are available. Upload a dataset first.",
                    retryable=False,
                )
            return normalized_candidate

        if strict:
            target_table = normalized_candidate or context.dataset_table
            preview = ", ".join(f'"{item}"' for item in tables[:5])
            if len(tables) > 5:
                preview = f"{preview}, ..."
            raise ToolExecutionError(
                code="DATASET_TABLE_NOT_FOUND",
                message=f'Dataset table "{target_table}" not found in current session. Available tables: {preview}',
                retryable=False,
            )

        return normalized_candidate

    def _match_table_name(self, table_name: str, candidates: list[str]) -> str | None:
        target = table_name.strip()
        if not target:
            return None
        candidate_map = {item.lower(): item for item in candidates}
        return candidate_map.get(target.lower())

    def _build_query_ast(self, arguments: dict[str, Any], registry: SemanticRegistry | None = None) -> SemanticQueryAST:
        explicit_filters = _parse_filters(arguments.get("filters", []))
        raw_group_by = arguments.get("group_by", [])
        if raw_group_by is None:
            raw_group_by = []
        if not isinstance(raw_group_by, list):
            raise ToolExecutionError(
                code="INVALID_GROUP_BY",
                message="group_by must be a list",
                retryable=False,
            )
        group_by = [str(item) for item in raw_group_by]

        limit = arguments.get("limit")
        if limit is not None:
            limit = int(limit)

        metric = arguments.get("metric")
        if metric:
            return SemanticQueryAST(
                metric=str(metric),
                group_by=group_by,
                filters=explicit_filters,
                limit=limit,
            )

        intent = arguments.get("intent")
        if intent:
            from .semantic import IntentParser as _IntentParser
            parser = _IntentParser(registry) if registry is not None else self.intent_parser
            parsed = parser.parse(str(intent))
            merged_group_by = group_by or parsed.group_by
            merged_filters = [*parsed.filters, *explicit_filters]
            return SemanticQueryAST(
                metric=parsed.metric,
                group_by=merged_group_by,
                filters=merged_filters,
                limit=limit,
            )

        raise ToolExecutionError(
            code="MISSING_QUERY_TARGET",
            message="query_metrics requires metric or intent",
            retryable=False,
        )

    def _all_session_tables(self, context: ToolContext) -> set[str]:
        """Return every table present in the user/project DuckDB session."""
        try:
            rows = self._fetch_session_tables(context)
            if rows:
                return set(rows)
        except ToolExecutionError:
            pass
        except Exception:
            pass
        if context.dataset_table:
            return {context.dataset_table}
        return set()

    def _effective_compiler(self, context: ToolContext) -> MetricCompiler:
        """Return the static semantic compiler.

        Legacy upload-time schema overlays were part of the rule-based Excel
        ingestion path and are no longer produced.
        """
        _ = context
        return self.compiler

    def _allowed_columns_for_role(self, context: ToolContext) -> set[str]:
        dataset_profile = self._tool_describe_table(
            context,
            {"table": context.dataset_table, "sample_limit": 1},
        )
        columns = dataset_profile.get("columns", [])
        if not isinstance(columns, list):
            return set()
        return {
            str(item.get("name", "")).strip().lower()
            for item in columns
            if isinstance(item, dict) and str(item.get("name", "")).strip()
        }

    @staticmethod
    def _load_column_metadata(*, context: ToolContext, table: str) -> dict[str, dict[str, Any]]:
        if not context.workspace_id:
            return {}
        try:
            db_path = get_workspace_service().db_path
            with sqlite_connect(db_path) as conn:
                return load_table_column_metadata(
                    conn,
                    workspace_id=context.workspace_id,
                    table_names=[table, context.dataset_table],
                )
        except sqlite3.Error:
            logger.exception(
                "column_metadata_load_failed workspace_id=%s table=%s",
                context.workspace_id,
                table,
            )
            return {}


def _parse_filters(raw_filters: Any) -> list[QueryFilter]:
    if raw_filters is None:
        return []
    if not isinstance(raw_filters, list):
        raise ToolExecutionError(
            code="INVALID_FILTERS",
            message="filters must be a list",
            retryable=False,
        )

    parsed: list[QueryFilter] = []
    for item in raw_filters:
        if not isinstance(item, dict):
            raise ToolExecutionError(
                code="INVALID_FILTERS",
                message="Each filter must be an object",
                retryable=False,
            )
        field = str(item.get("field", "")).strip()
        if not field:
            raise ToolExecutionError(
                code="INVALID_FILTERS",
                message="Filter field is required",
                retryable=False,
            )
        op = str(item.get("op", "eq"))
        parsed.append(
            QueryFilter(
                field=field,
                op=op,
                value=item.get("value"),
            )
        )

    return parsed


@lru_cache(maxsize=2)
def _cached_tool_calling_service(settings_key: str) -> ToolCallingService:
    _ = settings_key
    return ToolCallingService()


def get_tool_calling_service() -> ToolCallingService:
    settings = get_settings()
    return _cached_tool_calling_service(str(settings.upload_dir.resolve()))


def clear_tool_calling_service_cache() -> None:
    _cached_tool_calling_service.cache_clear()


def _safe_identifier(value: str) -> str:
    if not SAFE_IDENTIFIER_RE.match(value):
        raise ToolExecutionError(
            code="INVALID_IDENTIFIER",
            message=f"Invalid identifier: {value}",
            retryable=False,
        )
    return value


def _normalize_duckdb_type(raw_type: Any) -> str:
    normalized = " ".join(str(raw_type or "").strip().split())
    if not normalized or not SAFE_DUCKDB_TYPE_RE.match(normalized):
        raise ToolExecutionError(
            code="INVALID_COLUMN_TYPE",
            message=f"Invalid DuckDB column type: {raw_type!r}",
            retryable=False,
        )
    base_token = re.split(r"[(\s]", normalized, maxsplit=1)[0].upper()
    if base_token not in ALLOWED_DUCKDB_BASE_TYPES:
        raise ToolExecutionError(
            code="INVALID_COLUMN_TYPE",
            message=f"Unsupported column type: {normalized}",
            retryable=False,
        )
    return normalized


def _url_domain(url: str) -> str:
    try:
        host = urlparse(url).hostname or ""
    except ValueError:
        return ""
    return host.lower()


def _normalize_web_sources(sources: Any, round_sources: Any) -> list[dict[str, str]]:
    """Normalize provided sources, falling back to runtime round-level sources.

    Accepts items shaped as ``{url, title}`` or ``{id, title, url}``. Returns a
    de-duplicated (by url) list preserving order.
    """
    def _coerce(raw: Any) -> list[dict[str, str]]:
        if not isinstance(raw, list):
            return []
        coerced: list[dict[str, str]] = []
        for item in raw:
            if isinstance(item, str):
                url = item.strip()
                title = ""
            elif isinstance(item, dict):
                url = str(item.get("url") or "").strip()
                title = str(item.get("title") or "").strip()
            else:
                continue
            if url:
                coerced.append({"url": url, "title": title})
        return coerced

    primary = _coerce(sources)
    if not primary:
        primary = _coerce(round_sources)

    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in primary:
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        deduped.append(item)
    return deduped


def _summarize_tool_result(result: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    if "metric" in result:
        summary["metric"] = result.get("metric")
    if "row_count" in result:
        summary["row_count"] = result.get("row_count")
    if "sql" in result:
        summary["sql"] = result.get("sql")
    rows = result.get("rows")
    if isinstance(rows, list):
        summary["rows_preview_count"] = min(len(rows), 3)
        summary["rows_preview"] = rows[:3]
    if "table" in result:
        summary["table"] = result.get("table")
    columns = result.get("columns")
    if isinstance(columns, list):
        summary["columns"] = columns[:10]
    if "view_id" in result:
        summary["view_id"] = result.get("view_id")
    if "share_path" in result:
        summary["share_path"] = result.get("share_path")
    return summary


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
