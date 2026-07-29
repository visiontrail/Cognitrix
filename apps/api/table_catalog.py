from __future__ import annotations

import json
import logging
import re
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any, Literal

import duckdb
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from .agentic_ingestion.schema import initialize_sqlite_schema
from .auth import AuthIdentity, require_permission
from .column_metadata import (
    enrich_column_with_metadata,
    load_table_column_metadata,
    upsert_table_column_metadata,
)
from .config import get_settings
from .data_policy import filter_schema_columns, redact_rows
from .datasets import SAFE_IDENTIFIER_RE, get_dataset_service
from .sqlite_support import connect as sqlite_connect
from .workspaces import WorkspaceError, get_workspace_service

# `BUSINESS_TYPES` is an advisory vocabulary surfaced to the agent in prompts;
# the catalog accepts any free-form snake_case string the agent proposes.
BUSINESS_TYPES = ("roster", "project_progress", "attendance", "other")
# `WRITE_MODES` and `TIME_GRAINS` ARE enforced — downstream SQL generation
# branches on these exact values, so unknown values would be unexecutable.
WRITE_MODES = ("update_existing", "time_partitioned_new_table", "new_table", "append_only")
TIME_GRAINS = ("none", "month", "quarter", "year")
# Catalog entries created by the agent's `save_web_research` tool. Web-research
# tables reuse the existing catalog schema unchanged: free-form business_type,
# write_mode 'new_table' (the tool CREATE OR REPLACEs the whole table) and
# time_grain 'none'. They are never ingestion write targets.
WEB_RESEARCH_BUSINESS_TYPE = "web_research"
WEB_RESEARCH_PROVENANCE_COLUMNS = (
    {"name": "_source_url", "type": "VARCHAR", "description": "Source URL"},
    {"name": "_source_title", "type": "VARCHAR", "description": "Source title"},
    {"name": "_retrieved_at", "type": "TIMESTAMP", "description": "Retrieved at (UTC)"},
)
BUSINESS_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
TABLE_NAME_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
logger = logging.getLogger("cognitrix.table_catalog")


class TableCatalogError(Exception):
    def __init__(self, *, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code

    def to_detail(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
        }


class TableCatalogEntryUpdateRequest(BaseModel):
    table_name: str | None = Field(default=None, min_length=1, max_length=128)
    human_label: str | None = Field(default=None, min_length=1, max_length=120)
    business_type: str | None = None
    write_mode: Literal[
        "update_existing",
        "time_partitioned_new_table",
        "new_table",
        "append_only",
    ] | None = None
    time_grain: Literal["none", "month", "quarter", "year"] | None = None
    primary_keys: list[str] | None = None
    match_columns: list[str] | None = None
    is_active_target: bool | None = None
    description: str | None = Field(default=None, max_length=1000)

    @field_validator("table_name")
    @classmethod
    def validate_table_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not TABLE_NAME_PATTERN.match(normalized):
            raise ValueError("table_name must be a valid SQL identifier")
        return normalized.lower()

    @field_validator("business_type")
    @classmethod
    def validate_business_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("business_type cannot be empty")
        if not BUSINESS_TYPE_PATTERN.match(normalized):
            raise ValueError(
                "business_type must be snake_case ASCII (a-z, 0-9, _; start with a letter)"
            )
        return normalized

    @field_validator("human_label")
    @classmethod
    def validate_human_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("human_label cannot be empty")
        return normalized

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()

    @field_validator("primary_keys", "match_columns")
    @classmethod
    def validate_column_lists(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        return _normalize_column_list(values)


@dataclass(slots=True)
class TableCatalogService:
    db_path: Path
    _lock: Lock = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._initialize_schema()

    def list_entries(self, *, workspace_id: str) -> list[dict[str, Any]]:
        normalized_workspace_id = workspace_id.strip()
        if not normalized_workspace_id:
            raise TableCatalogError(
                code="WORKSPACE_NOT_FOUND",
                message="Workspace not found",
                status_code=404,
            )

        with self._lock, self._connect() as conn:
            self._assert_workspace_exists(conn, workspace_id=normalized_workspace_id)
            rows = conn.execute(
                """
                SELECT *
                FROM table_catalog
                WHERE workspace_id = ?
                ORDER BY business_type ASC, is_active_target DESC, updated_at DESC
                """,
                (normalized_workspace_id,),
            ).fetchall()

        return [self._serialize_entry(row) for row in rows]

    def get_entry(self, *, workspace_id: str, catalog_id: str) -> dict[str, Any]:
        row = self._get_entry_row(workspace_id=workspace_id, catalog_id=catalog_id)
        return self._serialize_entry(row)

    def update_entry(
        self,
        *,
        workspace_id: str,
        catalog_id: str,
        actor_user_id: str,
        payload: TableCatalogEntryUpdateRequest,
    ) -> dict[str, Any]:
        normalized_workspace_id = workspace_id.strip()
        normalized_catalog_id = catalog_id.strip()
        normalized_actor = actor_user_id.strip()
        updates = payload.model_dump(exclude_none=True)

        with self._lock, self._connect() as conn:
            self._assert_workspace_exists(conn, workspace_id=normalized_workspace_id)
            self._ensure_user_record(conn, user_id=normalized_actor)

            current = conn.execute(
                "SELECT * FROM table_catalog WHERE id = ? AND workspace_id = ?",
                (normalized_catalog_id, normalized_workspace_id),
            ).fetchone()
            if current is None:
                raise TableCatalogError(
                    code="CATALOG_ENTRY_NOT_FOUND",
                    message="Catalog entry not found",
                    status_code=404,
                )

            if updates:
                business_type = str(updates.get("business_type") or current["business_type"])
                is_active_target = bool(
                    updates.get("is_active_target", bool(current["is_active_target"]))
                )

                if is_active_target:
                    conn.execute(
                        """
                        UPDATE table_catalog
                        SET is_active_target = 0, updated_by = ?, updated_at = ?
                        WHERE workspace_id = ? AND business_type = ? AND id != ?
                        """,
                        (
                            normalized_actor,
                            _utc_now(),
                            normalized_workspace_id,
                            business_type,
                            normalized_catalog_id,
                        ),
                    )

                assignments: list[str] = []
                values: list[Any] = []
                for field_name in (
                    "table_name",
                    "human_label",
                    "business_type",
                    "write_mode",
                    "time_grain",
                    "description",
                    "is_active_target",
                ):
                    if field_name in updates:
                        assignments.append(f"{field_name} = ?")
                        field_value: Any = updates[field_name]
                        if field_name == "is_active_target":
                            field_value = int(bool(field_value))
                        values.append(field_value)

                if "primary_keys" in updates:
                    assignments.append("primary_keys = ?")
                    values.append(json.dumps(updates["primary_keys"], ensure_ascii=False))

                if "match_columns" in updates:
                    assignments.append("match_columns = ?")
                    values.append(json.dumps(updates["match_columns"], ensure_ascii=False))

                if assignments:
                    assignments.extend(("updated_by = ?", "updated_at = ?"))
                    values.extend((normalized_actor, _utc_now(), normalized_catalog_id, normalized_workspace_id))
                    conn.execute(
                        f"""
                        UPDATE table_catalog
                        SET {", ".join(assignments)}
                        WHERE id = ? AND workspace_id = ?
                        """,
                        tuple(values),
                    )
                    conn.commit()

            row = conn.execute(
                "SELECT * FROM table_catalog WHERE id = ? AND workspace_id = ?",
                (normalized_catalog_id, normalized_workspace_id),
            ).fetchone()

        if row is None:
            raise TableCatalogError(
                code="CATALOG_ENTRY_NOT_FOUND",
                message="Catalog entry not found",
                status_code=404,
            )

        return self._serialize_entry(row)

    def register_web_research_entry(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
        table_name: str,
        human_label: str,
        description: str,
        columns: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Upsert a catalog entry for a `web_research_*` table.

        Keyed on (workspace_id, business_type='web_research', table_name) so a
        repeated save into the same table (CREATE OR REPLACE semantics) refreshes
        the existing entry instead of duplicating it. Entries are never ingestion
        write targets (is_active_target=0).
        """
        normalized_workspace_id = workspace_id.strip()
        normalized_table = table_name.strip()
        if not TABLE_NAME_PATTERN.match(normalized_table):
            raise TableCatalogError(
                code="CATALOG_TABLE_NAME_INVALID",
                message="table_name must be a valid SQL identifier",
                status_code=400,
            )
        normalized_label = human_label.strip()[:120] or normalized_table
        normalized_description = description.strip()[:1000]
        now = _utc_now()

        with self._lock, self._connect() as conn:
            self._assert_workspace_exists(conn, workspace_id=normalized_workspace_id)
            self._ensure_user_record(conn, user_id=actor_user_id.strip())

            existing = conn.execute(
                """
                SELECT id FROM table_catalog
                WHERE workspace_id = ? AND business_type = ? AND table_name = ?
                """,
                (normalized_workspace_id, WEB_RESEARCH_BUSINESS_TYPE, normalized_table),
            ).fetchone()
            if existing is None:
                catalog_id = uuid.uuid4().hex
                conn.execute(
                    """
                    INSERT INTO table_catalog (
                        id, workspace_id, table_name, human_label, business_type,
                        write_mode, time_grain, primary_keys, match_columns,
                        is_active_target, description, created_by, updated_by,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'new_table', 'none', '[]', '[]', 0, ?, ?, ?, ?, ?)
                    """,
                    (
                        catalog_id,
                        normalized_workspace_id,
                        normalized_table,
                        normalized_label,
                        WEB_RESEARCH_BUSINESS_TYPE,
                        normalized_description,
                        actor_user_id.strip(),
                        actor_user_id.strip(),
                        now,
                        now,
                    ),
                )
            else:
                catalog_id = str(existing["id"])
                conn.execute(
                    """
                    UPDATE table_catalog
                    SET human_label = ?, description = ?, updated_by = ?, updated_at = ?
                    WHERE id = ? AND workspace_id = ?
                    """,
                    (
                        normalized_label,
                        normalized_description,
                        actor_user_id.strip(),
                        now,
                        catalog_id,
                        normalized_workspace_id,
                    ),
                )

            if columns:
                metadata_columns = [
                    {"name": str(column.get("name") or ""), "type": str(column.get("type") or "")}
                    for column in columns
                ]
                metadata_columns.extend(dict(column) for column in WEB_RESEARCH_PROVENANCE_COLUMNS)
                upsert_table_column_metadata(
                    conn,
                    workspace_id=normalized_workspace_id,
                    table_name=normalized_table,
                    columns=metadata_columns,
                    updated_at=now,
                )
            conn.commit()

            row = conn.execute(
                "SELECT * FROM table_catalog WHERE id = ? AND workspace_id = ?",
                (catalog_id, normalized_workspace_id),
            ).fetchone()

        if row is None:
            raise TableCatalogError(
                code="CATALOG_ENTRY_NOT_FOUND",
                message="Catalog entry not found after registration",
                status_code=500,
            )
        return self._serialize_entry(row)

    def delete_entry(self, *, workspace_id: str, catalog_id: str) -> None:
        normalized_workspace_id = workspace_id.strip()
        normalized_catalog_id = catalog_id.strip()

        with self._lock, self._connect() as conn:
            self._assert_workspace_exists(conn, workspace_id=normalized_workspace_id)
            existing = conn.execute(
                "SELECT id FROM table_catalog WHERE id = ? AND workspace_id = ?",
                (normalized_catalog_id, normalized_workspace_id),
            ).fetchone()
            if existing is None:
                raise TableCatalogError(
                    code="CATALOG_ENTRY_NOT_FOUND",
                    message="Catalog entry not found",
                    status_code=404,
                )

            conn.execute(
                "DELETE FROM table_catalog WHERE id = ? AND workspace_id = ?",
                (normalized_catalog_id, normalized_workspace_id),
            )
            conn.commit()

    def get_active_target(
        self,
        *,
        workspace_id: str,
        business_type: str,
    ) -> dict[str, Any] | None:
        normalized_workspace_id = workspace_id.strip()

        with self._lock, self._connect() as conn:
            self._assert_workspace_exists(conn, workspace_id=normalized_workspace_id)
            row = conn.execute(
                """
                SELECT *
                FROM table_catalog
                WHERE workspace_id = ?
                  AND business_type = ?
                  AND is_active_target = 1
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (normalized_workspace_id, business_type),
            ).fetchone()

        if row is None:
            return None
        return self._serialize_entry(row)

    def preview_table_data(
        self,
        *,
        workspace_id: str,
        catalog_id: str,
        actor_user_id: str,
        actor_project_id: str,
        actor_role: str,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        entry = self.get_entry(workspace_id=workspace_id, catalog_id=catalog_id)
        table_name = str(entry["table_name"]).strip()
        if not SAFE_IDENTIFIER_RE.match(table_name):
            raise TableCatalogError(
                code="CATALOG_TABLE_NAME_INVALID",
                message="Catalog table name is not a valid SQL identifier",
                status_code=400,
            )

        settings = get_settings()
        dataset_service = get_dataset_service(
            settings.upload_dir,
            ai_api_key=settings.ai_api_key,
            ai_model=settings.ai_model,
            ai_base_url=settings.model_provider_url,
            ai_timeout=settings.ai_timeout_seconds,
        )

        resolved_table = table_name
        try:
            with dataset_service.session_manager.connection(
                actor_user_id,
                actor_project_id,
                workspace_id=workspace_id,
            ) as duck_conn:
                available_tables = {
                    str(row[0]).strip().lower(): str(row[0]).strip()
                    for row in duck_conn.execute("SHOW TABLES").fetchall()
                }
                resolved_table = (
                    available_tables.get(table_name.lower())
                    or self._resolve_recent_execution_table(
                        workspace_id=workspace_id,
                        logical_table_name=table_name,
                        available_tables=available_tables,
                    )
                )
                if resolved_table is None:
                    raise TableCatalogError(
                        code="CATALOG_TABLE_DATA_NOT_FOUND",
                        message="No physical data table has been written for this catalog entry yet",
                        status_code=404,
                    )

                column_rows = duck_conn.execute(f'PRAGMA table_info("{resolved_table}")').fetchall()
                row_count = int(duck_conn.execute(f'SELECT COUNT(*) FROM "{resolved_table}"').fetchone()[0])
                cursor = duck_conn.execute(
                    f'SELECT * FROM "{resolved_table}" LIMIT {limit} OFFSET {offset}'
                )
                column_names = [str(column[0]) for column in (cursor.description or [])]
                rows = [dict(zip(column_names, row)) for row in cursor.fetchall()]
        except TableCatalogError:
            raise
        except duckdb.Error as exc:
            raise TableCatalogError(
                code="CATALOG_TABLE_DATA_READ_FAILED",
                message="Failed to read table data",
                status_code=500,
            ) from exc

        column_metadata: dict[str, dict[str, Any]] = {}
        column_labels: dict[str, str] = {}
        with self._lock, self._connect() as sqlite_conn:
            column_metadata = load_table_column_metadata(
                sqlite_conn,
                workspace_id=workspace_id,
                table_names=[resolved_table, table_name],
            )
            label_row = sqlite_conn.execute(
                """
                SELECT proposal_json FROM ingestion_proposals
                WHERE workspace_id = ? AND (target_table = ? OR target_table = ?)
                ORDER BY created_at DESC LIMIT 1
                """,
                (workspace_id, table_name, resolved_table),
            ).fetchone()
            if label_row is not None:
                try:
                    mapping = json.loads(label_row["proposal_json"]).get("column_mapping", {})
                    column_labels = {v: k for k, v in mapping.items()}
                except (json.JSONDecodeError, AttributeError, TypeError):
                    pass

        typed_columns = []
        for item in column_rows:
            column_name = str(item[1])
            fallback_label = column_labels.get(column_name)
            typed_column = enrich_column_with_metadata(
                {
                    "name": column_name,
                    "type": str(item[2]),
                    "nullable": not bool(item[3]),
                    "primary_key": bool(item[5]),
                    "label": fallback_label,
                    "original_name": fallback_label,
                    "description": fallback_label,
                },
                column_metadata,
            )
            typed_columns.append(typed_column)
        typed_columns = [
            {
                **column,
                "label": column.get("label") or None,
                "original_name": column.get("original_name") or None,
                "description": column.get("description") or None,
            }
            for column in typed_columns
        ]
        safe_columns = filter_schema_columns(typed_columns, role=actor_role)
        safe_column_names = [str(item["name"]) for item in safe_columns]
        redacted_rows = redact_rows(rows, role=actor_role)
        visible_rows = [
            {column_name: row.get(column_name) for column_name in safe_column_names}
            for row in redacted_rows
        ]

        return {
            "entry": entry,
            "table": resolved_table,
            "row_count": row_count,
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(visible_rows) < row_count,
            "columns": safe_columns,
            "rows": visible_rows,
        }

    def _resolve_recent_execution_table(
        self,
        *,
        workspace_id: str,
        logical_table_name: str,
        available_tables: dict[str, str],
    ) -> str | None:
        normalized_logical = logical_table_name.strip().lower()
        if not normalized_logical:
            return None

        with self._lock, self._connect() as sqlite_conn:
            rows = sqlite_conn.execute(
                """
                SELECT e.execution_receipt, p.proposal_json
                FROM ingestion_executions AS e
                JOIN ingestion_proposals AS p ON p.id = e.proposal_id
                WHERE e.workspace_id = ? AND e.status = 'succeeded'
                ORDER BY COALESCE(e.finished_at, e.started_at) DESC
                LIMIT 25
                """,
                (workspace_id,),
            ).fetchall()

        for row in rows:
            receipt = _decode_json_dict(row["execution_receipt"])
            proposal = _decode_json_dict(row["proposal_json"])
            receipt_target = str(receipt.get("target_table") or "").strip().lower()
            proposal_target = str(proposal.get("target_table") or "").strip().lower()
            if not receipt_target:
                continue
            if (
                proposal_target == normalized_logical
                or receipt_target == normalized_logical
                or receipt_target.startswith(f"{normalized_logical}_")
            ):
                resolved = available_tables.get(receipt_target)
                if resolved:
                    return resolved
        return None

    def _get_entry_row(self, *, workspace_id: str, catalog_id: str) -> sqlite3.Row:
        normalized_workspace_id = workspace_id.strip()
        normalized_catalog_id = catalog_id.strip()

        with self._lock, self._connect() as conn:
            self._assert_workspace_exists(conn, workspace_id=normalized_workspace_id)
            row = conn.execute(
                "SELECT * FROM table_catalog WHERE id = ? AND workspace_id = ?",
                (normalized_catalog_id, normalized_workspace_id),
            ).fetchone()

        if row is None:
            raise TableCatalogError(
                code="CATALOG_ENTRY_NOT_FOUND",
                message="Catalog entry not found",
                status_code=404,
            )

        return row

    def _initialize_schema(self) -> None:
        with self._connect() as conn:
            initialize_sqlite_schema(conn)

    def _connect(self) -> sqlite3.Connection:
        return sqlite_connect(self.db_path, foreign_keys=True)

    def _assert_workspace_exists(self, conn: sqlite3.Connection, *, workspace_id: str) -> None:
        row = conn.execute(
            "SELECT id FROM workspaces WHERE id = ? AND status = 'active'",
            (workspace_id,),
        ).fetchone()
        if row is None:
            raise TableCatalogError(
                code="WORKSPACE_NOT_FOUND",
                message="Workspace not found",
                status_code=404,
            )

    def _ensure_user_record(self, conn: sqlite3.Connection, *, user_id: str) -> None:
        normalized_user = user_id.strip()
        if not normalized_user:
            raise TableCatalogError(
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
    def _list_table_names(conn: sqlite3.Connection, *, workspace_id: str) -> set[str]:
        rows = conn.execute(
            "SELECT table_name FROM table_catalog WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchall()
        return {str(row["table_name"]).strip().lower() for row in rows if str(row["table_name"]).strip()}

    @staticmethod
    def _serialize_entry(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "workspace_id": str(row["workspace_id"]),
            "table_name": str(row["table_name"]),
            "human_label": str(row["human_label"]),
            "business_type": str(row["business_type"]),
            "write_mode": str(row["write_mode"]),
            "time_grain": str(row["time_grain"]),
            "primary_keys": _decode_json_list(row["primary_keys"]),
            "match_columns": _decode_json_list(row["match_columns"]),
            "is_active_target": bool(row["is_active_target"]),
            "description": str(row["description"]),
            "created_by": str(row["created_by"]),
            "updated_by": str(row["updated_by"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }


router = APIRouter(prefix="/workspaces/{workspace_id}/catalog", tags=["table-catalog"])


@router.get("")
async def list_table_catalog_entries(
    workspace_id: str,
    identity: AuthIdentity = Depends(require_permission("workspaces:read")),
) -> dict[str, Any]:
    _assert_workspace_role(workspace_id=workspace_id, identity=identity, minimum_role="editor")
    service = get_table_catalog_service()
    try:
        entries = service.list_entries(workspace_id=workspace_id)
    except TableCatalogError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc

    return {
        "count": len(entries),
        "entries": entries,
    }


@router.get("/active-target")
async def get_active_catalog_target(
    workspace_id: str,
    business_type: str,
    identity: AuthIdentity = Depends(require_permission("workspaces:read")),
) -> dict[str, Any]:
    _assert_workspace_role(workspace_id=workspace_id, identity=identity, minimum_role="editor")
    service = get_table_catalog_service()
    try:
        entry = service.get_active_target(workspace_id=workspace_id, business_type=business_type)
    except TableCatalogError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc

    if entry is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "CATALOG_ACTIVE_TARGET_NOT_FOUND",
                "message": "No active catalog target found for the requested business type",
            },
        )

    return {"entry": entry}


@router.get("/{catalog_id}")
async def get_table_catalog_entry(
    workspace_id: str,
    catalog_id: str,
    identity: AuthIdentity = Depends(require_permission("workspaces:read")),
) -> dict[str, Any]:
    _assert_workspace_role(workspace_id=workspace_id, identity=identity, minimum_role="editor")
    service = get_table_catalog_service()
    try:
        entry = service.get_entry(workspace_id=workspace_id, catalog_id=catalog_id)
    except TableCatalogError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc

    return {"entry": entry}


@router.get("/{catalog_id}/data")
async def preview_table_catalog_data(
    workspace_id: str,
    catalog_id: str,
    limit: int = 100,
    offset: int = 0,
    identity: AuthIdentity = Depends(require_permission("workspaces:read")),
) -> dict[str, Any]:
    _assert_workspace_role(workspace_id=workspace_id, identity=identity, minimum_role="editor")
    bounded_limit = max(1, min(int(limit), 200))
    bounded_offset = max(0, int(offset))
    service = get_table_catalog_service()
    try:
        return service.preview_table_data(
            workspace_id=workspace_id,
            catalog_id=catalog_id,
            actor_user_id=identity.user_id,
            actor_project_id=identity.project_id,
            actor_role=identity.role,
            limit=bounded_limit,
            offset=bounded_offset,
        )
    except TableCatalogError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc


@router.patch("/{catalog_id}")
async def update_table_catalog_entry(
    workspace_id: str,
    catalog_id: str,
    request: TableCatalogEntryUpdateRequest,
    identity: AuthIdentity = Depends(require_permission("workspaces:write")),
) -> dict[str, Any]:
    _assert_workspace_role(workspace_id=workspace_id, identity=identity, minimum_role="editor")
    service = get_table_catalog_service()
    try:
        entry = service.update_entry(
            workspace_id=workspace_id,
            catalog_id=catalog_id,
            actor_user_id=identity.user_id,
            payload=request,
        )
    except TableCatalogError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc

    return {"entry": entry}


@router.delete("/{catalog_id}")
async def delete_table_catalog_entry(
    workspace_id: str,
    catalog_id: str,
    identity: AuthIdentity = Depends(require_permission("workspaces:manage")),
) -> dict[str, str]:
    _assert_workspace_role(workspace_id=workspace_id, identity=identity, minimum_role="admin")
    service = get_table_catalog_service()
    try:
        service.delete_entry(workspace_id=workspace_id, catalog_id=catalog_id)
    except TableCatalogError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc

    return {"status": "deleted", "catalog_id": catalog_id}


def _assert_workspace_role(*, workspace_id: str, identity: AuthIdentity, minimum_role: str) -> str:
    workspace_service = get_workspace_service()
    try:
        return workspace_service.assert_workspace_access(
            workspace_id=workspace_id,
            user_id=identity.user_id,
            minimum_role=minimum_role,
        )
    except WorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc


@lru_cache(maxsize=2)
def _cached_table_catalog_service(db_path: str) -> TableCatalogService:
    return TableCatalogService(db_path=Path(db_path).resolve())


def get_table_catalog_service() -> TableCatalogService:
    workspace_service = get_workspace_service()
    return _cached_table_catalog_service(str(workspace_service.db_path))


def clear_table_catalog_service_cache() -> None:
    _cached_table_catalog_service.cache_clear()


def _normalize_column_list(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        trimmed = value.strip()
        if not trimmed:
            continue
        lowered = trimmed.lower()
        if lowered not in normalized:
            normalized.append(lowered)
    return normalized


def _decode_json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]

    if not isinstance(value, str):
        return []

    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return []

    if not isinstance(decoded, list):
        return []

    return [str(item) for item in decoded]


def _decode_json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value

    if not isinstance(value, str):
        return {}

    try:
        decoded = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}

    if not isinstance(decoded, dict):
        return {}

    return decoded


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
