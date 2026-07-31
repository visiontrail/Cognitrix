from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ValidationError

from .admin_store import AdminControlStore, get_admin_store
from .audit import get_audit_logger
from .auth import (
    AuthIdentity,
    clear_auth_cache,
    get_role_directory,
    normalize_role,
    require_permission,
)
from .config import Settings, get_bootstrap_settings, get_settings

router = APIRouter(prefix="/admin/control", tags=["admin-control"])

EXPLICIT_SECRET_KEYS = {
    "AI_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "AUTH_BOOTSTRAP_ADMIN_PASSWORD",
    "AUTH_SECRET",
    "WEB_SEARCH_API_KEY",
}
RESTART_REQUIRED_KEYS = {
    "APP_ENV",
    "DATABASE_URL",
    "UPLOAD_DIR",
    "AUTH_SECRET",
    "CORS_ALLOW_ORIGINS",
    "APP_URL",
    "PUBLIC_BASE_URL",
    "AGENT_SKILLS_DIR",
    "AGENT_SKILLS_ENABLED",
    "AUTH_BOOTSTRAP_ADMIN_EMAIL",
    "AUTH_BOOTSTRAP_ADMIN_PASSWORD",
    "AUTH_BOOTSTRAP_SUPERADMIN_EMAIL",
}
MODEL_SETTING_KEYS = {
    "MODEL_PROVIDER_URL",
    "AI_API_KEY",
    "AI_MODEL",
    "AI_TIMEOUT_SECONDS",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "API_TIMEOUT_MS",
}


class SettingUpdateRequest(BaseModel):
    value: Any = None
    clear: bool = False


class UserRoleUpdateRequest(BaseModel):
    role: str


class UserStatusUpdateRequest(BaseModel):
    status: Literal["active", "suspended"]


class ModelConnectionTestRequest(BaseModel):
    provider_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    timeout_seconds: float | None = None


def get_control_store() -> AdminControlStore:
    return get_admin_store(get_bootstrap_settings().upload_dir)


def record_usage_event(
    *,
    user_id: str,
    project_id: str | None,
    event_type: str,
    route: str | None = None,
    status_code: int | None = None,
    duration_ms: float | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    try:
        get_control_store().record_usage(
            user_id=user_id,
            project_id=project_id,
            event_type=event_type,
            route=route,
            status_code=status_code,
            duration_ms=duration_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            metadata=metadata,
        )
    except Exception:
        # Telemetry must never break a product request.
        return


@router.get("/meta")
async def admin_meta(
    identity: AuthIdentity = Depends(require_permission("admin:control")),
) -> dict[str, Any]:
    settings = get_settings()
    return {
        "actor": {"user_id": identity.user_id, "role": identity.role},
        "environment": settings.app_env,
        "app_name": settings.app_name,
        "settings_count": len(Settings.model_fields),
        "restart_required_count": len(RESTART_REQUIRED_KEYS),
        "skills": {
            "enabled": settings.agent_skills_enabled,
            "directory": str(settings.resolved_agent_skills_dir),
            "max_upload_mb": settings.agent_skills_max_upload_mb,
        },
    }


@router.get("/settings")
async def list_settings(
    category: str | None = None,
    identity: AuthIdentity = Depends(require_permission("admin:control")),
) -> dict[str, Any]:
    del identity
    items = _settings_inventory()
    if category:
        normalized = category.strip().lower()
        items = [item for item in items if item["category"] == normalized]
    categories = sorted({str(item["category"]) for item in _settings_inventory()})
    return {"count": len(items), "categories": categories, "settings": items}


@router.get("/settings/history")
async def list_setting_history(
    limit: int = Query(default=100, ge=1, le=500),
    identity: AuthIdentity = Depends(require_permission("admin:control")),
) -> dict[str, Any]:
    del identity
    rows = get_control_store().list_history(limit=limit)
    return {"count": len(rows), "history": rows}


@router.patch("/settings/{key}")
async def update_setting(
    key: str,
    request: SettingUpdateRequest,
    identity: AuthIdentity = Depends(require_permission("admin:control")),
) -> dict[str, Any]:
    normalized = key.strip().upper()
    field_name, field = _field_for_alias(normalized)
    if field is None or field_name is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "setting_not_found", "message": f"Unknown setting: {normalized}"},
        )

    secret = _is_secret(normalized)
    current = get_settings()
    existing = getattr(current, field_name)
    if secret and not request.clear and (request.value is None or str(request.value) == ""):
        return _serialize_setting(
            key=normalized,
            field_name=field_name,
            effective=current,
            base=get_bootstrap_settings(),
            overrides=get_control_store().load_overrides(),
        )

    next_value = "" if request.clear else request.value
    candidate_payload = current.model_dump(by_alias=True)
    candidate_payload[normalized] = next_value
    try:
        Settings(_env_file=None, **candidate_payload)
    except ValidationError as exc:
        _audit_admin_mutation(
            identity=identity,
            action="setting_update",
            status="rejected",
            resource=f"admin.settings.{normalized}",
            detail={"key": normalized, "reason": "validation_failed"},
        )
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_setting_value",
                "message": _sanitized_validation_message(normalized, exc, secret=secret),
            },
        ) from exc

    get_control_store().set_override(
        key=normalized,
        value=next_value,
        is_secret=secret,
        updated_by=identity.user_id,
    )
    _clear_runtime_caches(normalized)
    _audit_admin_mutation(
        identity=identity,
        action="setting_update",
        status="success",
        resource=f"admin.settings.{normalized}",
        detail={"key": normalized, "restart_required": normalized in RESTART_REQUIRED_KEYS},
    )
    return _serialize_setting(
        key=normalized,
        field_name=field_name,
        effective=get_settings(),
        base=get_bootstrap_settings(),
        overrides=get_control_store().load_overrides(),
    )


@router.delete("/settings/{key}")
async def reset_setting(
    key: str,
    identity: AuthIdentity = Depends(require_permission("admin:control")),
) -> dict[str, Any]:
    normalized = key.strip().upper()
    field_name, field = _field_for_alias(normalized)
    if field is None or field_name is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "setting_not_found", "message": f"Unknown setting: {normalized}"},
        )
    removed = get_control_store().delete_override(
        key=normalized,
        is_secret=_is_secret(normalized),
        updated_by=identity.user_id,
    )
    _clear_runtime_caches(normalized)
    _audit_admin_mutation(
        identity=identity,
        action="setting_reset",
        status="success",
        resource=f"admin.settings.{normalized}",
        detail={"key": normalized, "had_override": removed},
    )
    return _serialize_setting(
        key=normalized,
        field_name=field_name,
        effective=get_settings(),
        base=get_bootstrap_settings(),
        overrides=get_control_store().load_overrides(),
    )


@router.get("/models")
async def get_model_settings(
    identity: AuthIdentity = Depends(require_permission("admin:control")),
) -> dict[str, Any]:
    del identity
    items = [
        item for item in _settings_inventory() if str(item["key"]) in MODEL_SETTING_KEYS
    ]
    return {"count": len(items), "settings": items}


@router.post("/models/test")
async def test_model_connection(
    request: ModelConnectionTestRequest,
    identity: AuthIdentity = Depends(require_permission("admin:control")),
) -> dict[str, Any]:
    settings = get_settings()
    provider_url = (request.provider_url or settings.model_provider_url).strip().rstrip("/")
    model = (request.model or settings.ai_model).strip()
    api_key = request.api_key if request.api_key not in (None, "") else settings.ai_api_key
    timeout = request.timeout_seconds or settings.ai_timeout_seconds
    if not provider_url or not model or not api_key:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "model_configuration_incomplete",
                "message": "Provider URL, model, and API key are required",
            },
        )

    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=max(1.0, min(float(timeout), 30.0))) as client:
            response = await client.post(
                f"{provider_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "Reply with OK."}],
                    "max_tokens": 1,
                    "temperature": 0,
                },
            )
        latency = round((time.perf_counter() - started) * 1000, 2)
        if response.status_code >= 400:
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "model_connection_failed",
                    "message": f"Provider returned HTTP {response.status_code}",
                    "latency_ms": latency,
                },
            )
        _audit_admin_mutation(
            identity=identity,
            action="model_connection_test",
            status="success",
            resource="admin.models",
            detail={"provider": _provider_label(provider_url), "model": model},
        )
        return {
            "ok": True,
            "provider": _provider_label(provider_url),
            "model": model,
            "latency_ms": latency,
        }
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        latency = round((time.perf_counter() - started) * 1000, 2)
        _audit_admin_mutation(
            identity=identity,
            action="model_connection_test",
            status="failed",
            resource="admin.models",
            detail={"provider": _provider_label(provider_url), "model": model},
        )
        raise HTTPException(
            status_code=502,
            detail={
                "code": "model_connection_failed",
                "message": _sanitize_connection_error(exc),
                "latency_ms": latency,
            },
        ) from exc


@router.get("/users")
async def list_admin_users(
    q: str = "",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    identity: AuthIdentity = Depends(require_permission("admin:control")),
) -> dict[str, Any]:
    del identity
    conn = _app_db_conn()
    try:
        term = f"%{q.strip().lower()}%"
        where = ""
        params: list[Any] = []
        if q.strip():
            where = (
                "WHERE LOWER(COALESCE(u.email_lower, u.email)) LIKE ? "
                "OR LOWER(u.display_name) LIKE ?"
            )
            params.extend([term, term])
        total_row = conn.execute(
            f"SELECT COUNT(*) AS count FROM users u {where}", params
        ).fetchone()
        rows = conn.execute(
            f"""
            SELECT
                u.id, u.email, COALESCE(u.email_lower, LOWER(u.email)) AS email_lower,
                u.display_name, u.job_id, u.status, u.created_at, u.last_login_at,
                uj.label_zh AS job_label_zh, uj.label_en AS job_label_en,
                (SELECT COUNT(*) FROM workspace_members wm WHERE wm.user_id = u.id) AS workspace_count
            FROM users u
            LEFT JOIN user_jobs uj ON uj.id = u.job_id
            {where}
            ORDER BY u.created_at DESC
            LIMIT ? OFFSET ?
            """,
            [*params, page_size, (page - 1) * page_size],
        ).fetchall()
    finally:
        conn.close()

    usage = _recent_user_usage()
    role_dir = get_role_directory()
    users = []
    for row in rows:
        user_id = str(row["id"])
        override = role_dir.get_override(user_id) or {}
        users.append(
            {
                "id": user_id,
                "email": str(row["email_lower"]),
                "display_name": str(row["display_name"]),
                "job_id": row["job_id"],
                "job_label": str(row["job_label_zh"] or row["job_label_en"] or ""),
                "status": str(row["status"]),
                "role": str(override.get("role", "admin")),
                "created_at": str(row["created_at"]),
                "last_login_at": row["last_login_at"],
                "workspace_count": int(row["workspace_count"] or 0),
                "usage": usage.get(user_id, _empty_usage()),
            }
        )
    total = int(total_row["count"] if total_row else 0)
    return {
        "users": users,
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


@router.patch("/users/{user_id}/role")
async def update_admin_user_role(
    user_id: str,
    request: UserRoleUpdateRequest,
    identity: AuthIdentity = Depends(require_permission("admin:control")),
) -> dict[str, Any]:
    try:
        role = normalize_role(request.role)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_role", "message": "Unsupported role"},
        ) from exc
    user = _require_user(user_id)
    role_dir = get_role_directory()
    previous = str((role_dir.get_override(user_id) or {}).get("role", "admin"))
    if previous == "superadmin" and role != "superadmin" and _active_superadmin_count() <= 1:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "last_superadmin",
                "message": "The last active superadmin cannot be demoted",
            },
        )
    role_dir.set_override(
        user_id=user_id,
        role=role,
        department=None,
        clearance=0,
        updated_by=identity.user_id,
    )
    clear_auth_cache()
    _audit_admin_mutation(
        identity=identity,
        action="user_role_update",
        status="success",
        resource=f"admin.users.{user_id}",
        detail={"user_id": user_id, "previous_role": previous, "new_role": role},
    )
    return {
        "id": user_id,
        "email": user["email"],
        "role": role,
        "status": user["status"],
    }


@router.patch("/users/{user_id}/status")
async def update_admin_user_status(
    user_id: str,
    request: UserStatusUpdateRequest,
    identity: AuthIdentity = Depends(require_permission("admin:control")),
) -> dict[str, Any]:
    user = _require_user(user_id)
    if user_id == identity.user_id and request.status != "active":
        raise HTTPException(
            status_code=409,
            detail={"code": "self_lockout", "message": "You cannot suspend your own account"},
        )
    effective_role = str(
        (get_role_directory().get_override(user_id) or {}).get("role", "admin")
    )
    if (
        effective_role == "superadmin"
        and request.status != "active"
        and _active_superadmin_count() <= 1
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "last_superadmin",
                "message": "The last active superadmin cannot be suspended",
            },
        )
    conn = _app_db_conn()
    try:
        conn.execute(
            "UPDATE users SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (request.status, user_id),
        )
        conn.commit()
    finally:
        conn.close()
    _audit_admin_mutation(
        identity=identity,
        action="user_status_update",
        status="success",
        resource=f"admin.users.{user_id}",
        detail={
            "user_id": user_id,
            "previous_status": user["status"],
            "new_status": request.status,
        },
    )
    return {
        "id": user_id,
        "email": user["email"],
        "role": effective_role,
        "status": request.status,
    }


@router.get("/usage/overview")
async def get_usage_overview(
    days: int = Query(default=30, ge=1, le=365),
    identity: AuthIdentity = Depends(require_permission("admin:control")),
) -> dict[str, Any]:
    del identity
    start_dt, end_dt = _date_window(days)
    store = get_control_store()
    summary = store.overview(start=start_dt.isoformat(), end=end_dt.isoformat())
    conn = _app_db_conn()
    try:
        row = conn.execute(
            """
            SELECT COUNT(*) AS total_users,
                   SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS enabled_users
            FROM users
            """
        ).fetchone()
    finally:
        conn.close()
    summary["total_users"] = int(row["total_users"] or 0)
    summary["enabled_users"] = int(row["enabled_users"] or 0)
    return {
        "range": {
            "days": days,
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
        },
        "summary": summary,
        "trend": _fill_daily_trend(
            store.daily_trend(start=start_dt.isoformat(), end=end_dt.isoformat()),
            start=start_dt,
            days=days,
        ),
    }


@router.get("/usage/users")
async def get_usage_users(
    days: int = Query(default=30, ge=1, le=365),
    sort: Literal[
        "requests", "chat_turns", "tool_calls", "tokens", "last_activity_at"
    ] = "chat_turns",
    order: Literal["asc", "desc"] = "desc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    identity: AuthIdentity = Depends(require_permission("admin:control")),
) -> dict[str, Any]:
    del identity
    start_dt, end_dt = _date_window(days)
    usage = get_control_store().user_usage(
        start=start_dt.isoformat(), end=end_dt.isoformat()
    )
    conn = _app_db_conn()
    try:
        rows = conn.execute(
            """
            SELECT id, COALESCE(email_lower, LOWER(email)) AS email,
                   display_name, status FROM users
            """
        ).fetchall()
    finally:
        conn.close()
    items = [
        {
            "id": str(row["id"]),
            "email": str(row["email"]),
            "display_name": str(row["display_name"]),
            "status": str(row["status"]),
            **usage.get(str(row["id"]), _empty_usage()),
        }
        for row in rows
    ]
    reverse = order == "desc"
    items.sort(
        key=lambda item: (
            str(item.get(sort) or "") if sort == "last_activity_at" else int(item.get(sort) or 0)
        ),
        reverse=reverse,
    )
    total = len(items)
    start = (page - 1) * page_size
    return {
        "users": items[start : start + page_size],
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


@router.get("/skills/meta")
async def get_skills_meta(
    identity: AuthIdentity = Depends(require_permission("admin:control")),
) -> dict[str, Any]:
    del identity
    settings = get_settings()
    return {
        "enabled": settings.agent_skills_enabled,
        "directory": str(settings.resolved_agent_skills_dir),
        "max_upload_mb": settings.agent_skills_max_upload_mb,
        "known_agents": [
            "WriteIngestionAgent",
            "QueryAgent",
            "ChartQueryAgent",
        ],
    }


def _settings_inventory() -> list[dict[str, Any]]:
    effective = get_settings()
    base = get_bootstrap_settings()
    overrides = get_control_store().load_overrides()
    result = []
    for field_name, field in Settings.model_fields.items():
        key = str(field.alias or field_name).upper()
        result.append(
            _serialize_setting(
                key=key,
                field_name=field_name,
                effective=effective,
                base=base,
                overrides=overrides,
            )
        )
    return sorted(result, key=lambda item: (str(item["category"]), str(item["key"])))


def _serialize_setting(
    *,
    key: str,
    field_name: str,
    effective: Settings,
    base: Settings,
    overrides: dict[str, Any],
) -> dict[str, Any]:
    value = getattr(effective, field_name)
    secret = _is_secret(key)
    source = "override" if key in overrides else _base_source(key)
    serialized = str(value) if isinstance(value, Path) else value
    base_value = getattr(base, field_name)
    base_serialized = str(base_value) if isinstance(base_value, Path) else base_value
    return {
        "key": key,
        "category": _setting_category(key),
        "type": _setting_type(value),
        "value": None if secret else serialized,
        "masked_value": _mask_secret(str(serialized)) if secret and str(serialized) else "",
        "configured": bool(str(serialized)) if secret else True,
        "secret": secret,
        "source": source,
        "has_override": key in overrides,
        "restart_required": key in RESTART_REQUIRED_KEYS,
        "base_value": None if secret else base_serialized,
        "description": _setting_description(key),
    }


def _base_source(key: str) -> str:
    if key in os.environ:
        return "environment"
    env_path = Path(os.getenv("API_ENV_FILE") or Path(__file__).resolve().parent / ".env")
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and stripped.partition("=")[0].strip() == key:
                return "environment"
    except OSError:
        pass
    return "default"


def _field_for_alias(key: str) -> tuple[str | None, Any | None]:
    for name, field in Settings.model_fields.items():
        if str(field.alias or name).upper() == key:
            return name, field
    return None, None


def _is_secret(key: str) -> bool:
    normalized = key.upper()
    return (
        normalized in EXPLICIT_SECRET_KEYS
        or normalized.endswith("_API_KEY")
        or normalized.endswith("_AUTH_TOKEN")
        or normalized.endswith("_PASSWORD")
        or normalized.endswith("_SECRET")
    )


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    tail = value[-4:] if len(value) > 4 else value[-1:]
    return f"••••••••{tail}"


def _setting_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, Path):
        return "path"
    return "string"


def _setting_category(key: str) -> str:
    if key in MODEL_SETTING_KEYS or key.startswith(("AI_", "ANTHROPIC_", "MODEL_")):
        return "models"
    if key.startswith(("AUTH_", "USER_", "PASSWORD_", "ACCESS_", "INVITE_")):
        return "authentication"
    if key.startswith(("AGENT_", "CLAUDE_", "MULTI_CHART_", "WEB_")):
        return "agent"
    if key.startswith(("DATABASE_", "UPLOAD_")):
        return "storage"
    if key.startswith(("PUBLIC_", "APP_", "CORS_", "LOG_", "API_")):
        return "application"
    return "features"


def _setting_description(key: str) -> str:
    descriptions = {
        "MODEL_PROVIDER_URL": "OpenAI-compatible model provider base URL",
        "AI_API_KEY": "Primary model provider API credential",
        "AI_MODEL": "Default model identifier",
        "ANTHROPIC_BASE_URL": "Anthropic Messages protocol endpoint",
        "ANTHROPIC_AUTH_TOKEN": "Anthropic-compatible provider credential",
        "AGENT_SKILLS_ENABLED": "Enable validated Agent Skill loading at runtime",
        "AUTH_REGISTRATION_ENABLED": "Allow new users to self-register",
        "ADMIN_USAGE_RETENTION_DAYS": "Number of days to retain usage events",
        "AGENT_MODE_MAX_STEPS": "Agent canvas mode: tool-step budget for the execution phase",
        "AGENT_MODE_OUTLINE_MAX_STEPS": (
            "Agent canvas mode: tool-step budget for the outline planning turn "
            "(too low ends the turn with no outline)"
        ),
        "AGENT_MODE_TIMEOUT_SECONDS": "Agent canvas mode: wall-clock budget for one run",
        "AGENT_MODE_MAX_CHARTS": "Agent canvas mode: maximum charts placed in one run",
        "AGENT_MODE_MAX_PAGES": (
            "Agent canvas mode: maximum dashboard pages (sidebar entries) one run may create"
        ),
    }
    return descriptions.get(key, key.replace("_", " ").title())


def _clear_runtime_caches(key: str) -> None:
    if key in RESTART_REQUIRED_KEYS:
        return
    get_settings.cache_clear()
    from .agent_runtime import clear_agent_runtime_cache
    from .chart_query_agent import clear_chart_query_agent_cache
    from .session_titles import clear_session_title_service_cache
    from .tool_calling import clear_tool_calling_service_cache

    clear_agent_runtime_cache()
    clear_chart_query_agent_cache()
    clear_session_title_service_cache()
    clear_tool_calling_service_cache()


def _sanitized_validation_message(key: str, exc: ValidationError, *, secret: bool) -> str:
    if secret:
        return f"{key} failed validation"
    errors = exc.errors(include_url=False)
    message = str(errors[0].get("msg", "invalid value")) if errors else "invalid value"
    return f"{key}: {message}"[:300]


def _audit_admin_mutation(
    *,
    identity: AuthIdentity,
    action: str,
    status: str,
    resource: str,
    detail: dict[str, Any],
) -> None:
    get_audit_logger().log(
        event_type="administration",
        action=action,
        status=status,
        severity="INFO" if status == "success" else "ALERT",
        user_id=identity.user_id,
        project_id=identity.project_id,
        resource=resource,
        detail=detail,
    )


def _app_db_conn():  # type: ignore[no-untyped-def]
    from .auth import _get_db_conn

    return _get_db_conn()


def _require_user(user_id: str) -> dict[str, Any]:
    conn = _app_db_conn()
    try:
        row = conn.execute(
            """
            SELECT id, COALESCE(email_lower, LOWER(email)) AS email, status
            FROM users WHERE id = ?
            """,
            (user_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "user_not_found", "message": "User not found"},
        )
    return {"id": str(row["id"]), "email": str(row["email"]), "status": str(row["status"])}


def _active_superadmin_count() -> int:
    conn = _app_db_conn()
    try:
        rows = conn.execute("SELECT id FROM users WHERE status = 'active'").fetchall()
    finally:
        conn.close()
    role_dir = get_role_directory()
    return sum(
        1
        for row in rows
        if str((role_dir.get_override(str(row["id"])) or {}).get("role", "admin"))
        == "superadmin"
    )


def _date_window(days: int) -> tuple[datetime, datetime]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    return start, end


def _recent_user_usage() -> dict[str, dict[str, Any]]:
    start, end = _date_window(30)
    return get_control_store().user_usage(start=start.isoformat(), end=end.isoformat())


def _empty_usage() -> dict[str, Any]:
    return {
        "requests": 0,
        "chat_turns": 0,
        "tool_calls": 0,
        "tokens": 0,
        "last_activity_at": None,
    }


def _fill_daily_trend(
    rows: list[dict[str, Any]], *, start: datetime, days: int
) -> list[dict[str, Any]]:
    by_day = {str(row["date"]): row for row in rows}
    first = start.date()
    result = []
    for offset in range(days + 1):
        day = (first + timedelta(days=offset)).isoformat()
        if day > datetime.now(timezone.utc).date().isoformat():
            break
        result.append(
            by_day.get(
                day,
                {
                    "date": day,
                    "requests": 0,
                    "chat_turns": 0,
                    "tool_calls": 0,
                    "active_users": 0,
                    "tokens": 0,
                },
            )
        )
    return result


def _provider_label(url: str) -> str:
    try:
        return httpx.URL(url).host or "custom"
    except Exception:
        return "custom"


def _sanitize_connection_error(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "Provider connection timed out"
    if isinstance(exc, httpx.ConnectError):
        return "Provider could not be reached"
    return "Provider connection test failed"
