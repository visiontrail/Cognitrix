# workspace-conversations Specification

## Purpose
TBD - created by archiving change scope-conversations-to-workspace. Update Purpose after archive.
## Requirements
### Requirement: Workspace-scoped conversation persistence
The system SHALL persist chat sessions, active session selection, messages, and completed trace data independently for each `(user_id, workspace_id)` pair.

#### Scenario: Same user switches between workspaces
- **WHEN** a user has conversations in workspace A and then switches to workspace B
- **THEN** the chat session list, active session, messages, and completed traces shown in workspace B are loaded from workspace B's persisted conversation state only

#### Scenario: User returns to previous workspace
- **WHEN** the user switches from workspace B back to workspace A
- **THEN** the chat session list, active session, messages, and completed traces from workspace A are restored

#### Scenario: No workspace selected
- **WHEN** no active workspace is selected
- **THEN** the chat UI SHALL expose no active conversation and SHALL NOT persist new chat state

### Requirement: Workspace-scoped session lifecycle
The system SHALL create, rename, delete, and activate chat sessions only within the active workspace's conversation scope.

#### Scenario: Create session in active workspace
- **WHEN** the user creates a new chat session while workspace A is active
- **THEN** the new session is stored in workspace A's conversation state and MUST NOT appear in workspace B's session list

#### Scenario: Delete session in active workspace
- **WHEN** the user deletes a chat session while workspace A is active
- **THEN** the session and its messages are removed from workspace A only and workspace B's sessions remain unchanged

#### Scenario: Active session does not belong to workspace
- **WHEN** a workspace switch leaves the previous active session outside the newly active workspace scope
- **THEN** the active session is reset to the first session in the new workspace or `null` if none exists

### Requirement: Workspace-bound message sending
The system SHALL send assistant chat and ingestion conversation requests using the active workspace ID and a session ID that belongs to that workspace.

#### Scenario: Send message in workspace
- **WHEN** the user sends a chat message from a session in workspace A
- **THEN** the request body includes `workspace_id` for workspace A and `conversation_id` equal to that workspace A session ID

#### Scenario: Session from another workspace rejected
- **WHEN** the user attempts to send a message using a session ID that is not present in the active workspace's conversation scope
- **THEN** the client rejects the send before starting the stream and displays a user-facing chat error

#### Scenario: Ingestion approval cannot cross workspaces
- **WHEN** an ingestion plan is awaiting approval in workspace A and the user switches to workspace B
- **THEN** workspace B has no access to workspace A's pending approval or setup state

### Requirement: Workspace-aware chat caches
The system SHALL key chat session and message caches by workspace so cached UI data cannot be reused across workspace switches.

#### Scenario: Session cache invalidation
- **WHEN** a session is created, renamed, or deleted in workspace A
- **THEN** only workspace A's chat session cache is invalidated

#### Scenario: Message cache lookup
- **WHEN** the chat panel loads messages for a session while workspace B is active
- **THEN** the cache lookup includes workspace B and the session ID

### Requirement: Legacy user-scoped conversation handling
The system SHALL handle existing user-scoped local conversation data without displaying it globally across every workspace.

#### Scenario: First workspace-scoped load with legacy data
- **WHEN** workspace-scoped conversation storage is empty and legacy user-scoped conversation storage exists
- **THEN** the system MAY migrate the legacy data into only the currently active workspace and SHALL record that the legacy data was considered for migration

#### Scenario: Subsequent workspace-scoped loads
- **WHEN** another workspace loads after legacy data was considered for migration
- **THEN** the system SHALL NOT duplicate the legacy user-scoped conversations into that other workspace

#### Scenario: Invalid legacy data
- **WHEN** legacy user-scoped conversation storage is malformed or references missing sessions
- **THEN** the system SHALL ignore the invalid legacy data and initialize the workspace conversation state as empty

