from __future__ import annotations

import json
import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from .sqlite_support import connect as sqlite_connect


class AdminControlStore:
    """Small, isolated SQLite store for global configuration and usage facts."""

    def __init__(self, *, upload_dir: Path) -> None:
        self.path = (upload_dir / "state" / "admin_control.sqlite3").resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self.ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        return sqlite_connect(self.path)

    def ensure_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS setting_overrides (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    is_secret INTEGER NOT NULL DEFAULT 0,
                    updated_by TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS setting_history (
                    id TEXT PRIMARY KEY,
                    key TEXT NOT NULL,
                    action TEXT NOT NULL,
                    is_secret INTEGER NOT NULL DEFAULT 0,
                    updated_by TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_setting_history_updated
                    ON setting_history(updated_at DESC);

                CREATE TABLE IF NOT EXISTS usage_events (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    project_id TEXT,
                    event_type TEXT NOT NULL,
                    route TEXT,
                    status_code INTEGER,
                    duration_ms REAL,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_usage_events_created
                    ON usage_events(created_at);
                CREATE INDEX IF NOT EXISTS idx_usage_events_user_created
                    ON usage_events(user_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_usage_events_type_created
                    ON usage_events(event_type, created_at);
                """
            )
            conn.commit()

    def load_overrides(self) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT key, value_json FROM setting_overrides ORDER BY key"
            ).fetchall()
        result: dict[str, Any] = {}
        for row in rows:
            try:
                result[str(row["key"])] = json.loads(str(row["value_json"]))
            except (TypeError, ValueError):
                continue
        return result

    def set_override(
        self,
        *,
        key: str,
        value: Any,
        is_secret: bool,
        updated_by: str,
    ) -> None:
        now = _utc_now()
        encoded = json.dumps(value, ensure_ascii=False, default=str)
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO setting_overrides (key, value_json, is_secret, updated_by, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    is_secret = excluded.is_secret,
                    updated_by = excluded.updated_by,
                    updated_at = excluded.updated_at
                """,
                (key, encoded, int(is_secret), updated_by, now),
            )
            conn.execute(
                """
                INSERT INTO setting_history (id, key, action, is_secret, updated_by, updated_at)
                VALUES (?, ?, 'set', ?, ?, ?)
                """,
                (uuid.uuid4().hex, key, int(is_secret), updated_by, now),
            )
            conn.commit()

    def set_overrides(
        self,
        *,
        values: dict[str, tuple[Any, bool]],
        updated_by: str,
    ) -> None:
        """Persist a validated settings form as one transaction."""
        if not values:
            return
        now = _utc_now()
        with self._lock, self._connect() as conn:
            for key, (value, is_secret) in values.items():
                encoded = json.dumps(value, ensure_ascii=False, default=str)
                conn.execute(
                    """
                    INSERT INTO setting_overrides
                        (key, value_json, is_secret, updated_by, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value_json = excluded.value_json,
                        is_secret = excluded.is_secret,
                        updated_by = excluded.updated_by,
                        updated_at = excluded.updated_at
                    """,
                    (key, encoded, int(is_secret), updated_by, now),
                )
                conn.execute(
                    """
                    INSERT INTO setting_history
                        (id, key, action, is_secret, updated_by, updated_at)
                    VALUES (?, ?, 'set', ?, ?, ?)
                    """,
                    (uuid.uuid4().hex, key, int(is_secret), updated_by, now),
                )
            conn.commit()

    def delete_override(self, *, key: str, is_secret: bool, updated_by: str) -> bool:
        now = _utc_now()
        with self._lock, self._connect() as conn:
            cursor = conn.execute("DELETE FROM setting_overrides WHERE key = ?", (key,))
            if cursor.rowcount:
                conn.execute(
                    """
                    INSERT INTO setting_history (id, key, action, is_secret, updated_by, updated_at)
                    VALUES (?, ?, 'reset', ?, ?, ?)
                    """,
                    (uuid.uuid4().hex, key, int(is_secret), updated_by, now),
                )
            conn.commit()
            return bool(cursor.rowcount)

    def list_history(self, *, limit: int = 100) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 500))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, key, action, is_secret, updated_by, updated_at
                FROM setting_history ORDER BY updated_at DESC, rowid DESC LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "key": str(row["key"]),
                "action": str(row["action"]),
                "is_secret": bool(row["is_secret"]),
                "updated_by": str(row["updated_by"]),
                "updated_at": str(row["updated_at"]),
            }
            for row in rows
        ]

    def record_usage(
        self,
        *,
        user_id: str,
        project_id: str | None,
        event_type: str,
        route: str | None = None,
        status_code: int | None = None,
        duration_ms: float | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        normalized_user = user_id.strip()
        normalized_type = event_type.strip()
        if not normalized_user or not normalized_type:
            return
        safe_metadata = _bounded_metadata(metadata or {})
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO usage_events (
                    id, user_id, project_id, event_type, route, status_code,
                    duration_ms, input_tokens, output_tokens, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid.uuid4().hex,
                    normalized_user,
                    project_id,
                    normalized_type,
                    route,
                    status_code,
                    duration_ms,
                    input_tokens,
                    output_tokens,
                    json.dumps(safe_metadata, ensure_ascii=False),
                    _utc_now(),
                ),
            )
            conn.commit()

    def cleanup_usage(self, *, retention_days: int) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, int(retention_days)))
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM usage_events WHERE created_at < ?",
                (cutoff.isoformat(timespec="seconds"),),
            )
            conn.commit()
            return int(cursor.rowcount or 0)

    def overview(self, *, start: str, end: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    SUM(CASE WHEN event_type = 'api_request' THEN 1 ELSE 0 END) AS requests,
                    COUNT(DISTINCT user_id) AS active_users,
                    SUM(CASE WHEN event_type = 'chat_turn' THEN 1 ELSE 0 END) AS chat_turns,
                    SUM(CASE WHEN event_type = 'tool_call' THEN 1 ELSE 0 END) AS tool_calls,
                    SUM(CASE WHEN status_code >= 400 OR event_type = 'error' THEN 1 ELSE 0 END) AS errors,
                    COALESCE(SUM(input_tokens), 0) AS input_tokens,
                    COALESCE(SUM(output_tokens), 0) AS output_tokens,
                    COALESCE(AVG(CASE WHEN event_type = 'api_request' THEN duration_ms END), 0) AS avg_latency_ms
                FROM usage_events
                WHERE created_at >= ? AND created_at < ?
                """,
                (start, end),
            ).fetchone()
        return {
            "requests": int(row["requests"] or 0),
            "active_users": int(row["active_users"] or 0),
            "chat_turns": int(row["chat_turns"] or 0),
            "tool_calls": int(row["tool_calls"] or 0),
            "errors": int(row["errors"] or 0),
            "input_tokens": int(row["input_tokens"] or 0),
            "output_tokens": int(row["output_tokens"] or 0),
            "avg_latency_ms": round(float(row["avg_latency_ms"] or 0), 2),
        }

    def daily_trend(self, *, start: str, end: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    SUBSTR(created_at, 1, 10) AS day,
                    SUM(CASE WHEN event_type = 'api_request' THEN 1 ELSE 0 END) AS requests,
                    SUM(CASE WHEN event_type = 'chat_turn' THEN 1 ELSE 0 END) AS chat_turns,
                    SUM(CASE WHEN event_type = 'tool_call' THEN 1 ELSE 0 END) AS tool_calls,
                    COUNT(DISTINCT user_id) AS active_users,
                    COALESCE(SUM(input_tokens), 0) + COALESCE(SUM(output_tokens), 0) AS tokens
                FROM usage_events
                WHERE created_at >= ? AND created_at < ?
                GROUP BY SUBSTR(created_at, 1, 10)
                ORDER BY day
                """,
                (start, end),
            ).fetchall()
        return [
            {
                "date": str(row["day"]),
                "requests": int(row["requests"] or 0),
                "chat_turns": int(row["chat_turns"] or 0),
                "tool_calls": int(row["tool_calls"] or 0),
                "active_users": int(row["active_users"] or 0),
                "tokens": int(row["tokens"] or 0),
            }
            for row in rows
        ]

    def user_usage(self, *, start: str, end: str) -> dict[str, dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    user_id,
                    SUM(CASE WHEN event_type = 'api_request' THEN 1 ELSE 0 END) AS requests,
                    SUM(CASE WHEN event_type = 'chat_turn' THEN 1 ELSE 0 END) AS chat_turns,
                    SUM(CASE WHEN event_type = 'tool_call' THEN 1 ELSE 0 END) AS tool_calls,
                    COALESCE(SUM(input_tokens), 0) + COALESCE(SUM(output_tokens), 0) AS tokens,
                    MAX(created_at) AS last_activity_at
                FROM usage_events
                WHERE created_at >= ? AND created_at < ?
                GROUP BY user_id
                """,
                (start, end),
            ).fetchall()
        return {
            str(row["user_id"]): {
                "requests": int(row["requests"] or 0),
                "chat_turns": int(row["chat_turns"] or 0),
                "tool_calls": int(row["tool_calls"] or 0),
                "tokens": int(row["tokens"] or 0),
                "last_activity_at": row["last_activity_at"],
            }
            for row in rows
        }


_stores: dict[str, AdminControlStore] = {}
_stores_lock = Lock()


def get_admin_store(upload_dir: Path) -> AdminControlStore:
    key = str(upload_dir.resolve())
    with _stores_lock:
        store = _stores.get(key)
        if store is None:
            store = AdminControlStore(upload_dir=upload_dir)
            _stores[key] = store
        return store


def clear_admin_store_cache() -> None:
    with _stores_lock:
        _stores.clear()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _bounded_metadata(value: dict[str, Any]) -> dict[str, Any]:
    allowed = {"tool_name", "model", "provider", "outcome"}
    result: dict[str, Any] = {}
    for key in allowed:
        item = value.get(key)
        if isinstance(item, (str, int, float, bool)) or item is None:
            result[key] = item
    return result
