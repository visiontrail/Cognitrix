## ADDED Requirements

### Requirement: Canvas 工具栏 Collaborators 按钮

在 Canvas Web Page Design 模式工具栏中，系统 MAY 提供 **Collaborators** 按钮用于管理共同设计者。该按钮 MUST 与 Publish 区分，MUST NOT 用于生成公开只读链接。按钮仅当当前登录用户是当前工作空间 owner/editor 时可见可用。

#### Scenario: Owner 管理共同设计者
- **WHEN** 工作空间 owner 进入 Canvas Web Page Design 模式
- **THEN** 工具栏可显示 Collaborators 按钮
- **AND** Publish 仍是唯一公开链接入口

#### Scenario: 非编辑者不可见
- **WHEN** 非 owner/editor 用户进入 Canvas
- **THEN** Collaborators 按钮不渲染

### Requirement: Collaborators 弹窗仅管理编辑者

Collaborators 弹窗 SHALL 只管理可编辑协作者。搜索、添加、移除和角色展示 MUST 使用 owner/editor 语义，MUST NOT 提供 viewer 角色、查看者邀请链接或只读访问承诺。

#### Scenario: 添加编辑者
- **WHEN** owner 在 Collaborators 弹窗搜索并添加用户 A
- **THEN** 前端调用成员接口把 A 加入工作空间 editor
- **AND** A 获得设计/编辑权限而非公开只读访问

#### Scenario: 不提供查看者角色
- **WHEN** owner 打开 Collaborators 弹窗
- **THEN** UI MUST NOT 渲染“查看者”角色选项
- **AND** MUST NOT 暗示可通过协作者弹窗分享只读页面

## MODIFIED Requirements

### Requirement: 邀请链接生成与复制

后端 SHALL only provide workspace invite links for adding editor collaborators when collaborator invite links are enabled. The request body MUST NOT accept `role = viewer`; omitted role defaults to `editor`, and any explicit role MUST be `editor`. Invite URLs are for joining the workspace as a designer/editor, not for viewing published pages.

#### Scenario: 生成编辑者邀请链接
- **WHEN** owner 在 Collaborators 弹窗点击"生成邀请链接"
- **THEN** 后端写入 `workspace_invites` 行，role 为 `editor`，返回完整 URL
- **AND** 前端展示 URL 与"复制"按钮

#### Scenario: 拒绝 viewer 邀请
- **WHEN** 客户端请求 `POST /workspaces/{id}/invites` 且 body 含 `role = "viewer"`
- **THEN** 后端返回 HTTP 422
- **AND** MUST NOT 创建邀请记录

#### Scenario: 复制链接
- **WHEN** 用户点击"复制"
- **THEN** URL 写入剪贴板；toast "邀请链接已复制"

#### Scenario: 撤销链接
- **WHEN** 用户点击"撤销"
- **THEN** `DELETE /workspaces/{id}/invites/{invite_id}` 将 `revoked_at` 设为当前时间；该 URL 之后接受时返回 HTTP 410

### Requirement: 邀请链接接受流程

系统 SHALL provide invite acceptance only for editor collaborators:
- 已登录用户：校验 token（签名、未过期、未撤销、未超用次数），通过则将其加入 `workspace_members`，role 固定为 `editor`。
- 未登录用户：前端路由 `/invites/<token>` 检测到无登录态时 SHALL 重定向到 `/register?invite=<token>`；注册成功后前端 MUST 立即调用同一 accept endpoint。

Invite acceptance MUST NOT be used for read-only public published-page access.

#### Scenario: 已登录用户接受编辑者邀请
- **WHEN** 已登录用户访问 `/invites/abc123`
- **THEN** 前端调用 accept API，成功则跳转到对应工作空间画布；toast "已加入工作空间『XXX』"
- **AND** 该用户在 workspace_members 中的 role 为 `editor`

#### Scenario: 未登录用户接受
- **WHEN** 未登录用户访问 `/invites/abc123`
- **THEN** 重定向到 `/register?invite=abc123`；用户完成注册后自动接受邀请并跳转工作空间

#### Scenario: 已经是协作者
- **WHEN** 用户已是 `workspace_members` 中的 owner/editor，再次接受同一链接
- **THEN** 后端返回 200 与 `{"already_member": true}`；前端跳转到工作空间但不显示 toast

#### Scenario: 链接过期
- **WHEN** 接受时 `expires_at < now()`
- **THEN** 后端返回 HTTP 410 `{"error": "invite_expired"}`；前端显示"邀请链接已过期，请联系工作空间所有者"

#### Scenario: 链接已被撤销
- **WHEN** 接受时 `revoked_at IS NOT NULL`
- **THEN** 后端返回 HTTP 410 `{"error": "invite_revoked"}`

#### Scenario: 链接超过使用次数
- **WHEN** 接受时 `max_uses IS NOT NULL AND used_count >= max_uses`
- **THEN** 后端返回 HTTP 410 `{"error": "invite_exhausted"}`

### Requirement: 工作空间成员关系即权威 RBAC

工作空间所有设计与编辑权限 SHALL 来源于 `workspace_members(workspace_id, user_id, role)` 表。Valid workspace membership roles are `owner` and `editor` only. Editing, saving canvas, managing collaborators, and publishing require `role IN (owner, editor)` unless a stricter owner-only operation is explicitly defined. Public published-page viewing MUST NOT depend on `workspace_members`.

#### Scenario: 非成员尝试编辑
- **WHEN** 不在 `workspace_members` 中的用户调用 `POST /workspaces/{id}/canvas`
- **THEN** 后端返回 HTTP 403 `{"error": "workspace_role_required"}`

#### Scenario: viewer 成员不再有效
- **WHEN** 数据库中存在遗留 `role = "viewer"` 的 workspace_members 行
- **THEN** 后端 MUST NOT treat that row as granting workspace access
- **AND** migration SHOULD remove or neutralize that row rather than upgrading it to editor

#### Scenario: Owner 删除工作空间
- **WHEN** owner 调用 `DELETE /workspaces/{id}`
- **THEN** 后端级联删除 `workspace_members`、`workspace_invites`、相关 published 历史与 public publication 元数据

## REMOVED Requirements

### Requirement: Canvas 工具栏 Share 按钮

**Reason**: "Share" is no longer a separate workspace viewer/collaboration action. Public read-only sharing is handled by Publish.

**Migration**: Remove the Share button or rename editor-collaboration management to Collaborators.

### Requirement: Share 弹窗结构

**Reason**: The old Share dialog mixes collaborators, viewer roles, and invite links. Public viewing now belongs to Publish; collaboration is owner/editor only.

**Migration**: Replace with a Collaborators dialog that manages editor collaborators only, or remove the dialog if editor collaboration is out of scope for the implementation slice.
