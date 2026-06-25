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


class PublishedPageError(Exception):
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


# Legacy visibility modes retained only for read-compat with rows written before
# the public-link migration. New publishes do not write visibility decisions.
VISIBILITY_MODES = {"private", "registered", "allowlist"}

# Public token entropy: 32 url-safe bytes -> ~256 bits, well above the 128-bit floor.
PUBLIC_TOKEN_BYTES = 32


class PublishWorkspaceRequest(BaseModel):
    """Publish payload after the public-link migration: layout/sidebar/charts only.

    Visibility fields are intentionally absent; the backend manages a single
    active public link per workspace instead.
    """

    model_config = {"extra": "ignore"}

    layout: dict[str, Any] = Field(default_factory=dict)
    sidebar: list[dict[str, Any]] = Field(default_factory=list)
    charts: list[PublishedChartSnapshot] = Field(default_factory=list)


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

        manifest = {
            "workspace_id": normalized_workspace_id,
            "version": version,
            "published_at": published_at,
            "layout": layout,
            "sidebar": sidebar,
            "charts": chart_entries,
        }
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


def read_manifest(page: PublishedPage) -> dict[str, Any]:
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


def read_chart_data(page: PublishedPage, *, chart_id: str) -> dict[str, Any]:
    manifest = read_manifest(page)
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
