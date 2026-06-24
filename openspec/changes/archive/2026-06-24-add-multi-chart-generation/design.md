## Context

Designer chat currently has a single-chart output contract. `AgentRuntime._finalize_turn()` appends one `spec` SSE event, `ChatStreamService` stores one `latest_spec`, `use-chat.ts` keeps only `latestSpec`, `toChartAsset()` creates one `ChartAsset`, and `ChatMessage.chartAsset` references one card. That contract is workable for ordinary "show me turnover by month" prompts, but it is the wrong shape for prompts like "create one headcount trend chart for every department".

The requested behavior has two distinct phases:

1. The system recognizes that a turn should produce multiple charts.
2. The user confirms the inferred chart set/count before the system performs the heavier multi-chart generation work.

The confirmation gate is not optional. Even when the prompt explicitly asks for multiple charts, the user still needs a visible checkpoint because "all departments" can mean three charts in demo data or dozens in production data.

## Goals / Non-Goals

**Goals:**

- Detect explicit and inferred multi-chart intent in Designer chat turns.
- Ask for user confirmation whenever the system plans to produce more than one chart.
- Let the user confirm, narrow, adjust count/values, or cancel the proposed chart set.
- Generate multiple chart specs in a dedicated bounded flow after confirmation.
- Render and persist multiple chart assets from one assistant response.
- Preserve the current single-chart path and the existing `spec` event for ordinary turns.

**Non-Goals:**

- No portal chat support in this change.
- No automatic dashboard layout generation beyond making returned chart assets available to the existing workspace canvas.
- No unbounded "chart for every value" fan-out.
- No new external model/provider dependency.
- No change to write-ingestion approval semantics.

## Decisions

### 1. Add a preflight multi-chart planner before normal generation

Before entering the normal chart finalization path, `AgentRuntime` will run a lightweight multi-chart preflight for ordinary query turns. The planner combines deterministic cues ("each department", "all regions", "分别", "每个", explicit numeric chart requests) with the model's structured judgment when needed. If it decides the turn is still single-chart, the existing path continues unchanged.

When the planner needs actual segment values, it may call existing read-only BI tools such as `get_distinct_values` through `ToolCallingService`, so the same SQL guardrails, RLS, role filtering, and dataset scoping apply. The planner output is a bounded `MultiChartPlan` containing a grouping dimension, proposed items, chart type preference, metric/query intent, inferred count, confidence, and a human-readable reason.

Alternative considered: let the main ReAct agent start generating and infer multi-chart intent from the final JSON. That is too late because the user must confirm before the expensive work begins.

### 2. Model confirmation as session state, not frontend-only state

`AgentSessionState` will store an optional pending multi-chart confirmation with `confirmation_id`, original request metadata, proposed items, expiry, and max chart count. The frontend will also store a lightweight pending UI state for rendering, but the backend remains authoritative.

The stream for a detected multi-chart turn will emit:

- `planning` events explaining the detection.
- `confirmation_required` with `confirmation_type: "multi_chart_generation"`, a `confirmation_id`, proposed chart items, count, limit, and default selection.
- `final` with `status: "awaiting_confirmation"` so the stream terminates cleanly.

The subsequent confirmed request will include a typed `multi_chart_confirmation` payload on `POST /chat/stream` rather than relying on natural-language parsing of "yes" or "generate 5". The backend validates the payload against the pending confirmation before generating charts.

Alternative considered: ask the user with a plain assistant message and parse their next text answer. That is brittle, hard to localize, and unsafe when the user edits the count or selected departments.

### 3. Generate charts through a dedicated bounded orchestrator

After confirmation, a `MultiChartGenerationService` will execute the plan. It will not simply loop independent chat turns, because that would duplicate planning, pollute conversation history, and make partial failure hard to report. Instead it will reuse existing primitives:

- `ToolCallingService` for data access.
- `secure_query_sql()` and existing RLS/redaction policy for SQL safety.
- `ChartStrategyRouter` and existing chart spec normalization for renderable specs.
- Agent trace events for visibility into planning, tool calls, and failures.

The first implementation should execute chart items sequentially or with tightly bounded concurrency. DuckDB session isolation and predictable SSE ordering are more important than raw throughput for this feature.

Alternative considered: request one giant final answer containing all chart specs. That creates large fragile JSON payloads and prevents the UI from rendering successful charts progressively.

### 4. Stream repeated `spec` events with group metadata

The current `spec` SSE event remains the canonical chart-output event. Multi-chart generation will emit one `spec` event per chart. Each payload will include:

- `multi_chart_group_id`
- `chart_id`
- `chart_index`
- `chart_count`
- `chart_key`
- `chart_label`
- `spec`

`final` will include a chart summary array and aggregate status. For backward compatibility, `AgentSessionState.last_spec` remains populated with the first successful chart or the latest chart according to existing behavior, while a new `last_specs` list stores all successful chart specs for the turn.

Alternative considered: introduce a `multi_spec` event. Reusing `spec` keeps the renderer path simple and lets existing SSE infrastructure replay the event stream without special batching rules.

### 5. Make frontend chat messages explicitly multi-asset capable

Frontend types will add `ChatMessage.chartAssets?: ChartAssetReference[]` while keeping `chartAsset?: ChartAssetReference` as a compatibility alias for the primary/first chart. `AssistantResponse` and mutation success handling will similarly support `chartAssets: ChartAsset[]`.

`streamAssistantResponse()` will collect all `spec` events for a multi-chart group and archive each as an individual `ChartAsset`. The assistant message will render a compact multi-chart group with one card per generated chart, plus controls expected by the current workspace workflow: add individual chart to canvas and add all generated charts to canvas.

Alternative considered: create one combined chart asset containing nested specs. That would fight the current workspace model, where each chart node points at one `ChartAsset`.

### 6. Enforce explicit limits

Add a backend limit such as `AGENT_MAX_MULTI_CHARTS` with a conservative default. If the inferred item set exceeds the limit, the confirmation UI must require the user to narrow the selection or count before generation can start. The backend must reject confirmed payloads that exceed the limit even if the frontend is bypassed.

## Risks / Trade-offs

- [Risk] False positive detection interrupts ordinary single-chart requests. → Mitigation: require more than one concrete chart item or high-confidence language before emitting confirmation; keep the user able to cancel and continue with a single-chart request.
- [Risk] "All departments" expands into too many charts. → Mitigation: hard backend limit, distinct-value preview, and selection/count controls in the confirmation UI.
- [Risk] Partial failures make the response feel broken. → Mitigation: emit successful `spec` events as they complete, include failed chart labels in `final`, and keep the assistant message usable when at least one chart succeeds.
- [Risk] Replayed SSE streams could duplicate assets. → Mitigation: use stable `chart_id` values derived from `multi_chart_group_id` and chart key; frontend asset insertion must be idempotent.
- [Risk] Session state becomes inconsistent if the user confirms an expired plan. → Mitigation: confirmation payloads carry `confirmation_id`; backend rejects stale, missing, or mismatched confirmations with an `error` and a terminal `final`.

## Migration Plan

1. Add backend models and settings for multi-chart plans, confirmation state, limits, and typed confirmation request payloads.
2. Add the preflight planner and confirmation event emission without changing the existing single-chart path.
3. Add the multi-chart execution service and repeated grouped `spec` events.
4. Extend frontend chat and asset types to support `chartAssets` arrays while preserving `chartAsset`.
5. Add the confirmation UI and multi-chart message rendering.
6. Add tests across planner detection, confirmation validation, SSE grouping, frontend asset archiving, and UI rendering.

Rollback is straightforward: disable the preflight planner with a feature flag or limit the detector to always return single-chart. Existing single-chart behavior remains intact.

## Open Questions

- Should the default multi-chart limit be 8, 10, or 12 for local development and production?
- Should "add all charts to canvas" use the current free-canvas grid placement only, or also auto-place charts into web-design zones when the active canvas is web-design?
