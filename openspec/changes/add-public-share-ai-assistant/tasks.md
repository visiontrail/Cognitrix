## 1. Publish Data Contract

- [x] 1.1 Extend frontend chart asset/node types to carry explicit assistant raw rows separate from render rows.
- [x] 1.2 Populate assistant raw rows from backend chat final/spec payload when charts are generated and archived as assets.
- [x] 1.3 Update canvas add-to-workspace and workspace snapshot serialization so assistant rows survive node creation, autosave, reload, and publish preparation.
- [x] 1.4 Extend `CanvasPublishSnapshot` and publish request models to send render rows plus assistant rows and assistant completeness metadata per chart.

## 2. Snapshot Writing

- [x] 2.1 Update `SnapshotWriter` to write capped render rows to `data.json` and full redacted assistant rows to `assistant-data.jsonl`.
- [x] 2.2 Add manifest-level `assistant.available` metadata and per-chart `assistant_data_path`, `assistant_row_count`, and `assistant_data_available` fields.
- [x] 2.3 Ensure assistant rows use the same `forbidden_sensitive_columns()` and `redact_rows()` pipeline as render rows.
- [x] 2.4 Handle incomplete assistant rows by marking assistant unavailable or failing publish with an explicit validation error.
- [x] 2.5 Preserve legacy snapshot rendering for manifests that do not include assistant metadata.

## 3. Public Snapshot Agent Backend

- [x] 3.1 Update `SnapshotDuckDBCache` to key cache entries by published page id and version and load tables from `assistant_data_path`.
- [x] 3.2 Upgrade `ChartQueryAgent.run_turn()` to run a real `ClaudeSDKClient`/`ClaudeAgentOptions` loop with snapshot-only tools.
- [x] 3.3 Stream `planning`, `tool_use`, `tool_result`, `final`, and `error` events with `step_id`, `started_at`, and `completed_at` correlation metadata.
- [x] 3.4 Keep `SQLReadOnlyValidator` enforcement against explicit snapshot table and column allowlists.
- [x] 3.5 Add `POST /public/pages/{token}/chat` with public token resolution, active/revoked handling, no-store headers, rate limiting, and optional visibility authorization parity with manifest/chart routes.

## 4. Public Assistant Frontend

- [x] 4.1 Add public API client support for streaming assistant requests with `message`, `conversation_id`, and optional `chart_id`.
- [x] 4.2 Add `AI Assistant` action to `PublicCanvasActions` beside Export, Print, and the theme toggle when manifest assistant metadata allows it.
- [x] 4.3 Build the right-side public assistant drawer with local conversation state, streaming trace rows, final answer rendering, and error handling.
- [x] 4.4 Wire the drawer into web-page, free-layout, and fixed-size public canvas renderers without breaking export/print capture exclusions.
- [x] 4.5 Add i18n strings for assistant button, drawer title, input placeholder, running states, unavailable state, and errors.

## 5. Tests and Verification

- [x] 5.1 Add backend publish-flow tests proving assistant rows are redacted, uncapped by `AGENT_MAX_SQL_ROWS`, and recorded in manifest metadata.
- [x] 5.2 Add backend public-route tests for `/public/pages/{token}/chat` success, revoked token 404, missing assistant data, and no internal leakage in SSE payloads.
- [x] 5.3 Add `ChartQueryAgent` unit tests for assistant-data loading, cache reuse/eviction, read-only SQL validation, and tool allowlist enforcement.
- [x] 5.4 Add frontend unit tests for public assistant action visibility, drawer open/close, streaming event rendering, and legacy manifest unavailable behavior.
- [x] 5.5 Run focused backend pytest files and frontend Vitest coverage for publish/public-page flows.
