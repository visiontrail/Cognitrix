from __future__ import annotations

import sqlite3
import time
from collections import defaultdict
from threading import Lock
from typing import Any
from urllib.parse import unquote, urlparse
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from .auth import AuthIdentity, get_current_identity
from .config import get_settings
from .sqlite_support import connect as sqlite_connect

router = APIRouter(tags=["users"])

SQLITE_RELATIVE_BASE = Path(__file__).resolve().parent

_rate_lock = Lock()
_rate_buckets: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT = 60
_WINDOW_SECONDS = 60.0


def _check_rate_limit(user_id: str) -> None:
    now = time.monotonic()
    with _rate_lock:
        calls = _rate_buckets[user_id]
        cutoff = now - _WINDOW_SECONDS
        _rate_buckets[user_id] = [t for t in calls if t > cutoff]
        if len(_rate_buckets[user_id]) >= _RATE_LIMIT:
            raise HTTPException(
                status_code=429,
                headers={"Retry-After": "60"},
                detail={"code": "rate_limit_exceeded", "message": "Rate limit exceeded"},
            )
        _rate_buckets[user_id].append(now)


def _get_db_conn() -> sqlite3.Connection:
    settings = get_settings()
    db_url = settings.database_url.strip()
    if db_url.startswith("sqlite://"):
        parsed = urlparse(db_url)
        raw_path = unquote(parsed.path)
        if raw_path.startswith("//"):
            db_path = Path("/" + raw_path.lstrip("/")).resolve()
        elif raw_path.startswith("/") and len(raw_path) > 1 and raw_path[1] != ".":
            db_path = Path(raw_path).resolve()
        else:
            if raw_path.startswith("/"):
                raw_path = raw_path[1:]
            db_path = (SQLITE_RELATIVE_BASE / raw_path).resolve()
    else:
        db_path = (settings.upload_dir / "state" / "ai_views.sqlite3").resolve()
    return sqlite_connect(db_path)


@router.get("/users/search")
async def search_users(
    q: str = Query(default=""),
    limit: int = Query(default=20, ge=1, le=50),
    identity: AuthIdentity = Depends(get_current_identity),
) -> dict[str, Any]:
    if len(q.strip()) < 2:
        raise HTTPException(
            status_code=400,
            detail={"code": "query_too_short", "message": "Query must be at least 2 characters"},
        )

    _check_rate_limit(identity.user_id)

    from .users import search_users as _search_users

    conn = _get_db_conn()
    try:
        results = _search_users(conn, q=q, limit=limit, exclude_user_id=None)
    finally:
        conn.close()

    return {"count": len(results), "users": results}


class BatchUsersRequest(BaseModel):
    user_ids: list[str]


@router.post("/users/batch")
async def batch_users(
    body: BatchUsersRequest,
    identity: AuthIdentity = Depends(get_current_identity),
) -> dict[str, object]:
    if not body.user_ids:
        return {"count": 0, "users": []}
    if len(body.user_ids) > 100:
        raise HTTPException(
            status_code=400,
            detail={"code": "too_many_ids", "message": "At most 100 user_ids per request"},
        )

    from .users import get_users_by_ids

    cleaned_ids = [uid.strip() for uid in body.user_ids if uid.strip()]
    conn = _get_db_conn()
    try:
        results = get_users_by_ids(conn, cleaned_ids)
    finally:
        conn.close()
    return {"count": len(results), "users": results}
