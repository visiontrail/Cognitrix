from __future__ import annotations

import logging
from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.config import get_settings
from apps.api.main import HealthzAccessLogFilter, app, configure_application_logging


def _set_minimal_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("APP_NAME", "Cognitrix API")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/db")
    monkeypatch.setenv("MODEL_PROVIDER_URL", "http://localhost:11434")
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))


def test_healthz_success(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path)
    get_settings.cache_clear()

    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "Cognitrix API"
    assert payload["environment"] == "development"
    assert (tmp_path / "uploads").exists()


def test_configure_application_logging_binds_cognitrix_logger_to_uvicorn_handler() -> None:
    app_logger = logging.getLogger("cognitrix")
    uvicorn_logger = logging.getLogger("uvicorn.error")
    access_logger = logging.getLogger("uvicorn.access")
    original_app_handlers = list(app_logger.handlers)
    original_app_level = app_logger.level
    original_app_propagate = app_logger.propagate
    original_uvicorn_handlers = list(uvicorn_logger.handlers)
    original_access_filters = list(access_logger.filters)

    handler = logging.StreamHandler()
    uvicorn_logger.handlers = [handler]
    access_logger.filters = []

    try:
        configure_application_logging("INFO")
        assert app_logger.level == logging.INFO
        assert app_logger.handlers == [handler]
        assert app_logger.propagate is False
        assert sum(isinstance(item, HealthzAccessLogFilter) for item in access_logger.filters) == 1

        configure_application_logging("INFO")
        assert sum(isinstance(item, HealthzAccessLogFilter) for item in access_logger.filters) == 1
    finally:
        app_logger.handlers = original_app_handlers
        app_logger.setLevel(original_app_level)
        app_logger.propagate = original_app_propagate
        uvicorn_logger.handlers = original_uvicorn_handlers
        access_logger.filters = original_access_filters


def test_healthz_access_log_filter_only_suppresses_successful_health_checks() -> None:
    healthz_record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:12345", "GET", "/healthz", "1.1", 200),
        exc_info=None,
    )
    failed_healthz_record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:12345", "GET", "/healthz", "1.1", 503),
        exc_info=None,
    )
    api_record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:12345", "GET", "/workspaces", "1.1", 200),
        exc_info=None,
    )

    log_filter = HealthzAccessLogFilter()

    assert log_filter.filter(healthz_record) is False
    assert log_filter.filter(failed_healthz_record) is True
    assert log_filter.filter(api_record) is True
