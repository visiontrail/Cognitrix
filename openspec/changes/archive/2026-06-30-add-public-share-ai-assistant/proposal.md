## Why

Public published pages currently let viewers inspect the rendered charts but not ask follow-up questions over the data behind those charts. Designers already generate and publish chart snapshots, so the public page can support a scoped AI assistant if the published snapshot carries the full publishable raw rows and the assistant is constrained to that immutable snapshot.

## What Changes

- Add an `AI Assistant` entry to the public page action group beside Export, Print, and the theme toggle.
- Open a right-side assistant drawer from the public page, with message history, streaming agent trace, and an input for arbitrary data questions.
- Expose a public-token chat endpoint that streams responses using the same Claude Agent SDK event loop pattern as the designer-facing BI agent, but scoped to published snapshot data only.
- Change publish snapshot generation so every chart node can include the full publishable raw rows needed by the assistant, after the existing redaction and sensitive-column filtering pipeline.
- Load all chart-node snapshot datasets into the public assistant context so visitors can ask page-level questions, cross-chart questions, or chart-specific questions.
- Keep public assistant access tied to the public token and active/revoked publication state; the assistant MUST NOT query live DuckDB sessions or unpublished workspace state.

## Capabilities

### New Capabilities
- `public-share-ai-assistant`: Public-link AI assistant UI and public-token chat behavior for published pages.

### Modified Capabilities
- `workspace-publish`: Publish snapshots must persist the full publishable raw rows for chart nodes so public assistant queries can access all published chart data.
- `chart-query-agent`: Existing snapshot-backed agent behavior must move from the removed portal/page-id route to the active public-token route and execute through the Claude Agent SDK loop.
- `public-publish-link`: Public token reads must include the assistant chat endpoint, using the same active/revoked token and authorization behavior as manifest/chart data reads.

## Impact

- Backend: `apps/api/published_pages.py`, `apps/api/public_pages.py`, `apps/api/chart_query_agent.py`, agent guardrails/tool wiring, config for public assistant row/query limits, and publish-flow tests.
- Frontend: `apps/web/components/public/public-page-client.tsx`, `apps/web/components/public/public-canvas-actions.tsx`, new public assistant drawer/client API components, i18n strings, and public-page UI tests.
- Data: published snapshot files under `UPLOAD_DIR/published/{workspace_id}/{version}/charts/{chart_id}/` will store assistant-readable full publishable rows, with manifest metadata indicating assistant availability and row counts.
- Security and privacy: only redacted publishable rows are exposed; public assistant queries remain read-only and snapshot-scoped.
