"""Primary → backup endpoint failover inside the SDK turn.

Every test here pins the same boundary: an attempt is *uncommitted* until a
frame that required a model round trip arrives, and only an uncommitted attempt
may be abandoned for the next endpoint. CLI bookkeeping frames
(``SystemMessage(init)``, ``status``) are emitted before the gateway is ever
contacted, so counting them as model output silently kills both failover paths
— the error path re-raises instead of switching, and time-to-first-token
collapses to process-spawn time so no sample is ever slow.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import anyio
import pytest
from claude_agent_sdk import ResultMessage, SystemMessage
from fastapi.testclient import TestClient

from apps.api.agent_runtime import (
    AgentRequest,
    AgentRuntimeError,
    SDKAttemptState,
    drain_sdk_attempt_cleanups,
    get_agent_runtime,
)
from apps.api.main import app
from apps.api.model_router import get_model_router
from tests.agent_test_utils import set_agent_env, upload_dataset

FINAL_ANSWER = {
    "chart_type": "bar",
    "title": "入职年份统计",
    "x_key": "hire_year",
    "y_key": "metric_value",
    "series_key": None,
    "metric_name": "headcount",
    "rows": [{"hire_year": 2023, "metric_value": 2}],
    "conclusion": "按入职年份统计员工数。",
    "scope": "当前数据集",
    "anomalies": "none",
}


def _set_failover_env(monkeypatch, tmp_path: Path) -> None:
    set_agent_env(monkeypatch, tmp_path)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "primary-secret")
    monkeypatch.setenv("MODEL_BACKUP_ENABLED", "true")
    monkeypatch.setenv("MODEL_BACKUP_PROVIDER", "deepseek")
    monkeypatch.setenv("MODEL_BACKUP_ANTHROPIC_URL", "https://backup.test/anthropic")
    monkeypatch.setenv("MODEL_BACKUP_API_KEY", "backup-secret")
    monkeypatch.setenv("MODEL_BACKUP_MODEL", "backup-model")
    monkeypatch.setenv("MODEL_ROUTER_ENABLED", "true")

    from apps.api.config import get_settings
    from apps.api.agent_runtime import clear_agent_runtime_cache

    get_settings.cache_clear()
    clear_agent_runtime_cache()
    get_model_router().reset_health()


def _slot_of(options) -> str:  # type: ignore[no-untyped-def]
    """Which endpoint an attempt was built for, read off the pinned SDK env."""
    return "backup" if "backup.test" in str((options.env or {}).get("ANTHROPIC_BASE_URL", "")) else "primary"


def _result_message() -> ResultMessage:
    return ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id="session-failover",
        result="{}",
        structured_output=dict(FINAL_ANSWER),
    )


def _install_client(runtime, factory) -> None:  # type: ignore[no-untyped-def]
    runtime._sdk_client_factory = factory  # noqa: SLF001 - test seam


def _request(dataset_table: str, request_id: str) -> AgentRequest:
    return AgentRequest(
        conversation_id=f"failover-{request_id}",
        request_id=request_id,
        user_id="alice",
        project_id="north",
        dataset_table=dataset_table,
        message="柱状图显示入职年份统计",
        role="admin",
        department="HR",
        clearance=9,
    )


# ---------------------------------------------------------------------------
# Frame classification
# ---------------------------------------------------------------------------


def test_cli_bookkeeping_frames_never_commit_the_attempt() -> None:
    attempt = SDKAttemptState(started_at=0.0)

    attempt.observe(SystemMessage(subtype="init", data={"tools": []}))
    attempt.observe(SystemMessage(subtype="status", data={"state": "thinking"}))

    assert attempt.committed is False
    assert attempt.ttft_ms() is None

    attempt.observe(_result_message())

    assert attempt.committed is True
    assert attempt.ttft_ms() is not None


def test_init_frame_restarts_the_ttft_clock() -> None:
    attempt = SDKAttemptState(started_at=0.0)
    # A clock anchored at attempt start would bill CLI spawn and MCP setup to
    # the endpoint; anchored at init it measures only the gateway.
    attempt.observe(SystemMessage(subtype="init", data={}))
    spawn_end = attempt.started_at

    assert spawn_end > 0.0

    attempt.observe(_result_message())

    assert attempt.ttft_ms() is not None
    assert attempt.ttft_ms() < 1000  # not the whole (fake) spawn window


# ---------------------------------------------------------------------------
# Error failover
# ---------------------------------------------------------------------------


def test_failure_after_cli_init_still_fails_over_to_backup(monkeypatch, tmp_path: Path) -> None:
    _set_failover_env(monkeypatch, tmp_path)
    slots: list[str] = []

    class _InitThenFailPrimaryClient:
        def __init__(self, *, options):  # type: ignore[no-untyped-def]
            self.slot = _slot_of(options)
            slots.append(self.slot)

        async def __aenter__(self):  # type: ignore[no-untyped-def]
            return self

        async def __aexit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
            return False

        async def query(self, prompt: str, session_id: str = "default") -> None:
            return None

        async def receive_response(self):  # type: ignore[no-untyped-def]
            # The CLI subprocess starts fine even when the gateway is dead, so a
            # real failure always arrives *after* these frames.
            yield SystemMessage(subtype="init", data={"tools": []})
            yield SystemMessage(subtype="status", data={"state": "connecting"})
            if self.slot == "primary":
                raise RuntimeError("Connection error: primary gateway refused")
            yield _result_message()

    with TestClient(app) as client:
        dataset_table = upload_dataset(client, rows=[{"employee_id": "E-1", "hire_year": 2023}])
        runtime = get_agent_runtime()
        _install_client(runtime, _InitThenFailPrimaryClient)
        result = runtime.run_turn(_request(dataset_table, "req-error-failover"))

    assert slots == ["primary", "backup"]
    assert result.final_status == "completed"
    snapshot = get_model_router().snapshot()
    assert snapshot["slots"]["primary"]["consecutive_failures"] == 1
    assert snapshot["slots"]["primary"]["samples"][0]["error_kind"] == "RuntimeError"


def test_failure_after_model_output_is_not_retried(monkeypatch, tmp_path: Path) -> None:
    _set_failover_env(monkeypatch, tmp_path)
    slots: list[str] = []

    class _CommitThenFailClient:
        def __init__(self, *, options):  # type: ignore[no-untyped-def]
            slots.append(_slot_of(options))

        async def __aenter__(self):  # type: ignore[no-untyped-def]
            return self

        async def __aexit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
            return False

        async def query(self, prompt: str, session_id: str = "default") -> None:
            return None

        async def receive_response(self):  # type: ignore[no-untyped-def]
            yield SystemMessage(subtype="init", data={})
            yield _result_message()  # committed: tokens paid for, tools may have run
            raise RuntimeError("Connection error: dropped mid-stream")

    with TestClient(app) as client:
        dataset_table = upload_dataset(client, rows=[{"employee_id": "E-1", "hire_year": 2023}])
        runtime = get_agent_runtime()
        _install_client(runtime, _CommitThenFailClient)
        with pytest.raises(AgentRuntimeError):
            runtime.run_turn(_request(dataset_table, "req-committed"))

    # Replaying would re-run tool side effects and re-bill the tokens, so the
    # error belongs to the caller — not to the next endpoint.
    assert slots == ["primary"]


# ---------------------------------------------------------------------------
# First-token deadline
# ---------------------------------------------------------------------------


def test_slow_primary_is_preempted_and_backup_serves(monkeypatch, tmp_path: Path) -> None:
    _set_failover_env(monkeypatch, tmp_path)
    slots: list[str] = []
    closed: list[str] = []

    class _HangingPrimaryClient:
        def __init__(self, *, options):  # type: ignore[no-untyped-def]
            self.slot = _slot_of(options)
            slots.append(self.slot)

        async def __aenter__(self):  # type: ignore[no-untyped-def]
            return self

        async def __aexit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
            closed.append(self.slot)
            return False

        async def query(self, prompt: str, session_id: str = "default") -> None:
            return None

        async def receive_response(self):  # type: ignore[no-untyped-def]
            yield SystemMessage(subtype="init", data={})
            if self.slot == "primary":
                await asyncio.sleep(30)  # alive, but the model never answers
            yield _result_message()

    with TestClient(app) as client:
        dataset_table = upload_dataset(client, rows=[{"employee_id": "E-1", "hire_year": 2023}])
        runtime = get_agent_runtime()
        _install_client(runtime, _HangingPrimaryClient)
        runtime._first_token_deadline_seconds = lambda: 0.05  # noqa: SLF001 - test seam

        async def _run() -> object:
            turn = await runtime._run_turn_with_sdk(_request(dataset_table, "req-deadline"))  # noqa: SLF001
            await drain_sdk_attempt_cleanups(timeout=5.0)
            return turn

        result = anyio.run(_run)

    assert slots == ["primary", "backup"]
    # The abandoned attempt is reaped off the request path, so it may finish
    # closing after the backup has already answered — order is not guaranteed.
    assert sorted(closed) == ["backup", "primary"], "the abandoned attempt must be torn down"
    assert result.final_status == "completed"
    snapshot = get_model_router().snapshot()
    assert snapshot["slots"]["primary"]["samples"][0]["error_kind"] == "first_token_deadline"


def test_agent_canvas_runs_follow_the_open_breaker(monkeypatch, tmp_path: Path) -> None:
    _set_failover_env(monkeypatch, tmp_path)
    monkeypatch.setenv("AGENT_CANVAS_MODE_ENABLED", "true")

    from apps.api.config import get_settings
    from apps.api.agent_canvas_mode import get_agent_canvas_mode_service

    get_settings.cache_clear()
    settings = get_settings()
    router = get_model_router()
    service = get_agent_canvas_mode_service()

    assert service._routed_endpoint().slot == "primary"  # noqa: SLF001

    primary = router.candidates(protocol="anthropic", settings=settings)[0]
    router.record(primary, ok=False, error_kind="ConnectError", settings=settings)
    router.record(primary, ok=False, error_kind="ConnectError", settings=settings)

    # A canvas run cannot be replayed mid-flight, but it must not keep hammering
    # an endpoint the breaker has already opened on.
    assert service._routed_endpoint().slot == "backup"  # noqa: SLF001
    router.reset_health()


def test_last_candidate_is_never_preempted(monkeypatch, tmp_path: Path) -> None:
    _set_failover_env(monkeypatch, tmp_path)
    monkeypatch.setenv("MODEL_BACKUP_ENABLED", "false")

    from apps.api.config import get_settings
    from apps.api.agent_runtime import clear_agent_runtime_cache

    get_settings.cache_clear()
    clear_agent_runtime_cache()
    attempts: list[str] = []

    class _SlowButAliveClient:
        def __init__(self, *, options):  # type: ignore[no-untyped-def]
            attempts.append(_slot_of(options))

        async def __aenter__(self):  # type: ignore[no-untyped-def]
            return self

        async def __aexit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
            return False

        async def query(self, prompt: str, session_id: str = "default") -> None:
            return None

        async def receive_response(self):  # type: ignore[no-untyped-def]
            yield SystemMessage(subtype="init", data={})
            await asyncio.sleep(0.2)  # slower than the deadline below
            yield _result_message()

    with TestClient(app) as client:
        dataset_table = upload_dataset(client, rows=[{"employee_id": "E-1", "hire_year": 2023}])
        runtime = get_agent_runtime()
        _install_client(runtime, _SlowButAliveClient)
        runtime._first_token_deadline_seconds = lambda: 0.05  # noqa: SLF001 - test seam
        result = runtime.run_turn(_request(dataset_table, "req-no-fallback"))

    # Slow output beats no output: with nowhere to fail over to, the attempt runs
    # to completion instead of being abandoned.
    assert attempts == ["primary"]
    assert result.final_status == "completed"
