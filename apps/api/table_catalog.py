from __future__ import annotations

import json
import logging
import re
import sqlite3
import socket
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any, Literal
from urllib import error as urllib_error
from urllib import request as urllib_request

import duckdb
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from .agentic_ingestion.schema import initialize_sqlite_schema
from .auth import AuthIdentity, require_permission
from .config import get_settings
from .data_policy import filter_schema_columns, redact_rows
from .datasets import SAFE_IDENTIFIER_RE, get_dataset_service
from .workspaces import WorkspaceError, get_workspace_service

BUSINESS_TYPES = ("roster", "project_progress", "attendance", "other")
WRITE_MODES = ("update_existing", "time_partitioned_new_table", "new_table", "append_only")
TIME_GRAINS = ("none", "month", "quarter", "year")
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


class TableCatalogEntryCreateRequest(BaseModel):
    table_name: str | None = Field(default=None, min_length=1, max_length=128)
    human_label: str = Field(min_length=1, max_length=120)
    business_type: Literal["roster", "project_progress", "attendance", "other"] = "other"
    write_mode: Literal[
        "update_existing",
        "time_partitioned_new_table",
        "new_table",
        "append_only",
    ] = "new_table"
    time_grain: Literal["none", "month", "quarter", "year"] = "none"
    primary_keys: list[str] = Field(default_factory=list)
    match_columns: list[str] = Field(default_factory=list)
    is_active_target: bool = False
    description: str = Field(default="", max_length=1000)

    @field_validator("table_name")
    @classmethod
    def validate_table_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not TABLE_NAME_PATTERN.match(normalized):
            raise ValueError("table_name must be a valid SQL identifier")
        return normalized.lower()

    @field_validator("human_label")
    @classmethod
    def validate_human_label(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("human_label cannot be empty")
        return normalized

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        return value.strip()

    @field_validator("primary_keys", "match_columns")
    @classmethod
    def validate_column_lists(cls, values: list[str]) -> list[str]:
        return _normalize_column_list(values)


class TableCatalogEntryUpdateRequest(BaseModel):
    table_name: str | None = Field(default=None, min_length=1, max_length=128)
    human_label: str | None = Field(default=None, min_length=1, max_length=120)
    business_type: Literal["roster", "project_progress", "attendance", "other"] | None = None
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

    def create_entry(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
        payload: TableCatalogEntryCreateRequest,
    ) -> dict[str, Any]:
        normalized_workspace_id = workspace_id.strip()
        normalized_actor = actor_user_id.strip()
        catalog_id = uuid.uuid4().hex
        now = _utc_now()

        with self._lock, self._connect() as conn:
            self._assert_workspace_exists(conn, workspace_id=normalized_workspace_id)
            self._ensure_user_record(conn, user_id=normalized_actor)
            existing_table_names = self._list_table_names(conn, workspace_id=normalized_workspace_id)

        generated_table_name = payload.table_name is None
        candidate_table_name = payload.table_name or _generate_table_name_with_ai(
            human_label=payload.human_label,
            description=payload.description,
            existing_table_names=existing_table_names,
        )

        with self._lock, self._connect() as conn:
            self._assert_workspace_exists(conn, workspace_id=normalized_workspace_id)
            self._ensure_user_record(conn, user_id=normalized_actor)
            current_table_names = self._list_table_names(conn, workspace_id=normalized_workspace_id)
            table_name = (
                _dedupe_table_name(candidate_table_name, current_table_names)
                if generated_table_name
                else candidate_table_name
            )

            if payload.is_active_target:
                conn.execute(
                    """
                    UPDATE table_catalog
                    SET is_active_target = 0, updated_by = ?, updated_at = ?
                    WHERE workspace_id = ? AND business_type = ?
                    """,
                    (normalized_actor, now, normalized_workspace_id, payload.business_type),
                )

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
                    normalized_workspace_id,
                    table_name,
                    payload.human_label,
                    payload.business_type,
                    payload.write_mode,
                    payload.time_grain,
                    json.dumps(payload.primary_keys, ensure_ascii=False),
                    json.dumps(payload.match_columns, ensure_ascii=False),
                    int(payload.is_active_target),
                    payload.description,
                    normalized_actor,
                    normalized_actor,
                    now,
                    now,
                ),
            )
            conn.commit()

            row = conn.execute(
                "SELECT * FROM table_catalog WHERE id = ? AND workspace_id = ?",
                (catalog_id, normalized_workspace_id),
            ).fetchone()

        if row is None:
            raise TableCatalogError(
                code="CATALOG_ENTRY_NOT_FOUND",
                message="Catalog entry not found",
                status_code=404,
            )

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
        business_type: Literal["roster", "project_progress", "attendance", "other"],
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

        column_labels: dict[str, str] = {}
        with self._lock, self._connect() as sqlite_conn:
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

        typed_columns = [
            {
                "name": str(item[1]),
                "type": str(item[2]),
                "nullable": not bool(item[3]),
                "primary_key": bool(item[5]),
                "label": column_labels.get(str(item[1])),
            }
            for item in column_rows
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
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

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


@router.post("")
async def create_table_catalog_entry(
    workspace_id: str,
    request: TableCatalogEntryCreateRequest,
    identity: AuthIdentity = Depends(require_permission("workspaces:write")),
) -> dict[str, Any]:
    _assert_workspace_role(workspace_id=workspace_id, identity=identity, minimum_role="editor")
    service = get_table_catalog_service()
    try:
        entry = service.create_entry(
            workspace_id=workspace_id,
            actor_user_id=identity.user_id,
            payload=request,
        )
    except TableCatalogError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc

    return {"entry": entry}


@router.get("")
async def list_table_catalog_entries(
    workspace_id: str,
    identity: AuthIdentity = Depends(require_permission("workspaces:read")),
) -> dict[str, Any]:
    _assert_workspace_role(workspace_id=workspace_id, identity=identity, minimum_role="viewer")
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
    business_type: Literal["roster", "project_progress", "attendance", "other"],
    identity: AuthIdentity = Depends(require_permission("workspaces:read")),
) -> dict[str, Any]:
    _assert_workspace_role(workspace_id=workspace_id, identity=identity, minimum_role="viewer")
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
    _assert_workspace_role(workspace_id=workspace_id, identity=identity, minimum_role="viewer")
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
    _assert_workspace_role(workspace_id=workspace_id, identity=identity, minimum_role="viewer")
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


def _generate_table_name_with_ai(
    *,
    human_label: str,
    description: str,
    existing_table_names: set[str],
) -> str:
    settings = get_settings()
    if not settings.model_provider_url.strip() or not settings.ai_api_key.strip() or not settings.ai_model.strip():
        raise TableCatalogError(
            code="TABLE_NAME_AI_NOT_CONFIGURED",
            message="AI table name generation is not configured",
            status_code=503,
        )

    payload: dict[str, Any] = {
        "model": settings.ai_model,
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You generate concise SQL table names for business datasets. "
                    "Return only JSON: {\"table_name\":\"...\"}. "
                    "The table_name must be English, lowercase snake_case, start with a letter or underscore, "
                    "contain only letters, numbers, and underscores, be at most 48 characters, "
                    "and must not be a generic sequence like table1, table2, workspace_table, or business_table."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "display_name": human_label,
                        "description": description,
                        "existing_table_names": sorted(existing_table_names),
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    }
    response = _post_table_name_ai_request(
        base_url=settings.model_provider_url,
        api_key=settings.ai_api_key,
        timeout_seconds=settings.ai_timeout_seconds,
        payload=payload,
    )
    candidate = _extract_ai_table_name(response)
    normalized = _normalize_ai_table_name(candidate)
    if not normalized:
        raise TableCatalogError(
            code="TABLE_NAME_AI_INVALID_RESPONSE",
            message="AI did not return a valid table name",
            status_code=502,
        )
    return normalized


def _post_table_name_ai_request(
    *,
    base_url: str,
    api_key: str,
    timeout_seconds: float,
    payload: dict[str, Any],
) -> dict[str, Any]:
    endpoint = _chat_completions_endpoint(base_url)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    request = urllib_request.Request(endpoint, data=body, headers=headers, method="POST")

    try:
        with urllib_request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except TimeoutError as exc:
        raise TableCatalogError(
            code="TABLE_NAME_AI_TIMEOUT",
            message="AI table name generation timed out",
            status_code=504,
        ) from exc
    except socket.timeout as exc:
        raise TableCatalogError(
            code="TABLE_NAME_AI_TIMEOUT",
            message="AI table name generation timed out",
            status_code=504,
        ) from exc
    except urllib_error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="ignore") if hasattr(exc, "read") else ""
        logger.warning("table_name_ai_http_error status=%s details=%s", exc.code, details or exc.reason)
        raise TableCatalogError(
            code="TABLE_NAME_AI_HTTP_ERROR",
            message="AI table name generation failed",
            status_code=502,
        ) from exc
    except urllib_error.URLError as exc:
        logger.warning("table_name_ai_request_error reason=%s", exc.reason)
        raise TableCatalogError(
            code="TABLE_NAME_AI_REQUEST_FAILED",
            message="AI table name generation request failed",
            status_code=502,
        ) from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TableCatalogError(
            code="TABLE_NAME_AI_NON_JSON",
            message="AI table name generation returned invalid JSON",
            status_code=502,
        ) from exc
    if not isinstance(parsed, dict):
        raise TableCatalogError(
            code="TABLE_NAME_AI_NON_JSON",
            message="AI table name generation returned invalid JSON",
            status_code=502,
        )
    return parsed


def _extract_ai_table_name(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""

    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first, dict) else {}
    content = message.get("content") if isinstance(message, dict) else None
    text = _content_to_text(content)
    if not text:
        return ""

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = _json_from_text_block(text)
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("table_name") or "")


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                chunks.append(text.strip())
        return "\n".join(chunks).strip()
    return ""


def _json_from_text_block(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped, flags=re.IGNORECASE).strip()
        stripped = re.sub(r"```$", "", stripped).strip()

    match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
    if not match:
        return {}
    try:
        decoded = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _normalize_ai_table_name(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", value.strip().lower()).strip("_")
    if not TABLE_NAME_PATTERN.match(normalized):
        return ""
    if normalized in {"table", "table1", "table2", "workspace_table", "business_table"}:
        return ""
    if re.fullmatch(r"table_?\d+", normalized):
        return ""
    return normalized[:48]


def _dedupe_table_name(table_name: str, existing_table_names: set[str]) -> str:
    normalized_existing = {item.lower() for item in existing_table_names}
    if table_name.lower() not in normalized_existing:
        return table_name

    index = 2
    base = table_name[:124]
    candidate = f"{base}_{index}"
    while candidate.lower() in normalized_existing:
        index += 1
        suffix = f"_{index}"
        candidate = f"{table_name[: 128 - len(suffix)]}{suffix}"
    return candidate


def _chat_completions_endpoint(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    if normalized.endswith("/v1"):
        return f"{normalized}/chat/completions"
    return f"{normalized}/v1/chat/completions"


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
