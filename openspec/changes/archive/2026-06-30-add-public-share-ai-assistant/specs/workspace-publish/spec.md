## MODIFIED Requirements

### Requirement: Publish creates an immutable versioned snapshot

When the user confirms publish in the public-link dialog, the system SHALL call `POST /workspaces/{workspace_id}/publish` without visibility fields. The backend creates a new version record and writes the snapshot to `UPLOAD_DIR/published/{workspace_id}/{version}/` containing:
- `manifest.json` — sidebar config, grid layout, page layout, zone positions, text zones, assistant availability metadata, and per-chart assistant data metadata
- `charts/{chart_id}/spec.json` — ECharts or Recharts spec
- `charts/{chart_id}/data.json` — render rows, capped at `AGENT_MAX_SQL_ROWS`
- `charts/{chart_id}/assistant-data.jsonl` — full assistant-readable raw rows carried by the chart asset at publish time

Both render rows and assistant rows MUST pass through the same `redact_rows()` and `forbidden_sensitive_columns()` pipeline as the query runtime before being written. `assistant-data.jsonl` MUST NOT be silently truncated by `AGENT_MAX_SQL_ROWS`; if complete assistant rows are unavailable for any published chart node, the manifest MUST mark assistant availability as false for the snapshot or the publish request MUST fail with an explicit validation error. The publish operation MUST create or refresh the workspace's active public-link record so the returned public URL points at the newly created snapshot version.

#### Scenario: Successful publish
- **WHEN** owner/editor 在弹窗中确认发布且所有 zone 都已加载数据
- **THEN** 前端调用 `POST /workspaces/{workspace_id}/publish` 不携带 visibility 字段
- **AND** 后端返回 `published_page_id`、版本号、公开 token、完整公开 URL 与发布时间

#### Scenario: Sensitive column redaction
- **WHEN** a chart's underlying data contains columns flagged by `forbidden_sensitive_columns()` for the publishing user's role
- **THEN** those columns are excluded from `charts/{chart_id}/data.json`
- **AND** those columns are excluded from `charts/{chart_id}/assistant-data.jsonl`

#### Scenario: Data cap enforcement
- **WHEN** a chart's source query returns more rows than `AGENT_MAX_SQL_ROWS`
- **THEN** only the first `AGENT_MAX_SQL_ROWS` rows are written to `data.json`; the manifest records `data_truncated: true` for that chart
- **AND** all publishable assistant rows are written to `assistant-data.jsonl` without using `AGENT_MAX_SQL_ROWS` as a cap

#### Scenario: Assistant availability recorded
- **WHEN** every published chart node has complete assistant rows after redaction
- **THEN** `manifest.json` records `assistant.available: true`
- **AND** every chart entry records `assistant_data_path`, `assistant_row_count`, and `assistant_data_available: true`

#### Scenario: Incomplete assistant rows are not presented as complete
- **WHEN** any published chart node lacks complete assistant rows
- **THEN** the system MUST NOT publish a manifest that claims `assistant.available: true`
- **AND** the public assistant MUST NOT be enabled against that incomplete snapshot
