from __future__ import annotations

import json
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

import duckdb
from claude_agent_sdk import ClaudeSDKClient

from .published_pages import PublishedPage, PublishedPageError, read_manifest
from .security import SQLGuardError, SQLReadOnlyValidator


class ChartQueryAgentError(Exception):
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
class SnapshotTable:
    chart_id: str
    table_name: str
    title: str
    chart_type: str | None
    columns: list[dict[str, str]]


@dataclass(slots=True)
class SnapshotDuckDBEntry:
    page_id: str
    connection: duckdb.DuckDBPyConnection
    tables: dict[str, SnapshotTable]
    created_at: float
    last_accessed_at: float


class SnapshotDuckDBCache:
    def __init__(self, *, max_entries: int = 10, ttl_seconds: int = 30 * 60) -> None:
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self._entries: OrderedDict[str, SnapshotDuckDBEntry] = OrderedDict()
        self._lock = Lock()

    def get(self, *, page: PublishedPage) -> SnapshotDuckDBEntry:
        now = time.monotonic()
        with self._lock:
            self._evict_expired(now=now)
            cached = self._entries.get(page.id)
            if cached is not None:
                cached.last_accessed_at = now
                self._entries.move_to_end(page.id)
                return cached

        loaded = self._load_page(page=page, now=now)
        with self._lock:
            existing = self._entries.get(page.id)
            if existing is not None:
                loaded.connection.close()
                existing.last_accessed_at = now
                self._entries.move_to_end(page.id)
                return existing
            self._entries[page.id] = loaded
            self._entries.move_to_end(page.id)
            self._evict_over_capacity()
            return loaded

    def clear(self) -> None:
        with self._lock:
            for entry in self._entries.values():
                entry.connection.close()
            self._entries.clear()

    def _load_page(self, *, page: PublishedPage, now: float) -> SnapshotDuckDBEntry:
        manifest = read_manifest(page, include_internal_paths=True)
        manifest_dir = Path(page.manifest_path).parent
        charts = manifest.get("charts")
        if not isinstance(charts, list):
            charts = []

        connection = duckdb.connect(database=":memory:")
        tables: dict[str, SnapshotTable] = {}
        try:
            for index, chart in enumerate(charts, start=1):
                if not isinstance(chart, dict):
                    continue
                chart_id = str(chart.get("chart_id") or f"chart_{index}")
                data_path = manifest_dir / str(chart.get("data_path") or "")
                if not data_path.exists():
                    raise ChartQueryAgentError(
                        code="SNAPSHOT_DATA_NOT_FOUND",
                        message=f"Snapshot data for chart '{chart_id}' was not found",
                        status_code=404,
                    )
                table_name = _safe_table_name(chart_id, fallback=f"chart_{index}")
                connection.execute(
                    f'CREATE TABLE "{table_name}" AS SELECT * FROM read_json_auto(?)',
                    [str(data_path)],
                )
                columns = [
                    {"name": str(row[1]), "type": str(row[2])}
                    for row in connection.execute(f'PRAGMA table_info("{table_name}")').fetchall()
                ]
                tables[chart_id] = SnapshotTable(
                    chart_id=chart_id,
                    table_name=table_name,
                    title=str(chart.get("title") or chart_id),
                    chart_type=str(chart.get("chart_type")) if chart.get("chart_type") else None,
                    columns=columns,
                )
        except Exception:
            connection.close()
            raise

        return SnapshotDuckDBEntry(
            page_id=page.id,
            connection=connection,
            tables=tables,
            created_at=now,
            last_accessed_at=now,
        )

    def _evict_expired(self, *, now: float) -> None:
        expired = [
            page_id
            for page_id, entry in self._entries.items()
            if now - entry.last_accessed_at > self.ttl_seconds
        ]
        for page_id in expired:
            entry = self._entries.pop(page_id)
            entry.connection.close()

    def _evict_over_capacity(self) -> None:
        while len(self._entries) > self.max_entries:
            _, entry = self._entries.popitem(last=False)
            entry.connection.close()


class SnapshotMCPTools:
    def __init__(self, *, cache: SnapshotDuckDBCache) -> None:
        self.cache = cache

    def list_snapshot_tables(self, *, page: PublishedPage) -> dict[str, Any]:
        entry = self.cache.get(page=page)
        return {
            "tables": [
                {
                    "chart_id": table.chart_id,
                    "table_name": table.table_name,
                    "title": table.title,
                    "chart_type": table.chart_type,
                }
                for table in entry.tables.values()
            ]
        }

    def describe_snapshot_table(
        self,
        *,
        page: PublishedPage,
        table_name: str,
        sample_limit: int = 8,
    ) -> dict[str, Any]:
        entry = self.cache.get(page=page)
        table = _find_table(entry, table_name=table_name)
        limit = max(1, min(int(sample_limit), 50))
        rows = entry.connection.execute(
            f'SELECT * FROM "{table.table_name}" LIMIT ?',
            [limit],
        ).fetchall()
        column_names = [item["name"] for item in table.columns]
        return {
            "chart_id": table.chart_id,
            "table_name": table.table_name,
            "title": table.title,
            "chart_type": table.chart_type,
            "columns": table.columns,
            "sample_rows": [dict(zip(column_names, row, strict=False)) for row in rows],
        }

    def query_snapshot_table(
        self,
        *,
        page: PublishedPage,
        sql: str,
        max_rows: int = 200,
    ) -> dict[str, Any]:
        entry = self.cache.get(page=page)
        table_names = {table.table_name for table in entry.tables.values()}
        columns_by_table = {
            table.table_name: {column["name"] for column in table.columns}
            for table in entry.tables.values()
        }
        validator = SQLReadOnlyValidator(
            allowed_tables=table_names,
            allowed_columns_by_table=columns_by_table,
        )
        try:
            validator.validate(sql)
        except SQLGuardError as exc:
            raise ChartQueryAgentError(
                code=exc.code,
                message=exc.message,
                status_code=400,
            ) from exc

        limit = max(1, min(int(max_rows), 200))
        cursor = entry.connection.execute(sql)
        column_names = [item[0] for item in cursor.description or []]
        rows = cursor.fetchmany(limit)
        return {
            "columns": column_names,
            "rows": [dict(zip(column_names, row, strict=False)) for row in rows],
            "row_count": len(rows),
        }


class ChartQueryAgent:
    def __init__(
        self,
        *,
        tools: SnapshotMCPTools | None = None,
        client_factory: type[ClaudeSDKClient] = ClaudeSDKClient,
    ) -> None:
        self.tools = tools or SnapshotMCPTools(cache=get_snapshot_duckdb_cache())
        self.client_factory = client_factory

    def load_skill_plugins(self) -> list[dict[str, str]]:
        """Return ``plugins=`` configs for skills assigned to ChartQueryAgent.

        Called from the SDK options builder when this agent is wired into a
        live ``ClaudeSDKClient`` loop. The current implementation of
        :meth:`run_turn` is a placeholder that does not instantiate
        ``ClaudeAgentOptions`` — when it does, it should pass the return value
        of this method as ``ClaudeAgentOptions.plugins``.
        """
        from .agent_skills.agents import CHART_QUERY_AGENT
        from .agent_skills.loader import load_skill_plugins_for_agent

        return load_skill_plugins_for_agent(CHART_QUERY_AGENT)

    def build_system_prompt(self, *, page: PublishedPage, chart_id: str | None = None) -> str:
        entry = self.tools.cache.get(page=page)
        table_summaries = [
            f"- {table.table_name}: {table.title}"
            + (f" ({table.chart_type})" if table.chart_type else "")
            + f"; columns: {', '.join(column['name'] for column in table.columns)}"
            for table in entry.tables.values()
        ]
        prompt = (
            "You are the published portal Chart Query Agent. "
            "Use only snapshot MCP tools: list_snapshot_tables, describe_snapshot_table, "
            "and query_snapshot_table. Answer from immutable published snapshot data only.\n\n"
            "Snapshot tables:\n"
            + "\n".join(table_summaries)
        )
        if chart_id:
            table = entry.tables.get(chart_id)
            if table is None:
                raise ChartQueryAgentError(
                    code="SNAPSHOT_CHART_NOT_FOUND",
                    message="Selected chart is not part of this published page",
                    status_code=404,
                )
            prompt += (
                "\n\nActive chart context:\n"
                f"table_name: {table.table_name}\n"
                f"chart_title: {table.title}\n"
                f"chart_type: {table.chart_type or 'unknown'}\n"
                f"columns: {', '.join(column['name'] for column in table.columns)}"
            )
        return prompt

    def run_turn(
        self,
        *,
        page: PublishedPage,
        message: str,
        request_id: str,
        conversation_id: str,
        chart_id: str | None = None,
    ) -> list[tuple[str, dict[str, Any]]]:
        system_prompt = self.build_system_prompt(page=page, chart_id=chart_id)
        _ = self.client_factory
        return [
            (
                "planning",
                {
                    "conversation_id": conversation_id,
                    "request_id": request_id,
                    "status": "running",
                    "text": "Planning against the published snapshot.",
                },
            ),
            (
                "final",
                {
                    "conversation_id": conversation_id,
                    "request_id": request_id,
                    "status": "completed",
                    "text": (
                        "Chart Query Agent is scoped to this published snapshot. "
                        "Snapshot tools are ready for read-only table questions."
                    ),
                    "table_context": "chart" if chart_id else "page",
                    "echo": message,
                },
            ),
        ]


_snapshot_duckdb_cache = SnapshotDuckDBCache()


def get_snapshot_duckdb_cache() -> SnapshotDuckDBCache:
    return _snapshot_duckdb_cache


def clear_snapshot_duckdb_cache() -> None:
    _snapshot_duckdb_cache.clear()


def format_sse(event_type: str, payload: dict[str, Any]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _find_table(entry: SnapshotDuckDBEntry, *, table_name: str) -> SnapshotTable:
    normalized = table_name.strip()
    for table in entry.tables.values():
        if table.table_name == normalized or table.chart_id == normalized:
            return table
    raise ChartQueryAgentError(
        code="SNAPSHOT_TABLE_NOT_FOUND",
        message="Snapshot table not found",
        status_code=404,
    )


def _safe_table_name(value: str, *, fallback: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip().lower()).strip("_")
    if not normalized:
        normalized = fallback
    if normalized[0].isdigit():
        normalized = f"chart_{normalized}"
    return normalized
