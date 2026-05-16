from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_ENV_FILE_PATH = Path(__file__).resolve().parent / ".env"
LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class Settings(BaseSettings):
    app_name: str = Field(default="Cognitrix API", alias="APP_NAME")
    app_env: str = Field(default="development", alias="APP_ENV")
    database_url: str = Field(alias="DATABASE_URL")
    model_provider_url: str = Field(alias="MODEL_PROVIDER_URL")
    ai_api_key: str = Field(default="", alias="AI_API_KEY")
    ai_model: str = Field(default="deepseek-chat", alias="AI_MODEL")
    ai_timeout_seconds: float = Field(default=20.0, alias="AI_TIMEOUT_SECONDS")
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
    auth_secret: str = Field(alias="AUTH_SECRET")
    user_accounts_enabled: bool = Field(default=True, alias="USER_ACCOUNTS_ENABLED")
    auth_registration_enabled: bool = Field(default=True, alias="AUTH_REGISTRATION_ENABLED")
    password_min_length: int = Field(default=8, alias="PASSWORD_MIN_LENGTH")
    access_token_ttl_min: int = Field(default=120, alias="ACCESS_TOKEN_TTL_MIN")
    invite_link_ttl_days: int = Field(default=14, alias="INVITE_LINK_TTL_DAYS")
    legacy_service_login_enabled: bool = Field(default=True, alias="LEGACY_SERVICE_LOGIN_ENABLED")
    auth_bootstrap_admin_email: str = Field(default="", alias="AUTH_BOOTSTRAP_ADMIN_EMAIL")
    auth_bootstrap_admin_password: str = Field(default="", alias="AUTH_BOOTSTRAP_ADMIN_PASSWORD")
    auth_bootstrap_superadmin_email: str = Field(default="", alias="AUTH_BOOTSTRAP_SUPERADMIN_EMAIL")
    agent_skills_enabled: bool = Field(default=False, alias="AGENT_SKILLS_ENABLED")
    agent_skills_dir: str = Field(default="", alias="AGENT_SKILLS_DIR")
    agent_skills_max_upload_mb: int = Field(default=25, alias="AGENT_SKILLS_MAX_UPLOAD_MB")
    legacy_xlsx_parser_enabled: bool = Field(default=True, alias="LEGACY_XLSX_PARSER_ENABLED")
    app_url: str = Field(default="http://localhost:3000", alias="APP_URL")
    log_level: str = Field(alias="LOG_LEVEL")
    upload_dir: Path = Field(alias="UPLOAD_DIR")
    cors_allow_origins: str = Field(
        default="http://127.0.0.1:3000,http://localhost:3000",
        alias="CORS_ALLOW_ORIGINS",
    )

    model_config = SettingsConfigDict(env_file_encoding="utf-8", extra="ignore")

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

    @field_validator("agent_timeout_seconds")
    @classmethod
    def validate_agent_timeout_seconds(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("AGENT_TIMEOUT_SECONDS must be greater than 0")
        return value

    @field_validator("agent_max_tool_steps", "agent_max_sql_rows", "agent_max_sql_scan_rows")
    @classmethod
    def validate_positive_ints(cls, value: int, info) -> int:  # type: ignore[no-untyped-def]
        if value <= 0:
            field_name = str(info.field_name).upper()
            raise ValueError(f"{field_name} must be greater than 0")
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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
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
