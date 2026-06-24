"""Server-side persistence for chat history, chart assets, and canvas snapshots.

These three data categories previously lived only in the browser's localStorage,
so they survived logout/login on the *same* browser but were invisible on any
other browser or device. This module gives them a durable, workspace + user
scoped home in the same SQLite database as the workspace records, exposed through
REST endpoints the web client hydrates from on load and writes to at commit
points (session create, turn completion, asset add, canvas autosave).

Rows are normalized: one row per session, message, and asset. The rich,
client-shaped fields that have no value to the server (message chart references,
trace summaries, the full chart spec, the canvas snapshot blob) are preserved
verbatim in a JSON `payload` column so the client gets back exactly what it
stored.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from .auth import AuthIdentity, get_current_identity
from .workspaces import WorkspaceError, get_workspace_service

logger = logging.getLogger("cognitrix.workspace_state")

_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS chat_sessions (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        title TEXT NOT NULL DEFAULT '',
        last_message TEXT NOT NULL DEFAULT '',
        message_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_chat_sessions_ws_user ON chat_sessions(workspace_id, user_id, updated_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS chat_messages (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        workspace_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        seq INTEGER NOT NULL,
        role TEXT NOT NULL DEFAULT 'assistant',
        content TEXT NOT NULL DEFAULT '',
        payload TEXT NOT NULL DEFAULT '{}',
        timestamp TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id, seq)",
    """
    CREATE TABLE IF NOT EXISTS chart_assets (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        title TEXT NOT NULL DEFAULT '',
        chart_type TEXT NOT NULL DEFAULT '',
        payload TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_chart_assets_ws_user ON chart_assets(workspace_id, user_id, created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS workspace_snapshots (
        workspace_id TEXT PRIMARY KEY,
        payload TEXT NOT NULL DEFAULT '{}',
        updated_by TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL
    )
    """,
)


def _loads(raw: Any, fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return fallback


class WorkspaceStateStore:
    """SQLite-backed store for chat history, chart assets, and canvas snapshots.

    Bound to the same database file as the workspace records so the workspace
    delete-cascade (which deletes from these tables directly) operates on the
    same data this store reads and writes.
    """

    def __init__(self, *, db_path: Path) -> None:
        self.db_path = db_path
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            for stmt in _SCHEMA_STATEMENTS:
                conn.execute(stmt)
            conn.commit()

    # -- chat sessions -------------------------------------------------------

    def list_sessions(self, *, workspace_id: str, user_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, title, last_message, message_count, created_at, updated_at
                FROM chat_sessions
                WHERE workspace_id = ? AND user_id = ?
                ORDER BY updated_at DESC
                """,
                (workspace_id, user_id),
            ).fetchall()
        return [self._serialize_session(row) for row in rows]

    def upsert_session(
        self,
        *,
        workspace_id: str,
        user_id: str,
        session_id: str,
        title: str,
        last_message: str,
        message_count: int,
        created_at: str,
        updated_at: str,
    ) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_sessions
                    (id, workspace_id, user_id, title, last_message, message_count, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    last_message = excluded.last_message,
                    message_count = excluded.message_count,
                    updated_at = excluded.updated_at
                WHERE excluded.user_id = chat_sessions.user_id
                  AND excluded.workspace_id = chat_sessions.workspace_id
                """,
                (
                    session_id,
                    workspace_id,
                    user_id,
                    title,
                    last_message,
                    int(message_count),
                    created_at,
                    updated_at,
                ),
            )
            conn.commit()
            row = conn.execute(
                """
                SELECT id, title, last_message, message_count, created_at, updated_at
                FROM chat_sessions WHERE id = ? AND workspace_id = ? AND user_id = ?
                """,
                (session_id, workspace_id, user_id),
            ).fetchone()
        if row is None:
            # A session id owned by another user/workspace cannot be hijacked.
            raise WorkspaceError(
                code="CHAT_SESSION_CONFLICT",
                message="Session id belongs to a different scope",
                status_code=409,
            )
        return self._serialize_session(row)

    def delete_session(self, *, workspace_id: str, user_id: str, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM chat_messages WHERE session_id = ? AND workspace_id = ? AND user_id = ?",
                (session_id, workspace_id, user_id),
            )
            conn.execute(
                "DELETE FROM chat_sessions WHERE id = ? AND workspace_id = ? AND user_id = ?",
                (session_id, workspace_id, user_id),
            )
            conn.commit()

    # -- chat messages -------------------------------------------------------

    def list_messages(
        self, *, workspace_id: str, user_id: str, session_id: str
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT payload FROM chat_messages
                WHERE session_id = ? AND workspace_id = ? AND user_id = ?
                ORDER BY seq ASC
                """,
                (session_id, workspace_id, user_id),
            ).fetchall()
        return [_loads(row["payload"], {}) for row in rows]

    def replace_messages(
        self,
        *,
        workspace_id: str,
        user_id: str,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> int:
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM chat_messages WHERE session_id = ? AND workspace_id = ? AND user_id = ?",
                (session_id, workspace_id, user_id),
            )
            for seq, message in enumerate(messages):
                message_id = str(message.get("id") or f"{session_id}-{seq}")
                conn.execute(
                    """
                    INSERT INTO chat_messages
                        (id, session_id, workspace_id, user_id, seq, role, content, payload, timestamp, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        message_id,
                        session_id,
                        workspace_id,
                        user_id,
                        seq,
                        str(message.get("role") or "assistant"),
                        str(message.get("content") or ""),
                        json.dumps(message, ensure_ascii=False),
                        str(message.get("timestamp") or ""),
                        now,
                    ),
                )
            conn.commit()
        return len(messages)

    # -- chart assets --------------------------------------------------------

    def list_chart_assets(self, *, workspace_id: str, user_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT payload FROM chart_assets
                WHERE workspace_id = ? AND user_id = ?
                ORDER BY created_at DESC
                """,
                (workspace_id, user_id),
            ).fetchall()
        return [_loads(row["payload"], {}) for row in rows]

    def upsert_chart_asset(
        self,
        *,
        workspace_id: str,
        user_id: str,
        asset_id: str,
        asset: dict[str, Any],
    ) -> dict[str, Any]:
        title = str(asset.get("title") or "")
        chart_type = str(asset.get("chartType") or asset.get("chart_type") or "")
        created_at = str(asset.get("createdAt") or _utc_now())
        updated_at = str(asset.get("updatedAt") or created_at)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chart_assets
                    (id, workspace_id, user_id, title, chart_type, payload, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    chart_type = excluded.chart_type,
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                WHERE excluded.user_id = chart_assets.user_id
                  AND excluded.workspace_id = chart_assets.workspace_id
                """,
                (
                    asset_id,
                    workspace_id,
                    user_id,
                    title,
                    chart_type,
                    json.dumps(asset, ensure_ascii=False),
                    created_at,
                    updated_at,
                ),
            )
            conn.commit()
        return asset

    # -- canvas snapshot -----------------------------------------------------

    def get_snapshot(self, *, workspace_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM workspace_snapshots WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchone()
        if row is None:
            return None
        snapshot = _loads(row["payload"], None)
        return snapshot if isinstance(snapshot, dict) else None

    def save_snapshot(
        self, *, workspace_id: str, snapshot: dict[str, Any], updated_by: str
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO workspace_snapshots (workspace_id, payload, updated_by, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(workspace_id) DO UPDATE SET
                    payload = excluded.payload,
                    updated_by = excluded.updated_by,
                    updated_at = excluded.updated_at
                """,
                (workspace_id, json.dumps(snapshot, ensure_ascii=False), updated_by, _utc_now()),
            )
            conn.commit()

    @staticmethod
    def _serialize_session(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "title": str(row["title"] or ""),
            "lastMessage": str(row["last_message"] or ""),
            "messageCount": int(row["message_count"] or 0),
            "createdAt": str(row["created_at"] or ""),
            "updatedAt": str(row["updated_at"] or ""),
        }


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@lru_cache(maxsize=2)
def _cached_store(db_path_str: str) -> WorkspaceStateStore:
    return WorkspaceStateStore(db_path=Path(db_path_str))


def get_workspace_state_store() -> WorkspaceStateStore:
    # Bind to the exact database file the workspace records (and the workspace
    # delete-cascade) use, so cascade deletes and these reads stay consistent.
    db_path = get_workspace_service().db_path
    return _cached_store(str(db_path))


def clear_workspace_state_store_cache() -> None:
    _cached_store.cache_clear()


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class ChatSessionUpsertRequest(BaseModel):
    # Accept camelCase (what the web client sends) and snake_case interchangeably.
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    title: str = ""
    last_message: str = ""
    message_count: int = 0
    created_at: str = ""
    updated_at: str = ""


class ChatMessagesReplaceRequest(BaseModel):
    messages: list[dict[str, Any]] = Field(default_factory=list)


class ChartAssetUpsertRequest(BaseModel):
    asset: dict[str, Any]


class CanvasSnapshotSaveRequest(BaseModel):
    snapshot: dict[str, Any]


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/workspaces", tags=["workspace-state"])


def _assert_access(workspace_id: str, user_id: str, minimum_role: str) -> None:
    try:
        get_workspace_service().assert_workspace_access(
            workspace_id=workspace_id,
            user_id=user_id,
            minimum_role=minimum_role,
        )
    except WorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc


@router.get("/{workspace_id}/chat/sessions")
async def list_chat_sessions(
    workspace_id: str,
    identity: AuthIdentity = Depends(get_current_identity),
) -> dict[str, object]:
    _assert_access(workspace_id, identity.user_id, "viewer")
    sessions = get_workspace_state_store().list_sessions(
        workspace_id=workspace_id, user_id=identity.user_id
    )
    return {"sessions": sessions}


@router.put("/{workspace_id}/chat/sessions/{session_id}")
async def upsert_chat_session(
    workspace_id: str,
    session_id: str,
    request: ChatSessionUpsertRequest,
    identity: AuthIdentity = Depends(get_current_identity),
) -> dict[str, object]:
    _assert_access(workspace_id, identity.user_id, "viewer")
    now = _utc_now()
    try:
        session = get_workspace_state_store().upsert_session(
            workspace_id=workspace_id,
            user_id=identity.user_id,
            session_id=session_id,
            title=request.title,
            last_message=request.last_message,
            message_count=request.message_count,
            created_at=request.created_at or now,
            updated_at=request.updated_at or now,
        )
    except WorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc
    return {"session": session}


@router.delete("/{workspace_id}/chat/sessions/{session_id}")
async def delete_chat_session(
    workspace_id: str,
    session_id: str,
    identity: AuthIdentity = Depends(get_current_identity),
) -> dict[str, object]:
    _assert_access(workspace_id, identity.user_id, "viewer")
    get_workspace_state_store().delete_session(
        workspace_id=workspace_id, user_id=identity.user_id, session_id=session_id
    )
    return {"deleted": True}


@router.get("/{workspace_id}/chat/sessions/{session_id}/messages")
async def list_chat_messages(
    workspace_id: str,
    session_id: str,
    identity: AuthIdentity = Depends(get_current_identity),
) -> dict[str, object]:
    _assert_access(workspace_id, identity.user_id, "viewer")
    messages = get_workspace_state_store().list_messages(
        workspace_id=workspace_id, user_id=identity.user_id, session_id=session_id
    )
    return {"messages": messages}


@router.put("/{workspace_id}/chat/sessions/{session_id}/messages")
async def replace_chat_messages(
    workspace_id: str,
    session_id: str,
    request: ChatMessagesReplaceRequest,
    identity: AuthIdentity = Depends(get_current_identity),
) -> dict[str, object]:
    _assert_access(workspace_id, identity.user_id, "viewer")
    count = get_workspace_state_store().replace_messages(
        workspace_id=workspace_id,
        user_id=identity.user_id,
        session_id=session_id,
        messages=request.messages,
    )
    return {"count": count}


@router.get("/{workspace_id}/chart-assets")
async def list_chart_assets(
    workspace_id: str,
    identity: AuthIdentity = Depends(get_current_identity),
) -> dict[str, object]:
    _assert_access(workspace_id, identity.user_id, "viewer")
    assets = get_workspace_state_store().list_chart_assets(
        workspace_id=workspace_id, user_id=identity.user_id
    )
    return {"assets": assets}


@router.put("/{workspace_id}/chart-assets/{asset_id}")
async def upsert_chart_asset(
    workspace_id: str,
    asset_id: str,
    request: ChartAssetUpsertRequest,
    identity: AuthIdentity = Depends(get_current_identity),
) -> dict[str, object]:
    _assert_access(workspace_id, identity.user_id, "viewer")
    asset = get_workspace_state_store().upsert_chart_asset(
        workspace_id=workspace_id,
        user_id=identity.user_id,
        asset_id=asset_id,
        asset=request.asset,
    )
    return {"asset": asset}


@router.get("/{workspace_id}/canvas-snapshot")
async def get_canvas_snapshot(
    workspace_id: str,
    identity: AuthIdentity = Depends(get_current_identity),
) -> dict[str, object]:
    _assert_access(workspace_id, identity.user_id, "viewer")
    snapshot = get_workspace_state_store().get_snapshot(workspace_id=workspace_id)
    return {"snapshot": snapshot}


@router.put("/{workspace_id}/canvas-snapshot")
async def save_canvas_snapshot(
    workspace_id: str,
    request: CanvasSnapshotSaveRequest,
    identity: AuthIdentity = Depends(get_current_identity),
) -> dict[str, object]:
    _assert_access(workspace_id, identity.user_id, "editor")
    get_workspace_state_store().save_snapshot(
        workspace_id=workspace_id,
        snapshot=request.snapshot,
        updated_by=identity.user_id,
    )
    return {"saved": True}
