## 1. Data Model and Migration

- [x] 1.1 Add a public publication state table or equivalent store that maps one active high-entropy token to the workspace's current published page/version.
- [x] 1.2 Extend `apps/api/published_pages.py` with models and store methods for create-or-refresh, get status, revoke, and resolve active public token.
- [x] 1.3 Add a public URL builder using configured public base URL first, then request origin/base URL fallback.
- [x] 1.4 Stop writing new `visibility_mode` and `visibility_user_ids` decisions while preserving legacy columns for rollback/read compatibility during the migration.
- [x] 1.5 Add migration handling for existing `workspace_members.role = "viewer"` rows so they no longer grant workspace access and are not upgraded to editor.
- [x] 1.6 Update workspace invite schema/validation so new invite links cannot create viewer memberships.

## 2. Backend Publish and Public Read APIs

- [x] 2.1 Simplify `PublishWorkspaceRequest` to accept layout/sidebar/charts only and remove visibility validators from the new request contract.
- [x] 2.2 Update `POST /workspaces/{workspace_id}/publish` to require owner/editor, write a new immutable snapshot, create or refresh the active public link, and return link metadata.
- [x] 2.3 Add `GET /workspaces/{workspace_id}/publish` for owner/editor publication status.
- [x] 2.4 Add `DELETE /workspaces/{workspace_id}/publish` to revoke the active public link without deleting immutable history.
- [x] 2.5 Keep `GET /workspaces/{workspace_id}/published` as owner/editor history only and remove visibility summary fields from the response.
- [x] 2.6 Replace authenticated `/portal/pages/{page_id}/manifest` public consumption with unauthenticated token-based manifest and chart-data routes.
- [x] 2.7 Ensure public token routes return 404 for unknown, inactive, revoked, or missing-snapshot cases without revealing which case occurred.
- [x] 2.8 Add basic anti-scanning protection and no-store/short-cache headers for public manifest and chart-data JSON.
- [x] 2.9 Remove `X-App-Mode` backend checks and any viewer-mode quick-fail behavior from publish/workspace routes.

## 3. Backend Workspace and Account Semantics

- [x] 3.1 Update workspace role validation so user-facing workspace membership accepts only owner/editor.
- [x] 3.2 Audit workspace read/write guards in `workspaces.py`, `workspace_state.py`, and `table_catalog.py` and replace viewer minimum-role assumptions with owner/editor access where appropriate.
- [x] 3.3 Update collaborator/member endpoints to reject viewer role creation or role changes.
- [x] 3.4 Update invite creation and accept flow so accepted invites always create editor collaborators.
- [x] 3.5 Update `/auth/me` to remove `default_app_mode` and return only owner/editor workspaces in `available_workspaces`.
- [x] 3.6 Confirm BI data-policy/runtime roles that use the string `viewer` are not accidentally removed when they are unrelated to workspace membership.

## 4. Frontend Workbench Changes

- [x] 4.1 Remove app-mode storage helpers, `X-App-Mode` header injection, and `defaultAppMode` logic from auth/session code.
- [x] 4.2 Remove designer/viewer segmented controls and viewer-mode routing from `AppShell` and related navigation.
- [x] 4.3 Replace the current visibility-based `PublishPanel` with a public-link publish dialog that supports publish, copy link, open preview, update publish, and cancel publish.
- [x] 4.4 Update `publishWorkspace` client code to send no visibility payload and consume returned token/public URL metadata.
- [x] 4.5 Add frontend client functions for publish status and cancel publish.
- [x] 4.6 Remove Publish-dialog user search and allowlist UI.
- [x] 4.7 Remove or rename the current Share button/dialog so public sharing is not duplicated beside Publish.
- [x] 4.8 If collaborator management remains, rename it to Collaborators and constrain all role options to editor-only.

## 5. Public Published Page UI

- [x] 5.1 Add a standalone public route such as `/p/[token]` outside the authenticated workbench shell.
- [x] 5.2 Fetch manifest and chart data through the public token APIs without auth headers.
- [x] 5.3 Render the published page sidebar, chart grid, and text zones from the snapshot with no editor controls or login prompts.
- [x] 5.4 Render a neutral invalid/expired-link state for 404 public-token responses.
- [x] 5.5 Remove embedded portal chat from the public page for this change, or hard-disable it behind a future capability flag.

## 6. Tests

- [x] 6.1 Add backend unit tests for public publication create-or-refresh, stable token reuse, revoke, and token resolution.
- [x] 6.2 Update publish integration tests to assert `POST /publish` returns public-link metadata and does not accept visibility payloads.
- [x] 6.3 Add unauthenticated public-read tests for manifest and chart data loading from snapshot files.
- [x] 6.4 Add security tests that unknown/revoked tokens return 404 and public responses omit membership, owner identity, visibility, and filesystem internals.
- [x] 6.5 Add migration/permission tests proving legacy viewer workspace memberships do not grant workspace access and are not upgraded to editor.
- [x] 6.6 Update frontend tests for Publish dialog states: unpublished, published, copy/open/update/cancel, and no user-search/allowlist controls.
- [x] 6.7 Add public route rendering tests for valid and invalid token states.
- [x] 6.8 Remove or rewrite old tests that assert viewer app mode, portal visibility filtering, allowlist publishing, or viewer invite behavior.

## 7. Cleanup and Verification

- [x] 7.1 Remove dead i18n keys and TypeScript types for visibility modes, app mode, viewer portal, and publish allowlists.
- [x] 7.2 Update docs and `.env.example` entries for the public base URL if a new setting is introduced.
- [x] 7.3 Run targeted backend tests for publish, portal/public read, workspace collaboration, auth, and security.
- [x] 7.4 Run targeted frontend Vitest coverage for publish dialog, public page route, auth/session, and workbench navigation.
- [x] 7.5 Run `openspec status --change replace-viewer-with-public-publish-links` and the relevant OpenSpec validation command before implementation is considered ready.
