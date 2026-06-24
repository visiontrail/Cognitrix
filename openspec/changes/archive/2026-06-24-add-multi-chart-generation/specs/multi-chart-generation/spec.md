## ADDED Requirements

### Requirement: Multi-chart intent is detected before chart generation
The Designer chat runtime SHALL detect when a user turn should produce more than one chart before executing the chart generation path. Detection SHALL cover explicit multi-chart requests and inferred per-segment requests such as generating the same analysis for every department, region, job family, or other dataset dimension.

#### Scenario: Explicit multi-chart request is detected
- **WHEN** a user asks the Designer chat to generate multiple charts in one turn
- **THEN** the runtime identifies the turn as a multi-chart candidate before producing any chart spec

#### Scenario: Per-dimension request is detected
- **WHEN** a user asks for a chart separately for every value of a dimension such as department
- **THEN** the runtime infers the grouping dimension and candidate chart set before producing any chart spec

#### Scenario: Single-chart request bypasses multi-chart flow
- **WHEN** a user asks for one aggregate chart without per-segment or multiple-chart intent
- **THEN** the runtime continues through the existing single-chart generation flow without emitting a multi-chart confirmation

### Requirement: Multi-chart generation requires user confirmation
Whenever the runtime determines that more than one chart should be generated, it MUST ask for user confirmation before generating chart specs. Confirmation SHALL be required even when the user's prompt explicitly requests multiple charts.

#### Scenario: Confirmation is emitted for inferred multi-chart intent
- **WHEN** the runtime infers that the answer should be multiple charts
- **THEN** it emits a `confirmation_required` SSE event with `confirmation_type` set to `multi_chart_generation`
- **AND** it emits a terminal `final` SSE event with `status` set to `awaiting_confirmation`
- **AND** it does not emit any chart `spec` event before confirmation

#### Scenario: Confirmation includes proposed chart count
- **WHEN** the runtime emits a multi-chart confirmation request
- **THEN** the payload includes a stable `confirmation_id`, inferred grouping dimension, proposed chart items, proposed count, maximum allowed count, and a localized explanation of why multiple charts are proposed

#### Scenario: Explicit multi-chart prompt still requires confirmation
- **WHEN** the user explicitly asks for multiple charts in the prompt
- **THEN** the runtime still emits a multi-chart confirmation request before generating those charts

#### Scenario: User cancels confirmation
- **WHEN** the user cancels a pending multi-chart confirmation
- **THEN** the runtime clears the pending confirmation state
- **AND** emits a terminal response without generating chart specs

### Requirement: User can adjust the confirmed chart set
The confirmation UI and backend request contract SHALL let the user confirm the proposed chart set, narrow selected items, adjust the chart count within limits, or cancel generation. The backend MUST validate the confirmed selection against the pending confirmation state.

#### Scenario: User confirms proposed chart set
- **WHEN** the user confirms the proposed chart set without edits
- **THEN** the next chat request includes the matching `confirmation_id` and approved chart items
- **AND** the backend starts the multi-chart generation flow for those items

#### Scenario: User narrows chart selection
- **WHEN** the user selects fewer chart items than originally proposed
- **THEN** the backend generates charts only for the selected items

#### Scenario: User exceeds maximum count
- **WHEN** the user confirms more chart items than the configured maximum allows
- **THEN** the backend rejects the confirmation
- **AND** no chart specs are generated

#### Scenario: Stale confirmation is rejected
- **WHEN** the frontend submits a missing, expired, or mismatched `confirmation_id`
- **THEN** the backend emits an `error` SSE event and a terminal `final` SSE event
- **AND** no chart specs are generated

### Requirement: Confirmed multi-chart generation emits grouped chart specs
After a valid confirmation, the runtime SHALL execute a dedicated multi-chart generation flow and emit each generated chart as its own `spec` SSE event. Every emitted chart spec MUST be associated with the same multi-chart group and MUST carry stable per-chart metadata.

#### Scenario: Multiple chart specs are streamed
- **WHEN** the user confirms generation of N chart items
- **THEN** the runtime emits N successful `spec` SSE events when all N charts are generated successfully
- **AND** each `spec` payload includes `multi_chart_group_id`, `chart_id`, `chart_index`, `chart_count`, `chart_key`, `chart_label`, and `spec`

#### Scenario: Chart order is stable
- **WHEN** multiple specs are emitted for one multi-chart group
- **THEN** `chart_index` values preserve the confirmed item order
- **AND** frontend rendering does not depend on network arrival order

#### Scenario: Final response summarizes generated charts
- **WHEN** multi-chart generation completes
- **THEN** the terminal `final` SSE payload includes `status: "completed"` and a summary of generated chart ids, titles, and any failed chart items

#### Scenario: Partial chart failure is reported
- **WHEN** at least one confirmed chart item fails but at least one chart succeeds
- **THEN** the runtime emits `spec` events for the successful charts
- **AND** the terminal `final` payload reports partial completion and lists failed chart labels

### Requirement: Multi-chart generation uses existing data security controls
The multi-chart planner and generator SHALL use the same dataset scoping, read-only SQL validation, row-level security, sensitive-column redaction, and role permissions as the existing single-chart query runtime.

#### Scenario: Planner queries distinct dimension values
- **WHEN** the planner queries possible grouping values for a dimension
- **THEN** the query is executed through the existing read-only guarded tool path
- **AND** values outside the user's role, department, or clearance scope are not exposed

#### Scenario: Generator executes per-chart queries
- **WHEN** the generator executes a query for an approved chart item
- **THEN** SQL validation, RLS injection, and sensitive data policy checks are applied before returning rows to the agent

#### Scenario: Unauthorized field is requested
- **WHEN** the multi-chart flow attempts to use a forbidden sensitive column
- **THEN** the request is rejected or redacted according to the existing security policy
- **AND** no unauthorized data appears in confirmation payloads, chart specs, or final text

### Requirement: Frontend renders confirmation and multiple chart assets
The Designer chat UI SHALL render multi-chart confirmation requests as an interactive question box and SHALL render confirmed multi-chart results as multiple chart cards tied to one assistant message.

#### Scenario: Confirmation question box appears
- **WHEN** a `confirmation_required` SSE event with `confirmation_type: "multi_chart_generation"` arrives
- **THEN** the active assistant message displays a confirmation question box with the proposed count and chart labels

#### Scenario: Confirm action resumes generation
- **WHEN** the user confirms from the question box
- **THEN** the frontend sends a typed confirmation payload to `POST /chat/stream`
- **AND** the UI shows the resumed generation trace in the same chat session

#### Scenario: Multiple chart cards render in one message
- **WHEN** multiple grouped `spec` events are received for one assistant response
- **THEN** the frontend archives each spec as an individual `ChartAsset`
- **AND** the assistant message displays a chart card for each generated asset

#### Scenario: Multi-chart assets persist across reload
- **WHEN** the page reloads after a completed multi-chart response
- **THEN** the chat message still references all generated chart assets
- **AND** each chart card can be opened or added to the workspace

### Requirement: Single-chart compatibility is preserved
Existing single-chart chat behavior SHALL remain compatible with clients and tests that expect one chart spec and one primary chart asset.

#### Scenario: Existing spec event remains valid
- **WHEN** a single-chart response is generated
- **THEN** the backend emits the existing `spec` payload shape with a single `spec` object
- **AND** the frontend creates one `ChartAsset` and one `chartAsset` message reference

#### Scenario: Multi-chart message keeps primary asset compatibility
- **WHEN** a multi-chart response creates multiple assets
- **THEN** the message stores all assets in `chartAssets`
- **AND** the first successful asset is also exposed through the existing `chartAsset` field for compatibility
