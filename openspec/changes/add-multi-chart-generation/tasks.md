## 1. Backend Contracts And State

- [x] 1.1 Add multi-chart settings for enablement, maximum chart count, and confirmation TTL in `apps/api/config.py`.
- [x] 1.2 Extend chat request models with a typed `multi_chart_confirmation` payload that supports confirm, adjusted selection, and cancel actions.
- [x] 1.3 Add backend data models for `MultiChartPlan`, `MultiChartItem`, pending confirmation state, and grouped chart spec metadata.
- [x] 1.4 Extend `AgentSessionState` persistence with pending multi-chart confirmation and `last_specs` while preserving existing `last_spec` behavior.

## 2. Multi-Chart Planning And Confirmation

- [x] 2.1 Implement a multi-chart preflight planner that detects explicit multi-chart prompts and inferred per-dimension prompts before normal chart generation.
- [x] 2.2 Route planner value discovery through existing guarded BI tools so distinct dimension values respect SQL validation, RLS, and redaction.
- [x] 2.3 Integrate the planner into `AgentRuntime` so single-chart turns continue through the existing path unchanged.
- [x] 2.4 Emit `confirmation_required` SSE events and terminal `final(status="awaiting_confirmation")` responses for detected multi-chart turns.
- [x] 2.5 Validate confirmed, adjusted, canceled, expired, and mismatched confirmation payloads against backend session state.

## 3. Multi-Chart Generation Runtime

- [x] 3.1 Implement `MultiChartGenerationService` to execute confirmed chart items without looping independent chat turns.
- [x] 3.2 Reuse existing `ToolCallingService`, `secure_query_sql()`, RLS/redaction policy, and `ChartStrategyRouter` for each generated chart.
- [x] 3.3 Emit one grouped `spec` SSE event per successful chart with stable `multi_chart_group_id`, `chart_id`, ordering, key, label, and spec fields.
- [x] 3.4 Emit terminal `final` payloads that summarize completed charts and report partial failures without discarding successful charts.
- [x] 3.5 Update `ChatStreamService` session context replay/update logic to preserve multi-chart latest specs and grouped events.

## 4. Frontend State And Streaming

- [x] 4.1 Extend chart/chat TypeScript types so `ChatMessage` and `AssistantResponse` support multiple chart assets while keeping the existing primary `chartAsset`.
- [x] 4.2 Add chat-store state and actions for pending multi-chart confirmations, including confirm, adjusted selection, cancel, and cleanup.
- [x] 4.3 Update `streamAssistantResponse()` to handle `confirmation_required`, collect grouped repeated `spec` events, and submit typed confirmation payloads.
- [x] 4.4 Make asset archiving idempotent for replayed grouped `spec` events and add all generated assets to `asset-store`.
- [x] 4.5 Update mutation success handling to persist multiple chart assets and invalidate chat/asset queries correctly.

## 5. Frontend UI

- [x] 5.1 Build a multi-chart confirmation question box for Designer chat messages with proposed count, labels, limit messaging, selection controls, confirm, and cancel.
- [x] 5.2 Render multiple generated chart cards in one assistant message while preserving the existing single-card rendering path.
- [x] 5.3 Add "add all generated charts to workspace" behavior with stable canvas placement and existing individual add-to-canvas controls.
- [x] 5.4 Add localized strings for multi-chart confirmation, adjusted selection, cancellation, partial completion, and limit errors.
- [x] 5.5 Verify the confirmation box and multi-chart card group fit mobile and desktop chat widths without overlapping controls or chart previews.

## 6. Tests And Verification

- [x] 6.1 Add backend unit tests for planner detection, single-chart bypass, maximum count enforcement, and stale confirmation rejection.
- [x] 6.2 Add backend stream tests asserting confirmation events, no pre-confirmation `spec`, grouped repeated `spec` payloads, final summaries, and partial failure behavior.
- [x] 6.3 Add backend security tests proving planner and generator queries apply RLS, read-only validation, and sensitive-column policy.
- [x] 6.4 Add frontend Vitest coverage for confirmation UI actions, grouped `spec` collection, multi-asset message persistence, and replay idempotency.
- [x] 6.5 Add UI tests for rendering multiple chart cards and adding all generated charts to the workspace.
- [x] 6.6 Run targeted backend pytest, frontend Vitest, and the existing build/lint checks relevant to chat and chart assets.
