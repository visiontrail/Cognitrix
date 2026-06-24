## REMOVED Requirements

### Requirement: 顶栏暴露设计者/查看者模式切换

**Reason**: The app no longer has a viewer mode. Public readers use direct public links outside the authenticated workbench.

**Migration**: Remove the segmented control, `localStorage.cognitrix_app_mode`, and `X-App-Mode` request header injection.

### Requirement: 设计者模式 UI 范围

**Reason**: There is no longer a designer/viewer mode distinction. Authenticated owner/editor users see the normal workbench according to workspace permissions.

**Migration**: Keep the existing workbench shell for authenticated designers and remove mode-dependent branching.

### Requirement: 查看者模式 UI 范围

**Reason**: Viewer mode is removed. Public published pages are standalone link routes and do not expose the workspace, catalog, or portal browser.

**Migration**: Remove viewer-mode redirects and portal-only shell logic.

### Requirement: 后端按模式 + 协作关系做权限校验

**Reason**: `X-App-Mode` is removed and MUST NOT participate in backend authorization.

**Migration**: Backend authorization uses workspace owner/editor membership for mutation routes and public token active state for public read routes.
