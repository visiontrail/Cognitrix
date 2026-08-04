from __future__ import annotations

import os
import sqlite3
from functools import lru_cache
from pathlib import Path

from pydantic import Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_ENV_FILE_PATH = Path(__file__).resolve().parent / ".env"
LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
DEFAULT_DEVELOPMENT_ADMIN_PASSWORD = "Admin@123456"
DEFAULT_BOOTSTRAP_ADMIN_EMAIL = "admin@cognitrix.local"
# Signing keys that have ever been shipped in a template or committed to the
# repository. Anyone who can read the repo can forge tokens with these.
PUBLIC_PLACEHOLDER_SECRETS = {
    "replace-with-a-strong-secret",
    "dd904b50ad26343d430462093f66bedc79ec0be5db9c93422fa424ca0781f5d8",
}
# Bounds for MODEL_ROUTER_FIRST_TOKEN_DEADLINE_MS. Routing decides when to stop
# using the primary and start paying for the backup, so a mistyped threshold has
# a bill attached — and one below the floor would preempt runs that were never
# unhealthy.
FIRST_TOKEN_DEADLINE_FLOOR_MS = 5000
FIRST_TOKEN_DEADLINE_CEILING_MS = 600000


class Settings(BaseSettings):
    app_name: str = Field(default="Cognitrix API", alias="APP_NAME")
    app_env: str = Field(default="development", alias="APP_ENV")
    database_url: str = Field(alias="DATABASE_URL")
    sqlite_busy_timeout_ms: int = Field(default=15000, alias="SQLITE_BUSY_TIMEOUT_MS")
    model_provider_url: str = Field(
        default="https://api.deepseek.com", alias="MODEL_PROVIDER_URL"
    )
    ai_api_key: str = Field(default="", alias="AI_API_KEY")
    ai_model: str = Field(default="deepseek-chat", alias="AI_MODEL")
    ai_timeout_seconds: float = Field(default=20.0, alias="AI_TIMEOUT_SECONDS")
    model_primary_provider: str = Field(default="deepseek", alias="MODEL_PRIMARY_PROVIDER")
    model_backup_enabled: bool = Field(default=False, alias="MODEL_BACKUP_ENABLED")
    model_backup_provider: str = Field(default="yinhe", alias="MODEL_BACKUP_PROVIDER")
    model_backup_url: str = Field(default="", alias="MODEL_BACKUP_URL")
    model_backup_anthropic_url: str = Field(
        default="", alias="MODEL_BACKUP_ANTHROPIC_URL"
    )
    model_backup_api_key: str = Field(default="", alias="MODEL_BACKUP_API_KEY")
    model_backup_model: str = Field(default="", alias="MODEL_BACKUP_MODEL")
    model_backup_fast_model: str = Field(default="", alias="MODEL_BACKUP_FAST_MODEL")
    model_router_enabled: bool = Field(default=True, alias="MODEL_ROUTER_ENABLED")
    model_router_failure_threshold: int = Field(
        default=2, alias="MODEL_ROUTER_FAILURE_THRESHOLD"
    )
    model_router_cooldown_seconds: int = Field(
        default=60, alias="MODEL_ROUTER_COOLDOWN_SECONDS"
    )
    model_router_slow_ttft_ms: int = Field(
        default=15000, alias="MODEL_ROUTER_SLOW_TTFT_MS"
    )
    # Hard preemption deadline for the first model frame: once it expires the
    # attempt is abandoned and the next candidate starts immediately. This is
    # what MODEL_ROUTER_SLOW_TTFT_MS cannot do — that one only labels a sample
    # *after* the token finally arrives, so it never bounds what the user waits.
    # Applies only while the attempt is uncommitted and only when another
    # candidate exists; 0 disables preemption entirely.
    model_router_first_token_deadline_ms: int = Field(
        default=20000, alias="MODEL_ROUTER_FIRST_TOKEN_DEADLINE_MS"
    )
    anthropic_base_url: str = Field(
        default="https://api.deepseek.com/anthropic",
        alias="ANTHROPIC_BASE_URL",
    )
    anthropic_auth_token: str = Field(default="", alias="ANTHROPIC_AUTH_TOKEN")
    anthropic_default_haiku_model: str = Field(
        default="",
        alias="ANTHROPIC_DEFAULT_HAIKU_MODEL",
    )
    api_timeout_ms: int = Field(default=600000, alias="API_TIMEOUT_MS")
    claude_agent_sdk_enabled: bool = Field(default=True, alias="CLAUDE_AGENT_SDK_ENABLED")
    agentic_ingestion_enabled: bool = Field(default=True, alias="AGENTIC_INGESTION_ENABLED")
    agent_max_tool_steps: int = Field(default=6, alias="AGENT_MAX_TOOL_STEPS")
    agent_max_sql_rows: int = Field(default=200, alias="AGENT_MAX_SQL_ROWS")
    agent_max_sql_scan_rows: int = Field(default=10000, alias="AGENT_MAX_SQL_SCAN_ROWS")
    agent_timeout_seconds: float = Field(default=25.0, alias="AGENT_TIMEOUT_SECONDS")
    agent_canvas_mode_enabled: bool = Field(default=False, alias="AGENT_CANVAS_MODE_ENABLED")
    agent_mode_max_steps: int = Field(default=40, alias="AGENT_MODE_MAX_STEPS")
    agent_mode_outline_max_steps: int = Field(default=24, alias="AGENT_MODE_OUTLINE_MAX_STEPS")
    agent_mode_timeout_seconds: float = Field(default=600.0, alias="AGENT_MODE_TIMEOUT_SECONDS")
    agent_mode_max_charts: int = Field(default=12, alias="AGENT_MODE_MAX_CHARTS")
    agent_mode_max_pages: int = Field(default=6, alias="AGENT_MODE_MAX_PAGES")
    web_search_enabled: bool = Field(default=False, alias="WEB_SEARCH_ENABLED")
    web_search_provider: str = Field(default="bocha", alias="WEB_SEARCH_PROVIDER")
    web_search_api_key: str = Field(default="", alias="WEB_SEARCH_API_KEY")
    web_search_max_results: int = Field(default=8, alias="WEB_SEARCH_MAX_RESULTS")
    web_search_max_calls_per_turn: int = Field(default=5, alias="WEB_SEARCH_MAX_CALLS_PER_TURN")
    web_fetch_timeout_seconds: float = Field(default=15.0, alias="WEB_FETCH_TIMEOUT_SECONDS")
    web_fetch_max_bytes: int = Field(default=2097152, alias="WEB_FETCH_MAX_BYTES")
    web_fetch_max_chars: int = Field(default=20000, alias="WEB_FETCH_MAX_CHARS")
    public_assistant_cache_ttl_seconds: int = Field(default=30 * 60, alias="PUBLIC_ASSISTANT_CACHE_TTL_SECONDS")
    public_assistant_cache_max_entries: int = Field(default=10, alias="PUBLIC_ASSISTANT_CACHE_MAX_ENTRIES")
    public_assistant_max_query_rows: int = Field(default=200, alias="PUBLIC_ASSISTANT_MAX_QUERY_ROWS")
    multi_chart_generation_enabled: bool = Field(default=True, alias="MULTI_CHART_GENERATION_ENABLED")
    agent_max_multi_charts: int = Field(default=8, alias="AGENT_MAX_MULTI_CHARTS")
    multi_chart_confirmation_ttl_seconds: int = Field(default=900, alias="MULTI_CHART_CONFIRMATION_TTL_SECONDS")
    ingestion_plan_timeout_seconds: float = Field(default=600.0, alias="INGESTION_PLAN_TIMEOUT_SECONDS")
    auth_secret: str = Field(alias="AUTH_SECRET")
    user_accounts_enabled: bool = Field(default=True, alias="USER_ACCOUNTS_ENABLED")
    auth_registration_enabled: bool = Field(default=True, alias="AUTH_REGISTRATION_ENABLED")
    password_min_length: int = Field(default=8, alias="PASSWORD_MIN_LENGTH")
    access_token_ttl_min: int = Field(default=120, alias="ACCESS_TOKEN_TTL_MIN")
    invite_link_ttl_days: int = Field(default=14, alias="INVITE_LINK_TTL_DAYS")
    # Credential-free service-token login. Off by default and ignored entirely
    # when APP_ENV=production: the endpoint issues a token for any role the
    # caller asks for, so an exposed instance would hand out `superadmin`.
    legacy_service_login_enabled: bool = Field(default=False, alias="LEGACY_SERVICE_LOGIN_ENABLED")
    # Carries a default so a deployment that configures nothing still ends up
    # with an account somebody can log in with; set it empty to opt out of
    # bootstrapping. An empty password is not a disable switch — one is
    # generated and logged once (see `_bootstrap_admin`), because a hardcoded
    # default credential would be public to everyone who can read this repo.
    auth_bootstrap_admin_email: str = Field(
        default=DEFAULT_BOOTSTRAP_ADMIN_EMAIL, alias="AUTH_BOOTSTRAP_ADMIN_EMAIL"
    )
    auth_bootstrap_admin_password: str = Field(default="", alias="AUTH_BOOTSTRAP_ADMIN_PASSWORD")
    auth_bootstrap_superadmin_email: str = Field(default="", alias="AUTH_BOOTSTRAP_SUPERADMIN_EMAIL")
    agent_skills_enabled: bool = Field(default=False, alias="AGENT_SKILLS_ENABLED")
    agent_skills_dir: str = Field(default="", alias="AGENT_SKILLS_DIR")
    agent_skills_max_upload_mb: int = Field(default=25, alias="AGENT_SKILLS_MAX_UPLOAD_MB")
    admin_usage_retention_days: int = Field(default=180, alias="ADMIN_USAGE_RETENTION_DAYS")
    legacy_xlsx_parser_enabled: bool = Field(default=True, alias="LEGACY_XLSX_PARSER_ENABLED")
    app_url: str = Field(default="http://localhost:3000", alias="APP_URL")
    public_base_url: str = Field(default="", alias="PUBLIC_BASE_URL")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    upload_dir: Path = Field(alias="UPLOAD_DIR")
    cors_allow_origins: str = Field(
        default="http://127.0.0.1:3000,http://localhost:3000",
        alias="CORS_ALLOW_ORIGINS",
    )

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        upper = value.upper()
        if upper not in LOG_LEVELS:
            allowed = ", ".join(sorted(LOG_LEVELS))
            raise ValueError(f"LOG_LEVEL must be one of: {allowed}")
        return upper

    @field_validator("upload_dir")
    @classmethod
    def normalize_upload_dir(cls, value: Path) -> Path:
        if value.is_absolute():
            return value
        return (Path(__file__).resolve().parent / value).resolve()

    @field_validator("ai_timeout_seconds")
    @classmethod
    def validate_ai_timeout_seconds(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("AI_TIMEOUT_SECONDS must be greater than 0")
        return value

    @field_validator("api_timeout_ms")
    @classmethod
    def validate_api_timeout_ms(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("API_TIMEOUT_MS must be greater than 0")
        return value

    @field_validator("sqlite_busy_timeout_ms")
    @classmethod
    def validate_sqlite_busy_timeout_ms(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("SQLITE_BUSY_TIMEOUT_MS must be greater than 0")
        return value

    @field_validator(
        "agent_timeout_seconds",
        "ingestion_plan_timeout_seconds",
        "web_fetch_timeout_seconds",
        "agent_mode_timeout_seconds",
    )
    @classmethod
    def validate_agent_timeout_seconds(cls, value: float) -> float:
        if value <= 0:
            raise ValueError(
                "AGENT_TIMEOUT_SECONDS / INGESTION_PLAN_TIMEOUT_SECONDS / WEB_FETCH_TIMEOUT_SECONDS / "
                "AGENT_MODE_TIMEOUT_SECONDS must be greater than 0"
            )
        return value

    @field_validator("web_search_provider")
    @classmethod
    def validate_web_search_provider(cls, value: str) -> str:
        normalized = str(value or "").strip().lower()
        allowed = {"bocha", "tavily"}
        if normalized not in allowed:
            raise ValueError(f"WEB_SEARCH_PROVIDER must be one of: {', '.join(sorted(allowed))}")
        return normalized

    @field_validator(
        "agent_max_tool_steps",
        "agent_max_sql_rows",
        "agent_max_sql_scan_rows",
        "public_assistant_cache_ttl_seconds",
        "public_assistant_cache_max_entries",
        "public_assistant_max_query_rows",
        "agent_max_multi_charts",
        "multi_chart_confirmation_ttl_seconds",
        "web_search_max_results",
        "web_search_max_calls_per_turn",
        "web_fetch_max_bytes",
        "web_fetch_max_chars",
        "agent_mode_max_steps",
        "agent_mode_outline_max_steps",
        "agent_mode_max_charts",
        "agent_mode_max_pages",
        "admin_usage_retention_days",
        "model_router_failure_threshold",
        "model_router_cooldown_seconds",
        "model_router_slow_ttft_ms",
    )
    @classmethod
    def validate_positive_ints(cls, value: int, info) -> int:  # type: ignore[no-untyped-def]
        if value <= 0:
            field_name = str(info.field_name).upper()
            raise ValueError(f"{field_name} must be greater than 0")
        return value

    @field_validator("model_router_first_token_deadline_ms")
    @classmethod
    def validate_first_token_deadline(cls, value: int) -> int:
        # 0 means "never preempt". Any non-zero value below the floor would
        # abandon healthy runs: CLI spawn plus a gateway handshake alone costs
        # seconds before the first token can possibly arrive.
        if value and not (
            FIRST_TOKEN_DEADLINE_FLOOR_MS <= value <= FIRST_TOKEN_DEADLINE_CEILING_MS
        ):
            raise ValueError(
                "MODEL_ROUTER_FIRST_TOKEN_DEADLINE_MS must be 0 (disabled) or between "
                f"{FIRST_TOKEN_DEADLINE_FLOOR_MS} and {FIRST_TOKEN_DEADLINE_CEILING_MS}"
            )
        if value < 0:
            raise ValueError("MODEL_ROUTER_FIRST_TOKEN_DEADLINE_MS must not be negative")
        return value

    @field_validator("agent_skills_max_upload_mb")
    @classmethod
    def validate_agent_skills_max_upload_mb(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("AGENT_SKILLS_MAX_UPLOAD_MB must be greater than 0")
        return value

    @model_validator(mode="after")
    def validate_agent_engine_sdk_toggle(self) -> "Settings":
        if not self.claude_agent_sdk_enabled:
            raise ValueError("CLAUDE_AGENT_SDK_ENABLED must be true for Agent runtime")
        if (
            self.app_env.strip().lower() == "production"
            and self.auth_bootstrap_admin_password == DEFAULT_DEVELOPMENT_ADMIN_PASSWORD
        ):
            raise ValueError(
                "The documented development Admin password cannot be used when APP_ENV=production"
            )
        # An empty or placeholder signing key still produces valid-looking JWTs,
        # so a misconfigured deployment fails open: anyone can mint a token for
        # any role. Refuse to boot instead of serving with a known key.
        if self.app_env.strip().lower() == "production" and (
            not self.auth_secret.strip() or self.auth_secret in PUBLIC_PLACEHOLDER_SECRETS
        ):
            raise ValueError(
                "AUTH_SECRET must be a non-empty, deployment-specific value when "
                "APP_ENV=production (generate one with `openssl rand -hex 32`, or "
                "run scripts/deploy.sh which does it for you)"
            )
        return self

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.cors_allow_origins.split(",") if item.strip()]

    @property
    def resolved_agent_skills_dir(self) -> Path:
        raw = (self.agent_skills_dir or "").strip()
        if not raw:
            return (self.upload_dir / "agent_skills").resolve()
        candidate = Path(raw).expanduser()
        if candidate.is_absolute():
            return candidate.resolve()
        return (Path(__file__).resolve().parent / candidate).resolve()


def get_bootstrap_settings() -> Settings:
    env_file_override = os.getenv("API_ENV_FILE")
    env_file = (
        Path(env_file_override).expanduser().resolve()
        if env_file_override
        else DEFAULT_ENV_FILE_PATH
    )
    try:
        return Settings(_env_file=env_file)
    except ValidationError as exc:
        raise RuntimeError(f"Invalid API configuration: {exc}") from exc


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return validated effective settings (environment plus admin overrides).

    The bootstrap upload directory deliberately remains the control database
    anchor, so even an overridden UPLOAD_DIR can be found again after restart.
    """

    base = get_bootstrap_settings()
    try:
        from .admin_store import get_admin_store

        overrides = get_admin_store(base.upload_dir).load_overrides()
    except (OSError, sqlite3.Error):
        overrides = {}
    if not overrides:
        return base

    declared_aliases = {
        str(field.alias or name)
        for name, field in Settings.model_fields.items()
    }
    safe_overrides = {
        key: value for key, value in overrides.items() if key in declared_aliases
    }
    try:
        return Settings(
            _env_file=None,
            **{
                **base.model_dump(by_alias=True),
                **safe_overrides,
            },
        )
    except ValidationError as exc:
        raise RuntimeError(f"Invalid persisted API configuration: {exc}") from exc
