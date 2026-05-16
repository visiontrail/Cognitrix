## Why

Non-English Excel headers are currently losing their human-readable meaning after ingestion normalizes columns to safe identifiers such as `c_1` and `c_2`. This breaks discoverability in the Workspace table catalog and chat `@` column suggestions, and it removes context the agent needs to answer questions against uploaded data.

## What Changes

- Persist uploaded column display metadata separately from the physical DuckDB identifier, including the original Excel header and a description/display label suitable for non-English headers.
- Return column descriptions from backend table-description and table-catalog APIs whenever metadata exists.
- Show described/original column labels in the Workspace table catalog table-detail view while preserving the safe physical column name.
- Use described/original column labels in chat `@` suggestions so users do not see only generated identifiers like `c_1` and `c_2`.
- Keep SQL execution and guardrails based on safe physical identifiers; descriptions are presentation and prompt context, not executable identifiers.

## Capabilities

### New Capabilities
- `column-descriptions`: Covers ingestion-time column description persistence, catalog/API exposure, and UI display for uploaded column metadata.

### Modified Capabilities

## Impact

- Backend ingestion metadata generation and execution under `apps/api/agentic_ingestion/`.
- Backend table catalog and tool description payloads under `apps/api/table_catalog.py`, `apps/api/tool_calling.py`, and related schema helpers.
- Frontend catalog, chat input mention suggestions, and shared API types under `apps/web/`.
- Focused backend and frontend tests covering non-English header uploads and display metadata.
