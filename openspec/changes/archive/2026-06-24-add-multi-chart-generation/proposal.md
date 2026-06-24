## Why

The current chat runtime and UI effectively treat a turn as producing one primary chart spec plus one final answer. This breaks down when a user asks for per-segment analysis, such as "generate the same chart for every department", because the agent either has to compress multiple departmental views into one chart or leave the user to repeat the same request manually.

Users need a controlled way for the AI to recognize multi-chart intent, confirm the chart count before spending tokens and query time, then return several chart assets in a single conversational flow.

## What Changes

- Add a multi-chart generation flow for Designer chat turns when the AI detects that the right answer is multiple charts, including prompts like "for each department" or explicit requests for several charts.
- Before generating multiple charts, require an interactive confirmation step that shows the inferred chart set/count and lets the user confirm, adjust, or cancel.
- After confirmation, route the turn into a dedicated multi-chart generation path that plans, queries, and emits multiple chart specs as separate chart assets tied to one assistant response.
- Preserve existing single-chart behavior when the user asks for one chart or declines multi-chart generation.
- Add backend and frontend contracts so multiple `spec`-like outputs can be streamed, archived, rendered, and saved without relying on arrival order.

## Capabilities

### New Capabilities

- `multi-chart-generation`: Detect, confirm, generate, stream, render, and persist multiple chart outputs from one Designer chat turn.

### Modified Capabilities

<!-- None - no existing spec-level requirements are changing. -->

## Impact

- Backend: `apps/api/agent_runtime.py`, `apps/api/chat.py`, `apps/api/tool_calling.py`, `apps/api/chart_strategy.py`, session persistence under `UPLOAD_DIR/state/agent_sessions.sqlite3`, and related tests for SSE ordering, confirmation state, and multi-spec emission.
- Frontend: `apps/web/hooks/use-chat.ts`, chat and asset stores, `ChatPanel`, chart asset archiving, message rendering, confirmation modal/question UI, workspace asset insertion, and i18n strings.
- Contracts: chat SSE payloads must support grouped multi-chart emissions with stable identifiers; chat message and chart asset types must represent multiple generated specs from a single turn.
- Agent behavior: prompting and guardrails must distinguish legitimate multi-chart generation from runaway chart fan-out and enforce configured limits.
