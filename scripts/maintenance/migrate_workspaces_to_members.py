#!/usr/bin/env python3
"""
One-time migration: ensure every workspace has an owner row in workspace_members.
This script is safe to run multiple times (idempotent).

Called automatically from auth.py login hook on first login of a workspace owner.
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
import sys

SQLITE_RELATIVE_BASE = Path(__file__).resolve().parents[2] / "apps" / "api"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def migrate_workspaces_to_members(db_path: Path) -> int:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    inserted = 0
    try:
        rows = conn.execute(
            """
            SELECT w.id AS workspace_id, w.owner_user_id
            FROM workspaces w
            WHERE NOT EXISTS (
                SELECT 1 FROM workspace_members wm
                WHERE wm.workspace_id = w.id AND wm.user_id = w.owner_user_id AND wm.role = 'owner'
            )
            AND w.status = 'active'
            """
        ).fetchall()

        for row in rows:
            member_id = uuid.uuid4().hex
            conn.execute(
                """
                INSERT OR IGNORE INTO workspace_members (id, workspace_id, user_id, role, created_at)
                VALUES (?, ?, ?, 'owner', ?)
                """,
                (member_id, row["workspace_id"], row["owner_user_id"], _utc_now()),
            )
            inserted += 1

        conn.commit()
    finally:
        conn.close()
    return inserted


def _find_db_path() -> Path:
    import os
    from urllib.parse import unquote, urlparse

    db_url = os.getenv("DATABASE_URL", "")
    if db_url.startswith("sqlite://"):
        parsed = urlparse(db_url)
        raw_path = unquote(parsed.path)
        if raw_path.startswith("//"):
            return Path("/" + raw_path.lstrip("/")).resolve()
        if raw_path.startswith("/"):
            raw_path = raw_path[1:]
        return (SQLITE_RELATIVE_BASE / raw_path).resolve()

    upload_dir = os.getenv("UPLOAD_DIR", "./apps/api/data/uploads")
    return (Path(upload_dir) / "state" / "ai_views.sqlite3").resolve()


if __name__ == "__main__":
    db_path = _find_db_path()
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        sys.exit(1)
    n = migrate_workspaces_to_members(db_path)
    print(f"Migrated {n} workspace(s) to workspace_members")
