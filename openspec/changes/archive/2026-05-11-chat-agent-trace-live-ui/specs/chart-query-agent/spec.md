## MODIFIED Requirements

### Requirement: Agent responses streamed as SSE to the portal chat window

The portal chat endpoint `POST /portal/pages/{page_id}/chat` SHALL stream events using the same SSE event types as the existing query runtime: `planning`, `tool_use`, `tool_result`, `final`, `error`. Every `tool_use` and `tool_result` payload SHALL include a `step_id` (string, stable across the matching call/result pair) and `started_at` (epoch seconds set at tool-call time); each `tool_result` SHALL additionally include `completed_at` (epoch seconds). These correlation fields are required so any consuming UI (Designer or portal) can pair tool calls to their results without relying on event ordering.

#### Scenario: Streaming response received

- **WHEN** the `ChartQueryAgent` processes a turn
- **THEN** the portal chat window displays events progressively as they arrive: tool use indicators while querying, then the final answer

#### Scenario: Error event on agent failure

- **WHEN** the `ChartQueryAgent` encounters an unrecoverable error
- **THEN** an `error` SSE event is emitted and the chat window displays a user-facing error message

#### Scenario: Tool events carry step correlation metadata

- **WHEN** the `ChartQueryAgent` issues a tool call
- **THEN** the `tool_use` payload contains a non-empty `step_id` and a numeric `started_at`
- **AND WHEN** the matching `tool_result` arrives
- **THEN** it carries the same `step_id`, the original `started_at`, and a `completed_at` greater than or equal to `started_at`
