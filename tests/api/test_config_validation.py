from __future__ import annotations

import pytest

from apps.api.config import get_settings


@pytest.mark.parametrize(
    "missing_key",
    [
        # MODEL_PROVIDER_URL and LOG_LEVEL deliberately carry defaults: an
        # orchestrated deployment should only have to supply the values that
        # cannot be guessed safely. The storage locations and the signing key
        # stay required — a wrong guess there loses data or fails open.
        "DATABASE_URL",
        "AUTH_SECRET",
        "UPLOAD_DIR",
    ],
)
def test_missing_required_env_raises_runtime_error(monkeypatch, missing_key: str, tmp_path) -> None:
    env_file = tmp_path / "api.env"
    env_lines = {
        "DATABASE_URL": "postgresql://user:pass@localhost:5432/db",
        "MODEL_PROVIDER_URL": "http://localhost:11434",
        "AUTH_SECRET": "secret",
        "LOG_LEVEL": "INFO",
        "UPLOAD_DIR": "./uploads",
    }
    env_lines.pop(missing_key)
    env_file.write_text(
        "\n".join(f"{key}={value}" for key, value in env_lines.items()),
        encoding="utf-8",
    )

    monkeypatch.setenv("API_ENV_FILE", str(env_file))
    for key in ["DATABASE_URL", "MODEL_PROVIDER_URL", "AUTH_SECRET", "LOG_LEVEL", "UPLOAD_DIR"]:
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()

    with pytest.raises(RuntimeError):
        get_settings()


def test_optional_ai_settings_are_loaded_from_env_file(monkeypatch, tmp_path) -> None:
    env_file = tmp_path / "api.env"
    env_file.write_text(
        "\n".join(
            [
                "DATABASE_URL=postgresql://user:pass@localhost:5432/db",
                "MODEL_PROVIDER_URL=https://api.openai.com",
                "AI_API_KEY=test-api-key",
                "AI_MODEL=qwen-plus",
                "AI_TIMEOUT_SECONDS=12",
                "ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic",
                "ANTHROPIC_AUTH_TOKEN=deepseek-agent-key",
                "ANTHROPIC_DEFAULT_HAIKU_MODEL=deepseek-chat",
                "API_TIMEOUT_MS=600000",
                "AGENTIC_INGESTION_ENABLED=true",
                "AUTH_SECRET=secret",
                "LOG_LEVEL=INFO",
                "UPLOAD_DIR=./uploads",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("API_ENV_FILE", str(env_file))
    for key in [
        "DATABASE_URL",
        "MODEL_PROVIDER_URL",
        "AI_API_KEY",
        "AI_MODEL",
        "AI_TIMEOUT_SECONDS",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL",
        "API_TIMEOUT_MS",
        "AUTH_SECRET",
        "LOG_LEVEL",
        "UPLOAD_DIR",
    ]:
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.ai_api_key == "test-api-key"
    assert settings.ai_model == "qwen-plus"
    assert settings.ai_timeout_seconds == 12
    assert settings.anthropic_base_url == "https://api.deepseek.com/anthropic"
    assert settings.anthropic_auth_token == "deepseek-agent-key"
    assert settings.anthropic_default_haiku_model == "deepseek-chat"
    assert settings.api_timeout_ms == 600000
    assert settings.agentic_ingestion_enabled is True


def test_agent_engine_requires_claude_agent_sdk_toggle(monkeypatch, tmp_path) -> None:
    env_file = tmp_path / "api.env"
    env_file.write_text(
        "\n".join(
            [
                "DATABASE_URL=postgresql://user:pass@localhost:5432/db",
                "MODEL_PROVIDER_URL=https://api.openai.com",
                "CLAUDE_AGENT_SDK_ENABLED=false",
                "AUTH_SECRET=secret",
                "LOG_LEVEL=INFO",
                "UPLOAD_DIR=./uploads",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("API_ENV_FILE", str(env_file))
    for key in [
        "DATABASE_URL",
        "MODEL_PROVIDER_URL",
        "CLAUDE_AGENT_SDK_ENABLED",
        "AUTH_SECRET",
        "LOG_LEVEL",
        "UPLOAD_DIR",
    ]:
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()

    with pytest.raises(RuntimeError):
        get_settings()


def _write_env(tmp_path, monkeypatch, **overrides) -> None:
    """Write an env file and clear the matching process env.

    An override of ``None`` omits the key entirely, so the field falls through
    to its default — that is what the K8s-minimal-manifest tests exercise.
    """

    values = {
        "DATABASE_URL": "sqlite:///./state.sqlite3",
        "MODEL_PROVIDER_URL": "https://api.deepseek.com",
        "CLAUDE_AGENT_SDK_ENABLED": "true",
        "AUTH_SECRET": "a" * 64,
        "LOG_LEVEL": "INFO",
        "UPLOAD_DIR": "./uploads",
        "APP_ENV": "production",
    }
    values.update(overrides)
    omitted = [key for key, value in values.items() if value is None]
    for key in omitted:
        values.pop(key)
    env_file = tmp_path / "api.env"
    env_file.write_text(
        "\n".join(f"{key}={value}" for key, value in values.items()), encoding="utf-8"
    )
    monkeypatch.setenv("API_ENV_FILE", str(env_file))
    for key in list(values) + omitted:
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()


@pytest.mark.parametrize(
    "auth_secret",
    [
        "",
        "replace-with-a-strong-secret",
        "dd904b50ad26343d430462093f66bedc79ec0be5db9c93422fa424ca0781f5d8",
    ],
)
def test_public_auth_secret_rejected_in_production(monkeypatch, tmp_path, auth_secret) -> None:
    """An empty or repository-known signing key must never boot in production.

    Such a key still signs structurally valid JWTs, so the deployment fails open:
    anyone able to read the template can mint a token for any role.
    """

    _write_env(tmp_path, monkeypatch, AUTH_SECRET=auth_secret)

    with pytest.raises(RuntimeError, match="AUTH_SECRET"):
        get_settings()


def test_public_auth_secret_allowed_outside_production(monkeypatch, tmp_path) -> None:
    _write_env(tmp_path, monkeypatch, APP_ENV="development", AUTH_SECRET="")

    assert get_settings().auth_secret == ""


@pytest.mark.parametrize(
    ("key", "expected"),
    [("MODEL_PROVIDER_URL", "https://api.deepseek.com"), ("LOG_LEVEL", "INFO")],
)
def test_defaulted_keys_do_not_block_startup(monkeypatch, tmp_path, key, expected) -> None:
    """A K8s manifest should only have to carry AUTH_SECRET.

    The container image supplies DATABASE_URL and UPLOAD_DIR (they name paths
    that must line up with the mounted volume), which leaves these two to fall
    back to their defaults.
    """

    _write_env(tmp_path, monkeypatch, **{key: None})
    settings = get_settings()

    assert getattr(settings, key.lower()) == expected
