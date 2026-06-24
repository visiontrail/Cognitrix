## MODIFIED Requirements

### Requirement: 用户登录与登出

系统 SHALL 提供 `POST /auth/login`（邮箱+密码）、`POST /auth/logout`、`GET /auth/me` 三个接口及前端 `/login` 页面。登录成功后下发 access_token（JWT，过期时间 `ACCESS_TOKEN_TTL_MIN` 分钟）与 HttpOnly cookie；登出时撤销 cookie 并使该用户的 token 黑名单生效到过期。`GET /auth/me` 返回当前登录用户的 `{id, email, display_name, job_label, available_workspaces}`。`available_workspaces` MUST list only workspaces where the user is owner/editor. The response MUST NOT include `default_app_mode` or a viewer-mode hint.

#### Scenario: 登录成功
- **WHEN** 用户在 `/login` 页提交正确的邮箱与密码
- **THEN** 后端校验密码哈希通过，更新 `last_login_at`，返回 access_token；前端跳转到 `/`

#### Scenario: 登录失败
- **WHEN** 邮箱不存在 或 密码错误
- **THEN** 后端返回 HTTP 401 与统一信息 `{"error": "invalid_credentials"}`（不区分两种情况以避免邮箱枚举）

#### Scenario: 拉取当前用户
- **WHEN** 已登录用户访问 `GET /auth/me`
- **THEN** 后端返回该用户的基本信息以及他作为 owner/editor 的工作空间列表
- **AND** 响应 MUST NOT 包含 `default_app_mode`

#### Scenario: 登出
- **WHEN** 用户点击登出
- **THEN** `POST /auth/logout` 撤销 session cookie；前端清空内存 token 并跳转到 `/login`

### Requirement: 注册用户搜索接口

系统 SHALL 提供 `GET /users/search?q=<term>&limit=<n>`，要求登录态。`q` 长度 MUST ≥ 2，`limit` 默认 20、最大 50。匹配规则：邮箱前缀匹配 OR 姓名包含匹配。返回字段 SHALL 仅包含 `{id, email_masked, display_name, job_label}`，邮箱以 `<前2位>***<@后段>` 形式打码。该接口 MUST 应用每用户每分钟 60 次的速率限制。该接口可用于添加 editor collaborators，但 MUST NOT be required for public-link publishing.

#### Scenario: 设计者搜索共同编辑者
- **WHEN** 已登录设计者在 Collaborators 弹窗的搜索框中输入 "li"
- **THEN** 前端调用 `GET /users/search?q=li`，后端返回 `[{id, email_masked: "li***@galaxyspace.ai", display_name: "李雷", job_label: "项目经理"}, ...]`

#### Scenario: Publish 不搜索查看者
- **WHEN** 设计者打开 Publish 弹窗
- **THEN** 前端 MUST NOT 调用 `GET /users/search` 来选择发布页查看者

#### Scenario: 查询过短
- **WHEN** `q` 长度 < 2
- **THEN** 后端返回 HTTP 400 `{"error": "query_too_short"}`

#### Scenario: 速率限制触发
- **WHEN** 同一用户 1 分钟内调用搜索接口超过 60 次
- **THEN** 后端返回 HTTP 429 与 `Retry-After` 头
