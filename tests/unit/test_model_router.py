from __future__ import annotations

from types import SimpleNamespace

from apps.api.agent_runtime import build_sdk_provider_env
from apps.api.model_router import ModelRouter


def _settings(**updates):  # type: ignore[no-untyped-def]
    values = {
        "model_primary_provider": "yinhe",
        "model_provider_url": "https://oneapi.yhroot.com",
        "anthropic_base_url": "https://oneapi.yhroot.com",
        "anthropic_auth_token": "primary-secret",
        "ai_api_key": "",
        "ai_model": "yinhe-thinking",
        "anthropic_default_haiku_model": "yinhe-chat",
        "api_timeout_ms": 600000,
        "model_backup_enabled": True,
        "model_backup_provider": "deepseek",
        "model_backup_url": "https://backup.test",
        "model_backup_anthropic_url": "https://backup.test/anthropic",
        "model_backup_api_key": "backup-secret",
        "model_backup_model": "backup-model",
        "model_backup_fast_model": "backup-fast",
        "model_router_enabled": True,
        "model_router_failure_threshold": 2,
        "model_router_cooldown_seconds": 60,
        "model_router_slow_ttft_ms": 15000,
    }
    values.update(updates)
    return SimpleNamespace(**values)


def test_primary_is_preferred_and_endpoint_is_pinned_into_sdk_env() -> None:
    settings = _settings()
    router = ModelRouter()

    candidates = router.candidates(protocol="anthropic", settings=settings)

    assert [item.slot for item in candidates] == ["primary", "backup"]
    env, model = build_sdk_provider_env(settings, endpoint=candidates[0])
    assert model == "yinhe-thinking"
    assert env["ANTHROPIC_BASE_URL"] == "https://oneapi.yhroot.com"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "primary-secret"
    assert env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "yinhe-chat"


def test_circuit_breaker_routes_to_backup_after_primary_failures() -> None:
    settings = _settings()
    router = ModelRouter()
    primary = router.candidates(protocol="anthropic", settings=settings)[0]

    router.record(primary, ok=False, error_kind="ConnectError", settings=settings)
    assert router.snapshot(settings)["serving_slot"] == "primary"

    router.record(primary, ok=False, error_kind="TimeoutError", settings=settings)

    assert [item.slot for item in router.candidates(protocol="anthropic", settings=settings)] == [
        "backup",
        "primary",
    ]
    snapshot = router.snapshot(settings)
    assert snapshot["primary_breaker_open"] is True
    assert snapshot["serving_slot"] == "backup"


def test_disabled_backup_never_receives_traffic() -> None:
    settings = _settings(model_backup_enabled=False)
    router = ModelRouter()

    assert [item.slot for item in router.candidates(protocol="anthropic", settings=settings)] == [
        "primary"
    ]

