## ADDED Requirements

### Requirement: Agent SSE events expose step correlation metadata

Every `tool_use` and `tool_result` SSE payload emitted by `AgentRuntime` SHALL include a `step_id` (string, stable across the matching call/result pair) and `started_at` (epoch seconds, set at tool-call time). Each `tool_result` SHALL additionally include `completed_at` (epoch seconds). These fields MUST be present on both the Designer chat surface (`POST /chat/stream`) and the portal chat surface (`POST /portal/pages/{page_id}/chat`).

#### Scenario: Tool call/result pair share a step_id

- **WHEN** the agent executes a tool and `tool_use` is emitted
- **THEN** the payload contains a non-empty `step_id` and a numeric `started_at`
- **AND WHEN** the matching `tool_result` is emitted
- **THEN** the payload contains the same `step_id`, the original `started_at`, and a numeric `completed_at` greater than or equal to `started_at`

#### Scenario: Parallel tool calls remain pairable

- **WHEN** the agent issues two `execute_readonly_sql` calls in the same turn before either result returns
- **THEN** each `tool_use` payload carries a distinct `step_id`
- **AND** each subsequent `tool_result` is matched to its `tool_use` solely by `step_id`, regardless of arrival order

#### Scenario: Errored tool result preserves correlation

- **WHEN** a tool fails and the runtime emits a `tool_result` with an error payload
- **THEN** the payload still carries the originating `step_id`, `started_at`, and `completed_at`

### Requirement: Designer chat panel renders a live agent trace during streaming

While a chat turn's SSE stream is open in the Designer Conversation panel, the assistant message SHALL display an inline trace listing every received `planning`, `tool_use`, `tool_result`, and `error` event in arrival order. The trace MUST be visible without any user interaction and MUST update in place as new events arrive.

#### Scenario: Planning event renders as a thought row

- **WHEN** a `planning` SSE event arrives during a turn
- **THEN** a new row is appended to the active assistant message's trace, marked as a planning step, with a label preview of the thought text

#### Scenario: Tool call appears immediately, result patches the same row

- **WHEN** a `tool_use` SSE event arrives
- **THEN** a tool row is appended in `running` status, showing the tool name and a one-line argument preview
- **AND WHEN** the matching `tool_result` arrives (correlated by `step_id`)
- **THEN** the same row is updated in place to `ok` or `error` status, displaying its duration and a result preview

#### Scenario: Most recent live step is visually highlighted

- **WHEN** the trace is in `live` state and contains at least one step
- **THEN** the most recently received step displays a subtle pulsing indicator
- **AND** earlier steps render statically without animation

#### Scenario: Error event renders as an error step

- **WHEN** an `error` SSE event arrives mid-turn
- **THEN** an error row is appended with the error message and (when present) error code

### Requirement: Trace auto-collapses on turn completion

The trace SHALL transition from `live` to `collapsed` exactly once per turn, on the earliest of: receipt of a `final` SSE event, receipt of an `error` SSE event, or stream-reader close. Once collapsed, the trace MUST hide all step rows and replace them with a single one-line summary chip.

#### Scenario: Successful turn collapses to a summary chip

- **WHEN** the SSE stream closes after a `final` event has been received
- **THEN** the trace state becomes `collapsed`
- **AND** all step rows are hidden
- **AND** a single summary chip is shown with the total duration and the number of tool calls executed

#### Scenario: Errored turn collapses with error styling

- **WHEN** the SSE stream closes after an `error` event without a successful `final`
- **THEN** the trace state becomes `collapsed`
- **AND** the summary chip uses the error visual treatment and indicates the turn errored

#### Scenario: Stream interruption still collapses

- **WHEN** the SSE stream reader closes without receiving either `final` or `error` (e.g., transport drop)
- **THEN** the trace state becomes `collapsed`
- **AND** the summary chip indicates an incomplete turn

### Requirement: User can re-expand a collapsed trace

After a trace has collapsed, the user SHALL be able to re-expand it by clicking the summary chip; expanding again SHALL show every step that was captured during streaming, including planning, tool calls with arguments, tool results with previews, and any error step.

#### Scenario: Click expands the chip

- **WHEN** the user clicks the collapsed summary chip
- **THEN** the trace state becomes `expanded`
- **AND** all originally captured step rows are visible again, in their original order
- **AND** clicking the chip a second time returns the trace to `collapsed`

#### Scenario: New turn does not affect prior turn's collapse state

- **WHEN** a new chat turn starts on the same session
- **THEN** the new assistant message's trace begins in `live` state
- **AND** prior assistant messages' traces remain in their previously chosen state (`collapsed` or `expanded`)

### Requirement: Trace bodies persist across page reloads via localStorage; saved views exclude them

Full step bodies (planning text, tool arguments, tool result previews) SHALL be persisted to localStorage under a dedicated key (`cognitrix:chat-trace:v1:{userId}`) so that the user can re-expand the trace after a page reload. Raw tool result payloads (potentially large query rows) are NOT persisted; only the pre-computed `resultPreview` string is stored. The persisted `ChatMessage` also carries a lightweight `traceSummary` (step count, total duration, terminal status) as a fallback for rendering the collapsed chip if the localStorage trace entry is missing.

#### Scenario: Reload preserves full trace and chip remains expandable

- **WHEN** the user reloads the page after a turn has completed
- **THEN** the assistant message still displays its collapsed summary chip
- **AND** clicking the chip expands to show the full step list (planning, tool calls with argument previews, result previews, any error steps)

#### Scenario: Saved views do not include trace bodies

- **WHEN** an assistant message is included in a saved view payload
- **THEN** the saved view contains the message text and chart spec but does not contain any trace step bodies or tool result payloads

### Requirement: Trace UI is visually restrained

The agent trace UI SHALL match the existing chat surface aesthetic: monochrome iconography (single accent color reserved for error steps only), no spinner or shimmer animation other than a single pulsing dot on the live step, monospace formatting limited to tool arguments and result previews, and a maximum vertical extent of 60% of the viewport while live (with internal scroll for longer traces).

#### Scenario: No spinner during streaming

- **WHEN** the trace is in `live` state with a running tool step
- **THEN** the only visible animation is a single pulsing dot on the most recent step row
- **AND** there is no spinner, shimmer, or skeleton block elsewhere in the trace

#### Scenario: Long trace is internally scrollable

- **WHEN** a live trace contains more steps than fit within 60% of the viewport
- **THEN** the trace block has its own vertical scroll
- **AND** the assistant message bubble layout below the trace remains pinned in place
