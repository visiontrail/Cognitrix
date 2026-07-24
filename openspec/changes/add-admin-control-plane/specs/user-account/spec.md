## MODIFIED Requirements

### Requirement: 用户登录与登出

系统 SHALL 提供 `POST /auth/login`（邮箱+密码）、`POST /auth/logout`、`GET /auth/me` 三个接口及前端 `/login` 页面。登录成功后下发 access_token（JWT，过期时间 `ACCESS_TOKEN_TTL_MIN` 分钟）与 HttpOnly cookie；登出时撤销 cookie 并使该用户的 token 黑名单生效到过期。`GET /auth/me` 返回当前登录用户的 `{id, email, display_name, job_label, status, role, available_workspaces}`。`available_workspaces` MUST list only workspaces where the user is owner/editor. The response MUST NOT include `default_app_mode` or a viewer-mode hint. Suspended users MUST be rejected during login and on every authenticated request, including requests made with a previously issued token.

#### Scenario: 登录成功
- **WHEN** active 用户在 `/login` 页提交正确的邮箱与密码
- **THEN** 后端校验密码哈希通过，更新 `last_login_at`，返回 access_token 和有效 role；superadmin 前端跳转到 `/admin`，其他用户跳转到 `/`

#### Scenario: 登录失败
- **WHEN** 邮箱不存在、密码错误或账号已 suspended
- **THEN** 后端返回 HTTP 401 与统一信息 `{"error": "invalid_credentials"}`（不泄漏具体原因）

#### Scenario: 拉取当前用户
- **WHEN** 已登录 active 用户访问 `GET /auth/me`
- **THEN** 后端返回该用户的基本信息、status、有效 role 以及他作为 owner/editor 的工作空间列表
- **AND** 响应 MUST NOT 包含 `default_app_mode`

#### Scenario: 已签发 token 的账号被停用
- **WHEN** suspended 用户使用停用前签发的 token 发起请求
- **THEN** 后端拒绝请求且不执行业务操作

#### Scenario: 登出
- **WHEN** 用户点击登出
- **THEN** `POST /auth/logout` 撤销 session cookie；前端清空内存 token 并跳转到 `/login`
