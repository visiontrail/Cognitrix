from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.config import get_settings
from apps.api.main import app
from tests.auth_utils import auth_headers


def _set_minimal_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/db")
    monkeypatch.setenv("MODEL_PROVIDER_URL", "http://localhost:11434")
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    get_settings.cache_clear()


def test_chat_title_endpoint_returns_generated_title(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path)

    class _FakeTitleService:
        """Mirrors SessionTitleService.generate_title, including the locale kwarg."""

        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def generate_title(self, prompt: str, *, locale: str = "en") -> tuple[str, str]:
            self.calls.append((prompt, locale))
            return "员工离职趋势分析", "ai"

    fake_service = _FakeTitleService()
    monkeypatch.setattr("apps.api.main.get_session_title_service", lambda: fake_service)

    with TestClient(app) as client:
        headers = auth_headers(
            client,
            user_id="alice",
            project_id="north",
            role="viewer",
            department="HR",
            clearance=1,
        )
        response = client.post(
            "/chat/title",
            json={
                "user_id": "alice",
                "project_id": "north",
                "prompt": "请帮我分析最近 12 个月不同部门的离职趋势和波动原因",
                "locale": "zh-CN",
            },
            headers=headers,
        )

    assert response.status_code == 200
    assert response.json() == {"title": "员工离职趋势分析", "source": "ai"}
    # The requested locale must reach the title service, not just the prompt.
    assert fake_service.calls == [("请帮我分析最近 12 个月不同部门的离职趋势和波动原因", "zh-CN")]
