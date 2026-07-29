from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import unquote, urlparse

from .config import get_settings
from .sqlite_support import connect as sqlite_connect

SQLITE_RELATIVE_BASE = Path(__file__).resolve().parent


class ViewStorageError(Exception):
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
class SaveViewInput:
    user_id: str
    project_id: str
    dataset_table: str
    role: str
    department: str | None
    clearance: int
    title: str
    ai_state: dict[str, Any]
    conversation_id: str | None = None
    view_id: str | None = None
    metadata: dict[str, Any] | None = None
    # Optional: workspace this view belongs to. Pre-existing rows in the
    # ai_views table predate the column; new saves populate it so workspace
    # delete-cascade can reap them. Legacy callers that don't pass workspace_id
    # still work — their views just leak on workspace delete (documented).
    workspace_id: str | None = None


@dataclass(slots=True)
class RollbackInput:
    user_id: str
    project_id: str
    role: str
    department: str | None
    clearance: int
    target_version: int


class ViewStorageService:
    def __init__(self, *, db_path: Path, audit_log_path: Path) -> None:
        self.db_path = db_path
        self.audit_log_path = audit_log_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._init_schema()

    def save_view(self, payload: SaveViewInput) -> dict[str, Any]:
        if not payload.user_id.strip():
            raise ViewStorageError(
                code="AUTH_REQUIRED",
                message="user_id is required",
                status_code=401,
            )

        if not payload.project_id.strip():
            raise ViewStorageError(
                code="PROJECT_REQUIRED",
                message="project_id is required",
                status_code=422,
            )

        started = time.perf_counter()
        now = _utc_now()
        normalized_title = payload.title.strip() or "Saved View"
        view_id = str(payload.view_id).strip() if payload.view_id is not None else uuid.uuid4().hex

        with self._lock, self._connect() as conn:
            existing = conn.execute(
                """
                SELECT view_id, owner_user_id, owner_project_id, current_version
                FROM ai_views
                WHERE view_id = ?
                """,
                (view_id,),
            ).fetchone()

            if existing is None:
                current_version = 1
                conn.execute(
                    """
                    INSERT INTO ai_views (
                        view_id,
                        owner_user_id,
                        owner_project_id,
                        workspace_id,
                        dataset_table,
                        title,
                        conversation_id,
                        rbac_scope,
                        ai_state,
                        current_version,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        view_id,
                        payload.user_id,
                        payload.project_id,
                        (payload.workspace_id or "").strip() or None,
                        payload.dataset_table,
                        normalized_title,
                        payload.conversation_id,
                        self._encode_json(
                            {
                                "owner_role": payload.role,
                                "owner_department": payload.department,
                                "min_clearance": payload.clearance,
                            }
                        ),
                        self._encode_json(payload.ai_state),
                        current_version,
                        now,
                        now,
                    ),
                )
            else:
                if existing["owner_user_id"] != payload.user_id:
                    raise ViewStorageError(
                        code="VIEW_WRITE_FORBIDDEN",
                        message="Only the owner can create new versions for this view",
                        status_code=403,
                    )
                if existing["owner_project_id"] != payload.project_id:
                    raise ViewStorageError(
                        code="VIEW_PROJECT_MISMATCH",
                        message="project_id does not match the existing view",
                        status_code=403,
                    )

                current_version = int(existing["current_version"]) + 1
                # COALESCE so a caller without workspace_id doesn't clobber a
                # workspace association set by an earlier save.
                conn.execute(
                    """
                    UPDATE ai_views
                    SET title = ?,
                        dataset_table = ?,
                        conversation_id = ?,
                        ai_state = ?,
                        current_version = ?,
                        updated_at = ?,
                        workspace_id = COALESCE(?, workspace_id)
                    WHERE view_id = ?
                    """,
                    (
                        normalized_title,
                        payload.dataset_table,
                        payload.conversation_id,
                        self._encode_json(payload.ai_state),
                        current_version,
                        now,
                        (payload.workspace_id or "").strip() or None,
                        view_id,
                    ),
                )

            conn.execute(
                """
                INSERT INTO ai_view_versions (
                    view_id,
                    version,
                    ai_state,
                    metadata,
                    created_by,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    view_id,
                    current_version,
                    self._encode_json(payload.ai_state),
                    self._encode_json(payload.metadata or {}),
                    payload.user_id,
                    now,
                ),
            )
            conn.commit()

        self._append_event(
            {
                "event": "save",
                "view_id": view_id,
                "version": current_version,
                "user_id": payload.user_id,
                "project_id": payload.project_id,
                "timestamp": now,
            }
        )

        duration_ms = int((time.perf_counter() - started) * 1000)
        return {
            "view_id": view_id,
            "version": current_version,
            "title": normalized_title,
            "share_path": f"/share/{view_id}",
            "saved_at": now,
            "duration_ms": duration_ms,
        }

    def get_view(self, view_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    view_id,
                    owner_user_id,
                    owner_project_id,
                    dataset_table,
                    title,
                    conversation_id,
                    rbac_scope,
                    ai_state,
                    current_version,
                    created_at,
                    updated_at
                FROM ai_views
                WHERE view_id = ?
                """,
                (view_id,),
            ).fetchone()

            if row is None:
                raise ViewStorageError(
                    code="VIEW_NOT_FOUND",
                    message="View does not exist",
                    status_code=404,
                )

            history_rows = conn.execute(
                """
                SELECT version, created_at, created_by
                FROM ai_view_versions
                WHERE view_id = ?
                ORDER BY version ASC
                """,
                (view_id,),
            ).fetchall()

        return {
            "view_id": row["view_id"],
            "title": row["title"],
            "owner_user_id": row["owner_user_id"],
            "owner_project_id": row["owner_project_id"],
            "dataset_table": row["dataset_table"],
            "conversation_id": row["conversation_id"],
            "rbac_scope": self._decode_json(row["rbac_scope"]),
            "ai_state": self._decode_json(row["ai_state"]),
            "current_version": int(row["current_version"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "share_path": f"/share/{row['view_id']}",
            "versions": [
                {
                    "version": int(item["version"]),
                    "created_at": item["created_at"],
                    "created_by": item["created_by"],
                }
                for item in history_rows
            ],
        }

    def rollback_view(self, view_id: str, payload: RollbackInput) -> dict[str, Any]:
        if not payload.user_id.strip():
            raise ViewStorageError(
                code="AUTH_REQUIRED",
                message="user_id is required",
                status_code=401,
            )

        now = _utc_now()
        with self._lock, self._connect() as conn:
            current_view = conn.execute(
                """
                SELECT owner_user_id, owner_project_id, current_version, title, dataset_table, conversation_id
                FROM ai_views
                WHERE view_id = ?
                """,
                (view_id,),
            ).fetchone()
            if current_view is None:
                raise ViewStorageError(
                    code="VIEW_NOT_FOUND",
                    message="View does not exist",
                    status_code=404,
                )

            if current_view["owner_project_id"] != payload.project_id:
                raise ViewStorageError(
                    code="VIEW_PROJECT_MISMATCH",
                    message="project_id does not match the existing view",
                    status_code=403,
                )

            owner_user_id = str(current_view["owner_user_id"])
            if payload.user_id != owner_user_id and payload.role.strip().lower() != "admin":
                raise ViewStorageError(
                    code="ROLLBACK_FORBIDDEN",
                    message="Only owner/admin can rollback this view",
                    status_code=403,
                )

            target_row = conn.execute(
                """
                SELECT ai_state
                FROM ai_view_versions
                WHERE view_id = ? AND version = ?
                """,
                (view_id, payload.target_version),
            ).fetchone()
            if target_row is None:
                raise ViewStorageError(
                    code="VERSION_NOT_FOUND",
                    message="Target version does not exist",
                    status_code=404,
                )

            next_version = int(current_view["current_version"]) + 1
            rollback_state = target_row["ai_state"]

            conn.execute(
                """
                UPDATE ai_views
                SET ai_state = ?,
                    current_version = ?,
                    updated_at = ?
                WHERE view_id = ?
                """,
                (rollback_state, next_version, now, view_id),
            )
            conn.execute(
                """
                INSERT INTO ai_view_versions (
                    view_id,
                    version,
                    ai_state,
                    metadata,
                    created_by,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    view_id,
                    next_version,
                    rollback_state,
                    self._encode_json({"rollback_from_version": payload.target_version}),
                    payload.user_id,
                    now,
                ),
            )
            conn.commit()

        self._append_event(
            {
                "event": "rollback",
                "view_id": view_id,
                "target_version": payload.target_version,
                "new_version": next_version,
                "user_id": payload.user_id,
                "project_id": payload.project_id,
                "timestamp": now,
            }
        )

        return {
            "view_id": view_id,
            "rolled_back_to": payload.target_version,
            "version": next_version,
            "share_path": f"/share/{view_id}",
            "updated_at": now,
        }

    def _connect(self) -> sqlite3.Connection:
        return sqlite_connect(self.db_path)

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_views (
                    view_id TEXT PRIMARY KEY,
                    owner_user_id TEXT NOT NULL,
                    owner_project_id TEXT NOT NULL,
                    workspace_id TEXT,
                    dataset_table TEXT NOT NULL,
                    title TEXT NOT NULL,
                    conversation_id TEXT,
                    rbac_scope TEXT NOT NULL,
                    ai_state TEXT NOT NULL,
                    current_version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_view_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    view_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    ai_state TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(view_id, version),
                    FOREIGN KEY(view_id) REFERENCES ai_views(view_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ai_view_versions_view_id ON ai_view_versions(view_id)"
            )
            # Older databases predate the workspace_id column; add it idempotently
            # so workspace delete-cascade can find newly-saved views.
            self._ensure_column(conn, "ai_views", "workspace_id", "TEXT")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ai_views_workspace ON ai_views(workspace_id)"
            )
            conn.commit()

    @staticmethod
    def _ensure_column(
        conn: sqlite3.Connection,
        table: str,
        column: str,
        col_type: str,
    ) -> None:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        if any(str(r[1]) == column for r in rows):
            return
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")

    def _append_event(self, payload: dict[str, Any]) -> None:
        line = json.dumps(payload, ensure_ascii=False)
        with self.audit_log_path.open("a", encoding="utf-8") as fp:
            fp.write(f"{line}\n")

    @staticmethod
    def _encode_json(payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _decode_json(raw: str) -> dict[str, Any]:
        decoded = json.loads(raw)
        if isinstance(decoded, dict):
            return decoded
        return {"value": decoded}


@lru_cache(maxsize=2)
def _cached_view_storage_service(storage_key: str) -> ViewStorageService:
    parsed = urlparse(storage_key)
    db_path: Path
    if parsed.scheme == "sqlite":
        db_path = _sqlite_db_path_from_url(storage_key)
        audit_dir = db_path.parent
    else:
        fallback_root = Path(storage_key)
        fallback_root.mkdir(parents=True, exist_ok=True)
        db_path = fallback_root / "ai_views.sqlite3"
        audit_dir = fallback_root

    return ViewStorageService(
        db_path=db_path,
        audit_log_path=audit_dir / "view_events.log",
    )


def get_view_storage_service() -> ViewStorageService:
    settings = get_settings()
    db_url = settings.database_url.strip()

    # 本地开发/测试默认回落到 UPLOAD_DIR 下的 sqlite 文件，避免依赖外置数据库。
    if db_url.startswith("sqlite://"):
        storage_key = db_url
    else:
        storage_key = str((settings.upload_dir / "state").resolve())

    return _cached_view_storage_service(storage_key)


def clear_view_storage_service_cache() -> None:
    _cached_view_storage_service.cache_clear()


def _sqlite_db_path_from_url(database_url: str) -> Path:
    parsed = urlparse(database_url)
    raw_path = unquote(parsed.path)

    if raw_path.startswith("//"):
        return Path("/" + raw_path.lstrip("/")).resolve()

    if raw_path.startswith("/"):
        raw_path = raw_path[1:]

    return (SQLITE_RELATIVE_BASE / raw_path).resolve()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
