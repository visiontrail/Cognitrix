from __future__ import annotations

import sqlite3
from typing import Any


def upsert_table_column_metadata(
    conn: sqlite3.Connection,
    *,
    workspace_id: str,
    table_name: str,
    columns: list[dict[str, Any]],
    updated_at: str,
) -> None:
    normalized_workspace = workspace_id.strip()
    normalized_table = table_name.strip()
    if not normalized_workspace or not normalized_table:
        return

    conn.execute(
        """
        DELETE FROM table_column_metadata
        WHERE workspace_id = ? AND table_name = ?
        """,
        (normalized_workspace, normalized_table),
    )
    for index, column in enumerate(columns):
        column_name = str(column.get("name") or "").strip()
        if not column_name:
            continue
        original_name = _optional_text(column.get("original_name"))
        description = _optional_text(column.get("description")) or original_name
        data_type = _optional_text(column.get("type") or column.get("data_type"))
        conn.execute(
            """
            INSERT INTO table_column_metadata (
                workspace_id,
                table_name,
                column_name,
                original_name,
                description,
                data_type,
                ordinal_position,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(workspace_id, table_name, column_name) DO UPDATE SET
                original_name = excluded.original_name,
                description = excluded.description,
                data_type = excluded.data_type,
                ordinal_position = excluded.ordinal_position,
                updated_at = excluded.updated_at
            """,
            (
                normalized_workspace,
                normalized_table,
                column_name,
                original_name,
                description,
                data_type,
                int(column.get("ordinal_position") or index),
                updated_at,
                updated_at,
            ),
        )


def load_table_column_metadata(
    conn: sqlite3.Connection,
    *,
    workspace_id: str,
    table_names: list[str],
) -> dict[str, dict[str, Any]]:
    normalized_workspace = workspace_id.strip()
    normalized_tables = [table.strip() for table in table_names if table.strip()]
    if not normalized_workspace or not normalized_tables:
        return {}

    placeholders = ", ".join("?" for _ in normalized_tables)
    rows = conn.execute(
        f"""
        SELECT table_name, column_name, original_name, description, data_type, ordinal_position
        FROM table_column_metadata
        WHERE workspace_id = ? AND table_name IN ({placeholders})
        ORDER BY table_name ASC, ordinal_position ASC
        """,
        (normalized_workspace, *normalized_tables),
    ).fetchall()

    metadata: dict[str, dict[str, Any]] = {}
    for row in rows:
        column_name = str(row["column_name"])
        metadata[column_name] = {
            "table_name": str(row["table_name"]),
            "name": column_name,
            "original_name": _optional_text(row["original_name"]),
            "description": _optional_text(row["description"]),
            "data_type": _optional_text(row["data_type"]),
            "ordinal_position": int(row["ordinal_position"]),
        }
    return metadata


def enrich_column_with_metadata(
    column: dict[str, Any],
    metadata_by_column: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    column_name = str(column.get("name") or "")
    metadata = metadata_by_column.get(column_name)
    if not metadata:
        return column

    enriched = dict(column)
    original_name = metadata.get("original_name")
    description = metadata.get("description")
    if original_name:
        enriched["original_name"] = original_name
    if description:
        enriched["description"] = description
        enriched["label"] = description
    elif original_name:
        enriched["label"] = original_name
    return enriched


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
