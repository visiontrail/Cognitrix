"""Public read routes for published workspace pages.

Public pages are resolved by high-entropy token. Pages published to all users
remain anonymously readable; login-gated modes require a bearer/cookie session
that belongs to an active registered user. Unknown, inactive, revoked, or
missing-snapshot tokens all return an undifferentiated HTTP 404.
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
from threading import Lock
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from starlette.responses import StreamingResponse

from .auth import AuthIdentity, get_optional_identity
from .chart_query_agent import ChartQueryAgentError, format_sse, get_chart_query_agent
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
_SSE_HEADERS = {**_NO_STORE_HEADERS, "X-Accel-Buffering": "no"}

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


class PublicAssistantChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = None
    chart_id: str | None = None

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message is required")
        return normalized

    @field_validator("conversation_id", "chart_id")
    @classmethod
    def normalize_optional_ids(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


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


def _assistant_available(page: Any) -> bool:
    try:
        manifest = read_manifest(page)
    except PublishedPageError as exc:
        raise _NOT_FOUND from exc
    assistant = manifest.get("assistant") if isinstance(manifest.get("assistant"), dict) else {}
    return bool(assistant.get("available"))


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


@router.post("/pages/{token}/chat")
async def post_public_assistant_chat(
    token: str,
    body: PublicAssistantChatRequest,
    request: Request,
    identity: AuthIdentity | None = Depends(get_optional_identity),
) -> StreamingResponse:
    _enforce_rate_limit(request)
    page = _resolve_page(token)
    _authorize_page(page, identity)
    if not _assistant_available(page):
        raise _NOT_FOUND

    request_id = uuid.uuid4().hex
    conversation_id = body.conversation_id or uuid.uuid4().hex
    agent = get_chart_query_agent()

    async def event_stream():
        try:
            async for event_type, payload in agent.run_turn_stream(
                page=page,
                message=body.message,
                request_id=request_id,
                conversation_id=conversation_id,
                chart_id=body.chart_id,
            ):
                yield format_sse(event_type, payload)
        except ChartQueryAgentError as exc:
            error_payload = {
                "conversation_id": conversation_id,
                "request_id": request_id,
                "status": "failed",
                "code": exc.code,
                "message": exc.message,
            }
            yield format_sse("error", error_payload)
            yield format_sse(
                "final",
                {
                    "conversation_id": conversation_id,
                    "request_id": request_id,
                    "status": "failed",
                    "text": exc.message,
                },
            )
        except Exception:
            message = "Public assistant failed. Please retry."
            yield format_sse(
                "error",
                {
                    "conversation_id": conversation_id,
                    "request_id": request_id,
                    "status": "failed",
                    "code": "PUBLIC_ASSISTANT_FAILED",
                    "message": message,
                },
            )
            yield format_sse(
                "final",
                {
                    "conversation_id": conversation_id,
                    "request_id": request_id,
                    "status": "failed",
                    "text": message,
                },
            )

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=_SSE_HEADERS)
