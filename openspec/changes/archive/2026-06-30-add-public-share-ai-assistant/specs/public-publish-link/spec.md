## MODIFIED Requirements

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

### Requirement: 公开端点具备基础防扫描保护

系统 SHALL 对公开读取端点施加基础防扫描保护。实现 MUST 至少包含高熵 token，并 SHOULD 对 manifest、chart data 和 AI assistant chat 公开读取按来源 IP 或等效来源进行窗口限流。公开 JSON 和 SSE 响应 MUST 避免长期缓存已撤销内容。

#### Scenario: 高频 token 探测被限制
- **WHEN** 同一来源在短时间内对公开 token 端点发起超过阈值的请求
- **THEN** 系统 MUST 拒绝超额请求或延迟处理
- **AND** MUST NOT 返回可用于区分“曾存在但已撤销”和“从未存在”的信息

#### Scenario: 撤销后浏览器不应长期复用旧 JSON
- **WHEN** 公开端点返回 manifest、chart data 或 AI assistant chat 事件
- **THEN** 响应 MUST 使用 no-store 或短缓存策略，避免取消发布后长期展示旧 JSON 或 SSE 结果
