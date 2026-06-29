## Context

Public pages are served from immutable publish snapshots resolved by a high-entropy token at `/p/{token}` and backend routes under `/public/pages/{token}`. The public renderer already has an action group for export, print, and theme switching. Published chart data is written under `UPLOAD_DIR/published/{workspace_id}/{version}/charts/{chart_id}/`, but current snapshot writing caps rows at `AGENT_MAX_SQL_ROWS`, and the existing `ChartQueryAgent` is a placeholder oriented around the removed `/portal/pages/{page_id}/chat` route.

The requested assistant needs three things to be true at the same time: public visitors can open a drawer and ask questions, the agent can inspect all raw rows associated with published chart nodes, and the runtime cannot cross from a public token into the designer's live DuckDB session or unpublished workspace state.

## Goals / Non-Goals

**Goals:**
- Add a public-page AI Assistant button beside the existing public Export, Print, and theme controls.
- Provide a right-side assistant drawer that supports page-level and chart-specific questions over all chart-node datasets in the active published snapshot.
- Persist assistant-readable full publishable rows for every published chart node, after the existing sensitive-column filtering/redaction pipeline.
- Run public assistant turns through a real `ClaudeSDKClient` / `ClaudeAgentOptions` loop using snapshot-only tools and the same SSE event vocabulary as the designer query runtime.
- Resolve assistant access by public token, active/revoked state, and the same optional visibility authorization used by public manifest/chart reads.

**Non-Goals:**
- The assistant will not query live DuckDB sessions, uploaded source files, workspace drafts, unpublished chart assets, workspace membership, or designer chat history.
- The assistant will not edit charts, save views, mutate workspaces, or change published snapshots.
- The first implementation will not provide durable public visitor accounts or long-term server-side public chat history.
- Existing legacy snapshots will not be backfilled in place; republishing creates assistant-complete snapshots.

## Decisions

### Store Assistant Rows Separately From Render Rows

Publish snapshots should continue to support lightweight chart rendering, but the assistant needs full rows. Each chart entry should therefore contain:
- `data_path`: the existing render-data path used by the public chart endpoint.
- `assistant_data_path`: a new full publishable row file, preferably JSONL for streaming writes and DuckDB `read_json_auto` loading.
- `assistant_row_count`, `assistant_data_available`, and redaction/truncation metadata.

The assistant file MUST contain every row available in the chart asset at publish time after `forbidden_sensitive_columns()` and `redact_rows()`. It MUST NOT silently apply `AGENT_MAX_SQL_ROWS`; that cap can still apply to chart render payloads if needed. If the frontend does not provide full raw rows for a chart asset, the publish request should fail or mark the assistant unavailable for that chart rather than claiming complete coverage.

Alternative considered: reuse `data.json` for both rendering and assistant queries. That is simpler but makes every public chart fetch potentially download large raw datasets and couples chart-render performance to agent context size.

### Preserve Raw Rows Earlier in the Frontend Asset Path

The frontend currently reconstructs publish rows from `ChartNodeData.spec.echartsOption` via `extractChartRows()`. That is not a reliable contract for "all raw rows" because chart specs may contain aggregated or transformed data. The chart asset and node data model should carry explicit publish rows, such as `rawRows` or `assistantRows`, populated from the backend `final/spec` payload when the designer generates the chart. Publishing should send those rows in a dedicated field separate from render rows.

Alternative considered: make the backend recover rows from historical tool traces or live session tables at publish time. That is brittle, slower, and violates snapshot isolation.

### Public Token Chat Endpoint Reuses Snapshot Authorization

Add `POST /public/pages/{token}/chat` as an SSE endpoint. It should call the same token resolution, rate-limit, no-store, active/revoked handling, and optional visibility authorization helpers used by manifest and chart-data routes. Unknown, revoked, inactive, or missing-snapshot tokens remain indistinguishable where practical. The request body should include `message`, optional `conversation_id`, and optional `chart_id`.

Alternative considered: expose the existing page-id route. Page ids are internal identifiers and do not represent the public-link authorization model.

### Implement `ChartQueryAgent` As A Real Claude Agent SDK Loop

`ChartQueryAgent.run_turn()` should be upgraded from its current placeholder to instantiate `ClaudeSDKClient` with `ClaudeAgentOptions`, load plugins assigned to `ChartQueryAgent`, and expose only snapshot-safe tools:
- `list_snapshot_tables`
- `describe_snapshot_table`
- `query_snapshot_table`

The tool implementation should load `assistant_data_path` into an in-memory DuckDB cache keyed by published page id and snapshot version. SQL execution must use `SQLReadOnlyValidator` with explicit allowed tables and columns. Tool calls and results should stream as `planning`, `tool_use`, `tool_result`, `final`, and `error`, including `step_id`, `started_at`, and `completed_at` correlation fields.

Alternative considered: call the designer `AgentRuntime` with a different prompt. That gives the public assistant too much surface area because the designer runtime owns live BI tools, session state, save-view behavior, and dataset access.

### Keep Public Conversation State Ephemeral

The drawer should keep message history in client state for the active page session. The backend can accept `conversation_id` for trace correlation and may keep a short-lived in-memory conversation cache if the SDK loop needs prior turns. It should not persist anonymous public conversations to the existing designer `agent_sessions.sqlite3` store in this change.

Alternative considered: persist public visitor conversations in SQLite immediately. That creates retention and identity questions that are not needed for the initial assistant.

## Risks / Trade-offs

- Full assistant rows can make publish snapshots much larger -> store assistant rows separately, use JSONL streaming writes, add tests for large row counts, and expose clear manifest counts.
- Public assistant usage can increase model cost -> apply public endpoint rate limits, reuse the existing snapshot DuckDB cache, and keep the tool set small.
- Legacy snapshots lack full assistant data -> render them unchanged, hide or disable the assistant when `assistant_data_available` is false, and require designers to update publish for complete assistant support.
- The assistant can only answer from chart-node rows, not arbitrary source tables -> make the system prompt and UI wording scope answers to published page data.
- Duplicate chart nodes may point to the same asset -> deduplicate snapshot tables by chart asset id while preserving node/chart metadata for prompt context.

## Migration Plan

1. Extend chart asset/node and publish payload types to carry explicit full publishable rows.
2. Extend snapshot writing to write `assistant_data_path` and manifest metadata for new publishes.
3. Upgrade `ChartQueryAgent` to load assistant files and stream through Claude Agent SDK.
4. Add the public token chat route and frontend drawer.
5. Keep existing public snapshots renderable; assistant support appears after republish/update publish creates assistant-complete snapshots.

Rollback is straightforward for serving: remove/hide the assistant entry and endpoint while keeping the extra snapshot files inert. Published render paths continue to use existing manifest and chart data fields.

## Open Questions

- Should the product expose a publish-time warning showing the estimated assistant data size before confirming publish?
- Should anonymous public assistant conversations survive page reload via localStorage, or remain memory-only for v1?
