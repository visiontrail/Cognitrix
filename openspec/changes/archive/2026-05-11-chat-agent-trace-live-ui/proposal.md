## Why

Today the Designer Conversation panel (`ChatPanel` → `MessageList`) consumes only the `spec` and `final` SSE events emitted by `AgentRuntime`; the `planning`, `tool_use`, `tool_result`, and `error` events are discarded by `streamAssistantResponse` in `apps/web/hooks/use-chat.ts`. As a result, while the agent is working — sometimes for tens of seconds across multiple tool calls — users see a static "sending" state and have no insight into what the model is doing. Mainstream chat UIs (Claude.ai, Claude Code, ChatGPT) all expose a live "thinking + tool" trace; the absence of this affordance makes Cognitrix feel slower and less trustworthy than it is, and makes it hard to diagnose stuck or low-quality turns.

The backend already emits the right events end-to-end (`agent_runtime.py` → `chat.py` SSE → `lib/chat/sse.ts`). This change wires those events through to the chat surface and adds the disclosure pattern.

## What Changes

- Capture the full per-turn agent trace (planning thoughts, tool_use, tool_result, intermediate text, errors) in the chat store, keyed by the assistant message id.
- Render the trace inline in `MessageItem` while the turn is streaming, with each event shown as a compact row (icon + tool name / thought summary, tool args + result preview on expand).
- Auto-collapse the trace once the turn ends (final event received OR error OR stream closed). Replace it with a one-line summary chip ("Thought for 4s · 3 tool calls") that the user can click to re-expand for inspection.
- Persist trace step previews to localStorage (key: `cognitrix:chat-trace:v1:{userId}`) so re-opening or reloading the session keeps the full trace expandable; raw tool result payloads are excluded from persistence. Saved views do not include trace bodies.
- Backend stays largely as-is; only minor additions: a stable `step_id` and `started_at` timestamp on each `tool_use`/`tool_result` payload so the UI can group, time, and de-duplicate steps reliably.
- Disclosure UI must be **restrained**: small monochrome icons, no animation other than a single pulsing dot during streaming, collapsed-by-default once the turn finishes.

Out of scope: streaming the final answer text token-by-token (separate concern), exposing trace in the published portal chat, exposing trace in saved views.

## Capabilities

### New Capabilities
- `chat-agent-trace`: live disclosure of agent planning, tool calls, and tool results in the Designer Conversation panel, with auto-collapse-on-completion.

### Modified Capabilities
- `chart-query-agent`: tighten the existing SSE event contract — every `tool_use` and `tool_result` payload MUST carry `step_id` and `started_at` so the UI can group call/result pairs and compute durations. The portal chat surface already streams these events but does not need to render the disclosure UI; this change does not modify portal rendering.

## Impact

- Backend: `apps/api/agent_runtime.py` (add `step_id`/`started_at` to tool event payloads), `apps/api/chat.py` (no logic change, contract reaffirmed in tests), `tests/api/test_chat_stream.py` and `tests/integration/test_agent_runtime.py` (assert new fields).
- Frontend: `apps/web/hooks/use-chat.ts` (consume planning/tool_use/tool_result/error events), `apps/web/stores/chat-store.ts` (add per-message `trace` slice + `traceState: "live" | "collapsed"`), `apps/web/types/chat.ts` (extend `ChatMessage` with optional `trace` field), `apps/web/components/chat/message-item.tsx` (render trace), new `apps/web/components/chat/agent-trace.tsx` and `agent-trace-step.tsx`, `apps/web/lib/i18n/dictionary.ts` (new strings).
- Tests: new Vitest unit tests for the trace component (live → collapsed transition, expand-on-click, error rendering); update existing chat-panel tests that assume only `final`/`spec` events.
- No DB or migration impact. No change to saved-view payloads. No change to the published portal chat surface.
