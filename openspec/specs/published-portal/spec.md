## MODIFIED Requirements

### Requirement: Published page renders with page-level sidebar and chart grid

When a public published page is loaded by token, the system SHALL render:
- The page's multi-level sidebar defined at design time
- The chart grid and text zones from the published snapshot
- Charts loaded from snapshot data by public token
- No editor controls, workspace toolbars, collaborator controls, login prompts, or viewer-mode chrome

Clicking a sidebar section SHALL smoothly scroll to the linked grid row.

#### Scenario: Page sidebar navigation
- **WHEN** the visitor clicks a section in the published page sidebar
- **THEN** the grid scrolls smoothly to the row anchored to that section

#### Scenario: Charts load from snapshot
- **WHEN** the public published page is rendered
- **THEN** each chart zone fetches its spec and data through the public token route and renders using ECharts or Recharts consistent with the chart type

#### Scenario: Text zones render formatted text
- **WHEN** a zone contains a text block
- **THEN** the text is rendered as formatted markdown (bold, italic, headings supported)

## ADDED Requirements

### Requirement: Public published page opens directly by link

The frontend SHALL provide a standalone public route for published pages, such as `/p/{token}`. This route MUST render outside the authenticated workbench shell and MUST NOT require login. The page SHALL fetch the public manifest and chart data using only the route token.

#### Scenario: 未登录访问公开发布页
- **WHEN** 未登录访问者打开有效的公开发布链接
- **THEN** 前端渲染只读发布页
- **AND** MUST NOT 重定向到 `/login`

#### Scenario: 无效链接显示失效状态
- **WHEN** 访问者打开无效或已取消的公开发布链接
- **THEN** 前端展示链接不存在或已失效的只读错误状态
- **AND** MUST NOT 泄露该链接是否曾经存在

## REMOVED Requirements

### Requirement: Portal entry page at /portal

**Reason**: The viewer portal is removed. Published pages are opened through direct public links rather than a logged-in workspace browser.

**Migration**: Replace portal entry navigation with public-link URLs returned by Publish. `/portal` may redirect designers to the workspace/editor home or to documentation, but it is not the public consumption surface.

### Requirement: Left sidebar lists published workspaces

**Reason**: Public readers do not browse all visible workspaces. Possession of a direct link is the access mechanism.

**Migration**: Remove `GET /portal/workspaces` usage from public consumption flows.

### Requirement: AI chat window embedded in portal page view

**Reason**: Public-link v1 is a read-only snapshot surface. Embedded AI chat introduces cost, abuse, and auth assumptions that require a separate design.

**Migration**: Remove the embedded chat from public published pages for this change. A future public chart-chat feature can be proposed independently.

### Requirement: Portal designed for future per-user workspace visibility

**Reason**: Per-user published-page visibility is no longer part of the product model.

**Migration**: Delete user-visibility filtering from public page access. Public token validity replaces per-user visibility.

### Requirement: Portal 路由要求登录态

**Reason**: Public published pages MUST NOT require login.

**Migration**: The new public page route renders without auth. Authenticated designer history remains under workspace management routes.

### Requirement: Portal 列表按当前用户可见性过滤

**Reason**: There is no viewer portal list or visibility matrix.

**Migration**: Remove private/registered/allowlist filtering. Designers use workspace publish status/history; public readers use direct links.

### Requirement: Portal 详情接口校验可见性

**Reason**: Public access is authorized by high-entropy token and active/revoked state, not by logged-in user visibility.

**Migration**: Replace page-id + identity visibility checks with token + active-publication checks. Unknown/revoked token returns 404.
