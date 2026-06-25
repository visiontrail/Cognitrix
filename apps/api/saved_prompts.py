from __future__ import annotations

import json
import re
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from .audit import get_audit_logger
from .auth import AuthIdentity, require_permission
from .config import get_settings

# ---------------------------------------------------------------------------
# Variable template syntax (Decision 3 in design.md)
# ---------------------------------------------------------------------------
# Single-brace placeholders ``{variable_name}`` where the name matches
# ``[A-Za-z][A-Za-z0-9_]{0,63}``. Literal braces are written ``\{`` / ``\}``.
# Double braces ``{{ ... }}`` are NOT treated as variables (they are reserved
# for i18n interpolation elsewhere in the codebase).
VARIABLE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")

# Controlled capability-hint allowlist (Decision 5). These map to existing
# composer affordances; they are hints only and grant no backend privilege.
ALLOWED_CAPABILITIES: tuple[str, ...] = ("file_upload", "multi_chart", "data_labels")

MAX_NAME_LENGTH = 120
MAX_BODY_LENGTH = 8000
DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 200


class SavedPromptError(Exception):
    def __init__(self, *, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code

    def to_detail(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


def extract_variables(body: str) -> list[str]:
    """Extract ``{variable}`` placeholders from a prompt body.

    Returns variable names in first-seen order. Repeated exact placeholders
    collapse to a single entry. Raises :class:`SavedPromptError` for malformed
    placeholders or case-ambiguous duplicates. ``\\{`` / ``\\}`` are literal
    braces and ``{{ ... }}`` is ignored (not a variable).
    """

    ordered: list[str] = []
    seen_lower: dict[str, str] = {}
    length = len(body)
    i = 0
    while i < length:
        char = body[i]

        # Escaped literal brace: ``\{`` or ``\}``.
        if char == "\\" and i + 1 < length and body[i + 1] in "{}":
            i += 2
            continue

        if char == "{":
            # Double brace -> not a variable; skip both braces.
            if i + 1 < length and body[i + 1] == "{":
                i += 2
                continue

            closing = body.find("}", i + 1)
            if closing == -1:
                raise SavedPromptError(
                    code="PROMPT_VARIABLE_INVALID",
                    message="Unterminated variable placeholder '{'",
                    status_code=422,
                )

            inner = body[i + 1:closing]
            if not VARIABLE_NAME_RE.match(inner):
                raise SavedPromptError(
                    code="PROMPT_VARIABLE_INVALID",
                    message=(
                        f"Invalid variable placeholder '{{{inner}}}'. Variable names must "
                        "start with a letter and contain only letters, digits, and underscores."
                    ),
                    status_code=422,
                )

            lower = inner.lower()
            existing = seen_lower.get(lower)
            if existing is None:
                seen_lower[lower] = inner
                ordered.append(inner)
            elif existing != inner:
                raise SavedPromptError(
                    code="PROMPT_VARIABLE_AMBIGUOUS",
                    message=(
                        f"Ambiguous variables '{{{existing}}}' and '{{{inner}}}' differ only "
                        "by letter case."
                    ),
                    status_code=422,
                )

            i = closing + 1
            continue

        # Lone or double closing brace outside a placeholder: treat as literal.
        i += 1

    return ordered


def validate_capabilities(values: list[str] | None) -> list[str]:
    """Validate and de-duplicate capability hints against the allowlist."""

    if not values:
        return []
    normalized: list[str] = []
    for raw in values:
        candidate = str(raw).strip()
        if candidate not in ALLOWED_CAPABILITIES:
            raise SavedPromptError(
                code="PROMPT_CAPABILITY_INVALID",
                message=f"Unsupported capability hint '{candidate}'",
                status_code=422,
            )
        if candidate not in normalized:
            normalized.append(candidate)
    return normalized


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------
class SavedPromptCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    body: str = Field(min_length=1, max_length=MAX_BODY_LENGTH)
    capabilities: list[str] = Field(default_factory=list)

    @field_validator("name", "body")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be empty")
        return normalized


class SavedPromptUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=MAX_NAME_LENGTH)
    body: str | None = Field(default=None, max_length=MAX_BODY_LENGTH)
    capabilities: list[str] | None = None

    @field_validator("name", "body")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be empty")
        return normalized


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class SavedPromptStore:
    db_path: Path
    _lock: Lock = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._init_schema()

    def create(
        self,
        *,
        owner_user_id: str,
        name: str,
        body: str,
        capabilities: list[str],
    ) -> dict[str, Any]:
        owner = _require_owner(owner_user_id)
        variables = extract_variables(body)
        normalized_caps = validate_capabilities(capabilities)
        now = _utc_now()
        prompt_id = uuid.uuid4().hex

        with self._lock, self._connect() as conn:
            self._assert_name_available(conn, owner_user_id=owner, name=name, exclude_id=None)
            conn.execute(
                """
                INSERT INTO saved_prompts (
                    id, owner_user_id, name, body, variables_json, capabilities_json,
                    usage_count, last_used_at, created_at, updated_at, archived_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, NULL, ?, ?, NULL)
                """,
                (
                    prompt_id,
                    owner,
                    name,
                    body,
                    _encode_json(variables),
                    _encode_json(normalized_caps),
                    now,
                    now,
                ),
            )
            conn.commit()
            row = self._fetch_row(conn, owner_user_id=owner, prompt_id=prompt_id)

        return _serialize(row)

    def list(
        self,
        *,
        owner_user_id: str,
        query: str | None = None,
        include_archived: bool = False,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> list[dict[str, Any]]:
        owner = _require_owner(owner_user_id)
        bounded_limit = max(1, min(int(limit), MAX_LIST_LIMIT))
        clauses = ["owner_user_id = ?"]
        params: list[Any] = [owner]
        if not include_archived:
            clauses.append("archived_at IS NULL")
        normalized_query = (query or "").strip()
        if normalized_query:
            clauses.append("(name LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\')")
            like = f"%{_escape_like(normalized_query)}%"
            params.extend([like, like])

        sql = (
            "SELECT * FROM saved_prompts WHERE "
            + " AND ".join(clauses)
            + " ORDER BY (last_used_at IS NULL) ASC, last_used_at DESC, updated_at DESC"
            + " LIMIT ?"
        )
        params.append(bounded_limit)

        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [_serialize(row) for row in rows]

    def get(self, *, owner_user_id: str, prompt_id: str) -> dict[str, Any]:
        owner = _require_owner(owner_user_id)
        with self._lock, self._connect() as conn:
            row = self._fetch_row(conn, owner_user_id=owner, prompt_id=prompt_id)
        return _serialize(row)

    def update(
        self,
        *,
        owner_user_id: str,
        prompt_id: str,
        name: str | None,
        body: str | None,
        capabilities: list[str] | None,
    ) -> dict[str, Any]:
        owner = _require_owner(owner_user_id)
        now = _utc_now()
        with self._lock, self._connect() as conn:
            current = self._fetch_row(conn, owner_user_id=owner, prompt_id=prompt_id)

            new_name = name if name is not None else str(current["name"])
            new_body = body if body is not None else str(current["body"])
            variables = extract_variables(new_body)
            if capabilities is not None:
                new_caps = validate_capabilities(capabilities)
            else:
                new_caps = _decode_json_list(current["capabilities_json"])

            if name is not None:
                self._assert_name_available(
                    conn, owner_user_id=owner, name=new_name, exclude_id=prompt_id
                )

            conn.execute(
                """
                UPDATE saved_prompts
                SET name = ?, body = ?, variables_json = ?, capabilities_json = ?, updated_at = ?
                WHERE id = ? AND owner_user_id = ?
                """,
                (
                    new_name,
                    new_body,
                    _encode_json(variables),
                    _encode_json(new_caps),
                    now,
                    prompt_id,
                    owner,
                ),
            )
            conn.commit()
            row = self._fetch_row(conn, owner_user_id=owner, prompt_id=prompt_id)

        return _serialize(row)

    def archive(self, *, owner_user_id: str, prompt_id: str) -> dict[str, Any]:
        owner = _require_owner(owner_user_id)
        now = _utc_now()
        with self._lock, self._connect() as conn:
            row = self._fetch_row(conn, owner_user_id=owner, prompt_id=prompt_id)
            if row["archived_at"] is None:
                conn.execute(
                    "UPDATE saved_prompts SET archived_at = ?, updated_at = ? WHERE id = ? AND owner_user_id = ?",
                    (now, now, prompt_id, owner),
                )
                conn.commit()
                row = self._fetch_row(conn, owner_user_id=owner, prompt_id=prompt_id)
        return _serialize(row)

    def mark_used(self, *, owner_user_id: str, prompt_id: str) -> dict[str, Any]:
        owner = _require_owner(owner_user_id)
        now = _utc_now()
        with self._lock, self._connect() as conn:
            row = self._fetch_row(conn, owner_user_id=owner, prompt_id=prompt_id)
            if row["archived_at"] is not None:
                raise SavedPromptError(
                    code="PROMPT_ARCHIVED",
                    message="Archived prompts cannot be used",
                    status_code=409,
                )
            conn.execute(
                """
                UPDATE saved_prompts
                SET usage_count = usage_count + 1, last_used_at = ?
                WHERE id = ? AND owner_user_id = ?
                """,
                (now, prompt_id, owner),
            )
            conn.commit()
            row = self._fetch_row(conn, owner_user_id=owner, prompt_id=prompt_id)
        return _serialize(row)

    # -- internals ----------------------------------------------------------
    def _fetch_row(
        self, conn: sqlite3.Connection, *, owner_user_id: str, prompt_id: str
    ) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM saved_prompts WHERE id = ? AND owner_user_id = ?",
            (prompt_id.strip(), owner_user_id),
        ).fetchone()
        if row is None:
            raise SavedPromptError(
                code="PROMPT_NOT_FOUND",
                message="Saved prompt not found",
                status_code=404,
            )
        return row

    def _assert_name_available(
        self,
        conn: sqlite3.Connection,
        *,
        owner_user_id: str,
        name: str,
        exclude_id: str | None,
    ) -> None:
        params: list[Any] = [owner_user_id, name.strip().lower()]
        sql = (
            "SELECT id FROM saved_prompts "
            "WHERE owner_user_id = ? AND lower(name) = ? AND archived_at IS NULL"
        )
        if exclude_id is not None:
            sql += " AND id != ?"
            params.append(exclude_id)
        existing = conn.execute(sql, tuple(params)).fetchone()
        if existing is not None:
            raise SavedPromptError(
                code="PROMPT_NAME_TAKEN",
                message="A saved prompt with this name already exists",
                status_code=409,
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS saved_prompts (
                    id TEXT PRIMARY KEY,
                    owner_user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    body TEXT NOT NULL,
                    variables_json TEXT NOT NULL,
                    capabilities_json TEXT NOT NULL,
                    usage_count INTEGER NOT NULL DEFAULT 0,
                    last_used_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    archived_at TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_saved_prompts_owner "
                "ON saved_prompts(owner_user_id, archived_at, updated_at)"
            )
            conn.commit()


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
router = APIRouter(prefix="/saved-prompts", tags=["saved-prompts"])


@router.get("")
async def list_saved_prompts(
    query: str | None = Query(default=None),
    include_archived: bool = Query(default=False),
    limit: int = Query(default=DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT),
    identity: AuthIdentity = Depends(require_permission("prompts:read")),
) -> dict[str, Any]:
    store = get_saved_prompt_store()
    try:
        prompts = store.list(
            owner_user_id=identity.user_id,
            query=query,
            include_archived=include_archived,
            limit=limit,
        )
    except SavedPromptError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc
    return {"count": len(prompts), "prompts": prompts}


@router.post("")
async def create_saved_prompt(
    request: SavedPromptCreateRequest,
    identity: AuthIdentity = Depends(require_permission("prompts:write")),
) -> dict[str, Any]:
    store = get_saved_prompt_store()
    try:
        prompt = store.create(
            owner_user_id=identity.user_id,
            name=request.name,
            body=request.body,
            capabilities=request.capabilities,
        )
    except SavedPromptError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc
    _audit("saved_prompt_create", identity=identity, prompt=prompt)
    return {"prompt": prompt}


@router.get("/{prompt_id}")
async def get_saved_prompt(
    prompt_id: str,
    identity: AuthIdentity = Depends(require_permission("prompts:read")),
) -> dict[str, Any]:
    store = get_saved_prompt_store()
    try:
        prompt = store.get(owner_user_id=identity.user_id, prompt_id=prompt_id)
    except SavedPromptError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc
    return {"prompt": prompt}


@router.patch("/{prompt_id}")
async def update_saved_prompt(
    prompt_id: str,
    request: SavedPromptUpdateRequest,
    identity: AuthIdentity = Depends(require_permission("prompts:write")),
) -> dict[str, Any]:
    store = get_saved_prompt_store()
    try:
        prompt = store.update(
            owner_user_id=identity.user_id,
            prompt_id=prompt_id,
            name=request.name,
            body=request.body,
            capabilities=request.capabilities,
        )
    except SavedPromptError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc
    _audit("saved_prompt_update", identity=identity, prompt=prompt)
    return {"prompt": prompt}


@router.delete("/{prompt_id}")
async def delete_saved_prompt(
    prompt_id: str,
    identity: AuthIdentity = Depends(require_permission("prompts:write")),
) -> dict[str, Any]:
    store = get_saved_prompt_store()
    try:
        prompt = store.archive(owner_user_id=identity.user_id, prompt_id=prompt_id)
    except SavedPromptError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc
    _audit("saved_prompt_delete", identity=identity, prompt=prompt)
    return {"status": "archived", "prompt": prompt}


@router.post("/{prompt_id}/use")
async def use_saved_prompt(
    prompt_id: str,
    identity: AuthIdentity = Depends(require_permission("prompts:read")),
) -> dict[str, Any]:
    store = get_saved_prompt_store()
    try:
        prompt = store.mark_used(owner_user_id=identity.user_id, prompt_id=prompt_id)
    except SavedPromptError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc
    _audit("saved_prompt_use", identity=identity, prompt=prompt)
    return {"prompt": prompt}


# ---------------------------------------------------------------------------
# Helpers / service wiring
# ---------------------------------------------------------------------------
def _audit(action: str, *, identity: AuthIdentity, prompt: dict[str, Any]) -> None:
    # Metadata only (Decision 7): never log prompt name, body, or variable values.
    get_audit_logger().log(
        event_type="saved_prompt",
        action=action,
        status="success",
        user_id=identity.user_id,
        project_id=identity.project_id,
        resource=f"/saved-prompts/{prompt.get('id')}",
        detail={
            "prompt_id": prompt.get("id"),
            "variable_count": len(prompt.get("variables") or []),
            "capabilities": list(prompt.get("capabilities") or []),
            "archived": prompt.get("archived_at") is not None,
        },
    )


@lru_cache(maxsize=2)
def _cached_saved_prompt_store(db_path: str) -> SavedPromptStore:
    return SavedPromptStore(db_path=Path(db_path).resolve())


def get_saved_prompt_store() -> SavedPromptStore:
    settings = get_settings()
    db_path = (settings.upload_dir / "state" / "saved_prompts.sqlite3").resolve()
    return _cached_saved_prompt_store(str(db_path))


def clear_saved_prompt_store_cache() -> None:
    _cached_saved_prompt_store.cache_clear()


def _require_owner(owner_user_id: str) -> str:
    normalized = (owner_user_id or "").strip()
    if not normalized:
        raise SavedPromptError(
            code="AUTH_REQUIRED",
            message="user_id is required",
            status_code=401,
        )
    return normalized


def _serialize(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "name": str(row["name"]),
        "body": str(row["body"]),
        "variables": _decode_json_list(row["variables_json"]),
        "capabilities": _decode_json_list(row["capabilities_json"]),
        "usage_count": int(row["usage_count"]),
        "last_used_at": row["last_used_at"],
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
        "archived_at": row["archived_at"],
    }


def _encode_json(payload: list[str]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _decode_json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if not isinstance(value, str):
        return []
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(decoded, list):
        return []
    return [str(item) for item in decoded]


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
