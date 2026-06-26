## MODIFIED Requirements

### Requirement: Publish action available on Web Page Design canvas

A **Publish** button SHALL be visible in the Web Page Design canvas toolbar to users whose role on the current workspace is `owner` or `editor`. The button is disabled if any chart zone contains a chart with no loaded data. Users without owner/editor access MUST NOT see the Publish button. Clicking the button opens the public-link publish dialog defined by this capability.

#### Scenario: Publish button visible to owner/editor
- **WHEN** 工作空间 owner 或 editor 进入 Web Page Design 模式
- **THEN** 工具栏渲染 Publish 按钮

#### Scenario: Publish button hidden for non-editors
- **WHEN** 非 owner/editor 用户进入 Web Page Design 模式
- **THEN** Publish 按钮不渲染

#### Scenario: Publish blocked with empty chart
- **WHEN** the workspace contains a chart zone whose chart has not yet been loaded with data
- **THEN** the Publish button is disabled and a tooltip reads "All charts must have data before publishing"

#### Scenario: Publish opens public-link dialog
- **WHEN** owner/editor 点击启用状态的 Publish 按钮
- **THEN** 系统打开公开链接发布弹窗，不立即发起发布请求

### Requirement: Publish creates an immutable versioned snapshot

When the user confirms publish in the public-link dialog, the system SHALL call `POST /workspaces/{workspace_id}/publish` without visibility fields. The backend creates a new version record and writes the snapshot to `UPLOAD_DIR/published/{workspace_id}/{version}/` containing:
- `manifest.json` — sidebar config, grid layout, page layout, zone positions, text zones
- `charts/{chart_id}/spec.json` — ECharts or Recharts spec
- `charts/{chart_id}/data.json` — raw rows, capped at `AGENT_MAX_SQL_ROWS`

The raw data rows MUST pass through the same `redact_rows()` and `forbidden_sensitive_columns()` pipeline as the query runtime before being written. The publish operation MUST create or refresh the workspace's active public-link record so the returned public URL points at the newly created snapshot version.

#### Scenario: Successful publish
- **WHEN** owner/editor 在弹窗中确认发布且所有 zone 都已加载数据
- **THEN** 前端调用 `POST /workspaces/{workspace_id}/publish` 不携带 visibility 字段
- **AND** 后端返回 `published_page_id`、版本号、公开 token、完整公开 URL 与发布时间

#### Scenario: Sensitive column redaction
- **WHEN** a chart's underlying data contains columns flagged by `forbidden_sensitive_columns()` for the publishing user's role
- **THEN** those columns are excluded from `charts/{chart_id}/data.json`

#### Scenario: Data cap enforcement
- **WHEN** a chart's source query returns more rows than `AGENT_MAX_SQL_ROWS`
- **THEN** only the first `AGENT_MAX_SQL_ROWS` rows are written to `data.json`; the manifest records `data_truncated: true` for that chart

### Requirement: Publish history accessible per workspace

The backend SHALL maintain immutable publish history for each workspace. `GET /workspaces/{workspace_id}/published` returns a list of published versions with `{ version, published_at, published_by, page_id }`, newest first. Only owner/editor users of the workspace may read publish history. Public readers MUST NOT receive publish history.

#### Scenario: Version list returned
- **WHEN** owner/editor 调用 `GET /workspaces/{workspace_id}/published`
- **THEN** the response is an ordered list of published versions, newest first

#### Scenario: Public reader cannot list history
- **WHEN** a public-link visitor opens the published page
- **THEN** the public response MUST NOT expose the workspace publish history list

### Requirement: Publish snapshot accessible without live DuckDB session

Published page assets SHALL be served from snapshot files, not from any live DuckDB session. Owner/editor history may reference `published_page_id`, but public readers MUST access the active public snapshot through the public token route defined by `public-publish-link`.

#### Scenario: Snapshot served independently
- **WHEN** the live DuckDB session for the workspace's source dataset is unavailable
- **THEN** the published public page still loads and renders charts from snapshot data

#### Scenario: Missing snapshot returns 404
- **WHEN** a public token points at a missing snapshot file
- **THEN** the public API returns HTTP 404

## ADDED Requirements

### Requirement: Publish dialog manages public link lifecycle

点击 Publish 按钮时 SHALL 打开公开链接发布弹窗。弹窗 MUST 表达“任何持有链接的人都可以查看该发布快照”，并在存在 active 公开发布时展示公开链接、复制按钮、打开预览、更新发布、取消发布动作；在未发布时展示确认发布动作。弹窗 MUST 提示发布内容是当前时刻快照，后续改动需要点击更新发布才会出现在公开页。

#### Scenario: 未发布时打开 Publish
- **WHEN** 设计者点击 Publish 且当前工作空间没有 active 公开发布
- **THEN** 弹窗展示“发布并生成公开链接”主操作
- **AND** 不展示 visibility 单选项或用户搜索框

#### Scenario: 已发布时打开 Publish
- **WHEN** 设计者点击 Publish 且当前工作空间已有 active 公开发布
- **THEN** 弹窗展示公开链接、复制、打开预览、更新发布、取消发布

#### Scenario: 更新发布
- **WHEN** 设计者点击“更新发布”
- **THEN** 前端调用 `POST /workspaces/{workspace_id}/publish`
- **AND** 成功后公开链接保持不变但快照时间更新

#### Scenario: 取消发布
- **WHEN** 设计者点击“取消发布”并确认
- **THEN** 前端调用 `DELETE /workspaces/{workspace_id}/publish`
- **AND** 弹窗进入未发布状态

## REMOVED Requirements

### Requirement: Publish 弹窗暴露可见性策略

**Reason**: Published pages are no longer private/registered/allowlist resources. Publish now creates a public link, and possession of the link is the only viewer-side access grant.

**Migration**: Replace the visibility settings UI with the public-link lifecycle dialog.

### Requirement: Publish 接口接受可见性参数

**Reason**: The publish API no longer accepts `visibility_mode` or `visibility_user_ids`.

**Migration**: Clients MUST call `POST /workspaces/{workspace_id}/publish` with layout/sidebar/charts only. The backend creates or refreshes the workspace's public publication automatically.

### Requirement: 发布历史按版本记录可见性

**Reason**: Version history no longer records or displays visibility summaries.

**Migration**: History rows should show version/time/publisher/page id. Public-link status is queried from `GET /workspaces/{workspace_id}/publish`.

### Requirement: 调整已发布版本的可见性

**Reason**: There is no published-version visibility matrix to adjust.

**Migration**: To stop public access, call `DELETE /workspaces/{workspace_id}/publish`. To expose updated content, call `POST /workspaces/{workspace_id}/publish`.
