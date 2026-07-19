from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, AsyncGenerator

import anyio
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    TextBlock,
    ToolAnnotations,
    create_sdk_mcp_server,
    tool,
)

from .agent_canvas import (
    CANVAS_FORMAT_WEB_DESIGN,
    CANVAS_TOOL_DEFINITIONS,
    CANVAS_TOOL_NAMES,
    RUN_STATUS_AWAITING_APPROVAL,
    RUN_STATUS_CANCELED,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
    RUN_STATUS_PARTIAL,
    RUN_STATUS_RUNNING,
    RUN_STATUS_STOPPED,
    SIZE_PRESETS,
    TERMINAL_RUN_STATUSES,
    TEXT_STYLES,
    block_id_for,
    get_agent_canvas_run_store,
)
from .agent_guardrails import AgentGuardrailContext, AgentGuardrailError
from .agent_prompting import (
    build_agent_canvas_execution_prompt,
    build_agent_canvas_outline_prompt,
)
from .agent_runtime import (
    AGENT_TOOL_DEFINITIONS,
    SDK_MCP_SERVER_NAME,
    AgentRequest,
    _canonical_sdk_tool_name,
    _localized_text,
    _normalize_response_locale,
    _parse_final_answer,
    build_sdk_provider_env,
    get_agent_runtime,
)
from .audit import get_audit_logger
from .config import get_settings
from .tool_calling import ToolCall, ToolCallRequest, ToolCallResponse

logger = logging.getLogger("cognitrix.agent_canvas")


class AgentCanvasRetryError(Exception):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_detail(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}

# Read-only exploration tools available in both phases (design D4): everything
# except save_view, which has no place in a dashboard-generation run.
READONLY_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    definition
    for definition in AGENT_TOOL_DEFINITIONS
    if definition.get("function", {}).get("name") != "save_view"
]
READONLY_TOOL_NAMES = tuple(
    str(definition["function"]["name"]) for definition in READONLY_TOOL_DEFINITIONS
)

OUTLINE_MAX_STEPS = 8
KEEPALIVE_INTERVAL_SECONDS = 15.0


@dataclass(slots=True)
class ActiveRunHandle:
    run_id: str
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    subscribers: list[asyncio.Queue] = field(default_factory=list)
    task: asyncio.Task | None = None

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self.subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        if queue in self.subscribers:
            self.subscribers.remove(queue)

    def broadcast(self, item: tuple[str, dict[str, Any]] | None) -> None:
        for queue in list(self.subscribers):
            queue.put_nowait(item)


@dataclass(slots=True)
class CanvasExecutionContext:
    run: dict[str, Any]
    request: AgentRequest
    locale: str
    handle: ActiveRunHandle
    outline: dict[str, Any]
    charts_total: int
    charts_placed: int = 0
    blocks_placed: int = 0
    failed_items: int = 0
    finish_called: bool = False
    finish_summary: str = ""
    budget_exhausted: bool = False
    next_step: int = 1
    tool_steps: int = 0
    text_blocks: list[str] = field(default_factory=list)
    sections: list[str] = field(default_factory=list)


class AgentCanvasModeService:
    """Two-phase agent-canvas runs: outline → approval → detached execution.

    The execution task is shielded from SSE consumer cancellation (design D7):
    ops are persisted to the op log inside the tool handlers before any live
    push, and the task itself is owned by this service, not by a response
    generator. Disconnected clients replay from the op log and re-attach.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self.settings = settings
        self.runtime = get_agent_runtime()
        self.guardrails = self.runtime.guardrails
        self.tool_service = self.runtime.tool_service
        self.store = get_agent_canvas_run_store()
        self._active: dict[str, ActiveRunHandle] = {}
        self._sdk_client_factory = ClaudeSDKClient

    # ------------------------------------------------------------------
    # Chat-stream entry point
    # ------------------------------------------------------------------

    async def stream_turn(
        self,
        *,
        request: Any,
        conversation_id: str,
    ) -> AsyncGenerator[tuple[str, dict[str, Any]], None]:
        base = {
            "conversation_id": conversation_id,
            "request_id": request.request_id,
        }
        if request.agent_run_confirmation is not None:
            async for item in self._stream_confirmation_turn(
                request=request, conversation_id=conversation_id, base=base
            ):
                yield item
            return

        # ------ New agent-mode turn: validate, plan, pause (or auto-run) ------
        canvas_format = str(request.canvas_format or "").strip()
        if canvas_format != CANVAS_FORMAT_WEB_DESIGN:
            for _item in _error_final(
                base,
                code="AGENT_CANVAS_FORMAT_UNSUPPORTED",
                message=(
                    "Agent mode currently supports only the web-design canvas format. "
                    f"Got: '{canvas_format or 'none'}'."
                ),
            ):
                yield _item
            return
        workspace_id = str(request.workspace_id or "").strip()
        if not workspace_id:
            for _item in _error_final(
                base,
                code="AGENT_CANVAS_WORKSPACE_REQUIRED",
                message="Agent mode requires an active workspace.",
            ):
                yield _item
            return
        active = self.store.get_active_run(workspace_id=workspace_id, user_id=request.user_id)
        if active is not None and active["status"] == RUN_STATUS_RUNNING:
            if active["run_id"] in self._active:
                for _item in _error_final(
                    base,
                    code="AGENT_CANVAS_RUN_ALREADY_ACTIVE",
                    message="A dashboard-generation run is already active in this workspace.",
                ):
                    yield _item
                return
            # Dangling run (server restart mid-run): finalize as partial so the
            # workspace is never wedged behind a zombie status.
            self._reconcile_dangling_run(active)

        agent_request = self._build_agent_request(request, conversation_id)
        guard_context = AgentGuardrailContext(
            role=agent_request.role,
            user_id=agent_request.user_id,
            project_id=agent_request.project_id,
        )
        # Raises AgentGuardrailError → mapped to error events by ChatStreamService.
        self.guardrails.validate_user_message(message=agent_request.message, context=guard_context)
        locale = _normalize_response_locale(agent_request.response_locale, agent_request.message)

        yield (
            "planning",
            {
                **base,
                "text": _localized_text(
                    locale,
                    en="Planning the dashboard outline...",
                    zh="正在规划仪表盘大纲...",
                ),
            },
        )

        outline_queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()

        async def _run_outline() -> dict[str, Any] | None:
            try:
                return await self._run_outline_phase(
                    agent_request=agent_request,
                    base=base,
                    emit=lambda event: outline_queue.put_nowait(event),
                )
            finally:
                outline_queue.put_nowait(None)

        outline_task = asyncio.ensure_future(_run_outline())
        try:
            while True:
                item = await outline_queue.get()
                if item is None:
                    break
                yield item
            outline = await outline_task
        finally:
            if not outline_task.done():
                outline_task.cancel()
                try:
                    await outline_task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass

        if outline is None:
            for _item in _error_final(
                base,
                code="AGENT_CANVAS_OUTLINE_FAILED",
                message=_localized_text(
                    locale,
                    en="Could not produce a valid dashboard outline. Please rephrase and retry.",
                    zh="未能生成有效的仪表盘大纲，请调整描述后重试。",
                ),
            ):
                yield _item
            return

        confirmation_id = f"dash-{uuid.uuid4().hex}"
        expires_at = time.time() + int(self.settings.multi_chart_confirmation_ttl_seconds)
        auto_approve = bool(getattr(request, "auto_approve", False))
        pending_outline = {
            "confirmation_id": confirmation_id,
            "expires_at": expires_at,
            "original_message": agent_request.message,
            "locale": locale,
            "outline": outline,
        }
        run = self.store.create_run(
            conversation_id=conversation_id,
            workspace_id=workspace_id,
            user_id=agent_request.user_id,
            canvas_format=canvas_format,
            status=RUN_STATUS_RUNNING if auto_approve else RUN_STATUS_AWAITING_APPROVAL,
            confirmation_id=confirmation_id,
            outline=pending_outline,
        )

        outline_payload = self._outline_payload(
            base=base,
            run=run,
            outline=outline,
            confirmation_id=confirmation_id,
            expires_at=expires_at,
            locale=locale,
        )

        if not auto_approve:
            yield ("confirmation_required", outline_payload)
            yield (
                "final",
                {
                    **base,
                    "status": "awaiting_confirmation",
                    "confirmation_type": "dashboard_outline",
                    "confirmation_id": confirmation_id,
                    "run_id": run["run_id"],
                    "text": _localized_text(
                        locale,
                        en=f"Please review the outline before I build {outline['chart_count']} charts.",
                        zh=f"构建 {outline['chart_count']} 个图表前，请先确认大纲。",
                    ),
                },
            )
            return

        # auto_approve: the outline is informational; execution starts at once
        # (server budgets still apply — the pause is the only thing skipped).
        yield ("outline", outline_payload)
        handle = self._start_execution(run=run, agent_request=agent_request, locale=locale, auto_approve=True)
        async for item in self._tail_handle(handle):
            yield item

    async def _stream_confirmation_turn(
        self,
        *,
        request: Any,
        conversation_id: str,
        base: dict[str, Any],
    ) -> AsyncGenerator[tuple[str, dict[str, Any]], None]:
        payload = request.agent_run_confirmation
        confirmation_id = str(payload.confirmation_id or "").strip()
        run = self.store.get_run_by_confirmation(confirmation_id) if confirmation_id else None
        if run is None:
            for _item in _error_final(
                base,
                code="AGENT_CANVAS_CONFIRMATION_MISSING",
                message="No pending dashboard outline matches this confirmation.",
            ):
                yield _item
            return
        if run["status"] != RUN_STATUS_AWAITING_APPROVAL:
            for _item in _error_final(
                base,
                code="AGENT_CANVAS_CONFIRMATION_STALE",
                message="This dashboard outline is no longer awaiting approval.",
            ):
                yield _item
            return
        pending = run.get("outline") or {}
        locale = str(pending.get("locale") or "en-US")
        if float(pending.get("expires_at") or 0) < time.time():
            self.store.update_status(run["run_id"], RUN_STATUS_CANCELED)
            for _item in _error_final(
                base,
                code="AGENT_CANVAS_CONFIRMATION_EXPIRED",
                message=_localized_text(
                    locale,
                    en="The dashboard outline confirmation expired. Please ask again.",
                    zh="仪表盘大纲确认已过期，请重新发起请求。",
                ),
            ):
                yield _item
            return

        if payload.action == "cancel":
            self.store.update_status(run["run_id"], RUN_STATUS_CANCELED)
            yield (
                "final",
                {
                    **base,
                    "status": "canceled",
                    "run_id": run["run_id"],
                    "text": _localized_text(
                        locale,
                        en="Dashboard generation was canceled.",
                        zh="已取消仪表盘生成。",
                    ),
                },
            )
            return

        outline = pending.get("outline") or {}
        filtered, selection_error = _filter_outline_selection(
            outline,
            selected_item_keys=payload.selected_item_keys,
            max_charts=int(self.settings.agent_mode_max_charts),
        )
        if selection_error is not None:
            for _item in _error_final(base, **selection_error):
                yield _item
            return

        pending_update = {**pending, "outline": filtered}
        self.store.update_status(run["run_id"], RUN_STATUS_RUNNING, outline=pending_update)
        run = self.store.get_run(run["run_id"]) or run

        agent_request = self._build_agent_request(
            request,
            conversation_id,
            message_override=str(pending.get("original_message") or request.message or ""),
        )
        handle = self._start_execution(
            run=run, agent_request=agent_request, locale=locale, auto_approve=False
        )
        async for item in self._tail_handle(handle):
            yield item

    # ------------------------------------------------------------------
    # Outline phase
    # ------------------------------------------------------------------

    async def _run_outline_phase(
        self,
        *,
        agent_request: AgentRequest,
        base: dict[str, Any],
        emit: Any,
    ) -> dict[str, Any] | None:
        system_text = "\n\n".join(
            [
                build_agent_canvas_outline_prompt(max_charts=int(self.settings.agent_mode_max_charts)),
                *self._context_sections(agent_request),
            ]
        )
        state = {"final": None}

        async def invoke(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            return await self._invoke_phase_tool(
                agent_request=agent_request,
                base=base,
                emit=emit,
                exec_ctx=None,
                allowed_tools=READONLY_TOOL_NAMES,
                tool_name=tool_name,
                arguments=arguments,
                step_counter=state,
            )

        options = self._build_options(
            system_text=system_text,
            tool_definitions=READONLY_TOOL_DEFINITIONS,
            allowed_tools=READONLY_TOOL_NAMES,
            invoke=invoke,
            max_turns=OUTLINE_MAX_STEPS,
            agent_request=agent_request,
        )
        try:
            timeout = min(180.0, float(self.settings.agent_mode_timeout_seconds))
            raw = await asyncio.wait_for(
                self._run_sdk_conversation(options=options, message=agent_request.message),
                timeout=timeout,
            )
        except (asyncio.TimeoutError, Exception) as exc:  # noqa: BLE001
            logger.warning(
                "agent_canvas_outline_failed conversation_id=%s error=%s",
                agent_request.conversation_id,
                exc,
            )
            return None
        if raw is None:
            return None
        try:
            return _normalize_outline(raw, max_charts=int(self.settings.agent_mode_max_charts))
        except ValueError as exc:
            logger.warning(
                "agent_canvas_outline_invalid conversation_id=%s error=%s",
                agent_request.conversation_id,
                exc,
            )
            return None

    # ------------------------------------------------------------------
    # Execution phase (detached task)
    # ------------------------------------------------------------------

    def _start_execution(
        self,
        *,
        run: dict[str, Any],
        agent_request: AgentRequest,
        locale: str,
        auto_approve: bool,
    ) -> ActiveRunHandle:
        handle = ActiveRunHandle(run_id=run["run_id"])
        self._active[run["run_id"]] = handle
        outline = (run.get("outline") or {}).get("outline") or {}
        exec_ctx = CanvasExecutionContext(
            run=run,
            request=agent_request,
            locale=locale,
            handle=handle,
            outline=outline,
            charts_total=int(outline.get("chart_count") or 0),
        )
        get_audit_logger().log(
            event_type="agent",
            action="agent_run_start",
            status="success",
            user_id=agent_request.user_id,
            project_id=agent_request.project_id,
            detail={
                "run_id": run["run_id"],
                "workspace_id": run["workspace_id"],
                "canvas_format": run["canvas_format"],
                "chart_items": exec_ctx.charts_total,
                "auto_approve": auto_approve,
            },
        )
        handle.task = asyncio.ensure_future(self._execute_run(exec_ctx))
        return handle

    async def _execute_run(self, exec_ctx: CanvasExecutionContext) -> None:
        run = exec_ctx.run
        run_id = run["run_id"]
        base = {
            "conversation_id": exec_ctx.request.conversation_id,
            "request_id": exec_ctx.request.request_id,
        }
        started = time.perf_counter()
        status = RUN_STATUS_FAILED
        failure_code: str | None = None
        try:
            # First op of every run: create the fresh page (design D8). Ops are
            # persisted before the live push, so replay always sees them.
            page_op = self.store.append_op(
                run_id=run_id,
                op_type="create_page",
                payload=lambda seq: {
                    "block_id": block_id_for(run_id, seq),
                    "page_id": run["page_id"],
                    "title": str(exec_ctx.outline.get("title") or "Dashboard"),
                },
            )
            exec_ctx.handle.broadcast(("canvas_op", self._op_event(base, run, page_op)))

            outline_json = json.dumps(exec_ctx.outline, ensure_ascii=False, indent=2)
            system_text = "\n\n".join(
                [
                    build_agent_canvas_execution_prompt(
                        outline_json=outline_json,
                        max_charts=int(self.settings.agent_mode_max_charts),
                    ),
                    *self._context_sections(exec_ctx.request),
                ]
            )

            async def invoke(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
                return await self._invoke_phase_tool(
                    agent_request=exec_ctx.request,
                    base=base,
                    emit=exec_ctx.handle.broadcast,
                    exec_ctx=exec_ctx,
                    allowed_tools=READONLY_TOOL_NAMES + CANVAS_TOOL_NAMES,
                    tool_name=tool_name,
                    arguments=arguments,
                    step_counter=None,
                )

            options = self._build_options(
                system_text=system_text,
                tool_definitions=[*READONLY_TOOL_DEFINITIONS, *CANVAS_TOOL_DEFINITIONS],
                allowed_tools=READONLY_TOOL_NAMES + CANVAS_TOOL_NAMES,
                invoke=invoke,
                max_turns=int(self.settings.agent_mode_max_steps),
                agent_request=exec_ctx.request,
            )
            message = _localized_text(
                exec_ctx.locale,
                en="Build the approved dashboard outline now, following the build protocol exactly.",
                zh="现在开始按已批准的大纲和构建协议逐项生成仪表盘。",
            )

            sdk_task = asyncio.ensure_future(
                self._run_sdk_conversation(
                    options=options,
                    message=message,
                    collect_text=exec_ctx.text_blocks,
                )
            )
            cancel_task = asyncio.ensure_future(exec_ctx.handle.cancel_event.wait())
            done, _pending = await asyncio.wait(
                {sdk_task, cancel_task},
                timeout=float(self.settings.agent_mode_timeout_seconds),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if sdk_task in done:
                cancel_task.cancel()
                try:
                    await sdk_task
                except Exception as exc:  # noqa: BLE001 - partial results are kept
                    logger.warning("agent_canvas_execution_error run_id=%s error=%s", run_id, exc)
                    failure_code = "AGENT_CANVAS_EXECUTION_FAILED"
                if exec_ctx.handle.cancel_event.is_set():
                    status = RUN_STATUS_STOPPED
                elif exec_ctx.budget_exhausted:
                    # Budgets are terminal (agent-canvas-mode spec): even a
                    # subsequent finish_dashboard leaves the run partial.
                    status = RUN_STATUS_PARTIAL
                    failure_code = failure_code or "AGENT_MODE_BUDGET_EXCEEDED"
                elif exec_ctx.finish_called:
                    status = RUN_STATUS_COMPLETED
                elif failure_code is not None and exec_ctx.charts_placed == 0 and exec_ctx.blocks_placed == 0:
                    status = RUN_STATUS_FAILED
                else:
                    # Watchdog finalization: the model stopped without calling
                    # finish_dashboard — never leave a run `running` forever.
                    status = RUN_STATUS_PARTIAL
                    failure_code = failure_code or "AGENT_CANVAS_FINISH_MISSING"
            elif cancel_task in done:
                sdk_task.cancel()
                try:
                    await sdk_task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
                status = RUN_STATUS_STOPPED
            else:
                # Watchdog timeout: keep everything already placed.
                sdk_task.cancel()
                cancel_task.cancel()
                try:
                    await sdk_task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
                status = RUN_STATUS_PARTIAL
                failure_code = "AGENT_MODE_TIMEOUT"
        except Exception as exc:  # noqa: BLE001 - the run task must always finalize
            logger.exception("agent_canvas_run_crashed run_id=%s", run_id)
            failure_code = failure_code or "AGENT_CANVAS_EXECUTION_FAILED"
            _ = exc
            if exec_ctx.charts_placed > 0 or exec_ctx.blocks_placed > 0:
                status = RUN_STATUS_PARTIAL
        finally:
            duration_ms = int((time.perf_counter() - started) * 1000)
            skipped = max(
                0, exec_ctx.charts_total - exec_ctx.charts_placed - exec_ctx.failed_items
            )
            summary_text = exec_ctx.finish_summary or _default_summary(
                status=status,
                locale=exec_ctx.locale,
                placed=exec_ctx.charts_placed,
                failed=exec_ctx.failed_items,
            )
            summary = {
                "status": status,
                "text": summary_text,
                "placed": exec_ctx.charts_placed,
                "failed": exec_ctx.failed_items,
                "skipped": skipped,
                "duration_ms": duration_ms,
            }
            if failure_code:
                summary["code"] = failure_code
            self.store.update_status(run_id, status, summary=summary)
            get_audit_logger().log(
                event_type="agent",
                action="agent_run_finish",
                status="success" if status == RUN_STATUS_COMPLETED else "failed",
                severity="INFO",
                user_id=exec_ctx.request.user_id,
                project_id=exec_ctx.request.project_id,
                detail={
                    "run_id": run_id,
                    "status": status,
                    "op_count": self.store.count_ops(run_id=run_id),
                    "chart_count": exec_ctx.charts_placed,
                    "failed_count": exec_ctx.failed_items,
                    "duration_ms": duration_ms,
                },
            )
            final_payload = {
                **base,
                "status": status,
                "run_id": run_id,
                "page_id": run["page_id"],
                "text": summary_text,
                "placed_count": exec_ctx.charts_placed,
                "failed_count": exec_ctx.failed_items,
                "skipped_count": skipped,
                "duration_ms": duration_ms,
                "tool_steps": exec_ctx.tool_steps,
            }
            if failure_code:
                final_payload["code"] = failure_code
            exec_ctx.handle.broadcast(("final", final_payload))
            exec_ctx.handle.broadcast(None)
            self._active.pop(run_id, None)

    # ------------------------------------------------------------------
    # Run control / re-attach surface
    # ------------------------------------------------------------------

    def stop_run(self, run_id: str) -> dict[str, Any] | None:
        run = self.store.get_run(run_id)
        if run is None:
            return None
        handle = self._active.get(run_id)
        if handle is not None:
            handle.cancel_event.set()
        elif run["status"] == RUN_STATUS_AWAITING_APPROVAL:
            self.store.update_status(run_id, RUN_STATUS_CANCELED)
        elif run["status"] == RUN_STATUS_RUNNING:
            # Dangling run without a live task (e.g. restart): finalize directly.
            self.store.update_status(
                run_id,
                RUN_STATUS_STOPPED,
                summary={"status": RUN_STATUS_STOPPED, "reason": "stopped_without_active_task"},
            )
        get_audit_logger().log(
            event_type="agent",
            action="agent_run_stop",
            status="success",
            user_id=run["user_id"],
            project_id="",
            detail={"run_id": run_id},
        )
        return self.store.get_run(run_id)

    def retry_item(
        self,
        *,
        run_id: str,
        seq: int,
        user_id: str,
        project_id: str,
        role: str,
        department: str | None,
        clearance: int,
    ) -> dict[str, Any]:
        """Re-execute a single failed chart item (error placeholder → chart).

        The new op reuses the placeholder's block id via `_replaces_block_id`,
        so the client swaps the block in place without moving anything else.
        """
        run = self.store.get_run(run_id)
        if run is None:
            raise AgentCanvasRetryError(code="AGENT_CANVAS_RUN_NOT_FOUND", message="Unknown run.")
        ops = self.store.list_ops_after(run_id=run_id, after_seq=int(seq) - 1)
        target = next((op for op in ops if int(op["seq"]) == int(seq)), None)
        if target is None or target["op_type"] != "error_placeholder":
            raise AgentCanvasRetryError(
                code="AGENT_CANVAS_RETRY_TARGET_INVALID",
                message="The referenced op is not a retryable error placeholder.",
            )
        payload = target.get("payload") or {}
        args = dict(payload.get("args") or {})
        if not args:
            raise AgentCanvasRetryError(
                code="AGENT_CANVAS_RETRY_TARGET_INVALID",
                message="The error placeholder does not carry retryable arguments.",
            )
        args["_agent_run"] = {
            "run_id": run_id,
            "page_id": run["page_id"],
            "workspace_id": run["workspace_id"],
            "conversation_id": run["conversation_id"],
        }
        args["_replaces_block_id"] = str(payload.get("block_id") or "")
        response = self.tool_service.invoke(
            ToolCallRequest(
                conversation_id=run["conversation_id"],
                request_id=f"retry-{uuid.uuid4().hex}",
                idempotency_key=f"retry-{run_id}-{seq}-{uuid.uuid4().hex[:8]}",
                user_id=user_id,
                project_id=project_id,
                workspace_id=run["workspace_id"],
                dataset_table="",
                role=role,
                department=department,
                clearance=clearance,
                emit_debug_blocks=False,
                tool=ToolCall(name="place_chart", arguments=args),
            )
        )
        if response.status != "success" or not isinstance(response.result, dict):
            error = response.error or {"code": "TOOL_FAILED", "message": "Retry failed"}
            raise AgentCanvasRetryError(
                code=str(error.get("code") or "AGENT_CANVAS_RETRY_FAILED"),
                message=str(error.get("message") or "Retry failed"),
            )
        result = dict(response.result)
        op = result.pop("op", None)
        base = {"conversation_id": run["conversation_id"], "request_id": ""}
        if isinstance(op, dict):
            handle = self._active.get(run_id)
            if handle is not None:
                handle.broadcast(("canvas_op", self._op_event(base, run, op)))
        return {
            "status": result.get("status"),
            "op": self._op_event(base, run, op) if isinstance(op, dict) else None,
            "error": result.get("error"),
        }

    def describe_run(self, run: dict[str, Any]) -> dict[str, Any]:
        ops = self.store.list_ops_after(run_id=run["run_id"], after_seq=0)
        return {
            "run_id": run["run_id"],
            "conversation_id": run["conversation_id"],
            "workspace_id": run["workspace_id"],
            "page_id": run["page_id"],
            "canvas_format": run["canvas_format"],
            "status": run["status"],
            "summary": run.get("summary"),
            "last_seq": ops[-1]["seq"] if ops else 0,
            "created_at": run["created_at"],
            "updated_at": run["updated_at"],
        }

    def get_workspace_run(self, *, workspace_id: str, user_id: str) -> dict[str, Any] | None:
        run = self.store.get_active_run(workspace_id=workspace_id, user_id=user_id)
        if run is not None and run["status"] == RUN_STATUS_RUNNING and run["run_id"] not in self._active:
            run = self._reconcile_dangling_run(run)
        if run is None:
            run = self.store.get_latest_run(workspace_id=workspace_id, user_id=user_id)
        return run

    def _reconcile_dangling_run(self, run: dict[str, Any]) -> dict[str, Any]:
        self.store.update_status(
            run["run_id"],
            RUN_STATUS_PARTIAL,
            summary={"status": RUN_STATUS_PARTIAL, "code": "AGENT_CANVAS_RUN_INTERRUPTED"},
        )
        return self.store.get_run(run["run_id"]) or run

    async def tail_run(
        self,
        *,
        run_id: str,
        after_seq: int = 0,
    ) -> AsyncGenerator[tuple[str, dict[str, Any]], None]:
        """Replay ops after `after_seq`, then live-tail a still-running run."""
        run = self.store.get_run(run_id)
        if run is None:
            yield ("error", {"code": "AGENT_CANVAS_RUN_NOT_FOUND", "message": "Unknown run."})
            return
        handle = self._active.get(run_id)
        queue = handle.subscribe() if handle is not None else None
        try:
            base = {"conversation_id": run["conversation_id"], "request_id": ""}
            max_seq = int(after_seq)
            for op in self.store.list_ops_after(run_id=run_id, after_seq=after_seq):
                max_seq = max(max_seq, int(op["seq"]))
                yield ("canvas_op", self._op_event(base, run, op))

            if queue is None:
                refreshed = self.store.get_run(run_id) or run
                if refreshed["status"] == RUN_STATUS_RUNNING:
                    refreshed = self._reconcile_dangling_run(refreshed)
                yield ("final", self._terminal_payload(base, refreshed))
                return

            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_INTERVAL_SECONDS)
                except asyncio.TimeoutError:
                    yield ("keepalive", {})
                    continue
                if item is None:
                    break
                event_type, payload = item
                if event_type == "canvas_op" and int(payload.get("seq") or 0) <= max_seq:
                    continue
                yield item
        finally:
            if handle is not None and queue is not None:
                handle.unsubscribe(queue)

    async def _tail_handle(
        self, handle: ActiveRunHandle
    ) -> AsyncGenerator[tuple[str, dict[str, Any]], None]:
        queue = handle.subscribe()
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_INTERVAL_SECONDS)
                except asyncio.TimeoutError:
                    yield ("keepalive", {})
                    continue
                if item is None:
                    return
                yield item
        finally:
            handle.unsubscribe(queue)

    # ------------------------------------------------------------------
    # SDK plumbing
    # ------------------------------------------------------------------

    def _build_agent_request(
        self,
        request: Any,
        conversation_id: str,
        *,
        message_override: str | None = None,
    ) -> AgentRequest:
        return AgentRequest(
            conversation_id=conversation_id,
            request_id=request.request_id,
            user_id=request.user_id,
            project_id=request.project_id,
            workspace_id=(request.workspace_id or "").strip() or None,
            dataset_table=request.dataset_table,
            message=message_override if message_override is not None else (request.message or ""),
            role=request.role,
            department=request.department,
            clearance=request.clearance,
            response_locale=request.response_locale,
        )

    def _context_sections(self, agent_request: AgentRequest) -> list[str]:
        try:
            all_tables = self.tool_service.dataset_service.list_tables(
                user_id=agent_request.user_id,
                project_id=agent_request.project_id,
                workspace_id=agent_request.workspace_id,
            )
        except Exception:  # noqa: BLE001
            all_tables = [agent_request.dataset_table] if agent_request.dataset_table else []
        if all_tables:
            tables_hint = (
                "Available dataset tables: "
                + ", ".join(f"`{table}`" for table in all_tables)
                + ". Inspect them with describe_table before writing SQL."
            )
        else:
            tables_hint = (
                "No dataset tables have been uploaded in this session yet. "
                "Confirm with list_tables; do not assume any table exists."
            )
        locale = _normalize_response_locale(agent_request.response_locale, agent_request.message)
        language_name = "English" if locale == "en-US" else "Simplified Chinese"
        language_hint = (
            "## Response language\n"
            f"The user interface selected locale is `{locale}`. Write every user-visible "
            f"natural-language field (titles, text content, summaries) in {language_name}. "
            "Keep column names, metric names, and raw data values unchanged."
        )
        return [
            tables_hint + f" User role: {agent_request.role}. Row-level security is enforced automatically.",
            language_hint,
        ]

    def _build_options(
        self,
        *,
        system_text: str,
        tool_definitions: list[dict[str, Any]],
        allowed_tools: tuple[str, ...],
        invoke: Any,
        max_turns: int,
        agent_request: AgentRequest,
    ) -> ClaudeAgentOptions:
        sdk_tools = []
        for definition in tool_definitions:
            function_def = definition.get("function", {})
            tool_name = str(function_def.get("name") or "")
            if not tool_name:
                continue
            description = str(function_def.get("description") or tool_name)
            input_schema = function_def.get("parameters") or {"type": "object", "properties": {}}
            is_read_only = tool_name in READONLY_TOOL_NAMES
            annotations = ToolAnnotations(
                readOnlyHint=is_read_only,
                destructiveHint=not is_read_only,
                idempotentHint=is_read_only,
                openWorldHint=False,
            )

            async def handler(args: dict[str, Any], _tool_name: str = tool_name) -> dict[str, Any]:
                return await invoke(_tool_name, args)

            sdk_tools.append(tool(tool_name, description, input_schema, annotations=annotations)(handler))

        server = create_sdk_mcp_server(name=SDK_MCP_SERVER_NAME, version="1.0.0", tools=sdk_tools)
        env, model = build_sdk_provider_env(self.settings)

        async def can_use_tool(
            tool_name: str,
            input_data: dict[str, Any],
            permission_context: Any,
        ) -> PermissionResultAllow | PermissionResultDeny:
            _ = permission_context
            canonical = _canonical_sdk_tool_name(tool_name)
            if canonical not in allowed_tools:
                return PermissionResultDeny(
                    message=f"Tool '{tool_name}' is outside the agent-canvas tool surface."
                )
            try:
                self.guardrails.validate_tool_call(
                    tool_name=canonical,
                    arguments=input_data if isinstance(input_data, dict) else {},
                    context=AgentGuardrailContext(
                        role=agent_request.role,
                        user_id=agent_request.user_id,
                        project_id=agent_request.project_id,
                    ),
                    agent_mode=True,
                )
            except AgentGuardrailError as exc:
                return PermissionResultDeny(message=exc.message)
            return PermissionResultAllow()

        async def pre_tool_use(
            input_data: dict[str, Any],
            tool_use_id: str | None,
            hook_context: dict[str, Any],
        ) -> dict[str, Any]:
            _ = (tool_use_id, hook_context)
            canonical = _canonical_sdk_tool_name(str(input_data.get("tool_name") or ""))
            if canonical not in allowed_tools:
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": (
                            f"Tool '{canonical}' is outside the agent-canvas tool surface."
                        ),
                    }
                }
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                    "permissionDecisionReason": "Agent-canvas tool call allowed.",
                }
            }

        options = ClaudeAgentOptions(
            tools=[],
            system_prompt=system_text,
            mcp_servers={SDK_MCP_SERVER_NAME: server},
            can_use_tool=can_use_tool,
            hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[pre_tool_use])]},
            permission_mode="default",
            session_id=None,
            resume=None,
            max_turns=max_turns,
            model=model,
            env=env,
            output_format=None,
        )
        # Test seam: scripted SDK clients drive the real tool pipeline through
        # this invoker without a live provider. Harmless for the real client.
        options._cognitrix_tool_invoker = invoke  # type: ignore[attr-defined]
        return options

    async def _run_sdk_conversation(
        self,
        *,
        options: ClaudeAgentOptions,
        message: str,
        collect_text: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Run one SDK conversation; returns the parsed final JSON if any."""
        final_answer: dict[str, Any] | None = None
        text_blocks: list[str] = []
        async with self._sdk_client_factory(options=options) as client:
            await client.query(message)
            async for sdk_message in client.receive_response():
                if isinstance(sdk_message, AssistantMessage):
                    for block in sdk_message.content:
                        if isinstance(block, TextBlock) and block.text:
                            text_blocks.append(block.text)
                            if collect_text is not None:
                                collect_text.append(block.text)
                elif isinstance(sdk_message, ResultMessage):
                    if isinstance(sdk_message.structured_output, dict):
                        final_answer = sdk_message.structured_output
                    elif sdk_message.result:
                        final_answer = _parse_final_answer(sdk_message.result)
        if final_answer is None and text_blocks:
            final_answer = _parse_final_answer("\n".join(text_blocks))
        return final_answer

    async def _invoke_phase_tool(
        self,
        *,
        agent_request: AgentRequest,
        base: dict[str, Any],
        emit: Any,
        exec_ctx: CanvasExecutionContext | None,
        allowed_tools: tuple[str, ...],
        tool_name: str,
        arguments: dict[str, Any],
        step_counter: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if not isinstance(arguments, dict):
            arguments = {}
        canonical = _canonical_sdk_tool_name(tool_name)
        if exec_ctx is not None:
            exec_ctx.tool_steps += 1
            step = exec_ctx.next_step
            exec_ctx.next_step += 1
        else:
            step = int((step_counter or {}).get("step", 1))
            if step_counter is not None:
                step_counter["step"] = step + 1
        step_id = str(uuid.uuid4())
        started_at = time.time()
        emit(
            (
                "tool_use",
                {
                    **base,
                    "tool_name": canonical,
                    "step": step,
                    "arguments": arguments,
                    "step_id": step_id,
                    "started_at": started_at,
                },
            )
        )

        def _observation(payload: dict[str, Any], *, status: str, error: dict[str, Any] | None = None) -> dict[str, Any]:
            emit(
                (
                    "tool_result",
                    {
                        **base,
                        "tool_name": canonical,
                        "step": step,
                        "status": status,
                        "result": payload,
                        "error": error,
                        "from_cache": False,
                        "step_id": step_id,
                        "started_at": started_at,
                        "completed_at": time.time(),
                    },
                )
            )
            return {
                "content": [
                    {"type": "text", "text": json.dumps(payload, ensure_ascii=False, default=str)}
                ],
                "is_error": False,
            }

        # ---- Guardrails ----
        try:
            if canonical not in allowed_tools:
                raise AgentGuardrailError(
                    code="TOOL_NOT_ALLOWED",
                    message=f"Tool '{canonical}' is outside the agent-canvas tool surface.",
                )
            self.guardrails.validate_tool_call(
                tool_name=canonical,
                arguments={k: v for k, v in arguments.items() if not k.startswith("_")},
                context=AgentGuardrailContext(
                    role=agent_request.role,
                    user_id=agent_request.user_id,
                    project_id=agent_request.project_id,
                ),
                agent_mode=True,
            )
            if exec_ctx is not None:
                if exec_ctx.handle.cancel_event.is_set():
                    raise AgentGuardrailError(
                        code="AGENT_RUN_STOPPED",
                        message="The run was stopped by the user. Do not call more tools.",
                    )
                if canonical == "place_chart":
                    self.guardrails.enforce_canvas_chart_budget(exec_ctx.charts_placed)
                elif canonical in {"add_section", "add_text_block"}:
                    self.guardrails.enforce_canvas_block_budget(exec_ctx.blocks_placed)
        except AgentGuardrailError as exc:
            if exec_ctx is not None and exc.code in {
                "AGENT_MODE_CHART_BUDGET_EXCEEDED",
                "AGENT_MODE_BLOCK_BUDGET_EXCEEDED",
            }:
                exec_ctx.budget_exhausted = True
            return _observation({"error": exc.to_detail()}, status="error", error=exc.to_detail())

        # ---- Dispatch through ToolCallingService ----
        invoke_arguments = dict(arguments)
        if exec_ctx is not None and canonical in CANVAS_TOOL_NAMES:
            invoke_arguments["_agent_run"] = {
                "run_id": exec_ctx.run["run_id"],
                "page_id": exec_ctx.run["page_id"],
                "workspace_id": exec_ctx.run["workspace_id"],
                "conversation_id": exec_ctx.request.conversation_id,
            }

        def call() -> ToolCallResponse:
            return self.tool_service.invoke(
                ToolCallRequest(
                    conversation_id=agent_request.conversation_id,
                    request_id=agent_request.request_id,
                    idempotency_key=f"{agent_request.request_id}:{canonical}:{step_id}",
                    user_id=agent_request.user_id,
                    project_id=agent_request.project_id,
                    workspace_id=agent_request.workspace_id,
                    dataset_table=agent_request.dataset_table,
                    role=agent_request.role,
                    department=agent_request.department,
                    clearance=agent_request.clearance,
                    emit_debug_blocks=False,
                    tool=ToolCall(name=canonical, arguments=invoke_arguments),
                )
            )

        response = await anyio.to_thread.run_sync(call)
        if response.status != "success" or not isinstance(response.result, dict):
            error = response.error or {"code": "TOOL_FAILED", "message": "Tool execution failed"}
            return _observation({"error": error}, status="error", error=error)

        result = dict(response.result)
        run = exec_ctx.run if exec_ctx is not None else None
        if exec_ctx is not None and run is not None and canonical in CANVAS_TOOL_NAMES:
            op = result.pop("op", None)
            if canonical == "place_chart":
                spec = None
                if isinstance(op, dict):
                    spec = (op.get("payload") or {}).get("spec")
                if result.get("status") == "placed":
                    exec_ctx.charts_placed += 1
                    if isinstance(spec, dict):
                        asset_id = str(result.get("asset_id") or "")
                        emit(
                            (
                                "spec",
                                {
                                    **base,
                                    "spec": spec,
                                    "chart_id": asset_id.removeprefix("asset-") or None,
                                    "run_id": run["run_id"],
                                },
                            )
                        )
                elif result.get("status") == "error_placeholder":
                    exec_ctx.failed_items += 1
            elif canonical == "add_section":
                exec_ctx.blocks_placed += 1
                exec_ctx.sections.append(str((op or {}).get("payload", {}).get("title") or ""))
            elif canonical == "add_text_block":
                exec_ctx.blocks_placed += 1
            elif canonical == "finish_dashboard":
                exec_ctx.finish_called = True
                exec_ctx.finish_summary = str(result.get("summary") or "")

            if isinstance(op, dict):
                emit(("canvas_op", self._op_event(base, run, op)))

            # Semantic shadow (design D5): remind the model what it has already
            # placed so it never needs a read_canvas tool.
            result["progress"] = {
                "sections_placed": [title for title in exec_ctx.sections if title],
                "charts_placed": exec_ctx.charts_placed,
                "charts_total": exec_ctx.charts_total,
                "failed_items": exec_ctx.failed_items,
            }

        return _observation(result, status="success")

    @staticmethod
    def _op_event(
        base: dict[str, Any], run: dict[str, Any], op: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            **base,
            "run_id": run["run_id"],
            "seq": int(op["seq"]),
            "op_type": str(op["op_type"]),
            "page_id": run["page_id"],
            "payload": op.get("payload") or {},
        }

    def _terminal_payload(self, base: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
        summary = run.get("summary") or {}
        return {
            **base,
            "status": run["status"],
            "run_id": run["run_id"],
            "page_id": run["page_id"],
            "text": str(summary.get("text") or ""),
            "placed_count": int(summary.get("placed") or 0),
            "failed_count": int(summary.get("failed") or 0),
            "skipped_count": int(summary.get("skipped") or 0),
        }

    def _outline_payload(
        self,
        *,
        base: dict[str, Any],
        run: dict[str, Any],
        outline: dict[str, Any],
        confirmation_id: str,
        expires_at: float,
        locale: str,
    ) -> dict[str, Any]:
        return {
            **base,
            "confirmation_type": "dashboard_outline",
            "confirmation_id": confirmation_id,
            "run_id": run["run_id"],
            "canvas_format": run["canvas_format"],
            "page_title": outline.get("title") or "Dashboard",
            "sections": outline.get("sections") or [],
            "proposed_chart_count": int(outline.get("chart_count") or 0),
            "max_chart_count": int(self.settings.agent_mode_max_charts),
            "expires_at": expires_at,
            "truncated": bool(outline.get("truncated")),
            "reason": _localized_text(
                locale,
                en="Review the dashboard outline; deselect any chart you do not need.",
                zh="请确认仪表盘大纲，可取消不需要的图表。",
            ),
        }

    def clear_runtime_state(self) -> None:
        for handle in list(self._active.values()):
            handle.cancel_event.set()
        self._active.clear()


# ---------------------------------------------------------------------------
# Outline helpers
# ---------------------------------------------------------------------------


def _normalize_outline(raw: dict[str, Any], *, max_charts: int) -> dict[str, Any]:
    sections_raw = raw.get("sections")
    if not isinstance(sections_raw, list) or not sections_raw:
        raise ValueError("outline has no sections")

    used_keys: set[str] = set()

    def unique_key(candidate: Any, fallback: str) -> str:
        key = str(candidate or "").strip() or fallback
        while key in used_keys:
            key = f"{key}-{len(used_keys)}"
        used_keys.add(key)
        return key

    sections: list[dict[str, Any]] = []
    chart_count = 0
    truncated = False
    for section_index, section_raw in enumerate(sections_raw, start=1):
        if not isinstance(section_raw, dict):
            continue
        items_raw = section_raw.get("items")
        items: list[dict[str, Any]] = []
        for item_index, item_raw in enumerate(items_raw if isinstance(items_raw, list) else [], start=1):
            if not isinstance(item_raw, dict):
                continue
            kind = str(item_raw.get("kind") or "chart").strip().lower()
            if kind == "chart":
                title = str(item_raw.get("title") or "").strip()
                if not title:
                    continue
                if chart_count >= max_charts:
                    truncated = True
                    continue
                chart_count += 1
                size_preset = str(item_raw.get("size_preset") or "").strip()
                chart_type = str(item_raw.get("chart_type") or "bar").strip() or "bar"
                if size_preset not in SIZE_PRESETS:
                    size_preset = "kpi" if chart_type in {"single_value", "gauge"} else "half"
                items.append(
                    {
                        "key": unique_key(item_raw.get("key"), f"c{section_index}-{item_index}"),
                        "kind": "chart",
                        "title": title,
                        "description": str(item_raw.get("description") or "").strip(),
                        "chart_type": chart_type,
                        "size_preset": size_preset,
                    }
                )
            elif kind == "text":
                content = str(item_raw.get("content") or "").strip()
                if not content:
                    continue
                style = str(item_raw.get("style") or "body").strip()
                items.append(
                    {
                        "key": unique_key(item_raw.get("key"), f"t{section_index}-{item_index}"),
                        "kind": "text",
                        "style": style if style in TEXT_STYLES else "body",
                        "content": content,
                    }
                )
        if items:
            sections.append(
                {
                    "key": unique_key(section_raw.get("key"), f"s{section_index}"),
                    "title": str(section_raw.get("title") or f"Section {section_index}").strip(),
                    "items": items,
                }
            )

    if not sections or chart_count == 0:
        raise ValueError("outline has no chart items")

    return {
        "title": str(raw.get("title") or "Dashboard").strip() or "Dashboard",
        "sections": sections,
        "chart_count": chart_count,
        "truncated": truncated,
    }


def _filter_outline_selection(
    outline: dict[str, Any],
    *,
    selected_item_keys: list[str] | None,
    max_charts: int,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    sections = outline.get("sections") or []
    chart_keys = {
        str(item.get("key"))
        for section in sections
        for item in (section.get("items") or [])
        if item.get("kind") == "chart"
    }
    if selected_item_keys is None:
        selected = set(chart_keys)
    else:
        selected = {str(key).strip() for key in selected_item_keys if str(key).strip()}
        unknown = selected - chart_keys
        if unknown:
            return None, {
                "code": "AGENT_CANVAS_CONFIRMATION_ITEM_MISMATCH",
                "message": "The confirmed selection includes unknown outline items.",
            }
    if not selected:
        return None, {
            "code": "AGENT_CANVAS_CONFIRMATION_EMPTY",
            "message": "Select at least one chart to generate.",
        }
    if len(selected) > max_charts:
        return None, {
            "code": "AGENT_CANVAS_CONFIRMATION_OVERSIZED",
            "message": f"Select at most {max_charts} charts before generating.",
        }

    filtered_sections: list[dict[str, Any]] = []
    chart_count = 0
    for section in sections:
        items = []
        for item in section.get("items") or []:
            if item.get("kind") == "chart":
                if str(item.get("key")) not in selected:
                    continue
                chart_count += 1
            items.append(item)
        if items:
            filtered_sections.append({**section, "items": items})
    filtered = {
        **outline,
        "sections": filtered_sections,
        "chart_count": chart_count,
    }
    return filtered, None


def _default_summary(*, status: str, locale: str, placed: int, failed: int) -> str:
    if status == RUN_STATUS_COMPLETED:
        return _localized_text(
            locale,
            en=f"Dashboard completed: {placed} charts placed.",
            zh=f"仪表盘已完成：共放置 {placed} 个图表。",
        )
    if status == RUN_STATUS_STOPPED:
        return _localized_text(
            locale,
            en=f"Run stopped: {placed} charts were placed and kept.",
            zh=f"运行已停止：已放置的 {placed} 个图表保留在画布上。",
        )
    if status == RUN_STATUS_PARTIAL:
        return _localized_text(
            locale,
            en=f"Run ended early: {placed} charts placed, {failed} failed. Everything placed is kept.",
            zh=f"运行提前结束：已放置 {placed} 个图表，{failed} 个失败。已放置内容全部保留。",
        )
    return _localized_text(
        locale,
        en="Dashboard generation failed before any content was placed.",
        zh="仪表盘生成失败，尚未放置任何内容。",
    )


def _error_final(base: dict[str, Any], *, code: str, message: str) -> list[tuple[str, dict[str, Any]]]:
    return [
        ("error", {**base, "status": "failed", "code": code, "message": message}),
        ("final", {**base, "status": "failed", "code": code, "text": message}),
    ]


_terminal_statuses = TERMINAL_RUN_STATUSES  # re-export convenience for main.py


@lru_cache(maxsize=2)
def _cached_service(settings_key: str) -> AgentCanvasModeService:
    _ = settings_key
    return AgentCanvasModeService()


def get_agent_canvas_mode_service() -> AgentCanvasModeService:
    settings = get_settings()
    settings_key = "|".join(
        [
            str(settings.upload_dir.resolve()),
            "on" if settings.agent_canvas_mode_enabled else "off",
            settings.ai_model.strip(),
        ]
    )
    return _cached_service(settings_key)


def clear_agent_canvas_mode_service_cache() -> None:
    _cached_service.cache_clear()
