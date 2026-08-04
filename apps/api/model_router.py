from __future__ import annotations

import time
from collections import deque
from dataclasses import asdict, dataclass
from threading import Lock
from typing import Any, Literal


@dataclass(frozen=True)
class ProviderProfile:
    name: str
    label: str
    default_openai_url: str
    default_anthropic_url: str
    default_model: str
    default_fast_model: str
    models: tuple[str, ...]
    notes: str


# This catalogue intentionally mirrors RavenAIService's provider profiles. Model
# ids remain presets rather than a whitelist, so administrators can use a newly
# released model immediately through the free-text option in the UI.
PROVIDER_PROFILES: dict[str, ProviderProfile] = {
    "yinhe": ProviderProfile(
        name="yinhe",
        label="银河内部模型（OneAPI）",
        default_openai_url="https://oneapi.yhroot.com",
        default_anthropic_url="https://oneapi.yhroot.com",
        default_model="yinhe-thinking",
        default_fast_model="yinhe-chat",
        models=("yinhe-thinking", "yinhe-chat"),
        notes="公司内部统一网关；优先用于 CogniTrix 主力模型。",
    ),
    "deepseek": ProviderProfile(
        name="deepseek",
        label="DeepSeek 深度求索",
        default_openai_url="https://api.deepseek.com",
        default_anthropic_url="https://api.deepseek.com/anthropic",
        default_model="deepseek-chat",
        default_fast_model="deepseek-chat",
        models=("deepseek-chat", "deepseek-reasoner"),
        notes="OpenAI 与 Anthropic 兼容端点。",
    ),
    "anthropic": ProviderProfile(
        name="anthropic",
        label="Anthropic 官方",
        default_openai_url="",
        default_anthropic_url="https://api.anthropic.com",
        default_model="claude-sonnet-4-6",
        default_fast_model="claude-haiku-4-5-20251001",
        models=(
            "claude-opus-4-6",
            "claude-sonnet-4-6",
            "claude-haiku-4-5-20251001",
        ),
        notes="原生 Anthropic Messages API。",
    ),
    "aliyun": ProviderProfile(
        name="aliyun",
        label="阿里云百炼 / 通义千问",
        default_openai_url="",
        default_anthropic_url=(
            "https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/apps/anthropic"
        ),
        default_model="qwen3.7-max",
        default_fast_model="qwen3.7-flash",
        models=("qwen3.7-max", "qwen3.7-plus", "qwen3.7-flash", "qwen3-coder-next"),
        notes="Base URL 中的 WorkspaceId 必须由管理员替换。",
    ),
    "zhipu": ProviderProfile(
        name="zhipu",
        label="智谱 AI / GLM",
        default_openai_url="",
        default_anthropic_url="https://open.bigmodel.cn/api/anthropic",
        default_model="glm-5.2",
        default_fast_model="glm-5.2",
        models=("glm-5.2",),
        notes="Anthropic 兼容端点。",
    ),
    "moonshot": ProviderProfile(
        name="moonshot",
        label="月之暗面 / Kimi",
        default_openai_url="",
        default_anthropic_url="https://api.moonshot.cn/anthropic",
        default_model="kimi-k3",
        default_fast_model="kimi-k2.7-code-highspeed",
        models=("kimi-k3", "kimi-k2.7-code", "kimi-k2.7-code-highspeed", "kimi-k2.6"),
        notes="Anthropic 兼容端点。",
    ),
    "minimax": ProviderProfile(
        name="minimax",
        label="MiniMax 稀宇科技",
        default_openai_url="",
        default_anthropic_url="https://api.minimaxi.com/anthropic",
        default_model="MiniMax-M3",
        default_fast_model="MiniMax-M2.5",
        models=("MiniMax-M3", "MiniMax-M2.7", "MiniMax-M2.5"),
        notes="Anthropic 兼容端点。",
    ),
    "stepfun": ProviderProfile(
        name="stepfun",
        label="阶跃星辰 StepFun",
        default_openai_url="",
        default_anthropic_url="https://api.stepfun.com",
        default_model="step-3.7-flash",
        default_fast_model="step-3.5-flash",
        models=("step-3.7-flash", "step-3.5-flash-2603", "step-3.5-flash"),
        notes="Anthropic 兼容端点。",
    ),
    "mimo": ProviderProfile(
        name="mimo",
        label="小米 MiMo",
        default_openai_url="",
        default_anthropic_url="https://api.xiaomimimo.com/anthropic",
        default_model="mimo-v2.5-pro",
        default_fast_model="mimo-v2.5",
        models=("mimo-v2.5-pro", "mimo-v2.5"),
        notes="Anthropic 兼容端点。",
    ),
    "hunyuan": ProviderProfile(
        name="hunyuan",
        label="腾讯混元",
        default_openai_url="",
        default_anthropic_url="https://api.hunyuan.cloud.tencent.com/anthropic",
        default_model="hunyuan-2.0-thinking-20251109",
        default_fast_model="hunyuan-2.0-instruct-20251111",
        models=("hunyuan-2.0-thinking-20251109", "hunyuan-2.0-instruct-20251111"),
        notes="Anthropic 兼容端点。",
    ),
    "custom": ProviderProfile(
        name="custom",
        label="自定义兼容端点",
        default_openai_url="",
        default_anthropic_url="",
        default_model="",
        default_fast_model="",
        models=(),
        notes="URL 与模型均由管理员填写。",
    ),
}


@dataclass(frozen=True)
class ModelEndpoint:
    slot: Literal["primary", "backup"]
    provider: str
    openai_url: str
    anthropic_url: str
    api_key: str
    model: str
    fast_model: str

    def supports(self, protocol: Literal["openai", "anthropic"]) -> bool:
        return bool(self.openai_url if protocol == "openai" else self.anthropic_url)

    def public_dict(self) -> dict[str, Any]:
        return {
            "slot": self.slot,
            "provider": self.provider,
            "openai_url": self.openai_url,
            "anthropic_url": self.anthropic_url,
            "model": self.model,
            "fast_model": self.fast_model,
            "api_key_configured": bool(self.api_key),
            "configured": bool(self.api_key and self.model and self.anthropic_url),
        }


def provider_profiles_payload() -> list[dict[str, Any]]:
    return [
        {**asdict(profile), "models": list(profile.models)}
        for profile in PROVIDER_PROFILES.values()
    ]


class ModelRouter:
    """Primary-first router with safe pre-output failover and a circuit breaker."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._failures: dict[str, int] = {"primary": 0, "backup": 0}
        self._breaker_until = 0.0
        self._samples: dict[str, deque[dict[str, Any]]] = {
            "primary": deque(maxlen=20),
            "backup": deque(maxlen=20),
        }

    def endpoints(self, settings: Any | None = None) -> dict[str, ModelEndpoint | None]:
        if settings is None:
            from .config import get_settings

            settings = get_settings()

        primary_provider = str(settings.model_primary_provider or "custom").strip().lower()
        primary_profile = PROVIDER_PROFILES.get(primary_provider, PROVIDER_PROFILES["custom"])
        primary = ModelEndpoint(
            slot="primary",
            provider=primary_provider,
            openai_url=str(settings.model_provider_url or primary_profile.default_openai_url).strip().rstrip("/"),
            anthropic_url=str(settings.anthropic_base_url or primary_profile.default_anthropic_url).strip().rstrip("/"),
            api_key=str(settings.anthropic_auth_token or settings.ai_api_key or "").strip(),
            model=str(settings.ai_model or primary_profile.default_model).strip(),
            fast_model=str(settings.anthropic_default_haiku_model or primary_profile.default_fast_model or settings.ai_model).strip(),
        )

        backup_provider = str(settings.model_backup_provider or "custom").strip().lower()
        backup_profile = PROVIDER_PROFILES.get(backup_provider, PROVIDER_PROFILES["custom"])
        backup = ModelEndpoint(
            slot="backup",
            provider=backup_provider,
            openai_url=str(settings.model_backup_url or backup_profile.default_openai_url).strip().rstrip("/"),
            anthropic_url=str(settings.model_backup_anthropic_url or backup_profile.default_anthropic_url).strip().rstrip("/"),
            api_key=str(settings.model_backup_api_key or "").strip(),
            model=str(settings.model_backup_model or backup_profile.default_model).strip(),
            fast_model=str(settings.model_backup_fast_model or backup_profile.default_fast_model or settings.model_backup_model).strip(),
        )
        return {"primary": primary, "backup": backup}

    def candidates(
        self,
        *,
        protocol: Literal["openai", "anthropic"] = "anthropic",
        settings: Any | None = None,
    ) -> list[ModelEndpoint]:
        if settings is None:
            from .config import get_settings

            settings = get_settings()
        endpoints = self.endpoints(settings)
        primary = endpoints["primary"]
        backup = endpoints["backup"]
        ordered = (primary, backup) if settings.model_backup_enabled else (primary,)
        available = [
            endpoint
            for endpoint in ordered
            if endpoint is not None and endpoint.api_key and endpoint.model and endpoint.supports(protocol)
        ]
        if len(available) < 2:
            return available
        if not settings.model_router_enabled:
            return [available[0]]
        with self._lock:
            breaker_open = self._breaker_until > time.monotonic()
        return list(reversed(available)) if breaker_open else available

    def record(
        self,
        endpoint: ModelEndpoint,
        *,
        ok: bool,
        latency_ms: float | None = None,
        error_kind: str | None = None,
        settings: Any | None = None,
    ) -> None:
        if settings is None:
            from .config import get_settings

            settings = get_settings()
        slow = bool(ok and latency_ms is not None and latency_ms > settings.model_router_slow_ttft_ms)
        sample = {
            "ok": bool(ok),
            "slow": slow,
            "latency_ms": round(float(latency_ms), 2) if latency_ms is not None else None,
            "error_kind": error_kind,
            "at": int(time.time()),
        }
        with self._lock:
            self._samples[endpoint.slot].appendleft(sample)
            if ok and not slow:
                self._failures[endpoint.slot] = 0
                if endpoint.slot == "primary":
                    self._breaker_until = 0.0
                return
            self._failures[endpoint.slot] += 1
            if (
                endpoint.slot == "primary"
                and settings.model_router_enabled
                and self._failures[endpoint.slot] >= settings.model_router_failure_threshold
                and settings.model_backup_enabled
                and bool(self.endpoints(settings)["backup"].api_key)
            ):
                self._breaker_until = time.monotonic() + settings.model_router_cooldown_seconds

    def snapshot(self, settings: Any | None = None) -> dict[str, Any]:
        if settings is None:
            from .config import get_settings

            settings = get_settings()
        endpoints = self.endpoints(settings)
        with self._lock:
            remaining = max(0, int(self._breaker_until - time.monotonic()))
            samples = {slot: list(rows) for slot, rows in self._samples.items()}
            failures = dict(self._failures)
        return {
            "enabled": bool(settings.model_router_enabled),
            "serving_slot": "backup" if remaining and endpoints["backup"] else "primary",
            "primary_breaker_open": bool(remaining),
            "cooldown_remaining_seconds": remaining,
            "failure_threshold": settings.model_router_failure_threshold,
            "slow_ttft_ms": settings.model_router_slow_ttft_ms,
            "first_token_deadline_ms": int(
                getattr(settings, "model_router_first_token_deadline_ms", 0) or 0
            ),
            "slots": {
                slot: {
                    **(endpoint.public_dict() if endpoint else {"slot": slot, "configured": False}),
                    "consecutive_failures": failures[slot],
                    "samples": samples[slot],
                }
                for slot, endpoint in endpoints.items()
            },
        }

    def reset_health(self) -> None:
        with self._lock:
            self._failures = {"primary": 0, "backup": 0}
            self._breaker_until = 0.0
            for rows in self._samples.values():
                rows.clear()


_router = ModelRouter()


def get_model_router() -> ModelRouter:
    return _router
