"""Shared seeding for table-catalog rows.

`POST /workspaces/{id}/catalog` was removed in 453c839: catalog entries are now
only created by the product flows that own them (ingestion setup-confirm, and
`save_web_research`). Tests that merely need a pre-existing entry as a fixture
seed the state DB directly instead of driving one of those flows.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

SEED_TIMESTAMP = "2026-01-01T00:00:00+00:00"


def insert_catalog_entry(
    db_path: Path,
    *,
    workspace_id: str,
    table_name: str,
    human_label: str,
    business_type: str = "other",
    write_mode: str = "new_table",
    time_grain: str = "none",
    primary_keys: list[str] | None = None,
    match_columns: list[str] | None = None,
    is_active_target: bool = False,
    description: str = "",
    created_by: str = "alice",
) -> str:
    """Insert one table_catalog row and return its id."""
    catalog_id = uuid.uuid4().hex
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            """
            INSERT INTO table_catalog (
                id, workspace_id, table_name, human_label, business_type,
                write_mode, time_grain, primary_keys, match_columns,
                is_active_target, description, created_by, updated_by,
                created_at, updated_at
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
                json.dumps(primary_keys or []),
                json.dumps(match_columns or []),
                int(is_active_target),
                description,
                created_by,
                created_by,
                SEED_TIMESTAMP,
                SEED_TIMESTAMP,
            ),
        )
        conn.commit()
    return catalog_id
