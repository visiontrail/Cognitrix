from __future__ import annotations

import hashlib
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer  # type: ignore[import-untyped]

from .config import get_settings


@dataclass(slots=True)
class InviteRecord:
    id: str
    workspace_id: str
    token_hash: str
    role: str
    created_by: str
    expires_at: str
    revoked_at: str | None
    used_count: int
    max_uses: int | None
    created_at: str


def _get_serializer() -> URLSafeTimedSerializer:
    secret = get_settings().auth_secret
    return URLSafeTimedSerializer(secret, salt="workspace-invite")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _utc_future(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec="seconds")


def create_invite(
    conn: sqlite3.Connection,
    *,
    workspace_id: str,
    created_by: str,
    role: str = "editor",
    expires_in_days: int | None = None,
    max_uses: int | None = None,
) -> dict[str, Any]:
    # Invite links only create editor collaborators; viewer is not a role.
    if role.strip().lower() != "editor":
        raise ValueError("invite role must be editor")
    role = "editor"
    settings = get_settings()
    effective_days = expires_in_days if expires_in_days is not None else settings.invite_link_ttl_days
    invite_id = uuid.uuid4().hex
    expires_at = _utc_future(effective_days)

    serializer = _get_serializer()
    data = {"invite_id": invite_id, "workspace_id": workspace_id, "role": role}
    raw_token = serializer.dumps(data)
    token_hash = _hash_token(raw_token)
    now = _utc_now()

    conn.execute(
        """
        INSERT INTO workspace_invites (
            id, workspace_id, token_hash, role, created_by, expires_at,
            revoked_at, used_count, max_uses, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, NULL, 0, ?, ?)
        """,
        (invite_id, workspace_id, token_hash, role, created_by, expires_at, max_uses, now),
    )
    conn.commit()

    app_url = settings.app_url.rstrip("/")
    invite_url = f"{app_url}/invites/{raw_token}"
    return {
        "id": invite_id,
        "workspace_id": workspace_id,
        "role": role,
        "expires_at": expires_at,
        "invite_url": invite_url,
        "created_at": now,
    }


def list_invites(conn: sqlite3.Connection, *, workspace_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, workspace_id, role, created_by, expires_at, revoked_at,
               used_count, max_uses, created_at
        FROM workspace_invites
        WHERE workspace_id = ? AND revoked_at IS NULL
        ORDER BY created_at DESC
        """,
        (workspace_id,),
    ).fetchall()
    return [
        {
            "id": str(row["id"]),
            "workspace_id": str(row["workspace_id"]),
            "role": str(row["role"]),
            "created_by": str(row["created_by"]),
            "expires_at": str(row["expires_at"]),
            "revoked_at": row["revoked_at"],
            "used_count": int(row["used_count"]),
            "max_uses": row["max_uses"],
            "created_at": str(row["created_at"]),
        }
        for row in rows
    ]


def revoke_invite(conn: sqlite3.Connection, *, invite_id: str, workspace_id: str) -> None:
    now = _utc_now()
    result = conn.execute(
        """
        UPDATE workspace_invites
        SET revoked_at = ?
        WHERE id = ? AND workspace_id = ? AND revoked_at IS NULL
        """,
        (now, invite_id, workspace_id),
    )
    conn.commit()
    if result.rowcount == 0:
        raise ValueError("invite_not_found_or_already_revoked")


def accept_invite(
    conn: sqlite3.Connection,
    *,
    raw_token: str,
    user_id: str,
) -> dict[str, Any]:
    serializer = _get_serializer()
    settings = get_settings()
    max_age = settings.invite_link_ttl_days * 86400

    try:
        data = serializer.loads(raw_token, max_age=max_age)
    except SignatureExpired as exc:
        raise ValueError("invite_expired") from exc
    except BadSignature as exc:
        raise ValueError("invite_invalid") from exc

    invite_id = str(data.get("invite_id", ""))
    workspace_id = str(data.get("workspace_id", ""))
    # Accepted invites always create editor collaborators. Any legacy viewer
    # invite token is coerced to editor; viewer is no longer a membership role.
    role = "editor"

    token_hash = _hash_token(raw_token)
    row = conn.execute(
        """
        SELECT id, workspace_id, role, revoked_at, used_count, max_uses, expires_at
        FROM workspace_invites
        WHERE token_hash = ?
        """,
        (token_hash,),
    ).fetchone()

    if row is None:
        raise ValueError("invite_not_found")

    now_str = _utc_now()
    if row["revoked_at"] is not None:
        raise ValueError("invite_revoked")

    if row["expires_at"] and row["expires_at"] < now_str:
        raise ValueError("invite_expired")

    if row["max_uses"] is not None and int(row["used_count"]) >= int(row["max_uses"]):
        raise ValueError("invite_exhausted")

    # Check if already a member
    existing = conn.execute(
        "SELECT role FROM workspace_members WHERE workspace_id = ? AND user_id = ?",
        (workspace_id, user_id),
    ).fetchone()

    if existing is not None:
        return {"workspace_id": workspace_id, "role": str(existing["role"]), "already_member": True}

    member_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO workspace_members (id, workspace_id, user_id, role, created_at, added_by)
        VALUES (?, ?, ?, ?, ?, NULL)
        """,
        (member_id, workspace_id, user_id, role, now_str),
    )
    conn.execute(
        "UPDATE workspace_invites SET used_count = used_count + 1 WHERE id = ?",
        (row["id"],),
    )
    conn.commit()

    return {"workspace_id": workspace_id, "role": role, "already_member": False}
