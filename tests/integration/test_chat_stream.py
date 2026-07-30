from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.agent_runtime import clear_agent_runtime_cache, get_agent_runtime
from apps.api.chat import clear_chat_stream_service_cache
from apps.api.config import get_settings
from apps.api.datasets import clear_dataset_service_cache
from apps.api.main import app
from apps.api.semantic import clear_semantic_cache
from apps.api.tool_calling import clear_tool_calling_service_cache
from apps.api.views import clear_view_storage_service_cache
from tests.agent_test_utils import upload_dataset
from tests.auth_utils import auth_headers


def _set_minimal_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/db")
    monkeypatch.setenv("MODEL_PROVIDER_URL", "http://localhost:11434")
    monkeypatch.delenv("AI_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_AGENT_SDK_ENABLED", raising=False)
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    # These tests assert the SSE contract for a dead SDK. Multi-chart planning
    # probes get_distinct_values *before* the SDK runs, and that observation lets
    # the runtime recover a grounded answer instead of failing — a real feature,
    # but it hides the failure path under test, so keep it off here.
    monkeypatch.setenv("MULTI_CHART_GENERATION_ENABLED", "false")
    get_settings.cache_clear()
    clear_dataset_service_cache()
    clear_semantic_cache()
    clear_tool_calling_service_cache()
    clear_chat_stream_service_cache()
    clear_view_storage_service_cache()
    clear_agent_runtime_cache()


def _upload_dataset(client: TestClient) -> str:
    return upload_dataset(
        client,
        rows=[
            {"employee_id": "E-001", "department": "HR", "status": "active", "salary": 1000},
            {"employee_id": "E-002", "department": "HR", "status": "inactive", "salary": 1200},
            {"employee_id": "E-003", "department": "PM", "status": "active", "salary": 900},
        ],
        user_id="alice",
        project_id="north",
    )


def _read_sse_events(response) -> tuple[list[dict[str, object]], float | None]:
    events: list[dict[str, object]] = []
    current: dict[str, object] = {}
    first_chunk_at: float | None = None

    for raw_line in response.iter_lines():
        line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
        if line and first_chunk_at is None:
            first_chunk_at = time.perf_counter()

        if line == "":
            if {"id", "event", "data"}.issubset(current):
                payload = json.loads(str(current["data"]))
                events.append(
                    {
                        "id": int(current["id"]),
                        "event": str(current["event"]),
                        "data": payload,
                    }
                )
            current = {}
            continue

        if line.startswith("id:"):
            current["id"] = line.split(":", 1)[1].strip()
            continue
        if line.startswith("event:"):
            current["event"] = line.split(":", 1)[1].strip()
            continue
        if line.startswith("data:"):
            current["data"] = line.split(":", 1)[1].strip()

    return events, first_chunk_at


def _install_failing_sdk_client() -> None:
    runtime = get_agent_runtime()

    class _FailingSDKClient:
        def __init__(self, *, options):  # type: ignore[no-untyped-def]
            _ = options

        async def __aenter__(self):  # type: ignore[no-untyped-def]
            raise RuntimeError("sdk timed out")

        async def __aexit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
            return False

    runtime._sdk_client_factory = _FailingSDKClient


def test_chat_stream_emits_required_events_with_low_first_token_latency(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _set_minimal_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        dataset_table = _upload_dataset(client)
        headers = auth_headers(
            client,
            user_id="alice",
            project_id="north",
            role="viewer",
            department="HR",
            clearance=1,
        )
        _install_failing_sdk_client()
        start = time.perf_counter()
        with client.stream(
            "POST",
            "/chat/stream",
            json={
                "conversation_id": "conv-stream-1",
                "request_id": "chat-req-1",
                "user_id": "alice",
                "project_id": "north",
                "dataset_table": dataset_table,
                "role": "viewer",
                "department": "HR",
                "clearance": 1,
                "message": "按部门看在职人数",
            },
            headers=headers,
        ) as response:
            assert response.status_code == 200
            events, first_chunk_at = _read_sse_events(response)

    assert first_chunk_at is not None
    assert first_chunk_at - start < 2.0
    assert [item["event"] for item in events][-2:] == ["error", "final"]
    assert events[-1]["data"]["status"] == "failed"


def test_chat_stream_reconnect_replays_missing_events(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        dataset_table = _upload_dataset(client)
        headers = auth_headers(
            client,
            user_id="alice",
            project_id="north",
            role="viewer",
            department="HR",
            clearance=1,
        )
        _install_failing_sdk_client()

        with client.stream(
            "POST",
            "/chat/stream",
            json={
                "conversation_id": "conv-stream-2",
                "request_id": "chat-req-2",
                "user_id": "alice",
                "project_id": "north",
                "dataset_table": dataset_table,
                "role": "viewer",
                "department": "HR",
                "clearance": 1,
                "message": "按部门看在职人数",
            },
            headers=headers,
        ) as first_response:
            assert first_response.status_code == 200
            first_events, _ = _read_sse_events(first_response)

        assert [item["event"] for item in first_events][-2:] == ["error", "final"]
        assert [item["id"] for item in first_events] == list(range(1, len(first_events) + 1))

        with client.stream(
            "POST",
            "/chat/stream",
            json={
                "conversation_id": "conv-stream-2",
                "request_id": "chat-req-2-replay",
                "user_id": "alice",
                "project_id": "north",
                "dataset_table": dataset_table,
                "last_event_id": first_events[-2]["id"],
                "message": None,
            },
            headers=headers,
        ) as replay_response:
            assert replay_response.status_code == 200
            replay_events, _ = _read_sse_events(replay_response)

    assert [item["id"] for item in replay_events] == [first_events[-1]["id"]]
    assert [item["event"] for item in replay_events] == ["final"]
    assert replay_events[-1]["data"]["status"] == "failed"


def test_chat_stream_returns_agent_error_when_sdk_fails(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path)
    monkeypatch.setenv("AI_API_KEY", "test-api-key")
    get_settings.cache_clear()
    clear_chat_stream_service_cache()
    clear_agent_runtime_cache()

    with TestClient(app) as client:
        dataset_table = _upload_dataset(client)
        headers = auth_headers(
            client,
            user_id="alice",
            project_id="north",
            role="viewer",
            department="HR",
            clearance=1,
        )
        _install_failing_sdk_client()

        with client.stream(
            "POST",
            "/chat/stream",
            json={
                "conversation_id": "conv-stream-timeout",
                "request_id": "chat-req-timeout",
                "user_id": "alice",
                "project_id": "north",
                "dataset_table": dataset_table,
                "role": "viewer",
                "department": "HR",
                "clearance": 1,
                "message": "Hi",
            },
            headers=headers,
        ) as response:
            assert response.status_code == 200
            events, _ = _read_sse_events(response)

    assert [item["event"] for item in events][-2:] == ["error", "final"]
    assert events[-2]["data"]["code"] == "AGENT_SDK_FAILED"
    assert events[-1]["data"]["status"] == "failed"
