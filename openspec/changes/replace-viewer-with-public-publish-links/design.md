## Context

Cognitrix currently mixes two concepts:

1. workspace collaboration, where a user can be `owner`, `editor`, or `viewer`;
2. published-page consumption, where a logged-in viewer reaches pages through `/portal` and visibility rules (`private`, `registered`, `allowlist`).

That produces a product split between "designer" and "viewer" modes. The requested target is simpler and closer to Notion/RavenAI sharing: designers publish a read-only snapshot and receive a public link. Anyone with the link can view the page. Nobody needs to become a viewer account, workspace member, or portal user.

The repository already has the hard part of publishing: immutable snapshot files under `UPLOAD_DIR/published/{workspace_id}/{version}/`, row caps, and redaction. RavenAI provides the reference lifecycle: owner-side create/status/revoke endpoints, high-entropy token, public unauthenticated read route, refresh-in-place semantics, and immediate 404 after revoke.

## Goals / Non-Goals

**Goals:**

- Remove viewer as a product mode and workspace collaboration role.
- Make Publish the only sharing action for read-only consumption.
- Provide one active public publish link per workspace, with status, copy/open, update publish, and cancel publish actions.
- Keep snapshot semantics: publishing captures the page at a point in time; later workspace edits do not alter the public page until the designer updates the publish.
- Keep public tokens decoupled from `workspace_id`, `page_id`, user id, version, and timestamps.
- Serve public pages without authentication while preserving redaction, row caps, and static snapshot reads.
- Keep owner/editor checks for all publish management operations.

**Non-Goals:**

- Building granular per-user published-page permissions.
- Keeping a logged-in viewer portal or viewer dashboard.
- Reworking the BI chart snapshot file format beyond public-link metadata.
- Adding password-protected or expiring public links in this change.
- Removing authenticated editor collaboration entirely; owner/editor collaboration can remain, but viewer collaboration cannot.

## Decisions

### Decision 1: Publish link is a first-class lifecycle, not `visibility_mode = registered`

The new model SHALL add public-link state instead of treating `registered` visibility as "public enough". A public publish link needs fields that visibility does not provide cleanly:

- `token`: high-entropy public identifier, generated with `secrets.token_urlsafe(16)` or stronger.
- `workspace_id`: owning workspace.
- `active_page_id`: currently served snapshot/version.
- `is_active`: revocation switch.
- `published_at` / `updated_at`: public snapshot timestamp.
- optional `revoked_at`.

Implementation can either extend `published_pages` or create a small companion table such as `workspace_publications`. Prefer the companion table because existing `published_pages` already represents immutable versions, while the public link is mutable state that points at the current public version.

Alternative considered: keep `visibility_mode = registered` and expose existing `page_id`. Rejected because it keeps the old registered/viewer mental model, exposes an internal page id as the public locator, and does not give clean refresh/revoke semantics.

### Decision 2: One active token per workspace, refreshed in place

Like RavenAI conversation sharing, publishing a workspace repeatedly SHALL refresh the active public snapshot and reuse the same public token while active. The system still creates a new immutable `published_pages` version on each publish/update, then repoints the active publication row to that latest page.

This preserves version history for designers while keeping copied links stable. A user who already shared the link does not need to send a new URL after updating the published snapshot.

Alternative considered: generate a new token for every version. Rejected because it makes "update publish" behave like "create a different public page" and breaks the Notion-like stable link expectation.

### Decision 3: Public read route is unauthenticated and token based

The public route SHALL not depend on `get_current_identity`, cookies, workspace membership, or `X-App-Mode`. It returns only the active snapshot addressed by token, and unknown/revoked tokens return 404.

Recommended API shape:

- `GET /public/pages/{token}/manifest`
- `GET /public/pages/{token}/charts/{chart_id}/data`

The frontend browser route can be `/p/{token}` or `/publish/{token}`. The owner-facing response returns the complete browser-openable URL, built from `PUBLIC_BASE_URL` or request origin/base URL using the same priority as RavenAI.

Alternative considered: continue using `/portal/pages/{page_id}/manifest`. Rejected because `/portal` currently implies logged-in discovery and visibility filtering, while the new public model is direct-link access.

### Decision 4: Owner/editor management remains authenticated

Only workspace `owner` and `editor` users can publish, update the public snapshot, get publication status, or cancel the public link. Public readers get no mutation endpoints, no workspace membership, and no workspace list.

Recommended owner-side API shape:

- `POST /workspaces/{workspace_id}/publish`: create or refresh the public snapshot and return `{token, public_url, published_page_id, version, published_at, is_active}`.
- `GET /workspaces/{workspace_id}/publish`: return current publication status or `{is_active: false}`.
- `DELETE /workspaces/{workspace_id}/publish`: revoke the active public link and make public reads return 404.
- `GET /workspaces/{workspace_id}/published`: keep authenticated history for owner/editor only.

Alternative considered: keep `PATCH /published/{version}/visibility`. Rejected because there is no longer a visibility matrix to patch.

### Decision 5: Workspace roles become owner/editor only for product collaboration

The user-facing workspace membership model SHALL remove `viewer`. Existing `viewer` rows need migration. The least surprising migration is to remove viewer memberships from collaborative access because public readers no longer need membership. If a deployment used viewer rows for people who should edit, an admin/designer must re-add those users as editors.

Internal BI data roles such as auth/runtime `role="viewer"` may still exist where they mean data clearance or row-level policy, but they MUST NOT drive workspace membership or app mode. Implementation should avoid broad string replacement; only workspace collaboration and app-mode contracts are in scope.

Alternative considered: map existing viewer memberships to editor. Rejected because it silently grants write access to users who previously had read-only access.

### Decision 6: Frontend Publish dialog owns link management

The existing publish visibility panel should be replaced by a dialog modeled on RavenAI's "分享对话" UI:

- Title: publish/share wording for a public page link.
- Explanation: anyone with the link can view the published snapshot.
- Public link field and copy button when active.
- Snapshot timestamp and note that later edits/messages do not appear until update.
- Actions: open preview, update publish, cancel publish.
- Warning copy for sensitive data.

The existing separate `ShareDialog` should not appear beside Publish for viewer consumption. If editor collaboration remains, it should be renamed away from public sharing (for example "Collaborators") so Publish is the only public-link concept.

Alternative considered: keep Share for public link and Publish for snapshots. Rejected because the user explicitly wants RavenAI's "share" behavior to map to this project's "publish".

## Risks / Trade-offs

- Public links can expose sensitive published data if a designer publishes the wrong page -> keep the warning explicit, preserve redaction at publish time, and make cancel publish immediate.
- Old visibility columns and code paths may continue influencing access if only frontend is changed -> remove visibility validation and visible-workspace filtering from backend contracts, then cover with tests.
- Existing viewer memberships become inaccessible after migration -> document this as intentional and do not auto-upgrade viewers to editors.
- Public token scan attempts are possible -> generate high-entropy tokens and add basic per-IP rate limiting to public manifest/data endpoints.
- Browser caches may briefly show revoked content -> use no-store or short-cache headers for public JSON endpoints unless a stronger CDN invalidation story exists.
- Public chart query/chat features may accidentally create authenticated assumptions -> either remove embedded portal chat from public pages for this change or ensure any public chart query endpoint is explicitly designed with snapshot-only, token-only access.

## Migration Plan

1. Add public publication state and APIs while keeping old columns readable for rollback.
2. Update publish creation to always create/refresh a public link and stop writing new visibility decisions.
3. Add unauthenticated public token read routes with 404 for unknown/revoked tokens.
4. Replace the frontend Publish dialog and remove app-mode/viewer routing.
5. Remove viewer role choices from collaborator UI and reject new `viewer` workspace memberships/invites.
6. Migrate existing `workspace_members.role = 'viewer'` out of active collaborative access, preferably by deleting or marking those rows according to the existing migration conventions.
7. Deprecate old `/portal/workspaces` viewer discovery and visibility endpoints. Keep only authenticated designer history and public token reads.
8. After tests pass, remove dead frontend i18n keys, types, and API clients tied to visibility modes and app mode.

Rollback is straightforward if the old columns are retained during the initial deployment: re-enable the old publish dialog/routes and ignore the companion public publication rows. After old UI/API removal is shipped, rollback requires restoring the previous application build.

## Open Questions

- Public browser route name: `/p/{token}`, `/publish/{token}`, or `/portal/{token}`. The design recommends `/p/{token}` for brevity and to avoid the old portal semantics.
- Whether public pages should include embedded AI chart chat in this change. The safer v1 is read-only charts/text only; public chart chat can be proposed separately with explicit abuse and cost controls.
- How to represent migrated viewer memberships in audit logs. The implementation should preserve enough audit detail to explain why a former viewer no longer sees a workspace.
