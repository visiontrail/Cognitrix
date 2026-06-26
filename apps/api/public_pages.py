"""Public read routes for published workspace pages.

Public pages are resolved by high-entropy token. Pages published to all users
remain anonymously readable; login-gated modes require a bearer/cookie session
that belongs to an active registered user. Unknown, inactive, revoked, or
missing-snapshot tokens all return an undifferentiated HTTP 404.
"""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from .auth import AuthIdentity, get_optional_identity
from .published_pages import (
    PublishedPageError,
    VISIBILITY_ALLOWLIST,
    VISIBILITY_PUBLIC,
    VISIBILITY_REGISTERED,
    get_published_page_store,
    read_chart_data,
    read_manifest,
)

router = APIRouter(prefix="/public", tags=["public"])

# Basic per-source anti-scanning protection for public token endpoints.
_RATE_LIMIT = 120  # requests
_RATE_WINDOW_SECONDS = 60.0
_rate_lock = Lock()
_rate_buckets: dict[str, list[float]] = defaultdict(list)

# Avoid serving revoked content from caches after a publish is cancelled.
_NO_STORE_HEADERS = {"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"}

_NOT_FOUND = HTTPException(
    status_code=404,
    detail={"code": "not_found", "message": "Not found"},
)
_AUTH_REQUIRED = HTTPException(
    status_code=401,
    headers=_NO_STORE_HEADERS,
    detail={"code": "authentication_required", "message": "Login is required to view this page"},
)
_FORBIDDEN = HTTPException(
    status_code=403,
    headers=_NO_STORE_HEADERS,
    detail={"code": "published_page_forbidden", "message": "You do not have access to this page"},
)


def _client_key(request: Request) -> str:
    client = request.client
    return client.host if client and client.host else "unknown"


def _enforce_rate_limit(request: Request) -> None:
    key = _client_key(request)
    now = time.monotonic()
    cutoff = now - _RATE_WINDOW_SECONDS
    with _rate_lock:
        calls = [t for t in _rate_buckets[key] if t > cutoff]
        if len(calls) >= _RATE_LIMIT:
            _rate_buckets[key] = calls
            # Use the same 404 surface as missing tokens so the limiter cannot be
            # used to distinguish "existed but revoked" from "never existed".
            raise HTTPException(
                status_code=404,
                headers={"Retry-After": "60", **_NO_STORE_HEADERS},
                detail={"code": "not_found", "message": "Not found"},
            )
        calls.append(now)
        _rate_buckets[key] = calls


def _resolve_page(token: str) -> Any:
    """Resolve the active published page for a token, or raise 404.

    Collapses unknown/inactive/revoked/missing-snapshot into one 404.
    """

    store = get_published_page_store()
    publication = store.resolve_active_publication(token=token)
    if publication is None:
        raise _NOT_FOUND
    try:
        return store.get(page_id=publication.active_page_id)
    except PublishedPageError as exc:  # missing snapshot row
        raise _NOT_FOUND from exc


def _registered_user_id(identity: AuthIdentity | None) -> str:
    if identity is None:
        return ""

    from .users import get_user_by_id
    from .workspaces import get_workspace_service

    service = get_workspace_service()
    conn = service._connect()
    try:
        user = get_user_by_id(conn, identity.user_id)
    finally:
        conn.close()
    if user is None or user.status != "active":
        return ""
    return user.id


def _workspace_member_roles(*, workspace_id: str, user_id: str) -> set[str]:
    if not user_id:
        return set()
    from .workspaces import WorkspaceError, get_workspace_service

    try:
        role = get_workspace_service().assert_workspace_access(
            workspace_id=workspace_id,
            user_id=user_id,
            minimum_role="editor",
        )
    except WorkspaceError:
        return set()
    return {role}


def _authorize_page(page: Any, identity: AuthIdentity | None) -> None:
    visibility_mode = str(getattr(page, "visibility_mode", VISIBILITY_PUBLIC) or VISIBILITY_PUBLIC)
    if visibility_mode == VISIBILITY_PUBLIC:
        return

    user_id = _registered_user_id(identity)
    if not user_id:
        raise _AUTH_REQUIRED

    roles = _workspace_member_roles(workspace_id=str(page.workspace_id), user_id=user_id)
    if visibility_mode == VISIBILITY_REGISTERED:
        return
    if visibility_mode == VISIBILITY_ALLOWLIST and page.is_visible_to(
        user_id=user_id,
        workspace_member_roles=roles,
    ):
        return
    raise _FORBIDDEN


@router.get("/pages/{token}/manifest")
async def get_public_manifest(
    token: str,
    request: Request,
    response: Response,
    identity: AuthIdentity | None = Depends(get_optional_identity),
) -> dict[str, Any]:
    _enforce_rate_limit(request)
    page = _resolve_page(token)
    _authorize_page(page, identity)
    try:
        manifest = read_manifest(page)
    except PublishedPageError as exc:
        raise _NOT_FOUND from exc
    response.headers.update(_NO_STORE_HEADERS)
    return {
        "version": page.version,
        "published_at": page.published_at,
        "manifest": manifest,
    }


@router.get("/pages/{token}/charts/{chart_id}/data")
async def get_public_chart_data(
    token: str,
    chart_id: str,
    request: Request,
    response: Response,
    identity: AuthIdentity | None = Depends(get_optional_identity),
) -> dict[str, Any]:
    _enforce_rate_limit(request)
    page = _resolve_page(token)
    _authorize_page(page, identity)
    try:
        payload = read_chart_data(page, chart_id=chart_id)
    except PublishedPageError as exc:
        raise _NOT_FOUND from exc
    response.headers.update(_NO_STORE_HEADERS)
    # Strip the internal page id from the public response.
    return {
        "chart_id": payload.get("chart_id", chart_id),
        "spec": payload.get("spec", {}),
        "rows": payload.get("rows", []),
        "data_truncated": bool(payload.get("data_truncated")),
    }
