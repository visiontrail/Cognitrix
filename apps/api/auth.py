from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any, Callable
from urllib.parse import unquote, urlparse

from fastapi import Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator

from .audit import get_audit_logger
from .config import get_settings

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "superadmin": {
        "datasets:upload",
        "datasets:read",
        "semantic:metrics",
        "semantic:query",
        "chat:tool",
        "chat:stream",
        "views:write",
        "views:read",
        "views:share",
        "views:rollback",
        "audit:read",
        "auth:manage",
        "workspaces:read",
        "workspaces:write",
        "workspaces:manage",
        "skills:admin",
    },
    "admin": {
        "datasets:upload",
        "datasets:read",
        "semantic:metrics",
        "semantic:query",
        "chat:tool",
        "chat:stream",
        "views:write",
        "views:read",
        "views:share",
        "views:rollback",
        "audit:read",
        "auth:manage",
        "workspaces:read",
        "workspaces:write",
        "workspaces:manage",
    },
    "hr": {
        "datasets:upload",
        "datasets:read",
        "semantic:metrics",
        "semantic:query",
        "chat:tool",
        "chat:stream",
        "views:write",
        "views:read",
        "views:share",
        "audit:read",
        "workspaces:read",
        "workspaces:write",
        "workspaces:manage",
    },
    "pm": {
        "datasets:upload",
        "datasets:read",
        "semantic:metrics",
        "semantic:query",
        "chat:tool",
        "chat:stream",
        "views:write",
        "views:read",
        "views:share",
        "workspaces:read",
        "workspaces:write",
        "workspaces:manage",
    },
    "viewer": {
        "datasets:read",
        "semantic:metrics",
        "semantic:query",
        "chat:tool",
        "chat:stream",
        "views:read",
        "views:share",
        "workspaces:read",
        "workspaces:write",
    },
}

DEFAULT_TOKEN_TTL_SECONDS = 3600
MAX_TOKEN_TTL_SECONDS = 24 * 3600

SQLITE_RELATIVE_BASE = Path(__file__).resolve().parent

_bearer_scheme = HTTPBearer(auto_error=False)
logger = logging.getLogger("cognitrix.auth")


@dataclass(slots=True)
class AuthIdentity:
    user_id: str
    project_id: str
    role: str
    department: str | None
    clearance: int
    token_id: str
    expires_at: int


class LoginRequest(BaseModel):
    user_id: str
    project_id: str
    role: str = "viewer"
    department: str | None = None
    clearance: int = 0
    expires_in: int = Field(default=DEFAULT_TOKEN_TTL_SECONDS, ge=60, le=MAX_TOKEN_TTL_SECONDS)


class EmailLoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    email: str
    password: str
    display_name: str
    job_id: int

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized or len(normalized) < 3:
            raise ValueError("Invalid email address")
        return normalized

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("display_name is required")
        return normalized


class RoleUpdateRequest(BaseModel):
    role: str
    department: str | None = None
    clearance: int = 0


class AuthTokenError(Exception):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class TokenExpiredError(AuthTokenError):
    pass


class TokenService:
    def __init__(self, *, secret: str) -> None:
        normalized = secret.strip()
        if not normalized:
            raise RuntimeError("AUTH_SECRET cannot be empty")
        self._secret = normalized.encode("utf-8")

    def issue_token(
        self,
        *,
        user_id: str,
        project_id: str,
        role: str,
        department: str | None,
        clearance: int,
        expires_in: int,
    ) -> tuple[str, int]:
        now = int(time.time())
        expires_at = now + expires_in
        normalized_role = normalize_role(role)
        payload = {
            "sub": user_id,
            "project_id": project_id,
            "role": normalized_role,
            "department": department,
            "clearance": int(clearance),
            "iat": now,
            "exp": expires_at,
            "jti": hashlib.sha1(f"{user_id}:{project_id}:{now}".encode("utf-8")).hexdigest()[:16],
        }
        token = self._encode(payload)
        return token, expires_at

    def verify_token(self, token: str) -> AuthIdentity:
        payload = self._decode(token)

        expires_at = int(payload.get("exp", 0))
        if expires_at <= int(time.time()):
            raise TokenExpiredError(code="TOKEN_EXPIRED", message="Authentication token has expired")

        user_id = str(payload.get("sub", "")).strip()
        project_id = str(payload.get("project_id", "")).strip()
        if not user_id or not project_id:
            raise AuthTokenError(code="TOKEN_INVALID", message="Authentication token is invalid")

        role = normalize_role(str(payload.get("role", "viewer")))
        clearance = int(payload.get("clearance", 0))
        token_id = str(payload.get("jti", "")).strip() or "unknown"

        department_raw = payload.get("department")
        department = str(department_raw).strip() if isinstance(department_raw, str) else None
        if department == "":
            department = None

        return AuthIdentity(
            user_id=user_id,
            project_id=project_id,
            role=role,
            department=department,
            clearance=clearance,
            token_id=token_id,
            expires_at=expires_at,
        )

    def _encode(self, payload: dict[str, Any]) -> str:
        header = {"alg": "HS256", "typ": "JWT"}
        header_bytes = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
        payload_bytes = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        signing_input = f"{header_bytes}.{payload_bytes}".encode("utf-8")
        signature = _b64url_encode(hmac.new(self._secret, signing_input, hashlib.sha256).digest())
        return f"{header_bytes}.{payload_bytes}.{signature}"

    def _decode(self, token: str) -> dict[str, Any]:
        parts = token.split(".")
        if len(parts) != 3:
            raise AuthTokenError(code="TOKEN_INVALID", message="Authentication token is invalid")

        header_segment, payload_segment, signature_segment = parts
        expected_signature = _b64url_encode(
            hmac.new(
                self._secret,
                f"{header_segment}.{payload_segment}".encode("utf-8"),
                hashlib.sha256,
            ).digest()
        )

        if not hmac.compare_digest(expected_signature, signature_segment):
            raise AuthTokenError(code="TOKEN_INVALID", message="Authentication token is invalid")

        try:
            header = json.loads(_b64url_decode(header_segment).decode("utf-8"))
            payload = json.loads(_b64url_decode(payload_segment).decode("utf-8"))
        except (ValueError, json.JSONDecodeError) as exc:
            raise AuthTokenError(code="TOKEN_INVALID", message="Authentication token is invalid") from exc

        if header.get("alg") != "HS256":
            raise AuthTokenError(code="TOKEN_INVALID", message="Authentication token is invalid")

        if not isinstance(payload, dict):
            raise AuthTokenError(code="TOKEN_INVALID", message="Authentication token is invalid")

        return payload


class RoleDirectory:
    def __init__(self, *, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def set_override(
        self,
        *,
        user_id: str,
        role: str,
        department: str | None,
        clearance: int,
        updated_by: str,
    ) -> dict[str, Any]:
        normalized_user = user_id.strip()
        if not normalized_user:
            raise ValueError("user_id is required")

        normalized_role = normalize_role(role)
        now = int(time.time())

        with self._lock:
            payload = self._load()
            payload[normalized_user] = {
                "role": normalized_role,
                "department": department,
                "clearance": int(clearance),
                "updated_by": updated_by,
                "updated_at": now,
            }
            self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return payload[normalized_user]

    def get_override(self, user_id: str) -> dict[str, Any] | None:
        normalized_user = user_id.strip()
        if not normalized_user:
            return None

        with self._lock:
            payload = self._load()
            raw = payload.get(normalized_user)
            if not isinstance(raw, dict):
                return None
            return dict(raw)

    def has_any_with_role(self, role: str) -> bool:
        target = role.strip().lower()
        with self._lock:
            payload = self._load()
        for entry in payload.values():
            if isinstance(entry, dict) and str(entry.get("role", "")).strip().lower() == target:
                return True
        return False

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        raw = self.path.read_text(encoding="utf-8").strip()
        if not raw:
            return {}
        decoded = json.loads(raw)
        if isinstance(decoded, dict):
            return decoded
        return {}


def has_permission(role: str, permission: str) -> bool:
    normalized_role = normalize_role(role)
    return permission in ROLE_PERMISSIONS.get(normalized_role, set())


def normalize_role(role: str) -> str:
    normalized = role.strip().lower()
    if normalized not in ROLE_PERMISSIONS:
        raise AuthTokenError(code="ROLE_INVALID", message="Unsupported role")
    return normalized


def require_permission(permission: str) -> Callable[[Request, AuthIdentity], AuthIdentity]:
    def dependency(
        request: Request,
        identity: AuthIdentity = Depends(get_current_identity),
    ) -> AuthIdentity:
        if has_permission(identity.role, permission):
            return identity

        get_audit_logger().log(
            event_type="authorization",
            action=permission,
            status="denied",
            severity="ALERT",
            user_id=identity.user_id,
            project_id=identity.project_id,
            resource=str(request.url.path),
            detail={"role": identity.role},
        )
        raise HTTPException(
            status_code=403,
            detail={
                "code": "RBAC_FORBIDDEN",
                "message": "You do not have permission to access this resource",
            },
        )

    return dependency


def ensure_scope(identity: AuthIdentity, *, user_id: str, project_id: str) -> None:
    if identity.user_id != user_id or identity.project_id != project_id:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "SCOPE_MISMATCH",
                "message": "Token scope does not match request context",
            },
        )


def can_access_owned_resource(
    identity: AuthIdentity,
    *,
    owner_user_id: str,
    owner_project_id: str,
) -> bool:
    if identity.role in {"admin", "superadmin"}:
        return True
    return identity.user_id == owner_user_id and identity.project_id == owner_project_id


def issue_access_token(payload: LoginRequest) -> dict[str, Any]:
    service = get_token_service()
    token, expires_at = service.issue_token(
        user_id=payload.user_id.strip(),
        project_id=payload.project_id.strip(),
        role=payload.role,
        department=payload.department,
        clearance=payload.clearance,
        expires_in=payload.expires_in,
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_at": expires_at,
        "user": {
            "user_id": payload.user_id.strip(),
            "project_id": payload.project_id.strip(),
            "role": normalize_role(payload.role),
            "department": payload.department,
            "clearance": int(payload.clearance),
        },
    }


def issue_user_token(
    *,
    user_id: str,
    role: str = "admin",
    department: str | None = None,
    clearance: int = 0,
) -> tuple[str, int]:
    settings = get_settings()
    expires_in = settings.access_token_ttl_min * 60
    service = get_token_service()
    return service.issue_token(
        user_id=user_id,
        project_id="default",
        role=role,
        department=department,
        clearance=clearance,
        expires_in=expires_in,
    )


def _get_db_conn() -> sqlite3.Connection:
    settings = get_settings()
    db_url = settings.database_url.strip()
    if db_url.startswith("sqlite://"):
        parsed = urlparse(db_url)
        raw_path = unquote(parsed.path)
        if raw_path.startswith("//"):
            # 4-slash absolute path: sqlite:////abs/path
            db_path = Path("/" + raw_path.lstrip("/")).resolve()
        elif raw_path.startswith("/") and len(raw_path) > 1 and raw_path[1] != ".":
            # absolute path like /abs/path
            db_path = Path(raw_path).resolve()
        else:
            # relative path
            if raw_path.startswith("/"):
                raw_path = raw_path[1:]
            db_path = (SQLITE_RELATIVE_BASE / raw_path).resolve()
    else:
        db_path = (settings.upload_dir / "state" / "ai_views.sqlite3").resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def handle_email_register(request: RegisterRequest, response: Response) -> dict[str, Any]:
    from .users import create_user, get_user_by_email
    from .jobs import validate_job_id

    settings = get_settings()
    if not settings.auth_registration_enabled:
        raise HTTPException(
            status_code=403,
            detail={"code": "registration_disabled", "message": "Registration is currently disabled"},
        )
    if len(request.password) < settings.password_min_length:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "password_too_short",
                "message": f"密码至少 {settings.password_min_length} 位",
            },
        )

    conn = _get_db_conn()
    try:
        existing = get_user_by_email(conn, request.email)
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail={"code": "email_taken", "message": "该邮箱已被注册"},
            )

        if not validate_job_id(conn, request.job_id):
            raise HTTPException(
                status_code=422,
                detail={"code": "invalid_job_id", "message": "Invalid job_id"},
            )

        user = create_user(
            conn,
            email=request.email,
            display_name=request.display_name,
            password=request.password,
            job_id=request.job_id,
        )
    finally:
        conn.close()

    token, expires_at = issue_user_token(user_id=user.id)
    _set_session_cookie(response, token)
    get_audit_logger().log(
        event_type="authentication",
        action="register",
        status="success",
        user_id=user.id,
        project_id="default",
        detail={"email": user.email},
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_at": expires_at,
        "user": {
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "job_id": user.job_id,
        },
    }


def handle_email_login(request: EmailLoginRequest, response: Response) -> dict[str, Any]:
    from .users import get_user_by_email, update_last_login, verify_password

    submitted_email = request.email.strip().lower()
    logger.info("[login] attempt email=%s", submitted_email)

    conn = _get_db_conn()
    try:
        user = get_user_by_email(conn, submitted_email)
        if user is None:
            logger.warning("[login] user not found email=%s", submitted_email)
            raise HTTPException(
                status_code=401,
                detail={"code": "invalid_credentials", "message": "邮箱或密码错误"},
            )
        logger.info(
            "[login] user found id=%s email_col=%s email_lower=%s has_password=%s",
            user.id,
            user.email,
            user.email_lower,
            user.password_hash is not None,
        )
        if user.password_hash is None:
            logger.warning("[login] no password_hash for user id=%s", user.id)
            raise HTTPException(
                status_code=401,
                detail={"code": "invalid_credentials", "message": "邮箱或密码错误"},
            )
        pw_ok = verify_password(request.password, user.password_hash)
        logger.info("[login] password verify result=%s user_id=%s", pw_ok, user.id)
        if not pw_ok:
            raise HTTPException(
                status_code=401,
                detail={"code": "invalid_credentials", "message": "邮箱或密码错误"},
            )
        update_last_login(conn, user.id)
    finally:
        conn.close()

    token, expires_at = issue_user_token(user_id=user.id)
    _set_session_cookie(response, token)
    logger.info(
        "[login] success user_id=%s email_lower=%s email_col=%s display_name=%s",
        user.id,
        user.email_lower,
        user.email,
        user.display_name,
    )
    get_audit_logger().log(
        event_type="authentication",
        action="login",
        status="success",
        user_id=user.id,
        project_id="default",
        detail={"email": user.email_lower},
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_at": expires_at,
        "user": {
            "id": user.id,
            "email": user.email_lower,
            "display_name": user.display_name,
            "job_id": user.job_id,
        },
    }


def handle_logout(response: Response) -> dict[str, str]:
    response.delete_cookie("cognitrix_session", samesite="lax")
    return {"status": "ok"}


def handle_me(identity: AuthIdentity) -> dict[str, Any]:
    from .users import get_user_by_id
    from .workspaces import get_workspace_service

    conn = _get_db_conn()
    try:
        user = get_user_by_id(conn, identity.user_id)
    finally:
        conn.close()

    if user is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "authentication_required", "message": "User not found"},
        )

    available_workspaces = get_workspace_service().list_workspaces_for_user(user_id=identity.user_id)
    has_designer_workspace = any(
        w.get("role") in ("owner", "editor") for w in available_workspaces
    )
    default_app_mode = "designer" if has_designer_workspace else "viewer"

    return {
        "id": user.id,
        "email": user.email_lower,
        "display_name": user.display_name,
        "job_id": user.job_id,
        "last_login_at": user.last_login_at,
        "available_workspaces": available_workspaces,
        "default_app_mode": default_app_mode,
    }


def get_current_identity(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> AuthIdentity:
    audit = get_audit_logger()
    header_snapshot = _authorization_header_snapshot(request)

    # Cookie fallback: read from cognitrix_session cookie if no bearer token
    token_str: str | None = None
    if credentials and credentials.scheme.lower() == "bearer":
        token_str = credentials.credentials
    else:
        cookie_token = request.cookies.get("cognitrix_session")
        if cookie_token:
            token_str = cookie_token

    if token_str is None:
        reason = "missing_token"
        if header_snapshot["has_auth_header"] and header_snapshot["auth_scheme"] != "bearer":
            reason = "invalid_auth_scheme"
        elif (
            header_snapshot["has_auth_header"]
            and header_snapshot["auth_scheme"] == "bearer"
            and header_snapshot["token_length"] == 0
        ):
            reason = "empty_bearer_token"

        audit.log(
            event_type="authentication",
            action="access",
            status="denied",
            severity="ALERT",
            resource=str(request.url.path),
            detail={"reason": reason},
        )
        logger.warning(
            "auth_denied path=%s method=%s reason=%s has_auth_header=%s auth_scheme=%s token_length=%d",
            request.url.path,
            request.method,
            reason,
            header_snapshot["has_auth_header"],
            header_snapshot["auth_scheme"],
            header_snapshot["token_length"],
        )
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_REQUIRED", "message": "Authentication is required"},
        )

    try:
        identity = get_token_service().verify_token(token_str)
    except TokenExpiredError as exc:
        audit.log(
            event_type="authentication",
            action="access",
            status="denied",
            severity="ALERT",
            resource=str(request.url.path),
            detail={"reason": exc.code},
        )
        logger.warning(
            "auth_denied path=%s method=%s reason=%s token_fingerprint=%s token_length=%d",
            request.url.path,
            request.method,
            exc.code,
            _token_fingerprint(token_str),
            len(token_str),
        )
        raise HTTPException(status_code=401, detail={"code": exc.code, "message": exc.message}) from exc
    except AuthTokenError as exc:
        audit.log(
            event_type="authentication",
            action="access",
            status="denied",
            severity="ALERT",
            resource=str(request.url.path),
            detail={"reason": exc.code},
        )
        logger.warning(
            "auth_denied path=%s method=%s reason=%s token_fingerprint=%s token_length=%d",
            request.url.path,
            request.method,
            exc.code,
            _token_fingerprint(token_str),
            len(token_str),
        )
        raise HTTPException(status_code=401, detail={"code": exc.code, "message": exc.message}) from exc

    override = get_role_directory().get_override(identity.user_id)
    if override:
        override_role = override.get("role", identity.role)
        identity = AuthIdentity(
            user_id=identity.user_id,
            project_id=identity.project_id,
            role=normalize_role(str(override_role)),
            department=_optional_string(override.get("department")) or identity.department,
            clearance=int(override.get("clearance", identity.clearance)),
            token_id=identity.token_id,
            expires_at=identity.expires_at,
        )

    request.state.identity = identity
    return identity


def get_optional_identity(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> AuthIdentity | None:
    try:
        return get_current_identity(request, credentials)
    except HTTPException:
        return None


def get_role_directory() -> RoleDirectory:
    settings = get_settings()
    target = (settings.upload_dir / "auth" / "role_overrides.json").resolve()
    return _cached_role_directory(str(target))


def get_token_service() -> TokenService:
    settings = get_settings()
    return _cached_token_service(settings.auth_secret)


@lru_cache(maxsize=2)
def _cached_token_service(secret: str) -> TokenService:
    return TokenService(secret=secret)


@lru_cache(maxsize=2)
def _cached_role_directory(path_key: str) -> RoleDirectory:
    return RoleDirectory(path=Path(path_key))


def clear_auth_cache() -> None:
    _cached_token_service.cache_clear()
    _cached_role_directory.cache_clear()


def _set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    max_age = settings.access_token_ttl_min * 60
    response.set_cookie(
        key="cognitrix_session",
        value=token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=False,  # Set True in production behind HTTPS
    )


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _authorization_header_snapshot(request: Request) -> dict[str, Any]:
    raw_header = request.headers.get("authorization", "").strip()
    if not raw_header:
        return {
            "has_auth_header": False,
            "auth_scheme": "",
            "token_length": 0,
        }

    scheme, _, rest = raw_header.partition(" ")
    token = rest.strip()
    return {
        "has_auth_header": True,
        "auth_scheme": scheme.strip().lower(),
        "token_length": len(token),
    }


def _token_fingerprint(token: str) -> str:
    if not token:
        return "none"
    return hashlib.sha1(token.encode("utf-8")).hexdigest()[:12]


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _b64url_decode(raw: str) -> bytes:
    padding = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(f"{raw}{padding}")
