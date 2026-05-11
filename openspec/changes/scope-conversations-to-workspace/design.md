## Context

The workspace UI already has a first-class active workspace in `useWorkspaceStore`, and chat requests include `workspace_id` when streaming assistant responses and ingestion workflows. However, the frontend chat store persists sessions and messages with keys scoped only by user (`cognitrix:chat:v1:<userId>` and `cognitrix:chat-trace:v1:<userId>`), and React Query uses global chat keys such as `["chat-sessions"]`. As a result, a user can switch from workspace A to workspace B while still seeing and reusing workspace A conversation IDs, messages, traces, pending approvals, and session metadata.

The change should keep local-first chat persistence and existing backend streaming behavior. It should add workspace scoping at the state and cache boundaries so the same user has independent conversation state per workspace.

## Goals / Non-Goals

**Goals:**
- Persist and restore chat sessions, active session, messages, traces, and pending ingestion state per `(user_id, workspace_id)`.
- Reset or reload chat state immediately when the active workspace changes.
- Prevent sending a message through a session that does not belong to the active workspace.
- Keep existing user isolation and authentication behavior intact.
- Provide safe compatibility for existing localStorage data so old user-scoped sessions do not leak into every workspace.

**Non-Goals:**
- Add server-side durable chat history storage.
- Change agent reasoning, chart generation, or ingestion semantics beyond workspace binding.
- Change published portal chat, which already stores sessions per published `pageId`.
- Introduce cross-workspace conversation search or sharing.

## Decisions

1. Use `(userId, workspaceId)` as the persistence scope for chat state.

   Chat storage helpers should expose workspace-aware keys, for example `cognitrix:chat:v2:<userId>:<workspaceId>` and `cognitrix:chat-trace:v2:<userId>:<workspaceId>`. This keeps data isolated without needing a larger nested persistence document. The prior v1 keys remain readable only for a controlled one-time migration path.

   Alternative considered: store all workspace conversations in one per-user object. That makes migration easier but increases write amplification and makes corruption in one large localStorage value more damaging.

2. Make chat store initialization workspace-aware.

   `useChatStore.initForUser` should become or be complemented by an initializer that takes both `userId` and `workspaceId`. The store should track the currently initialized pair and load a new persisted slice whenever that pair changes. When there is no active workspace, the store should expose an empty chat state and avoid persisting new sessions.

   Alternative considered: filter a single global `sessions` array by a `workspaceId` field. This still risks active-session and pending-state bleed if callers forget to filter, and it leaves old storage organized around the wrong boundary.

3. Include `workspaceId` in chat query keys and mutation invalidation.

   Hooks such as `useChatSessions`, `useChatMessages`, `useCreateSession`, and `useDeleteSession` should take or derive the active workspace ID and use query keys like `["chat-sessions", workspaceId]` and `["chat-messages", workspaceId, sessionId]`. Mutations should invalidate only the active workspace's chat queries.

   Alternative considered: rely only on Zustand reactivity. Query keys currently describe the chat data contract for components and tests; keeping them workspace-aware prevents stale cache reads after workspace switches.

4. Keep session IDs opaque but validate session ownership in the frontend.

   `ChatSession` should carry `workspaceId` or the store should enforce membership through the workspace-scoped slice. Message send paths should verify that `sessionId` exists in the currently initialized workspace before streaming. Requests continue sending `conversation_id: sessionId` and `workspace_id: activeWorkspaceId`.

   Alternative considered: prefix session IDs with workspace IDs. This helps debugging but makes IDs user-visible in some places and is unnecessary if store boundaries are correct.

5. Treat legacy v1 localStorage as unassigned and migrate conservatively.

   On first load of a workspace-scoped key, the app may import v1 chat data only into the user's currently active workspace, then mark that legacy key as migrated for that user. If migration metadata is absent or invalid, the safer fallback is to ignore v1 data rather than show it in every workspace.

   Alternative considered: duplicate v1 data into each workspace. That preserves visibility but directly violates the requirement by spreading global conversations across workspaces.

## Risks / Trade-offs

- Existing users may not see old local conversations in secondary workspaces after migration → migrate v1 data only once into the first active workspace and keep legacy data untouched for potential manual recovery.
- Components may still read `useChatStore` without workspace context → centralize initialization in `AppShell` and add tests around workspace switching and sidebar session lists.
- Pending ingestion approvals are currently memory-only → clear or namespace pending approval/setup maps on workspace switch so a plan from one workspace cannot be approved in another.
- Trace persistence can leave orphaned entries when messages move or are deleted → save trace data under the same workspace key and prune traces to message IDs in the current workspace slice during load.
- Backend accepts arbitrary `conversation_id` strings → frontend scoping prevents normal leakage, while backend requests must continue requiring `workspace_id` and using workspace authorization for data access.

## Migration Plan

1. Add workspace-aware storage key helpers and a migration marker key.
2. Update chat store initialization, persistence, trace persistence, and clear behavior to use `(userId, workspaceId)`.
3. Update chat hooks and query invalidation to include workspace ID.
4. Update workspace switch flow so chat state reloads when `activeWorkspaceId` changes and becomes empty when no workspace is selected.
5. Add focused tests for storage keys, workspace switching, session creation/deletion, message send guards, traces, and pending ingestion isolation.
6. Rollback by retaining v1 readers and reverting callers to user-only initialization if a production issue appears; v2 workspace keys are additive and do not destroy v1 data.
