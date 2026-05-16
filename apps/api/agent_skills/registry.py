"""SQLite-backed registry for installed agent skills and per-agent assignments.

The registry lives in ``${UPLOAD_DIR}/state/agent_skills.sqlite3`` and mirrors the
existing ``state/*.sqlite3`` patterns: one DB file per concern, table create-if-
missing on first connection, no formal migration framework needed because the
schema is owned exclusively by this module.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any, Iterable

from ..config import get_settings


class SkillNotFoundError(KeyError):
    """Raised when a skill id is not present in the registry."""


VALID_STATUSES = {"enabled", "disabled"}


@dataclass(slots=True)
class AgentSkillRecord:
    id: str
    name: str
    version: str
    sha256: str
    status: str
    uploaded_by: str
    uploaded_at: int
    bundle_dir: str
    manifest: dict[str, Any] = field(default_factory=dict)
    load_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "sha256": self.sha256,
            "status": self.status,
            "uploaded_by": self.uploaded_by,
            "uploaded_at": self.uploaded_at,
            "bundle_dir": self.bundle_dir,
            "manifest": dict(self.manifest),
            "load_error": self.load_error,
        }


@dataclass(slots=True)
class AgentSkillAssignment:
    skill_id: str
    agent_name: str
    assigned_by: str
    assigned_at: int


_SCHEMA_SQL = (
    """
    CREATE TABLE IF NOT EXISTS agent_skills (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        version TEXT NOT NULL DEFAULT '',
        sha256 TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'enabled',
        uploaded_by TEXT NOT NULL,
        uploaded_at INTEGER NOT NULL,
        bundle_dir TEXT NOT NULL,
        manifest_json TEXT NOT NULL DEFAULT '{}',
        load_error TEXT,
        UNIQUE (name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_skill_assignments (
        skill_id TEXT NOT NULL,
        agent_name TEXT NOT NULL,
        assigned_by TEXT NOT NULL,
        assigned_at INTEGER NOT NULL,
        PRIMARY KEY (skill_id, agent_name),
        FOREIGN KEY (skill_id) REFERENCES agent_skills(id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_skill_assignments_agent ON agent_skill_assignments(agent_name)",
    "CREATE INDEX IF NOT EXISTS idx_skills_status ON agent_skills(status)",
)


class SkillRegistry:
    """Thread-safe registry; not designed for high write concurrency.

    The underlying SQLite file uses WAL mode so concurrent readers (agent runtime
    looking up assignments) do not block the rare admin writer.
    """

    def __init__(self, *, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._ensure_schema()

    # ------------------------------------------------------------------
    # Connection / schema
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _ensure_schema(self) -> None:
        with self._lock, self._connect() as conn:
            for stmt in _SCHEMA_SQL:
                conn.execute(stmt)
            conn.commit()

    # ------------------------------------------------------------------
    # Skill CRUD
    # ------------------------------------------------------------------

    def upsert(
        self,
        *,
        skill_id: str,
        name: str,
        version: str,
        sha256: str,
        uploaded_by: str,
        bundle_dir: str,
        manifest: dict[str, Any] | None = None,
        status: str = "enabled",
    ) -> AgentSkillRecord:
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status: {status!r}")
        now = int(time.time())
        payload = json.dumps(manifest or {}, ensure_ascii=False)
        with self._lock, self._connect() as conn:
            # If a row with the same name already exists we treat the operation as a
            # replace of that record — name is the unique skill identifier across
            # versions, and we keep one installed bundle per name at a time.
            existing = conn.execute(
                "SELECT id FROM agent_skills WHERE name = ?", (name,)
            ).fetchone()
            if existing is not None and str(existing["id"]) != skill_id:
                conn.execute("DELETE FROM agent_skills WHERE id = ?", (existing["id"],))
            conn.execute(
                """
                INSERT INTO agent_skills (
                    id, name, version, sha256, status, uploaded_by, uploaded_at,
                    bundle_dir, manifest_json, load_error
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    version = excluded.version,
                    sha256 = excluded.sha256,
                    status = excluded.status,
                    uploaded_by = excluded.uploaded_by,
                    uploaded_at = excluded.uploaded_at,
                    bundle_dir = excluded.bundle_dir,
                    manifest_json = excluded.manifest_json,
                    load_error = NULL
                """,
                (
                    skill_id,
                    name,
                    version,
                    sha256,
                    status,
                    uploaded_by,
                    now,
                    bundle_dir,
                    payload,
                ),
            )
            conn.commit()
        return self.get(skill_id)

    def get(self, skill_id: str) -> AgentSkillRecord:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_skills WHERE id = ?", (skill_id,)
            ).fetchone()
        if row is None:
            raise SkillNotFoundError(skill_id)
        return _row_to_record(row)

    def get_by_name(self, name: str) -> AgentSkillRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_skills WHERE name = ?", (name,)
            ).fetchone()
        return _row_to_record(row) if row else None

    def list(self) -> list[AgentSkillRecord]:
        with self._connect() as conn:
            # Tiebreak with rowid so rapid successive upserts in the same second
            # still come back newest-first.
            rows = conn.execute(
                "SELECT * FROM agent_skills ORDER BY uploaded_at DESC, rowid DESC"
            ).fetchall()
        return [_row_to_record(row) for row in rows]

    def set_status(self, skill_id: str, status: str) -> AgentSkillRecord:
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status: {status!r}")
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "UPDATE agent_skills SET status = ? WHERE id = ?",
                (status, skill_id),
            )
            if cursor.rowcount == 0:
                raise SkillNotFoundError(skill_id)
            conn.commit()
        return self.get(skill_id)

    def set_load_error(self, skill_id: str, error: str | None) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE agent_skills SET load_error = ? WHERE id = ?",
                (error, skill_id),
            )
            conn.commit()

    def delete(self, skill_id: str) -> None:
        with self._lock, self._connect() as conn:
            cursor = conn.execute("DELETE FROM agent_skills WHERE id = ?", (skill_id,))
            if cursor.rowcount == 0:
                raise SkillNotFoundError(skill_id)
            conn.commit()

    # ------------------------------------------------------------------
    # Assignments
    # ------------------------------------------------------------------

    def assign(self, *, skill_id: str, agent_name: str, assigned_by: str) -> AgentSkillAssignment:
        normalized_agent = agent_name.strip()
        if not normalized_agent:
            raise ValueError("agent_name is required")
        now = int(time.time())
        with self._lock, self._connect() as conn:
            # Ensure the skill exists — FK ON DELETE CASCADE only cares about the
            # other direction. Raise explicitly so callers can map to 404.
            skill_row = conn.execute(
                "SELECT 1 FROM agent_skills WHERE id = ?", (skill_id,)
            ).fetchone()
            if skill_row is None:
                raise SkillNotFoundError(skill_id)
            conn.execute(
                """
                INSERT INTO agent_skill_assignments (skill_id, agent_name, assigned_by, assigned_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(skill_id, agent_name) DO UPDATE SET
                    assigned_by = excluded.assigned_by,
                    assigned_at = excluded.assigned_at
                """,
                (skill_id, normalized_agent, assigned_by, now),
            )
            conn.commit()
        return AgentSkillAssignment(
            skill_id=skill_id,
            agent_name=normalized_agent,
            assigned_by=assigned_by,
            assigned_at=now,
        )

    def unassign(self, *, skill_id: str, agent_name: str) -> bool:
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM agent_skill_assignments WHERE skill_id = ? AND agent_name = ?",
                (skill_id, agent_name),
            )
            conn.commit()
            return cursor.rowcount > 0

    def list_assignments_for_skill(self, skill_id: str) -> list[AgentSkillAssignment]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_skill_assignments WHERE skill_id = ? ORDER BY agent_name",
                (skill_id,),
            ).fetchall()
        return [_row_to_assignment(row) for row in rows]

    def list_assignments_for_agent(self, agent_name: str) -> list[AgentSkillAssignment]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_skill_assignments WHERE agent_name = ? ORDER BY assigned_at",
                (agent_name,),
            ).fetchall()
        return [_row_to_assignment(row) for row in rows]


# ----------------------------------------------------------------------
# Module-level singleton helpers
# ----------------------------------------------------------------------


def _row_to_record(row: sqlite3.Row) -> AgentSkillRecord:
    manifest_raw = row["manifest_json"] if "manifest_json" in row.keys() else "{}"
    try:
        manifest = json.loads(manifest_raw) if manifest_raw else {}
    except (TypeError, ValueError):
        manifest = {}
    return AgentSkillRecord(
        id=str(row["id"]),
        name=str(row["name"]),
        version=str(row["version"] or ""),
        sha256=str(row["sha256"]),
        status=str(row["status"]),
        uploaded_by=str(row["uploaded_by"]),
        uploaded_at=int(row["uploaded_at"]),
        bundle_dir=str(row["bundle_dir"]),
        manifest=manifest if isinstance(manifest, dict) else {},
        load_error=row["load_error"] if row["load_error"] else None,
    )


def _row_to_assignment(row: sqlite3.Row) -> AgentSkillAssignment:
    return AgentSkillAssignment(
        skill_id=str(row["skill_id"]),
        agent_name=str(row["agent_name"]),
        assigned_by=str(row["assigned_by"]),
        assigned_at=int(row["assigned_at"]),
    )


@lru_cache(maxsize=2)
def _cached_registry(path_key: str) -> SkillRegistry:
    return SkillRegistry(db_path=Path(path_key))


def get_skill_registry() -> SkillRegistry:
    settings = get_settings()
    target = (settings.upload_dir / "state" / "agent_skills.sqlite3").resolve()
    return _cached_registry(str(target))


def clear_skill_registry_cache() -> None:
    _cached_registry.cache_clear()
