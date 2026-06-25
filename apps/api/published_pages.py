from __future__ import annotations

import json
import re
import secrets
import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import unquote, urlparse

from pydantic import BaseModel, Field, field_validator

from .config import get_settings
from .data_policy import forbidden_sensitive_columns, redact_rows

SQLITE_RELATIVE_BASE = Path(__file__).resolve().parent
PUBLISHED_SCHEMA_PATH = SQLITE_RELATIVE_BASE / "migrations" / "0004_published_pages_init.sql"

CANVAS_KIND_FREE_LAYOUT = "free_layout"
CANVAS_KIND_FIXED_SIZE = "fixed_size"
CANVAS_KIND_WEB_PAGE = "web_page"
SUPPORTED_CANVAS_KINDS = {CANVAS_KIND_FREE_LAYOUT, CANVAS_KIND_FIXED_SIZE, CANVAS_KIND_WEB_PAGE}
CANVAS_FORMAT_INFINITE = "infinite"
CANVAS_FORMAT_WEB_DESIGN = "web-design"
FIXED_CANVAS_PRESETS: dict[str, dict[str, int]] = {
    "a4-portrait": {"width": 794, "height": 1123},
    "a4-landscape": {"width": 1123, "height": 794},
    "a3-portrait": {"width": 1123, "height": 1587},
    "letter-portrait": {"width": 816, "height": 1056},
    "wide-16-9": {"width": 1280, "height": 720},
}
CANVAS_FORMAT_KINDS: dict[str, str] = {
    CANVAS_FORMAT_INFINITE: CANVAS_KIND_FREE_LAYOUT,
    CANVAS_FORMAT_WEB_DESIGN: CANVAS_KIND_WEB_PAGE,
    **{preset_id: CANVAS_KIND_FIXED_SIZE for preset_id in FIXED_CANVAS_PRESETS},
}
PUBLIC_NODE_TYPES = {"chart", "text", "stickyNote", "divider", "section"}
PUBLIC_NODE_DATA_FIELDS: dict[str, set[str]] = {
    "chart": {"type", "assetId", "title", "chartType", "width", "height"},
    "text": {"type", "content", "fontSize", "fontWeight", "color", "width", "height"},
    "stickyNote": {"type", "content", "color", "width", "height", "rotation"},
    "divider": {"type", "label", "lineStyle", "width", "rotation"},
    "section": {"type", "title", "width", "height"},
}


class PublishedPageError(Exception):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int = 400,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.extra = extra or {}

    def to_detail(self) -> dict[str, Any]:
        detail: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
        }
        detail.update(self.extra)
        return detail


class PublishedChartSnapshot(BaseModel):
    chart_id: str = Field(min_length=1)
    spec: dict[str, Any] = Field(default_factory=dict)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    title: str | None = None
    chart_type: str | None = None

    @field_validator("chart_id")
    @classmethod
    def validate_chart_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("chart_id is required")
        return normalized


class PublishedCanvasFormat(BaseModel):
    id: str = Field(min_length=1)

    @field_validator("id")
    @classmethod
    def validate_canvas_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("canvas format id is required")
        return normalized


class PublishedViewport(BaseModel):
    x: float = 0
    y: float = 0
    zoom: float = 1


# Legacy visibility modes retained only for read-compat with rows written before
# the public-link migration. New publishes do not write visibility decisions.
VISIBILITY_MODES = {"private", "registered", "allowlist"}

# Public token entropy: 32 url-safe bytes -> ~256 bits, well above the 128-bit floor.
PUBLIC_TOKEN_BYTES = 32


class PublishWorkspaceRequest(BaseModel):
    """Publish payload for the public-link snapshot lifecycle.

    Legacy Web Design clients may still submit ``layout`` and ``sidebar``.
    Canvas-aware clients submit the active ``canvas_format`` plus mode-specific
    ``nodes``/``edges`` or ``web_design`` payload.
    """

    model_config = {"extra": "ignore"}

    canvas_format: PublishedCanvasFormat | None = None
    viewport: PublishedViewport = Field(default_factory=PublishedViewport)
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    web_design: dict[str, Any] | None = None
    layout: dict[str, Any] = Field(default_factory=dict)
    sidebar: list[dict[str, Any]] = Field(default_factory=list)
    charts: list[PublishedChartSnapshot] = Field(default_factory=list)

    def canvas_format_id(self) -> str:
        return self.canvas_format.id if self.canvas_format else CANVAS_FORMAT_WEB_DESIGN

    def web_design_payload(self) -> dict[str, Any]:
        if isinstance(self.web_design, dict):
            return dict(self.web_design)
        return {"layout": self.layout, "sidebar": self.sidebar}


class PublishedPage(BaseModel):
    id: str
    workspace_id: str
    version: int
    published_at: str
    published_by: str
    manifest_path: str
    visibility_mode: str = "private"
    visibility_user_ids: list[str] = Field(default_factory=list)

    def to_history_item(self) -> dict[str, Any]:
        user_count = len(self.visibility_user_ids) if self.visibility_mode == "allowlist" else None
        return {
            "page_id": self.id,
            "version": self.version,
            "published_at": self.published_at,
            "published_by": self.published_by,
            "manifest_path": self.manifest_path,
            "canvas_format_id": manifest_canvas_format_id(self),
            "canvas_kind": manifest_canvas_kind(self),
            "visibility_mode": self.visibility_mode,
            "visibility_user_count": user_count,
            "visibility_user_ids": self.visibility_user_ids if self.visibility_mode == "allowlist" else [],
        }

    def is_visible_to(self, *, user_id: str, workspace_member_roles: set[str]) -> bool:
        if self.visibility_mode == "registered":
            return True
        if self.visibility_mode == "private":
            return bool(workspace_member_roles & {"owner", "editor"})
        if self.visibility_mode == "allowlist":
            if bool(workspace_member_roles & {"owner", "editor"}):
                return True
            if user_id and any(uid == user_id for uid in self.visibility_user_ids):
                return True
            return False
        return False


class PublicPublication(BaseModel):
    """Mutable public-link state pointing at the workspace's active snapshot version.

    Decoupled from workspace_id/page_id/version/user/timestamps via a high-entropy
    token. One active publication per workspace; revoke flips ``is_active`` to False.
    """

    workspace_id: str
    token: str
    active_page_id: str
    version: int
    is_active: bool
    published_at: str
    updated_at: str
    revoked_at: str | None = None

    def to_status(self, *, public_url: str | None = None) -> dict[str, Any]:
        return {
            "token": self.token,
            "public_url": public_url,
            "published_page_id": self.active_page_id,
            "version": self.version,
            "published_at": self.published_at,
            "is_active": self.is_active,
        }


def build_public_url(token: str, *, request_base_url: str | None = None) -> str:
    """Build a browser-openable public URL for ``token``.

    Priority: configured ``PUBLIC_BASE_URL``, then the request origin/base URL,
    then ``APP_URL``. Mirrors RavenAI's share-link URL resolution.
    """

    settings = get_settings()
    base = (settings.public_base_url or "").strip()
    if not base:
        base = (request_base_url or "").strip()
    if not base:
        base = (settings.app_url or "").strip()
    base = base.rstrip("/")
    return f"{base}/p/{token}"


@dataclass(slots=True)
class SnapshotWriteResult:
    manifest_path: Path
    manifest: dict[str, Any]


class SnapshotWriter:
    def __init__(self, *, upload_dir: Path, max_rows: int) -> None:
        self.upload_dir = upload_dir
        self.max_rows = max_rows

    def write(
        self,
        *,
        workspace_id: str,
        version: int,
        canvas_format_id: str,
        viewport: PublishedViewport | dict[str, Any] | None = None,
        nodes: list[dict[str, Any]] | None = None,
        edges: list[dict[str, Any]] | None = None,
        web_design: dict[str, Any] | None = None,
        layout: dict[str, Any],
        sidebar: list[dict[str, Any]],
        charts: list[PublishedChartSnapshot],
        actor_role: str,
        published_at: str,
    ) -> SnapshotWriteResult:
        normalized_workspace_id = workspace_id.strip()
        if not normalized_workspace_id:
            raise PublishedPageError(
                code="WORKSPACE_ID_REQUIRED",
                message="workspace_id is required",
                status_code=422,
            )
        canvas = build_canvas_metadata(canvas_format_id=canvas_format_id, viewport=viewport)
        canvas_kind = canvas["kind"]
        safe_nodes = normalize_public_nodes(nodes or [])
        safe_edges = normalize_public_edges(edges or [])
        if canvas_kind == CANVAS_KIND_FIXED_SIZE:
            offending_node_ids = validate_fixed_size_node_bounds(safe_nodes, canvas=canvas)
            if offending_node_ids:
                raise PublishedPageError(
                    code="PUBLISH_FIXED_NODE_OUT_OF_BOUNDS",
                    message="Fixed-size canvas contains nodes outside the page bounds",
                    status_code=422,
                    extra={"node_ids": offending_node_ids},
                )
        if canvas_kind == CANVAS_KIND_FREE_LAYOUT:
            canvas["bounds"] = compute_content_bounds(safe_nodes)

        target_dir = self.upload_dir / "published" / _safe_path_segment(normalized_workspace_id) / str(version)
        if target_dir.exists():
            shutil.rmtree(target_dir)
        charts_dir = target_dir / "charts"
        charts_dir.mkdir(parents=True, exist_ok=True)

        chart_entries: list[dict[str, Any]] = []
        for chart in charts:
            chart_dir = charts_dir / _safe_path_segment(chart.chart_id)
            chart_dir.mkdir(parents=True, exist_ok=True)

            rows = list(chart.rows)
            capped_rows = rows[: self.max_rows]
            data_truncated = len(rows) > self.max_rows
            safe_rows = self._sanitize_rows(capped_rows, role=actor_role)

            spec_payload = dict(chart.spec)
            spec_payload.setdefault("chart_id", chart.chart_id)
            if chart.title:
                spec_payload.setdefault("title", chart.title)
            if chart.chart_type:
                spec_payload.setdefault("chart_type", chart.chart_type)

            spec_path = chart_dir / "spec.json"
            data_path = chart_dir / "data.json"
            _write_json(spec_path, spec_payload)
            _write_json(data_path, safe_rows)

            chart_entries.append(
                {
                    "chart_id": chart.chart_id,
                    "title": chart.title or spec_payload.get("title") or chart.chart_id,
                    "chart_type": chart.chart_type or spec_payload.get("chart_type"),
                    "spec_path": _relative_posix(spec_path, target_dir),
                    "data_path": _relative_posix(data_path, target_dir),
                    "row_count": len(safe_rows),
                    "source_row_count": len(rows),
                    "data_truncated": data_truncated,
                }
            )

        if canvas_kind == CANVAS_KIND_WEB_PAGE:
            web_payload = dict(web_design or {})
            manifest_layout = web_payload.get("layout") if isinstance(web_payload.get("layout"), dict) else layout
            manifest_sidebar = (
                web_payload.get("sidebar") if isinstance(web_payload.get("sidebar"), list) else sidebar
            )
            content: dict[str, Any] = {
                "nodes": safe_nodes,
                "edges": safe_edges,
                "web_design": {"layout": manifest_layout, "sidebar": manifest_sidebar},
            }
        else:
            manifest_layout = {}
            manifest_sidebar = []
            content = {"nodes": safe_nodes, "edges": safe_edges}

        manifest = {
            "schema_version": 2,
            "workspace_id": normalized_workspace_id,
            "version": version,
            "published_at": published_at,
            "canvas": canvas,
            "content": content,
            "charts": chart_entries,
        }
        if canvas_kind == CANVAS_KIND_WEB_PAGE:
            # Keep legacy top-level fields for older public clients while schema
            # v2 renderers read through content.web_design.
            manifest["layout"] = manifest_layout
            manifest["sidebar"] = manifest_sidebar
        manifest_path = target_dir / "manifest.json"
        _write_json(manifest_path, manifest)
        return SnapshotWriteResult(manifest_path=manifest_path, manifest=manifest)

    def _sanitize_rows(self, rows: list[dict[str, Any]], *, role: str) -> list[dict[str, Any]]:
        blocked = forbidden_sensitive_columns(role)
        filtered_rows: list[dict[str, Any]] = []
        for row in rows:
            filtered_rows.append(
                {
                    key: value
                    for key, value in row.items()
                    if _normalize_identifier(str(key)) not in blocked
                }
            )
        return redact_rows(filtered_rows, role=role)


class PublishedPageStore:
    def __init__(self, *, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._init_schema()

    def next_version(self, *, workspace_id: str) -> int:
        normalized_workspace_id = workspace_id.strip()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(version), 0) AS latest_version FROM published_pages WHERE workspace_id = ?",
                (normalized_workspace_id,),
            ).fetchone()
        return int(row["latest_version"]) + 1 if row is not None else 1

    def create(
        self,
        *,
        workspace_id: str,
        version: int,
        published_by: str,
        manifest_path: Path,
        published_at: str | None = None,
        visibility_mode: str = "private",
        visibility_user_ids: list[str] | None = None,
    ) -> PublishedPage:
        normalized_workspace_id = workspace_id.strip()
        normalized_publisher = published_by.strip()
        if not normalized_workspace_id:
            raise PublishedPageError(
                code="WORKSPACE_ID_REQUIRED",
                message="workspace_id is required",
                status_code=422,
            )
        if not normalized_publisher:
            raise PublishedPageError(
                code="AUTH_REQUIRED",
                message="published_by is required",
                status_code=401,
            )

        page_id = uuid.uuid4().hex
        now = published_at or _utc_now()
        vis_user_ids_json = json.dumps(visibility_user_ids or [])
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO published_pages (
                    id, workspace_id, version, published_at, published_by, manifest_path,
                    visibility_mode, visibility_user_ids
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    page_id,
                    normalized_workspace_id,
                    version,
                    now,
                    normalized_publisher,
                    str(manifest_path),
                    visibility_mode,
                    vis_user_ids_json,
                ),
            )
            conn.commit()

        return PublishedPage(
            id=page_id,
            workspace_id=normalized_workspace_id,
            version=version,
            published_at=now,
            published_by=normalized_publisher,
            manifest_path=str(manifest_path),
            visibility_mode=visibility_mode,
            visibility_user_ids=visibility_user_ids or [],
        )

    def get(self, *, page_id: str) -> PublishedPage:
        normalized_page_id = page_id.strip()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, workspace_id, version, published_at, published_by, manifest_path,
                       COALESCE(visibility_mode, 'private') AS visibility_mode,
                       visibility_user_ids
                FROM published_pages
                WHERE id = ?
                """,
                (normalized_page_id,),
            ).fetchone()
        if row is None:
            raise PublishedPageError(
                code="PUBLISHED_PAGE_NOT_FOUND",
                message="Published page not found",
                status_code=404,
            )
        return self._serialize(row)

    def get_latest(self, *, workspace_id: str) -> PublishedPage:
        normalized_workspace_id = workspace_id.strip()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, workspace_id, version, published_at, published_by, manifest_path,
                       COALESCE(visibility_mode, 'private') AS visibility_mode,
                       visibility_user_ids
                FROM published_pages
                WHERE workspace_id = ?
                ORDER BY version DESC
                LIMIT 1
                """,
                (normalized_workspace_id,),
            ).fetchone()
        if row is None:
            raise PublishedPageError(
                code="PUBLISHED_PAGE_NOT_FOUND",
                message="Published page not found",
                status_code=404,
            )
        return self._serialize(row)

    def list_by_workspace(self, *, workspace_id: str) -> list[PublishedPage]:
        normalized_workspace_id = workspace_id.strip()
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, workspace_id, version, published_at, published_by, manifest_path,
                       COALESCE(visibility_mode, 'private') AS visibility_mode,
                       visibility_user_ids
                FROM published_pages
                WHERE workspace_id = ?
                ORDER BY version DESC
                """,
                (normalized_workspace_id,),
            ).fetchall()
        return [self._serialize(row) for row in rows]

    def list_latest_by_workspace(self) -> list[PublishedPage]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT pp.id, pp.workspace_id, pp.version, pp.published_at, pp.published_by,
                       pp.manifest_path,
                       COALESCE(pp.visibility_mode, 'private') AS visibility_mode,
                       pp.visibility_user_ids
                FROM published_pages AS pp
                JOIN (
                    SELECT workspace_id, MAX(version) AS version
                    FROM published_pages
                    GROUP BY workspace_id
                ) AS latest
                  ON latest.workspace_id = pp.workspace_id
                 AND latest.version = pp.version
                ORDER BY pp.published_at DESC
                """
            ).fetchall()
        return [self._serialize(row) for row in rows]

    def update_visibility(
        self,
        *,
        page_id: str,
        visibility_mode: str,
        visibility_user_ids: list[str],
    ) -> PublishedPage:
        vis_user_ids_json = json.dumps(visibility_user_ids)
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE published_pages
                SET visibility_mode = ?, visibility_user_ids = ?
                WHERE id = ?
                """,
                (visibility_mode, vis_user_ids_json, page_id),
            )
            conn.commit()
        return self.get(page_id=page_id)

    # --- Public publication (public-link) lifecycle -----------------------------

    def upsert_publication(
        self,
        *,
        workspace_id: str,
        active_page_id: str,
        version: int,
        published_at: str | None = None,
    ) -> PublicPublication:
        """Create or refresh the workspace's active public link.

        If an active publication already exists, its token and creation time are
        reused (refresh-in-place) and only the active snapshot pointer is updated.
        If none exists, or the previous one was revoked, a fresh high-entropy
        token is minted so revoked links never come back to life.
        """

        normalized_workspace_id = workspace_id.strip()
        normalized_page_id = active_page_id.strip()
        if not normalized_workspace_id:
            raise PublishedPageError(
                code="WORKSPACE_ID_REQUIRED",
                message="workspace_id is required",
                status_code=422,
            )
        now = published_at or _utc_now()
        with self._lock, self._connect() as conn:
            existing = conn.execute(
                """
                SELECT workspace_id, token, active_page_id, version, is_active,
                       published_at, updated_at, revoked_at
                FROM workspace_publications
                WHERE workspace_id = ?
                """,
                (normalized_workspace_id,),
            ).fetchone()

            if existing is not None and int(existing["is_active"]) == 1:
                token = str(existing["token"])
                first_published_at = str(existing["published_at"])
                conn.execute(
                    """
                    UPDATE workspace_publications
                    SET active_page_id = ?, version = ?, updated_at = ?,
                        is_active = 1, revoked_at = NULL
                    WHERE workspace_id = ?
                    """,
                    (normalized_page_id, version, now, normalized_workspace_id),
                )
            else:
                token = secrets.token_urlsafe(PUBLIC_TOKEN_BYTES)
                first_published_at = now
                conn.execute(
                    """
                    INSERT INTO workspace_publications (
                        workspace_id, token, active_page_id, version, is_active,
                        published_at, updated_at, revoked_at
                    ) VALUES (?, ?, ?, ?, 1, ?, ?, NULL)
                    ON CONFLICT(workspace_id) DO UPDATE SET
                        token = excluded.token,
                        active_page_id = excluded.active_page_id,
                        version = excluded.version,
                        is_active = 1,
                        published_at = excluded.published_at,
                        updated_at = excluded.updated_at,
                        revoked_at = NULL
                    """,
                    (normalized_workspace_id, token, normalized_page_id, version, now, now),
                )
            conn.commit()

        return PublicPublication(
            workspace_id=normalized_workspace_id,
            token=token,
            active_page_id=normalized_page_id,
            version=version,
            is_active=True,
            published_at=first_published_at,
            updated_at=now,
            revoked_at=None,
        )

    def get_publication(self, *, workspace_id: str) -> PublicPublication | None:
        normalized_workspace_id = workspace_id.strip()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT workspace_id, token, active_page_id, version, is_active,
                       published_at, updated_at, revoked_at
                FROM workspace_publications
                WHERE workspace_id = ?
                """,
                (normalized_workspace_id,),
            ).fetchone()
        if row is None:
            return None
        return self._serialize_publication(row)

    def revoke_publication(self, *, workspace_id: str) -> PublicPublication | None:
        normalized_workspace_id = workspace_id.strip()
        now = _utc_now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE workspace_publications
                SET is_active = 0, revoked_at = ?, updated_at = ?
                WHERE workspace_id = ?
                """,
                (now, now, normalized_workspace_id),
            )
            conn.commit()
        return self.get_publication(workspace_id=normalized_workspace_id)

    def resolve_active_publication(self, *, token: str) -> PublicPublication | None:
        """Return the active publication for a public token, or None.

        Returns None for unknown, inactive, or revoked tokens so callers can
        respond with an undifferentiated 404.
        """

        normalized_token = token.strip()
        if not normalized_token:
            return None
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT workspace_id, token, active_page_id, version, is_active,
                       published_at, updated_at, revoked_at
                FROM workspace_publications
                WHERE token = ? AND is_active = 1
                """,
                (normalized_token,),
            ).fetchone()
        if row is None:
            return None
        return self._serialize_publication(row)

    @staticmethod
    def _serialize_publication(row: sqlite3.Row) -> PublicPublication:
        return PublicPublication(
            workspace_id=str(row["workspace_id"]),
            token=str(row["token"]),
            active_page_id=str(row["active_page_id"]),
            version=int(row["version"]),
            is_active=bool(int(row["is_active"])),
            published_at=str(row["published_at"]),
            updated_at=str(row["updated_at"]),
            revoked_at=str(row["revoked_at"]) if row["revoked_at"] else None,
        )

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(PUBLISHED_SCHEMA_PATH.read_text(encoding="utf-8"))
            conn.commit()
            # Add legacy visibility columns (idempotent). Retained read-only for
            # rollback compatibility; new publishes no longer write them.
            for stmt in [
                "ALTER TABLE published_pages ADD COLUMN visibility_mode TEXT NOT NULL DEFAULT 'private'",
                "ALTER TABLE published_pages ADD COLUMN visibility_user_ids TEXT",
            ]:
                try:
                    conn.execute(stmt)
                    conn.commit()
                except Exception:
                    pass  # Column already exists
            # Public-link companion table: one active publication per workspace.
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workspace_publications (
                    workspace_id TEXT PRIMARY KEY,
                    token TEXT NOT NULL UNIQUE,
                    active_page_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    published_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    revoked_at TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_workspace_publications_token "
                "ON workspace_publications(token)"
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _serialize(row: sqlite3.Row) -> PublishedPage:
        raw_ids = row["visibility_user_ids"]
        try:
            vis_ids = json.loads(raw_ids) if raw_ids else []
            if not isinstance(vis_ids, list):
                vis_ids = []
        except (json.JSONDecodeError, TypeError):
            vis_ids = []
        return PublishedPage(
            id=str(row["id"]),
            workspace_id=str(row["workspace_id"]),
            version=int(row["version"]),
            published_at=str(row["published_at"]),
            published_by=str(row["published_by"]),
            manifest_path=str(row["manifest_path"]),
            visibility_mode=str(row["visibility_mode"]) if row["visibility_mode"] else "private",
            visibility_user_ids=[str(x) for x in vis_ids if x is not None],
        )


@lru_cache(maxsize=2)
def _cached_published_page_store(storage_key: str) -> PublishedPageStore:
    parsed = urlparse(storage_key)
    if parsed.scheme == "sqlite":
        db_path = _sqlite_db_path_from_url(storage_key).parent / "published_pages.sqlite3"
    else:
        state_root = Path(storage_key)
        state_root.mkdir(parents=True, exist_ok=True)
        db_path = state_root / "published_pages.sqlite3"
    return PublishedPageStore(db_path=db_path)


def get_published_page_store() -> PublishedPageStore:
    settings = get_settings()
    db_url = settings.database_url.strip()
    if db_url.startswith("sqlite://"):
        storage_key = db_url
    else:
        storage_key = str((settings.upload_dir / "state").resolve())
    return _cached_published_page_store(storage_key)


def clear_published_page_store_cache() -> None:
    _cached_published_page_store.cache_clear()


def get_snapshot_writer() -> SnapshotWriter:
    settings = get_settings()
    return SnapshotWriter(upload_dir=settings.upload_dir, max_rows=settings.agent_max_sql_rows)


def build_canvas_metadata(
    *,
    canvas_format_id: str,
    viewport: PublishedViewport | dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_format_id = canvas_format_id.strip()
    canvas_kind = CANVAS_FORMAT_KINDS.get(normalized_format_id)
    if not canvas_kind:
        raise PublishedPageError(
            code="PUBLISH_UNSUPPORTED_CANVAS_FORMAT",
            message=f"Unsupported canvas format: {normalized_format_id}",
            status_code=422,
        )

    viewport_payload = _normalize_viewport(viewport)
    canvas: dict[str, Any] = {
        "format_id": normalized_format_id,
        "kind": canvas_kind,
        "viewport": viewport_payload,
    }
    if canvas_kind == CANVAS_KIND_FIXED_SIZE:
        preset = FIXED_CANVAS_PRESETS[normalized_format_id]
        canvas["page"] = {
            "preset_id": normalized_format_id,
            "width": preset["width"],
            "height": preset["height"],
        }
    return canvas


def normalize_public_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        data = node.get("data")
        if not isinstance(data, dict):
            continue
        data_type = str(data.get("type") or "").strip()
        if data_type not in PUBLIC_NODE_TYPES:
            continue
        position = node.get("position") if isinstance(node.get("position"), dict) else {}
        width = _positive_float(node.get("width"), _positive_float(data.get("width"), 240))
        height = _positive_float(node.get("height"), _positive_float(data.get("height"), 160))
        allowed_fields = PUBLIC_NODE_DATA_FIELDS.get(data_type, {"type"})
        safe_data = {
            key: value
            for key, value in data.items()
            if key in allowed_fields and _is_json_safe_scalar_or_container(value)
        }
        safe_data["type"] = data_type
        if data_type == "chart" and "assetId" not in safe_data:
            continue
        normalized.append(
            {
                "id": str(node.get("id") or uuid.uuid4().hex),
                "type": str(node.get("type") or ""),
                "position": {
                    "x": _finite_float(position.get("x"), 0),
                    "y": _finite_float(position.get("y"), 0),
                },
                "width": width,
                "height": height,
                "data": safe_data,
                "hidden": bool(node.get("hidden", False)),
                "zIndex": _optional_int(node.get("zIndex")),
            }
        )
    return normalized


def normalize_public_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        source = str(edge.get("source") or "").strip()
        target = str(edge.get("target") or "").strip()
        if not source or not target:
            continue
        normalized.append(
            {
                "id": str(edge.get("id") or f"{source}-{target}"),
                "source": source,
                "target": target,
                "sourceHandle": str(edge["sourceHandle"]) if edge.get("sourceHandle") else None,
                "targetHandle": str(edge["targetHandle"]) if edge.get("targetHandle") else None,
                "type": str(edge["type"]) if edge.get("type") else None,
            }
        )
    return normalized


def validate_fixed_size_node_bounds(nodes: list[dict[str, Any]], *, canvas: dict[str, Any]) -> list[str]:
    page = canvas.get("page") if isinstance(canvas.get("page"), dict) else {}
    page_width = _positive_float(page.get("width"), 0)
    page_height = _positive_float(page.get("height"), 0)
    if page_width <= 0 or page_height <= 0:
        return [str(node.get("id") or "") for node in nodes if node.get("id")]
    offending: list[str] = []
    for node in nodes:
        if node.get("hidden"):
            continue
        position = node.get("position") if isinstance(node.get("position"), dict) else {}
        x = _finite_float(position.get("x"), 0)
        y = _finite_float(position.get("y"), 0)
        width = _positive_float(node.get("width"), 0)
        height = _positive_float(node.get("height"), 0)
        if x < 0 or y < 0 or x + width > page_width or y + height > page_height:
            offending.append(str(node.get("id") or "unknown"))
    return offending


def compute_content_bounds(nodes: list[dict[str, Any]]) -> dict[str, float]:
    visible_nodes = [node for node in nodes if not node.get("hidden")]
    if not visible_nodes:
        return {"x": 0, "y": 0, "width": 0, "height": 0}
    left = min(_finite_float((node.get("position") or {}).get("x"), 0) for node in visible_nodes)
    top = min(_finite_float((node.get("position") or {}).get("y"), 0) for node in visible_nodes)
    right = max(
        _finite_float((node.get("position") or {}).get("x"), 0) + _positive_float(node.get("width"), 0)
        for node in visible_nodes
    )
    bottom = max(
        _finite_float((node.get("position") or {}).get("y"), 0) + _positive_float(node.get("height"), 0)
        for node in visible_nodes
    )
    return {"x": left, "y": top, "width": max(0, right - left), "height": max(0, bottom - top)}


def read_raw_manifest(page: PublishedPage) -> dict[str, Any]:
    manifest_path = Path(page.manifest_path)
    if not manifest_path.exists():
        raise PublishedPageError(
            code="PUBLISHED_MANIFEST_NOT_FOUND",
            message="Published manifest not found",
            status_code=404,
        )
    decoded = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(decoded, dict):
        raise PublishedPageError(
            code="PUBLISHED_MANIFEST_INVALID",
            message="Published manifest is invalid",
            status_code=500,
        )
    return decoded


def read_manifest(page: PublishedPage, *, include_internal_paths: bool = False) -> dict[str, Any]:
    return normalize_manifest(read_raw_manifest(page), include_internal_paths=include_internal_paths)


def normalize_manifest(raw_manifest: dict[str, Any], *, include_internal_paths: bool = False) -> dict[str, Any]:
    if raw_manifest.get("schema_version") == 2:
        manifest = dict(raw_manifest)
        canvas = manifest.get("canvas") if isinstance(manifest.get("canvas"), dict) else {}
        canvas_format_id = str(canvas.get("format_id") or CANVAS_FORMAT_WEB_DESIGN)
        try:
            normalized_canvas = build_canvas_metadata(
                canvas_format_id=canvas_format_id,
                viewport=canvas.get("viewport") if isinstance(canvas, dict) else None,
            )
        except PublishedPageError:
            normalized_canvas = {
                "format_id": canvas_format_id,
                "kind": str(canvas.get("kind") or ""),
                "viewport": _normalize_viewport(canvas.get("viewport")),
            }
            if isinstance(canvas.get("page"), dict):
                normalized_canvas["page"] = dict(canvas["page"])
        if isinstance(canvas.get("bounds"), dict):
            normalized_canvas["bounds"] = {
                "x": _finite_float(canvas["bounds"].get("x"), 0),
                "y": _finite_float(canvas["bounds"].get("y"), 0),
                "width": _positive_float(canvas["bounds"].get("width"), 0),
                "height": _positive_float(canvas["bounds"].get("height"), 0),
            }
        manifest["canvas"] = normalized_canvas
        content = manifest.get("content") if isinstance(manifest.get("content"), dict) else {}
        manifest["content"] = {
            "nodes": normalize_public_nodes(content.get("nodes") if isinstance(content.get("nodes"), list) else []),
            "edges": normalize_public_edges(content.get("edges") if isinstance(content.get("edges"), list) else []),
            **({"web_design": content["web_design"]} if isinstance(content.get("web_design"), dict) else {}),
        }
        manifest["charts"] = _normalize_chart_entries(manifest.get("charts"), include_internal_paths=include_internal_paths)
        return manifest

    layout = raw_manifest.get("layout") if isinstance(raw_manifest.get("layout"), dict) else {}
    sidebar = raw_manifest.get("sidebar") if isinstance(raw_manifest.get("sidebar"), list) else []
    return {
        "schema_version": 2,
        "workspace_id": str(raw_manifest.get("workspace_id") or ""),
        "version": int(raw_manifest.get("version") or 0),
        "published_at": str(raw_manifest.get("published_at") or ""),
        "canvas": build_canvas_metadata(canvas_format_id=CANVAS_FORMAT_WEB_DESIGN),
        "content": {
            "nodes": [],
            "edges": [],
            "web_design": {"layout": layout, "sidebar": sidebar},
        },
        "layout": layout,
        "sidebar": sidebar,
        "charts": _normalize_chart_entries(raw_manifest.get("charts"), include_internal_paths=include_internal_paths),
    }


def manifest_canvas_format_id(page: PublishedPage) -> str:
    try:
        manifest = read_manifest(page)
        canvas = manifest.get("canvas") if isinstance(manifest.get("canvas"), dict) else {}
        return str(canvas.get("format_id") or CANVAS_FORMAT_WEB_DESIGN)
    except PublishedPageError:
        return CANVAS_FORMAT_WEB_DESIGN


def manifest_canvas_kind(page: PublishedPage) -> str:
    try:
        manifest = read_manifest(page)
        canvas = manifest.get("canvas") if isinstance(manifest.get("canvas"), dict) else {}
        return str(canvas.get("kind") or CANVAS_KIND_WEB_PAGE)
    except PublishedPageError:
        return CANVAS_KIND_WEB_PAGE


def read_chart_data(page: PublishedPage, *, chart_id: str) -> dict[str, Any]:
    manifest = read_manifest(page, include_internal_paths=True)
    chart_entries = manifest.get("charts")
    if not isinstance(chart_entries, list):
        chart_entries = []
    chart_entry = next(
        (
            item
            for item in chart_entries
            if isinstance(item, dict) and str(item.get("chart_id") or "") == chart_id
        ),
        None,
    )
    if chart_entry is None:
        raise PublishedPageError(
            code="PUBLISHED_CHART_NOT_FOUND",
            message="Published chart not found",
            status_code=404,
        )

    manifest_dir = Path(page.manifest_path).parent
    spec = _read_json_file(manifest_dir / str(chart_entry.get("spec_path") or ""))
    rows = _read_json_file(manifest_dir / str(chart_entry.get("data_path") or ""))
    return {
        "page_id": page.id,
        "chart_id": chart_id,
        "spec": spec if isinstance(spec, dict) else {},
        "rows": rows if isinstance(rows, list) else [],
        "data_truncated": bool(chart_entry.get("data_truncated")),
    }


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


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _read_json_file(path: Path) -> Any:
    if not path.exists():
        raise PublishedPageError(
            code="PUBLISHED_SNAPSHOT_FILE_NOT_FOUND",
            message="Published snapshot file not found",
            status_code=404,
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_chart_entries(value: Any, *, include_internal_paths: bool) -> list[dict[str, Any]]:
    entries = value if isinstance(value, list) else []
    normalized: list[dict[str, Any]] = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        chart_id = str(item.get("chart_id") or "").strip()
        if not chart_id:
            continue
        entry = {
            "chart_id": chart_id,
            "title": str(item.get("title") or chart_id),
            "chart_type": str(item["chart_type"]) if item.get("chart_type") else None,
            "row_count": int(item.get("row_count") or 0),
            "source_row_count": int(item.get("source_row_count") or 0),
            "data_truncated": bool(item.get("data_truncated")),
        }
        if include_internal_paths:
            entry["spec_path"] = str(item.get("spec_path") or "")
            entry["data_path"] = str(item.get("data_path") or "")
        normalized.append(entry)
    return normalized


def _normalize_viewport(value: PublishedViewport | dict[str, Any] | None) -> dict[str, float]:
    if isinstance(value, PublishedViewport):
        raw = value.model_dump()
    elif isinstance(value, dict):
        raw = value
    else:
        raw = {}
    zoom = _finite_float(raw.get("zoom"), 1)
    if zoom <= 0:
        zoom = 1
    return {
        "x": _finite_float(raw.get("x"), 0),
        "y": _finite_float(raw.get("y"), 0),
        "zoom": zoom,
    }


def _finite_float(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number or number in {float("inf"), float("-inf")}:
        return default
    return number


def _positive_float(value: Any, default: float) -> float:
    return max(0, _finite_float(value, default))


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_json_safe_scalar_or_container(value: Any) -> bool:
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, list):
        return all(_is_json_safe_scalar_or_container(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _is_json_safe_scalar_or_container(item)
            for key, item in value.items()
        )
    return False


def _safe_path_segment(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip())
    normalized = normalized.strip(".-")
    return normalized or uuid.uuid4().hex


def _relative_posix(path: Path, base: Path) -> str:
    return path.relative_to(base).as_posix()


def _normalize_identifier(value: str) -> str:
    lowered = value.strip().lower()
    lowered = re.sub(r"\s+", "_", lowered)
    lowered = re.sub(r"[^a-z0-9_]+", "_", lowered)
    return re.sub(r"_+", "_", lowered).strip("_")
