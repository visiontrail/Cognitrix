# public-publish-link Specification

## Purpose
TBD - created by archiving change add-public-share-ai-assistant. Update Purpose after archive.
## Requirements
### Requirement: 设计者发布生成公开不可猜测链接

系统 SHALL 允许工作空间 owner/editor 对当前工作空间创建公开发布。创建公开发布时，系统 MUST 生成一个高熵、不可猜测的 public token（至少约 128 bit 熵），并返回可直接在浏览器打开的完整 `public_url`。public token MUST 与 `workspace_id`、`published_page_id`、版本号、用户 id、自增序号和时间戳解耦。

#### Scenario: 首次发布返回公开链接
- **WHEN** owner/editor 对含有有效图表数据的工作空间调用 `POST /workspaces/{workspace_id}/publish`
- **THEN** 系统 MUST 创建发布快照与公开发布记录
- **AND** 响应 MUST 返回 `token`、`public_url`、`published_page_id`、`version`、`published_at`、`is_active=true`

#### Scenario: token 不可由内部标识推导
- **WHEN** 系统连续创建多个公开发布链接
- **THEN** 每个 token MUST 唯一且不可由工作空间 id、发布版本号、用户 id 或创建时间推导

### Requirement: 公开发布采用快照语义且更新复用链接

公开发布内容 SHALL 来自发布/更新时刻捕获的不可变快照。工作空间在发布后继续编辑画布、图表或文本 MUST NOT 改变已公开页面，直到 owner/editor 明确更新发布。同一工作空间同时至多有一个 active public token；重复发布 MUST 创建新的快照版本并把现有 active token 指向新版本，MUST NOT 生成第二个 active token。

#### Scenario: 发布后编辑不影响公开页
- **WHEN** 工作空间 W 在 t0 发布并得到公开链接
- **AND** 设计者在 t1 修改 W 的布局或图表
- **THEN** 公开链接读取到的内容仍 MUST 是 t0 快照

#### Scenario: 更新发布复用链接
- **WHEN** 工作空间 W 已存在 active 公开链接
- **AND** owner/editor 再次调用 `POST /workspaces/{workspace_id}/publish`
- **THEN** 系统 MUST 创建新的不可变快照版本
- **AND** 现有 token 与 `public_url` MUST 保持不变并指向新快照

### Requirement: 公开读取端点无需鉴权

系统 SHALL 提供 public token 驱动的公开读取端点，包括 manifest、chart data 和 AI assistant chat。公开读取端点 MUST NOT 依赖 bearer token、session cookie、`get_current_identity`、workspace membership、`X-App-Mode` 或登录态。未知 token、已撤销 token、未激活 token MUST 统一返回 404。AI assistant chat 端点 MUST 使用同一 public token 解析逻辑，并且 MUST NOT 接受内部 `page_id` 作为公开访问凭证。

#### Scenario: 未登录访问者读取公开 manifest
- **WHEN** 未登录访问者请求有效 token 对应的公开 manifest 端点
- **THEN** 系统 MUST 返回发布页 manifest
- **AND** MUST NOT 要求任何认证头或登录 cookie

#### Scenario: 未登录访问者发起公开 AI assistant chat
- **WHEN** 未登录访问者向有效 token 对应的 `POST /public/pages/{token}/chat` 发送问题
- **THEN** 系统 MUST 以 SSE 流返回公开 assistant 事件
- **AND** MUST NOT 要求任何认证头或登录 cookie

#### Scenario: 已撤销链接返回 404
- **WHEN** 访问者请求已撤销公开链接的 manifest、chart data 或 AI assistant chat
- **THEN** 系统 MUST 返回 HTTP 404
- **AND** MUST NOT 透露该 token 是否曾经存在

### Requirement: 公开响应不泄露成员关系与内部状态

公开读取响应 SHALL 只包含渲染发布页与运行公开 assistant 所需的快照数据。响应 MUST NOT 包含 workspace member 列表、owner/editor 身份、用户邮箱、workspace 内部权限、live DuckDB session 路径、数据库文件路径、agent session id、未公开的工作空间草稿状态或 publish management metadata。AI assistant events MUST NOT expose internal snapshot file paths or live tool configuration.

#### Scenario: 公开 manifest 不含权限字段
- **WHEN** 任意访问者读取公开 manifest
- **THEN** 响应 MUST NOT 包含 `published_by` 以外的用户身份细节
- **AND** MUST NOT 包含 `workspace_members`、`visibility_mode`、`visibility_user_ids`、`owner_email`、`database_path`

#### Scenario: 图表数据来自已脱敏快照
- **WHEN** 任意访问者读取公开 chart data
- **THEN** 响应 MUST 只返回发布时写入的已脱敏、已截断数据
- **AND** MUST NOT 查询 live DuckDB session

#### Scenario: Assistant events do not leak internals
- **WHEN** 任意访问者使用公开 AI assistant
- **THEN** SSE payloads MUST NOT expose filesystem paths, workspace membership, bearer tokens, agent session ids, or live DuckDB connection details
- **AND** assistant tool results MUST be derived only from published snapshot tables

### Requirement: 设计者可查询和取消公开发布

系统 SHALL 允许 workspace owner/editor 查询当前公开发布状态并取消公开发布。取消公开发布 MUST 立即使 public token 的公开读取返回 404；取消操作 MUST NOT 删除不可变发布历史快照。

#### Scenario: 查询未发布状态
- **WHEN** owner/editor 调用 `GET /workspaces/{workspace_id}/publish` 且工作空间没有 active 公开发布
- **THEN** 系统 MUST 返回 `{is_active: false}`

#### Scenario: 查询已发布状态
- **WHEN** owner/editor 调用 `GET /workspaces/{workspace_id}/publish` 且存在 active 公开发布
- **THEN** 系统 MUST 返回 `token`、`public_url`、`published_page_id`、`version`、`published_at`、`is_active=true`

#### Scenario: 取消发布立即失效
- **WHEN** owner/editor 调用 `DELETE /workspaces/{workspace_id}/publish`
- **THEN** 系统 MUST 将当前公开发布标记为 inactive
- **AND** 后续公开读取该 token MUST 返回 HTTP 404

### Requirement: 公开端点具备基础防扫描保护

系统 SHALL 对公开读取端点施加基础防扫描保护。实现 MUST 至少包含高熵 token，并 SHOULD 对 manifest、chart data 和 AI assistant chat 公开读取按来源 IP 或等效来源进行窗口限流。公开 JSON 和 SSE 响应 MUST 避免长期缓存已撤销内容。

#### Scenario: 高频 token 探测被限制
- **WHEN** 同一来源在短时间内对公开 token 端点发起超过阈值的请求
- **THEN** 系统 MUST 拒绝超额请求或延迟处理
- **AND** MUST NOT 返回可用于区分“曾存在但已撤销”和“从未存在”的信息

#### Scenario: 撤销后浏览器不应长期复用旧 JSON
- **WHEN** 公开端点返回 manifest、chart data 或 AI assistant chat 事件
- **THEN** 响应 MUST 使用 no-store 或短缓存策略，避免取消发布后长期展示旧 JSON 或 SSE 结果

