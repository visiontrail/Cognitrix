## Context

`AgentRuntime` (`apps/api/agent_runtime.py`) already runs a ReAct loop and emits SSE events through `ChatStreamService` (`apps/api/chat.py`) for every meaningful step:

- `planning` — model thinking blocks (when present)
- `tool_use` — pre-tool invocation, with name + arguments
- `tool_result` — tool output (truncated for size)
- `spec` — final chart/table spec
- `final` — terminal natural-language answer
- `error` — guardrail or runtime failure

The Designer Conversation flow (`apps/web/hooks/use-chat.ts` → `streamAssistantResponse`) currently throws away everything except `spec`, `final`, and (only as a fallback) `error`. The legacy `ChatWorkbench` test surface (`apps/web/components/workbench/chat-workbench.tsx`) does collect `tool_use`/`tool_result`/`planning` into a flat `toolTrace` array, but it is unstyled debug output (`<pre>{JSON.stringify(...)}</pre>`) and is not what the production `ChatPanel` renders.

The user expectation, set by Claude.ai and Claude Code, is: while the agent works, show *what it is doing right now*; once it finishes, hide that work behind a one-line summary so the conversation log stays readable.

## Goals / Non-Goals

**Goals:**

- Surface every agent step (planning thought, tool call, tool result, error) in the chat panel as it happens.
- Visually distinguish "live" trace (during streaming) from "collapsed" trace (after the turn ends), with the collapsed form being a single discreet line that does not crowd the conversation.
- Let the user click the collapsed summary to re-expand the full trace for inspection.
- Keep the visual design restrained: no rainbow icons, no aggressive animation, monospace only for tool args/results.
- Cleanly handle interruption: if the stream errors mid-turn, the trace stays expanded with the error step highlighted; subsequent turns work normally.

**Non-Goals:**

- Streaming the final answer text token-by-token. (`final` arrives as one payload today — that is fine for this change.)
- Exposing the trace in the **published portal** chat (`/portal/pages/{page_id}/chat`). That surface uses the same SSE contract but its UI requirements are different and out of scope here.
- Persisting full trace bodies into saved views or to the backend. Trace step previews are persisted client-side (localStorage), but raw tool result payloads are excluded from persistence to avoid storing large query result sets.
- Adding new agent capabilities or tools.
- Re-architecting `AgentRuntime`. Backend changes are limited to enriching existing payloads.

## Decisions

### 1. Trace lives on the assistant `ChatMessage`, not as a separate sibling component

**Decision:** Extend `ChatMessage` with an optional `trace` field. `MessageItem` decides how to render it based on `trace.state`.

**Why:** Tying trace lifetime to the message it belongs to means scrolling, message reordering, deletion, and session switching all "just work" with no extra state plumbing. The collapsed summary needs to live next to the assistant bubble forever; the live expanded view also lives next to that bubble — they are the same component in two states.

**Alternative considered:** A floating "agent activity" panel above the composer (the way some IDEs do it). Rejected because it disconnects the trace from the answer it produced — once you scroll up to a previous turn, you cannot tell what tool calls produced it.

### 2. Two trace states: `live` and `collapsed`

**Decision:** `trace.state` is exactly `"live"` while the SSE stream for that turn is open, and flips to `"collapsed"` exactly once on the first of: `final` event received, `error` event received, or stream reader closes. The user can manually toggle to `"expanded"` after collapse, but new turns always start `live`.

**Why:** A single boolean (live vs not-live) drove by stream lifecycle is unambiguous and matches user expectation. We deliberately do not auto-collapse mid-stream even if the agent pauses (e.g., between tool calls).

**Edge case:** if the page reloads while a turn is mid-flight, the SSE connection drops; on reload the persisted message has no trace bodies and shows just the user message with no assistant follow-up. We do **not** try to resume mid-turn traces — the existing `last_event_id` replay path in `ChatStreamService` is for resuming the answer, not the trace UI. For completed turns, trace step previews are persisted to localStorage so the full trace remains viewable after reload.

### 3. Backend adds `step_id` and `started_at` to tool events; that's it

**Decision:** `agent_runtime._sdk_pre_tool_use_hook` and `_sdk_post_tool_use_hook` (and the equivalent paths for non-SDK invocations) include two additional fields in their emitted payload:

- `step_id: str` — UUID generated at `pre_tool_use`, copied verbatim onto the matching `tool_result` so the UI can pair them.
- `started_at: float` — epoch seconds at `pre_tool_use`; `tool_result` additionally carries `completed_at` so the UI can compute duration.

**Why:** Today the UI has to match tool call/result pairs heuristically by ordering, which breaks when the agent issues parallel tool calls. With explicit IDs the UI logic is trivial: maintain a `Map<step_id, TraceStep>` and update entries as events arrive.

**Alternative considered:** Have the UI generate its own correlation ID from `(tool_name + index)`. Rejected: brittle when the same tool is called multiple times in one turn (extremely common — `describe_table` then `execute_readonly_sql` then `execute_readonly_sql` again).

### 4. Trace rendering — what each step looks like

**Decision:** Each step is one row, ~32px tall, structure:

```
[icon]  [label]                                [duration]  [chevron]
        [optional one-line subtitle preview]
```

- **Planning step**: brain icon, label = first 80 chars of the thought; expand reveals the full thought as wrapped prose.
- **Tool step**: small box icon, label = tool name (e.g., `execute_readonly_sql`); subtitle = a one-line preview of the most identifying argument (the SQL's first 80 chars, or the table name); expand reveals full arguments + first ~20 lines of result + a "result truncated, N more rows" hint when applicable.
- **Error step**: warning icon (terracotta), label = error code/message; expand reveals stack-trace-equivalent detail when present.

While `live`, the most recent step has a single pulsing dot to its left and is auto-scrolled into view. Earlier steps are static.

While `collapsed`, the entire block becomes one line: `Thought for {duration} · {N} tool calls · click to expand`. If the turn ended in an error, that line uses the terracotta error color and reads `Errored after {duration} · click to inspect`.

### 5. State store shape

**Decision:** Add to `chat-store.ts`:

```ts
type TraceStep =
  | { kind: "planning"; id: string; text: string; startedAt: number }
  | {
      kind: "tool";
      id: string; // step_id from backend
      tool: string;
      args: Record<string, unknown>;
      result?: unknown;
      resultPreview?: string;
      startedAt: number;
      completedAt?: number;
      status: "running" | "ok" | "error";
    }
  | { kind: "error"; id: string; message: string; code?: string; at: number };

type MessageTrace = {
  state: "live" | "collapsed" | "expanded";
  steps: TraceStep[];
  startedAt: number;
  endedAt?: number;
};

// New store slices:
// traceByMessageId: Record<string, MessageTrace>
// startTrace(messageId), pushTraceStep(messageId, step), patchTraceStep(messageId, stepId, partial), endTrace(messageId, reason: "final" | "error" | "closed"), setTraceState(messageId, state)
```

The `ChatMessage` itself carries `traceSummary?: { stepCount: number; durationMs: number; status: "ok" | "error" }` as a lightweight fallback. The full `MessageTrace` (steps with previews, excluding raw result payloads) is persisted separately to localStorage under `cognitrix:chat-trace:v1:{userId}` and restored on `initForUser`, so the collapsed chip remains expandable after a page reload.

### 6. Streaming pipeline — where the wiring goes

**Decision:** All SSE consumption stays in `streamAssistantResponse` in `use-chat.ts`. We synthesize the assistant message id eagerly (before the first event arrives) so trace events have a stable target id from event #1. The function pseudocode:

```ts
const messageId = `msg-${generateId()}`;
const traceStartedAt = Date.now();
useChatStore.getState().startTrace(messageId, traceStartedAt);

for await (const event of parseSSEStream(...)) {
  switch (event.event) {
    case "planning":
      pushTraceStep(messageId, { kind: "planning", ... });
      break;
    case "tool_use":
      pushTraceStep(messageId, { kind: "tool", id: payload.step_id, status: "running", ... });
      break;
    case "tool_result":
      patchTraceStep(messageId, payload.step_id, { result, resultPreview, completedAt, status: payload.status });
      break;
    case "spec":
      latestSpec = payload.spec;
      break;
    case "error":
      pushTraceStep(messageId, { kind: "error", ... });
      break;
    case "final":
      finalText = payload.text;
      break;
  }
}

useChatStore.getState().endTrace(messageId, terminalReason);
// ... existing assistantMessage build, with messageId reused and traceSummary attached
```

### 7. Visual restraint — explicit constraints

- Icons: 14px, `stroke-stone-gray` (already in palette). No color except the error step.
- Animation: a single 1.2s pulse on the live-step dot. No spinner, no shimmer on rows.
- Typography: tool name in `text-label`, args/result body in `font-mono text-caption`.
- Spacing: each row `py-1.5`, never wider than the assistant bubble (`max-w-[85%]`).
- Collapsed chip: `text-caption text-stone-gray`, single button-like row, hover underline only.

This matches the existing `genui/state-panels.tsx` aesthetic (warm cream, monochrome) rather than introducing a new visual style.

## Risks / Trade-offs

- **Risk:** SSE events arrive out of order under jittery network → tool_result before tool_use → orphan step. **Mitigation:** `pushTraceStep` for `tool_result` with an unknown `step_id` creates a stub step in `running` state and immediately patches it; reconciles when the matching `tool_use` arrives.
- **Risk:** Long-running tools (10s+ SQL) make the trace look stuck. **Mitigation:** running steps display elapsed time live (recompute on a 1Hz tick while `state === "live"`).
- **Risk:** Very long traces (20+ steps) push the answer below the fold. **Mitigation:** while `live`, the trace is fully expanded but capped at a max-height of 60vh with internal scroll; on collapse it becomes one line.
- **Risk:** Tool result payloads can be megabytes (raw query results). **Mitigation:** `tool_result` payloads are already truncated by `agent_runtime.py`; on the UI side, `result` is stored as-is but `resultPreview` is computed once at receive time and the expanded view shows only `resultPreview`. Full `result` is reachable through a "view full result" affordance only.
- **Trade-off:** Trace step previews are persisted to localStorage; raw tool result payloads are excluded. → Users get full step-by-step inspection after reload without the storage cost of large query result sets. Full raw results remain accessible in the underlying audit log.
- **Trade-off:** We do not stream the final text token-by-token. → Users who care about perceived latency get the trace as their progress signal instead, which is more informative than partial tokens.

## Migration Plan

This is additive, no migration. Rollout order:

1. Backend payload enrichment (`step_id`, `started_at`, `completed_at`) — backwards compatible, old clients ignore the extra fields.
2. Frontend store + types + SSE consumer changes.
3. UI components (`agent-trace.tsx`, `agent-trace-step.tsx`) wired into `MessageItem`.
4. i18n strings + tests.

Rollback: revert frontend commit. Backend change is harmless on its own.

## Open Questions

- Should the **collapsed** chip include the tool list (e.g., `used: list_tables, execute_readonly_sql ×2`) or stay strictly minimal (`3 tool calls`)? Default in this design: minimal. Revisit after dogfooding.
- For an `error` mid-turn, should we still show the partial chart spec if one was emitted before the error? Default: yes — show whatever arrived. The error step in the trace makes the failure obvious.
