from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from threading import Lock
from typing import Any, AsyncGenerator, Iterator, Literal

from pydantic import BaseModel, Field

from .agent_guardrails import AgentGuardrailError
from .agent_runtime import AgentRequest, AgentRuntimeError, get_agent_runtime
from .config import get_settings

logger = logging.getLogger("cognitrix.chat")


class MultiChartConfirmationItem(BaseModel):
    key: str
    label: str | None = None


class MultiChartConfirmationPayload(BaseModel):
    confirmation_id: str
    action: Literal["confirm", "adjust", "cancel"]
    selected_items: list[MultiChartConfirmationItem] | None = None


class ChatStreamRequest(BaseModel):
    user_id: str
    project_id: str
    workspace_id: str | None = None
    dataset_table: str = ""
    message: str | None = None
    preferred_chart_type: str | None = None
    generation_strategy: Literal["multi_chart"] | None = None
    web_search_requested: bool = False
    response_locale: str | None = None
    conversation_id: str | None = None
    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    role: str = "viewer"
    department: str | None = None
    clearance: int = 0
    last_event_id: int | None = None
    multi_chart_confirmation: MultiChartConfirmationPayload | None = None


@dataclass(slots=True)
class ChatEvent:
    id: int
    type: str
    payload: dict[str, Any]


@dataclass(slots=True)
class ChatSession:
    conversation_id: str
    next_event_id: int = 1
    events: list[ChatEvent] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)


class ChatSessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, ChatSession] = {}
        self._lock = Lock()

    def append_events(self, *, conversation_id: str, events: list[tuple[str, dict[str, Any]]]) -> list[ChatEvent]:
        with self._lock:
            session = self._sessions.get(conversation_id)
            if session is None:
                session = ChatSession(conversation_id=conversation_id)
                self._sessions[conversation_id] = session

            created: list[ChatEvent] = []
            for event_type, payload in events:
                event = ChatEvent(
                    id=session.next_event_id,
                    type=event_type,
                    payload=payload,
                )
                session.next_event_id += 1
                session.events.append(event)
                created.append(event)
            return created

    def events_after(self, *, conversation_id: str, last_event_id: int) -> list[ChatEvent]:
        with self._lock:
            session = self._sessions.get(conversation_id)
            if session is None:
                return []
            return [item for item in session.events if item.id > last_event_id]

    def get_context(self, *, conversation_id: str) -> dict[str, Any]:
        with self._lock:
            session = self._sessions.get(conversation_id)
            if session is None:
                session = ChatSession(conversation_id=conversation_id)
                self._sessions[conversation_id] = session
            return dict(session.context)

    def update_context(self, *, conversation_id: str, updates: dict[str, Any]) -> None:
        with self._lock:
            session = self._sessions.get(conversation_id)
            if session is None:
                session = ChatSession(conversation_id=conversation_id)
                self._sessions[conversation_id] = session
            session.context.update(updates)

    def clear_conversation(self, *, conversation_id: str) -> None:
        with self._lock:
            self._sessions.pop(conversation_id, None)

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()


class ChatStreamService:
    def __init__(self) -> None:
        settings = get_settings()
        self.settings = settings
        self.agent_runtime = get_agent_runtime()
        self.sessions = ChatSessionStore()

    def stream(
        self,
        request: ChatStreamRequest,
        *,
        last_event_id_header: str | None = None,
    ) -> Iterator[str]:
        conversation_id = request.conversation_id or uuid.uuid4().hex
        last_event_id = request.last_event_id
        if last_event_id is None and last_event_id_header:
            try:
                last_event_id = int(last_event_id_header)
            except ValueError:
                last_event_id = None

        replay_events: list[ChatEvent] = []
        if last_event_id is not None:
            replay_events = self.sessions.events_after(
                conversation_id=conversation_id,
                last_event_id=last_event_id,
            )

        new_events: list[ChatEvent] = []
        if request.message or request.multi_chart_confirmation:
            try:
                generated = self._generate_event_payloads(request=request, conversation_id=conversation_id)
            except Exception:
                logger.exception(
                    "chat_stream_generation_failed conversation_id=%s request_id=%s",
                    conversation_id,
                    request.request_id,
                )
                generated = self._build_terminal_failure_events(
                    conversation_id=conversation_id,
                    request_id=request.request_id,
                    text="Unable to process the request right now. Please retry.",
                )
            new_events = self.sessions.append_events(conversation_id=conversation_id, events=generated)
        elif last_event_id is None:
            generated = self._build_terminal_failure_events(
                conversation_id=conversation_id,
                request_id=request.request_id,
                text="message is required when not replaying a previous stream",
            )
            new_events = self.sessions.append_events(conversation_id=conversation_id, events=generated)

        for event in [*replay_events, *new_events]:
            yield _format_sse(event)

    async def stream_async(
        self,
        request: ChatStreamRequest,
        *,
        last_event_id_header: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """Async generator — yields SSE strings in real-time as the agent produces events."""
        conversation_id = request.conversation_id or uuid.uuid4().hex
        last_event_id = request.last_event_id
        if last_event_id is None and last_event_id_header:
            try:
                last_event_id = int(last_event_id_header)
            except ValueError:
                last_event_id = None

        # Replay any missed events first
        if last_event_id is not None:
            for event in self.sessions.events_after(
                conversation_id=conversation_id,
                last_event_id=last_event_id,
            ):
                yield _format_sse(event)

        if not request.message and request.multi_chart_confirmation is None:
            if last_event_id is None:
                generated = self._build_terminal_failure_events(
                    conversation_id=conversation_id,
                    request_id=request.request_id,
                    text="message is required when not replaying a previous stream",
                )
                for event in self.sessions.append_events(conversation_id=conversation_id, events=generated):
                    yield _format_sse(event)
            return

        try:
            async for event_type, payload in self._stream_agent_events(
                request=request,
                conversation_id=conversation_id,
            ):
                created = self.sessions.append_events(
                    conversation_id=conversation_id,
                    events=[(event_type, payload)],
                )
                for event in created:
                    yield _format_sse(event)
        except AgentGuardrailError as exc:
            logger.warning(
                "agent_guardrail_blocked conversation_id=%s request_id=%s code=%s",
                conversation_id,
                request.request_id,
                exc.code,
            )
            error_events = [
                ("error", {
                    "conversation_id": conversation_id,
                    "request_id": request.request_id,
                    "status": "failed",
                    "code": exc.code,
                    "message": exc.message,
                }),
                ("final", {
                    "conversation_id": conversation_id,
                    "request_id": request.request_id,
                    "status": "failed",
                    "text": exc.message,
                }),
            ]
            for event in self.sessions.append_events(conversation_id=conversation_id, events=error_events):
                yield _format_sse(event)
        except AgentRuntimeError as exc:
            logger.warning(
                "agent_runtime_failed conversation_id=%s request_id=%s code=%s",
                conversation_id,
                request.request_id,
                exc.code,
            )
            error_events = [
                ("error", {
                    "conversation_id": conversation_id,
                    "request_id": request.request_id,
                    "status": "failed",
                    "code": exc.code,
                    "message": exc.message,
                }),
                ("final", {
                    "conversation_id": conversation_id,
                    "request_id": request.request_id,
                    "status": "failed",
                    "text": exc.message,
                }),
            ]
            for event in self.sessions.append_events(conversation_id=conversation_id, events=error_events):
                yield _format_sse(event)
        except Exception:
            logger.exception(
                "chat_stream_generation_failed conversation_id=%s request_id=%s",
                conversation_id,
                request.request_id,
            )
            error_events = self._build_terminal_failure_events(
                conversation_id=conversation_id,
                request_id=request.request_id,
                text="Unable to process the request right now. Please retry.",
            )
            for event in self.sessions.append_events(conversation_id=conversation_id, events=error_events):
                yield _format_sse(event)
        finally:
            # Update context after stream ends (agent_session_id, etc.)
            # This is best-effort — context is pulled from stored session state
            pass

    async def _stream_agent_events(
        self,
        *,
        request: ChatStreamRequest,
        conversation_id: str,
    ) -> AsyncGenerator[tuple[str, dict[str, Any]], None]:
        message = request.message or ""
        agent_request = AgentRequest(
            conversation_id=conversation_id,
            request_id=request.request_id,
            user_id=request.user_id,
            project_id=request.project_id,
            workspace_id=request.workspace_id,
            dataset_table=request.dataset_table,
            message=message,
            preferred_chart_type=request.preferred_chart_type,
            generation_strategy=request.generation_strategy,
            web_search_requested=request.web_search_requested,
            response_locale=request.response_locale,
            role=request.role,
            department=request.department,
            clearance=request.clearance,
            multi_chart_confirmation=request.multi_chart_confirmation.model_dump()
            if request.multi_chart_confirmation
            else None,
        )
        async for event_type, payload in self.agent_runtime.run_turn_stream(agent_request):
            yield event_type, payload
        # Update session context after streaming completes
        runtime_session = self.agent_runtime.get_persisted_session(conversation_id)
        if runtime_session is not None:
            self.sessions.update_context(
                conversation_id=conversation_id,
                updates={
                    "latest_spec": runtime_session.last_spec,
                    "latest_specs": runtime_session.last_specs,
                    "agent_session_id": runtime_session.agent_session_id,
                    "agent_tool_trace": runtime_session.last_tool_trace,
                },
            )

    def clear_runtime_state(self) -> None:
        self.sessions.clear()
        self.agent_runtime.clear_runtime_state()

    def reset_conversation(self, conversation_id: str) -> None:
        self.sessions.clear_conversation(conversation_id=conversation_id)
        self.agent_runtime.reset_session(conversation_id)

    def _generate_event_payloads(
        self,
        *,
        request: ChatStreamRequest,
        conversation_id: str,
    ) -> list[tuple[str, dict[str, Any]]]:
        try:
            return self._generate_agent_event_payloads(request=request, conversation_id=conversation_id)
        except AgentGuardrailError as exc:
            logger.warning(
                "agent_guardrail_blocked conversation_id=%s request_id=%s code=%s",
                conversation_id,
                request.request_id,
                exc.code,
            )
            return [
                (
                    "error",
                    {
                        "conversation_id": conversation_id,
                        "request_id": request.request_id,
                        "status": "failed",
                        "code": exc.code,
                        "message": exc.message,
                    },
                ),
                (
                    "final",
                    {
                        "conversation_id": conversation_id,
                        "request_id": request.request_id,
                        "status": "failed",
                        "text": exc.message,
                    },
                ),
            ]
        except AgentRuntimeError as exc:
            logger.warning(
                "agent_runtime_failed conversation_id=%s request_id=%s code=%s",
                conversation_id,
                request.request_id,
                exc.code,
            )
            return [
                (
                    "error",
                    {
                        "conversation_id": conversation_id,
                        "request_id": request.request_id,
                        "status": "failed",
                        "code": exc.code,
                        "message": exc.message,
                    },
                ),
                (
                    "final",
                    {
                        "conversation_id": conversation_id,
                        "request_id": request.request_id,
                        "status": "failed",
                        "text": exc.message,
                    },
                ),
            ]

    def _generate_agent_event_payloads(
        self,
        *,
        request: ChatStreamRequest,
        conversation_id: str,
    ) -> list[tuple[str, dict[str, Any]]]:
        message = request.message or ""
        result = self.agent_runtime.run_turn(
            AgentRequest(
                conversation_id=conversation_id,
                request_id=request.request_id,
                user_id=request.user_id,
                project_id=request.project_id,
                workspace_id=request.workspace_id,
                dataset_table=request.dataset_table,
                message=message,
                preferred_chart_type=request.preferred_chart_type,
                generation_strategy=request.generation_strategy,
                web_search_requested=request.web_search_requested,
                response_locale=request.response_locale,
                role=request.role,
                department=request.department,
                clearance=request.clearance,
                multi_chart_confirmation=request.multi_chart_confirmation.model_dump()
                if request.multi_chart_confirmation
                else None,
            )
        )
        self.sessions.update_context(
            conversation_id=conversation_id,
            updates={
                "latest_spec": result.spec,
                "latest_specs": result.specs,
                "latest_sql": result.ai_state.get("latest_result", {}).get("sql")
                if isinstance(result.ai_state.get("latest_result"), dict)
                else None,
                "agent_session_id": result.agent_session_id,
                "agent_tool_trace": result.tool_trace,
            },
        )
        return result.events

    def _build_terminal_failure_events(
        self,
        *,
        conversation_id: str,
        request_id: str,
        text: str,
    ) -> list[tuple[str, dict[str, Any]]]:
        return [
            (
                "final",
                {
                    "conversation_id": conversation_id,
                    "request_id": request_id,
                    "status": "failed",
                    "text": text,
                },
            )
        ]


def _format_sse(event: ChatEvent) -> str:
    return (
        f"id: {event.id}\n"
        f"event: {event.type}\n"
        f"data: {json.dumps(event.payload, ensure_ascii=False, default=str)}\n\n"
    )


@lru_cache(maxsize=2)
def _cached_chat_stream_service(settings_key: str) -> ChatStreamService:
    _ = settings_key
    return ChatStreamService()


def get_chat_stream_service() -> ChatStreamService:
    settings = get_settings()
    settings_key = "|".join(
        [
            str(settings.upload_dir.resolve()),
            settings.model_provider_url.strip(),
            settings.ai_model.strip(),
            "enabled" if bool(settings.ai_api_key.strip()) else "disabled",
        ]
    )
    return _cached_chat_stream_service(settings_key)


def clear_chat_stream_service_cache() -> None:
    _cached_chat_stream_service.cache_clear()
