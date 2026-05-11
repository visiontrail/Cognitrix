## Why

Conversation state is currently scoped globally per user, so switching workspaces can show the wrong chat sessions, messages, traces, and pending ingestion approvals. Workspace users need the assistant conversation to follow the active workspace so each workspace keeps its own context and history.

## What Changes

- Scope chat sessions, active session selection, messages, traces, and pending ingestion state by `workspace_id`.
- Restore the correct conversation list and active conversation when the user switches workspaces.
- Ensure outgoing chat and ingestion requests always bind to the active workspace and cannot reuse a session from another workspace.
- Preserve existing per-user isolation while adding workspace-level isolation beneath it.
- Provide migration/fallback handling for existing user-level local conversation data.

## Capabilities

### New Capabilities
- `workspace-conversations`: Defines workspace-scoped chat sessions, message history, traces, pending ingestion state, and behavior when switching workspaces.

### Modified Capabilities

## Impact

- Affected frontend state: `apps/web/stores/chat-store.ts`, `apps/web/hooks/use-chat.ts`, chat session/message query keys, workspace switching flows, and local storage keys.
- Affected backend/API contract: workspace-bound chat stream requests and ingestion conversation requests must keep validating and using `workspace_id`.
- Affected tests: chat store persistence, workspace switching behavior, send-message guards, and regression coverage for not leaking conversations across workspaces.
