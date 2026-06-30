# public-share-ai-assistant Specification

## Purpose
TBD - created by archiving change add-public-share-ai-assistant. Update Purpose after archive.
## Requirements
### Requirement: Public page exposes an AI Assistant action
The public published page SHALL render an `AI Assistant` action in the existing top-right public action group beside Export, Print, and the theme toggle when the active published snapshot declares assistant data availability. Activating the action SHALL open a right-side assistant drawer without navigating away from the public page.

#### Scenario: Assistant action appears beside public controls
- **WHEN** a visitor opens a valid public published page whose manifest has `assistant.available=true`
- **THEN** the public action group MUST include an `AI Assistant` button beside Export, Print, and the theme toggle

#### Scenario: Assistant drawer opens
- **WHEN** the visitor clicks the `AI Assistant` button
- **THEN** a right-side assistant drawer opens over the public page
- **AND** the published page remains visible and scrollable behind or beside the drawer

#### Scenario: Legacy snapshot without assistant data
- **WHEN** a visitor opens a valid public published page whose manifest does not declare complete assistant data
- **THEN** the public page MUST NOT start an assistant conversation against incomplete data
- **AND** the assistant action MUST be hidden or disabled with a non-sensitive unavailable state

### Requirement: Assistant can answer from all published chart-node datasets
The public assistant SHALL answer questions using all assistant-readable raw rows attached to chart nodes in the active published snapshot. The assistant context SHALL include chart id, node id, chart title, chart type, row counts, column names, and page/section metadata where available.

#### Scenario: Page-level question uses all chart data
- **WHEN** the visitor asks a question without selecting a specific chart
- **THEN** the assistant MUST have access to every assistant-enabled chart-node dataset in the active published snapshot
- **AND** it MAY combine data across multiple published chart nodes when answering

#### Scenario: Chart-specific question uses selected chart context
- **WHEN** the visitor asks a question with a selected `chart_id`
- **THEN** the assistant request MUST include that `chart_id`
- **AND** the assistant prompt MUST identify the selected chart while preserving access to the rest of the published page data

#### Scenario: Assistant is scoped to published snapshot
- **WHEN** the assistant answers any public-page question
- **THEN** it MUST use only data and metadata from the active immutable published snapshot
- **AND** it MUST NOT use live workspace state, unpublished nodes, designer chat history, or live DuckDB tables

### Requirement: Assistant drawer streams agent progress and final answers
The assistant drawer SHALL consume the public assistant SSE stream and render progressive agent activity using the same public-facing event types as the designer chat trace: `planning`, `tool_use`, `tool_result`, `final`, and `error`.

#### Scenario: Streaming progress is shown
- **WHEN** the assistant endpoint emits `planning`, `tool_use`, or `tool_result` events
- **THEN** the drawer MUST show a compact live trace for the running answer

#### Scenario: Final answer is appended
- **WHEN** the assistant endpoint emits a `final` event
- **THEN** the drawer MUST append the final answer to the conversation
- **AND** the input MUST become available for another question

#### Scenario: Error is shown without losing history
- **WHEN** the assistant endpoint emits an `error` event or the stream fails
- **THEN** the drawer MUST show a user-facing failure message
- **AND** previously rendered messages in the drawer MUST remain visible

### Requirement: Public assistant conversation state is page-session scoped
The public assistant SHALL keep the visitor's conversation history scoped to the currently opened public page session. The frontend SHALL generate or reuse a `conversation_id` for the active drawer session and send it with assistant requests.

#### Scenario: Drawer preserves conversation while open
- **WHEN** the visitor asks multiple questions during one public-page session
- **THEN** the drawer MUST preserve the prior messages for that session
- **AND** each request MUST carry the same `conversation_id`

#### Scenario: Page reload starts a clean local session
- **WHEN** the visitor reloads the public page
- **THEN** the assistant MAY start with an empty local message history
- **AND** no durable public chat history is required

