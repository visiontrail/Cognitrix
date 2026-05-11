## 1. Storage Scope

- [x] 1.1 Add workspace-aware chat and trace storage key helpers for `(userId, workspaceId)`.
- [x] 1.2 Add a legacy migration marker so v1 user-scoped chat data is considered at most once per user.
- [x] 1.3 Update storage tests to cover v2 workspace keys and legacy malformed-data handling.

## 2. Chat Store

- [x] 2.1 Update chat store initialization to load state for `(userId, workspaceId)` and expose an empty state when no workspace is active.
- [x] 2.2 Update chat persistence and trace persistence to write only to the current workspace scope.
- [x] 2.3 Ensure pending ingestion approval/setup state is cleared or scoped when the initialized workspace changes.
- [x] 2.4 Add a session ownership check helper for validating that a session belongs to the active workspace scope.

## 3. Hooks And Workspace Switching

- [x] 3.1 Update `AppShell` or the equivalent workspace bootstrap flow to reinitialize chat whenever the active workspace changes.
- [x] 3.2 Include `workspaceId` in chat session and message React Query keys.
- [x] 3.3 Update create/delete/rename/session-touch invalidations to target the active workspace's chat query keys only.
- [x] 3.4 Reject send-message and ingestion-message mutations before streaming when no active workspace exists or the session is not in the active workspace scope.

## 4. UI Behavior

- [x] 4.1 Ensure the sidebar session list shows only sessions for the active workspace.
- [x] 4.2 Ensure the chat panel resets to the new workspace's active session or empty state after workspace switching.
- [x] 4.3 Keep published portal chat behavior unchanged because it is scoped by published page ID.

## 5. Verification

- [x] 5.1 Add or update chat store tests for switching between two workspaces and restoring each workspace's active session/messages/traces.
- [x] 5.2 Add or update UI tests for sidebar and chat panel workspace isolation.
- [x] 5.3 Add mutation tests confirming chat and ingestion sends include the active `workspace_id` and reject sessions from another workspace.
- [x] 5.4 Run the relevant frontend test suite and record any remaining gaps.
