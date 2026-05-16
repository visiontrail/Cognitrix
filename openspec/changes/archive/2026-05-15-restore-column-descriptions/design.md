## Context

Excel ingestion normalizes arbitrary headers into safe DuckDB identifiers. That is necessary for SQL safety, but non-English or otherwise unsafe headers lose their original meaning if the system does not persist a second metadata layer. DuckDB supports column comments through SQL comments in recent versions, but relying on engine-native metadata would couple the feature to DuckDB version behavior and would not automatically help the existing SQLite-backed catalog, API payloads, or frontend mention UI.

The application already has durable SQLite state for ingestion jobs and table catalog entries, while DuckDB holds workspace data. Column descriptions should live in the application metadata layer and be projected into APIs and prompt/tool context when needed.

## Goals / Non-Goals

**Goals:**

- Preserve a physical SQL column name, original uploaded header, and human-readable description/display label for each ingested column.
- Surface descriptions in table preview/catalog APIs, Workspace table catalog detail, and chat `@` suggestions.
- Keep guardrails, generated SQL, and execution on physical column names.
- Backfill a useful label from existing ingestion `column_mapping` where explicit description metadata is unavailable.

**Non-Goals:**

- Add a dependency on DuckDB-native column comments for correctness.
- Rename existing physical DuckDB columns or rewrite saved views.
- Translate every possible header perfectly without LLM support; fallback labels must still be deterministic.

## Decisions

- Store column descriptions in SQLite application state, not DuckDB comments. This keeps behavior stable across DuckDB versions and gives the table catalog and chat APIs one metadata source. DuckDB comments can be considered later as an optional mirror, but not as the source of truth.
- Extend ingestion execution metadata from `column_mapping` into explicit per-column metadata with `name`, `original_name`, and `description`. Existing `column_mapping` remains supported so current plans and tests do not break.
- Enrich `describe_table` and catalog preview responses with metadata by matching physical column names against stored metadata. When no stored metadata exists, responses remain backward-compatible and only include `name` and `type`.
- Render both display metadata and physical identifiers in UI. Users see the human label first, while engineers and SQL-aware flows can still inspect the underlying column name.

## Risks / Trade-offs

- Existing uploaded tables may not have metadata. → Use deterministic fallbacks from physical names and any available ingestion job `column_mapping`.
- Frontend mention replacement still needs executable identifiers. → Suggestions display the description/original header but insert or carry the physical column name used by backend tools.
- Metadata can drift if future write paths alter DuckDB tables directly. → Centralize metadata writes in ingestion execution and keep API enrichment tolerant of missing records.

## Migration Plan

Add a SQLite migration for `table_column_metadata` with workspace, table, column name, original name, description, type, and timestamps. Runtime schema initialization will create it for local/dev databases. New ingestions populate it during execution; existing tables continue working with fallback labels.

Rollback is non-destructive: frontend simply stops reading extra fields, and backend can ignore the metadata table without changing DuckDB data.

## Open Questions

- Whether a later version should also mirror descriptions into DuckDB `COMMENT ON COLUMN` when the bundled DuckDB version supports it consistently.
