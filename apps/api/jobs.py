from __future__ import annotations

import sqlite3
from typing import Any
from urllib.parse import unquote, urlparse
from pathlib import Path
from functools import lru_cache

from fastapi import APIRouter

from .config import get_settings
from .sqlite_support import connect as sqlite_connect

SQLITE_RELATIVE_BASE = Path(__file__).resolve().parent
router = APIRouter(tags=["jobs"])


@router.get("/jobs")
async def list_jobs() -> dict[str, Any]:
    jobs = _get_jobs()
    return {"count": len(jobs), "jobs": jobs}


def _get_jobs() -> list[dict[str, Any]]:
    db_path = _get_db_path()
    conn = sqlite_connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, code, label_zh, label_en, sort_order FROM user_jobs ORDER BY sort_order ASC"
        ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "code": str(row["code"]),
                "label_zh": str(row["label_zh"]),
                "label_en": str(row["label_en"]),
                "sort_order": int(row["sort_order"]),
            }
            for row in rows
        ]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def _get_db_path() -> Path:
    settings = get_settings()
    db_url = settings.database_url.strip()
    if db_url.startswith("sqlite://"):
        parsed = urlparse(db_url)
        raw_path = unquote(parsed.path)
        if raw_path.startswith("//"):
            return Path("/" + raw_path.lstrip("/")).resolve()
        if raw_path.startswith("/"):
            raw_path = raw_path[1:]
        return (SQLITE_RELATIVE_BASE / raw_path).resolve()
    return (settings.upload_dir / "state" / "ai_views.sqlite3").resolve()


def validate_job_id(conn: sqlite3.Connection, job_id: int) -> bool:
    row = conn.execute("SELECT 1 FROM user_jobs WHERE id = ?", (job_id,)).fetchone()
    return row is not None
