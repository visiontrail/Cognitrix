from __future__ import annotations

import json
import logging
import re
import socket
import time
from functools import lru_cache
from urllib import error as urllib_error
from urllib import request as urllib_request

from .config import get_settings

logger = logging.getLogger("cognitrix.session_titles")

DEFAULT_SESSION_TITLE = "New Conversation"
SESSION_TITLE_MAX_LENGTH = 24


class SessionTitleService:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float,
    ) -> None:
        self.base_url = base_url.strip()
        self.api_key = api_key.strip()
        self.model = model.strip()
        self.timeout_seconds = timeout_seconds

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    def generate_title(self, prompt: str, *, locale: str = "en") -> tuple[str, str]:
        fallback_title = build_fallback_session_title(prompt)
        normalized_prompt = normalize_session_title(prompt, fallback_title)
        if not normalized_prompt:
            return fallback_title, "fallback"
        if not self.enabled:
            return fallback_title, "fallback"

        lang_instruction = (
            "Return the title in Chinese." if locale.startswith("zh") else "Return the title in English."
        )

        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You create concise conversation titles for a BI chat application. "
                        f"{lang_instruction} "
                        "Keep it specific, natural, and short. "
                        "Use at most 6 English words or 18 Chinese characters. "
                        "Do not add quotes, markdown, prefixes, or explanations."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "task": "Generate a short title for this conversation request.",
                            "message": prompt,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        }

        endpoint = _chat_completions_endpoint(self.base_url)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        request = urllib_request.Request(endpoint, data=body, headers=headers, method="POST")
        started_at = time.perf_counter()

        try:
            with urllib_request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except TimeoutError as exc:
            self._log_failure(endpoint=endpoint, prompt=prompt, error=exc, started_at=started_at)
            return fallback_title, "fallback"
        except socket.timeout as exc:
            self._log_failure(endpoint=endpoint, prompt=prompt, error=exc, started_at=started_at)
            return fallback_title, "fallback"
        except urllib_error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="ignore") if hasattr(exc, "read") else ""
            self._log_failure(
                endpoint=endpoint,
                prompt=prompt,
                error=exc,
                started_at=started_at,
                details=details,
            )
            return fallback_title, "fallback"
        except urllib_error.URLError as exc:
            self._log_failure(endpoint=endpoint, prompt=prompt, error=exc, started_at=started_at)
            return fallback_title, "fallback"

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            self._log_failure(endpoint=endpoint, prompt=prompt, error=exc, started_at=started_at, details=raw)
            return fallback_title, "fallback"

        content = _extract_message_content(data)
        title = normalize_session_title(content, fallback_title)
        return title, "ai" if title != fallback_title else "fallback"

    def _log_failure(
        self,
        *,
        endpoint: str,
        prompt: str,
        error: Exception,
        started_at: float,
        details: str | None = None,
    ) -> None:
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
        logger.warning(
            "session_title_generation_failed endpoint=%s elapsed_ms=%s error_type=%s error=%s prompt_preview=%s details=%s",
            endpoint,
            elapsed_ms,
            type(error).__name__,
            str(error),
            normalize_session_title(prompt, DEFAULT_SESSION_TITLE),
            details or "",
        )


def normalize_session_title(value: str, fallback: str = DEFAULT_SESSION_TITLE) -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "")).strip()
    cleaned = re.sub(r"^(title|标题)\s*[:：-]\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip("\"'`“”‘’ ")
    resolved = cleaned or fallback.strip() or DEFAULT_SESSION_TITLE
    characters = list(resolved)
    if len(characters) <= SESSION_TITLE_MAX_LENGTH:
        return resolved
    return "".join(characters[: SESSION_TITLE_MAX_LENGTH - 1]).rstrip() + "…"


def build_fallback_session_title(prompt: str) -> str:
    normalized = re.sub(r"\s+", " ", str(prompt or "")).strip()
    if not normalized:
        return DEFAULT_SESSION_TITLE

    sentence = re.split(r"[。！？!?；;\n]+", normalized, maxsplit=1)[0].strip()
    return normalize_session_title(sentence or normalized, DEFAULT_SESSION_TITLE)


def _extract_message_content(payload: dict[str, object]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""

    first = choices[0]
    if not isinstance(first, dict):
        return ""

    message = first.get("message")
    if not isinstance(message, dict):
        return ""

    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
        return " ".join(parts)
    return ""


def _chat_completions_endpoint(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    if normalized.endswith("/v1"):
        return f"{normalized}/chat/completions"
    return f"{normalized}/v1/chat/completions"


@lru_cache(maxsize=2)
def _cached_session_title_service(settings_key: str) -> SessionTitleService:
    _ = settings_key
    settings = get_settings()
    return SessionTitleService(
        base_url=settings.model_provider_url,
        api_key=settings.ai_api_key,
        model=settings.ai_model,
        timeout_seconds=settings.ai_timeout_seconds,
    )


def get_session_title_service() -> SessionTitleService:
    settings = get_settings()
    settings_key = "|".join(
        [
            settings.model_provider_url.strip(),
            settings.ai_model.strip(),
            "enabled" if bool(settings.ai_api_key.strip()) else "disabled",
        ]
    )
    return _cached_session_title_service(settings_key)


def clear_session_title_service_cache() -> None:
    _cached_session_title_service.cache_clear()
