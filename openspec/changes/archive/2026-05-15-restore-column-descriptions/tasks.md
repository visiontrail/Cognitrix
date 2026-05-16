## 1. Metadata Model

- [x] 1.1 Add SQLite schema/migration support for per-table column metadata.
- [x] 1.2 Add backend helper functions to upsert and read column metadata by workspace/table.

## 2. Ingestion Persistence

- [x] 2.1 Populate column metadata during ingestion execution from physical columns, source headers, and inferred mappings.
- [x] 2.2 Preserve backward compatibility with existing ingestion plan payloads that only include `column_mapping`.

## 3. API Exposure

- [x] 3.1 Enrich `describe_table` tool results with original header and description fields.
- [x] 3.2 Enrich Workspace table catalog data-preview column payloads with original header and description fields.

## 4. Frontend Display

- [x] 4.1 Update catalog preview types and rendering to show description/original header first and physical name second.
- [x] 4.2 Update chat `@` column suggestions to display human-readable descriptions while retaining physical identifiers.

## 5. Verification

- [x] 5.1 Add or update backend tests for non-English header metadata persistence and API exposure.
- [x] 5.2 Add or update frontend tests for catalog preview and `@` suggestion display.
- [x] 5.3 Run focused backend and frontend checks.
