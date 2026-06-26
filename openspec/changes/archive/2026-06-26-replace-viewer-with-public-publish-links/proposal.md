## Why

The current product model splits the app into "designer" and "viewer" modes, then adds collaborator viewers, invite links, and publish visibility rules on top. That is the wrong abstraction for Cognitrix publishing: a published BI page should behave like a Notion public share page, where the designer creates a read-only snapshot link and anyone with that link can open it without becoming a workspace member.

This change removes the viewer product concept and makes "publish" the single sharing action. It aligns the BI publish flow with RavenAI's conversation sharing model: high-entropy public token, snapshot semantics, refresh in place, and immediate revocation.

## What Changes

- **BREAKING** Remove the application-level designer/viewer mode switch and all `X-App-Mode: designer|viewer` behavior from the product contract.
- **BREAKING** Remove the workspace `viewer` collaborator role from user-facing collaboration and permission semantics. Workspace collaboration remains owner/editor only.
- **BREAKING** Remove publish visibility choices (`private`, `registered`, `allowlist`) and user allowlist selection from the Publish dialog and API contract.
- Replace the existing Publish dialog with a public-link publish dialog similar to RavenAI's share dialog:
  - publish creates a public read-only snapshot link;
  - repeated publish/update refreshes the current public snapshot and reuses the same token/link;
  - cancel/unpublish immediately disables the public link;
  - the dialog shows copy, open preview, update publish, and cancel publish actions.
- Make published pages readable through a public unauthenticated route by token. Possession of the public link is the only viewer-side access grant.
- Keep owner/editor authorization for managing workspaces and publishing. Only designers with edit access can create, update, inspect, or revoke a public publish link.
- Remove viewer-oriented portal browsing as the primary experience. Public published pages are opened directly by link rather than discovered through a logged-in viewer portal.
- Preserve existing snapshot safety requirements: published chart data remains capped and redacted at publish time, and public read paths never query the live DuckDB session.

## Capabilities

### New Capabilities

- `public-publish-link`: Public-link lifecycle for published workspace pages, including token generation, refresh-in-place snapshot semantics, public read endpoints, owner/editor management endpoints, and revocation.

### Modified Capabilities

- `workspace-publish`: Publish no longer accepts visibility modes; it manages one active public link per workspace and returns public-link metadata.
- `published-portal`: Portal access no longer requires login or visibility filtering; public pages render directly by token/page link and do not expose a viewer workspace browser.
- `workspace-collaboration`: Collaboration removes viewer role and invite-link viewer flows; workspace members are owner/editor only.
- `app-role-mode`: The designer/viewer app mode is removed.
- `user-account`: `/auth/me` and related account contracts no longer expose `default_app_mode` or owner/editor/viewer workspace lists.

## Impact

- Backend:
  - `apps/api/published_pages.py` needs a public-link model, active-link lifecycle, revocation state, and compatibility cleanup for old visibility fields.
  - `apps/api/workspaces.py` publish/history routes need to stop accepting visibility payloads and expose public-link status/update/revoke behavior.
  - `apps/api/portal.py` needs unauthenticated public token routes and should stop treating published-page access as a logged-in visibility problem.
  - Workspace RBAC in `apps/api/workspaces.py`, `workspace_state.py`, and `table_catalog.py` must stop using `viewer` as a workspace membership role for product access.
  - Auth/account responses in `apps/api/auth.py` must stop returning `default_app_mode`.
- Frontend:
  - Remove app-mode storage, mode switch UI, `X-App-Mode` request header injection, and viewer-mode routing.
  - Replace `PublishPanel` visibility selection with a public-link management dialog.
  - Remove or repurpose the current `ShareDialog` so "share" is no longer a separate viewer/collaborator concept beside Publish.
  - Public page route should render a standalone read-only published snapshot by token/link, outside the authenticated workspace editor flow.
- Data:
  - New or migrated state must represent one active public publish link per workspace (or per latest published page lineage) with token, public URL, `is_active`, `published_at`, and snapshot/version metadata.
  - Existing `published_pages.visibility_mode` and `visibility_user_ids` become legacy columns and must not drive new behavior.
- Tests:
  - Replace visibility/allowlist/viewer-mode tests with public-link publish, refresh, revoke, and unauthenticated read tests.
  - Add regression coverage that revoked/unknown tokens return 404 and public responses do not include workspace membership, owner identity, or live session internals.
