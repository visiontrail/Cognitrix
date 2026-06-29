from __future__ import annotations

import logging
import re
import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from threading import Lock
from urllib.parse import unquote, urlparse

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from .agentic_ingestion.schema import initialize_sqlite_schema
from .audit import get_audit_logger
from .auth import AuthIdentity, get_current_identity, require_permission
from .config import get_settings
from .datasets import DuckDBSessionManager
from .published_pages import (
    CANVAS_KIND_WEB_PAGE,
    VISIBILITY_ALLOWLIST,
    PublishedPageError,
    PublishedPage,
    PublicPublication,
    PublishWorkspaceRequest,
    canvas_kind_for_format,
    get_published_page_store,
    get_snapshot_writer,
    manifest_canvas_format_id,
    manifest_canvas_kind,
    read_chart_data,
    read_manifest,
)

logger = logging.getLogger("cognitrix.workspaces")

SQLITE_RELATIVE_BASE = Path(__file__).resolve().parent
ROLE_RANK: dict[str, int] = {
    "viewer": 0,
    "editor": 1,
    "admin": 2,
    "owner": 3,
}

# After the public-link migration, user-facing workspace membership is
# owner/editor only. ``viewer`` is no longer a valid collaboration role; legacy
# viewer rows are neutralized on startup and never grant workspace access.
VALID_MEMBERSHIP_ROLES: frozenset[str] = frozenset({"owner", "editor"})


class WorkspaceError(Exception):
    def __init__(self, *, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code

    def to_detail(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
        }


class CreateWorkspaceRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Workspace name cannot be empty")
        return normalized


class UpdateWorkspaceRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Workspace name cannot be empty")
        return normalized


class AddWorkspaceMemberRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    role: str = Field(default="editor")
    email: str | None = None
    display_name: str | None = None

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("user_id is required")
        return normalized

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in VALID_MEMBERSHIP_ROLES:
            raise ValueError("Workspace membership role must be owner or editor")
        return normalized


class UpdateMemberRoleRequest(BaseModel):
    role: str = Field(default="editor")

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized != "editor":
            raise ValueError("Workspace member role can only be set to editor")
        return normalized


class CreateInviteRequest(BaseModel):
    role: str = Field(default="editor")
    expires_in_days: int | None = None
    max_uses: int | None = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized != "editor":
            raise ValueError("Invite role must be editor")
        return normalized


@dataclass(slots=True)
class MemberRecord:
    user_id: str
    role: str


class WorkspaceService:
    def __init__(self, *, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._initialize_schema()

    def create_workspace(self, *, owner_user_id: str, name: str) -> dict[str, str]:
        normalized_name = name.strip()
        if not normalized_name:
            raise WorkspaceError(
                code="WORKSPACE_NAME_REQUIRED",
                message="Workspace name is required",
                status_code=422,
            )

        normalized_owner = owner_user_id.strip()
        if not normalized_owner:
            raise WorkspaceError(
                code="AUTH_REQUIRED",
                message="user_id is required",
                status_code=401,
            )

        workspace_id = uuid.uuid4().hex

        with self._lock, self._connect() as conn:
            self._ensure_user(conn, user_id=normalized_owner, email=None, display_name=None)
            slug = self._allocate_slug(conn, normalized_name)
            now = _utc_now()

            conn.execute(
                """
                INSERT INTO workspaces (
                    id, name, slug, owner_user_id, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'active', ?, ?)
                """,
                (workspace_id, normalized_name, slug, normalized_owner, now, now),
            )
            conn.execute(
                """
                INSERT INTO workspace_members (
                    id, workspace_id, user_id, role, created_at
                ) VALUES (?, ?, ?, 'owner', ?)
                """,
                (uuid.uuid4().hex, workspace_id, normalized_owner, now),
            )
            conn.commit()

        return {
            "workspace_id": workspace_id,
            "name": normalized_name,
            "slug": slug,
            "role": "owner",
        }

    def list_workspaces_for_user(self, *, user_id: str) -> list[dict[str, str]]:
        normalized_user = user_id.strip()
        if not normalized_user:
            return []

        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    w.id,
                    w.name,
                    w.slug,
                    w.status,
                    w.created_at,
                    w.updated_at,
                    wm.role
                FROM workspaces AS w
                JOIN workspace_members AS wm
                  ON wm.workspace_id = w.id
                WHERE wm.user_id = ? AND w.status = 'active'
                  AND wm.role IN ('owner', 'editor')
                ORDER BY w.updated_at DESC
                """,
                (normalized_user,),
            ).fetchall()

        return [self._serialize_workspace(row) for row in rows]

    def list_workspace_summaries(
        self,
        *,
        workspace_ids: list[str],
        user_id: str | None = None,
    ) -> list[dict[str, str]]:
        normalized_ids = [item.strip() for item in workspace_ids if item.strip()]
        if not normalized_ids:
            return []

        placeholders = ",".join("?" for _ in normalized_ids)
        params: list[str] = [*normalized_ids]
        user_join = ""
        user_where = ""
        if user_id is not None and user_id.strip():
            user_join = "JOIN workspace_members AS wm ON wm.workspace_id = w.id"
            user_where = "AND wm.user_id = ?"
            params.append(user_id.strip())

        with self._lock, self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT w.id, w.name, w.slug, w.status, w.created_at, w.updated_at
                FROM workspaces AS w
                {user_join}
                WHERE w.id IN ({placeholders}) AND w.status = 'active'
                {user_where}
                """,
                params,
            ).fetchall()

        summaries_by_id = {
            str(row["id"]): {
                "workspace_id": str(row["id"]),
                "name": str(row["name"]),
                "slug": str(row["slug"]),
                "status": str(row["status"]),
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
            }
            for row in rows
        }
        return [summaries_by_id[item] for item in normalized_ids if item in summaries_by_id]

    def get_workspace_for_user(self, *, workspace_id: str, user_id: str) -> dict[str, str]:
        normalized_workspace_id = workspace_id.strip()
        normalized_user = user_id.strip()
        if not normalized_workspace_id or not normalized_user:
            raise WorkspaceError(
                code="WORKSPACE_FORBIDDEN",
                message="You do not have permission to access this workspace",
                status_code=403,
            )

        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    w.id,
                    w.name,
                    w.slug,
                    w.status,
                    w.created_at,
                    w.updated_at,
                    wm.role
                FROM workspaces AS w
                JOIN workspace_members AS wm
                  ON wm.workspace_id = w.id
                WHERE w.id = ? AND wm.user_id = ? AND w.status = 'active'
                """,
                (normalized_workspace_id, normalized_user),
            ).fetchone()

        if row is None:
            raise WorkspaceError(
                code="WORKSPACE_FORBIDDEN",
                message="You do not have permission to access this workspace",
                status_code=403,
            )

        return self._serialize_workspace(row)

    def assert_workspace_access(
        self,
        *,
        workspace_id: str,
        user_id: str,
        minimum_role: str = "editor",
    ) -> str:
        normalized_workspace_id = workspace_id.strip()
        normalized_user = user_id.strip()
        normalized_minimum_role = minimum_role.strip().lower()

        if normalized_minimum_role not in ROLE_RANK:
            raise WorkspaceError(
                code="WORKSPACE_ROLE_INVALID",
                message="Unsupported workspace role requirement",
                status_code=500,
            )

        with self._lock, self._connect() as conn:
            member = self._get_member(conn, workspace_id=normalized_workspace_id, user_id=normalized_user)

        if member is None:
            raise WorkspaceError(
                code="WORKSPACE_FORBIDDEN",
                message="You do not have permission to access this workspace",
                status_code=403,
            )

        if ROLE_RANK[member.role] < ROLE_RANK[normalized_minimum_role]:
            raise WorkspaceError(
                code="WORKSPACE_FORBIDDEN",
                message="You do not have permission to access this workspace",
                status_code=403,
            )

        return member.role

    def rename_workspace(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
        name: str,
    ) -> dict[str, str]:
        normalized_workspace_id = workspace_id.strip()
        normalized_actor = actor_user_id.strip()
        normalized_name = name.strip()

        if not normalized_name:
            raise WorkspaceError(
                code="WORKSPACE_NAME_REQUIRED",
                message="Workspace name is required",
                status_code=422,
            )

        with self._lock, self._connect() as conn:
            actor_member = self._get_member(
                conn,
                workspace_id=normalized_workspace_id,
                user_id=normalized_actor,
            )
            if actor_member is None or ROLE_RANK[actor_member.role] < ROLE_RANK["editor"]:
                raise WorkspaceError(
                    code="WORKSPACE_FORBIDDEN",
                    message="You do not have permission to access this workspace",
                    status_code=403,
                )

            workspace_row = conn.execute(
                """
                SELECT id, slug, status, created_at, updated_at
                FROM workspaces
                WHERE id = ?
                """,
                (normalized_workspace_id,),
            ).fetchone()
            if workspace_row is None or str(workspace_row["status"]) != "active":
                raise WorkspaceError(
                    code="WORKSPACE_NOT_FOUND",
                    message="Workspace not found",
                    status_code=404,
                )

            now = _utc_now()
            conn.execute(
                """
                UPDATE workspaces
                SET name = ?, updated_at = ?
                WHERE id = ?
                """,
                (normalized_name, now, normalized_workspace_id),
            )
            conn.commit()

            return {
                "workspace_id": normalized_workspace_id,
                "name": normalized_name,
                "slug": str(workspace_row["slug"]),
                "status": "active",
                "role": actor_member.role,
                "created_at": str(workspace_row["created_at"]),
                "updated_at": now,
            }

    def deactivate_workspace(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
        confirm_workspace_name: str | None = None,
    ) -> dict[str, object]:
        """Hard-delete a workspace and every piece of state attached to it.

        Cascade order is fixed to satisfy the implicit FK graph in the SQLite
        schema. Filesystem cleanup (workspace DuckDB file, uploaded raw files,
        snapshot directory) runs AFTER the SQL transaction commits — failures
        there are logged but do not roll back the SQL state, because by then
        the rows are gone and a partial filesystem leak is preferable to a
        zombie workspace whose UI listing is gone but whose data lingers.

        ``confirm_workspace_name`` is the typed-confirmation guardrail. When
        provided, it must equal the workspace's current ``name``; otherwise we
        reject before touching anything. Callers (e.g. the sidebar delete
        flow) are expected to pass it; legacy callers that omit it still get
        the deletion (backward compat) but lose the safety net.
        """
        normalized_workspace_id = workspace_id.strip()
        normalized_actor = actor_user_id.strip()
        deleted_at = _utc_now()
        normalized_confirm = (
            confirm_workspace_name.strip() if confirm_workspace_name is not None else None
        )

        settings = get_settings()
        upload_dir = settings.upload_dir
        duckdb_file_path: Path | None = None
        uploads_dir_to_remove: Path | None = None
        deleted_counts: dict[str, int] = {}
        workspace_name = ""

        with self._lock, self._connect() as conn:
            actor_member = self._get_member(
                conn,
                workspace_id=normalized_workspace_id,
                user_id=normalized_actor,
            )
            if actor_member is None or ROLE_RANK[actor_member.role] < ROLE_RANK["admin"]:
                raise WorkspaceError(
                    code="WORKSPACE_FORBIDDEN",
                    message="You do not have permission to access this workspace",
                    status_code=403,
                )

            workspace_row = conn.execute(
                """
                SELECT id, name, status
                FROM workspaces
                WHERE id = ?
                """,
                (normalized_workspace_id,),
            ).fetchone()
            if workspace_row is None or str(workspace_row["status"]) != "active":
                raise WorkspaceError(
                    code="WORKSPACE_NOT_FOUND",
                    message="Workspace not found",
                    status_code=404,
                )
            workspace_name = str(workspace_row["name"])

            if normalized_confirm is not None and normalized_confirm != workspace_name:
                raise WorkspaceError(
                    code="WORKSPACE_DELETE_CONFIRM_MISMATCH",
                    message=(
                        "Confirmation does not match the workspace name. "
                        f"Type the workspace name '{workspace_name}' to confirm."
                    ),
                    status_code=422,
                )

            # Filesystem targets — resolve while we still know the workspace exists.
            duckdb_file_path = DuckDBSessionManager(upload_dir).workspace_db_path(
                normalized_workspace_id
            )
            uploads_dir_to_remove = (
                upload_dir / "agentic_ingestion" / "raw" / normalized_workspace_id
            ).resolve()

            # Cascade DELETE order: leaves first, parents last. Each step is a
            # plain DELETE that runs in the surrounding transaction. We capture
            # rowcounts for the audit event.
            cascade_plan: list[tuple[str, str]] = [
                # ingestion_executions → ingestion_proposals → ingestion_jobs
                (
                    "ingestion_executions",
                    "DELETE FROM ingestion_executions WHERE workspace_id = ?",
                ),
                (
                    "ingestion_proposals",
                    "DELETE FROM ingestion_proposals WHERE workspace_id = ?",
                ),
                (
                    "ingestion_events",
                    "DELETE FROM ingestion_events WHERE job_id IN ("
                    "SELECT id FROM ingestion_jobs WHERE workspace_id = ?)",
                ),
                (
                    "ingestion_jobs",
                    "DELETE FROM ingestion_jobs WHERE workspace_id = ?",
                ),
                (
                    "ingestion_uploads",
                    "DELETE FROM ingestion_uploads WHERE workspace_id = ?",
                ),
                (
                    "table_column_metadata",
                    "DELETE FROM table_column_metadata WHERE workspace_id = ?",
                ),
                (
                    "table_catalog",
                    "DELETE FROM table_catalog WHERE workspace_id = ?",
                ),
                # ai_views + version history. ai_view_versions FKs ai_views with
                # ON DELETE CASCADE so deleting the parent is sufficient in
                # principle, but PRAGMA foreign_keys is OFF for this connection
                # (see _connect). Delete the version rows explicitly first.
                (
                    "ai_view_versions",
                    "DELETE FROM ai_view_versions WHERE view_id IN ("
                    "SELECT view_id FROM ai_views WHERE workspace_id = ?)",
                ),
                (
                    "ai_views",
                    "DELETE FROM ai_views WHERE workspace_id = ?",
                ),
                (
                    "published_pages",
                    "DELETE FROM published_pages WHERE workspace_id = ?",
                ),
                # Server-side chat history, chart assets, and canvas snapshot
                # (see workspace_state.py). These live in this same SQLite file.
                (
                    "chat_messages",
                    "DELETE FROM chat_messages WHERE workspace_id = ?",
                ),
                (
                    "chat_sessions",
                    "DELETE FROM chat_sessions WHERE workspace_id = ?",
                ),
                (
                    "chart_assets",
                    "DELETE FROM chart_assets WHERE workspace_id = ?",
                ),
                (
                    "workspace_snapshots",
                    "DELETE FROM workspace_snapshots WHERE workspace_id = ?",
                ),
                (
                    "workspace_invites",
                    "DELETE FROM workspace_invites WHERE workspace_id = ?",
                ),
                (
                    "workspace_members",
                    "DELETE FROM workspace_members WHERE workspace_id = ?",
                ),
                (
                    "workspaces",
                    "DELETE FROM workspaces WHERE id = ?",
                ),
            ]
            try:
                conn.execute("BEGIN")
                for table_name, sql in cascade_plan:
                    try:
                        cursor = conn.execute(sql, (normalized_workspace_id,))
                        deleted_counts[table_name] = int(cursor.rowcount or 0)
                    except sqlite3.OperationalError as exc:
                        # Tolerate missing tables (e.g. published_pages absent in a
                        # fresh dev DB before that migration ran) — the rest of the
                        # cascade still needs to commit.
                        if "no such table" in str(exc).lower():
                            deleted_counts[table_name] = 0
                            logger.debug(
                                "workspace_delete_skipped_missing_table table=%s workspace_id=%s",
                                table_name,
                                normalized_workspace_id,
                            )
                            continue
                        raise
                conn.execute("COMMIT")
            except sqlite3.DatabaseError:
                conn.execute("ROLLBACK")
                raise

        # agent_sessions lives in a separate SQLite file (state/agent_sessions.sqlite3)
        # because AgentSessionStore opens its own connection. Wipe the workspace's
        # SDK resume cache here. Best-effort: a failure here doesn't roll back the
        # SQL state — the cache will self-trim as new sessions overwrite it.
        agent_sessions_path = (upload_dir / "state" / "agent_sessions.sqlite3").resolve()
        if agent_sessions_path.exists():
            try:
                _agent_conn = sqlite3.connect(agent_sessions_path)
                try:
                    cols = _agent_conn.execute(
                        "PRAGMA table_info(agent_sessions)"
                    ).fetchall()
                    if any(str(c[1]) == "workspace_id" for c in cols):
                        cursor = _agent_conn.execute(
                            "DELETE FROM agent_sessions WHERE workspace_id = ?",
                            (normalized_workspace_id,),
                        )
                        deleted_counts["agent_sessions"] = int(cursor.rowcount or 0)
                        _agent_conn.commit()
                finally:
                    _agent_conn.close()
            except sqlite3.DatabaseError as exc:
                logger.warning(
                    "workspace_delete_agent_sessions_cleanup_failed workspace_id=%s error=%s",
                    normalized_workspace_id,
                    exc,
                )

        # Filesystem cleanup — best-effort after SQL commit. Log everything for
        # an operator to chase down leaks; do not raise.
        if duckdb_file_path is not None and duckdb_file_path.exists():
            try:
                duckdb_file_path.unlink()
                logger.info(
                    "workspace_delete_duckdb_removed workspace_id=%s path=%s",
                    normalized_workspace_id,
                    duckdb_file_path,
                )
            except OSError as exc:
                logger.warning(
                    "workspace_delete_duckdb_remove_failed workspace_id=%s path=%s error=%s",
                    normalized_workspace_id,
                    duckdb_file_path,
                    exc,
                )

        if uploads_dir_to_remove is not None and uploads_dir_to_remove.exists():
            try:
                shutil.rmtree(uploads_dir_to_remove)
                logger.info(
                    "workspace_delete_uploads_removed workspace_id=%s path=%s",
                    normalized_workspace_id,
                    uploads_dir_to_remove,
                )
            except OSError as exc:
                logger.warning(
                    "workspace_delete_uploads_remove_failed workspace_id=%s path=%s error=%s",
                    normalized_workspace_id,
                    uploads_dir_to_remove,
                    exc,
                )

        try:
            get_audit_logger().log(
                event_type="workspace_lifecycle",
                action="workspace.delete",
                status="ok",
                user_id=normalized_actor,
                resource=normalized_workspace_id,
                detail={
                    "workspace_name": workspace_name,
                    "deleted_counts": deleted_counts,
                    "duckdb_file_existed": bool(
                        duckdb_file_path and not duckdb_file_path.exists()
                    ),
                    "uploads_dir_existed": bool(
                        uploads_dir_to_remove and not uploads_dir_to_remove.exists()
                    ),
                },
            )
        except Exception as audit_exc:  # noqa: BLE001 — audit is best-effort
            logger.warning(
                "workspace_delete_audit_failed workspace_id=%s error=%s",
                normalized_workspace_id,
                audit_exc,
            )

        return {
            "workspace_id": normalized_workspace_id,
            "status": "deleted",
            "deleted_at": deleted_at,
            "deleted_counts": deleted_counts,
        }

    def add_member(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
        member_user_id: str,
        role: str,
        email: str | None,
        display_name: str | None,
    ) -> dict[str, str]:
        normalized_workspace_id = workspace_id.strip()
        normalized_actor = actor_user_id.strip()
        normalized_member = member_user_id.strip()
        normalized_role = role.strip().lower()

        if normalized_role not in VALID_MEMBERSHIP_ROLES:
            raise WorkspaceError(
                code="WORKSPACE_ROLE_INVALID",
                message="Workspace membership role must be owner or editor",
                status_code=422,
            )

        with self._lock, self._connect() as conn:
            actor_member = self._get_member(
                conn,
                workspace_id=normalized_workspace_id,
                user_id=normalized_actor,
            )
            if actor_member is None or ROLE_RANK[actor_member.role] < ROLE_RANK["editor"]:
                raise WorkspaceError(
                    code="WORKSPACE_FORBIDDEN",
                    message="You do not have permission to manage workspace members",
                    status_code=403,
                )

            workspace_exists = conn.execute(
                "SELECT id FROM workspaces WHERE id = ?",
                (normalized_workspace_id,),
            ).fetchone()
            if workspace_exists is None:
                raise WorkspaceError(
                    code="WORKSPACE_NOT_FOUND",
                    message="Workspace not found",
                    status_code=404,
                )

            self._ensure_user(
                conn,
                user_id=normalized_member,
                email=email,
                display_name=display_name,
            )

            existing_member = self._get_member(
                conn,
                workspace_id=normalized_workspace_id,
                user_id=normalized_member,
            )
            if existing_member is None:
                conn.execute(
                    """
                    INSERT INTO workspace_members (
                        id, workspace_id, user_id, role, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        uuid.uuid4().hex,
                        normalized_workspace_id,
                        normalized_member,
                        normalized_role,
                        _utc_now(),
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE workspace_members
                    SET role = ?
                    WHERE workspace_id = ? AND user_id = ?
                    """,
                    (normalized_role, normalized_workspace_id, normalized_member),
                )

            conn.commit()

        return {
            "workspace_id": normalized_workspace_id,
            "user_id": normalized_member,
            "role": normalized_role,
        }

    def update_member_role(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
        target_user_id: str,
        new_role: str,
    ) -> dict[str, str]:
        normalized_workspace_id = workspace_id.strip()
        normalized_actor = actor_user_id.strip()
        normalized_target = target_user_id.strip()
        normalized_role = new_role.strip().lower()

        if normalized_role != "editor":
            raise WorkspaceError(
                code="WORKSPACE_ROLE_INVALID",
                message="Workspace member role can only be set to editor",
                status_code=422,
            )

        with self._lock, self._connect() as conn:
            actor_member = self._get_member(conn, workspace_id=normalized_workspace_id, user_id=normalized_actor)
            if actor_member is None or ROLE_RANK[actor_member.role] < ROLE_RANK["editor"]:
                raise WorkspaceError(
                    code="WORKSPACE_FORBIDDEN",
                    message="You do not have permission to manage workspace members",
                    status_code=403,
                )
            target_member = self._get_member(conn, workspace_id=normalized_workspace_id, user_id=normalized_target)
            if target_member is None:
                raise WorkspaceError(
                    code="MEMBER_NOT_FOUND",
                    message="Member not found",
                    status_code=404,
                )
            if target_member.role == "owner":
                raise WorkspaceError(
                    code="CANNOT_DEMOTE_OWNER",
                    message="Cannot change the owner's role",
                    status_code=422,
                )
            conn.execute(
                "UPDATE workspace_members SET role = ? WHERE workspace_id = ? AND user_id = ?",
                (normalized_role, normalized_workspace_id, normalized_target),
            )
            conn.commit()

        return {"workspace_id": normalized_workspace_id, "user_id": normalized_target, "role": normalized_role}

    def remove_member(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
        target_user_id: str,
    ) -> dict[str, str]:
        normalized_workspace_id = workspace_id.strip()
        normalized_actor = actor_user_id.strip()
        normalized_target = target_user_id.strip()

        with self._lock, self._connect() as conn:
            actor_member = self._get_member(conn, workspace_id=normalized_workspace_id, user_id=normalized_actor)
            if actor_member is None or ROLE_RANK[actor_member.role] < ROLE_RANK["editor"]:
                raise WorkspaceError(
                    code="WORKSPACE_FORBIDDEN",
                    message="You do not have permission to manage workspace members",
                    status_code=403,
                )
            target_member = self._get_member(conn, workspace_id=normalized_workspace_id, user_id=normalized_target)
            if target_member is None:
                raise WorkspaceError(
                    code="MEMBER_NOT_FOUND",
                    message="Member not found",
                    status_code=404,
                )
            if target_member.role == "owner":
                raise WorkspaceError(
                    code="CANNOT_REMOVE_OWNER",
                    message="Cannot remove the workspace owner",
                    status_code=422,
                )
            conn.execute(
                "DELETE FROM workspace_members WHERE workspace_id = ? AND user_id = ?",
                (normalized_workspace_id, normalized_target),
            )
            conn.commit()

        return {"workspace_id": normalized_workspace_id, "user_id": normalized_target, "status": "removed"}

    def list_members(self, *, workspace_id: str, actor_user_id: str) -> list[dict[str, str]]:
        normalized_workspace_id = workspace_id.strip()
        normalized_actor = actor_user_id.strip()

        with self._lock, self._connect() as conn:
            actor_member = self._get_member(
                conn,
                workspace_id=normalized_workspace_id,
                user_id=normalized_actor,
            )
            if actor_member is None:
                raise WorkspaceError(
                    code="WORKSPACE_FORBIDDEN",
                    message="You do not have permission to access this workspace",
                    status_code=403,
                )

            rows = conn.execute(
                """
                SELECT
                    wm.user_id,
                    wm.role,
                    COALESCE(u.display_name, wm.user_id) AS display_name,
                    COALESCE(u.email, '') AS email
                FROM workspace_members AS wm
                LEFT JOIN users AS u
                  ON u.id = wm.user_id
                WHERE wm.workspace_id = ?
                ORDER BY CASE wm.role
                    WHEN 'owner' THEN 4
                    WHEN 'admin' THEN 3
                    WHEN 'editor' THEN 2
                    ELSE 1
                END DESC,
                wm.user_id ASC
                """,
                (normalized_workspace_id,),
            ).fetchall()

        return [
            {
                "user_id": str(row["user_id"]),
                "role": str(row["role"]),
                "display_name": str(row["display_name"]),
                "email": str(row["email"]),
            }
            for row in rows
        ]

    def _initialize_schema(self) -> None:
        with self._connect() as conn:
            initialize_sqlite_schema(conn)
            self._migrate_legacy_viewer_members(conn)

    def _migrate_legacy_viewer_members(self, conn: sqlite3.Connection) -> None:
        """Neutralize legacy ``viewer`` workspace memberships.

        Public published-page viewing no longer depends on workspace membership,
        so legacy viewer rows are removed rather than upgraded to editor (which
        would silently grant write access). Idempotent.
        """

        try:
            removed = conn.execute(
                "DELETE FROM workspace_members WHERE role = 'viewer'"
            ).rowcount
            conn.commit()
        except sqlite3.OperationalError:
            return  # Table not present yet
        if removed:
            logger.info(
                "Removed %d legacy viewer workspace membership row(s) during migration",
                removed,
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _allocate_slug(self, conn: sqlite3.Connection, name: str) -> str:
        base = _slugify(name)
        if not base:
            base = "workspace"

        candidate = base
        index = 2
        while True:
            row = conn.execute(
                "SELECT 1 FROM workspaces WHERE slug = ?",
                (candidate,),
            ).fetchone()
            if row is None:
                return candidate
            candidate = f"{base}-{index}"
            index += 1

    def _ensure_user(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: str,
        email: str | None,
        display_name: str | None,
    ) -> None:
        normalized_user = user_id.strip()
        if not normalized_user:
            raise WorkspaceError(
                code="USER_ID_REQUIRED",
                message="user_id is required",
                status_code=422,
            )

        normalized_email = _normalize_email(normalized_user, email)
        insert_display_name = (display_name or "").strip() or normalized_user
        now = _utc_now()

        if display_name is not None:
            conn.execute(
                """
                INSERT INTO users (id, email, display_name, status, created_at, updated_at)
                VALUES (?, ?, ?, 'active', ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    email = excluded.email,
                    display_name = excluded.display_name,
                    updated_at = excluded.updated_at
                """,
                (normalized_user, normalized_email, insert_display_name, now, now),
            )
        else:
            conn.execute(
                """
                INSERT INTO users (id, email, display_name, status, created_at, updated_at)
                VALUES (?, ?, ?, 'active', ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    email = excluded.email,
                    updated_at = excluded.updated_at
                """,
                (normalized_user, normalized_email, insert_display_name, now, now),
            )

    def _get_member(
        self,
        conn: sqlite3.Connection,
        *,
        workspace_id: str,
        user_id: str,
    ) -> MemberRecord | None:
        row = conn.execute(
            """
            SELECT wm.user_id, wm.role
            FROM workspace_members AS wm
            JOIN workspaces AS w
              ON w.id = wm.workspace_id
            WHERE wm.workspace_id = ? AND wm.user_id = ? AND w.status = 'active'
            """,
            (workspace_id, user_id),
        ).fetchone()
        if row is None:
            return None

        return MemberRecord(
            user_id=str(row["user_id"]),
            role=str(row["role"]),
        )

    @staticmethod
    def _serialize_workspace(row: sqlite3.Row) -> dict[str, str]:
        return {
            "workspace_id": str(row["id"]),
            "name": str(row["name"]),
            "slug": str(row["slug"]),
            "status": str(row["status"]),
            "role": str(row["role"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }


router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.post("")
async def create_workspace(
    request: CreateWorkspaceRequest,
    identity: AuthIdentity = Depends(require_permission("workspaces:write")),
) -> dict[str, str]:
    service = get_workspace_service()
    try:
        return service.create_workspace(owner_user_id=identity.user_id, name=request.name)
    except WorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc


@router.get("")
async def list_workspaces(
    identity: AuthIdentity = Depends(require_permission("workspaces:read")),
) -> dict[str, object]:
    service = get_workspace_service()
    workspaces = service.list_workspaces_for_user(user_id=identity.user_id)
    return {
        "count": len(workspaces),
        "workspaces": workspaces,
    }


@router.get("/{workspace_id}")
async def get_workspace(
    workspace_id: str,
    identity: AuthIdentity = Depends(require_permission("workspaces:read")),
) -> dict[str, str]:
    service = get_workspace_service()
    try:
        return service.get_workspace_for_user(workspace_id=workspace_id, user_id=identity.user_id)
    except WorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc


@router.patch("/{workspace_id}")
async def rename_workspace(
    workspace_id: str,
    request: UpdateWorkspaceRequest,
    identity: AuthIdentity = Depends(require_permission("workspaces:write")),
) -> dict[str, str]:
    service = get_workspace_service()
    try:
        return service.rename_workspace(
            workspace_id=workspace_id,
            actor_user_id=identity.user_id,
            name=request.name,
        )
    except WorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc


class DeleteWorkspaceRequest(BaseModel):
    """Optional body for DELETE /workspaces/{id} carrying the typed
    confirmation. Backward-compatible: callers that send no body still get
    the deletion (with no name guardrail), so old clients keep working."""

    confirm_workspace_name: str | None = None


@router.delete("/{workspace_id}")
async def delete_workspace(
    workspace_id: str,
    request: DeleteWorkspaceRequest | None = Body(default=None),
    identity: AuthIdentity = Depends(require_permission("workspaces:manage")),
) -> dict[str, object]:
    service = get_workspace_service()
    try:
        return service.deactivate_workspace(
            workspace_id=workspace_id,
            actor_user_id=identity.user_id,
            confirm_workspace_name=request.confirm_workspace_name if request else None,
        )
    except WorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc


@router.get("/{workspace_id}/members")
async def list_workspace_members(
    workspace_id: str,
    identity: AuthIdentity = Depends(require_permission("workspaces:read")),
) -> dict[str, object]:
    service = get_workspace_service()
    try:
        members = service.list_members(workspace_id=workspace_id, actor_user_id=identity.user_id)
    except WorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc

    return {
        "count": len(members),
        "members": members,
    }


@router.post("/{workspace_id}/members")
async def add_workspace_member(
    workspace_id: str,
    request: AddWorkspaceMemberRequest,
    identity: AuthIdentity = Depends(get_current_identity),
) -> dict[str, str]:
    service = get_workspace_service()
    try:
        return service.add_member(
            workspace_id=workspace_id,
            actor_user_id=identity.user_id,
            member_user_id=request.user_id,
            role=request.role,
            email=request.email,
            display_name=request.display_name,
        )
    except WorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc


@router.patch("/{workspace_id}/members/{user_id}")
async def update_workspace_member_role(
    workspace_id: str,
    user_id: str,
    request: UpdateMemberRoleRequest,
    identity: AuthIdentity = Depends(get_current_identity),
) -> dict[str, str]:
    service = get_workspace_service()
    try:
        return service.update_member_role(
            workspace_id=workspace_id,
            actor_user_id=identity.user_id,
            target_user_id=user_id,
            new_role=request.role,
        )
    except WorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc


@router.delete("/{workspace_id}/members/{user_id}")
async def remove_workspace_member(
    workspace_id: str,
    user_id: str,
    identity: AuthIdentity = Depends(get_current_identity),
) -> dict[str, str]:
    service = get_workspace_service()
    try:
        return service.remove_member(
            workspace_id=workspace_id,
            actor_user_id=identity.user_id,
            target_user_id=user_id,
        )
    except WorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc


@router.post("/{workspace_id}/invites")
async def create_workspace_invite(
    workspace_id: str,
    request: CreateInviteRequest,
    identity: AuthIdentity = Depends(get_current_identity),
) -> dict[str, object]:
    service = get_workspace_service()
    try:
        service.assert_workspace_access(
            workspace_id=workspace_id,
            user_id=identity.user_id,
            minimum_role="editor",
        )
    except WorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc

    from .collaboration import create_invite
    conn = service._connect()
    try:
        result = create_invite(
            conn,
            workspace_id=workspace_id,
            created_by=identity.user_id,
            role=request.role,
            expires_in_days=request.expires_in_days,
            max_uses=request.max_uses,
        )
    finally:
        conn.close()
    return result


@router.get("/{workspace_id}/invites")
async def list_workspace_invites(
    workspace_id: str,
    identity: AuthIdentity = Depends(get_current_identity),
) -> dict[str, object]:
    service = get_workspace_service()
    try:
        service.assert_workspace_access(
            workspace_id=workspace_id,
            user_id=identity.user_id,
            minimum_role="editor",
        )
    except WorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc

    from .collaboration import list_invites
    conn = service._connect()
    try:
        invites = list_invites(conn, workspace_id=workspace_id)
    finally:
        conn.close()
    return {"count": len(invites), "invites": invites}


@router.delete("/{workspace_id}/invites/{invite_id}")
async def revoke_workspace_invite(
    workspace_id: str,
    invite_id: str,
    identity: AuthIdentity = Depends(get_current_identity),
) -> dict[str, str]:
    service = get_workspace_service()
    try:
        service.assert_workspace_access(
            workspace_id=workspace_id,
            user_id=identity.user_id,
            minimum_role="editor",
        )
    except WorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc

    from .collaboration import revoke_invite
    conn = service._connect()
    try:
        revoke_invite(conn, invite_id=invite_id, workspace_id=workspace_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "invite_not_found", "message": str(exc)}) from exc
    finally:
        conn.close()
    return {"status": "revoked", "invite_id": invite_id}


def _build_public_url_for_request(token: str, request: Request) -> str:
    from .published_pages import build_public_url

    request_base = ""
    try:
        request_base = str(request.base_url).rstrip("/")
    except Exception:  # pragma: no cover - defensive
        request_base = ""
    return build_public_url(token, request_base_url=request_base)


def _validate_publish_visibility_users(
    service: WorkspaceService,
    *,
    visibility_mode: str,
    user_ids: list[str],
) -> list[str]:
    if visibility_mode != VISIBILITY_ALLOWLIST:
        return []
    from .users import get_users_by_ids

    cleaned: list[str] = []
    seen: set[str] = set()
    for user_id in user_ids:
        normalized = user_id.strip()
        if not normalized or normalized in seen:
            continue
        cleaned.append(normalized)
        seen.add(normalized)
    if not cleaned:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "PUBLISH_VISIBILITY_USERS_REQUIRED",
                "message": "Select at least one registered user for restricted publishing",
            },
        )

    conn = service._connect()
    try:
        users = get_users_by_ids(conn, cleaned)
    finally:
        conn.close()
    found = {str(user.get("id") or "") for user in users}
    missing = [user_id for user_id in cleaned if user_id not in found]
    if missing:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "PUBLISH_VISIBILITY_USERS_INVALID",
                "message": "One or more selected users are not registered or active",
                "user_ids": missing,
            },
        )
    return cleaned


def _publication_status_with_visibility(
    publication: PublicPublication,
    *,
    page: PublishedPage | None,
    public_url: str,
) -> dict[str, object]:
    status = publication.to_status(public_url=public_url)
    if page is not None:
        status["visibility_mode"] = page.visibility_mode
        status["visibility_user_ids"] = page.visibility_user_ids
        status["visibility_user_count"] = len(page.visibility_user_ids)
    return status


@router.post("/{workspace_id}/publish")
async def publish_workspace(
    workspace_id: str,
    request: PublishWorkspaceRequest,
    http_request: Request,
    identity: AuthIdentity = Depends(get_current_identity),
) -> dict[str, object]:
    service = get_workspace_service()
    try:
        service.assert_workspace_access(
            workspace_id=workspace_id,
            user_id=identity.user_id,
            minimum_role="editor",
        )
    except WorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc

    empty_charts = [chart.chart_id for chart in request.charts if not chart.rows]
    if empty_charts:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "PUBLISH_CHART_DATA_REQUIRED",
                "message": "All charts must have data before publishing",
                "chart_ids": empty_charts,
            },
        )

    store = get_published_page_store()
    writer = get_snapshot_writer()
    version = store.next_version(workspace_id=workspace_id)
    published_at = _utc_now()
    visibility_user_ids = _validate_publish_visibility_users(
        service,
        visibility_mode=request.visibility_mode,
        user_ids=request.visibility_user_ids,
    )
    try:
        snapshot = writer.write(
            workspace_id=workspace_id,
            version=version,
            canvas_format_id=request.canvas_format_id(),
            page_count=request.page_count,
            background_preset_id=request.background_preset_id,
            viewport=request.viewport,
            nodes=request.nodes,
            edges=request.edges,
            web_design=request.web_design_payload(),
            layout=request.layout,
            sidebar=request.sidebar,
            charts=request.charts,
            actor_role=identity.role,
            published_at=published_at,
        )
    except PublishedPageError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc
    page = store.create(
        workspace_id=workspace_id,
        version=version,
        published_by=identity.user_id,
        manifest_path=snapshot.manifest_path,
        published_at=published_at,
        visibility_mode=request.visibility_mode,
        visibility_user_ids=visibility_user_ids,
    )
    canvas_kind = snapshot.manifest.get("canvas", {}).get("kind", CANVAS_KIND_WEB_PAGE)
    publication = store.upsert_publication(
        workspace_id=workspace_id,
        active_page_id=page.id,
        version=version,
        canvas_kind=canvas_kind,
        published_at=published_at,
    )
    public_url = _build_public_url_for_request(publication.token, http_request)
    status = _publication_status_with_visibility(publication, page=page, public_url=public_url)
    status["canvas_format_id"] = request.canvas_format_id()
    status["canvas_kind"] = canvas_kind
    return status


@router.get("/{workspace_id}/publish")
async def get_workspace_publication(
    workspace_id: str,
    http_request: Request,
    canvas_format_id: str | None = None,
    identity: AuthIdentity = Depends(get_current_identity),
) -> dict[str, object]:
    service = get_workspace_service()
    try:
        service.assert_workspace_access(
            workspace_id=workspace_id,
            user_id=identity.user_id,
            minimum_role="editor",
        )
    except WorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc

    try:
        canvas_kind = canvas_kind_for_format(canvas_format_id)
    except PublishedPageError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc

    publication = get_published_page_store().get_publication(
        workspace_id=workspace_id, canvas_kind=canvas_kind
    )
    if publication is None or not publication.is_active:
        return {"is_active": False, "canvas_kind": canvas_kind}
    public_url = _build_public_url_for_request(publication.token, http_request)
    status = publication.to_status(public_url=public_url)
    try:
        page = get_published_page_store().get(page_id=publication.active_page_id)
        status["canvas_format_id"] = manifest_canvas_format_id(page)
        status["canvas_kind"] = manifest_canvas_kind(page)
        status["visibility_mode"] = page.visibility_mode
        status["visibility_user_ids"] = page.visibility_user_ids
        status["visibility_user_count"] = len(page.visibility_user_ids)
    except Exception:
        pass
    return status


@router.delete("/{workspace_id}/publish")
async def revoke_workspace_publication(
    workspace_id: str,
    canvas_format_id: str | None = None,
    identity: AuthIdentity = Depends(get_current_identity),
) -> dict[str, object]:
    service = get_workspace_service()
    try:
        service.assert_workspace_access(
            workspace_id=workspace_id,
            user_id=identity.user_id,
            minimum_role="editor",
        )
    except WorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc

    try:
        canvas_kind = canvas_kind_for_format(canvas_format_id)
    except PublishedPageError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc

    get_published_page_store().revoke_publication(workspace_id=workspace_id, canvas_kind=canvas_kind)
    return {"is_active": False, "canvas_kind": canvas_kind}


@router.get("/{workspace_id}/published")
async def list_workspace_published_pages(
    workspace_id: str,
    identity: AuthIdentity = Depends(get_current_identity),
) -> dict[str, object]:
    service = get_workspace_service()
    try:
        service.assert_workspace_access(
            workspace_id=workspace_id,
            user_id=identity.user_id,
            minimum_role="editor",
        )
    except WorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc

    pages = get_published_page_store().list_by_workspace(workspace_id=workspace_id)
    history = [page.to_history_item() for page in pages]
    return {
        "count": len(history),
        "published_pages": history,
    }


@router.get("/{workspace_id}/published/{page_id}/snapshot")
async def get_workspace_published_page_snapshot(
    workspace_id: str,
    page_id: str,
    identity: AuthIdentity = Depends(get_current_identity),
) -> dict[str, object]:
    service = get_workspace_service()
    try:
        service.assert_workspace_access(
            workspace_id=workspace_id,
            user_id=identity.user_id,
            minimum_role="editor",
        )
    except WorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc

    store = get_published_page_store()
    try:
        page = store.get(page_id=page_id)
    except PublishedPageError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc

    if page.workspace_id != workspace_id:
        raise HTTPException(
            status_code=404,
            detail={"code": "PUBLISHED_PAGE_NOT_FOUND", "message": "Published page not found"},
        )

    try:
        manifest = read_manifest(page)
        charts = [
            read_chart_data(
                page,
                chart_id=str(chart.get("chart_id") or ""),
                include_assistant_rows=True,
            )
            for chart in manifest.get("charts", [])
            if isinstance(chart, dict) and str(chart.get("chart_id") or "").strip()
        ]
    except PublishedPageError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc

    return {
        "page_id": page.id,
        "version": page.version,
        "published_at": page.published_at,
        "published_by": page.published_by,
        "canvas_format_id": manifest_canvas_format_id(page),
        "canvas_kind": manifest_canvas_kind(page),
        "manifest": manifest,
        "charts": charts,
    }


@lru_cache(maxsize=2)
def _cached_workspace_service(storage_key: str) -> WorkspaceService:
    parsed = urlparse(storage_key)
    if parsed.scheme == "sqlite":
        db_path = _sqlite_db_path_from_url(storage_key)
    else:
        state_root = Path(storage_key)
        state_root.mkdir(parents=True, exist_ok=True)
        db_path = state_root / "workspace_state.sqlite3"

    return WorkspaceService(db_path=db_path)


def get_workspace_service() -> WorkspaceService:
    settings = get_settings()
    db_url = settings.database_url.strip()
    if db_url.startswith("sqlite://"):
        storage_key = db_url
    else:
        storage_key = str((settings.upload_dir / "state").resolve())
    return _cached_workspace_service(storage_key)


def clear_workspace_service_cache() -> None:
    _cached_workspace_service.cache_clear()


def _sqlite_db_path_from_url(database_url: str) -> Path:
    parsed = urlparse(database_url)
    raw_path = unquote(parsed.path)

    if raw_path.startswith("//"):
        return Path("/" + raw_path.lstrip("/")).resolve()

    if raw_path.startswith("/"):
        raw_path = raw_path[1:]

    return (SQLITE_RELATIVE_BASE / raw_path).resolve()


def _slugify(raw: str) -> str:
    compact = re.sub(r"[^a-zA-Z0-9]+", "-", raw.strip().lower())
    compact = compact.strip("-")
    if len(compact) > 56:
        return compact[:56].rstrip("-")
    return compact


def _normalize_email(user_id: str, email: str | None) -> str:
    candidate = (email or "").strip().lower()
    if candidate and "@" in candidate:
        return candidate

    user_candidate = user_id.strip().lower()
    if "@" in user_candidate:
        return user_candidate

    safe_local_part = re.sub(r"[^a-z0-9._-]+", "-", user_candidate)
    safe_local_part = safe_local_part.strip("-._") or "user"
    return f"{safe_local_part}@local.invalid"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
