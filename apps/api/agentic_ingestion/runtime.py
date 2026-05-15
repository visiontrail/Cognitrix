from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import asyncio
from typing import Any, AsyncGenerator

import anyio
import duckdb
import pandas as pd
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ClaudeSDKError,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    TextBlock,
    ToolAnnotations,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    create_sdk_mcp_server,
    tool,
)
from sqlglot import exp, parse
from sqlglot.errors import ParseError

from ..column_metadata import upsert_table_column_metadata
from ..config import get_settings
from .models import (
    IngestionAgentPlanOutput,
    IngestionApprovalOverrides,
    IngestionCatalogSetupSeed,
    IngestionExecutionAgentOutput,
    IngestionProposalPayload,
)
from .routing import RouteDecision, select_agent_route

logger = logging.getLogger("cognitrix.ingestion")

SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SAFE_DUCKDB_TYPE_RE = re.compile(r"^[A-Za-z0-9_(),\s]+$")
FORBIDDEN_WRITE_EXPRESSIONS: tuple[type[exp.Expression], ...] = (
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Command,
    exp.Delete,
)
DEFAULT_ACTION_OPTIONS = [
    "update_existing",
    "time_partitioned_new_table",
    "new_table",
    "cancel",
]
CATALOG_SETUP_APPROVAL_OPTIONS = ["confirm_catalog_setup", "cancel"]
INGESTION_APPROVAL_OPTION_VALUES = [
    *DEFAULT_ACTION_OPTIONS,
    *[item for item in CATALOG_SETUP_APPROVAL_OPTIONS if item not in DEFAULT_ACTION_OPTIONS],
]
RECOVERABLE_PLANNING_OUTPUT_CODES = frozenset({
    "AGENT_STRUCTURED_OUTPUT_MISSING",
    "AGENT_STRUCTURED_OUTPUT_INVALID",
    "AGENT_PROPOSAL_REQUIRED",
    "INGESTION_AI_UNAVAILABLE",
})
INGESTION_SDK_MCP_SERVER_NAME = "ingestion"
INGESTION_SDK_RUNTIME_BACKEND = "claude-agent-sdk"
INGESTION_EXECUTION_SDK_MCP_SERVER_NAME = "ingestion_execute"
_LEGACY_APPROVAL_TOOL_ALIASES = frozenset({"AskUserQuestion", "request_human_approval"})
INGESTION_AGENT_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "get_workspace_catalog",
        "description": (
            "List workspace catalog entries that describe business table intents, "
            "human labels, natural-language purpose descriptions, and any known write hints. "
            "Some entries may not have schema details yet; infer them from the upload when needed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "workspace_id": {"type": "string"},
            },
            "required": ["workspace_id"],
        },
        "read_only": True,
    },
    {
        "name": "list_existing_tables",
        "description": (
            "List physical DuckDB tables for the workspace. Also returns catalog_tables "
            "separately so the agent can distinguish persisted data from business intents."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "workspace_id": {"type": "string"},
            },
            "required": ["workspace_id"],
        },
        "read_only": True,
    },
    {
        "name": "inspect_upload",
        "description": "Inspect the uploaded workbook metadata, sheets, columns, and sample preview.",
        "parameters": {
            "type": "object",
            "properties": {
                "upload_id": {"type": "string"},
            },
            "required": ["upload_id"],
        },
        "read_only": True,
    },
    {
        "name": "describe_table_schema",
        "description": (
            "Describe one catalog target. Returns {found: false} if the table does not exist "
            "in the catalog yet — treat that as confirmation a new table must be created. "
            "This may contain only business-purpose metadata if schema has not been inferred yet."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "workspace_id": {"type": "string"},
                "table_name": {"type": "string"},
            },
            "required": ["workspace_id", "table_name"],
        },
        "read_only": True,
    },
    {
        "name": "build_diff_preview",
        "description": (
            "Build a bounded dry preview for the proposed action by inspecting the real "
            "workspace DuckDB target table and the uploaded workbook. This returns computed "
            "insert/update/conflict counts and the candidate actions that are valid for the "
            "current physical table state."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "workspace_id": {"type": "string"},
                "upload_id": {"type": "string"},
                "target_table": {"type": "string"},
                "match_columns": {"type": "array", "items": {"type": "string"}},
                "action_mode": {"type": "string", "enum": DEFAULT_ACTION_OPTIONS},
                "column_mapping": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "Optional original upload header to target column mapping.",
                },
            },
            "required": ["workspace_id", "upload_id", "target_table", "action_mode"],
        },
        "read_only": True,
    },
    {
        "name": "generate_write_sql_draft",
        "description": (
            "Generate a draft SQL shape for the proposed write action. The draft is explanatory; "
            "execution will later rebuild and validate SQL after human approval."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "workspace_id": {"type": "string"},
                "job_id": {"type": "string"},
                "target_table": {"type": "string"},
                "action_mode": {"type": "string", "enum": DEFAULT_ACTION_OPTIONS},
                "match_columns": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["workspace_id", "job_id", "target_table", "action_mode"],
        },
        "read_only": True,
    },
    {
        "name": "create_catalog_entry",
        "description": (
            "Create a new catalog entry for a table that does not yet exist in the workspace. "
            "Call this when get_workspace_catalog returns no matching entry for the upload. "
            "Infer table_name, human_label, business_type, write_mode, and primary/match columns "
            "from the upload columns and content. After this succeeds, call describe_table_schema "
            "to verify, then build_diff_preview and generate_write_sql_draft to complete the proposal."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "workspace_id": {"type": "string"},
                "table_name": {
                    "type": "string",
                    "description": "SQL-safe snake_case identifier for the target table",
                },
                "human_label": {
                    "type": "string",
                    "description": "Human-readable display name for the table",
                },
                "business_type": {
                    "type": "string",
                    "description": (
                        "Free-form snake_case business classification (e.g. roster, "
                        "project_progress, attendance, sales_pipeline, inventory). "
                        "Propose the value that best describes the upload — the system "
                        "does not enforce a fixed vocabulary."
                    ),
                },
                "write_mode": {
                    "type": "string",
                    "enum": ["new_table", "update_existing", "time_partitioned_new_table"],
                },
                "time_grain": {
                    "type": "string",
                    "enum": ["none", "month", "quarter", "year"],
                    "description": "Required only when write_mode is time_partitioned_new_table",
                },
                "primary_keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Column names that uniquely identify each row",
                },
                "match_columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Columns used to match staging rows to target rows for MERGE",
                },
                "description": {
                    "type": "string",
                    "description": "Natural-language purpose of this table",
                },
            },
            "required": ["workspace_id", "table_name", "human_label", "business_type", "write_mode"],
        },
        "read_only": False,
    },
]
INGESTION_SDK_TOOL_NAMES = tuple(str(item["name"]) for item in INGESTION_AGENT_TOOL_DEFINITIONS)
INGESTION_SDK_ALLOWED_TOOL_NAMES = tuple(
    f"mcp__{INGESTION_SDK_MCP_SERVER_NAME}__{name}" for name in INGESTION_SDK_TOOL_NAMES
)
INGESTION_AGENT_PROPOSAL_TOOL_SEQUENCE = [
    "inspect_upload",
    "get_workspace_catalog",
    "list_existing_tables",
    # create_catalog_entry is optional — only needed when no catalog entry exists
    "create_catalog_entry",
    "describe_table_schema",
    "build_diff_preview",
    "generate_write_sql_draft",
]
# +3: one extra turn for create_catalog_entry, one for the final answer, one safety margin
MIN_INGESTION_AGENT_MAX_TURNS = len(INGESTION_AGENT_PROPOSAL_TOOL_SEQUENCE) + 3
INGESTION_EXECUTION_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "get_execution_context",
        "description": (
            "Return the approved write context, proposal hints, staging table name, and "
            "database path for the current execution session."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
        "read_only": True,
    },
    {
        "name": "inspect_upload",
        "description": "Inspect the uploaded workbook metadata, sheets, columns, and sample preview.",
        "parameters": {
            "type": "object",
            "properties": {
                "upload_id": {"type": "string"},
            },
            "required": ["upload_id"],
        },
        "read_only": True,
    },
    {
        "name": "get_workspace_catalog",
        "description": (
            "List workspace catalog entries that describe business table intents, "
            "purpose descriptions, and any inferred write hints."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "workspace_id": {"type": "string"},
            },
            "required": ["workspace_id"],
        },
        "read_only": True,
    },
    {
        "name": "describe_table_schema",
        "description": (
            "Describe one catalog target. Some catalogs start as business-only intents and "
            "gain schema hints after previous uploads."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "workspace_id": {"type": "string"},
                "table_name": {"type": "string"},
            },
            "required": ["workspace_id", "table_name"],
        },
        "read_only": True,
    },
    {
        "name": "describe_staging_dataset",
        "description": (
            "Describe the normalized staging dataset prepared for execution, including schema, "
            "column diagnostics, header mapping, and sample rows."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
        "read_only": True,
    },
    {
        "name": "describe_target_table",
        "description": (
            "Describe the physical DuckDB target table, including whether it exists, its schema, "
            "row count, and sample rows."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
        "read_only": True,
    },
    {
        "name": "preview_write_diff",
        "description": (
            "Compute an actual join preview between staging and target using the supplied match "
            "columns. Returns matched/unmatched counts and missing-column warnings."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "match_columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                },
            },
            "required": ["match_columns"],
        },
        "read_only": True,
    },
    {
        "name": "ensure_target_table_exists",
        "description": (
            "For approved update_existing executions, create the target table as an empty clone "
            "of the staging dataset when it does not already exist."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
        "read_only": False,
    },
    {
        "name": "resolve_column_mapping",
        "description": (
            "Resolve the mapping from staging column names to target column names. "
            "Uses raw_header_mapping, catalog contract, and proposal hints to produce "
            "a definitive staging_col → target_col map. Call this after describe_staging_dataset "
            "and describe_target_table to get confirmed column names for the write SQL."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
        "read_only": True,
    },
    {
        "name": "execute_approved_write",
        "description": (
            "Validate and execute one approved write statement against the current staging "
            "dataset and target table. This is the only write tool."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {"type": "string"},
                "reasoning": {"type": "string"},
            },
            "required": ["sql"],
        },
        "read_only": False,
    },
]
INGESTION_EXECUTION_TOOL_NAMES = tuple(
    str(item["name"]) for item in INGESTION_EXECUTION_TOOL_DEFINITIONS
)
INGESTION_EXECUTION_REQUIRED_TOOL_SEQUENCE = [
    "get_execution_context",
    "describe_staging_dataset",
    "describe_target_table",
    "resolve_column_mapping",
    "execute_approved_write",
]
MIN_INGESTION_EXECUTION_AGENT_MAX_TURNS = len(INGESTION_EXECUTION_REQUIRED_TOOL_SEQUENCE) + 2
INGESTION_AGENT_SYSTEM_PROMPT = """\
You are Cognitrix's Write Ingestion Agent.

Use the provided tools to inspect the upload, workspace catalog, existing targets, and
proposed diff. Then return structured JSON describing your decision.

Allowed decisions:
- awaiting_catalog_setup: fallback only — use this when create_catalog_entry fails or
  when you cannot determine enough schema information to create a catalog entry. Provide
  setup_questions and suggested_catalog_seed.
- awaiting_user_approval: you have a catalog entry (either pre-existing or just created
  via create_catalog_entry) and can produce a concrete write proposal. Include proposal
  with business_type, confidence, recommended_action, candidate_actions, target_table,
  match_columns, column_mapping, diff_preview, risks, explanation, and sql_draft.

If catalog entries only contain business-purpose descriptions and no schema hints, use the
upload itself to infer the likely keys, match columns, and write mode.

Before deciding anything else, classify the workbook layout yourself. Read
inspect_upload.sheet_summary.workbook_structure.sheets[*] — it carries neutral
structural signals only (merged_cell_count, first_row_density, has_stacked_top_metadata,
likely_layout, top_rows_preview). Use the top_rows_preview to read what is actually in
the file, then decide:

- flat_table — a clean tabular sheet whose first row is the header and remaining
  rows are records. Treat the upload as a single structured table; derive
  table_name, human_label, business_type, primary_keys, and match_columns purely
  from the observed column names and sample values.
- human_readable_matrix or mixed_or_unknown — a human-readable layout (stacked
  metadata above a real header row, merged cells, multi-row titles, pivoted
  layout, etc.). Do NOT try to ingest it as one flat table. Instead, in your
  response explain how the sheet should be decomposed into multiple analysis-
  ready tables (e.g., one or more dimension tables plus a long-format fact
  table) and return awaiting_catalog_setup with setup_questions that describe
  the decomposition you propose. Generate every table_name, human_label, and
  description from the actual content you read in top_rows_preview — never
  reuse a name from another file or a generic placeholder.

NEVER copy a table name, human_label, business_type, or description from a
prior example, a template, or the system prompt. Every naming decision must be
justified by content visible in the current upload's columns, sample_preview,
or top_rows_preview.

column_mapping must map every upload column header to its target column name.
For Chinese headers, look at the catalog purpose, match_columns, and any known schema hints
to identify which Chinese header corresponds to which target column (e.g., "工号" → "employee_id").
Include ALL upload columns in column_mapping even if only guessed.

Tool order for a NEW table (no catalog entry yet):
1. inspect_upload — learn file name, columns, and sample data
2. get_workspace_catalog — check for existing catalog entries
3. list_existing_tables — check for existing tables
4. create_catalog_entry — infer table_name, human_label, business_type, write_mode,
   primary_keys, and match_columns from the upload content. Use snake_case for table_name.
   `business_type` is FREE-FORM snake_case: propose whatever label best describes the
   upload (e.g. roster, project_progress, attendance, sales_pipeline, inventory,
   customer_feedback, …). Do not feel constrained to a fixed menu; pick the value a
   human analyst would use to categorise this file. Reuse an existing label from
   get_workspace_catalog when the upload clearly belongs to that category.
5. describe_table_schema — verify the entry was created (should return {found: true})
6. build_diff_preview — compute the write impact from the real target table state
7. generate_write_sql_draft — draft the SQL
8. Return awaiting_user_approval with the full proposal.

Tool order for an EXISTING table (catalog entry already present):
inspect_upload → get_workspace_catalog → list_existing_tables → describe_table_schema →
build_diff_preview → generate_write_sql_draft → return awaiting_user_approval.

If describe_table_schema returns {found: false} after create_catalog_entry, return
awaiting_catalog_setup as a fallback.

Candidate actions and impact counts must come from build_diff_preview. Do not invent
insert/update/conflict counts. Do not offer update_existing unless build_diff_preview
returns it in candidate_actions. The human_approval options must exactly match the
proposal candidate_actions.

Do not execute writes. Do not ask the user any questions. Human approval is handled by
the application after you return. Return ONLY valid JSON matching the required schema.
"""
INGESTION_EXECUTION_AGENT_SYSTEM_PROMPT = """\
You are Cognitrix's Write Execution Agent.

A human has already approved a write action and target table. Inspect the staging dataset
and target table, resolve the exact column mapping, then execute the approved write.

Required workflow:
1. Call get_execution_context — learn the approved_action, target_table, staging_table,
   and proposal_hints.
2. Call describe_staging_dataset — see staging columns (may be c_1, c_2 … for non-ASCII
   headers) and raw_header_mapping (original header → staging column name).
3. Call describe_target_table — see whether the target exists and its schema.
4. Call resolve_column_mapping — returns the confirmed staging_col → target_col map built
   from raw_header_mapping, catalog contract, and proposal hints. Use this map for all SQL.
5. For update_existing: if target does not exist call ensure_target_table_exists first.
6. Call execute_approved_write exactly once with the correct SQL. Use column names from
   resolve_column_mapping, not from proposal_hints.column_mapping directly.
7. Return structured output with status=executed and the receipt from execute_approved_write.

SQL rules:
- update_existing → MERGE INTO {target} AS t USING {staging} AS s ON …
- new_table / time_partitioned_new_table → CREATE TABLE {target} AS SELECT … FROM {staging}
- Use only columns that exist in both staging and target (after resolve_column_mapping).
- One statement only. Do not touch other tables.
- If the context is insufficient to write safely, return status=blocked.

Return ONLY valid JSON matching the required schema.
"""


class IngestionPlanningError(Exception):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int = 400,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code

    def to_detail(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(slots=True)
class SQLWriteValidator:
    target_table: str
    staging_table: str
    action_mode: str

    def validate(self, sql: str) -> str:
        normalized_sql = sql.strip()
        if not normalized_sql:
            raise IngestionPlanningError(
                code="WRITE_SQL_REQUIRED",
                message="Approved SQL is empty",
                status_code=422,
            )

        try:
            statements = parse(normalized_sql, read="duckdb")
        except ParseError as exc:
            raise IngestionPlanningError(
                code="WRITE_SQL_PARSE_ERROR",
                message="Approved SQL has invalid syntax",
                status_code=422,
            ) from exc

        if len(statements) != 1:
            raise IngestionPlanningError(
                code="WRITE_SQL_MULTI_STATEMENT_NOT_ALLOWED",
                message="Only one write statement is allowed",
                status_code=422,
            )
        statement = statements[0]
        self._assert_statement_type(statement)
        self._assert_forbidden_operations(statement)
        self._assert_target_binding(statement)
        self._assert_table_scope(statement)
        return normalized_sql

    def _assert_statement_type(self, statement: exp.Expression) -> None:
        if self.action_mode == "update_existing":
            if not isinstance(statement, exp.Merge):
                raise IngestionPlanningError(
                    code="WRITE_SQL_ACTION_MISMATCH",
                    message="update_existing action requires MERGE statement",
                    status_code=422,
                )
            return

        if self.action_mode in {"new_table", "time_partitioned_new_table"}:
            if not isinstance(statement, exp.Create):
                raise IngestionPlanningError(
                    code="WRITE_SQL_ACTION_MISMATCH",
                    message=f"{self.action_mode} action requires CREATE TABLE AS statement",
                    status_code=422,
                )
            return

        raise IngestionPlanningError(
            code="WRITE_ACTION_UNSUPPORTED",
            message=f"Unsupported approved action: {self.action_mode}",
            status_code=422,
        )

    def _assert_forbidden_operations(self, statement: exp.Expression) -> None:
        for node_type in FORBIDDEN_WRITE_EXPRESSIONS:
            if list(statement.find_all(node_type)):
                raise IngestionPlanningError(
                    code="WRITE_SQL_OPERATION_FORBIDDEN",
                    message="Approved SQL contains forbidden operation",
                    status_code=422,
                )

    def _assert_target_binding(self, statement: exp.Expression) -> None:
        if isinstance(statement, exp.Merge):
            target = statement.this
            if not isinstance(target, exp.Table):
                raise IngestionPlanningError(
                    code="WRITE_SQL_TARGET_MISSING",
                    message="MERGE statement must include a target table",
                    status_code=422,
                )
            target_name = target.name.lower()
            if target_name != self.target_table:
                raise IngestionPlanningError(
                    code="WRITE_SQL_TARGET_MISMATCH",
                    message="Approved SQL target table does not match approved proposal",
                    status_code=422,
                )
            return

        if isinstance(statement, exp.Create):
            target = statement.this
            if not isinstance(target, exp.Table):
                raise IngestionPlanningError(
                    code="WRITE_SQL_TARGET_MISSING",
                    message="CREATE statement must include a target table",
                    status_code=422,
                )
            target_name = target.name.lower()
            if target_name != self.target_table:
                raise IngestionPlanningError(
                    code="WRITE_SQL_TARGET_MISMATCH",
                    message="Approved SQL target table does not match approved proposal",
                    status_code=422,
                )

    def _assert_table_scope(self, statement: exp.Expression) -> None:
        allowed = {self.target_table, self.staging_table}
        for table in statement.find_all(exp.Table):
            table_name = table.name.lower()
            if table_name not in allowed:
                raise IngestionPlanningError(
                    code="WRITE_SQL_TABLE_NOT_ALLOWED",
                    message=f"Approved SQL touches table outside execution scope: {table_name}",
                    status_code=422,
                )


@dataclass(slots=True)
class IngestionExecutionSession:
    workspace_id: str
    job_id: str
    proposal_id: str
    upload_id: str
    approved_action: str
    target_table: str
    staging_table: str
    db_path: Path
    duckdb_conn: duckdb.DuckDBPyConnection
    upload_info: dict[str, Any]
    proposal_payload: IngestionProposalPayload
    dry_run_summary: dict[str, Any]
    staging_profile: dict[str, Any]
    raw_header_mapping: dict[str, str]
    column_diagnostics: list[dict[str, Any]]
    write_receipt: dict[str, Any] | None = None
    executed_sql: str | None = None


@dataclass(slots=True)
class WriteIngestionAgentRuntime:
    stage: str = "M6"

    def health_summary(self) -> str:
        return "Write ingestion runtime supports setup/planning/approval/execution lifecycle"

    def build_plan(
        self,
        *,
        workspace_id: str,
        job_id: str,
        requested_by: str,
        conversation_id: str | None = None,
        message: str | None = None,
    ) -> dict[str, Any]:
        normalized_workspace_id = workspace_id.strip()
        normalized_job_id = job_id.strip()
        normalized_requested_by = requested_by.strip()
        normalized_conversation_id = (conversation_id or "").strip() or None

        if not normalized_workspace_id:
            raise IngestionPlanningError(
                code="WORKSPACE_ID_REQUIRED",
                message="workspace_id is required",
                status_code=422,
            )
        if not normalized_job_id:
            raise IngestionPlanningError(
                code="JOB_ID_REQUIRED",
                message="job_id is required",
                status_code=422,
            )
        if not normalized_requested_by:
            raise IngestionPlanningError(
                code="AUTH_REQUIRED",
                message="user_id is required",
                status_code=401,
            )

        with self._connect() as conn:
            job = self._load_job_context(
                conn=conn,
                workspace_id=normalized_workspace_id,
                job_id=normalized_job_id,
            )
            route = select_agent_route(
                message=message,
                has_files=True,
                ingestion_job_status=str(job["status"]),
            )
            logger.info(
                "ingestion_plan_started workspace_id=%s job_id=%s requested_by=%s conversation_id=%s current_status=%s route=%s",
                normalized_workspace_id,
                normalized_job_id,
                normalized_requested_by,
                normalized_conversation_id or "",
                str(job["status"]),
                route.route,
            )
            self._set_job_status(
                conn=conn,
                job_id=normalized_job_id,
                status="planning",
                business_type_guess=None,
                agent_session_id=normalized_conversation_id,
            )
            self._insert_event(
                conn=conn,
                job_id=normalized_job_id,
                event_type="job_status_updated",
                payload={"status": "planning", "trigger": "ingestion_plan"},
            )

            agent_output, tool_trace = self._run_planning_agent_loop(
                conn=conn,
                workspace_id=normalized_workspace_id,
                job_id=normalized_job_id,
                upload_id=str(job["upload_id"]),
                requested_by=normalized_requested_by,
                conversation_id=normalized_conversation_id,
                message=message,
            )
            # Post-run recovery: the agent sometimes returns awaiting_user_approval with no
            # proposal when the workspace catalog is empty (first upload scenario).  Detect
            # this and synthesise an awaiting_catalog_setup output so the UI shows the
            # catalog-setup card instead of a 502 error.
            if agent_output.status != "awaiting_catalog_setup" and agent_output.proposal is None:
                recovered = self._recover_catalog_setup_from_tool_trace(tool_trace=tool_trace)
                if recovered is not None:
                    logger.warning(
                        "ingestion_agent_output_recovered_from_tool_trace job_id=%s reason=missing_proposal_empty_catalog",
                        normalized_job_id,
                    )
                    agent_output = recovered
            agent_output = self._reconcile_plan_output_with_tool_trace(
                conn=conn,
                agent_output=agent_output,
                tool_trace=tool_trace,
            )
            agent_guess = agent_output.agent_guess.model_dump(mode="json")
            analysis_audit = {
                "agent_planning": {
                    "engine": "write_ingestion_agent_loop",
                    "runtime_backend": INGESTION_SDK_RUNTIME_BACKEND,
                    "model": get_settings().ai_model.strip(),
                    "human_approval_tool_required": False,
                }
            }
            self._insert_event(
                conn=conn,
                job_id=normalized_job_id,
                event_type="business_type_inferred",
                payload={
                    "business_type": agent_guess["business_type"],
                    "confidence": agent_guess["confidence"],
                    "reasoning": agent_guess.get("reasoning", ""),
                    "analysis_audit": analysis_audit["agent_planning"],
                },
            )
            logger.info(
                "ingestion_agent_plan_generated workspace_id=%s job_id=%s status=%s business_type=%s confidence=%s",
                normalized_workspace_id,
                normalized_job_id,
                agent_output.status,
                agent_guess["business_type"],
                agent_guess["confidence"],
            )

            if agent_output.status == "awaiting_catalog_setup":
                if agent_output.suggested_catalog_seed is None:
                    raise IngestionPlanningError(
                        code="AGENT_SETUP_SEED_REQUIRED",
                        message="Agent output must include suggested_catalog_seed for catalog setup",
                        status_code=502,
                    )
                setup_payload = {
                    "status": "awaiting_catalog_setup",
                    "workspace_id": normalized_workspace_id,
                    "job_id": normalized_job_id,
                    "agent_guess": agent_guess,
                    "setup_questions": [
                        item.model_dump(mode="json") for item in agent_output.setup_questions
                    ],
                    "suggested_catalog_seed": agent_output.suggested_catalog_seed.model_dump(mode="json"),
                    "human_approval": agent_output.human_approval.model_dump(mode="json"),
                    "route": route.to_payload(),
                    "tool_trace": tool_trace,
                    "analysis_audit": analysis_audit,
                }
                self._set_job_status(
                    conn=conn,
                    job_id=normalized_job_id,
                    status="awaiting_catalog_setup",
                    business_type_guess=agent_guess["business_type"],
                    agent_session_id=normalized_conversation_id,
                )
                self._insert_event(
                    conn=conn,
                    job_id=normalized_job_id,
                    event_type="setup_required",
                    payload={
                        "business_type": agent_guess["business_type"],
                        "confidence": agent_guess["confidence"],
                        "human_approval": agent_output.human_approval.model_dump(mode="json"),
                        "analysis_audit": analysis_audit["agent_planning"],
                    },
                )
                conn.commit()
                logger.info(
                    "ingestion_plan_completed workspace_id=%s job_id=%s status=awaiting_catalog_setup",
                    normalized_workspace_id,
                    normalized_job_id,
                )
                return setup_payload

            if agent_output.proposal is None:
                raise IngestionPlanningError(
                    code="AGENT_PROPOSAL_REQUIRED",
                    message="Agent output must include proposal for user approval",
                    status_code=502,
                )
            proposal = self._normalize_agent_proposal(agent_output.proposal)
            proposal_id = self._persist_proposal(
                conn=conn,
                workspace_id=normalized_workspace_id,
                job_id=normalized_job_id,
                proposal=proposal,
            )
            self._set_job_status(
                conn=conn,
                job_id=normalized_job_id,
                status="awaiting_user_approval",
                business_type_guess=proposal.business_type,
                agent_session_id=normalized_conversation_id,
            )
            self._insert_event(
                conn=conn,
                job_id=normalized_job_id,
                event_type="human_approval_requested",
                payload=agent_output.human_approval.model_dump(mode="json"),
            )
            self._insert_event(
                conn=conn,
                job_id=normalized_job_id,
                event_type="proposal_generated",
                payload={
                    "proposal_id": proposal_id,
                    "recommended_action": proposal.recommended_action,
                    "target_table": proposal.target_table,
                    "human_approval": agent_output.human_approval.model_dump(mode="json"),
                },
            )
            conn.commit()
            logger.info(
                "ingestion_plan_completed workspace_id=%s job_id=%s status=awaiting_user_approval proposal_id=%s target_table=%s recommended_action=%s",
                normalized_workspace_id,
                normalized_job_id,
                proposal_id,
                proposal.target_table or "",
                proposal.recommended_action,
            )

            return {
                "status": "awaiting_user_approval",
                "workspace_id": normalized_workspace_id,
                "job_id": normalized_job_id,
                "proposal_id": proposal_id,
                "proposal_json": proposal.model_dump(mode="json"),
                "human_approval": agent_output.human_approval.model_dump(mode="json"),
                "route": route.to_payload(),
                "existing_tables": self._latest_tool_result(tool_trace, "list_existing_tables"),
                "tool_trace": tool_trace,
                "analysis_audit": analysis_audit,
            }

    def confirm_setup(
        self,
        *,
        workspace_id: str,
        job_id: str,
        requested_by: str,
        setup_seed: IngestionCatalogSetupSeed,
        conversation_id: str | None = None,
        message: str | None = None,
    ) -> dict[str, Any]:
        normalized_workspace_id = workspace_id.strip()
        normalized_job_id = job_id.strip()
        normalized_requested_by = requested_by.strip()
        normalized_conversation_id = (conversation_id or "").strip() or None

        if not normalized_workspace_id:
            raise IngestionPlanningError(
                code="WORKSPACE_ID_REQUIRED",
                message="workspace_id is required",
                status_code=422,
            )
        if not normalized_job_id:
            raise IngestionPlanningError(
                code="JOB_ID_REQUIRED",
                message="job_id is required",
                status_code=422,
            )
        if not normalized_requested_by:
            raise IngestionPlanningError(
                code="AUTH_REQUIRED",
                message="user_id is required",
                status_code=401,
            )
        if not SAFE_IDENTIFIER_RE.match(setup_seed.table_name):
            raise IngestionPlanningError(
                code="CATALOG_TABLE_NAME_INVALID",
                message="setup.table_name must be a valid SQL identifier",
                status_code=422,
            )

        with self._connect() as conn:
            job = self._load_job_context(
                conn=conn,
                workspace_id=normalized_workspace_id,
                job_id=normalized_job_id,
            )
            current_status = str(job["status"])
            if current_status not in {"uploaded", "planning", "awaiting_catalog_setup"}:
                raise IngestionPlanningError(
                    code="INGESTION_SETUP_NOT_ALLOWED",
                    message=f"Setup cannot be confirmed when job status is {current_status}",
                    status_code=409,
                )

            upload_info = self._tool_inspect_upload(conn=conn, upload_id=str(job["upload_id"]))
            catalog_entry = self._upsert_catalog_entry_from_setup(
                conn=conn,
                workspace_id=normalized_workspace_id,
                requested_by=normalized_requested_by,
                setup_seed=setup_seed,
                upload_info=upload_info,
            )
            self._set_job_status(
                conn=conn,
                job_id=normalized_job_id,
                status="planning",
                business_type_guess=setup_seed.business_type,
                agent_session_id=normalized_conversation_id,
            )
            self._insert_event(
                conn=conn,
                job_id=normalized_job_id,
                event_type="setup_confirmed",
                payload={
                    "catalog_entry_id": catalog_entry["id"],
                    "business_type": catalog_entry["business_type"],
                    "table_name": catalog_entry["table_name"],
                },
            )
            conn.commit()

        plan_payload = self.build_plan(
            workspace_id=normalized_workspace_id,
            job_id=normalized_job_id,
            requested_by=normalized_requested_by,
            conversation_id=normalized_conversation_id,
            message=message,
        )
        plan_payload["setup"] = {
            "status": "confirmed",
            "catalog_entry": catalog_entry,
        }
        return plan_payload

    async def build_plan_stream_async(
        self,
        *,
        workspace_id: str,
        job_id: str,
        requested_by: str,
        conversation_id: str | None = None,
        message: str | None = None,
    ) -> AsyncGenerator[tuple[str, dict[str, Any]], None]:
        """Async generator that streams planning agent events as (event_type, payload) tuples."""
        normalized_workspace_id = workspace_id.strip()
        normalized_job_id = job_id.strip()
        normalized_requested_by = requested_by.strip()
        normalized_conversation_id = (conversation_id or "").strip() or None

        event_queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()

        async def _run_and_finalize() -> None:
            try:
                if not normalized_workspace_id:
                    raise IngestionPlanningError(code="WORKSPACE_ID_REQUIRED", message="workspace_id is required", status_code=422)
                if not normalized_job_id:
                    raise IngestionPlanningError(code="JOB_ID_REQUIRED", message="job_id is required", status_code=422)
                if not normalized_requested_by:
                    raise IngestionPlanningError(code="AUTH_REQUIRED", message="user_id is required", status_code=401)

                settings = get_settings()
                auth_token_source = settings.anthropic_auth_token or settings.ai_api_key
                if not auth_token_source.strip() or not settings.ai_model.strip():
                    raise IngestionPlanningError(
                        code="INGESTION_AI_NOT_CONFIGURED",
                        message="Claude Agent SDK credentials are not configured for ingestion planning",
                        status_code=503,
                    )

                with self._connect() as conn:
                    job = self._load_job_context(
                        conn=conn,
                        workspace_id=normalized_workspace_id,
                        job_id=normalized_job_id,
                    )
                    route = select_agent_route(
                        message=message,
                        has_files=True,
                        ingestion_job_status=str(job["status"]),
                    )
                    self._set_job_status(
                        conn=conn,
                        job_id=normalized_job_id,
                        status="planning",
                        business_type_guess=None,
                        agent_session_id=normalized_conversation_id,
                    )
                    self._insert_event(
                        conn=conn,
                        job_id=normalized_job_id,
                        event_type="job_status_updated",
                        payload={"status": "planning", "trigger": "ingestion_plan"},
                    )

                    tool_trace_snapshot: list[dict[str, Any]] = []
                    try:
                        agent_output, tool_trace = await self._run_planning_agent_loop_async(
                            conn=conn,
                            workspace_id=normalized_workspace_id,
                            job_id=normalized_job_id,
                            upload_id=str(job["upload_id"]),
                            requested_by=normalized_requested_by,
                            conversation_id=normalized_conversation_id,
                            message=message,
                            tool_trace_sink=tool_trace_snapshot,
                            event_queue=event_queue,
                        )
                    except IngestionPlanningError as exc:
                        if exc.code in RECOVERABLE_PLANNING_OUTPUT_CODES:
                            recovered = (
                                self._recover_proposal_from_tool_trace(tool_trace=tool_trace_snapshot)
                                or self._recover_catalog_setup_from_tool_trace(tool_trace=tool_trace_snapshot)
                            )
                            if recovered is not None:
                                logger.warning(
                                    "ingestion_agent_output_recovered_from_tool_trace job_id=%s reason=%s",
                                    normalized_job_id,
                                    exc.code.lower(),
                                )
                                agent_output = recovered
                                tool_trace = tool_trace_snapshot
                            else:
                                raise
                        else:
                            raise

                    # Post-run recovery: the agent sometimes completes all tools but returns
                    # no structured output.  Try recovering a proposal first (catalog already
                    # populated), then fall back to requesting catalog setup (empty catalog /
                    # first-upload scenario).
                    if agent_output.status != "awaiting_catalog_setup" and agent_output.proposal is None:
                        recovered = (
                            self._recover_proposal_from_tool_trace(tool_trace=tool_trace)
                            or self._recover_catalog_setup_from_tool_trace(tool_trace=tool_trace)
                        )
                        if recovered is not None:
                            reason = (
                                "missing_proposal_tool_trace_recovered"
                                if recovered.status != "awaiting_catalog_setup"
                                else "missing_proposal_empty_catalog"
                            )
                            logger.warning(
                                "ingestion_agent_output_recovered_from_tool_trace job_id=%s reason=%s",
                                normalized_job_id,
                                reason,
                            )
                            agent_output = recovered

                    agent_output = self._reconcile_plan_output_with_tool_trace(
                        conn=conn,
                        agent_output=agent_output,
                        tool_trace=tool_trace,
                    )
                    agent_guess = agent_output.agent_guess.model_dump(mode="json")
                    analysis_audit = {
                        "agent_planning": {
                            "engine": "write_ingestion_agent_loop",
                            "runtime_backend": INGESTION_SDK_RUNTIME_BACKEND,
                            "model": settings.ai_model.strip(),
                            "human_approval_tool_required": False,
                        }
                    }
                    self._insert_event(
                        conn=conn,
                        job_id=normalized_job_id,
                        event_type="business_type_inferred",
                        payload={
                            "business_type": agent_guess["business_type"],
                            "confidence": agent_guess["confidence"],
                            "reasoning": agent_guess.get("reasoning", ""),
                            "analysis_audit": analysis_audit["agent_planning"],
                        },
                    )

                    if agent_output.status == "awaiting_catalog_setup":
                        if agent_output.suggested_catalog_seed is None:
                            raise IngestionPlanningError(
                                code="AGENT_SETUP_SEED_REQUIRED",
                                message="Agent output must include suggested_catalog_seed for catalog setup",
                                status_code=502,
                            )
                        decision_payload: dict[str, Any] = {
                            "status": "awaiting_catalog_setup",
                            "workspace_id": normalized_workspace_id,
                            "job_id": normalized_job_id,
                            "agent_guess": agent_guess,
                            "setup_questions": [item.model_dump(mode="json") for item in agent_output.setup_questions],
                            "suggested_catalog_seed": agent_output.suggested_catalog_seed.model_dump(mode="json"),
                            "human_approval": agent_output.human_approval.model_dump(mode="json"),
                            "route": route.to_payload(),
                            "tool_trace": tool_trace,
                            "analysis_audit": analysis_audit,
                        }
                        self._set_job_status(
                            conn=conn,
                            job_id=normalized_job_id,
                            status="awaiting_catalog_setup",
                            business_type_guess=agent_guess["business_type"],
                            agent_session_id=normalized_conversation_id,
                        )
                        self._insert_event(
                            conn=conn,
                            job_id=normalized_job_id,
                            event_type="setup_required",
                            payload={
                                "business_type": agent_guess["business_type"],
                                "confidence": agent_guess["confidence"],
                                "human_approval": agent_output.human_approval.model_dump(mode="json"),
                                "analysis_audit": analysis_audit["agent_planning"],
                            },
                        )
                        conn.commit()
                    else:
                        if agent_output.proposal is None:
                            raise IngestionPlanningError(
                                code="AGENT_PROPOSAL_REQUIRED",
                                message="Agent output must include proposal for user approval",
                                status_code=502,
                            )
                        proposal = self._normalize_agent_proposal(agent_output.proposal)
                        proposal_id = self._persist_proposal(
                            conn=conn,
                            workspace_id=normalized_workspace_id,
                            job_id=normalized_job_id,
                            proposal=proposal,
                        )
                        self._set_job_status(
                            conn=conn,
                            job_id=normalized_job_id,
                            status="awaiting_user_approval",
                            business_type_guess=proposal.business_type,
                            agent_session_id=normalized_conversation_id,
                        )
                        self._insert_event(
                            conn=conn,
                            job_id=normalized_job_id,
                            event_type="human_approval_requested",
                            payload=agent_output.human_approval.model_dump(mode="json"),
                        )
                        self._insert_event(
                            conn=conn,
                            job_id=normalized_job_id,
                            event_type="proposal_generated",
                            payload={
                                "proposal_id": proposal_id,
                                "recommended_action": proposal.recommended_action,
                                "target_table": proposal.target_table,
                                "human_approval": agent_output.human_approval.model_dump(mode="json"),
                            },
                        )
                        conn.commit()
                        decision_payload = {
                            "status": "awaiting_user_approval",
                            "workspace_id": normalized_workspace_id,
                            "job_id": normalized_job_id,
                            "proposal_id": proposal_id,
                            "proposal_json": proposal.model_dump(mode="json"),
                            "human_approval": agent_output.human_approval.model_dump(mode="json"),
                            "route": route.to_payload(),
                            "existing_tables": self._latest_tool_result(tool_trace, "list_existing_tables"),
                            "tool_trace": tool_trace,
                            "analysis_audit": analysis_audit,
                        }

                    event_queue.put_nowait(("decision", decision_payload))

            except IngestionPlanningError as exc:
                event_queue.put_nowait(("error", {
                    "job_id": normalized_job_id,
                    "code": exc.code,
                    "message": exc.message,
                }))
            except Exception as exc:
                event_queue.put_nowait(("error", {
                    "job_id": normalized_job_id,
                    "code": "INGESTION_AI_UNAVAILABLE",
                    "message": f"Planning agent failed: {exc}",
                }))
            finally:
                event_queue.put_nowait(None)

        task = asyncio.ensure_future(_run_and_finalize())
        try:
            while True:
                item = await event_queue.get()
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

    async def confirm_setup_stream_async(
        self,
        *,
        workspace_id: str,
        job_id: str,
        requested_by: str,
        setup_seed: IngestionCatalogSetupSeed,
        conversation_id: str | None = None,
        message: str | None = None,
    ) -> AsyncGenerator[tuple[str, dict[str, Any]], None]:
        """Async generator that streams confirm-setup agent events."""
        normalized_workspace_id = workspace_id.strip()
        normalized_job_id = job_id.strip()
        normalized_requested_by = requested_by.strip()
        normalized_conversation_id = (conversation_id or "").strip() or None

        if not normalized_workspace_id:
            raise IngestionPlanningError(code="WORKSPACE_ID_REQUIRED", message="workspace_id is required", status_code=422)
        if not normalized_job_id:
            raise IngestionPlanningError(code="JOB_ID_REQUIRED", message="job_id is required", status_code=422)
        if not normalized_requested_by:
            raise IngestionPlanningError(code="AUTH_REQUIRED", message="user_id is required", status_code=401)
        if not SAFE_IDENTIFIER_RE.match(setup_seed.table_name):
            raise IngestionPlanningError(
                code="CATALOG_TABLE_NAME_INVALID",
                message="setup.table_name must be a valid SQL identifier",
                status_code=422,
            )

        catalog_entry: dict[str, Any] | None = None
        with self._connect() as conn:
            job = self._load_job_context(
                conn=conn,
                workspace_id=normalized_workspace_id,
                job_id=normalized_job_id,
            )
            current_status = str(job["status"])
            if current_status not in {"uploaded", "planning", "awaiting_catalog_setup"}:
                raise IngestionPlanningError(
                    code="INGESTION_SETUP_NOT_ALLOWED",
                    message=f"Setup cannot be confirmed when job status is {current_status}",
                    status_code=409,
                )
            upload_info = self._tool_inspect_upload(conn=conn, upload_id=str(job["upload_id"]))
            catalog_entry = self._upsert_catalog_entry_from_setup(
                conn=conn,
                workspace_id=normalized_workspace_id,
                requested_by=normalized_requested_by,
                setup_seed=setup_seed,
                upload_info=upload_info,
            )
            self._set_job_status(
                conn=conn,
                job_id=normalized_job_id,
                status="planning",
                business_type_guess=setup_seed.business_type,
                agent_session_id=normalized_conversation_id,
            )
            self._insert_event(
                conn=conn,
                job_id=normalized_job_id,
                event_type="setup_confirmed",
                payload={
                    "catalog_entry_id": catalog_entry["id"],
                    "business_type": catalog_entry["business_type"],
                    "table_name": catalog_entry["table_name"],
                },
            )
            conn.commit()

        async for event_type, payload in self.build_plan_stream_async(
            workspace_id=normalized_workspace_id,
            job_id=normalized_job_id,
            requested_by=normalized_requested_by,
            conversation_id=normalized_conversation_id,
            message=message,
        ):
            if event_type == "decision" and catalog_entry is not None:
                payload = dict(payload)
                payload["setup"] = {"status": "confirmed", "catalog_entry": catalog_entry}
            yield event_type, payload

    def approve_plan(
        self,
        *,
        workspace_id: str,
        job_id: str,
        proposal_id: str,
        approved_action: str,
        approved_by: str,
        user_overrides: IngestionApprovalOverrides | None = None,
    ) -> dict[str, Any]:
        normalized_workspace_id = workspace_id.strip()
        normalized_job_id = job_id.strip()
        normalized_proposal_id = proposal_id.strip()
        normalized_approved_by = approved_by.strip()
        normalized_action = approved_action.strip().lower()

        if not normalized_workspace_id:
            raise IngestionPlanningError(
                code="WORKSPACE_ID_REQUIRED",
                message="workspace_id is required",
                status_code=422,
            )
        if not normalized_job_id:
            raise IngestionPlanningError(
                code="JOB_ID_REQUIRED",
                message="job_id is required",
                status_code=422,
            )
        if not normalized_proposal_id:
            raise IngestionPlanningError(
                code="PROPOSAL_ID_REQUIRED",
                message="proposal_id is required",
                status_code=422,
            )
        if not normalized_approved_by:
            raise IngestionPlanningError(
                code="AUTH_REQUIRED",
                message="user_id is required",
                status_code=401,
            )
        if normalized_action not in DEFAULT_ACTION_OPTIONS:
            raise IngestionPlanningError(
                code="APPROVED_ACTION_INVALID",
                message="approved_action is not supported",
                status_code=422,
            )

        with self._connect() as conn:
            self._ensure_user_record(conn=conn, user_id=normalized_approved_by)
            job = self._load_job_for_approval(
                conn=conn,
                workspace_id=normalized_workspace_id,
                job_id=normalized_job_id,
            )
            proposal_row, proposal_payload = self._load_proposal(
                conn=conn,
                workspace_id=normalized_workspace_id,
                job_id=normalized_job_id,
                proposal_id=normalized_proposal_id,
            )
            if normalized_action not in proposal_payload.candidate_actions:
                raise IngestionPlanningError(
                    code="APPROVED_ACTION_NOT_IN_CANDIDATES",
                    message="approved_action is not in proposal candidate_actions",
                    status_code=422,
                )

            if normalized_action == "cancel":
                self._set_job_status(
                    conn=conn,
                    job_id=normalized_job_id,
                    status="cancelled",
                    business_type_guess=proposal_payload.business_type,
                    agent_session_id=str(job["agent_session_id"]) if job["agent_session_id"] else None,
                )
                self._insert_event(
                    conn=conn,
                    job_id=normalized_job_id,
                    event_type="proposal_cancelled",
                    payload={
                        "proposal_id": normalized_proposal_id,
                        "approved_by": normalized_approved_by,
                    },
                )
                conn.commit()
                return {
                    "status": "cancelled",
                    "workspace_id": normalized_workspace_id,
                    "job_id": normalized_job_id,
                    "proposal_id": normalized_proposal_id,
                    "approved_action": "cancel",
                }

            overrides_payload = (user_overrides.model_dump(mode="json") if user_overrides else {})
            target_table, time_grain = self._resolve_approved_target(
                proposal_payload=proposal_payload,
                approved_action=normalized_action,
                overrides=user_overrides,
            )
            upload_info = self._tool_inspect_upload(conn=conn, upload_id=str(job["upload_id"]))
            preview_override = self._tool_build_diff_preview(
                conn=conn,
                workspace_id=normalized_workspace_id,
                upload_info=upload_info,
                target_table=target_table,
                match_columns=list(proposal_payload.match_columns),
                action_mode=normalized_action,
                column_mapping=dict(proposal_payload.column_mapping),
            )
            computed_candidates = self._valid_action_list(preview_override.get("candidate_actions"))
            if computed_candidates and normalized_action not in computed_candidates:
                raise IngestionPlanningError(
                    code="APPROVED_ACTION_NOT_AVAILABLE",
                    message="approved_action is not available for the current physical target table state",
                    status_code=422,
                )
            dry_run_summary = self._build_dry_run_summary(
                proposal_payload=proposal_payload,
                approved_action=normalized_action,
                target_table=target_table,
                time_grain=time_grain,
                preview_override=preview_override,
            )
            logger.info(
                "ingestion_approval_bound workspace_id=%s job_id=%s proposal_id=%s approved_action=%s target_table=%s time_grain=%s match_columns=%s dry_run_summary=%s",
                normalized_workspace_id,
                normalized_job_id,
                normalized_proposal_id,
                normalized_action,
                target_table,
                time_grain,
                _compact_json(proposal_payload.match_columns),
                _compact_json(dry_run_summary),
            )

            self._set_job_status(
                conn=conn,
                job_id=normalized_job_id,
                status="approved",
                business_type_guess=proposal_payload.business_type,
                agent_session_id=str(job["agent_session_id"]) if job["agent_session_id"] else None,
            )
            self._insert_event(
                conn=conn,
                job_id=normalized_job_id,
                event_type="proposal_approved",
                payload={
                    "proposal_id": normalized_proposal_id,
                    "approved_action": normalized_action,
                    "approved_by": normalized_approved_by,
                    "target_table": target_table,
                    "time_grain": time_grain,
                    "dry_run_summary": dry_run_summary,
                    "user_overrides": overrides_payload,
                    "proposal_version": int(proposal_row["proposal_version"]),
                },
            )
            self._insert_event(
                conn=conn,
                job_id=normalized_job_id,
                event_type="job_status_updated",
                payload={"status": "approved", "trigger": "ingestion_approve"},
            )
            conn.commit()

        return {
            "status": "approved",
            "workspace_id": normalized_workspace_id,
            "job_id": normalized_job_id,
            "proposal_id": normalized_proposal_id,
            "approved_action": normalized_action,
            "target_table": target_table,
            "time_grain": time_grain,
            "dry_run_summary": dry_run_summary,
        }

    def execute_plan(
        self,
        *,
        workspace_id: str,
        job_id: str,
        proposal_id: str,
        executed_by: str,
    ) -> dict[str, Any]:
        normalized_workspace_id = workspace_id.strip()
        normalized_job_id = job_id.strip()
        normalized_proposal_id = proposal_id.strip()
        normalized_executed_by = executed_by.strip()

        if not normalized_workspace_id:
            raise IngestionPlanningError(
                code="WORKSPACE_ID_REQUIRED",
                message="workspace_id is required",
                status_code=422,
            )
        if not normalized_job_id:
            raise IngestionPlanningError(
                code="JOB_ID_REQUIRED",
                message="job_id is required",
                status_code=422,
            )
        if not normalized_proposal_id:
            raise IngestionPlanningError(
                code="PROPOSAL_ID_REQUIRED",
                message="proposal_id is required",
                status_code=422,
            )
        if not normalized_executed_by:
            raise IngestionPlanningError(
                code="AUTH_REQUIRED",
                message="user_id is required",
                status_code=401,
            )

        started_at = _utc_now()
        with self._connect() as conn:
            self._ensure_user_record(conn=conn, user_id=normalized_executed_by)
            job = self._load_job_for_execution(
                conn=conn,
                workspace_id=normalized_workspace_id,
                job_id=normalized_job_id,
            )
            _proposal_row, proposal_payload = self._load_proposal(
                conn=conn,
                workspace_id=normalized_workspace_id,
                job_id=normalized_job_id,
                proposal_id=normalized_proposal_id,
            )
            approval_event = self._load_latest_approval_event(
                conn=conn,
                job_id=normalized_job_id,
                proposal_id=normalized_proposal_id,
            )
            approved_action = str(approval_event["approved_action"])
            target_table = str(approval_event["target_table"])
            dry_run_summary = approval_event["dry_run_summary"]
            upload_info = self._tool_inspect_upload(conn=conn, upload_id=str(job["upload_id"]))
            self._set_job_status(
                conn=conn,
                job_id=normalized_job_id,
                status="executing",
                business_type_guess=proposal_payload.business_type,
                agent_session_id=str(job["agent_session_id"]) if job["agent_session_id"] else None,
            )
            self._insert_event(
                conn=conn,
                job_id=normalized_job_id,
                event_type="job_status_updated",
                payload={"status": "executing", "trigger": "ingestion_execute"},
            )
            conn.commit()
        logger.info(
            "ingestion_execute_started workspace_id=%s job_id=%s proposal_id=%s target_table=%s approved_action=%s upload_id=%s upload_path=%s dry_run_summary=%s",
            normalized_workspace_id,
            normalized_job_id,
            normalized_proposal_id,
            target_table,
            approved_action,
            str(job["upload_id"]),
            str(upload_info.get("storage_path") or ""),
            _compact_json(dry_run_summary),
        )

        execution_id = uuid.uuid4().hex
        execution_mode = approved_action
        executed_sql = ""
        try:
            with self._connect() as exec_conn:
                execution_output, tool_trace = self._run_execution_agent_loop(
                    conn=exec_conn,
                    workspace_id=normalized_workspace_id,
                    job_id=normalized_job_id,
                    proposal_id=normalized_proposal_id,
                    upload_id=str(job["upload_id"]),
                    target_table=target_table,
                    approved_action=approved_action,
                    dry_run_summary=dry_run_summary,
                    upload_info=upload_info,
                    proposal_payload=proposal_payload,
                )
            if execution_output.status != "executed":
                raise IngestionPlanningError(
                    code="INGESTION_EXECUTION_BLOCKED",
                    message=execution_output.reasoning or "Execution agent blocked the write",
                    status_code=422,
                )
            receipt = dict(execution_output.receipt)
            executed_sql = execution_output.executed_sql
            receipt.setdefault("tool_trace", tool_trace)
            execution_status = "succeeded"
            failure_message = ""
        except IngestionPlanningError as exc:
            execution_status = "failed"
            failure_message = exc.message
            receipt = {
                "success": False,
                "workspace_id": normalized_workspace_id,
                "job_id": normalized_job_id,
                "target_table": target_table,
                "approved_action": approved_action,
                "error": {"code": exc.code, "message": exc.message},
            }
        except Exception as exc:  # pragma: no cover - defensive path
            execution_status = "failed"
            failure_message = str(exc)
            receipt = {
                "success": False,
                "workspace_id": normalized_workspace_id,
                "job_id": normalized_job_id,
                "target_table": target_table,
                "approved_action": approved_action,
                "error": {"code": "INGESTION_EXECUTION_FAILED", "message": str(exc)},
            }

        finished_at = _utc_now()
        logger.info(
            "ingestion_execute_finished workspace_id=%s job_id=%s proposal_id=%s execution_id=%s status=%s target_table=%s receipt=%s",
            normalized_workspace_id,
            normalized_job_id,
            normalized_proposal_id,
            execution_id,
            execution_status,
            target_table,
            _compact_json(receipt),
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ingestion_executions (
                    id,
                    job_id,
                    proposal_id,
                    workspace_id,
                    executed_by,
                    execution_mode,
                    validated_sql,
                    dry_run_summary,
                    execution_receipt,
                    status,
                    started_at,
                    finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    execution_id,
                    normalized_job_id,
                    normalized_proposal_id,
                    normalized_workspace_id,
                    normalized_executed_by,
                    execution_mode,
                    executed_sql,
                    json.dumps(dry_run_summary, ensure_ascii=False),
                    json.dumps(receipt, ensure_ascii=False),
                    execution_status,
                    started_at,
                    finished_at,
                ),
            )
            if execution_status == "succeeded":
                self._sync_catalog_entry_from_execution(
                    conn=conn,
                    workspace_id=normalized_workspace_id,
                    table_name=target_table,
                    requested_by=normalized_executed_by,
                    proposal_payload=proposal_payload,
                    approved_action=approved_action,
                )
                self._sync_column_metadata_from_execution(
                    conn=conn,
                    workspace_id=normalized_workspace_id,
                    table_name=target_table,
                    receipt=receipt,
                    proposal_payload=proposal_payload,
                )
            final_job_status = "succeeded" if execution_status == "succeeded" else "failed"
            self._set_job_status(
                conn=conn,
                job_id=normalized_job_id,
                status=final_job_status,
                business_type_guess=None,
                agent_session_id=None,
            )
            event_type = "execution_succeeded" if execution_status == "succeeded" else "execution_failed"
            self._insert_event(
                conn=conn,
                job_id=normalized_job_id,
                event_type=event_type,
                payload={
                    "execution_id": execution_id,
                    "proposal_id": normalized_proposal_id,
                    "status": execution_status,
                    "receipt": receipt,
                },
            )
            self._insert_event(
                conn=conn,
                job_id=normalized_job_id,
                event_type="job_status_updated",
                payload={"status": final_job_status, "trigger": "ingestion_execute_finalize"},
            )
            conn.commit()

        if execution_status != "succeeded":
            raise IngestionPlanningError(
                code="INGESTION_EXECUTION_FAILED",
                message=f"Execution failed: {failure_message}",
                status_code=500,
            )

        return {
            "status": "succeeded",
            "workspace_id": normalized_workspace_id,
            "job_id": normalized_job_id,
            "proposal_id": normalized_proposal_id,
            "execution_id": execution_id,
            "receipt": receipt,
        }

    async def execute_plan_stream_async(
        self,
        *,
        workspace_id: str,
        job_id: str,
        proposal_id: str,
        executed_by: str,
    ) -> AsyncGenerator[tuple[str, dict[str, Any]], None]:
        """Async generator that streams execution agent events as (event_type, payload) tuples."""
        normalized_workspace_id = workspace_id.strip()
        normalized_job_id = job_id.strip()
        normalized_proposal_id = proposal_id.strip()
        normalized_executed_by = executed_by.strip()

        if not normalized_workspace_id:
            raise IngestionPlanningError(code="WORKSPACE_ID_REQUIRED", message="workspace_id is required", status_code=422)
        if not normalized_job_id:
            raise IngestionPlanningError(code="JOB_ID_REQUIRED", message="job_id is required", status_code=422)
        if not normalized_proposal_id:
            raise IngestionPlanningError(code="PROPOSAL_ID_REQUIRED", message="proposal_id is required", status_code=422)
        if not normalized_executed_by:
            raise IngestionPlanningError(code="AUTH_REQUIRED", message="user_id is required", status_code=401)

        settings = get_settings()
        auth_token_source = settings.anthropic_auth_token or settings.ai_api_key
        if not auth_token_source.strip() or not settings.ai_model.strip():
            raise IngestionPlanningError(
                code="INGESTION_AI_NOT_CONFIGURED",
                message="Claude Agent SDK credentials are not configured for ingestion execution",
                status_code=503,
            )

        event_queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()

        async def _run_execution_and_finalize() -> None:
            try:
                started_at = _utc_now()
                with self._connect() as conn:
                    self._ensure_user_record(conn=conn, user_id=normalized_executed_by)
                    job = self._load_job_for_execution(
                        conn=conn,
                        workspace_id=normalized_workspace_id,
                        job_id=normalized_job_id,
                    )
                    _proposal_row, proposal_payload = self._load_proposal(
                        conn=conn,
                        workspace_id=normalized_workspace_id,
                        job_id=normalized_job_id,
                        proposal_id=normalized_proposal_id,
                    )
                    approval_event = self._load_latest_approval_event(
                        conn=conn,
                        job_id=normalized_job_id,
                        proposal_id=normalized_proposal_id,
                    )
                    approved_action = str(approval_event["approved_action"])
                    target_table = str(approval_event["target_table"])
                    dry_run_summary = approval_event["dry_run_summary"]
                    upload_info = self._tool_inspect_upload(conn=conn, upload_id=str(job["upload_id"]))
                    self._set_job_status(
                        conn=conn,
                        job_id=normalized_job_id,
                        status="executing",
                        business_type_guess=proposal_payload.business_type,
                        agent_session_id=str(job["agent_session_id"]) if job["agent_session_id"] else None,
                    )
                    self._insert_event(
                        conn=conn,
                        job_id=normalized_job_id,
                        event_type="job_status_updated",
                        payload={"status": "executing", "trigger": "ingestion_execute"},
                    )
                    conn.commit()

                execution_id = uuid.uuid4().hex
                execution_mode = approved_action
                executed_sql = ""

                session = self._prepare_execution_session(
                    workspace_id=normalized_workspace_id,
                    job_id=normalized_job_id,
                    proposal_id=normalized_proposal_id,
                    upload_id=str(job["upload_id"]),
                    target_table=target_table,
                    approved_action=approved_action,
                    dry_run_summary=dry_run_summary,
                    upload_info=upload_info,
                    proposal_payload=proposal_payload,
                )

                tool_trace_snapshot: list[dict[str, Any]] = []
                execution_status = "failed"
                failure_message = ""
                receipt: dict[str, Any] = {}

                try:
                    with self._connect() as exec_conn:
                        execution_output, tool_trace = await self._run_execution_agent_loop_async(
                            conn=exec_conn,
                            session=session,
                            tool_trace_sink=tool_trace_snapshot,
                            event_queue=event_queue,
                        )
                    if execution_output.status != "executed":
                        raise IngestionPlanningError(
                            code="INGESTION_EXECUTION_BLOCKED",
                            message=execution_output.reasoning or "Execution agent blocked the write",
                            status_code=422,
                        )
                    receipt = dict(execution_output.receipt)
                    executed_sql = execution_output.executed_sql
                    receipt.setdefault("tool_trace", tool_trace)
                    execution_status = "succeeded"
                except IngestionPlanningError as exc:
                    execution_status = "failed"
                    failure_message = exc.message
                    receipt = {
                        "success": False,
                        "workspace_id": normalized_workspace_id,
                        "job_id": normalized_job_id,
                        "target_table": target_table,
                        "approved_action": approved_action,
                        "error": {"code": exc.code, "message": exc.message},
                    }
                except Exception as exc:
                    execution_status = "failed"
                    failure_message = str(exc)
                    receipt = {
                        "success": False,
                        "workspace_id": normalized_workspace_id,
                        "job_id": normalized_job_id,
                        "target_table": target_table,
                        "approved_action": approved_action,
                        "error": {"code": "INGESTION_EXECUTION_FAILED", "message": str(exc)},
                    }
                finally:
                    try:
                        session.duckdb_conn.close()
                    except Exception:
                        pass

                finished_at = _utc_now()
                with self._connect() as conn:
                    conn.execute(
                        """
                        INSERT INTO ingestion_executions (
                            id, job_id, proposal_id, workspace_id, executed_by,
                            execution_mode, validated_sql, dry_run_summary,
                            execution_receipt, status, started_at, finished_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            execution_id,
                            normalized_job_id,
                            normalized_proposal_id,
                            normalized_workspace_id,
                            normalized_executed_by,
                            execution_mode,
                            executed_sql,
                            json.dumps(dry_run_summary, ensure_ascii=False),
                            json.dumps(receipt, ensure_ascii=False),
                            execution_status,
                            started_at,
                            finished_at,
                        ),
                    )
                    if execution_status == "succeeded":
                        self._sync_catalog_entry_from_execution(
                            conn=conn,
                            workspace_id=normalized_workspace_id,
                            table_name=target_table,
                            requested_by=normalized_executed_by,
                            proposal_payload=proposal_payload,
                            approved_action=approved_action,
                        )
                        self._sync_column_metadata_from_execution(
                            conn=conn,
                            workspace_id=normalized_workspace_id,
                            table_name=target_table,
                            receipt=receipt,
                            proposal_payload=proposal_payload,
                        )
                    final_job_status = "succeeded" if execution_status == "succeeded" else "failed"
                    self._set_job_status(
                        conn=conn,
                        job_id=normalized_job_id,
                        status=final_job_status,
                        business_type_guess=None,
                        agent_session_id=None,
                    )
                    event_type_db = "execution_succeeded" if execution_status == "succeeded" else "execution_failed"
                    self._insert_event(
                        conn=conn,
                        job_id=normalized_job_id,
                        event_type=event_type_db,
                        payload={"execution_id": execution_id, "proposal_id": normalized_proposal_id, "status": execution_status, "receipt": receipt},
                    )
                    self._insert_event(
                        conn=conn,
                        job_id=normalized_job_id,
                        event_type="job_status_updated",
                        payload={"status": final_job_status, "trigger": "ingestion_execute_finalize"},
                    )
                    conn.commit()

                if execution_status != "succeeded":
                    event_queue.put_nowait(("error", {
                        "job_id": normalized_job_id,
                        "code": "INGESTION_EXECUTION_FAILED",
                        "message": f"Execution failed: {failure_message}",
                    }))
                else:
                    event_queue.put_nowait(("decision", {
                        "status": "succeeded",
                        "workspace_id": normalized_workspace_id,
                        "job_id": normalized_job_id,
                        "proposal_id": normalized_proposal_id,
                        "execution_id": execution_id,
                        "receipt": receipt,
                    }))

            except IngestionPlanningError as exc:
                event_queue.put_nowait(("error", {
                    "job_id": normalized_job_id,
                    "code": exc.code,
                    "message": exc.message,
                }))
            except Exception as exc:
                event_queue.put_nowait(("error", {
                    "job_id": normalized_job_id,
                    "code": "INGESTION_AI_UNAVAILABLE",
                    "message": f"Execution agent failed: {exc}",
                }))
            finally:
                event_queue.put_nowait(None)

        task = asyncio.ensure_future(_run_execution_and_finalize())
        try:
            while True:
                item = await event_queue.get()
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

    def _run_execution_agent_loop(
        self,
        *,
        conn: sqlite3.Connection,
        workspace_id: str,
        job_id: str,
        proposal_id: str,
        upload_id: str,
        target_table: str,
        approved_action: str,
        dry_run_summary: dict[str, Any],
        upload_info: dict[str, Any],
        proposal_payload: IngestionProposalPayload,
    ) -> tuple[IngestionExecutionAgentOutput, list[dict[str, Any]]]:
        settings = get_settings()
        auth_token_source = settings.anthropic_auth_token or settings.ai_api_key
        if not auth_token_source.strip() or not settings.ai_model.strip():
            raise IngestionPlanningError(
                code="INGESTION_AI_NOT_CONFIGURED",
                message="Claude Agent SDK credentials are not configured for ingestion execution",
                status_code=503,
            )

        tool_trace_snapshot: list[dict[str, Any]] = []
        session = self._prepare_execution_session(
            workspace_id=workspace_id,
            job_id=job_id,
            proposal_id=proposal_id,
            upload_id=upload_id,
            target_table=target_table,
            approved_action=approved_action,
            dry_run_summary=dry_run_summary,
            upload_info=upload_info,
            proposal_payload=proposal_payload,
        )

        async def runner() -> tuple[IngestionExecutionAgentOutput, list[dict[str, Any]]]:
            return await self._run_execution_agent_loop_async(
                conn=conn,
                session=session,
                tool_trace_sink=tool_trace_snapshot,
            )

        try:
            return anyio.run(runner)
        except IngestionPlanningError:
            raise
        except TimeoutError as exc:
            recovered = self._recover_execution_output_from_tool_trace(
                tool_trace=tool_trace_snapshot,
                session=session,
            )
            if recovered is not None:
                logger.warning(
                    "ingestion_execution_output_recovered_from_tool_trace job_id=%s reason=timeout_outer",
                    job_id,
                )
                return recovered, tool_trace_snapshot
            raise IngestionPlanningError(
                code="INGESTION_AI_UNAVAILABLE",
                message=(
                    "Claude Agent SDK timed out during ingestion execution "
                    f"(>{settings.agent_timeout_seconds}s)"
                ),
                status_code=503,
            ) from exc
        except ClaudeSDKError as exc:
            recovered = self._recover_execution_output_from_tool_trace(
                tool_trace=tool_trace_snapshot,
                session=session,
            )
            if recovered is not None:
                logger.warning(
                    "ingestion_execution_output_recovered_from_tool_trace job_id=%s reason=claude_sdk_error",
                    job_id,
                )
                return recovered, tool_trace_snapshot
            suffix = str(exc).strip()
            detail = f": {suffix}" if suffix else ""
            raise IngestionPlanningError(
                code="INGESTION_AI_UNAVAILABLE",
                message=f"Claude Agent SDK is unavailable for ingestion execution{detail}",
                status_code=503,
            ) from exc
        except Exception as exc:
            raise IngestionPlanningError(
                code="INGESTION_AI_UNAVAILABLE",
                message=f"Claude Agent SDK failed during ingestion execution: {exc}",
                status_code=503,
            ) from exc
        finally:
            try:
                session.duckdb_conn.close()
            except Exception:
                pass

    async def _run_execution_agent_loop_async(
        self,
        *,
        conn: sqlite3.Connection,
        session: IngestionExecutionSession,
        tool_trace_sink: list[dict[str, Any]] | None = None,
        event_queue: asyncio.Queue | None = None,
    ) -> tuple[IngestionExecutionAgentOutput, list[dict[str, Any]]]:
        settings = get_settings()
        tool_trace = tool_trace_sink if tool_trace_sink is not None else []
        options = self._build_execution_sdk_options(
            conn=conn,
            job_id=session.job_id,
            session=session,
            tool_trace=tool_trace,
            event_queue=event_queue,
        )
        prompt = self._build_execution_agent_prompt(session=session)
        raw_output: dict[str, Any] | None = None
        text_blocks: list[str] = []
        session_id = f"ingestion-execute-{session.job_id}"

        try:
            with anyio.fail_after(settings.agent_timeout_seconds):
                async with ClaudeSDKClient(options=options) as client:
                    await client.query(prompt, session_id=session_id)
                    async for sdk_message in client.receive_response():
                        if event_queue is not None and isinstance(sdk_message, AssistantMessage):
                            for block in sdk_message.content:
                                if isinstance(block, TextBlock) and block.text:
                                    event_queue.put_nowait(("planning", {
                                        "job_id": session.job_id,
                                        "text": block.text,
                                    }))
                        candidate = self._consume_ingestion_sdk_message(
                            message=sdk_message,
                            text_blocks=text_blocks,
                        )
                        if candidate is not None:
                            raw_output = candidate
        except TimeoutError:
            recovered = self._recover_execution_output_from_tool_trace(
                tool_trace=tool_trace,
                session=session,
            )
            if recovered is not None:
                logger.warning(
                    "ingestion_execution_output_recovered_from_tool_trace job_id=%s reason=timeout",
                    session.job_id,
                )
                return recovered, tool_trace
            raise

        if raw_output is None and text_blocks:
            raw_output = _decode_json_dict("\n".join(text_blocks))
        if raw_output is None:
            recovered = self._recover_execution_output_from_tool_trace(
                tool_trace=tool_trace,
                session=session,
            )
            if recovered is not None:
                logger.warning(
                    "ingestion_execution_output_recovered_from_tool_trace job_id=%s reason=missing_structured_output",
                    session.job_id,
                )
                return recovered, tool_trace
            raise IngestionPlanningError(
                code="AGENT_STRUCTURED_OUTPUT_MISSING",
                message="Write Execution Agent did not return structured output",
                status_code=502,
            )
        try:
            output = IngestionExecutionAgentOutput.model_validate(raw_output)
        except Exception as exc:
            recovered = self._recover_execution_output_from_tool_trace(
                tool_trace=tool_trace,
                session=session,
            )
            if recovered is not None:
                logger.warning(
                    "ingestion_execution_output_recovered_from_tool_trace job_id=%s reason=invalid_structured_output",
                    session.job_id,
                )
                return recovered, tool_trace
            raise IngestionPlanningError(
                code="AGENT_STRUCTURED_OUTPUT_INVALID",
                message="Write Execution Agent returned invalid structured output",
                status_code=502,
            ) from exc

        if output.target_table != session.target_table:
            raise IngestionPlanningError(
                code="EXECUTION_TARGET_MISMATCH",
                message="Execution agent returned a target table outside the approved scope",
                status_code=502,
            )
        if output.approved_action != session.approved_action:
            raise IngestionPlanningError(
                code="EXECUTION_ACTION_MISMATCH",
                message="Execution agent returned an action outside the approved scope",
                status_code=502,
            )
        if output.status == "executed":
            if session.write_receipt is None:
                recovered = self._recover_execution_output_from_tool_trace(
                    tool_trace=tool_trace,
                    session=session,
                )
                if recovered is not None:
                    return recovered, tool_trace
                raise IngestionPlanningError(
                    code="EXECUTION_WRITE_NOT_PERFORMED",
                    message="Execution agent reported success without calling execute_approved_write",
                    status_code=502,
                )
            self._attach_canonical_write_receipt(output=output, session=session)
        return output, tool_trace

    @staticmethod
    def _attach_canonical_write_receipt(
        *,
        output: IngestionExecutionAgentOutput,
        session: IngestionExecutionSession,
    ) -> None:
        if output.status != "executed" or session.write_receipt is None:
            return
        canonical_receipt = dict(session.write_receipt)
        output.receipt = {**dict(output.receipt), **canonical_receipt}
        executed_sql = str(
            canonical_receipt.get("executed_sql") or output.executed_sql or session.executed_sql or ""
        ).strip()
        if executed_sql:
            output.executed_sql = executed_sql

    def _build_execution_sdk_options(
        self,
        *,
        conn: sqlite3.Connection,
        job_id: str,
        session: IngestionExecutionSession,
        tool_trace: list[dict[str, Any]],
        event_queue: asyncio.Queue | None = None,
    ) -> ClaudeAgentOptions:
        settings = get_settings()

        async def can_use_tool(
            tool_name: str,
            input_data: dict[str, Any],
            permission_context: Any,
        ) -> PermissionResultAllow | PermissionResultDeny:
            _ = (input_data, permission_context)
            canonical_name = _canonical_mcp_tool_name(
                tool_name,
                server_name=INGESTION_EXECUTION_SDK_MCP_SERVER_NAME,
            )
            if canonical_name in INGESTION_EXECUTION_TOOL_NAMES:
                return PermissionResultAllow()
            return PermissionResultDeny(
                message=f"Tool '{tool_name}' is outside the Write Execution Agent tool surface."
            )

        server = create_sdk_mcp_server(
            name=INGESTION_EXECUTION_SDK_MCP_SERVER_NAME,
            version="1.0.0",
            tools=self._build_execution_sdk_tools(
                conn=conn,
                job_id=job_id,
                session=session,
                tool_trace=tool_trace,
                event_queue=event_queue,
            ),
        )
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
            system_prompt=INGESTION_EXECUTION_AGENT_SYSTEM_PROMPT,
            mcp_servers={INGESTION_EXECUTION_SDK_MCP_SERVER_NAME: server},
            can_use_tool=can_use_tool,
            permission_mode="default",
            max_turns=max(
                settings.agent_max_tool_steps,
                MIN_INGESTION_EXECUTION_AGENT_MAX_TURNS,
            ),
            model=model,
            cwd=str(Path.cwd()),
            env=env,
            output_format={
                "type": "json_schema",
                "schema": IngestionExecutionAgentOutput.model_json_schema(),
            },
        )

    def _build_execution_sdk_tools(
        self,
        *,
        conn: sqlite3.Connection,
        job_id: str,
        session: IngestionExecutionSession,
        tool_trace: list[dict[str, Any]],
        event_queue: asyncio.Queue | None = None,
    ) -> list[Any]:
        sdk_tools: list[Any] = []
        for definition in INGESTION_EXECUTION_TOOL_DEFINITIONS:
            tool_name = str(definition["name"])
            description = str(definition["description"])
            input_schema = definition["parameters"]
            is_read_only = bool(definition.get("read_only", True))
            annotations = ToolAnnotations(
                readOnlyHint=is_read_only,
                destructiveHint=not is_read_only,
                idempotentHint=is_read_only,
                openWorldHint=False,
            )

            async def handler(args: dict[str, Any], _tool_name: str = tool_name) -> dict[str, Any]:
                step_id = uuid.uuid4().hex
                started_at = time.time()
                if event_queue is not None:
                    event_queue.put_nowait(("tool_use", {
                        "job_id": job_id,
                        "tool_name": _tool_name,
                        "arguments": args,
                        "step_id": step_id,
                        "started_at": started_at,
                    }))
                try:
                    result = self._invoke_execution_sdk_tool(
                        conn=conn,
                        job_id=job_id,
                        session=session,
                        tool_trace=tool_trace,
                        tool_name=_tool_name,
                        arguments=args,
                    )
                    completed_at = time.time()
                    if event_queue is not None:
                        event_queue.put_nowait(("tool_result", {
                            "job_id": job_id,
                            "tool_name": _tool_name,
                            "status": "success",
                            "result": result,
                            "step_id": step_id,
                            "started_at": started_at,
                            "completed_at": completed_at,
                        }))
                    return {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(result, ensure_ascii=False, default=str),
                            }
                        ],
                        "is_error": False,
                    }
                except Exception as exc:
                    completed_at = time.time()
                    if event_queue is not None:
                        event_queue.put_nowait(("tool_result", {
                            "job_id": job_id,
                            "tool_name": _tool_name,
                            "status": "error",
                            "error": str(exc),
                            "step_id": step_id,
                            "started_at": started_at,
                            "completed_at": completed_at,
                        }))
                    raise

            sdk_tools.append(
                tool(
                    tool_name,
                    description,
                    input_schema,
                    annotations=annotations,
                )(handler)
            )
        return sdk_tools

    def _invoke_execution_sdk_tool(
        self,
        *,
        conn: sqlite3.Connection,
        job_id: str,
        session: IngestionExecutionSession,
        tool_trace: list[dict[str, Any]],
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        canonical_name = _canonical_mcp_tool_name(
            tool_name,
            server_name=INGESTION_EXECUTION_SDK_MCP_SERVER_NAME,
        )
        if canonical_name not in INGESTION_EXECUTION_TOOL_NAMES:
            raise IngestionPlanningError(
                code="INGESTION_TOOL_NOT_ALLOWED",
                message=f"Tool '{tool_name}' is outside the Write Execution Agent tool surface",
                status_code=403,
            )
        if not isinstance(arguments, dict):
            arguments = {}
        return self._run_tool(
            conn=conn,
            job_id=job_id,
            trace=tool_trace,
            name=canonical_name,
            arguments=arguments,
            handler=lambda: self._handle_execution_tool(
                conn=conn,
                session=session,
                tool_name=canonical_name,
                arguments=arguments,
            ),
        )

    def _handle_execution_tool(
        self,
        *,
        conn: sqlite3.Connection,
        session: IngestionExecutionSession,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        if tool_name == "get_execution_context":
            return self._tool_get_execution_context(session=session)
        if tool_name == "inspect_upload":
            return self._tool_inspect_upload(
                conn=conn,
                upload_id=str(arguments.get("upload_id") or session.upload_id),
            )
        if tool_name == "get_workspace_catalog":
            return self._tool_get_workspace_catalog(
                conn=conn,
                workspace_id=session.workspace_id,
            )
        if tool_name == "describe_table_schema":
            return self._tool_describe_table_schema_by_name(
                conn=conn,
                workspace_id=session.workspace_id,
                table_name=str(arguments.get("table_name") or session.target_table),
            )
        if tool_name == "describe_staging_dataset":
            return self._tool_describe_staging_dataset(session=session)
        if tool_name == "describe_target_table":
            return self._tool_describe_target_table(conn=conn, session=session)
        if tool_name == "preview_write_diff":
            return self._tool_preview_write_diff(
                session=session,
                match_columns=[
                    self._normalize_identifier(str(item))
                    for item in arguments.get("match_columns", [])
                    if self._normalize_identifier(str(item))
                ],
            )
        if tool_name == "resolve_column_mapping":
            return self._tool_resolve_column_mapping(conn=conn, session=session)
        if tool_name == "ensure_target_table_exists":
            return self._tool_ensure_target_table_exists(session=session)
        if tool_name == "execute_approved_write":
            return self._tool_execute_approved_write(
                session=session,
                sql=str(arguments.get("sql", "")),
                reasoning=str(arguments.get("reasoning", "")),
            )
        raise IngestionPlanningError(
            code="INGESTION_TOOL_NOT_ALLOWED",
            message=f"Unsupported execution tool: {tool_name}",
            status_code=403,
        )

    @staticmethod
    def _build_execution_agent_prompt(*, session: IngestionExecutionSession) -> str:
        return json.dumps(
            {
                "task": "Execute the already-approved ingestion write.",
                "workspace_id": session.workspace_id,
                "job_id": session.job_id,
                "proposal_id": session.proposal_id,
                "upload_id": session.upload_id,
                "approved_action": session.approved_action,
                "target_table": session.target_table,
                "staging_table": session.staging_table,
                "dry_run_summary": session.dry_run_summary,
                "proposal_hints": {
                    "business_type": session.proposal_payload.business_type,
                    "match_columns": session.proposal_payload.match_columns,
                    "column_mapping": session.proposal_payload.column_mapping,
                    "explanation": session.proposal_payload.explanation,
                    "risks": session.proposal_payload.risks,
                },
                "required_tool_sequence": INGESTION_EXECUTION_REQUIRED_TOOL_SEQUENCE,
            },
            ensure_ascii=False,
        )

    def _recover_execution_output_from_tool_trace(
        self,
        *,
        tool_trace: list[dict[str, Any]],
        session: IngestionExecutionSession,
    ) -> IngestionExecutionAgentOutput | None:
        execute_item = self._latest_tool_trace_item(
            tool_trace,
            names={"execute_approved_write"},
        )
        if execute_item is None:
            return None

        if isinstance(execute_item.get("result"), dict):
            result = dict(execute_item["result"])
            try:
                return IngestionExecutionAgentOutput.model_validate(
                    {
                        "status": "executed",
                        "approved_action": session.approved_action,
                        "target_table": session.target_table,
                        "reasoning": (
                            "Recovered from tool trace because execute_approved_write completed "
                            "before the agent returned structured output."
                        ),
                        "executed_sql": str(
                            result.get("executed_sql") or session.executed_sql or ""
                        ).strip(),
                        "receipt": result,
                        "risks": [],
                    }
                )
            except Exception:
                return None

        error_payload = execute_item.get("error") if isinstance(execute_item.get("error"), dict) else {}
        if not error_payload:
            return None
        try:
            return IngestionExecutionAgentOutput.model_validate(
                {
                    "status": "blocked",
                    "approved_action": session.approved_action,
                    "target_table": session.target_table,
                    "reasoning": str(error_payload.get("error") or "Execution tool failed").strip(),
                    "executed_sql": str(session.executed_sql or "").strip(),
                    "receipt": {},
                    "risks": [],
                }
            )
        except Exception:
            return None

    def _run_planning_agent_loop(
        self,
        *,
        conn: sqlite3.Connection,
        workspace_id: str,
        job_id: str,
        upload_id: str,
        requested_by: str,
        conversation_id: str | None,
        message: str | None,
    ) -> tuple[IngestionAgentPlanOutput, list[dict[str, Any]]]:
        settings = get_settings()
        auth_token_source = settings.anthropic_auth_token or settings.ai_api_key
        if not auth_token_source.strip() or not settings.ai_model.strip():
            raise IngestionPlanningError(
                code="INGESTION_AI_NOT_CONFIGURED",
                message="Claude Agent SDK credentials are not configured for ingestion planning",
                status_code=503,
            )

        tool_trace_snapshot: list[dict[str, Any]] = []

        async def runner() -> tuple[IngestionAgentPlanOutput, list[dict[str, Any]]]:
            return await self._run_planning_agent_loop_async(
                conn=conn,
                workspace_id=workspace_id,
                job_id=job_id,
                upload_id=upload_id,
                requested_by=requested_by,
                conversation_id=conversation_id,
                message=message,
                tool_trace_sink=tool_trace_snapshot,
            )

        try:
            return anyio.run(runner)
        except IngestionPlanningError as exc:
            if exc.code in RECOVERABLE_PLANNING_OUTPUT_CODES:
                recovered = (
                    self._recover_proposal_from_tool_trace(tool_trace=tool_trace_snapshot)
                    or self._recover_catalog_setup_from_tool_trace(tool_trace=tool_trace_snapshot)
                )
                if recovered is not None:
                    logger.warning(
                        "ingestion_agent_output_recovered_from_tool_trace job_id=%s reason=%s",
                        job_id,
                        exc.code.lower(),
                    )
                    return recovered, tool_trace_snapshot
            raise
        except TimeoutError as exc:
            recovered = self._recover_agent_output_from_tool_trace(tool_trace=tool_trace_snapshot)
            if recovered is not None:
                logger.warning(
                    "ingestion_agent_output_recovered_from_tool_trace job_id=%s reason=timeout_outer",
                    job_id,
                )
                return recovered, tool_trace_snapshot
            raise IngestionPlanningError(
                code="INGESTION_AI_UNAVAILABLE",
                message=(
                    "Claude Agent SDK timed out during ingestion planning "
                    f"(>{settings.agent_timeout_seconds}s)"
                ),
                status_code=503,
            ) from exc
        except ClaudeSDKError as exc:
            recovered = self._recover_agent_output_from_tool_trace(tool_trace=tool_trace_snapshot)
            if recovered is not None:
                logger.warning(
                    "ingestion_agent_output_recovered_from_tool_trace job_id=%s reason=claude_sdk_error",
                    job_id,
                )
                return recovered, tool_trace_snapshot
            suffix = str(exc).strip()
            detail = f": {suffix}" if suffix else ""
            raise IngestionPlanningError(
                code="INGESTION_AI_UNAVAILABLE",
                message=f"Claude Agent SDK is unavailable for ingestion planning{detail}",
                status_code=503,
            ) from exc
        except Exception as exc:
            raise IngestionPlanningError(
                code="INGESTION_AI_UNAVAILABLE",
                message=f"Claude Agent SDK failed during ingestion planning: {exc}",
                status_code=503,
            ) from exc

    async def _run_planning_agent_loop_async(
        self,
        *,
        conn: sqlite3.Connection,
        workspace_id: str,
        job_id: str,
        upload_id: str,
        requested_by: str,
        conversation_id: str | None,
        message: str | None,
        tool_trace_sink: list[dict[str, Any]] | None = None,
        event_queue: asyncio.Queue | None = None,
    ) -> tuple[IngestionAgentPlanOutput, list[dict[str, Any]]]:
        settings = get_settings()
        tool_trace = tool_trace_sink if tool_trace_sink is not None else []
        options = self._build_ingestion_sdk_options(
            conn=conn,
            job_id=job_id,
            tool_trace=tool_trace,
            event_queue=event_queue,
        )
        prompt = self._build_ingestion_agent_prompt(
            workspace_id=workspace_id,
            job_id=job_id,
            upload_id=upload_id,
            requested_by=requested_by,
            message=message,
        )
        raw_output: dict[str, Any] | None = None
        text_blocks: list[str] = []
        session_id = conversation_id or f"ingestion-{job_id}"

        try:
            with anyio.fail_after(settings.agent_timeout_seconds):
                async with ClaudeSDKClient(options=options) as client:
                    await client.query(prompt, session_id=session_id)
                    async for sdk_message in client.receive_response():
                        if event_queue is not None and isinstance(sdk_message, AssistantMessage):
                            for block in sdk_message.content:
                                if isinstance(block, TextBlock) and block.text:
                                    event_queue.put_nowait(("planning", {
                                        "job_id": job_id,
                                        "text": block.text,
                                    }))
                        candidate = self._consume_ingestion_sdk_message(
                            message=sdk_message,
                            text_blocks=text_blocks,
                        )
                        if candidate is not None:
                            raw_output = candidate
        except TimeoutError:
            raise IngestionPlanningError(
                code="INGESTION_AI_UNAVAILABLE",
                message=(
                    "Write Ingestion Agent timed out. Please retry — "
                    f"the agent must complete within {settings.agent_timeout_seconds}s."
                ),
                status_code=503,
            )

        if raw_output is None and text_blocks:
            raw_output = _decode_json_dict("\n".join(text_blocks))
        if raw_output is None:
            raise IngestionPlanningError(
                code="AGENT_STRUCTURED_OUTPUT_MISSING",
                message="Write Ingestion Agent did not return structured output",
                status_code=502,
            )
        self._normalize_raw_plan_output(raw_output)
        self._inject_human_approval_if_missing(raw_output)
        self._inject_agent_guess_if_missing(raw_output, tool_trace=tool_trace)
        try:
            output = IngestionAgentPlanOutput.model_validate(raw_output)
        except Exception as exc:
            logger.warning(
                "ingestion_agent_output_invalid job_id=%s raw_keys=%s validation_error=%s",
                job_id,
                list(raw_output.keys()) if isinstance(raw_output, dict) else type(raw_output).__name__,
                str(exc),
            )
            raise IngestionPlanningError(
                code="AGENT_STRUCTURED_OUTPUT_INVALID",
                message="Write Ingestion Agent returned invalid structured output",
                status_code=502,
            ) from exc
        return output, tool_trace

    @staticmethod
    def _inject_human_approval_if_missing(raw_output: dict[str, Any]) -> None:
        if "human_approval" in raw_output and isinstance(raw_output["human_approval"], dict):
            return
        status = str(raw_output.get("status", "")).strip()
        if status == "awaiting_catalog_setup":
            raw_output["human_approval"] = {
                "required": True,
                "mechanism": "catalog_setup_card",
                "stage": "catalog_setup",
                "question": "Please confirm the catalog setup before proceeding.",
                "options": list(CATALOG_SETUP_APPROVAL_OPTIONS),
                "recommended_option": "confirm_catalog_setup",
            }
        else:
            proposal = raw_output.get("proposal") if isinstance(raw_output.get("proposal"), dict) else {}
            recommended = str(proposal.get("recommended_action") or "update_existing").strip()
            if recommended not in DEFAULT_ACTION_OPTIONS:
                recommended = "update_existing"
            raw_output["human_approval"] = {
                "required": True,
                "mechanism": "frontend_approval_card",
                "stage": "proposal_approval",
                "question": (
                    proposal.get("explanation")
                    or "Please review the proposed ingestion action."
                )[:300],
                "options": list(DEFAULT_ACTION_OPTIONS),
                "recommended_option": recommended,
            }

    @staticmethod
    def _inject_agent_guess_if_missing(
        raw_output: dict[str, Any],
        *,
        tool_trace: list[dict[str, Any]],
    ) -> None:
        existing = raw_output.get("agent_guess")
        if isinstance(existing, dict):
            bt = str(existing.get("business_type") or "").strip()
            if not bt:
                existing["business_type"] = "other"
            raw_conf = existing.get("confidence")
            try:
                conf = float(raw_conf)  # type: ignore[arg-type]
                if not (0.0 <= conf <= 1.0):
                    raise ValueError
            except (TypeError, ValueError):
                existing["confidence"] = 0.5
            return

        inferred_type = "other"
        for item in reversed(tool_trace):
            result = item.get("result") if isinstance(item.get("result"), dict) else {}
            bt = str(result.get("business_type") or "").strip()
            if bt:
                inferred_type = bt
                break
        raw_output["agent_guess"] = {
            "business_type": inferred_type,
            "confidence": 0.5,
            "reasoning": "Inferred from upload structure; agent did not provide an explicit guess.",
        }

    @staticmethod
    def _normalize_raw_plan_output(raw_output: dict[str, Any]) -> None:
        """Coerce field-level issues before Pydantic validation.

        Only execution-coupled enums (write_mode, time_grain, recommended_action)
        are normalised against a fixed set, because downstream SQL generation
        branches on those exact values. The free-form `business_type` is no
        longer coerced — the agent is trusted to propose whatever value best
        describes the upload.
        """
        _VALID_STATUSES = {"awaiting_catalog_setup", "awaiting_user_approval"}
        _VALID_ACTIONS = {"update_existing", "time_partitioned_new_table", "new_table", "cancel"}
        _VALID_TIME_GRAINS = {"none", "month", "quarter", "year"}
        _VALID_WRITE_MODES = {"update_existing", "time_partitioned_new_table", "new_table"}

        # Normalize status
        status = str(raw_output.get("status") or "").strip()
        if status not in _VALID_STATUSES:
            # Heuristic: if there's a suggested_catalog_seed or setup_questions, treat as setup
            if raw_output.get("suggested_catalog_seed") or raw_output.get("setup_questions"):
                raw_output["status"] = "awaiting_catalog_setup"
            else:
                raw_output["status"] = "awaiting_user_approval"

        # Normalize suggested_catalog_seed if present
        seed = raw_output.get("suggested_catalog_seed")
        if isinstance(seed, dict):
            bt = str(seed.get("business_type") or "").strip()
            if not bt:
                seed["business_type"] = "other"
            wm = str(seed.get("write_mode") or "new_table").strip()
            if wm not in _VALID_WRITE_MODES:
                seed["write_mode"] = "new_table"
            tg = str(seed.get("time_grain") or "none").strip()
            if tg not in _VALID_TIME_GRAINS:
                seed["time_grain"] = "none"
            if not seed.get("table_name"):
                seed["table_name"] = "uploaded_table"
            if not seed.get("human_label"):
                seed["human_label"] = str(seed["table_name"]).replace("_", " ").title()

        # Normalize proposal if present
        proposal = raw_output.get("proposal")
        if isinstance(proposal, dict):
            bt = str(proposal.get("business_type") or "").strip()
            if not bt:
                proposal["business_type"] = "other"
            ra = str(proposal.get("recommended_action") or "update_existing").strip()
            if ra not in _VALID_ACTIONS:
                proposal["recommended_action"] = "update_existing"
            tg = str(proposal.get("time_grain") or "none").strip()
            if tg not in _VALID_TIME_GRAINS:
                proposal["time_grain"] = "none"
            # diff_preview is required in IngestionProposalPayload; inject zeros if missing
            if not isinstance(proposal.get("diff_preview"), dict):
                proposal["diff_preview"] = {
                    "predicted_insert_count": 0,
                    "predicted_update_count": 0,
                    "predicted_conflict_count": 0,
                }
            raw_conf = proposal.get("confidence")
            try:
                conf = float(raw_conf)  # type: ignore[arg-type]
                if not (0.0 <= conf <= 1.0):
                    raise ValueError
            except (TypeError, ValueError):
                proposal["confidence"] = 0.5

    def _build_ingestion_sdk_options(
        self,
        *,
        conn: sqlite3.Connection,
        job_id: str,
        tool_trace: list[dict[str, Any]],
        event_queue: asyncio.Queue | None = None,
    ) -> ClaudeAgentOptions:
        settings = get_settings()

        async def can_use_tool(
            tool_name: str,
            input_data: dict[str, Any],
            permission_context: Any,
        ) -> PermissionResultAllow | PermissionResultDeny:
            _ = (input_data, permission_context)
            canonical_name = _canonical_ingestion_tool_name(tool_name)
            if canonical_name in INGESTION_SDK_TOOL_NAMES:
                return PermissionResultAllow()
            return PermissionResultDeny(
                message=f"Tool '{tool_name}' is outside the Write Ingestion Agent tool surface."
            )

        server = create_sdk_mcp_server(
            name=INGESTION_SDK_MCP_SERVER_NAME,
            version="1.0.0",
            tools=self._build_ingestion_sdk_tools(
                conn=conn,
                job_id=job_id,
                tool_trace=tool_trace,
                event_queue=event_queue,
            ),
        )
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
            system_prompt=INGESTION_AGENT_SYSTEM_PROMPT,
            mcp_servers={INGESTION_SDK_MCP_SERVER_NAME: server},
            can_use_tool=can_use_tool,
            permission_mode="default",
            max_turns=max(settings.agent_max_tool_steps, MIN_INGESTION_AGENT_MAX_TURNS),
            model=model,
            cwd=str(Path.cwd()),
            env=env,
            output_format={
                "type": "json_schema",
                "schema": IngestionAgentPlanOutput.model_json_schema(),
            },
        )

    def _build_ingestion_sdk_tools(
        self,
        *,
        conn: sqlite3.Connection,
        job_id: str,
        tool_trace: list[dict[str, Any]],
        event_queue: asyncio.Queue | None = None,
    ) -> list[Any]:
        sdk_tools: list[Any] = []
        for definition in INGESTION_AGENT_TOOL_DEFINITIONS:
            tool_name = str(definition["name"])
            description = str(definition["description"])
            input_schema = definition["parameters"]
            is_read_only = bool(definition.get("read_only", True))
            annotations = ToolAnnotations(
                readOnlyHint=is_read_only,
                destructiveHint=False,
                idempotentHint=is_read_only,
                openWorldHint=False,
            )

            async def handler(args: dict[str, Any], _tool_name: str = tool_name) -> dict[str, Any]:
                step_id = uuid.uuid4().hex
                started_at = time.time()
                if event_queue is not None:
                    event_queue.put_nowait(("tool_use", {
                        "job_id": job_id,
                        "tool_name": _tool_name,
                        "arguments": args,
                        "step_id": step_id,
                        "started_at": started_at,
                    }))
                try:
                    result = self._invoke_ingestion_sdk_tool(
                        conn=conn,
                        job_id=job_id,
                        tool_trace=tool_trace,
                        tool_name=_tool_name,
                        arguments=args,
                    )
                    completed_at = time.time()
                    if event_queue is not None:
                        event_queue.put_nowait(("tool_result", {
                            "job_id": job_id,
                            "tool_name": _tool_name,
                            "status": "success",
                            "result": result,
                            "step_id": step_id,
                            "started_at": started_at,
                            "completed_at": completed_at,
                        }))
                    return {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(result, ensure_ascii=False, default=str),
                            }
                        ],
                        "is_error": False,
                    }
                except Exception as exc:
                    completed_at = time.time()
                    if event_queue is not None:
                        event_queue.put_nowait(("tool_result", {
                            "job_id": job_id,
                            "tool_name": _tool_name,
                            "status": "error",
                            "error": str(exc),
                            "step_id": step_id,
                            "started_at": started_at,
                            "completed_at": completed_at,
                        }))
                    raise

            sdk_tools.append(
                tool(
                    tool_name,
                    description,
                    input_schema,
                    annotations=annotations,
                )(handler)
            )
        return sdk_tools

    def _invoke_ingestion_sdk_tool(
        self,
        *,
        conn: sqlite3.Connection,
        job_id: str,
        tool_trace: list[dict[str, Any]],
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        canonical_name = _canonical_ingestion_tool_name(tool_name)
        if canonical_name not in INGESTION_SDK_TOOL_NAMES:
            raise IngestionPlanningError(
                code="INGESTION_TOOL_NOT_ALLOWED",
                message=f"Tool '{tool_name}' is outside the Write Ingestion Agent tool surface",
                status_code=403,
            )
        if not isinstance(arguments, dict):
            arguments = {}
        return self._run_tool(
            conn=conn,
            job_id=job_id,
            trace=tool_trace,
            name=canonical_name,
            arguments=arguments,
            handler=lambda: self._handle_ingestion_tool(
                conn=conn,
                job_id=job_id,
                tool_name=canonical_name,
                arguments=arguments,
            ),
        )

    def _handle_ingestion_tool(
        self,
        *,
        conn: sqlite3.Connection,
        job_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        if tool_name == "get_workspace_catalog":
            return self._tool_get_workspace_catalog(
                conn=conn,
                workspace_id=str(arguments.get("workspace_id", "")),
            )
        if tool_name == "list_existing_tables":
            return self._tool_list_existing_tables(
                conn=conn,
                workspace_id=str(arguments.get("workspace_id", "")),
            )
        if tool_name == "inspect_upload":
            return self._tool_inspect_upload(
                conn=conn,
                upload_id=str(arguments.get("upload_id", "")),
            )
        if tool_name == "describe_table_schema":
            return self._tool_describe_table_schema_by_name(
                conn=conn,
                workspace_id=str(arguments.get("workspace_id", "")),
                table_name=str(arguments.get("table_name", "")),
            )
        if tool_name == "build_diff_preview":
            upload_info = self._tool_inspect_upload(
                conn=conn,
                upload_id=str(arguments.get("upload_id", "")),
            )
            raw_mapping = arguments.get("column_mapping")
            column_mapping = {
                str(key): str(value)
                for key, value in raw_mapping.items()
                if str(key).strip() and str(value).strip()
            } if isinstance(raw_mapping, dict) else None
            return self._tool_build_diff_preview(
                conn=conn,
                workspace_id=str(arguments.get("workspace_id", "")),
                upload_info=upload_info,
                target_table=str(arguments.get("target_table", "")),
                match_columns=[
                    str(item).strip().lower()
                    for item in arguments.get("match_columns", [])
                    if str(item).strip()
                ],
                action_mode=str(arguments.get("action_mode", "")),
                column_mapping=column_mapping,
            )
        if tool_name == "generate_write_sql_draft":
            return self._tool_generate_write_sql_draft(
                workspace_id=str(arguments.get("workspace_id", "")),
                job_id=str(arguments.get("job_id", job_id)),
                target_table=str(arguments.get("target_table", "")),
                action_mode=str(arguments.get("action_mode", "")),
                match_columns=[
                    str(item).strip().lower()
                    for item in arguments.get("match_columns", [])
                    if str(item).strip()
                ],
            )
        if tool_name == "create_catalog_entry":
            return self._tool_create_catalog_entry(
                conn=conn,
                job_id=job_id,
                arguments=arguments,
            )
        raise IngestionPlanningError(
            code="INGESTION_TOOL_NOT_ALLOWED",
            message=f"Unsupported ingestion tool: {tool_name}",
            status_code=403,
        )

    @staticmethod
    def _build_ingestion_agent_prompt(
        *,
        workspace_id: str,
        job_id: str,
        upload_id: str,
        requested_by: str,
        message: str | None,
    ) -> str:
        user_instruction_hint = (
            "IMPORTANT: The user has provided a custom instruction: "
            f'"{message}". '
            "Search get_workspace_catalog and list_existing_tables results for a table whose "
            "human_label, table_name, or description matches the user's intent. "
            "If a matching existing table is found, set target_table to that table's name and "
            "use update_existing as the recommended action — do NOT call create_catalog_entry. "
            "Only create a new catalog entry if no matching table exists."
        ) if message and message.strip() else None
        prompt: dict[str, Any] = {
            "task": "Build the next write ingestion lifecycle output.",
            "workspace_id": workspace_id,
            "job_id": job_id,
            "upload_id": upload_id,
            "requested_by": requested_by,
            "user_message": message or "",
            "required_tool_sequence": [
                "inspect_upload",
                "Read inspect_upload.sheet_summary.workbook_structure and top_rows_preview to classify each sheet (flat_table vs human_readable_matrix vs mixed_or_unknown). If the layout is not a clean flat table, return awaiting_catalog_setup with a proposed decomposition into multiple analysis-ready tables — do NOT force a non-flat sheet into a single table",
                "All table_name, human_label, business_type, and description values must be derived from this upload's observed content. NEVER reuse names, labels, or descriptions from a prior example or the system prompt",
                "get_workspace_catalog",
                "list_existing_tables",
                "IF user_message references an existing table by name or label → use that table as target_table with update_existing action; skip create_catalog_entry",
                "IF no matching existing catalog entry → call create_catalog_entry to create one (infer schema from upload columns)",
                "describe_table_schema — verify the catalog entry exists; if {found:false} after create_catalog_entry → return awaiting_catalog_setup",
                "build_diff_preview only when describe_table_schema returned {found:true}; pass workspace_id, upload_id, target_table, action_mode, match_columns, and the inferred column_mapping",
                "generate_write_sql_draft only when describe_table_schema returned {found:true}",
                "return awaiting_user_approval with complete proposal; proposal.candidate_actions and human_approval.options must match build_diff_preview.candidate_actions",
            ],
            "available_proposal_actions": DEFAULT_ACTION_OPTIONS,
        }
        if user_instruction_hint:
            prompt["user_instruction_guidance"] = user_instruction_hint
        return json.dumps(prompt, ensure_ascii=False)

    @staticmethod
    def _consume_ingestion_sdk_message(
        *,
        message: Any,
        text_blocks: list[str],
    ) -> dict[str, Any] | None:
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock) and block.text:
                    text_blocks.append(block.text)
                elif isinstance(block, ToolUseBlock):
                    continue
            return None
        if isinstance(message, UserMessage) and isinstance(message.content, list):
            for block in message.content:
                if isinstance(block, ToolResultBlock):
                    continue
            return None
        if isinstance(message, ResultMessage):
            if message.is_error:
                error_suffix = ""
                if message.errors:
                    error_suffix = f": {'; '.join(str(item) for item in message.errors)}"
                raise IngestionPlanningError(
                    code="INGESTION_AI_UNAVAILABLE",
                    message=(
                        "Write Ingestion Agent ended before producing structured output "
                        f"({message.subtype}, turns={message.num_turns}){error_suffix}"
                    ),
                    status_code=503,
                )
            if isinstance(message.structured_output, dict):
                return message.structured_output
            if message.result:
                return _decode_json_dict(message.result)
        return None

    def _assert_human_approval_requested(
        self,
        *,
        agent_output: IngestionAgentPlanOutput,
        tool_trace: list[dict[str, Any]],
        expected_stage: str,
    ) -> None:
        approval = agent_output.human_approval
        if not approval.required or approval.stage != expected_stage:
            raise IngestionPlanningError(
                code="HUMAN_APPROVAL_REQUIRED",
                message="Agent output must require human approval for the next step",
                status_code=502,
            )
        allowed_options = (
            CATALOG_SETUP_APPROVAL_OPTIONS
            if expected_stage == "catalog_setup"
            else DEFAULT_ACTION_OPTIONS
        )
        if not approval.options or any(option not in allowed_options for option in approval.options):
            raise IngestionPlanningError(
                code="HUMAN_APPROVAL_OPTIONS_INVALID",
                message="Agent human approval options are outside the designed choices",
                status_code=502,
            )
        if approval.recommended_option and approval.recommended_option not in approval.options:
            raise IngestionPlanningError(
                code="HUMAN_APPROVAL_RECOMMENDATION_INVALID",
                message="Agent human approval recommendation is not in approval options",
                status_code=502,
            )
        for item in tool_trace:
            if item.get("tool_name") not in _LEGACY_APPROVAL_TOOL_ALIASES:
                continue
            arguments = item.get("arguments")
            if isinstance(arguments, dict) and arguments.get("stage") == expected_stage:
                return
        raise IngestionPlanningError(
            code="HUMAN_APPROVAL_NOT_REQUESTED",
            message=(
                "Agent must call AskUserQuestion before returning the next step "
                "(request_human_approval is accepted as a legacy alias)"
            ),
            status_code=502,
        )

    @staticmethod
    def _normalize_agent_proposal(proposal: IngestionProposalPayload) -> IngestionProposalPayload:
        candidate_actions = list(proposal.candidate_actions)
        if any(action not in DEFAULT_ACTION_OPTIONS for action in candidate_actions):
            raise IngestionPlanningError(
                code="AGENT_PROPOSAL_ACTION_INVALID",
                message="Agent proposal contains an unsupported candidate action",
                status_code=502,
            )
        if proposal.recommended_action not in candidate_actions:
            raise IngestionPlanningError(
                code="AGENT_PROPOSAL_RECOMMENDATION_INVALID",
                message="Agent recommended action must be present in candidate_actions",
                status_code=502,
            )
        if "cancel" not in candidate_actions:
            raise IngestionPlanningError(
                code="AGENT_PROPOSAL_CANCEL_REQUIRED",
                message="Agent proposal candidate_actions must include cancel",
                status_code=502,
            )
        return proposal

    def _reconcile_plan_output_with_tool_trace(
        self,
        *,
        conn: sqlite3.Connection | None = None,
        agent_output: IngestionAgentPlanOutput,
        tool_trace: list[dict[str, Any]],
    ) -> IngestionAgentPlanOutput:
        if agent_output.proposal is None:
            return agent_output

        output_payload = agent_output.model_dump(mode="json")
        proposal = output_payload.get("proposal")
        if not isinstance(proposal, dict):
            return agent_output

        upload_info = self._latest_tool_result(tool_trace, "inspect_upload")
        upload_columns, _normalized_columns, structured_column_mode = self._proposal_columns_from_upload_info(
            upload_info
        )
        traced_column_mapping = self._column_mapping_from_build_diff_trace(
            tool_trace=tool_trace,
            upload_columns=upload_columns,
            structured_column_mode=structured_column_mode,
        )
        if traced_column_mapping:
            proposal["column_mapping"] = traced_column_mapping

        diff_result = self._latest_tool_result(tool_trace, "build_diff_preview")
        recomputed_diff = self._recompute_diff_preview_from_proposal(
            conn=conn,
            proposal=proposal,
            tool_trace=tool_trace,
        )
        if recomputed_diff:
            diff_result = recomputed_diff
        if diff_result:
            proposal["diff_preview"] = {
                "predicted_insert_count": self._as_non_negative_int(
                    diff_result.get("predicted_insert_count")
                ),
                "predicted_update_count": self._as_non_negative_int(
                    diff_result.get("predicted_update_count")
                ),
                "predicted_conflict_count": self._as_non_negative_int(
                    diff_result.get("predicted_conflict_count")
                ),
            }

        candidate_actions = self._valid_action_list(diff_result.get("candidate_actions"))
        if not candidate_actions:
            candidate_actions = self._valid_action_list(proposal.get("candidate_actions"))

        if not candidate_actions:
            target_table = str(proposal.get("target_table") or "").strip().lower()
            physical_tables = {
                str(item).strip().lower()
                for item in self._latest_tool_result(tool_trace, "list_existing_tables").get("workspace_tables", [])
                if str(item).strip()
            }
            candidate_actions = self._candidate_actions_for_target_state(
                target_exists=bool(target_table and target_table in physical_tables),
                requested_action=str(proposal.get("recommended_action") or ""),
            )

        if "cancel" not in candidate_actions:
            candidate_actions.append("cancel")

        recommended_action = str(
            diff_result.get("recommended_action") or proposal.get("recommended_action") or ""
        ).strip()
        if recommended_action not in candidate_actions:
            recommended_action = next(
                (item for item in candidate_actions if item != "cancel"),
                "cancel",
            )

        proposal["candidate_actions"] = candidate_actions
        proposal["recommended_action"] = recommended_action

        human_approval = output_payload.get("human_approval")
        if isinstance(human_approval, dict) and human_approval.get("stage") == "proposal_approval":
            human_approval["options"] = list(candidate_actions)
            human_approval["recommended_option"] = recommended_action

        return IngestionAgentPlanOutput.model_validate(output_payload)

    def _recompute_diff_preview_from_proposal(
        self,
        *,
        conn: sqlite3.Connection | None,
        proposal: dict[str, Any],
        tool_trace: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if conn is None:
            return {}
        upload_info = self._latest_tool_result(tool_trace, "inspect_upload")
        if not upload_info:
            return {}
        target_table = str(proposal.get("target_table") or "").strip()
        if not target_table:
            return {}
        workspace_id = ""
        for tool_name in ("get_workspace_catalog", "list_existing_tables", "describe_table_schema"):
            item = self._latest_tool_trace_item(tool_trace, names={tool_name})
            arguments = item.get("arguments") if isinstance(item, dict) else {}
            if isinstance(arguments, dict):
                workspace_id = str(arguments.get("workspace_id") or "").strip()
                if workspace_id:
                    break
        if not workspace_id:
            return {}
        raw_mapping = proposal.get("column_mapping")
        column_mapping = {
            str(key): str(value)
            for key, value in raw_mapping.items()
            if str(key).strip() and str(value).strip()
        } if isinstance(raw_mapping, dict) else {}
        try:
            return self._tool_build_diff_preview(
                conn=conn,
                workspace_id=workspace_id,
                upload_info=upload_info,
                target_table=target_table,
                match_columns=[
                    str(item).strip().lower()
                    for item in proposal.get("match_columns", [])
                    if str(item).strip()
                ],
                action_mode=str(proposal.get("recommended_action") or ""),
                column_mapping=column_mapping,
            )
        except Exception as exc:
            logger.warning(
                "ingestion_diff_preview_recompute_failed target_table=%s error=%s",
                target_table,
                exc,
            )
            return {}

    @staticmethod
    def _valid_action_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        result: list[str] = []
        for item in value:
            action = str(item).strip()
            if action in DEFAULT_ACTION_OPTIONS and action not in result:
                result.append(action)
        return result

    @staticmethod
    def _as_non_negative_int(value: Any) -> int:
        try:
            return max(int(value), 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _latest_tool_result(tool_trace: list[dict[str, Any]], tool_name: str) -> dict[str, Any]:
        for item in reversed(tool_trace):
            if item.get("tool_name") == tool_name and isinstance(item.get("result"), dict):
                return item["result"]
        return {}

    @staticmethod
    def _latest_tool_trace_item(
        tool_trace: list[dict[str, Any]],
        *,
        names: set[str] | frozenset[str] | tuple[str, ...] | list[str],
    ) -> dict[str, Any] | None:
        name_set = set(names)
        for item in reversed(tool_trace):
            if item.get("tool_name") in name_set:
                return item
        return None

    def _recover_agent_output_from_tool_trace(
        self,
        *,
        tool_trace: list[dict[str, Any]],
    ) -> IngestionAgentPlanOutput | None:
        approval_item = self._latest_tool_trace_item(
            tool_trace,
            names=_LEGACY_APPROVAL_TOOL_ALIASES,
        )
        if approval_item is None:
            return None

        arguments = approval_item.get("arguments") if isinstance(approval_item.get("arguments"), dict) else {}
        result = approval_item.get("result") if isinstance(approval_item.get("result"), dict) else {}
        stage = str(result.get("stage") or arguments.get("stage") or "").strip()
        if stage not in {"catalog_setup", "proposal_approval"}:
            return None

        if stage == "catalog_setup":
            allowed_options = list(CATALOG_SETUP_APPROVAL_OPTIONS)
            default_recommended = "confirm_catalog_setup"
            default_mechanism = "catalog_setup_card"
        else:
            allowed_options = list(DEFAULT_ACTION_OPTIONS)
            default_recommended = "update_existing"
            default_mechanism = "frontend_approval_card"

        raw_options = result.get("options") if isinstance(result.get("options"), list) else arguments.get("options")
        options = [
            str(item).strip()
            for item in (raw_options or [])
            if str(item).strip() in allowed_options
        ]
        if not options:
            options = list(allowed_options)

        recommended_option = str(
            result.get("recommended_option") or arguments.get("recommended_option") or ""
        ).strip()
        if recommended_option not in options:
            recommended_option = default_recommended if default_recommended in options else options[0]

        question = str(result.get("question") or arguments.get("question") or "").strip()
        if not question:
            question = (
                "Please confirm the catalog setup before proceeding."
                if stage == "catalog_setup"
                else "Please choose the ingestion action."
            )
        if len(question) > 300:
            question = question[:300].rstrip()

        mechanism = str(result.get("mechanism") or "").strip() or default_mechanism
        human_approval_payload = {
            "required": True,
            "mechanism": mechanism,
            "stage": stage,
            "question": question,
            "options": options,
            "recommended_option": recommended_option,
        }

        schema = self._latest_tool_result(tool_trace, "describe_table_schema")
        upload_info = self._latest_tool_result(tool_trace, "inspect_upload")
        upload_columns, normalized_columns, structured_column_mode = self._proposal_columns_from_upload_info(
            upload_info
        )

        business_type = str(schema.get("business_type") or "other").strip()
        if business_type not in {"roster", "project_progress", "attendance", "other"}:
            business_type = "other"
        agent_guess_payload = {
            "business_type": business_type,
            "confidence": 0.55,
            "reasoning": (
                "Recovered from tool trace because the agent called AskUserQuestion "
                "but did not return structured output before timeout."
            ),
        }

        if stage == "catalog_setup":
            table_name = str(schema.get("table_name") or "employee_roster").strip().lower()
            if not SAFE_IDENTIFIER_RE.match(table_name):
                table_name = self._normalize_identifier(table_name) or "employee_roster"

            human_label = str(schema.get("human_label") or table_name.replace("_", " ").title()).strip()
            if not human_label:
                human_label = table_name.replace("_", " ").title()

            write_mode = str(schema.get("write_mode") or "new_table").strip()
            if write_mode not in {"update_existing", "time_partitioned_new_table", "new_table"}:
                write_mode = "new_table"
            time_grain = str(schema.get("time_grain") or "none").strip()
            if time_grain not in {"none", "month", "quarter", "year"}:
                time_grain = "none"

            purpose_hint = str(schema.get("description") or "").strip()
            if not purpose_hint:
                source_columns = "、".join(upload_columns[:6]) if upload_columns else "当前上传数据"
                purpose_hint = f"Use this table for uploads containing {source_columns}."

            try:
                return IngestionAgentPlanOutput.model_validate(
                    {
                        "status": "awaiting_catalog_setup",
                        "agent_guess": agent_guess_payload,
                        "setup_questions": [
                            {
                                "question_id": "description",
                                "title": "Describe what this table should be used for",
                                "options": [],
                            }
                        ],
                        "suggested_catalog_seed": {
                            "business_type": business_type,
                            "table_name": table_name,
                            "human_label": human_label,
                            "write_mode": write_mode,
                            "time_grain": time_grain,
                            "primary_keys": [],
                            "match_columns": [],
                            "is_active_target": True,
                            "description": purpose_hint,
                        },
                        "human_approval": human_approval_payload,
                    }
                )
            except Exception:
                return None

        diff_preview_result = self._latest_tool_result(tool_trace, "build_diff_preview")
        draft_trace = self._latest_tool_trace_item(
            tool_trace,
            names={"generate_write_sql_draft"},
        )
        draft_arguments = draft_trace.get("arguments") if isinstance(draft_trace, dict) else {}
        sql_payload = self._latest_tool_result(tool_trace, "generate_write_sql_draft")

        target_table = str(draft_arguments.get("target_table") or schema.get("table_name") or "").strip().lower()
        if target_table and not SAFE_IDENTIFIER_RE.match(target_table):
            target_table = self._normalize_identifier(target_table)
        if not target_table:
            target_table = None

        candidate_actions = [item for item in options if item in DEFAULT_ACTION_OPTIONS]
        if "cancel" not in candidate_actions:
            candidate_actions.append("cancel")
        recommended_action = recommended_option if recommended_option in candidate_actions else candidate_actions[0]

        match_columns: list[str] = []
        for item in (
            draft_arguments.get("match_columns")
            if isinstance(draft_arguments.get("match_columns"), list)
            else []
        ):
            normalized = self._normalize_identifier(str(item))
            if normalized and normalized not in match_columns:
                match_columns.append(normalized)
        if not match_columns:
            for item in (
                schema.get("match_columns")
                if isinstance(schema.get("match_columns"), list)
                else []
            ):
                normalized = self._normalize_identifier(str(item))
                if normalized and normalized not in match_columns:
                    match_columns.append(normalized)
        if not match_columns and normalized_columns:
            match_columns = [normalized_columns[0]]

        time_grain = str(schema.get("time_grain") or "none").strip()
        if time_grain not in {"none", "month", "quarter", "year"}:
            time_grain = "none"

        def _as_non_negative_int(value: Any) -> int:
            try:
                return max(int(value), 0)
            except (TypeError, ValueError):
                return 0

        column_mapping = (
            self._column_mapping_from_build_diff_trace(
                tool_trace=tool_trace,
                upload_columns=upload_columns,
                structured_column_mode=structured_column_mode,
            )
            or self._fallback_column_mapping_from_upload_columns(
                upload_columns=upload_columns,
                structured_column_mode=structured_column_mode,
            )
        )

        proposal_payload = {
            "business_type": business_type,
            "confidence": 0.6,
            "recommended_action": recommended_action,
            "candidate_actions": candidate_actions,
            "target_table": target_table,
            "time_grain": time_grain,
            "match_columns": match_columns,
            "column_mapping": column_mapping,
            "diff_preview": {
                "predicted_insert_count": _as_non_negative_int(
                    diff_preview_result.get("predicted_insert_count")
                ),
                "predicted_update_count": _as_non_negative_int(
                    diff_preview_result.get("predicted_update_count")
                ),
                "predicted_conflict_count": _as_non_negative_int(
                    diff_preview_result.get("predicted_conflict_count")
                ),
            },
            "risks": [
                "Recovered from AskUserQuestion fallback after SDK timeout; review before approval."
            ],
            "explanation": (
                "Recovered a proposal from tool trace because the agent did not return "
                "structured output before timeout."
            ),
            "sql_draft": str(sql_payload.get("sql_draft") or "").strip(),
            "requires_catalog_setup": False,
        }
        try:
            return IngestionAgentPlanOutput.model_validate(
                {
                    "status": "awaiting_user_approval",
                    "agent_guess": agent_guess_payload,
                    "proposal": proposal_payload,
                    "human_approval": human_approval_payload,
                }
            )
        except Exception:
            return None

    def _recover_catalog_setup_from_tool_trace(
        self,
        *,
        tool_trace: list[dict[str, Any]],
    ) -> IngestionAgentPlanOutput | None:
        """Synthesise an awaiting_catalog_setup output when the tool trace shows
        describe_table_schema returned {found: false} (no catalog entry exists yet)
        or the workspace catalog was empty and no proposal tools were used."""
        schema_result = self._latest_tool_result(tool_trace, "describe_table_schema")
        catalog_result = self._latest_tool_result(tool_trace, "get_workspace_catalog")

        # Condition: the table was not found, OR the catalog has no entries at all
        table_not_found = schema_result.get("found") is False
        catalog_empty = not list(catalog_result.get("entries") or [])
        if not (table_not_found or catalog_empty):
            return None

        upload_info = self._latest_tool_result(tool_trace, "inspect_upload")
        column_summary = (
            upload_info.get("column_summary")
            if isinstance(upload_info.get("column_summary"), dict)
            else {}
        )
        raw_columns = (
            column_summary.get("all_columns")
            if isinstance(column_summary.get("all_columns"), list)
            else []
        )
        upload_columns = [str(item).strip() for item in raw_columns if str(item).strip()]

        # Derive a table name from the upload file name or the schema hint.
        # All naming here is a neutral fallback used only when the agent
        # failed to produce a structured output; we deliberately do NOT
        # synthesise a business-flavoured human_label or business_type from
        # heuristics — leave that for the user to fill in via the catalog
        # setup card.
        file_name = str(upload_info.get("file_name") or "").strip()
        hint_table = str(schema_result.get("table_name") or "").strip().lower()
        if hint_table and SAFE_IDENTIFIER_RE.match(hint_table):
            table_name = hint_table
        elif file_name:
            base = Path(file_name).stem
            table_name = self._normalize_identifier(base) or "uploaded_table"
        else:
            table_name = "uploaded_table"

        human_label = table_name.replace("_", " ").title()
        description = (
            f"Table for uploads containing: {', '.join(upload_columns[:8])}."
            if upload_columns
            else "New table from uploaded file."
        )
        business_type = "other"
        write_mode = "new_table"
        time_grain = "none"
        primary_keys: list[str] = []
        match_columns: list[str] = []

        try:
            return IngestionAgentPlanOutput.model_validate(
                {
                    "status": "awaiting_catalog_setup",
                    "agent_guess": {
                        "business_type": business_type,
                        "confidence": 0.5,
                        "reasoning": (
                            "No catalog entry found for this upload. Recovered from tool trace to request catalog setup."
                        ),
                    },
                    "setup_questions": [
                        {
                            "question_id": "description",
                            "title": "What is this table used for?",
                            "options": [],
                        }
                    ],
                    "suggested_catalog_seed": {
                        "business_type": business_type,
                        "table_name": table_name,
                        "human_label": human_label,
                        "write_mode": write_mode,
                        "time_grain": time_grain,
                        "primary_keys": primary_keys,
                        "match_columns": match_columns,
                        "is_active_target": True,
                        "description": description,
                    },
                    "human_approval": {
                        "required": True,
                        "mechanism": "catalog_setup_card",
                        "stage": "catalog_setup",
                        "question": "Please confirm the table definition before proceeding.",
                        "options": list(CATALOG_SETUP_APPROVAL_OPTIONS),
                        "recommended_option": "confirm_catalog_setup",
                    },
                }
            )
        except Exception:
            return None

    def _recover_proposal_from_tool_trace(
        self,
        *,
        tool_trace: list[dict[str, Any]],
    ) -> IngestionAgentPlanOutput | None:
        """Recover a proposal from tool trace when the agent called generate_write_sql_draft
        but did not produce valid structured output (e.g. non-Claude LLM ignoring json_schema)."""
        draft_trace = self._latest_tool_trace_item(
            tool_trace,
            names={"generate_write_sql_draft"},
        )
        if draft_trace is None:
            return None

        schema = self._latest_tool_result(tool_trace, "describe_table_schema")
        upload_info = self._latest_tool_result(tool_trace, "inspect_upload")
        upload_columns, normalized_columns, structured_column_mode = self._proposal_columns_from_upload_info(
            upload_info
        )

        business_type = str(schema.get("business_type") or "other").strip()
        if business_type not in {"roster", "project_progress", "attendance", "other"}:
            business_type = "other"
        agent_guess_payload = {
            "business_type": business_type,
            "confidence": 0.55,
            "reasoning": (
                "Recovered from tool trace because the agent completed all tools "
                "but did not return valid structured output."
            ),
        }

        allowed_options = list(DEFAULT_ACTION_OPTIONS)
        human_approval_payload = {
            "required": True,
            "mechanism": "frontend_approval_card",
            "stage": "proposal_approval",
            "question": "Please review the proposed ingestion action.",
            "options": allowed_options,
            "recommended_option": "update_existing",
        }

        diff_preview_result = self._latest_tool_result(tool_trace, "build_diff_preview")
        draft_arguments = draft_trace.get("arguments") if isinstance(draft_trace.get("arguments"), dict) else {}
        sql_payload = self._latest_tool_result(tool_trace, "generate_write_sql_draft")

        target_table = str(draft_arguments.get("target_table") or schema.get("table_name") or "").strip().lower()
        if target_table and not SAFE_IDENTIFIER_RE.match(target_table):
            target_table = self._normalize_identifier(target_table)
        if not target_table:
            target_table = None

        candidate_actions = list(DEFAULT_ACTION_OPTIONS) + ["cancel"]
        action_mode = str(draft_arguments.get("action_mode") or "update_existing").strip()
        recommended_action = action_mode if action_mode in candidate_actions else "update_existing"

        match_columns: list[str] = []
        for item in (
            draft_arguments.get("match_columns")
            if isinstance(draft_arguments.get("match_columns"), list)
            else []
        ):
            normalized = self._normalize_identifier(str(item))
            if normalized and normalized not in match_columns:
                match_columns.append(normalized)
        if not match_columns:
            for item in (
                schema.get("match_columns")
                if isinstance(schema.get("match_columns"), list)
                else []
            ):
                normalized = self._normalize_identifier(str(item))
                if normalized and normalized not in match_columns:
                    match_columns.append(normalized)
        if not match_columns and normalized_columns:
            match_columns = [normalized_columns[0]]

        time_grain = str(schema.get("time_grain") or "none").strip()
        if time_grain not in {"none", "month", "quarter", "year"}:
            time_grain = "none"

        def _as_non_negative_int(value: Any) -> int:
            try:
                return max(int(value), 0)
            except (TypeError, ValueError):
                return 0

        column_mapping = (
            self._column_mapping_from_build_diff_trace(
                tool_trace=tool_trace,
                upload_columns=upload_columns,
                structured_column_mode=structured_column_mode,
            )
            or self._fallback_column_mapping_from_upload_columns(
                upload_columns=upload_columns,
                structured_column_mode=structured_column_mode,
            )
        )

        proposal_payload = {
            "business_type": business_type,
            "confidence": 0.6,
            "recommended_action": recommended_action,
            "candidate_actions": candidate_actions,
            "target_table": target_table,
            "time_grain": time_grain,
            "match_columns": match_columns,
            "column_mapping": column_mapping,
            "diff_preview": {
                "predicted_insert_count": _as_non_negative_int(
                    diff_preview_result.get("predicted_insert_count")
                ),
                "predicted_update_count": _as_non_negative_int(
                    diff_preview_result.get("predicted_update_count")
                ),
                "predicted_conflict_count": _as_non_negative_int(
                    diff_preview_result.get("predicted_conflict_count")
                ),
            },
            "risks": [
                "Proposal recovered from tool trace; verify column mapping before approving."
            ],
            "explanation": (
                "Proposal recovered from tool trace because the agent completed all tools "
                "but did not return valid structured output. Review carefully before approving."
            ),
            "sql_draft": str(sql_payload.get("sql_draft") or "").strip(),
            "requires_catalog_setup": False,
        }
        try:
            return IngestionAgentPlanOutput.model_validate(
                {
                    "status": "awaiting_user_approval",
                    "agent_guess": agent_guess_payload,
                    "proposal": proposal_payload,
                    "human_approval": human_approval_payload,
                }
            )
        except Exception:
            return None

    def _proposal_columns_from_upload_info(
        self,
        upload_info: dict[str, Any],
    ) -> tuple[list[str], list[str], bool]:
        column_summary = (
            upload_info.get("column_summary")
            if isinstance(upload_info.get("column_summary"), dict)
            else {}
        )
        raw_columns = (
            column_summary.get("all_columns")
            if isinstance(column_summary.get("all_columns"), list)
            else []
        )
        upload_columns = [str(item).strip() for item in raw_columns if str(item).strip()]
        normalized_columns: list[str] = []
        for raw_column in upload_columns:
            candidate = self._normalize_identifier(raw_column)
            if candidate and candidate not in normalized_columns:
                normalized_columns.append(candidate)
        return upload_columns, normalized_columns, False

    def _column_mapping_from_build_diff_trace(
        self,
        *,
        tool_trace: list[dict[str, Any]],
        upload_columns: list[str],
        structured_column_mode: bool,
    ) -> dict[str, str]:
        build_diff_item = self._latest_tool_trace_item(tool_trace, names={"build_diff_preview"})
        arguments = build_diff_item.get("arguments") if isinstance(build_diff_item, dict) else {}
        raw_mapping = arguments.get("column_mapping") if isinstance(arguments, dict) else None
        if not isinstance(raw_mapping, dict):
            return {}
        return self._normalize_proposal_column_mapping(
            raw_mapping=raw_mapping,
            upload_columns=upload_columns,
            structured_column_mode=structured_column_mode,
        )

    def _fallback_column_mapping_from_upload_columns(
        self,
        *,
        upload_columns: list[str],
        structured_column_mode: bool,
    ) -> dict[str, str]:
        return self._normalize_proposal_column_mapping(
            raw_mapping={},
            upload_columns=upload_columns,
            structured_column_mode=structured_column_mode,
        )

    def _normalize_proposal_column_mapping(
        self,
        *,
        raw_mapping: dict[Any, Any],
        upload_columns: list[str],
        structured_column_mode: bool,
    ) -> dict[str, str]:
        mapped_by_header = {
            str(key).strip(): str(value).strip().lower()
            for key, value in raw_mapping.items()
            if str(key).strip() and str(value).strip()
        }
        ordered_headers = [str(item).strip() for item in upload_columns if str(item).strip()]
        if not ordered_headers:
            ordered_headers = list(mapped_by_header.keys())

        result: dict[str, str] = {}
        used_targets: set[str] = set()
        for index, raw_column in enumerate(ordered_headers):
            target = mapped_by_header.get(raw_column)
            if not target:
                target = raw_column if structured_column_mode else self._normalize_identifier(raw_column)
            if not target or not SAFE_IDENTIFIER_RE.match(target):
                target = f"c_{index + 1}"

            base = target
            seq = 2
            while target in used_targets:
                target = f"{base}_{seq}"
                seq += 1
            used_targets.add(target)
            result[raw_column] = target
        return result

    def _run_tool(
        self,
        *,
        conn: sqlite3.Connection,
        job_id: str,
        trace: list[dict[str, Any]],
        name: str,
        arguments: dict[str, Any],
        handler: Any,
    ) -> dict[str, Any]:
        started_at = time.perf_counter()
        self._insert_event(
            conn=conn,
            job_id=job_id,
            event_type="tool_use",
            payload={"tool_name": name, "arguments": arguments},
        )
        logger.info("ingestion_tool_use job_id=%s tool_name=%s arguments=%s", job_id, name, _compact_json(arguments))
        try:
            result = handler()
        except Exception as exc:
            elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
            error_payload = {
                "tool_name": name,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "elapsed_ms": elapsed_ms,
            }
            self._insert_event(
                conn=conn,
                job_id=job_id,
                event_type="tool_error",
                payload=error_payload,
            )
            trace.append({"tool_name": name, "arguments": arguments, "error": error_payload})
            logger.warning(
                "ingestion_tool_error job_id=%s tool_name=%s elapsed_ms=%s error_type=%s error=%s",
                job_id,
                name,
                elapsed_ms,
                type(exc).__name__,
                str(exc),
            )
            raise

        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
        self._insert_event(
            conn=conn,
            job_id=job_id,
            event_type="tool_result",
            payload={"tool_name": name, "result": result, "elapsed_ms": elapsed_ms},
        )
        trace.append(
            {
                "tool_name": name,
                "arguments": arguments,
                "result": result,
                "elapsed_ms": elapsed_ms,
            }
        )
        logger.info(
            "ingestion_tool_result job_id=%s tool_name=%s elapsed_ms=%s",
            job_id,
            name,
            elapsed_ms,
        )
        return result

    def _load_job_for_approval(
        self,
        *,
        conn: sqlite3.Connection,
        workspace_id: str,
        job_id: str,
    ) -> sqlite3.Row:
        row = conn.execute(
            """
            SELECT id, workspace_id, upload_id, status, agent_session_id
            FROM ingestion_jobs
            WHERE id = ? AND workspace_id = ?
            """,
            (job_id, workspace_id),
        ).fetchone()
        if row is None:
            raise IngestionPlanningError(
                code="INGESTION_JOB_NOT_FOUND",
                message="Ingestion job not found",
                status_code=404,
            )
        status = str(row["status"])
        if status != "awaiting_user_approval":
            raise IngestionPlanningError(
                code="INGESTION_APPROVAL_NOT_ALLOWED",
                message=f"Job status does not allow approval: {status}",
                status_code=409,
            )
        return row

    def _load_job_for_execution(
        self,
        *,
        conn: sqlite3.Connection,
        workspace_id: str,
        job_id: str,
    ) -> sqlite3.Row:
        row = conn.execute(
            """
            SELECT id, workspace_id, upload_id, status, agent_session_id
            FROM ingestion_jobs
            WHERE id = ? AND workspace_id = ?
            """,
            (job_id, workspace_id),
        ).fetchone()
        if row is None:
            raise IngestionPlanningError(
                code="INGESTION_JOB_NOT_FOUND",
                message="Ingestion job not found",
                status_code=404,
            )
        status = str(row["status"])
        if status != "approved":
            raise IngestionPlanningError(
                code="INGESTION_EXECUTION_NOT_ALLOWED",
                message=f"Job status does not allow execution: {status}",
                status_code=409,
            )
        return row

    def _load_proposal(
        self,
        *,
        conn: sqlite3.Connection,
        workspace_id: str,
        job_id: str,
        proposal_id: str,
    ) -> tuple[sqlite3.Row, IngestionProposalPayload]:
        row = conn.execute(
            """
            SELECT id, workspace_id, job_id, proposal_version, proposal_json
            FROM ingestion_proposals
            WHERE id = ? AND workspace_id = ? AND job_id = ?
            """,
            (proposal_id, workspace_id, job_id),
        ).fetchone()
        if row is None:
            raise IngestionPlanningError(
                code="INGESTION_PROPOSAL_NOT_FOUND",
                message="Ingestion proposal not found",
                status_code=404,
            )

        payload = _decode_json_dict(row["proposal_json"])
        try:
            proposal = IngestionProposalPayload.model_validate(payload)
        except Exception as exc:
            raise IngestionPlanningError(
                code="INGESTION_PROPOSAL_INVALID",
                message="Persisted proposal payload is invalid",
                status_code=500,
            ) from exc
        return row, proposal

    def _load_latest_approval_event(
        self,
        *,
        conn: sqlite3.Connection,
        job_id: str,
        proposal_id: str,
    ) -> dict[str, Any]:
        row = conn.execute(
            """
            SELECT payload
            FROM ingestion_events
            WHERE job_id = ? AND event_type = 'proposal_approved'
            ORDER BY rowid DESC
            LIMIT 1
            """,
            (job_id,),
        ).fetchone()
        if row is None:
            raise IngestionPlanningError(
                code="INGESTION_APPROVAL_NOT_FOUND",
                message="Proposal has not been approved",
                status_code=409,
            )
        payload = _decode_json_dict(row["payload"])
        if str(payload.get("proposal_id", "")).strip() != proposal_id:
            raise IngestionPlanningError(
                code="INGESTION_APPROVAL_MISMATCH",
                message="Proposal approval context is not bound to this proposal",
                status_code=409,
            )
        required = (
            "approved_action",
            "target_table",
            "dry_run_summary",
        )
        for key in required:
            if key not in payload:
                raise IngestionPlanningError(
                    code="INGESTION_APPROVAL_INVALID",
                    message="Approval payload is incomplete",
                    status_code=500,
                )
        return payload

    def _resolve_approved_target(
        self,
        *,
        proposal_payload: IngestionProposalPayload,
        approved_action: str,
        overrides: IngestionApprovalOverrides | None,
    ) -> tuple[str, str]:
        override_target = (overrides.target_table if overrides else None) or None
        override_time_grain = (overrides.time_grain if overrides else None) or None

        if approved_action == "update_existing":
            candidate = (override_target or proposal_payload.target_table or "").strip().lower()
            if not candidate:
                raise IngestionPlanningError(
                    code="TARGET_TABLE_REQUIRED",
                    message="target_table is required for update_existing",
                    status_code=422,
                )
            if not SAFE_IDENTIFIER_RE.match(candidate):
                raise IngestionPlanningError(
                    code="TARGET_TABLE_INVALID",
                    message="target_table must be a valid SQL identifier",
                    status_code=422,
                )
            return candidate, "none"

        time_grain = override_time_grain or proposal_payload.time_grain
        base_target = (
            override_target
            or proposal_payload.target_table
            or f"{proposal_payload.business_type}_ingestion"
        ).strip().lower()
        if not SAFE_IDENTIFIER_RE.match(base_target):
            raise IngestionPlanningError(
                code="TARGET_TABLE_INVALID",
                message="target_table must be a valid SQL identifier",
                status_code=422,
            )

        if approved_action == "new_table":
            if override_target:
                return base_target, "none"
            suffix = datetime.now(timezone.utc).strftime("%Y%m%d")
            return f"{base_target}_{suffix}", "none"

        if approved_action == "time_partitioned_new_table":
            if override_target:
                return base_target, time_grain
            suffix = self._partition_suffix(time_grain)
            return f"{base_target}_{suffix}", time_grain

        raise IngestionPlanningError(
            code="WRITE_ACTION_UNSUPPORTED",
            message=f"Unsupported approved action: {approved_action}",
            status_code=422,
        )

    @staticmethod
    def _partition_suffix(time_grain: str) -> str:
        now = datetime.now(timezone.utc)
        if time_grain == "year":
            return now.strftime("%Y")
        if time_grain == "quarter":
            quarter = ((now.month - 1) // 3) + 1
            return f"{now.year}q{quarter}"
        return now.strftime("%Y%m")

    def _build_validated_sql(
        self,
        *,
        approved_action: str,
        target_table: str,
        staging_table: str,
        proposal_payload: IngestionProposalPayload,
        target_column_types: dict[str, str] | None = None,
    ) -> str:
        mapping_values = [
            str(value).strip().lower()
            for value in proposal_payload.column_mapping.values()
            if str(value).strip()
        ]
        match_columns = [
            str(value).strip().lower()
            for value in proposal_payload.match_columns
            if str(value).strip()
        ]
        ordered_columns = self._dedupe_preserve_order([*mapping_values, *match_columns])
        safe_columns = [column for column in ordered_columns if SAFE_IDENTIFIER_RE.match(column)]
        normalized_target_types = {
            str(column).strip().lower(): str(dtype).strip()
            for column, dtype in (target_column_types or {}).items()
            if SAFE_IDENTIFIER_RE.match(str(column).strip().lower()) and str(dtype).strip()
        }
        if normalized_target_types:
            safe_columns = [
                column for column in safe_columns if column in normalized_target_types
            ]
        if not safe_columns:
            safe_columns = self._dedupe_preserve_order(match_columns)
            if normalized_target_types:
                safe_columns = [
                    column for column in safe_columns if column in normalized_target_types
                ]
        if not safe_columns:
            raise IngestionPlanningError(
                code="COLUMN_MAPPING_INVALID",
                message="Cannot build write SQL without valid mapped columns",
                status_code=422,
            )

        if approved_action == "update_existing":
            if not match_columns:
                raise IngestionPlanningError(
                    code="MATCH_COLUMNS_REQUIRED",
                    message="match_columns are required for update_existing",
                    status_code=422,
                )
            safe_match_columns = [value for value in match_columns if SAFE_IDENTIFIER_RE.match(value)]
            if not safe_match_columns:
                raise IngestionPlanningError(
                    code="MATCH_COLUMNS_INVALID",
                    message="match_columns must be valid SQL identifiers",
                    status_code=422,
                )
            if normalized_target_types:
                safe_match_columns = [
                    value for value in safe_match_columns if value in normalized_target_types
                ]
                if not safe_match_columns:
                    raise IngestionPlanningError(
                        code="MATCH_COLUMNS_INVALID",
                        message="match_columns must exist in the target table schema",
                        status_code=422,
                    )

            source_expr_by_column = {
                value: self._source_expr_for_target_type(
                    source_alias="s",
                    column=value,
                    target_type=normalized_target_types.get(value),
                )
                for value in safe_columns
            }
            match_expr = " AND ".join(
                [f"t.{value} = {source_expr_by_column[value]}" for value in safe_match_columns]
            )
            update_columns = [value for value in safe_columns if value not in set(safe_match_columns)]
            if not update_columns:
                update_columns = list(safe_columns)
            update_expr = ", ".join(
                [f"{value} = {source_expr_by_column[value]}" for value in update_columns]
            )
            insert_cols = ", ".join(safe_columns)
            insert_vals = ", ".join([source_expr_by_column[value] for value in safe_columns])
            return (
                f"MERGE INTO {target_table} AS t\n"
                f"USING {staging_table} AS s\n"
                f"ON {match_expr}\n"
                f"WHEN MATCHED THEN UPDATE SET {update_expr}\n"
                f"WHEN NOT MATCHED THEN INSERT ({insert_cols}) VALUES ({insert_vals})"
            )

        select_cols = ", ".join(safe_columns)
        return (
            f"CREATE TABLE {target_table} AS\n"
            f"SELECT {select_cols} FROM {staging_table}"
        )

    def _load_target_column_types(
        self,
        *,
        workspace_id: str,
        target_table: str,
    ) -> dict[str, str]:
        db_path = self._workspace_duckdb_path(workspace_id=workspace_id)
        if not db_path.exists():
            return {}

        try:
            conn = duckdb.connect(str(db_path))
        except Exception:  # pragma: no cover - defensive
            return {}

        try:
            rows = conn.execute(f"PRAGMA table_info('{target_table}')").fetchall()
        except Exception:
            return {}
        finally:
            conn.close()

        schema: dict[str, str] = {}
        for row in rows:
            if len(row) < 3:
                continue
            name = str(row[1]).strip().lower()
            dtype = str(row[2]).strip()
            if not SAFE_IDENTIFIER_RE.match(name):
                continue
            if not dtype:
                continue
            schema[name] = dtype
        return schema

    def _source_expr_for_target_type(
        self,
        *,
        source_alias: str,
        column: str,
        target_type: str | None,
    ) -> str:
        source_expr = f"{source_alias}.{column}"
        normalized_type = self._normalize_duckdb_type(target_type)
        if not normalized_type:
            return source_expr

        upper_type = normalized_type.upper()
        if "TIMESTAMP" in upper_type:
            return self._timestamp_cast_expr(source_expr=source_expr, target_type=normalized_type)
        if upper_type == "DATE":
            return self._date_cast_expr(source_expr=source_expr, target_type=normalized_type)
        return f"TRY_CAST({source_expr} AS {normalized_type})"

    @staticmethod
    def _normalize_duckdb_type(raw_type: str | None) -> str | None:
        if raw_type is None:
            return None
        normalized = " ".join(str(raw_type).strip().split())
        if not normalized:
            return None
        if not SAFE_DUCKDB_TYPE_RE.match(normalized):
            return None
        return normalized

    @staticmethod
    def _timestamp_cast_expr(*, source_expr: str, target_type: str) -> str:
        string_expr = f"NULLIF(TRIM(CAST({source_expr} AS VARCHAR)), '')"
        numeric_expr = f"TRY_CAST({source_expr} AS DOUBLE)"
        excel_serial_expr = (
            "CASE "
            f"WHEN {numeric_expr} IS NOT NULL AND {numeric_expr} BETWEEN 1 AND 600000 "
            f"THEN TRY_CAST("
            f"CAST(DATE '1899-12-30' + CAST(FLOOR({numeric_expr}) AS INTEGER) AS TIMESTAMP) "
            f"+ ({numeric_expr} - FLOOR({numeric_expr})) * INTERVAL '1 day' "
            f"AS {target_type}"
            ") "
            "ELSE NULL END"
        )
        return (
            "COALESCE("
            f"TRY_CAST({string_expr} AS {target_type}), "
            f"{excel_serial_expr}"
            ")"
        )

    @staticmethod
    def _date_cast_expr(*, source_expr: str, target_type: str) -> str:
        string_expr = f"NULLIF(TRIM(CAST({source_expr} AS VARCHAR)), '')"
        numeric_expr = f"TRY_CAST({source_expr} AS DOUBLE)"
        excel_serial_expr = (
            "CASE "
            f"WHEN {numeric_expr} IS NOT NULL AND {numeric_expr} BETWEEN 1 AND 600000 "
            f"THEN TRY_CAST(DATE '1899-12-30' + CAST(FLOOR({numeric_expr}) AS INTEGER) AS {target_type}) "
            "ELSE NULL END"
        )
        return (
            "COALESCE("
            f"TRY_CAST({string_expr} AS {target_type}), "
            f"{excel_serial_expr}"
            ")"
        )

    def _build_dry_run_summary(
        self,
        *,
        proposal_payload: IngestionProposalPayload,
        approved_action: str,
        target_table: str,
        time_grain: str,
        preview_override: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        preview = preview_override or proposal_payload.diff_preview.model_dump(mode="json")
        predicted_insert = int(preview.get("predicted_insert_count", 0))
        predicted_update = int(preview.get("predicted_update_count", 0))
        predicted_conflict = int(preview.get("predicted_conflict_count", 0))
        affected = predicted_insert + predicted_update
        schema_warnings = [
            f"match_column_missing:{column}"
            for column in proposal_payload.match_columns
            if column not in set(proposal_payload.column_mapping.values())
        ]
        return {
            "approved_action": approved_action,
            "target_table": target_table,
            "time_grain": time_grain,
            "predicted_insert_count": max(predicted_insert, 0),
            "predicted_update_count": max(predicted_update, 0),
            "predicted_conflict_count": max(predicted_conflict, 0),
            "predicted_affected_rows": max(affected, 0),
            "schema_warnings": schema_warnings,
            "risks": list(proposal_payload.risks),
        }

    def _prepare_execution_session(
        self,
        *,
        workspace_id: str,
        job_id: str,
        proposal_id: str,
        upload_id: str,
        target_table: str,
        approved_action: str,
        dry_run_summary: dict[str, Any],
        upload_info: dict[str, Any],
        proposal_payload: IngestionProposalPayload,
    ) -> IngestionExecutionSession:
        upload_path = Path(str(upload_info["storage_path"])).resolve()
        if not upload_path.exists():
            raise IngestionPlanningError(
                code="UPLOAD_FILE_MISSING",
                message="Uploaded file no longer exists on disk",
                status_code=500,
            )

        raw_dataframe, raw_header_mapping = self._load_execution_dataframe_with_header_mapping(
            upload_path=upload_path,
            column_mapping=dict(proposal_payload.column_mapping) if proposal_payload.column_mapping else None,
        )
        staging_dataframe = self._prepare_dataframe_for_staging(raw_dataframe)
        staging_table = self._staging_table_name(job_id)
        db_path = self._workspace_duckdb_path(workspace_id=workspace_id)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            duckdb_conn = duckdb.connect(str(db_path))
        except Exception as exc:  # pragma: no cover - defensive
            raise IngestionPlanningError(
                code="DUCKDB_CONNECT_FAILED",
                message=f"Unable to open workspace DuckDB: {exc}",
                status_code=500,
            ) from exc

        try:
            duckdb_conn.register("ingestion_upload_df", staging_dataframe)
            duckdb_conn.execute(
                f"CREATE OR REPLACE TEMP TABLE {staging_table} AS SELECT * FROM ingestion_upload_df"
            )
            duckdb_conn.unregister("ingestion_upload_df")
        except Exception as exc:
            try:
                duckdb_conn.unregister("ingestion_upload_df")
            except Exception:
                pass
            duckdb_conn.close()
            raise IngestionPlanningError(
                code="INGESTION_STAGING_PREP_FAILED",
                message=f"Unable to prepare DuckDB staging dataset: {exc}",
                status_code=500,
            ) from exc

        session = IngestionExecutionSession(
            workspace_id=workspace_id,
            job_id=job_id,
            proposal_id=proposal_id,
            upload_id=upload_id,
            approved_action=approved_action,
            target_table=target_table,
            staging_table=staging_table,
            db_path=db_path,
            duckdb_conn=duckdb_conn,
            upload_info=upload_info,
            proposal_payload=proposal_payload,
            dry_run_summary=dry_run_summary,
            staging_profile=self._dataframe_profile(staging_dataframe),
            raw_header_mapping=raw_header_mapping,
            column_diagnostics=self._build_dataframe_column_diagnostics(
                dataframe=raw_dataframe,
                raw_header_mapping=raw_header_mapping,
            ),
        )
        logger.info(
            "ingestion_execution_session_ready workspace_id=%s job_id=%s proposal_id=%s approved_action=%s target_table=%s staging_table=%s staging_profile=%s",
            workspace_id,
            job_id,
            proposal_id,
            approved_action,
            target_table,
            staging_table,
            _compact_json(session.staging_profile),
        )
        return session

    def _tool_get_execution_context(
        self,
        *,
        session: IngestionExecutionSession,
    ) -> dict[str, Any]:
        return {
            "workspace_id": session.workspace_id,
            "job_id": session.job_id,
            "proposal_id": session.proposal_id,
            "upload_id": session.upload_id,
            "approved_action": session.approved_action,
            "target_table": session.target_table,
            "staging_table": session.staging_table,
            "duckdb_path": str(session.db_path),
            "dry_run_summary": dict(session.dry_run_summary),
            "proposal_hints": {
                "business_type": session.proposal_payload.business_type,
                "match_columns": list(session.proposal_payload.match_columns),
                "column_mapping": dict(session.proposal_payload.column_mapping),
                "explanation": session.proposal_payload.explanation,
                "risks": list(session.proposal_payload.risks),
            },
        }

    def _tool_describe_staging_dataset(
        self,
        *,
        session: IngestionExecutionSession,
    ) -> dict[str, Any]:
        row_count = self._duckdb_table_row_count(
            conn=session.duckdb_conn,
            table_name=session.staging_table,
        )
        return {
            "table_name": session.staging_table,
            "row_count": row_count,
            "schema": self._duckdb_table_profile(
                conn=session.duckdb_conn,
                table_name=session.staging_table,
            ),
            "sample_rows": self._duckdb_table_sample_rows(
                conn=session.duckdb_conn,
                table_name=session.staging_table,
                limit=5,
            ),
            "raw_header_mapping": dict(session.raw_header_mapping),
            "column_diagnostics": list(session.column_diagnostics),
            "dataframe_profile": dict(session.staging_profile),
        }

    def _tool_describe_target_table(
        self,
        *,
        conn: sqlite3.Connection,
        session: IngestionExecutionSession,
    ) -> dict[str, Any]:
        exists = self._duckdb_table_exists(
            conn=session.duckdb_conn,
            table_name=session.target_table,
        )
        catalog_contract: dict[str, Any] | None = None
        try:
            catalog_contract = self._tool_describe_table_schema_by_name(
                conn=conn,
                workspace_id=session.workspace_id,
                table_name=session.target_table,
            )
        except IngestionPlanningError:
            catalog_contract = None

        payload: dict[str, Any] = {
            "table_name": session.target_table,
            "exists": exists,
            "catalog_contract": catalog_contract,
        }
        if not exists:
            payload["row_count"] = 0
            payload["schema"] = {"table_name": session.target_table, "columns": []}
            payload["sample_rows"] = []
            return payload

        payload["row_count"] = self._duckdb_table_row_count(
            conn=session.duckdb_conn,
            table_name=session.target_table,
        )
        payload["schema"] = self._duckdb_table_profile(
            conn=session.duckdb_conn,
            table_name=session.target_table,
        )
        payload["sample_rows"] = self._duckdb_table_sample_rows(
            conn=session.duckdb_conn,
            table_name=session.target_table,
            limit=5,
        )
        return payload

    def _tool_preview_write_diff(
        self,
        *,
        session: IngestionExecutionSession,
        match_columns: list[str],
    ) -> dict[str, Any]:
        safe_match_columns = [
            column for column in self._dedupe_preserve_order(match_columns) if SAFE_IDENTIFIER_RE.match(column)
        ]
        if not safe_match_columns:
            raise IngestionPlanningError(
                code="MATCH_COLUMNS_REQUIRED",
                message="preview_write_diff requires at least one valid match column",
                status_code=422,
            )

        staging_schema = self._duckdb_table_profile(
            conn=session.duckdb_conn,
            table_name=session.staging_table,
        )
        staging_columns = {
            str(item["name"]).strip().lower()
            for item in staging_schema.get("columns", [])
            if str(item.get("name", "")).strip()
        }
        target_exists = self._duckdb_table_exists(
            conn=session.duckdb_conn,
            table_name=session.target_table,
        )
        target_schema = (
            self._duckdb_table_profile(conn=session.duckdb_conn, table_name=session.target_table)
            if target_exists
            else {"table_name": session.target_table, "columns": []}
        )
        target_columns = {
            str(item["name"]).strip().lower()
            for item in target_schema.get("columns", [])
            if str(item.get("name", "")).strip()
        }
        missing_in_staging = [column for column in safe_match_columns if column not in staging_columns]
        missing_in_target = [column for column in safe_match_columns if column not in target_columns]

        payload: dict[str, Any] = {
            "approved_action": session.approved_action,
            "target_table": session.target_table,
            "staging_table": session.staging_table,
            "match_columns": safe_match_columns,
            "target_exists": target_exists,
            "missing_in_staging": missing_in_staging,
            "missing_in_target": missing_in_target,
            "staging_row_count": self._duckdb_table_row_count(
                conn=session.duckdb_conn,
                table_name=session.staging_table,
            ),
            "target_row_count": (
                self._duckdb_table_row_count(conn=session.duckdb_conn, table_name=session.target_table)
                if target_exists
                else 0
            ),
        }
        if not target_exists or missing_in_staging or missing_in_target:
            payload["matched_row_count"] = 0
            payload["unmatched_row_count"] = payload["staging_row_count"]
            payload["staging_duplicate_key_count"] = 0
            payload["target_duplicate_key_count"] = 0
            return payload

        group_expr = ", ".join(safe_match_columns)
        join_expr = " AND ".join([f"t.{column} = s.{column}" for column in safe_match_columns])
        first_match_column = safe_match_columns[0]
        payload["matched_row_count"] = int(
            session.duckdb_conn.execute(
                f"SELECT COUNT(*) FROM {session.staging_table} AS s "
                f"INNER JOIN {session.target_table} AS t ON {join_expr}"
            ).fetchone()[0]
        )
        payload["unmatched_row_count"] = int(
            session.duckdb_conn.execute(
                f"SELECT COUNT(*) FROM {session.staging_table} AS s "
                f"LEFT JOIN {session.target_table} AS t ON {join_expr} "
                f"WHERE t.{first_match_column} IS NULL"
            ).fetchone()[0]
        )
        payload["staging_duplicate_key_count"] = int(
            session.duckdb_conn.execute(
                f"SELECT COUNT(*) FROM ("
                f"SELECT {group_expr}, COUNT(*) AS c FROM {session.staging_table} "
                f"GROUP BY {group_expr} HAVING COUNT(*) > 1"
                f") AS dup"
            ).fetchone()[0]
        )
        payload["target_duplicate_key_count"] = int(
            session.duckdb_conn.execute(
                f"SELECT COUNT(*) FROM ("
                f"SELECT {group_expr}, COUNT(*) AS c FROM {session.target_table} "
                f"GROUP BY {group_expr} HAVING COUNT(*) > 1"
                f") AS dup"
            ).fetchone()[0]
        )
        return payload

    def _tool_resolve_column_mapping(
        self,
        *,
        conn: sqlite3.Connection,
        session: IngestionExecutionSession,
    ) -> dict[str, Any]:
        staging_schema = self._duckdb_table_profile(
            conn=session.duckdb_conn,
            table_name=session.staging_table,
        )
        staging_cols = {str(item["name"]).strip().lower() for item in staging_schema.get("columns", [])}

        raw_header_map: dict[str, str] = {
            str(original).strip(): str(staging_col).strip().lower()
            for original, staging_col in session.raw_header_mapping.items()
            if str(original).strip() and str(staging_col).strip()
        }

        proposal_col_map: dict[str, str] = {
            str(src).strip(): str(tgt).strip().lower()
            for src, tgt in (session.proposal_payload.column_mapping or {}).items()
            if str(src).strip() and str(tgt).strip()
        }

        try:
            catalog = self._tool_describe_table_schema_by_name(
                conn=conn,
                workspace_id=session.workspace_id,
                table_name=session.target_table,
            )
        except IngestionPlanningError:
            catalog = {}
        catalog_match_cols: list[str] = [
            str(c).strip().lower()
            for c in (catalog.get("match_columns") or session.proposal_payload.match_columns or [])
            if str(c).strip()
        ]

        resolved: dict[str, str] = {}
        for original_header, staging_col in raw_header_map.items():
            if staging_col not in staging_cols:
                continue
            target_col = proposal_col_map.get(original_header) or staging_col
            resolved[staging_col] = target_col

        for staging_col in staging_cols:
            if staging_col not in resolved:
                resolved[staging_col] = staging_col

        match_columns_resolved: list[str] = []
        for target_match_col in catalog_match_cols:
            for staging_col, target_col in resolved.items():
                if target_col == target_match_col or staging_col == target_match_col:
                    match_columns_resolved.append(staging_col)
                    break
            else:
                if target_match_col in staging_cols:
                    match_columns_resolved.append(target_match_col)

        return {
            "staging_to_target": resolved,
            "match_columns_staging": match_columns_resolved,
            "target_match_columns": catalog_match_cols,
            "staging_table": session.staging_table,
            "target_table": session.target_table,
            "note": (
                "Use staging_to_target to alias staging columns in SQL. "
                "Use match_columns_staging for ON clause in MERGE."
            ),
        }

    def _tool_ensure_target_table_exists(
        self,
        *,
        session: IngestionExecutionSession,
    ) -> dict[str, Any]:
        if session.approved_action != "update_existing":
            raise IngestionPlanningError(
                code="TARGET_TABLE_SETUP_NOT_ALLOWED",
                message="ensure_target_table_exists is only valid for update_existing executions",
                status_code=422,
            )
        exists = self._duckdb_table_exists(
            conn=session.duckdb_conn,
            table_name=session.target_table,
        )
        if exists:
            return {
                "table_name": session.target_table,
                "created": False,
                "schema": self._duckdb_table_profile(
                    conn=session.duckdb_conn,
                    table_name=session.target_table,
                ),
            }
        session.duckdb_conn.execute(
            f"CREATE TABLE {session.target_table} AS "
            f"SELECT * FROM {session.staging_table} WHERE 1 = 0"
        )
        return {
            "table_name": session.target_table,
            "created": True,
            "schema": self._duckdb_table_profile(
                conn=session.duckdb_conn,
                table_name=session.target_table,
            ),
        }

    def _tool_execute_approved_write(
        self,
        *,
        session: IngestionExecutionSession,
        sql: str,
        reasoning: str,
    ) -> dict[str, Any]:
        if session.write_receipt is not None:
            return dict(session.write_receipt)

        validator = SQLWriteValidator(
            target_table=session.target_table,
            staging_table=session.staging_table,
            action_mode=session.approved_action,
        )
        validated_sql = validator.validate(sql)
        target_exists_before = self._duckdb_table_exists(
            conn=session.duckdb_conn,
            table_name=session.target_table,
        )
        if session.approved_action == "update_existing" and not target_exists_before:
            raise IngestionPlanningError(
                code="TARGET_TABLE_NOT_READY",
                message=(
                    "Target table does not exist yet. Call ensure_target_table_exists before "
                    "execute_approved_write for update_existing."
                ),
                status_code=422,
            )

        rows_before = (
            self._duckdb_table_row_count(conn=session.duckdb_conn, table_name=session.target_table)
            if target_exists_before
            else 0
        )
        try:
            session.duckdb_conn.execute("BEGIN TRANSACTION")
            session.duckdb_conn.execute(validated_sql)
            session.duckdb_conn.execute("COMMIT")
        except Exception as exc:
            try:
                session.duckdb_conn.execute("ROLLBACK")
            except Exception:
                pass
            raise IngestionPlanningError(
                code="INGESTION_EXECUTION_FAILED",
                message=f"DuckDB execution failed: {exc}",
                status_code=500,
            ) from exc

        rows_after = self._duckdb_table_row_count(
            conn=session.duckdb_conn,
            table_name=session.target_table,
        )
        staging_row_count = self._duckdb_table_row_count(
            conn=session.duckdb_conn,
            table_name=session.staging_table,
        )
        inserted_rows = max(rows_after - rows_before, 0)
        updated_rows = 0
        if session.approved_action == "update_existing":
            updated_rows = max(staging_row_count - inserted_rows, 0)
        else:
            inserted_rows = rows_after if not target_exists_before else inserted_rows
        affected_rows = inserted_rows + updated_rows
        target_schema_after = self._duckdb_table_profile(
            conn=session.duckdb_conn,
            table_name=session.target_table,
        )
        column_metadata = self._build_column_metadata_for_receipt(
            session=session,
            target_schema=target_schema_after,
        )
        self._apply_duckdb_column_comments(
            conn=session.duckdb_conn,
            table_name=session.target_table,
            columns=column_metadata,
        )
        receipt = {
            "success": True,
            "workspace_id": session.workspace_id,
            "job_id": session.job_id,
            "proposal_id": session.proposal_id,
            "target_table": session.target_table,
            "approved_action": session.approved_action,
            "execution_mode": session.approved_action,
            "staging_table": session.staging_table,
            "duckdb_path": str(session.db_path),
            "executed_sql": validated_sql,
            "reasoning": reasoning.strip(),
            "predicted_insert_count": int(session.dry_run_summary.get("predicted_insert_count", 0)),
            "predicted_update_count": int(session.dry_run_summary.get("predicted_update_count", 0)),
            "rows_before": rows_before,
            "rows_after": rows_after,
            "staging_row_count": staging_row_count,
            "inserted_rows": inserted_rows,
            "updated_rows": updated_rows,
            "affected_rows": affected_rows,
            "target_exists_before": target_exists_before,
            "target_schema_after": target_schema_after,
            "column_metadata": column_metadata,
            "finished_at": _utc_now(),
        }
        session.executed_sql = validated_sql
        session.write_receipt = dict(receipt)
        return receipt

    @staticmethod
    def _build_column_metadata_for_receipt(
        *,
        session: IngestionExecutionSession,
        target_schema: dict[str, Any],
    ) -> list[dict[str, Any]]:
        original_by_target: dict[str, str] = {}
        for original, target in (session.proposal_payload.column_mapping or {}).items():
            original_text = str(original).strip()
            target_text = str(target).strip()
            if original_text and target_text:
                original_by_target[target_text] = original_text
        for original, target in (session.raw_header_mapping or {}).items():
            original_text = str(original).strip()
            target_text = str(target).strip()
            if original_text and target_text:
                original_by_target.setdefault(target_text, original_text)

        columns = target_schema.get("columns")
        if not isinstance(columns, list):
            return []

        metadata: list[dict[str, Any]] = []
        for index, column in enumerate(columns):
            if not isinstance(column, dict):
                continue
            column_name = str(column.get("name") or "").strip()
            if not column_name:
                continue
            original_name = original_by_target.get(column_name)
            metadata.append(
                {
                    "name": column_name,
                    "type": str(column.get("type") or ""),
                    "original_name": original_name,
                    "description": original_name,
                    "ordinal_position": index,
                }
            )
        return metadata

    @staticmethod
    def _apply_duckdb_column_comments(
        *,
        conn: duckdb.DuckDBPyConnection,
        table_name: str,
        columns: list[dict[str, Any]],
    ) -> None:
        if not SAFE_IDENTIFIER_RE.match(table_name):
            return
        for column in columns:
            column_name = str(column.get("name") or "").strip()
            description = str(column.get("description") or column.get("original_name") or "").strip()
            if not column_name or not description or not SAFE_IDENTIFIER_RE.match(column_name):
                continue
            escaped_description = description.replace("'", "''")
            try:
                conn.execute(
                    f"COMMENT ON COLUMN {table_name}.{column_name} IS '{escaped_description}'"
                )
            except duckdb.Error:
                logger.warning(
                    "duckdb_column_comment_failed table=%s column=%s",
                    table_name,
                    column_name,
                    exc_info=True,
                )

    @staticmethod
    def _duckdb_table_exists(
        *,
        conn: duckdb.DuckDBPyConnection,
        table_name: str,
    ) -> bool:
        row = conn.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_name = ?
            """,
            [table_name],
        ).fetchone()
        return bool(row and int(row[0]) > 0)

    @staticmethod
    def _duckdb_table_row_count(
        *,
        conn: duckdb.DuckDBPyConnection,
        table_name: str,
    ) -> int:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])

    def _duckdb_table_sample_rows(
        self,
        *,
        conn: duckdb.DuckDBPyConnection,
        table_name: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        cursor = conn.execute(f"SELECT * FROM {table_name} LIMIT {max(limit, 0)}")
        columns = [str(item[0]) for item in (cursor.description or [])]
        rows = cursor.fetchall()
        return [
            {
                column: self._serialize_json_value(row[index])
                for index, column in enumerate(columns)
            }
            for row in rows
        ]

    def _build_dataframe_column_diagnostics(
        self,
        *,
        dataframe: pd.DataFrame,
        raw_header_mapping: dict[str, str],
    ) -> list[dict[str, Any]]:
        diagnostics: list[dict[str, Any]] = []
        for column in dataframe.columns:
            series = dataframe[column]
            type_names: list[str] = []
            sample_values: list[str] = []
            non_null_count = 0
            for value in series.tolist():
                if value is None:
                    continue
                try:
                    if pd.isna(value):
                        continue
                except TypeError:
                    pass
                non_null_count += 1
                type_name = type(value).__name__
                if type_name not in type_names:
                    type_names.append(type_name)
                sample_text = str(self._serialize_json_value(value))
                if sample_text not in sample_values:
                    sample_values.append(sample_text)
                if len(type_names) >= 4 and len(sample_values) >= 4:
                    break
            raw_headers = [
                header for header, normalized in raw_header_mapping.items() if normalized == str(column)
            ]
            diagnostics.append(
                {
                    "column": str(column),
                    "raw_headers": raw_headers,
                    "non_null_count": non_null_count,
                    "python_types": type_names,
                    "sample_values": sample_values[:4],
                }
            )
        return diagnostics

    def _workspace_duckdb_path(self, *, workspace_id: str) -> Path:
        from ..config import get_settings

        root = get_settings().upload_dir / "agentic_ingestion" / "duckdb"
        safe_workspace = re.sub(r"[^A-Za-z0-9_-]+", "_", workspace_id).strip("_") or "workspace"
        return (root / f"{safe_workspace}.duckdb").resolve()

    def _load_execution_dataframe(
        self,
        *,
        upload_path: Path,
        proposal_payload: IngestionProposalPayload,
    ) -> pd.DataFrame:
        sheets = self._read_execution_workbook(upload_path=upload_path)
        alias_map = {
            str(key): str(value).strip().lower()
            for key, value in proposal_payload.column_mapping.items()
            if str(key).strip() and str(value).strip()
        }
        merged_frames: list[pd.DataFrame] = []
        for frame in sheets.values():
            renamed = self._normalize_frame_columns(frame=frame, alias_map=alias_map)
            merged_frames.append(renamed)

        merged = pd.concat(merged_frames, ignore_index=True, sort=False)
        merged = merged.where(pd.notna(merged), None)
        if merged.empty:
            merged = pd.DataFrame(columns=list({*merged.columns}))
        return merged

    def _load_execution_dataframe_with_header_mapping(
        self,
        *,
        upload_path: Path,
        column_mapping: dict[str, str] | None = None,
    ) -> tuple[pd.DataFrame, dict[str, str]]:
        alias_map = dict(column_mapping) if column_mapping else {}
        sheets = self._read_execution_workbook(upload_path=upload_path)
        merged_frames: list[pd.DataFrame] = []
        raw_header_mapping: dict[str, str] = {}
        for frame in sheets.values():
            renamed, header_mapping = self._normalize_frame_columns_with_mapping(
                frame=frame,
                alias_map=alias_map,
            )
            merged_frames.append(renamed)
            raw_header_mapping.update(header_mapping)

        merged = pd.concat(merged_frames, ignore_index=True, sort=False)
        merged = merged.where(pd.notna(merged), None)
        if merged.empty:
            merged = pd.DataFrame(columns=list({*merged.columns}))
        return merged, raw_header_mapping

    def _read_execution_workbook(self, *, upload_path: Path) -> dict[str, pd.DataFrame]:
        try:
            sheets = pd.read_excel(upload_path, sheet_name=None, dtype=object, engine="openpyxl")
        except Exception as exc:
            raise IngestionPlanningError(
                code="UPLOAD_READ_FAILED",
                message=f"Unable to read uploaded workbook: {exc}",
                status_code=500,
            ) from exc
        if not sheets:
            raise IngestionPlanningError(
                code="UPLOAD_READ_FAILED",
                message="Uploaded workbook has no readable sheets",
                status_code=500,
            )
        return sheets

    def _prepare_dataframe_for_staging(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        prepared = dataframe.copy()
        for column in prepared.columns:
            prepared[column] = prepared[column].map(self._serialize_json_value)
        prepared = prepared.where(pd.notna(prepared), None)
        return prepared

    @staticmethod
    def _dataframe_profile(dataframe: pd.DataFrame) -> dict[str, Any]:
        return {
            "rows": int(len(dataframe)),
            "columns": [str(column) for column in dataframe.columns],
            "dtypes": {str(column): str(dtype) for column, dtype in dataframe.dtypes.items()},
        }

    @staticmethod
    def _serialize_json_value(value: Any) -> Any:
        if value is None:
            return None
        try:
            if pd.isna(value):
                return None
        except TypeError:
            pass
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            if value.is_integer():
                return str(int(value))
            return format(value, "g")
        if isinstance(value, datetime):
            return value.isoformat(sep=" ")
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        isoformat = getattr(value, "isoformat", None)
        if callable(isoformat) and not isinstance(value, str):
            try:
                return isoformat()
            except TypeError:
                pass
        return str(value)

    @staticmethod
    def _duckdb_table_profile(
        *,
        conn: duckdb.DuckDBPyConnection,
        table_name: str,
    ) -> dict[str, Any]:
        rows = conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
        columns = []
        for row in rows:
            if len(row) < 3:
                continue
            columns.append(
                {
                    "name": str(row[1]),
                    "type": str(row[2]),
                }
            )
        return {
            "table_name": table_name,
            "columns": columns,
        }

    def _normalize_frame_columns(
        self,
        *,
        frame: pd.DataFrame,
        alias_map: dict[str, str],
    ) -> pd.DataFrame:
        renamed, _header_mapping = self._normalize_frame_columns_with_mapping(
            frame=frame,
            alias_map=alias_map,
        )
        return renamed

    def _normalize_frame_columns_with_mapping(
        self,
        *,
        frame: pd.DataFrame,
        alias_map: dict[str, str],
    ) -> tuple[pd.DataFrame, dict[str, str]]:
        rename_map: dict[str, str] = {}
        header_mapping: dict[str, str] = {}
        seen: set[str] = set()
        for index, column in enumerate(frame.columns):
            raw = str(column).strip()
            candidate = alias_map.get(raw) or self._normalize_identifier(raw)
            if not candidate:
                candidate = f"c_{index + 1}"
            if not SAFE_IDENTIFIER_RE.match(candidate):
                candidate = f"c_{index + 1}"
            base = candidate
            seq = 2
            while candidate in seen:
                candidate = f"{base}_{seq}"
                seq += 1
            seen.add(candidate)
            rename_map[column] = candidate
            header_mapping[raw] = candidate
        return frame.rename(columns=rename_map), header_mapping

    @staticmethod
    def _staging_table_name(job_id: str) -> str:
        return f"staging_{job_id[:12].lower()}"

    @staticmethod
    def _dedupe_preserve_order(values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            lowered = value.strip().lower()
            if not lowered:
                continue
            if lowered in result:
                continue
            result.append(lowered)
        return result

    def _persist_proposal(
        self,
        *,
        conn: sqlite3.Connection,
        workspace_id: str,
        job_id: str,
        proposal: IngestionProposalPayload,
    ) -> str:
        row = conn.execute(
            "SELECT COALESCE(MAX(proposal_version), 0) AS max_version FROM ingestion_proposals WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        next_version = int(row["max_version"]) + 1 if row is not None else 1
        proposal_id = uuid.uuid4().hex
        serialized = proposal.model_dump(mode="json")
        conn.execute(
            """
            INSERT INTO ingestion_proposals (
                id,
                job_id,
                workspace_id,
                proposal_version,
                proposal_json,
                recommended_action,
                target_table,
                predicted_insert_count,
                predicted_update_count,
                predicted_conflict_count,
                risk_summary,
                generated_sql_draft,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                proposal_id,
                job_id,
                workspace_id,
                next_version,
                json.dumps(serialized, ensure_ascii=False),
                proposal.recommended_action,
                proposal.target_table,
                proposal.diff_preview.predicted_insert_count,
                proposal.diff_preview.predicted_update_count,
                proposal.diff_preview.predicted_conflict_count,
                json.dumps(proposal.risks, ensure_ascii=False),
                proposal.sql_draft,
                _utc_now(),
            ),
        )
        return proposal_id

    def _sync_catalog_entry_from_execution(
        self,
        *,
        conn: sqlite3.Connection,
        workspace_id: str,
        table_name: str,
        requested_by: str,
        proposal_payload: IngestionProposalPayload,
        approved_action: str,
    ) -> None:
        row = conn.execute(
            """
            SELECT *
            FROM table_catalog
            WHERE workspace_id = ? AND table_name = ?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (workspace_id, table_name),
        ).fetchone()
        if row is None:
            logical_table_name = (proposal_payload.target_table or "").strip().lower()
            if logical_table_name and logical_table_name != table_name:
                row = conn.execute(
                    """
                    SELECT *
                    FROM table_catalog
                    WHERE workspace_id = ? AND table_name = ?
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (workspace_id, logical_table_name),
                ).fetchone()
        if row is None and proposal_payload.business_type != "other":
            row = conn.execute(
                """
                SELECT *
                FROM table_catalog
                WHERE workspace_id = ? AND business_type = ? AND is_active_target = 1
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (workspace_id, proposal_payload.business_type),
            ).fetchone()
        if row is None:
            return

        catalog_id = str(row["id"])
        business_type = proposal_payload.business_type
        if business_type == "other" and str(row["business_type"]) != "other":
            business_type = str(row["business_type"])
        primary_keys = _decode_json_list(row["primary_keys"])
        match_columns = self._dedupe_preserve_order(list(proposal_payload.match_columns))
        if not primary_keys:
            primary_keys = list(match_columns)

        write_mode = approved_action.strip().lower()
        if write_mode not in {"update_existing", "time_partitioned_new_table", "new_table", "append_only"}:
            write_mode = str(row["write_mode"])

        time_grain = proposal_payload.time_grain
        now = _utc_now()
        is_active_target = bool(row["is_active_target"])
        if business_type != "other":
            conn.execute(
                """
                UPDATE table_catalog
                SET is_active_target = 0, updated_by = ?, updated_at = ?
                WHERE workspace_id = ? AND business_type = ? AND id != ?
                """,
                (requested_by, now, workspace_id, business_type, catalog_id),
            )
            is_active_target = True

        conn.execute(
            """
            UPDATE table_catalog
            SET
                table_name = ?,
                business_type = ?,
                write_mode = ?,
                time_grain = ?,
                primary_keys = ?,
                match_columns = ?,
                is_active_target = ?,
                updated_by = ?,
                updated_at = ?
            WHERE id = ? AND workspace_id = ?
            """,
            (
                table_name,
                business_type,
                write_mode,
                time_grain,
                json.dumps(primary_keys, ensure_ascii=False),
                json.dumps(match_columns, ensure_ascii=False),
                int(is_active_target),
                requested_by,
                now,
                catalog_id,
                workspace_id,
            ),
        )

    def _sync_column_metadata_from_execution(
        self,
        *,
        conn: sqlite3.Connection,
        workspace_id: str,
        table_name: str,
        receipt: dict[str, Any],
        proposal_payload: IngestionProposalPayload,
    ) -> None:
        raw_columns = receipt.get("column_metadata")
        if not isinstance(raw_columns, list):
            raw_columns = []
        trace_receipt: dict[str, Any] = {}
        tool_trace = receipt.get("tool_trace")
        if isinstance(tool_trace, list):
            trace_receipt = self._latest_tool_result(tool_trace, "execute_approved_write")
            if not raw_columns and isinstance(trace_receipt.get("column_metadata"), list):
                raw_columns = trace_receipt["column_metadata"]

        columns: list[dict[str, Any]] = []
        for index, item in enumerate(raw_columns):
            if not isinstance(item, dict):
                continue
            column_name = str(item.get("name") or "").strip()
            if not column_name:
                continue
            original_name = str(item.get("original_name") or item.get("description") or "").strip()
            columns.append(
                {
                    "name": column_name,
                    "type": str(item.get("type") or item.get("data_type") or ""),
                    "original_name": original_name or None,
                    "description": str(item.get("description") or original_name or "").strip() or None,
                    "ordinal_position": int(item.get("ordinal_position") or index),
                }
            )

        if not columns:
            schema_after = receipt.get("target_schema_after")
            if not isinstance(schema_after, dict):
                schema_after = trace_receipt.get("target_schema_after")
            schema_columns = schema_after.get("columns") if isinstance(schema_after, dict) else None
            target_to_original = {
                str(target).strip(): str(original).strip()
                for original, target in proposal_payload.column_mapping.items()
                if str(original).strip() and str(target).strip()
            }
            if isinstance(schema_columns, list):
                for index, item in enumerate(schema_columns):
                    if not isinstance(item, dict):
                        continue
                    column_name = str(item.get("name") or "").strip()
                    if not column_name:
                        continue
                    original_name = target_to_original.get(column_name)
                    columns.append(
                        {
                            "name": column_name,
                            "type": str(item.get("type") or ""),
                            "original_name": original_name,
                            "description": original_name,
                            "ordinal_position": index,
                        }
                    )

        if not columns:
            return

        upsert_table_column_metadata(
            conn,
            workspace_id=workspace_id,
            table_name=table_name,
            columns=columns,
            updated_at=_utc_now(),
        )

    def _set_job_status(
        self,
        *,
        conn: sqlite3.Connection,
        job_id: str,
        status: str,
        business_type_guess: str | None,
        agent_session_id: str | None,
    ) -> None:
        conn.execute(
            """
            UPDATE ingestion_jobs
            SET status = ?,
                business_type_guess = COALESCE(?, business_type_guess),
                agent_session_id = COALESCE(?, agent_session_id),
                updated_at = ?
            WHERE id = ?
            """,
            (status, business_type_guess, agent_session_id, _utc_now(), job_id),
        )

    def _upsert_catalog_entry_from_setup(
        self,
        *,
        conn: sqlite3.Connection,
        workspace_id: str,
        requested_by: str,
        setup_seed: IngestionCatalogSetupSeed,
        upload_info: dict[str, Any],
    ) -> dict[str, Any]:
        self._ensure_user_record(conn=conn, user_id=requested_by)
        now = _utc_now()
        business_type = setup_seed.business_type
        table_name = setup_seed.table_name
        human_label = setup_seed.human_label
        write_mode = setup_seed.write_mode
        time_grain = setup_seed.time_grain
        description = setup_seed.description

        primary_keys = self._dedupe_preserve_order(list(setup_seed.primary_keys))
        match_columns = self._dedupe_preserve_order(list(setup_seed.match_columns))

        if setup_seed.is_active_target:
            conn.execute(
                """
                UPDATE table_catalog
                SET is_active_target = 0, updated_by = ?, updated_at = ?
                WHERE workspace_id = ? AND business_type = ?
                """,
                (requested_by, now, workspace_id, business_type),
            )

        existing = conn.execute(
            """
            SELECT id, created_by, created_at
            FROM table_catalog
            WHERE workspace_id = ? AND business_type = ? AND table_name = ?
            """,
            (workspace_id, business_type, table_name),
        ).fetchone()
        if existing is None:
            catalog_id = uuid.uuid4().hex
            conn.execute(
                """
                INSERT INTO table_catalog (
                    id,
                    workspace_id,
                    table_name,
                    human_label,
                    business_type,
                    write_mode,
                    time_grain,
                    primary_keys,
                    match_columns,
                    is_active_target,
                    description,
                    created_by,
                    updated_by,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    catalog_id,
                    workspace_id,
                    table_name,
                    human_label,
                    business_type,
                    write_mode,
                    time_grain,
                    json.dumps(primary_keys, ensure_ascii=False),
                    json.dumps(match_columns, ensure_ascii=False),
                    int(bool(setup_seed.is_active_target)),
                    description,
                    requested_by,
                    requested_by,
                    now,
                    now,
                ),
            )
        else:
            catalog_id = str(existing["id"])
            conn.execute(
                """
                UPDATE table_catalog
                SET
                    human_label = ?,
                    write_mode = ?,
                    time_grain = ?,
                    primary_keys = ?,
                    match_columns = ?,
                    is_active_target = ?,
                    description = ?,
                    updated_by = ?,
                    updated_at = ?
                WHERE id = ? AND workspace_id = ?
                """,
                (
                    human_label,
                    write_mode,
                    time_grain,
                    json.dumps(primary_keys, ensure_ascii=False),
                    json.dumps(match_columns, ensure_ascii=False),
                    int(bool(setup_seed.is_active_target)),
                    description,
                    requested_by,
                    now,
                    catalog_id,
                    workspace_id,
                ),
            )

        row = conn.execute(
            "SELECT * FROM table_catalog WHERE id = ? AND workspace_id = ?",
            (catalog_id, workspace_id),
        ).fetchone()
        if row is None:
            raise IngestionPlanningError(
                code="CATALOG_ENTRY_NOT_FOUND",
                message="Catalog entry not found after setup confirmation",
                status_code=500,
            )
        return self._serialize_catalog_entry(row)

    def _ensure_user_record(self, *, conn: sqlite3.Connection, user_id: str) -> None:
        normalized_user = user_id.strip()
        if not normalized_user:
            raise IngestionPlanningError(
                code="AUTH_REQUIRED",
                message="user_id is required",
                status_code=401,
            )

        now = _utc_now()
        safe_local_part = re.sub(r"[^a-z0-9._-]+", "-", normalized_user.lower()).strip("-._") or "user"
        fallback_email = f"{safe_local_part}@local.invalid"
        conn.execute(
            """
            INSERT INTO users (id, email, display_name, status, created_at, updated_at)
            VALUES (?, ?, ?, 'active', ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                updated_at = excluded.updated_at
            """,
            (normalized_user, fallback_email, normalized_user, now, now),
        )

    @staticmethod
    def _normalize_identifier(raw: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9_]+", "_", raw.strip().lower()).strip("_")
        if not normalized:
            return ""
        if normalized[0].isdigit():
            normalized = f"c_{normalized}"
        return normalized

    def _tool_get_workspace_catalog(
        self,
        *,
        conn: sqlite3.Connection,
        workspace_id: str,
    ) -> dict[str, Any]:
        rows = conn.execute(
            """
            SELECT *
            FROM table_catalog
            WHERE workspace_id = ?
            ORDER BY is_active_target DESC, updated_at DESC
            """,
            (workspace_id,),
        ).fetchall()
        entries = [self._serialize_catalog_entry(row) for row in rows]
        return {"count": len(entries), "entries": entries}

    def _tool_list_existing_tables(
        self,
        *,
        conn: sqlite3.Connection,
        workspace_id: str,
    ) -> dict[str, Any]:
        catalog_rows = conn.execute(
            """
            SELECT DISTINCT table_name
            FROM table_catalog
            WHERE workspace_id = ?
            ORDER BY table_name ASC
            """,
            (workspace_id,),
        ).fetchall()
        catalog_tables = [str(row["table_name"]) for row in catalog_rows]

        db_path = self._workspace_duckdb_path(workspace_id=workspace_id)
        physical_tables: list[str] = []
        if db_path.exists():
            try:
                duck_conn = duckdb.connect(str(db_path), read_only=True)
                try:
                    physical_tables = [
                        str(row[0])
                        for row in duck_conn.execute(
                            """
                            SELECT table_name
                            FROM information_schema.tables
                            WHERE table_schema = 'main'
                            ORDER BY table_name ASC
                            """
                        ).fetchall()
                    ]
                finally:
                    duck_conn.close()
            except Exception as exc:
                logger.warning(
                    "ingestion_list_existing_tables_failed workspace_id=%s duckdb_path=%s error=%s",
                    workspace_id,
                    db_path,
                    exc,
                )
        return {
            "workspace_tables": physical_tables,
            "count": len(physical_tables),
            "catalog_tables": catalog_tables,
            "catalog_count": len(catalog_tables),
        }

    def _tool_inspect_upload(self, *, conn: sqlite3.Connection, upload_id: str) -> dict[str, Any]:
        row = conn.execute(
            """
            SELECT
                id,
                file_name,
                storage_path,
                size_bytes,
                file_hash,
                sheet_summary,
                column_summary,
                sample_preview
            FROM ingestion_uploads
            WHERE id = ?
            """,
            (upload_id,),
        ).fetchone()
        if row is None:
            raise IngestionPlanningError(
                code="UPLOAD_NOT_FOUND",
                message="Upload not found for ingestion job",
                status_code=404,
            )
        sheet_summary = _decode_json_dict(row["sheet_summary"])
        return {
            "upload_id": str(row["id"]),
            "file_name": str(row["file_name"]),
            "storage_path": str(row["storage_path"]),
            "size_bytes": int(row["size_bytes"]),
            "file_hash": str(row["file_hash"]),
            "sheet_summary": sheet_summary,
            "column_summary": _decode_json_dict(row["column_summary"]),
            "sample_preview": _decode_json_list(row["sample_preview"]),
            "workbook_structure": sheet_summary.get("workbook_structure"),
        }

    def _physical_table_summary(self, *, workspace_id: str, table_name: str) -> dict[str, Any]:
        normalized_table = table_name.strip().lower()
        summary = {
            "exists": False,
            "row_count": 0,
            "schema": {"table_name": normalized_table, "columns": []},
        }
        if not normalized_table or not SAFE_IDENTIFIER_RE.match(normalized_table):
            return summary

        db_path = self._workspace_duckdb_path(workspace_id=workspace_id)
        if not db_path.exists():
            return summary

        try:
            duck_conn = duckdb.connect(str(db_path), read_only=True)
        except Exception as exc:
            logger.warning(
                "ingestion_physical_table_summary_connect_failed workspace_id=%s table=%s path=%s error=%s",
                workspace_id,
                normalized_table,
                db_path,
                exc,
            )
            return summary

        try:
            exists = self._duckdb_table_exists(conn=duck_conn, table_name=normalized_table)
            if not exists:
                return summary
            return {
                "exists": True,
                "row_count": self._duckdb_table_row_count(conn=duck_conn, table_name=normalized_table),
                "schema": self._duckdb_table_profile(conn=duck_conn, table_name=normalized_table),
            }
        except Exception as exc:
            logger.warning(
                "ingestion_physical_table_summary_failed workspace_id=%s table=%s path=%s error=%s",
                workspace_id,
                normalized_table,
                db_path,
                exc,
            )
            return summary
        finally:
            duck_conn.close()

    def _tool_describe_table_schema_by_name(
        self,
        *,
        conn: sqlite3.Connection,
        workspace_id: str,
        table_name: str,
    ) -> dict[str, Any]:
        normalized_table = table_name.strip().lower()
        row = conn.execute(
            """
            SELECT *
            FROM table_catalog
            WHERE workspace_id = ? AND table_name = ?
            ORDER BY is_active_target DESC, updated_at DESC
            LIMIT 1
            """,
            (workspace_id, normalized_table),
        ).fetchone()
        physical = self._physical_table_summary(workspace_id=workspace_id, table_name=normalized_table)
        if row is None:
            return {
                "found": False,
                "table_name": normalized_table,
                "physical_table_exists": physical["exists"],
                "physical_row_count": physical["row_count"],
                "physical_schema": physical["schema"],
                "message": (
                    "No catalog entry exists for this table. "
                    "Call create_catalog_entry to create one, then call describe_table_schema again to verify."
                ),
            }
        target_catalog = self._serialize_catalog_entry(row)
        return {
            "found": True,
            "table_name": target_catalog["table_name"],
            "human_label": target_catalog["human_label"],
            "description": target_catalog["description"],
            "business_type": target_catalog["business_type"],
            "primary_keys": list(target_catalog["primary_keys"]),
            "match_columns": list(target_catalog["match_columns"]),
            "write_mode": target_catalog["write_mode"],
            "time_grain": target_catalog["time_grain"],
            "physical_table_exists": physical["exists"],
            "physical_row_count": physical["row_count"],
            "physical_schema": physical["schema"],
        }

    def _tool_create_catalog_entry(
        self,
        *,
        conn: sqlite3.Connection,
        job_id: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a catalog entry on behalf of the planning agent.

        The agent calls this when the workspace has no matching catalog entry for the
        upload. The method validates the inputs, delegates to
        ``_upsert_catalog_entry_from_setup``, and commits immediately so that the
        subsequent ``describe_table_schema`` call can see the new entry.
        """
        workspace_id = str(arguments.get("workspace_id", "")).strip()
        if not workspace_id:
            # Fall back to the job's workspace_id
            row = conn.execute(
                "SELECT workspace_id, created_by, upload_id FROM ingestion_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                raise IngestionPlanningError(
                    code="INGESTION_JOB_NOT_FOUND",
                    message="Ingestion job not found",
                    status_code=404,
                )
            workspace_id = str(row["workspace_id"])
            requested_by = str(row["created_by"])
            upload_id = str(row["upload_id"])
        else:
            row = conn.execute(
                "SELECT created_by, upload_id FROM ingestion_jobs WHERE id = ? AND workspace_id = ?",
                (job_id, workspace_id),
            ).fetchone()
            if row is None:
                raise IngestionPlanningError(
                    code="INGESTION_JOB_NOT_FOUND",
                    message="Ingestion job not found for the given workspace",
                    status_code=404,
                )
            requested_by = str(row["created_by"])
            upload_id = str(row["upload_id"])

        table_name = str(arguments.get("table_name", "")).strip().lower()
        if not table_name:
            raise IngestionPlanningError(
                code="CATALOG_TABLE_NAME_INVALID",
                message="table_name is required",
                status_code=422,
            )
        normalized_name = self._normalize_identifier(table_name)
        if not normalized_name or not SAFE_IDENTIFIER_RE.match(normalized_name):
            raise IngestionPlanningError(
                code="CATALOG_TABLE_NAME_INVALID",
                message=f"table_name '{table_name}' is not a valid SQL identifier",
                status_code=422,
            )
        table_name = normalized_name

        business_type = str(arguments.get("business_type", "other")).strip()
        if business_type not in {"roster", "project_progress", "attendance", "other"}:
            business_type = "other"

        write_mode = str(arguments.get("write_mode", "new_table")).strip()
        if write_mode not in {"new_table", "update_existing", "time_partitioned_new_table"}:
            write_mode = "new_table"

        time_grain = str(arguments.get("time_grain", "none")).strip()
        if time_grain not in {"none", "month", "quarter", "year"}:
            time_grain = "none"

        human_label = str(arguments.get("human_label", "")).strip()
        if not human_label:
            human_label = table_name.replace("_", " ").title()

        description = str(arguments.get("description", "")).strip()

        raw_primary_keys = arguments.get("primary_keys") or []
        primary_keys = [str(k).strip().lower() for k in raw_primary_keys if str(k).strip()]

        raw_match_columns = arguments.get("match_columns") or []
        match_columns = [str(c).strip().lower() for c in raw_match_columns if str(c).strip()]

        setup_seed = IngestionCatalogSetupSeed(
            business_type=business_type,  # type: ignore[arg-type]
            table_name=table_name,
            human_label=human_label,
            write_mode=write_mode,  # type: ignore[arg-type]
            time_grain=time_grain,  # type: ignore[arg-type]
            primary_keys=primary_keys,
            match_columns=match_columns,
            is_active_target=True,
            description=description,
        )

        upload_info = self._tool_inspect_upload(conn=conn, upload_id=upload_id)
        catalog_entry = self._upsert_catalog_entry_from_setup(
            conn=conn,
            workspace_id=workspace_id,
            requested_by=requested_by,
            setup_seed=setup_seed,
            upload_info=upload_info,
        )
        conn.commit()
        logger.info(
            "ingestion_catalog_entry_created job_id=%s workspace_id=%s table_name=%s business_type=%s write_mode=%s",
            job_id,
            workspace_id,
            table_name,
            business_type,
            write_mode,
        )
        return {
            "created": True,
            "catalog_entry_id": catalog_entry["id"],
            "table_name": catalog_entry["table_name"],
            "human_label": catalog_entry["human_label"],
            "business_type": catalog_entry["business_type"],
            "write_mode": catalog_entry["write_mode"],
            "time_grain": catalog_entry["time_grain"],
            "primary_keys": catalog_entry["primary_keys"],
            "match_columns": catalog_entry["match_columns"],
            "message": (
                f"Catalog entry created for table '{table_name}'. "
                "Now call describe_table_schema to get the full schema contract."
            ),
        }

    def _tool_request_human_approval(
        self,
        *,
        conn: sqlite3.Connection,
        job_id: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        stage = str(arguments.get("stage", "")).strip()
        question = str(arguments.get("question", "")).strip()
        if len(question) > 300:
            question = question[:300].rstrip()
        options = [
            str(item).strip()
            for item in arguments.get("options", [])
            if str(item).strip()
        ]
        recommended_option = str(arguments.get("recommended_option", "")).strip() or None
        if stage == "catalog_setup":
            allowed_options = CATALOG_SETUP_APPROVAL_OPTIONS
            mechanism = "catalog_setup_card"
        elif stage == "proposal_approval":
            allowed_options = DEFAULT_ACTION_OPTIONS
            mechanism = "frontend_approval_card"
        else:
            raise IngestionPlanningError(
                code="HUMAN_APPROVAL_STAGE_INVALID",
                message="Human approval stage is not supported",
                status_code=422,
            )
        if not question:
            raise IngestionPlanningError(
                code="HUMAN_APPROVAL_QUESTION_REQUIRED",
                message="Human approval question is required",
                status_code=422,
            )
        if not options or any(option not in allowed_options for option in options):
            raise IngestionPlanningError(
                code="HUMAN_APPROVAL_OPTIONS_INVALID",
                message="Human approval options are outside the designed choices",
                status_code=422,
            )
        if recommended_option and recommended_option not in options:
            raise IngestionPlanningError(
                code="HUMAN_APPROVAL_RECOMMENDATION_INVALID",
                message="Human approval recommendation must be one of the approval options",
                status_code=422,
            )
        payload = {
            "required": True,
            "status": "pending",
            "mechanism": mechanism,
            "stage": stage,
            "question": question,
            "options": options,
            "recommended_option": recommended_option,
        }
        self._insert_event(
            conn=conn,
            job_id=job_id,
            event_type="human_approval_requested",
            payload=payload,
        )
        return payload

    def _tool_build_diff_preview(
        self,
        *,
        conn: sqlite3.Connection | None = None,
        workspace_id: str | None = None,
        upload_info: dict[str, Any],
        target_table: str | None = None,
        match_columns: list[str],
        action_mode: str,
        column_mapping: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        normalized_action = action_mode.strip().lower()
        if normalized_action not in DEFAULT_ACTION_OPTIONS:
            raise IngestionPlanningError(
                code="DIFF_PREVIEW_ACTION_INVALID",
                message="Diff preview action is not supported",
                status_code=422,
            )
        sheets = upload_info["sheet_summary"].get("sheets", [])
        total_rows = max(sum(int(item.get("row_count", 0)) for item in sheets), 0)
        normalized_target = (target_table or "").strip().lower()
        target_is_valid = bool(normalized_target and SAFE_IDENTIFIER_RE.match(normalized_target))
        target_state = (
            self._physical_table_summary(workspace_id=workspace_id or "", table_name=normalized_target)
            if workspace_id and target_is_valid
            else {"exists": False, "row_count": 0, "schema": {"table_name": normalized_target, "columns": []}}
        )
        target_exists = bool(target_state.get("exists"))

        candidate_actions = self._candidate_actions_for_target_state(
            target_exists=target_exists,
            requested_action=normalized_action,
        )
        recommended_action = (
            normalized_action
            if normalized_action in candidate_actions and normalized_action != "cancel"
            else candidate_actions[0]
        )

        base_payload: dict[str, Any] = {
            "target_table": normalized_target or None,
            "target_exists": target_exists,
            "target_row_count": int(target_state.get("row_count") or 0),
            "candidate_actions": candidate_actions,
            "recommended_action": recommended_action,
            "match_columns": self._dedupe_preserve_order(match_columns),
            "computed_from": "duckdb_target_state",
        }
        if normalized_action == "cancel":
            return {
                **base_payload,
                "predicted_insert_count": 0,
                "predicted_update_count": 0,
                "predicted_conflict_count": 0,
            }
        if normalized_action in {"new_table", "time_partitioned_new_table"}:
            return {
                **base_payload,
                "predicted_insert_count": total_rows,
                "predicted_update_count": 0,
                "predicted_conflict_count": 0,
            }

        if normalized_action == "update_existing" and not target_exists:
            return {
                **base_payload,
                "predicted_insert_count": total_rows,
                "predicted_update_count": 0,
                "predicted_conflict_count": 0,
                "reason": "Target table does not exist in the workspace DuckDB; all uploaded rows would be inserted into a new physical table.",
            }

        normalized_match_columns = [
            column
            for column in self._dedupe_preserve_order(match_columns)
            if SAFE_IDENTIFIER_RE.match(column)
        ]
        if not normalized_match_columns:
            return {
                **base_payload,
                "predicted_insert_count": total_rows,
                "predicted_update_count": 0,
                "predicted_conflict_count": 0,
                "reason": "No valid match columns were provided; rows cannot be classified as updates.",
            }

        upload_path = Path(str(upload_info.get("storage_path") or ""))
        if not upload_path.exists():
            return {
                **base_payload,
                "predicted_insert_count": total_rows,
                "predicted_update_count": 0,
                "predicted_conflict_count": 0,
                "reason": "Uploaded workbook is not available for row-level preview.",
            }

        try:
            staging_dataframe, _raw_header_mapping = self._load_execution_dataframe_with_header_mapping(
                upload_path=upload_path,
                column_mapping=column_mapping,
            )
        except Exception as exc:
            logger.warning(
                "ingestion_diff_preview_upload_load_failed upload_id=%s target_table=%s error=%s",
                upload_info.get("upload_id"),
                normalized_target,
                exc,
            )
            return {
                **base_payload,
                "predicted_insert_count": total_rows,
                "predicted_update_count": 0,
                "predicted_conflict_count": 0,
                "reason": "Uploaded workbook could not be loaded for row-level preview.",
            }

        staging_columns = {str(column).strip().lower() for column in staging_dataframe.columns}
        target_columns = {
            str(item.get("name", "")).strip().lower()
            for item in target_state.get("schema", {}).get("columns", [])
            if str(item.get("name", "")).strip()
        }
        missing_in_staging = [column for column in normalized_match_columns if column not in staging_columns]
        missing_in_target = [column for column in normalized_match_columns if column not in target_columns]
        if missing_in_staging or missing_in_target:
            return {
                **base_payload,
                "predicted_insert_count": int(len(staging_dataframe)),
                "predicted_update_count": 0,
                "predicted_conflict_count": 0,
                "missing_in_staging": missing_in_staging,
                "missing_in_target": missing_in_target,
                "reason": "Match columns are not present in both uploaded data and target table.",
            }

        db_path = self._workspace_duckdb_path(workspace_id=workspace_id or "")
        preview_table = f"preview_{uuid.uuid4().hex[:12]}"
        duck_conn: duckdb.DuckDBPyConnection | None = None
        try:
            duck_conn = duckdb.connect(str(db_path))
            prepared = self._prepare_dataframe_for_staging(staging_dataframe)
            duck_conn.register("ingestion_preview_df", prepared)
            duck_conn.execute(f"CREATE OR REPLACE TEMP TABLE {preview_table} AS SELECT * FROM ingestion_preview_df")
            duck_conn.unregister("ingestion_preview_df")

            join_expr = " AND ".join([f"t.{column} = s.{column}" for column in normalized_match_columns])
            update_count = int(
                duck_conn.execute(
                    f"SELECT COUNT(*) FROM {preview_table} AS s "
                    f"WHERE EXISTS (SELECT 1 FROM {normalized_target} AS t WHERE {join_expr})"
                ).fetchone()[0]
            )
            insert_count = int(
                duck_conn.execute(
                    f"SELECT COUNT(*) FROM {preview_table} AS s "
                    f"WHERE NOT EXISTS (SELECT 1 FROM {normalized_target} AS t WHERE {join_expr})"
                ).fetchone()[0]
            )
            group_expr = ", ".join(normalized_match_columns)
            staging_duplicate_count = int(
                duck_conn.execute(
                    f"SELECT COALESCE(SUM(c), 0) FROM ("
                    f"SELECT {group_expr}, COUNT(*) AS c FROM {preview_table} "
                    f"GROUP BY {group_expr} HAVING COUNT(*) > 1"
                    f") AS dup"
                ).fetchone()[0]
            )
            target_duplicate_count = int(
                duck_conn.execute(
                    f"SELECT COALESCE(SUM(c), 0) FROM ("
                    f"SELECT {group_expr}, COUNT(*) AS c FROM {normalized_target} "
                    f"GROUP BY {group_expr} HAVING COUNT(*) > 1"
                    f") AS dup"
                ).fetchone()[0]
            )
            return {
                **base_payload,
                "predicted_insert_count": max(insert_count, 0),
                "predicted_update_count": max(update_count, 0),
                "predicted_conflict_count": max(staging_duplicate_count + target_duplicate_count, 0),
                "staging_row_count": int(len(staging_dataframe)),
                "staging_duplicate_key_count": max(staging_duplicate_count, 0),
                "target_duplicate_key_count": max(target_duplicate_count, 0),
                "match_columns": normalized_match_columns,
            }
        except Exception as exc:
            try:
                if duck_conn is not None:
                    duck_conn.unregister("ingestion_preview_df")
            except Exception:
                pass
            logger.warning(
                "ingestion_diff_preview_compute_failed workspace_id=%s upload_id=%s target_table=%s error=%s",
                workspace_id,
                upload_info.get("upload_id"),
                normalized_target,
                exc,
            )
            return {
                **base_payload,
                "predicted_insert_count": int(len(staging_dataframe)),
                "predicted_update_count": 0,
                "predicted_conflict_count": 0,
                "reason": "Row-level preview failed; falling back to insert-only impact.",
            }
        finally:
            if duck_conn is not None:
                duck_conn.close()

    @staticmethod
    def _candidate_actions_for_target_state(
        *,
        target_exists: bool,
        requested_action: str,
    ) -> list[str]:
        if target_exists:
            ordered = ["update_existing", "time_partitioned_new_table", "new_table"]
        else:
            ordered = ["new_table", "time_partitioned_new_table"]
        if requested_action in ordered:
            ordered = [requested_action, *[item for item in ordered if item != requested_action]]
        return [*ordered, "cancel"]

    def _tool_generate_write_sql_draft(
        self,
        *,
        workspace_id: str,
        job_id: str,
        target_table: str,
        action_mode: str,
        match_columns: list[str],
    ) -> dict[str, str]:
        normalized_action = action_mode.strip().lower()
        if normalized_action not in {"update_existing", "time_partitioned_new_table", "new_table"}:
            raise IngestionPlanningError(
                code="SQL_DRAFT_ACTION_INVALID",
                message="SQL draft action is not supported",
                status_code=422,
            )
        safe_target = target_table if SAFE_IDENTIFIER_RE.match(target_table) else "target_table"
        staging_name = f"staging_{job_id[:12]}"
        match_expr = " AND ".join([f"t.{value} = s.{value}" for value in match_columns]) or "1 = 0"
        if normalized_action == "new_table":
            sql = (
                f"-- workspace={workspace_id}\n"
                f"CREATE TABLE {safe_target} AS\n"
                f"SELECT * FROM {staging_name};"
            )
        elif normalized_action == "time_partitioned_new_table":
            sql = (
                f"-- workspace={workspace_id}\n"
                f"CREATE TABLE {safe_target}_{{time_partition}} AS\n"
                f"SELECT * FROM {staging_name};"
            )
        else:
            sql = (
                f"-- workspace={workspace_id}\n"
                f"MERGE INTO {safe_target} AS t\n"
                f"USING {staging_name} AS s\n"
                f"ON {match_expr}\n"
                "WHEN MATCHED THEN UPDATE SET /* mapped columns */\n"
                "WHEN NOT MATCHED THEN INSERT /* mapped columns */;"
            )

        return {"sql_draft": sql}

    def _load_job_context(
        self,
        *,
        conn: sqlite3.Connection,
        workspace_id: str,
        job_id: str,
    ) -> sqlite3.Row:
        row = conn.execute(
            """
            SELECT
                j.id,
                j.workspace_id,
                j.upload_id,
                j.status,
                j.created_by,
                j.agent_session_id
            FROM ingestion_jobs AS j
            WHERE j.id = ? AND j.workspace_id = ?
            """,
            (job_id, workspace_id),
        ).fetchone()
        if row is None:
            raise IngestionPlanningError(
                code="INGESTION_JOB_NOT_FOUND",
                message="Ingestion job not found",
                status_code=404,
            )
        if str(row["status"]) in {"executing", "succeeded", "cancelled"}:
            raise IngestionPlanningError(
                code="INGESTION_JOB_IMMUTABLE",
                message=f"Job status does not allow planning: {row['status']}",
                status_code=409,
            )
        return row

    def _insert_event(
        self,
        *,
        conn: sqlite3.Connection,
        job_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        conn.execute(
            """
            INSERT INTO ingestion_events (id, job_id, event_type, payload, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex,
                job_id,
                event_type,
                json.dumps(payload, ensure_ascii=False),
                _utc_now(),
            ),
        )

    def _connect(self) -> sqlite3.Connection:
        from ..workspaces import get_workspace_service

        conn = sqlite3.connect(get_workspace_service().db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _serialize_catalog_entry(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "workspace_id": str(row["workspace_id"]),
            "table_name": str(row["table_name"]),
            "human_label": str(row["human_label"]),
            "description": str(row["description"]),
            "business_type": str(row["business_type"]),
            "write_mode": str(row["write_mode"]),
            "time_grain": str(row["time_grain"]),
            "primary_keys": _decode_json_list(row["primary_keys"]),
            "match_columns": _decode_json_list(row["match_columns"]),
            "is_active_target": bool(row["is_active_target"]),
        }


def _decode_json_list(raw: Any) -> list[Any]:
    if isinstance(raw, list):
        return raw
    if raw is None:
        return []
    try:
        decoded = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if isinstance(decoded, list):
        return decoded
    return []


def _decode_json_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if raw is None:
        return {}
    try:
        decoded = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    if isinstance(decoded, dict):
        return decoded
    return {}


def _canonical_mcp_tool_name(tool_name: str, *, server_name: str) -> str:
    normalized = str(tool_name or "").strip()
    prefix = f"mcp__{server_name}__"
    if normalized.startswith(prefix):
        return normalized[len(prefix):]
    return normalized


def _canonical_ingestion_tool_name(tool_name: str) -> str:
    return _canonical_mcp_tool_name(tool_name, server_name=INGESTION_SDK_MCP_SERVER_NAME)


def _compact_json(payload: Any) -> str:
    try:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return str(payload)


def _preview_sql(sql: str, *, max_length: int = 600) -> str:
    normalized = re.sub(r"\s+", " ", str(sql or "")).strip()
    if len(normalized) <= max_length:
        return normalized
    return f"{normalized[: max_length - 3]}..."


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
