## ADDED Requirements

### Requirement: Authenticated usage collection
The system SHALL record authenticated API request count, response status, latency, chat turns, tool calls, and available model input/output token metadata with user, route/event type, and timestamp dimensions. It MUST NOT record prompt text, response content, or secret values.

#### Scenario: User completes a chat turn
- **WHEN** an authenticated user completes a streamed chat request with two tool calls
- **THEN** usage storage records the chat turn, two tool-call events, request latency/status, and any runtime-provided token counts

### Requirement: Usage overview and trends
The admin API SHALL aggregate total/active users, request count, chat turns, tool calls, errors, token counts, and latency over a bounded date range, including daily trend points.

#### Scenario: Admin views the last seven days
- **WHEN** a superadmin requests the seven-day usage overview
- **THEN** the response returns summary totals and one ordered trend bucket per UTC date in range

### Requirement: Per-user usage breakdown
The admin API SHALL return a paginated per-user breakdown sortable by request count, chat turns, tool calls, token usage, or last activity.

#### Scenario: Identify most active users
- **WHEN** a superadmin sorts the usage table by chat turns descending
- **THEN** users are returned in descending chat-turn order with their last activity timestamp
