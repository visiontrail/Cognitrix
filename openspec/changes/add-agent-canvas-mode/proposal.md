# Proposal: add-agent-canvas-mode

## Why

Today the chat agent answers one question at a time and every chart lands on the canvas only through a manual "add to canvas" click. Lightweight analysts (the target user: someone assembling social/sales statistics into a publishable page) want to state a goal once — "build me a sales overview dashboard" — and watch the AI plan, generate, and lay out a complete publishable canvas end to end. The building blocks already exist (multi-chart planning + confirmation, chart asset archiving, deterministic format-specific layout engines, resumable agent sessions, SSE streaming); what is missing is a long-horizon agent mode that connects them and an agent-controlled path onto the canvas.

## What Changes

- Add an **Agent mode** to the chat composer: when enabled, a user turn is treated as a long-horizon dashboard-building task instead of a single-answer query.
- Agent mode first produces a **dashboard outline** (sections, per-chart one-line descriptions, size presets, estimated chart count) and asks for user approval before executing. Approval is **on by default** and can be disabled via a user setting.
- After approval, the agent executes a long run: it generates charts one by one through the existing BI tool chain and **streams placement operations to the client as new `canvas_op` SSE events**. Charts appear on the canvas progressively, not at the end.
- Every run **creates a fresh web-design page or isolated node-canvas region** ("from-zero generation"); existing canvas content is never touched. Undoing a run deletes its page or provenance-tagged nodes. The run request carries the active publishable canvas format and the client applies ops without changing formats.
- The agent decides **structure and content only** (sections, text blocks, which chart, size preset). Pixel/grid coordinates are always computed by the existing deterministic layout engine (`findSlot`/`compactLayout`) on the client. The model never emits geometry.
- New agent-facing **canvas tools** (`add_section`, `add_text_block`, `place_chart`, `finish_dashboard`) registered through `ToolCallingService` and whitelisted in `agent_guardrails`, mirroring how the web-search tools were added.
- The server keeps a **semantic shadow + op log** of each run (in `agent_sessions.sqlite3`) so tool calls can return synchronously, the model can be reminded of what it has placed so far, and a reconnecting client can replay missed ops.
- **Separate budgets** for agent mode (`AGENT_MODE_MAX_STEPS`, `AGENT_MODE_TIMEOUT_SECONDS`) so the existing 6-step/25s Q&A limits are untouched.
- **Failure isolation**: a failed chart becomes an error placeholder block with retry; the run continues. The user can stop the run at any time and keep what was already placed.
- The run's target canvas format is **soft-locked** while a run is active (banner + stop button, user editing disabled).
- Metadata-only **audit events** for run lifecycle and canvas ops, consistent with the existing audit philosophy.
- Model provider unchanged (DeepSeek gateway via the Claude Agent SDK path).

## Capabilities

### New Capabilities

- `agent-canvas-mode`: The user-facing mode — entry toggle in the chat composer, dashboard-outline approval gate (default on, user-disableable), long-run lifecycle (progress, stop, completion summary, failure isolation), and mode-specific step/time budgets.
- `agent-canvas-tools`: The agent-side canvas tool surface (`add_section`, `add_text_block`, `place_chart`, `finish_dashboard`), the server-side semantic shadow + op log, guardrail whitelisting, and metadata-only audit events.
- `canvas-op-streaming`: The `canvas_op` SSE event contract, client-side application of ops onto a fresh page or isolated run region via deterministic format-specific layout, soft lock during a run, provenance-scoped undo, error placeholder blocks with retry, and reconnect replay from the op log.

### Modified Capabilities

<!-- none: multi-chart-generation, canvas-web-design-mode, and chat-agent-trace requirements are unchanged; agent mode is a separate route that reuses their mechanisms without altering their spec-level behavior -->

## Impact

- **Backend (`apps/api/`)**: `agent_runtime.py` (agent-mode route, outline approval state machine, run loop, op log), `tool_calling.py` (canvas tool registration + dispatch), `agent_guardrails.py` (whitelist), `agent_prompting.py` (agent-mode system prompt section), `chat.py` (SSE `canvas_op` passthrough), `config.py` (new settings), `audit.py` (new event types), `agent_sessions.sqlite3` schema (op log table).
- **Frontend (`apps/web/`)**: chat composer toggle + outline approval card (reuses the multi-chart confirmation UI pattern), `chat-panel.tsx` SSE handling for `canvas_op`, `workspace-store.ts` (create-page-for-run, apply-op actions, soft lock flag, delete-page undo), `web-design-layout.ts` (placement reused as-is), run progress UI (reuses agent-trace components), i18n dictionary entries.
- **Config**: `.env.example` — `AGENT_CANVAS_MODE_ENABLED` (default `false`), `AGENT_MODE_MAX_STEPS`, `AGENT_MODE_TIMEOUT_SECONDS`, `AGENT_MODE_MAX_CHARTS`.
- **Tests**: unit (op log, shadow, guardrails, prompt assembly), API (SSE contract), integration (full run over fake provider), frontend (store actions, approval card, soft lock, replay), security (RBAC on run start, tool whitelist), evals (outline quality on DeepSeek).
- **No breaking changes**: with the flag off, no tools are registered, no SSE event types are emitted, and existing chat/canvas behavior is byte-for-byte unchanged.
