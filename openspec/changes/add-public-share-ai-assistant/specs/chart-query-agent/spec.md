## MODIFIED Requirements

### Requirement: Chart Query Agent runtime backed by snapshot data
A `ChartQueryAgent` backend class SHALL wrap `ClaudeSDKClient` the same way as `AgentRuntime`, but with a restricted MCP tool set operating on public published snapshot data only. The agent MUST resolve work from the active public token chat route and MUST NOT have access to any live DuckDB session or to tables outside the published page's snapshot.

#### Scenario: Agent initialized per public token
- **WHEN** a chat message is sent to `POST /public/pages/{token}/chat`
- **THEN** the backend resolves the active publication for `token`, loads or retrieves the active snapshot DuckDB for that published page, and routes the message through `ChartQueryAgent`

#### Scenario: Agent tools limited to snapshot
- **WHEN** the `ChartQueryAgent` executes a tool call
- **THEN** only `list_snapshot_tables`, `describe_snapshot_table`, and `query_snapshot_table` are available; any attempt to call a non-snapshot tool is rejected by the guardrail

#### Scenario: Live session isolation
- **WHEN** `ChartQueryAgent` runs
- **THEN** it has no reference to any `AgentRuntime` instance, live DuckDB session, upload-tier dataset, workspace draft state, or designer chat session

#### Scenario: Claude Agent SDK loop executes the turn
- **WHEN** `ChartQueryAgent` processes a valid public assistant turn
- **THEN** it MUST instantiate and run a `ClaudeSDKClient`/`ClaudeAgentOptions` loop with the snapshot-only tools and system prompt
- **AND** it MUST NOT return a placeholder response that bypasses the agent loop

### Requirement: Snapshot DuckDB loaded lazily and cached with TTL
The backend SHALL maintain an LRU cache of in-memory DuckDB instances keyed by active published page id and version. Each instance is loaded on first chat request from assistant data files in the snapshot and evicted after a configurable TTL (default: 30 minutes) or when the cache reaches its max size (default: 10 entries).

#### Scenario: Cache hit
- **WHEN** a second chat message arrives for the same active published page version within the TTL
- **THEN** the snapshot DuckDB is retrieved from cache without re-reading snapshot files

#### Scenario: Cache eviction on TTL
- **WHEN** the TTL expires for a cached snapshot DuckDB
- **THEN** the entry is evicted; the next request for that published page reloads from snapshot files

#### Scenario: Cache eviction on capacity
- **WHEN** the cache is at max size and a new published page is requested
- **THEN** the least-recently-used entry is evicted to make room

#### Scenario: Assistant data files populate tables
- **WHEN** the snapshot cache loads a published page whose manifest has `assistant.available=true`
- **THEN** it MUST create one read-only DuckDB table per assistant-enabled chart entry from `assistant_data_path`
- **AND** each table's metadata MUST include chart id, title, chart type, row count, and column names

### Requirement: Chart context scopes the agent conversation
When a chat message is sent with a `chart_id` field, the system SHALL prepend a system prompt prefix informing the agent which snapshot table is active and what the chart represents, based on the chart's `spec.json`, assistant data metadata, and manifest node metadata.

#### Scenario: Chart selected before asking
- **WHEN** the user selects a chart on the published page and sends a message
- **THEN** the request body includes `{ "chart_id": "<id>", "message": "..." }` and the agent's system prompt includes the chart's table name, column descriptions, row count, chart title, and chart type

#### Scenario: No chart selected
- **WHEN** the user sends a message without selecting a chart
- **THEN** the agent operates with visibility of all assistant-enabled snapshot tables and selects the most relevant one based on the question

#### Scenario: Chart context reset on deselection
- **WHEN** the user deselects the active chart or asks from page-level context
- **THEN** subsequent messages are sent without `chart_id`

### Requirement: Agent responses streamed as SSE to the portal chat window
The public assistant chat endpoint `POST /public/pages/{token}/chat` SHALL stream events using the same SSE event types as the existing query runtime: `planning`, `tool_use`, `tool_result`, `final`, `error`. Every `tool_use` and `tool_result` payload SHALL include a `step_id` (string, stable across the matching call/result pair) and `started_at` (epoch seconds set at tool-call time); each `tool_result` SHALL additionally include `completed_at` (epoch seconds). These correlation fields are required so the public assistant UI can pair tool calls to their results without relying on event ordering.

#### Scenario: Streaming response received
- **WHEN** the `ChartQueryAgent` processes a turn
- **THEN** the public assistant drawer displays events progressively as they arrive: tool use indicators while querying, then the final answer

#### Scenario: Error event on agent failure
- **WHEN** the `ChartQueryAgent` encounters an unrecoverable error
- **THEN** an `error` SSE event is emitted and the assistant drawer displays a user-facing error message

#### Scenario: Tool events carry step correlation metadata
- **WHEN** the `ChartQueryAgent` issues a tool call
- **THEN** the `tool_use` payload contains a non-empty `step_id` and a numeric `started_at`
- **AND WHEN** the matching `tool_result` arrives
- **THEN** it carries the same `step_id`, the original `started_at`, and a `completed_at` greater than or equal to `started_at`

### Requirement: Agent guardrails apply to snapshot queries
The `ChartQueryAgent` SHALL apply the same SQL-read-only validation (`SQLReadOnlyValidator`) to any SQL executed against the snapshot DuckDB. Write operations (INSERT, UPDATE, DELETE, DROP, CREATE) MUST be rejected.

#### Scenario: Read-only SQL accepted
- **WHEN** the agent issues a SELECT query against a snapshot table
- **THEN** the query executes and results are returned

#### Scenario: Write SQL rejected
- **WHEN** the agent attempts a mutating SQL statement
- **THEN** `SQLReadOnlyValidator` raises a validation error, the query is not executed, and an `error` event is emitted
