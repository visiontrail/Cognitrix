from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any, Callable

from .config import get_settings
from .sqlite_support import connect as sqlite_connect

# ---------------------------------------------------------------------------
# Agent canvas mode — run/op persistence and the canvas tool contract.
#
# The op log is the server-side "semantic shadow" of a dashboard-generation
# run (design D5): every canvas mutation is appended here before it is pushed
# to any live SSE subscriber, so a reconnecting client can replay exactly what
# it missed and the model can be reminded of what it has already placed.
# Tables live in agent_sessions.sqlite3 next to the SDK session cache and are
# created lazily on first store use — with AGENT_CANVAS_MODE_ENABLED=false the
# store is never constructed and the database file is untouched.
# ---------------------------------------------------------------------------

RUN_STATUS_AWAITING_APPROVAL = "awaiting_approval"
RUN_STATUS_RUNNING = "running"
RUN_STATUS_COMPLETED = "completed"
RUN_STATUS_PARTIAL = "partial"
RUN_STATUS_STOPPED = "stopped"
RUN_STATUS_FAILED = "failed"
RUN_STATUS_CANCELED = "canceled"

TERMINAL_RUN_STATUSES = frozenset(
    {
        RUN_STATUS_COMPLETED,
        RUN_STATUS_PARTIAL,
        RUN_STATUS_STOPPED,
        RUN_STATUS_FAILED,
        RUN_STATUS_CANCELED,
    }
)
ACTIVE_RUN_STATUSES = frozenset({RUN_STATUS_AWAITING_APPROVAL, RUN_STATUS_RUNNING})

CANVAS_FORMAT_WEB_DESIGN = "web-design"

# Structure-only size presets (design D2). The client maps each preset to a
# fixed grid span; the server never computes or accepts geometry.
SIZE_PRESETS = ("kpi", "half", "wide", "full")
TEXT_STYLES = ("title", "subtitle", "body")

# Keep this catalog deliberately smaller than the general chat chart catalog.
# Agent-canvas charts are produced atomically from a flat readonly query, so we
# expose only types whose data contract the canvas spec builder can execute and
# render faithfully. The same tuple drives the SDK tool enum, prompt guidance,
# argument validation, and outline normalization.
AGENT_DASHBOARD_CHART_TYPES = (
    "single_value",
    "gauge",
    "bar",
    "negative_bar",
    "grouped_bar",
    "stacked_bar",
    "line",
    "stacked_line",
    "area",
    "pie",
    "scatter",
    "heatmap",
    "funnel",
    "treemap",
    "radar",
    "table",
)

_DASHBOARD_CHART_TYPE_ALIASES = {
    "single-value": "single_value",
    "singlevalue": "single_value",
    "negative-bar": "negative_bar",
    "negativebar": "negative_bar",
    "grouped-bar": "grouped_bar",
    "groupedbar": "grouped_bar",
    "horizontal-bar": "grouped_bar",
    "stacked-bar": "stacked_bar",
    "stackedbar": "stacked_bar",
    "stacked-line": "stacked_line",
    "stackedline": "stacked_line",
}

# Section nesting depth. 1 = section heading, 2 = sub-section heading; the client
# maps them onto the web-design text styles (title / subtitle). Deliberately
# capped at two levels: deeper nesting has no distinct rendering on the canvas.
SECTION_LEVELS = (1, 2)
MAX_SECTION_LEVEL = max(SECTION_LEVELS)

CANVAS_TOOL_NAMES = (
    "add_page",
    "add_section",
    "add_text_block",
    "place_chart",
    "finish_dashboard",
)

# Argument keys that smell like geometry; canvas tool schemas are structure-only
# and any of these in a call is rejected outright (agent-canvas-tools spec).
_GEOMETRY_ARGUMENT_KEYS = frozenset(
    {
        "x",
        "y",
        "w",
        "h",
        "width",
        "height",
        "col",
        "row",
        "column",
        "col_span",
        "row_span",
        "colspan",
        "rowspan",
        "position",
        "left",
        "top",
        "right",
        "bottom",
        "px",
        "grid_x",
        "grid_y",
    }
)

CANVAS_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "add_page",
            "description": (
                "Start a NEW page of the dashboard and make it the current page: every "
                "later add_section/add_text_block/place_chart call lands on it until the "
                "next add_page. The page appears as its own entry in the canvas page "
                "sidebar. Use one page per top-level subject of the outline — for example "
                "one page per department, region, or product line when the user asked for a "
                "per-entity breakdown. The run's first page already exists; call add_page "
                "only for the second and later pages."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Page title, in the user's language (also the sidebar label)",
                    },
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_section",
            "description": (
                "Add a section header to the CURRENT page (the page created by the most "
                "recent add_page, or the run's first page). Returns a section_id used by "
                "add_text_block/place_chart. Call once per outline section, in order. "
                "Layout is computed automatically — never pass coordinates or sizes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Section heading text"},
                    "level": {
                        "type": "integer",
                        "enum": list(SECTION_LEVELS),
                        "description": (
                            "Heading depth: 1 = section (default), 2 = sub-section nested "
                            "under the preceding level-1 section"
                        ),
                    },
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_text_block",
            "description": (
                "Add a text block (narrative, summary, or annotation) to the dashboard "
                "page being generated. Layout is computed automatically."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "section_id": {"type": "string", "description": "Section id returned by add_section"},
                    "content": {"type": "string", "description": "Text content, in the user's language"},
                    "style": {
                        "type": "string",
                        "enum": list(TEXT_STYLES),
                        "description": "Text style: title, subtitle, or body (default body)",
                    },
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "place_chart",
            "description": (
                "Produce ONE chart and place it on the dashboard page being generated, in a "
                "single atomic step: the query runs server-side, the chart spec is built, and "
                "the block is streamed to the canvas. The result returns metadata only (no data "
                "rows). Provide either `sql` (a readonly SELECT whose dimension column is "
                "aliased AS segment and numeric value AS metric_value) or `metric` (a catalog "
                "metric name with optional group_by/filters). Layout is computed automatically "
                "from size_preset — never pass coordinates."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "section_id": {"type": "string", "description": "Section id returned by add_section"},
                    "title": {"type": "string", "description": "Chart title, in the user's language"},
                    "chart_type": {
                        "type": "string",
                        "enum": list(AGENT_DASHBOARD_CHART_TYPES),
                        "description": (
                            "Visual type from the executable dashboard chart catalog. Preserve "
                            "the approved outline type; choose by analytical intent and data shape, "
                            "not by habit or for cosmetic variety."
                        ),
                    },
                    "size_preset": {
                        "type": "string",
                        "enum": list(SIZE_PRESETS),
                        "description": "Block size: kpi (small stat), half (half width), wide (full width), full (full width, tall)",
                    },
                    "sql": {
                        "type": "string",
                        "description": (
                            "Readonly SELECT returning the chart data; alias the dimension "
                            "column AS segment and the numeric value AS metric_value"
                        ),
                    },
                    "metric": {"type": "string", "description": "Semantic metric name from get_metric_catalog"},
                    "group_by": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Group-by columns for the metric query",
                    },
                    "filters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "field": {"type": "string"},
                                "op": {"type": "string"},
                                "value": {},
                            },
                        },
                        "description": "Filter conditions for the metric query",
                    },
                    "description": {
                        "type": "string",
                        "description": "One-line description of what the chart shows",
                    },
                },
                "required": ["title", "chart_type", "size_preset"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish_dashboard",
            "description": (
                "Declare the dashboard-generation run complete. REQUIRED terminal call: "
                "after every outline item has been placed (or failed), call this exactly "
                "once with a short completion summary in the user's language."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "1-3 sentence completion summary"},
                },
                "required": ["summary"],
            },
        },
    },
]


class AgentCanvasError(Exception):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message}


def validate_canvas_tool_arguments(tool_name: str, arguments: dict[str, Any]) -> None:
    """Structure-only schema validation shared by the guardrail and handler paths."""
    if tool_name not in CANVAS_TOOL_NAMES:
        raise AgentCanvasError(
            code="AGENT_CANVAS_TOOL_UNKNOWN",
            message=f"Unknown canvas tool '{tool_name}'.",
        )
    geometry_keys = sorted(
        key for key in arguments if key.lower() in _GEOMETRY_ARGUMENT_KEYS
    )
    if geometry_keys:
        raise AgentCanvasError(
            code="AGENT_CANVAS_GEOMETRY_FORBIDDEN",
            message=(
                "Canvas tools accept structure only; layout is computed by the client. "
                f"Remove geometry argument(s): {', '.join(geometry_keys)}."
            ),
        )

    if tool_name == "add_page":
        title = str(arguments.get("title") or "").strip()
        if not title:
            raise AgentCanvasError(
                code="AGENT_CANVAS_TITLE_REQUIRED",
                message="add_page requires a non-empty title.",
            )
    elif tool_name == "add_section":
        title = str(arguments.get("title") or "").strip()
        if not title:
            raise AgentCanvasError(
                code="AGENT_CANVAS_TITLE_REQUIRED",
                message="add_section requires a non-empty title.",
            )
        if "level" in arguments and normalize_section_level(arguments.get("level")) is None:
            raise AgentCanvasError(
                code="AGENT_CANVAS_SECTION_LEVEL_INVALID",
                message=(
                    "add_section level must be one of: "
                    f"{', '.join(str(level) for level in SECTION_LEVELS)}."
                ),
            )
    elif tool_name == "add_text_block":
        content = str(arguments.get("content") or "").strip()
        if not content:
            raise AgentCanvasError(
                code="AGENT_CANVAS_CONTENT_REQUIRED",
                message="add_text_block requires non-empty content.",
            )
        style = str(arguments.get("style") or "body").strip()
        if style not in TEXT_STYLES:
            raise AgentCanvasError(
                code="AGENT_CANVAS_TEXT_STYLE_INVALID",
                message=f"add_text_block style must be one of: {', '.join(TEXT_STYLES)}.",
            )
    elif tool_name == "place_chart":
        title = str(arguments.get("title") or "").strip()
        if not title:
            raise AgentCanvasError(
                code="AGENT_CANVAS_TITLE_REQUIRED",
                message="place_chart requires a non-empty title.",
            )
        chart_type = normalize_dashboard_chart_type(arguments.get("chart_type"))
        if chart_type is None:
            raise AgentCanvasError(
                code="AGENT_CANVAS_CHART_TYPE_INVALID",
                message=(
                    "chart_type must be one of: "
                    f"{', '.join(AGENT_DASHBOARD_CHART_TYPES)}."
                ),
            )
        size_preset = str(arguments.get("size_preset") or "").strip()
        if size_preset not in SIZE_PRESETS:
            raise AgentCanvasError(
                code="AGENT_CANVAS_SIZE_PRESET_INVALID",
                message=f"size_preset must be one of: {', '.join(SIZE_PRESETS)}.",
            )
        sql = str(arguments.get("sql") or "").strip()
        metric = str(arguments.get("metric") or "").strip()
        if not sql and not metric:
            raise AgentCanvasError(
                code="AGENT_CANVAS_QUERY_REQUIRED",
                message="place_chart requires either `sql` or `metric`.",
            )
    elif tool_name == "finish_dashboard":
        summary = str(arguments.get("summary") or "").strip()
        if not summary:
            raise AgentCanvasError(
                code="AGENT_CANVAS_SUMMARY_REQUIRED",
                message="finish_dashboard requires a non-empty summary.",
            )


def normalize_section_level(value: Any) -> int | None:
    """Coerce a model-supplied section level to 1/2, or None when unusable.

    Models routinely send `"2"` rather than `2`; a string that is not a valid
    level (or a float, or None) is rejected by the caller instead of silently
    collapsing to a top-level heading.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        level = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return level if level in SECTION_LEVELS else None


def normalize_dashboard_chart_type(value: Any) -> str | None:
    """Return a canonical executable dashboard chart type, or ``None``.

    Stored outlines from older builds and model-generated JSON may contain
    harmless case/hyphen drift. Normalize those aliases, but never coerce an
    unknown chart family to ``bar``: that was the silent visual downgrade this
    catalog is designed to prevent at tool execution time.
    """
    normalized = str(value or "").strip()
    if not normalized:
        return None
    lower_catalog = {item.lower(): item for item in AGENT_DASHBOARD_CHART_TYPES}
    direct = lower_catalog.get(normalized.lower())
    if direct:
        return direct
    return _DASHBOARD_CHART_TYPE_ALIASES.get(normalized.lower())


def block_id_for(run_id: str, seq: int) -> str:
    """Deterministic block id (canvas-op-streaming spec): run id + seq."""
    return f"agent-block-{run_id}-{seq}"


def page_id_for(run_id: str) -> str:
    """The run's root page — created automatically as the run's first op."""
    return f"agent-{run_id}"


def child_page_id_for(run_id: str, seq: int) -> str:
    """Deterministic id for a page opened mid-run by `add_page`.

    Derived from the op seq for the same reason block ids are: replay of the op
    log must rebuild byte-identical page ids, so re-attaching after a disconnect
    never duplicates a page.
    """
    return f"agent-{run_id}-p{seq}"


class AgentCanvasRunStore:
    """SQLite-backed run metadata + append-only op log (lazy schema init)."""

    def __init__(self, *, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = Lock()
        self._schema_ready = False

    # -- schema ------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        return sqlite_connect(self.db_path, create_parents=True)

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        if self._schema_ready:
            return
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_canvas_runs (
                run_id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                page_id TEXT NOT NULL,
                canvas_format TEXT NOT NULL,
                status TEXT NOT NULL,
                confirmation_id TEXT,
                outline_json TEXT,
                summary_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_canvas_runs_workspace "
            "ON agent_canvas_runs(workspace_id, updated_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_canvas_runs_confirmation "
            "ON agent_canvas_runs(confirmation_id)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_canvas_ops (
                run_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                op_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (run_id, seq)
            )
            """
        )
        conn.commit()
        self._schema_ready = True

    # -- runs ---------------------------------------------------------------

    def create_run(
        self,
        *,
        run_id: str | None = None,
        conversation_id: str,
        workspace_id: str,
        user_id: str,
        canvas_format: str,
        status: str = RUN_STATUS_AWAITING_APPROVAL,
        confirmation_id: str | None = None,
        outline: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        resolved_run_id = run_id or f"acr-{uuid.uuid4().hex}"
        now = _utc_now()
        with self._lock, self._connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                """
                INSERT INTO agent_canvas_runs (
                    run_id, conversation_id, workspace_id, user_id, page_id,
                    canvas_format, status, confirmation_id, outline_json,
                    summary_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    resolved_run_id,
                    conversation_id,
                    workspace_id,
                    user_id,
                    page_id_for(resolved_run_id),
                    canvas_format,
                    status,
                    confirmation_id,
                    json.dumps(outline, ensure_ascii=False, default=str) if outline is not None else None,
                    now,
                    now,
                ),
            )
            conn.commit()
        run = self.get_run(resolved_run_id)
        assert run is not None
        return run

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM agent_canvas_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return _serialize_run(row) if row is not None else None

    def get_run_by_confirmation(self, confirmation_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM agent_canvas_runs WHERE confirmation_id = ? "
                "ORDER BY updated_at DESC LIMIT 1",
                (confirmation_id,),
            ).fetchone()
        return _serialize_run(row) if row is not None else None

    def update_status(
        self,
        run_id: str,
        status: str,
        *,
        outline: dict[str, Any] | None = None,
        summary: dict[str, Any] | None = None,
    ) -> None:
        assignments = ["status = ?", "updated_at = ?"]
        params: list[Any] = [status, _utc_now()]
        if outline is not None:
            assignments.append("outline_json = ?")
            params.append(json.dumps(outline, ensure_ascii=False, default=str))
        if summary is not None:
            assignments.append("summary_json = ?")
            params.append(json.dumps(summary, ensure_ascii=False, default=str))
        params.append(run_id)
        with self._lock, self._connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                f"UPDATE agent_canvas_runs SET {', '.join(assignments)} WHERE run_id = ?",
                params,
            )
            conn.commit()

    def get_active_run(self, *, workspace_id: str, user_id: str) -> dict[str, Any] | None:
        """The workspace's in-flight run, or None."""
        placeholders = ",".join("?" for _ in ACTIVE_RUN_STATUSES)
        with self._lock, self._connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                f"SELECT * FROM agent_canvas_runs WHERE workspace_id = ? AND user_id = ? "
                f"AND status IN ({placeholders}) ORDER BY updated_at DESC LIMIT 1",
                (workspace_id, user_id, *sorted(ACTIVE_RUN_STATUSES)),
            ).fetchone()
        return _serialize_run(row) if row is not None else None

    def get_latest_run(self, *, workspace_id: str, user_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM agent_canvas_runs WHERE workspace_id = ? AND user_id = ? "
                "ORDER BY updated_at DESC LIMIT 1",
                (workspace_id, user_id),
            ).fetchone()
        return _serialize_run(row) if row is not None else None

    # -- ops ----------------------------------------------------------------

    def append_op(
        self,
        *,
        run_id: str,
        op_type: str,
        payload: dict[str, Any] | Callable[[int], dict[str, Any]],
    ) -> dict[str, Any]:
        """Append one op with a monotonic per-run seq.

        `payload` may be a callable receiving the allocated seq, so payloads can
        embed deterministic ids derived from it (block_id = run_id + seq).
        """
        now = _utc_now()
        with self._lock, self._connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) AS max_seq FROM agent_canvas_ops WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            seq = int(row["max_seq"]) + 1
            resolved_payload = payload(seq) if callable(payload) else dict(payload)
            conn.execute(
                "INSERT INTO agent_canvas_ops (run_id, seq, op_type, payload_json, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    run_id,
                    seq,
                    op_type,
                    json.dumps(resolved_payload, ensure_ascii=False, default=str),
                    now,
                ),
            )
            conn.execute(
                "UPDATE agent_canvas_runs SET updated_at = ? WHERE run_id = ?",
                (now, run_id),
            )
            conn.commit()
        return {
            "run_id": run_id,
            "seq": seq,
            "op_type": op_type,
            "payload": resolved_payload,
            "created_at": now,
        }

    def list_ops_after(self, *, run_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                "SELECT seq, op_type, payload_json, created_at FROM agent_canvas_ops "
                "WHERE run_id = ? AND seq > ? ORDER BY seq ASC",
                (run_id, int(after_seq)),
            ).fetchall()
        ops: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(str(row["payload_json"]))
            except (json.JSONDecodeError, TypeError):
                payload = {}
            ops.append(
                {
                    "run_id": run_id,
                    "seq": int(row["seq"]),
                    "op_type": str(row["op_type"]),
                    "payload": payload if isinstance(payload, dict) else {},
                    "created_at": str(row["created_at"]),
                }
            )
        return ops

    def find_page_for_block(self, *, run_id: str, block_id: str) -> str | None:
        """Which page a previously emitted block (usually a section) lives on.

        Charts and text blocks reference their section by id, so the section's
        own op — not a mutable server-side cursor — is the authority on which
        page they belong to. That keeps placement correct even when the model
        opens a new page before it has finished filling the previous one.
        """
        if not block_id:
            return None
        with self._lock, self._connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                "SELECT payload_json FROM agent_canvas_ops WHERE run_id = ? ORDER BY seq ASC",
                (run_id,),
            ).fetchall()
        for row in rows:
            try:
                payload = json.loads(str(row["payload_json"]))
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(payload, dict):
                continue
            if str(payload.get("block_id") or "") == block_id:
                return str(payload.get("page_id") or "") or None
        return None

    def count_ops(self, *, run_id: str, op_type: str | None = None) -> int:
        with self._lock, self._connect() as conn:
            self._ensure_schema(conn)
            if op_type is None:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM agent_canvas_ops WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM agent_canvas_ops WHERE run_id = ? AND op_type = ?",
                    (run_id, op_type),
                ).fetchone()
        return int(row["n"])

    def clear(self) -> None:
        with self._lock, self._connect() as conn:
            self._ensure_schema(conn)
            conn.execute("DELETE FROM agent_canvas_ops")
            conn.execute("DELETE FROM agent_canvas_runs")
            conn.commit()


def _serialize_run(row: sqlite3.Row) -> dict[str, Any]:
    outline: dict[str, Any] | None = None
    raw_outline = row["outline_json"]
    if raw_outline:
        try:
            parsed = json.loads(str(raw_outline))
            outline = parsed if isinstance(parsed, dict) else None
        except (json.JSONDecodeError, TypeError):
            outline = None
    summary: dict[str, Any] | None = None
    raw_summary = row["summary_json"]
    if raw_summary:
        try:
            parsed = json.loads(str(raw_summary))
            summary = parsed if isinstance(parsed, dict) else None
        except (json.JSONDecodeError, TypeError):
            summary = None
    return {
        "run_id": str(row["run_id"]),
        "conversation_id": str(row["conversation_id"]),
        "workspace_id": str(row["workspace_id"]),
        "user_id": str(row["user_id"]),
        "page_id": str(row["page_id"]),
        "canvas_format": str(row["canvas_format"]),
        "status": str(row["status"]),
        "confirmation_id": str(row["confirmation_id"]) if row["confirmation_id"] else None,
        "outline": outline,
        "summary": summary,
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@lru_cache(maxsize=2)
def _cached_run_store(db_path_str: str) -> AgentCanvasRunStore:
    return AgentCanvasRunStore(db_path=Path(db_path_str))


def get_agent_canvas_run_store() -> AgentCanvasRunStore:
    settings = get_settings()
    db_path = (settings.upload_dir / "state" / "agent_sessions.sqlite3").resolve()
    return _cached_run_store(str(db_path))


def clear_agent_canvas_run_store_cache() -> None:
    _cached_run_store.cache_clear()
