from __future__ import annotations

import json
import logging
import time
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from .agentic_ingestion.router import router as ingestion_router
from .admin_skills import router as admin_skills_router
from .admin_control import (
    get_control_store,
    record_usage_event,
    router as admin_control_router,
)
from .audit import get_audit_logger
from .auth import (
    AuthIdentity,
    AuthTokenError,
    EmailLoginRequest,
    LoginRequest,
    RegisterRequest,
    RoleUpdateRequest,
    can_access_owned_resource,
    ensure_scope,
    get_current_identity,
    get_role_directory,
    handle_email_login,
    handle_email_register,
    handle_logout,
    handle_me,
    issue_access_token,
    require_permission,
)
from .jobs import router as jobs_router
from .user_search import router as user_search_router
from .chat import ChatStreamRequest, get_chat_stream_service
from .config import DEFAULT_DEVELOPMENT_ADMIN_PASSWORD, get_settings
from .data_policy import forbidden_sensitive_columns, redact_rows, redact_structure
from .datasets import get_dataset_service
from .public_pages import router as public_pages_router
from .session_titles import get_session_title_service
from .security import (
    AccessContext,
    QueryAccessError,
    RLSInjector,
    RLSError,
    SQLGuardError,
    SQLReadOnlyValidator,
    secure_query_sql,
)
from .semantic import (
    IntentParser,
    MetricCompileError,
    QueryFilter,
    SemanticQueryAST,
    get_metric_compiler,
    get_semantic_registry,
)
from .saved_prompts import router as saved_prompts_router
from .table_catalog import router as table_catalog_router
from .tool_calling import ToolCallRequest, get_tool_calling_service
from .views import (
    RollbackInput,
    SaveViewInput,
    ViewStorageError,
    get_view_storage_service,
)
from .db_migrations import apply_migrations
from .workspaces import WorkspaceError, get_workspace_service, router as workspaces_router
from .workspace_state import router as workspace_state_router

app = FastAPI(title="Cognitrix API", version="0.1.0")
app.include_router(ingestion_router)
app.include_router(workspaces_router)
app.include_router(workspace_state_router)
app.include_router(table_catalog_router)
app.include_router(saved_prompts_router)
app.include_router(public_pages_router)
app.include_router(jobs_router)
app.include_router(user_search_router)
app.include_router(admin_control_router)


def register_admin_skills_router_if_enabled() -> None:
    """Mount the /admin/skills management API exactly once.

    Runtime loading remains controlled by ``AGENT_SKILLS_ENABLED``. Keeping the
    management API mounted lets operators inspect/install skills and then enable
    loading from the unified control plane.
    """

    existing = {getattr(route, "path", "") for route in app.router.routes}
    if any(path.startswith("/admin/skills") for path in existing):
        return
    app.include_router(admin_skills_router)


register_admin_skills_router_if_enabled()


@app.middleware("http")
async def collect_admin_usage(request, call_next):  # type: ignore[no-untyped-def]
    started = time.perf_counter()
    response = await call_next(request)
    identity = getattr(request.state, "identity", None)
    if identity is not None:
        duration_ms = (time.perf_counter() - started) * 1000
        record_usage_event(
            user_id=identity.user_id,
            project_id=identity.project_id,
            event_type="api_request",
            route=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        if request.url.path == "/chat/stream":
            record_usage_event(
                user_id=identity.user_id,
                project_id=identity.project_id,
                event_type="chat_turn",
                route=request.url.path,
                status_code=response.status_code,
                duration_ms=duration_ms,
            )
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SemanticFilterInput(BaseModel):
    field: str
    op: str = "eq"
    value: Any

    def to_query_filter(self) -> QueryFilter:
        return QueryFilter(field=self.field, op=self.op, value=self.value)


class SemanticQueryRequest(BaseModel):
    user_id: str
    project_id: str
    workspace_id: str | None = None
    dataset_table: str
    metric: str | None = None
    intent: str | None = None
    group_by: list[str] = Field(default_factory=list)
    filters: list[SemanticFilterInput] = Field(default_factory=list)
    role: str = "viewer"
    department: str | None = None
    clearance: int = 0
    limit: int | None = None


class ChatStreamAPIRequest(ChatStreamRequest):
    pass


class ChatTitleRequest(BaseModel):
    user_id: str
    project_id: str
    prompt: str
    locale: str = "en"


class ChatSessionResetRequest(BaseModel):
    user_id: str
    project_id: str
    conversation_id: str
    workspace_id: str | None = None


class SaveViewRequest(BaseModel):
    user_id: str
    project_id: str
    dataset_table: str
    role: str = "viewer"
    department: str | None = None
    clearance: int = 0
    title: str = "Saved View"
    ai_state: dict[str, Any]
    conversation_id: str | None = None
    view_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RollbackViewRequest(BaseModel):
    user_id: str
    project_id: str
    role: str = "viewer"
    department: str | None = None
    clearance: int = 0


class HealthzAccessLogFilter(logging.Filter):
    """Suppress successful health check access logs while preserving real traffic logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple) or len(args) < 5:
            return True

        method = str(args[1])
        path = str(args[2]).split("?", 1)[0]
        status_code = str(args[4])
        return not (method == "GET" and path == "/healthz" and status_code == "200")


def _ensure_healthz_access_log_filter(access_logger: logging.Logger) -> None:
    if any(isinstance(item, HealthzAccessLogFilter) for item in access_logger.filters):
        return
    access_logger.addFilter(HealthzAccessLogFilter())


def configure_application_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    app_logger = logging.getLogger("cognitrix")
    uvicorn_error_logger = logging.getLogger("uvicorn.error")
    uvicorn_access_logger = logging.getLogger("uvicorn.access")

    app_logger.setLevel(level)
    _ensure_healthz_access_log_filter(uvicorn_access_logger)
    if uvicorn_error_logger.handlers:
        app_logger.handlers = uvicorn_error_logger.handlers
        app_logger.propagate = False
    elif not app_logger.handlers:
        logging.basicConfig(level=level)
        app_logger.propagate = True


_OFFICIAL_ANTHROPIC_HOSTS = {"api.anthropic.com"}


def _log_agent_sdk_provider_config(logger: logging.Logger, settings: Any) -> None:
    """Log the endpoint/model/credential the agent SDK will actually use.

    Every SDK-backed runtime resolves its provider from env, and shells that run
    Claude Code export ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN — which
    docker-compose interpolation prefers over the project `.env`. The resulting
    "third-party key against api.anthropic.com" produces an HTTP 401 that the
    SDK reports as ordinary assistant text, so it must be visible here.
    """
    from urllib.parse import urlparse

    from .agent_runtime import build_sdk_provider_env

    env, model = build_sdk_provider_env(settings)
    base_url = env.get("ANTHROPIC_BASE_URL", "")
    token = env.get("ANTHROPIC_AUTH_TOKEN", "")
    if settings.anthropic_auth_token.strip():
        auth_source = "ANTHROPIC_AUTH_TOKEN"
    elif settings.ai_api_key.strip():
        auth_source = "AI_API_KEY"
    else:
        auth_source = "none"
    key_kind = "anthropic" if token.startswith("sk-ant-") else ("third_party" if token else "missing")
    logger.info(
        "agent_sdk_provider_config base_url=%s model=%s auth_source=%s key_kind=%s key_len=%d",
        base_url or "(SDK default)",
        model or "(SDK default)",
        auth_source,
        key_kind,
        len(token),
    )
    if not token:
        logger.warning(
            "agent_sdk_provider_no_credential — set ANTHROPIC_AUTH_TOKEN (or AI_API_KEY); "
            "every agent turn will fail with an authentication error until then"
        )
        return
    host = (urlparse(base_url).hostname or "").lower() if base_url else "api.anthropic.com"
    if host in _OFFICIAL_ANTHROPIC_HOSTS and key_kind == "third_party":
        logger.warning(
            "agent_sdk_provider_mismatch base_url=%s model=%s key_kind=third_party — a non-Anthropic "
            "key is pointed at the official Anthropic endpoint, so every agent turn will fail with "
            "HTTP 401. If this container was started from a shell that exports ANTHROPIC_BASE_URL, "
            "that value overrode the project .env; unset it or set ANTHROPIC_BASE_URL explicitly "
            "(e.g. https://api.deepseek.com/anthropic).",
            base_url or "(SDK default)",
            model or "(SDK default)",
        )


@app.on_event("startup")
async def on_startup() -> None:
    settings = get_settings()
    configure_application_logging(settings.log_level)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    apply_migrations()
    control_store = get_control_store()
    control_store.cleanup_usage(retention_days=settings.admin_usage_retention_days)
    logger = logging.getLogger("cognitrix")
    logger.info(
        "application_logging_configured level=%s upload_dir=%s",
        settings.log_level,
        settings.upload_dir,
    )
    logger.info(
        "chat_runtime_config claude_agent_sdk_enabled=%s "
        "agent_max_tool_steps=%s agent_max_sql_rows=%s agent_timeout_seconds=%s "
        "web_search_enabled=%s web_search_provider=%s",
        settings.claude_agent_sdk_enabled,
        settings.agent_max_tool_steps,
        settings.agent_max_sql_rows,
        settings.agent_timeout_seconds,
        settings.web_search_enabled,
        settings.web_search_provider,
    )
    _log_agent_sdk_provider_config(logger, settings)
    if settings.web_search_enabled and not settings.web_search_api_key.strip():
        logger.warning(
            "web_search_enabled_without_api_key provider=%s — every web_search/"
            "web_fetch call will fail until WEB_SEARCH_API_KEY is set",
            settings.web_search_provider,
        )
    logger.info(
        "agentic_ingestion_forced_enabled=true configured_flag=%s",
        settings.agentic_ingestion_enabled,
    )
    if settings.legacy_service_login_enabled:
        if settings.app_env.strip().lower() == "production":
            logger.warning(
                "legacy_service_login_ignored_in_production — POST /auth/login stays "
                "disabled; it mints a token for any requested role without credentials"
            )
        else:
            logger.warning(
                "legacy_service_login_enabled app_env=%s — POST /auth/login issues a "
                "token for any requested role without credentials; never expose this instance",
                settings.app_env,
            )
    if settings.auth_bootstrap_admin_password == DEFAULT_DEVELOPMENT_ADMIN_PASSWORD:
        logger.warning(
            "development_admin_credentials_active email=%s; override or clear bootstrap credentials outside local development",
            settings.auth_bootstrap_admin_email,
        )

    if settings.agent_skills_enabled:
        from .agent_skills.bootstrap import bootstrap_vendored_xlsx_skill

        try:
            bootstrap_vendored_xlsx_skill()
        except Exception:
            # Bootstrap is best-effort; never block API startup on a skill error.
            logger.exception("xlsx_bootstrap_unexpected_error")


@app.post("/auth/register")
async def auth_register(request: RegisterRequest, response: Response) -> dict[str, Any]:
    return handle_email_register(request, response)


@app.post("/auth/email-login")
async def auth_email_login(request: EmailLoginRequest, response: Response) -> dict[str, Any]:
    return handle_email_login(request, response)


@app.post("/auth/logout")
async def auth_logout(response: Response) -> dict[str, str]:
    return handle_logout(response)


@app.get("/auth/me")
async def auth_me(identity: AuthIdentity = Depends(get_current_identity)) -> dict[str, Any]:
    return handle_me(identity)


def _legacy_service_login_available(settings: Any) -> bool:
    """Whether the credential-free service-token endpoint may answer.

    The endpoint mints a token for whatever `role` the caller names, without
    any credential, so an exposed instance hands out `superadmin` to anyone who
    can reach it. It exists only to keep local development and the smoke flow
    working, so it is off by default and can never be turned on in production —
    the flag is honoured outside production only.
    """

    if settings.app_env.strip().lower() == "production":
        return False
    return bool(settings.legacy_service_login_enabled)


@app.post("/auth/login")
async def auth_login(request: LoginRequest) -> dict[str, Any]:
    settings = get_settings()
    if not _legacy_service_login_available(settings):
        get_audit_logger().log(
            event_type="authentication",
            action="legacy_service_login",
            status="denied",
            severity="ALERT",
            user_id=request.user_id.strip() or "unknown",
            project_id=request.project_id.strip() or "unknown",
            detail={"reason": "endpoint_disabled", "requested_role": request.role},
        )
        # Undifferentiated 404: a disabled endpoint should not advertise that it
        # exists, nor that a different configuration would make it answer.
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Not Found"},
        )

    if not request.user_id.strip() or not request.project_id.strip():
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_LOGIN_PAYLOAD",
                "message": "user_id and project_id are required",
            },
        )

    audit = get_audit_logger()
    try:
        payload = issue_access_token(request)
    except AuthTokenError as exc:
        audit.log(
            event_type="authentication",
            action="login",
            status="denied",
            severity="ALERT",
            user_id=request.user_id,
            project_id=request.project_id,
            detail={"reason": exc.code},
        )
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": exc.message}) from exc

    audit.log(
        event_type="authentication",
        action="login",
        status="success",
        user_id=request.user_id,
        project_id=request.project_id,
        detail={"role": payload["user"]["role"]},
    )
    return payload


@app.post("/auth/roles/{user_id}")
async def update_user_role(
    user_id: str,
    request: RoleUpdateRequest,
    identity: AuthIdentity = Depends(require_permission("auth:manage")),
) -> dict[str, Any]:
    audit = get_audit_logger()
    try:
        override = get_role_directory().set_override(
            user_id=user_id,
            role=request.role,
            department=request.department,
            clearance=request.clearance,
            updated_by=identity.user_id,
        )
    except (AuthTokenError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "ROLE_UPDATE_INVALID", "message": str(exc)},
        ) from exc

    audit.log(
        event_type="authorization",
        action="role_update",
        status="success",
        user_id=identity.user_id,
        project_id=identity.project_id,
        detail={"target_user_id": user_id, "role": override["role"]},
    )
    return {"user_id": user_id, "override": override}


@app.get("/audit/events")
async def list_audit_events(
    user_id: str | None = None,
    action: str | None = None,
    status: str | None = None,
    severity: str | None = None,
    limit: int = 100,
    identity: AuthIdentity = Depends(require_permission("audit:read")),
) -> dict[str, Any]:
    _ = identity
    events = get_audit_logger().query(
        user_id=user_id,
        action=action,
        status=status,
        severity=severity,
        limit=limit,
    )
    return {"count": len(events), "events": events}


@app.get("/semantic/metrics")
async def list_semantic_metrics(
    identity: AuthIdentity = Depends(require_permission("semantic:metrics")),
) -> dict[str, object]:
    _ = identity
    registry = get_semantic_registry()
    metrics = registry.list_metrics()
    return {"count": len(metrics), "metrics": metrics}


@app.post("/semantic/query")
async def semantic_query(
    request: SemanticQueryRequest,
    identity: AuthIdentity = Depends(require_permission("semantic:query")),
) -> dict[str, object]:
    ensure_scope(identity, user_id=request.user_id, project_id=request.project_id)
    workspace_id = (request.workspace_id or "").strip() or None
    if workspace_id is not None:
        try:
            get_workspace_service().assert_workspace_access(
                workspace_id=workspace_id,
                user_id=identity.user_id,
                minimum_role="editor",
            )
        except WorkspaceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc

    settings = get_settings()
    registry = get_semantic_registry()
    compiler = get_metric_compiler()
    parser = IntentParser(registry)
    dataset_service = get_dataset_service(settings.upload_dir)
    audit = get_audit_logger()

    try:
        query_ast = _build_query_ast(request=request, parser=parser)
        compiled = compiler.compile(query_ast, table_override=request.dataset_table)
    except MetricCompileError as exc:
        raise HTTPException(status_code=422, detail=exc.to_detail()) from exc

    guard = SQLReadOnlyValidator(
        allowed_tables={request.dataset_table},
        sensitive_tables={"raw_payroll", "security_audit_log"},
        sensitive_columns=forbidden_sensitive_columns(identity.role),
    )
    rls_injector = RLSInjector()
    access_context = AccessContext(
        user_id=identity.user_id,
        role=identity.role,
        department=identity.department,
        clearance=identity.clearance,
    )

    try:
        secure_sql = secure_query_sql(
            compiled.sql,
            context=access_context,
            guard=guard,
            rls_injector=rls_injector,
        )
    except QueryAccessError as exc:
        audit.log(
            event_type="query",
            action="semantic_query",
            status="denied",
            severity="ALERT",
            user_id=identity.user_id,
            project_id=identity.project_id,
            detail={"code": exc.code},
        )
        raise HTTPException(status_code=403, detail=exc.to_detail()) from exc
    except (SQLGuardError, RLSError) as exc:
        raise HTTPException(status_code=400, detail=exc.to_detail()) from exc

    try:
        with dataset_service.session_manager.connection(
            identity.user_id,
            identity.project_id,
            workspace_id=workspace_id,
        ) as conn:
            cursor = conn.execute(secure_sql)
            columns = [column[0] for column in (cursor.description or [])]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "QUERY_EXECUTION_FAILED",
                "message": "Failed to execute semantic query",
            },
        ) from exc

    safe_rows = redact_rows(rows, role=identity.role)
    audit.log(
        event_type="query",
        action="semantic_query",
        status="success",
        user_id=identity.user_id,
        project_id=identity.project_id,
        detail={"metric": compiled.metric, "row_count": len(safe_rows)},
    )

    return {
        "metric": compiled.metric,
        "query_ast": {
            "metric": query_ast.metric,
            "group_by": query_ast.group_by,
            "filters": [
                {"field": item.field, "op": item.op, "value": item.value}
                for item in query_ast.filters
            ],
            "limit": query_ast.limit,
        },
        "sql": secure_sql,
        "explain": compiled.explain,
        "row_count": len(safe_rows),
        "rows": safe_rows,
    }


@app.post("/chat/tool-call")
async def chat_tool_call(
    request: ToolCallRequest,
    identity: AuthIdentity = Depends(require_permission("chat:tool")),
) -> dict[str, object]:
    ensure_scope(identity, user_id=request.user_id, project_id=request.project_id)
    workspace_id = (request.workspace_id or "").strip() or None
    if workspace_id is not None:
        try:
            get_workspace_service().assert_workspace_access(
                workspace_id=workspace_id,
                user_id=identity.user_id,
                minimum_role="editor",
            )
        except WorkspaceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc

    enforced_request = request.model_copy(
        update={
            "user_id": identity.user_id,
            "project_id": identity.project_id,
            "workspace_id": workspace_id,
            "role": identity.role,
            "department": identity.department,
            "clearance": identity.clearance,
        }
    )

    service = get_tool_calling_service()
    response = service.invoke(enforced_request)

    status = "success" if response.status == "success" else "failed"
    severity = "INFO"
    if response.error and response.error.get("code") in {"ACCESS_DENIED", "RBAC_FORBIDDEN"}:
        status = "denied"
        severity = "ALERT"

    get_audit_logger().log(
        event_type="query",
        action="tool_call",
        status=status,
        severity=severity,
        user_id=identity.user_id,
        project_id=identity.project_id,
        detail={"tool": response.tool_name, "attempts": response.attempts},
    )
    return response.model_dump()


@app.post("/chat/stream")
async def chat_stream(
    request: ChatStreamAPIRequest,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    identity: AuthIdentity = Depends(require_permission("chat:stream")),
) -> StreamingResponse:
    ensure_scope(identity, user_id=request.user_id, project_id=request.project_id)
    workspace_id = (request.workspace_id or "").strip() or None
    if workspace_id is not None:
        try:
            get_workspace_service().assert_workspace_access(
                workspace_id=workspace_id,
                user_id=identity.user_id,
                minimum_role="editor",
            )
        except WorkspaceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc

    enforced_request = request.model_copy(
        update={
            "user_id": identity.user_id,
            "project_id": identity.project_id,
            "workspace_id": workspace_id,
            "role": identity.role,
            "department": identity.department,
            "clearance": identity.clearance,
        }
    )

    get_audit_logger().log(
        event_type="query",
        action="chat_stream",
        status="success",
        user_id=identity.user_id,
        project_id=identity.project_id,
        detail={
            "conversation_id": enforced_request.conversation_id,
            "workspace_id": enforced_request.workspace_id,
        },
    )

    service = get_chat_stream_service()
    stream = service.stream_async(enforced_request, last_event_id_header=last_event_id)
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _require_agent_canvas_mode_enabled() -> None:
    if not get_settings().agent_canvas_mode_enabled:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "AGENT_CANVAS_MODE_DISABLED",
                "message": "Agent canvas mode is disabled",
            },
        )


def _load_authorized_agent_run(run_id: str, identity: AuthIdentity) -> dict[str, Any]:
    from .agent_canvas import get_agent_canvas_run_store

    run = get_agent_canvas_run_store().get_run(run_id)
    if run is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "AGENT_CANVAS_RUN_NOT_FOUND", "message": "Unknown run"},
        )
    try:
        get_workspace_service().assert_workspace_access(
            workspace_id=run["workspace_id"],
            user_id=identity.user_id,
            minimum_role="editor",
        )
    except WorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc
    return run


@app.get("/chat/agent-runs/active")
async def get_active_agent_run(
    workspace_id: str,
    identity: AuthIdentity = Depends(require_permission("chat:stream")),
) -> dict[str, Any]:
    _require_agent_canvas_mode_enabled()
    normalized_workspace_id = workspace_id.strip()
    try:
        get_workspace_service().assert_workspace_access(
            workspace_id=normalized_workspace_id,
            user_id=identity.user_id,
            minimum_role="editor",
        )
    except WorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc

    from .agent_canvas_mode import get_agent_canvas_mode_service

    service = get_agent_canvas_mode_service()
    run = service.get_workspace_run(workspace_id=normalized_workspace_id, user_id=identity.user_id)
    return {"run": service.describe_run(run) if run is not None else None}


@app.get("/chat/agent-runs/{run_id}/ops")
async def list_agent_run_ops(
    run_id: str,
    after_seq: int = 0,
    identity: AuthIdentity = Depends(require_permission("chat:stream")),
) -> dict[str, Any]:
    _require_agent_canvas_mode_enabled()
    run = _load_authorized_agent_run(run_id, identity)

    from .agent_canvas import get_agent_canvas_run_store

    ops = get_agent_canvas_run_store().list_ops_after(run_id=run_id, after_seq=after_seq)
    return {
        "run_id": run_id,
        "status": run["status"],
        "page_id": run["page_id"],
        "summary": run.get("summary"),
        # Each op carries its own page: a multi-page run must replay onto the
        # same pages it was built on, not collapse back onto the run root.
        "ops": [
            {**op, "page_id": str((op.get("payload") or {}).get("page_id") or run["page_id"])}
            for op in ops
        ],
    }


@app.post("/chat/agent-runs/{run_id}/stop")
async def stop_agent_run(
    run_id: str,
    identity: AuthIdentity = Depends(require_permission("chat:stream")),
) -> dict[str, Any]:
    _require_agent_canvas_mode_enabled()
    _load_authorized_agent_run(run_id, identity)

    from .agent_canvas_mode import get_agent_canvas_mode_service

    run = get_agent_canvas_mode_service().stop_run(run_id)
    if run is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "AGENT_CANVAS_RUN_NOT_FOUND", "message": "Unknown run"},
        )
    return {"run_id": run_id, "status": run["status"]}


class AgentRunRetryRequest(BaseModel):
    seq: int


@app.post("/chat/agent-runs/{run_id}/retry")
async def retry_agent_run_item(
    run_id: str,
    request: AgentRunRetryRequest,
    identity: AuthIdentity = Depends(require_permission("chat:stream")),
) -> dict[str, Any]:
    _require_agent_canvas_mode_enabled()
    _load_authorized_agent_run(run_id, identity)

    from .agent_canvas_mode import AgentCanvasRetryError, get_agent_canvas_mode_service

    try:
        result = get_agent_canvas_mode_service().retry_item(
            run_id=run_id,
            seq=request.seq,
            user_id=identity.user_id,
            project_id=identity.project_id,
            role=identity.role,
            department=identity.department,
            clearance=identity.clearance,
        )
    except AgentCanvasRetryError as exc:
        raise HTTPException(status_code=400, detail=exc.to_detail()) from exc
    return result


@app.get("/chat/agent-runs/{run_id}/tail")
async def tail_agent_run(
    run_id: str,
    after_seq: int = 0,
    identity: AuthIdentity = Depends(require_permission("chat:stream")),
) -> StreamingResponse:
    _require_agent_canvas_mode_enabled()
    _load_authorized_agent_run(run_id, identity)

    from .agent_canvas_mode import get_agent_canvas_mode_service

    service = get_agent_canvas_mode_service()

    async def stream() -> Any:
        event_id = 0
        async for event_type, payload in service.tail_run(run_id=run_id, after_seq=after_seq):
            if event_type == "keepalive":
                yield ": keepalive\n\n"
                continue
            event_id += 1
            data = json.dumps(payload, ensure_ascii=False, default=str)
            yield f"id: {event_id}\nevent: {event_type}\ndata: {data}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/chat/session/reset")
async def reset_chat_session(
    request: ChatSessionResetRequest,
    identity: AuthIdentity = Depends(require_permission("chat:stream")),
) -> dict[str, Any]:
    ensure_scope(identity, user_id=request.user_id, project_id=request.project_id)
    workspace_id = (request.workspace_id or "").strip() or None
    if workspace_id is not None:
        try:
            get_workspace_service().assert_workspace_access(
                workspace_id=workspace_id,
                user_id=identity.user_id,
                minimum_role="editor",
            )
        except WorkspaceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc

    conversation_id = request.conversation_id.strip()
    if not conversation_id:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_conversation_id",
                "message": "conversation_id is required",
            },
        )

    get_chat_stream_service().reset_conversation(conversation_id)
    get_audit_logger().log(
        event_type="query",
        action="chat_session_reset",
        status="success",
        user_id=identity.user_id,
        project_id=identity.project_id,
        detail={
            "conversation_id": conversation_id,
            "workspace_id": workspace_id,
        },
    )
    return {"status": "reset", "conversation_id": conversation_id}


@app.post("/chat/title")
async def generate_chat_title(
    request: ChatTitleRequest,
    identity: AuthIdentity = Depends(require_permission("chat:stream")),
) -> dict[str, str]:
    ensure_scope(identity, user_id=request.user_id, project_id=request.project_id)
    title, source = get_session_title_service().generate_title(request.prompt, locale=request.locale)

    get_audit_logger().log(
        event_type="query",
        action="chat_title",
        status="success",
        user_id=identity.user_id,
        project_id=identity.project_id,
        detail={"source": source},
    )
    return {"title": title, "source": source}


@app.post("/views")
async def save_view(
    request: SaveViewRequest,
    identity: AuthIdentity = Depends(require_permission("views:write")),
) -> dict[str, Any]:
    ensure_scope(identity, user_id=request.user_id, project_id=request.project_id)

    service = get_view_storage_service()
    safe_ai_state = redact_structure(request.ai_state, role=identity.role)
    try:
        result = service.save_view(
            SaveViewInput(
                user_id=identity.user_id,
                project_id=identity.project_id,
                dataset_table=request.dataset_table,
                role=identity.role,
                department=identity.department,
                clearance=identity.clearance,
                title=request.title,
                ai_state=safe_ai_state,
                conversation_id=request.conversation_id,
                view_id=request.view_id,
                metadata=request.metadata,
            )
        )
    except ViewStorageError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc

    get_audit_logger().log(
        event_type="sharing",
        action="save_view",
        status="success",
        user_id=identity.user_id,
        project_id=identity.project_id,
        detail={"view_id": result["view_id"], "version": result["version"]},
    )
    result["share_url"] = result["share_path"]
    return result


@app.get("/views/{view_id}")
async def get_view(
    view_id: str,
    identity: AuthIdentity = Depends(require_permission("views:read")),
) -> dict[str, Any]:
    service = get_view_storage_service()
    try:
        result = service.get_view(view_id)
    except ViewStorageError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc

    if not can_access_owned_resource(
        identity,
        owner_user_id=result["owner_user_id"],
        owner_project_id=result["owner_project_id"],
    ):
        get_audit_logger().log(
            event_type="authorization",
            action="view_read",
            status="denied",
            severity="ALERT",
            user_id=identity.user_id,
            project_id=identity.project_id,
            detail={"view_id": view_id},
        )
        raise HTTPException(
            status_code=403,
            detail={
                "code": "RBAC_FORBIDDEN",
                "message": "You do not have permission to access this resource",
            },
        )

    result["ai_state"] = redact_structure(result["ai_state"], role=identity.role)
    result["share_url"] = result["share_path"]
    return result


@app.get("/share/{view_id}")
async def get_shared_view(
    view_id: str,
    identity: AuthIdentity = Depends(require_permission("views:share")),
) -> dict[str, Any]:
    service = get_view_storage_service()
    try:
        result = service.get_view(view_id)
    except ViewStorageError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc

    result["ai_state"] = redact_structure(result["ai_state"], role=identity.role)
    result["share_url"] = result["share_path"]
    get_audit_logger().log(
        event_type="sharing",
        action="share_view",
        status="success",
        user_id=identity.user_id,
        project_id=identity.project_id,
        detail={"view_id": view_id, "current_version": result["current_version"]},
    )
    return result


@app.post("/views/{view_id}/rollback/{version}")
async def rollback_view(
    view_id: str,
    version: int,
    request: RollbackViewRequest,
    identity: AuthIdentity = Depends(require_permission("views:rollback")),
) -> dict[str, Any]:
    ensure_scope(identity, user_id=request.user_id, project_id=request.project_id)

    service = get_view_storage_service()
    try:
        result = service.rollback_view(
            view_id,
            RollbackInput(
                user_id=identity.user_id,
                project_id=identity.project_id,
                role=identity.role,
                department=identity.department,
                clearance=identity.clearance,
                target_version=version,
            ),
        )
    except ViewStorageError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc

    get_audit_logger().log(
        event_type="sharing",
        action="rollback_view",
        status="success",
        user_id=identity.user_id,
        project_id=identity.project_id,
        detail={"view_id": view_id, "version": result["version"]},
    )
    result["share_url"] = result["share_path"]
    return result


@app.post("/invites/{token}/accept")
async def accept_invite(
    token: str,
    identity: AuthIdentity = Depends(get_current_identity),
) -> dict[str, Any]:
    from .collaboration import accept_invite as _accept_invite
    from .auth import _get_db_conn

    conn = _get_db_conn()
    try:
        result = _accept_invite(conn, raw_token=token, user_id=identity.user_id)
    except ValueError as exc:
        code = str(exc)
        status = 410 if code in ("invite_expired", "invite_revoked", "invite_exhausted") else 400
        raise HTTPException(status_code=status, detail={"code": code, "message": code})
    finally:
        conn.close()

    if result.get("already_member"):
        return {"already_member": True, "workspace_id": result["workspace_id"], "role": result["role"]}

    from .workspaces import get_workspace_service, WorkspaceError
    try:
        workspace = get_workspace_service().get_workspace_for_user(
            workspace_id=result["workspace_id"],
            user_id=identity.user_id,
        )
    except WorkspaceError:
        workspace = {"workspace_id": result["workspace_id"]}

    return {
        "already_member": False,
        "workspace_id": result["workspace_id"],
        "role": result["role"],
        "workspace": workspace,
    }


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.app_env,
    }


@app.get("/chat/capabilities")
async def chat_capabilities(
    identity: AuthIdentity = Depends(require_permission("chat:stream")),
) -> dict[str, bool]:
    """Feature flags the chat composer needs to gate optional UI affordances."""
    _ = identity
    settings = get_settings()
    return {
        "agent_canvas_mode_enabled": bool(settings.agent_canvas_mode_enabled),
        "web_search_enabled": bool(settings.web_search_enabled),
    }


def _build_query_ast(*, request: SemanticQueryRequest, parser: IntentParser) -> SemanticQueryAST:
    explicit_filters = [item.to_query_filter() for item in request.filters]

    if request.metric:
        return SemanticQueryAST(
            metric=request.metric,
            group_by=request.group_by,
            filters=explicit_filters,
            limit=request.limit,
        )

    if request.intent:
        parsed = parser.parse(request.intent)
        merged_group_by = request.group_by or parsed.group_by
        merged_filters = [*parsed.filters, *explicit_filters]
        return SemanticQueryAST(
            metric=parsed.metric,
            group_by=merged_group_by,
            filters=merged_filters,
            limit=request.limit,
        )

    raise MetricCompileError(
        code="MISSING_QUERY_TARGET",
        message="Either metric or intent must be provided",
    )
