from __future__ import annotations

import json
import time
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi.testclient import TestClient

from claude_agent_sdk import AssistantMessage, ResultMessage, ToolUseBlock

from apps.api.agent_runtime import SDK_MCP_SERVER_NAME, clear_agent_runtime_cache
from apps.api.audit import clear_audit_logger_cache
from apps.api.auth import clear_auth_cache
from apps.api.chat import clear_chat_stream_service_cache
from apps.api.config import get_settings
from apps.api.datasets import clear_dataset_service_cache, get_dataset_service
from apps.api.semantic import clear_semantic_cache
from apps.api.tool_calling import clear_tool_calling_service_cache
from apps.api.views import clear_view_storage_service_cache


def set_agent_env(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'views.db'}")
    monkeypatch.setenv("MODEL_PROVIDER_URL", "https://api.deepseek.com")
    monkeypatch.setenv("AI_API_KEY", "deepseek-test-key")
    monkeypatch.setenv("AI_MODEL", "deepseek-chat")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.deepseek.com/anthropic")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "")
    monkeypatch.setenv("ANTHROPIC_DEFAULT_HAIKU_MODEL", "deepseek-chat")
    monkeypatch.setenv("API_TIMEOUT_MS", "600000")
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("CLAUDE_AGENT_SDK_ENABLED", "true")
    monkeypatch.setenv("AGENT_MAX_TOOL_STEPS", "6")
    monkeypatch.setenv("AGENT_MAX_SQL_ROWS", "200")
    monkeypatch.setenv("AGENT_MAX_SQL_SCAN_ROWS", "10000")
    monkeypatch.setenv("AGENT_TIMEOUT_SECONDS", "25")
    monkeypatch.setenv("WEB_SEARCH_ENABLED", "false")

    get_settings.cache_clear()
    clear_auth_cache()
    clear_audit_logger_cache()
    clear_dataset_service_cache()
    clear_semantic_cache()
    clear_tool_calling_service_cache()
    clear_chat_stream_service_cache()
    clear_view_storage_service_cache()
    clear_agent_runtime_cache()


def excel_bytes(rows: list[dict[str, object]]) -> bytes:
    dataframe = pd.DataFrame(rows)
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        dataframe.to_excel(writer, index=False)
    return buffer.getvalue()


def upload_dataset(
    client: TestClient,
    *,
    rows: list[dict[str, object]],
    user_id: str = "alice",
    project_id: str = "north",
    role: str = "admin",
    department: str | None = "HR",
    clearance: int = 9,
    filename: str = "dataset.xlsx",
) -> str:
    _ = (client, role, department, clearance, filename)
    batch_key = f"{abs(hash((user_id, project_id, filename))) & 0xFFFFFFFF:x}"
    dataset_table = f"dataset_{batch_key}"
    dataframe = pd.DataFrame(rows)
    service = get_dataset_service(get_settings().upload_dir)
    with service.session_manager.connection(user_id, project_id) as conn:
        conn.register("seed_df", dataframe)
        conn.execute(f'CREATE OR REPLACE TABLE "{dataset_table}" AS SELECT * FROM seed_df')
        conn.unregister("seed_df")
    return dataset_table


def read_sse_events(response) -> tuple[list[dict[str, Any]], float | None]:
    events: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
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


def install_scripted_sdk_client(runtime: Any, scenario: Any) -> None:
    """Install a fake ClaudeSDKClient that exercises SDK hooks in tests.

    ``scenario(prompt, options)`` should return:
    {
        "tool_calls": [
            {"name": "execute_readonly_sql", "arguments": {...}, "result": {...}},
        ],
        "final_answer": {...},
        "session_id": "optional-session-id",
    }
    """

    class _ScriptedClaudeSDKClient:
        def __init__(self, *, options: Any) -> None:
            self.options = options
            self.prompt = ""
            self.session_id = ""
            self.cli_session_id = str(
                getattr(options, "resume", None)
                or getattr(options, "session_id", None)
                or f"session-{uuid.uuid4()}"
            )

        async def __aenter__(self) -> "_ScriptedClaudeSDKClient":
            return self

        async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
            return False

        async def query(self, prompt: str, session_id: str = "default") -> None:
            self.prompt = prompt
            self.session_id = session_id

        async def receive_response(self):  # type: ignore[no-untyped-def]
            script = scenario(self.prompt, self.options)
            final_answer = dict(script.get("final_answer") or {})
            session_id = str(script.get("session_id") or self.cli_session_id)

            for index, call in enumerate(script.get("tool_calls") or [], start=1):
                raw_name = str(call["name"])
                tool_name = (
                    raw_name
                    if raw_name.startswith("mcp__")
                    else f"mcp__{SDK_MCP_SERVER_NAME}__{raw_name}"
                )
                arguments = dict(call.get("arguments") or {})
                result = dict(call.get("result") or {})
                tool_use_id = str(call.get("id") or f"toolu_test_{index}")
                hook_input = {
                    "hook_event_name": "PreToolUse",
                    "tool_name": tool_name,
                    "tool_input": arguments,
                    "tool_use_id": tool_use_id,
                }
                await self._run_hooks("PreToolUse", hook_input, tool_use_id)
                yield AssistantMessage(
                    content=[
                        ToolUseBlock(
                            id=tool_use_id,
                            name=tool_name,
                            input=arguments,
                        )
                    ],
                    model="claude-test",
                    session_id=session_id,
                )
                post_input = {
                    "hook_event_name": "PostToolUse",
                    "tool_name": tool_name,
                    "tool_input": arguments,
                    "tool_use_id": tool_use_id,
                    "tool_response": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(result, ensure_ascii=False, default=str),
                            }
                        ]
                    },
                }
                await self._run_hooks("PostToolUse", post_input, tool_use_id)

            yield ResultMessage(
                subtype="success",
                duration_ms=1,
                duration_api_ms=1,
                is_error=False,
                num_turns=1,
                session_id=session_id,
                result=json.dumps(final_answer, ensure_ascii=False, default=str),
                structured_output=final_answer,
            )

        async def _run_hooks(self, event: str, input_data: dict[str, Any], tool_use_id: str) -> None:
            for matcher in (self.options.hooks or {}).get(event, []):
                for hook in matcher.hooks:
                    await hook(input_data, tool_use_id, {"signal": None})

    runtime._sdk_client_factory = _ScriptedClaudeSDKClient
