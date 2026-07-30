# agent-canvas-mode Specification (delta)

## ADDED Requirements

### Requirement: Agent mode is an explicit, flag-gated chat entry point
The chat composer SHALL expose an Agent-mode toggle only when the backend reports `AGENT_CANVAS_MODE_ENABLED=true`. When the toggle is active, the chat request SHALL carry `agent_mode: true` and the active canvas format. When the feature flag is off, no agent-mode tools are registered, no agent-mode SSE event types are emitted, and existing chat behavior is unchanged.

#### Scenario: Toggle hidden when flag is off
- **WHEN** the backend is running with `AGENT_CANVAS_MODE_ENABLED=false`
- **THEN** the chat composer renders no Agent-mode toggle and chat requests never include `agent_mode`

#### Scenario: Agent-mode request is marked
- **WHEN** the user enables the Agent-mode toggle and sends a message
- **THEN** the `POST /chat/stream` body includes `agent_mode: true` and the `canvas_format` of the currently visible canvas

#### Scenario: Flag off leaves existing behavior unchanged
- **WHEN** `AGENT_CANVAS_MODE_ENABLED=false`
- **THEN** the guardrail tool whitelist excludes all canvas tools and the system prompt contains no agent-mode instructions

### Requirement: Unsupported canvas formats are rejected before planning
Agent mode v1 SHALL operate only on the `web-design` canvas format. When the request carries any other format, the backend MUST reject the turn with a typed error before the outline phase starts, and the UI SHALL offer a one-click switch to the web-design format before sending.

#### Scenario: Non-web-design format rejected
- **WHEN** an agent-mode request arrives with `canvas_format` other than `web-design`
- **THEN** the backend emits an `error` SSE event with a stable error code and performs no planning, no tool calls, and no run creation

#### Scenario: UI preempts the rejection
- **WHEN** the user enables Agent mode while the workspace panel is on a non-web-design canvas
- **THEN** the composer surfaces a prompt to switch to the web-design canvas before the message can be sent in Agent mode

### Requirement: Dashboard outline approval gates execution by default
An agent-mode turn SHALL first produce a dashboard outline (ordered sections, chart items with one-line descriptions and size presets, estimated chart count) and MUST pause for user approval before any canvas mutation. The pause reuses the confirmation contract: a `confirmation_required` SSE event with `confirmation_type: dashboard_outline` and a terminal `final` event with `status: awaiting_confirmation`. The user can approve, deselect individual chart items, or cancel. The backend MUST validate the confirmation against the pending run state and reject stale or oversized confirmations.

#### Scenario: Outline pauses for approval
- **WHEN** an agent-mode turn completes its outline phase
- **THEN** the runtime emits `confirmation_required` with `confirmation_type: dashboard_outline`, a stable `confirmation_id`, the outline payload, and a terminal `final` with `status: awaiting_confirmation`, and no `canvas_op` event has been emitted

#### Scenario: Approval starts execution
- **WHEN** the user approves the outline with a matching `confirmation_id`
- **THEN** the run transitions to `running` and execution begins for exactly the approved items

#### Scenario: Deselected items are skipped
- **WHEN** the user approves the outline with a subset of chart items selected
- **THEN** only the selected items are executed

#### Scenario: Cancel discards the run
- **WHEN** the user cancels the outline confirmation
- **THEN** the run finalizes without any canvas mutation and the pending confirmation state is cleared

#### Scenario: Stale confirmation rejected
- **WHEN** a confirmation arrives whose `confirmation_id` does not match the pending run
- **THEN** the backend rejects it and no execution starts

### Requirement: Approval can be skipped per user preference
The client SHALL offer a user preference to skip the approval pause. The preference is stored client-side and transmitted as `auto_approve: true` on the agent-mode request. The backend still produces the outline internally and proceeds directly to execution. Server-side budgets apply regardless of this preference.

#### Scenario: Auto-approve proceeds without pausing
- **WHEN** an agent-mode request carries `auto_approve: true`
- **THEN** the runtime emits the outline as an informational event and begins execution without an `awaiting_confirmation` pause

#### Scenario: Budgets apply despite auto-approve
- **WHEN** a run started with `auto_approve: true` reaches a step, time, or chart budget
- **THEN** the budget is enforced exactly as it would be for an approved run

### Requirement: Agent-mode runs use dedicated budgets
Agent-mode runs SHALL be governed by `AGENT_MODE_MAX_STEPS`, `AGENT_MODE_OUTLINE_MAX_STEPS`, `AGENT_MODE_TIMEOUT_SECONDS`, and `AGENT_MODE_MAX_CHARTS`, independent of the existing Q&A limits. Every one of them MUST be operator-tunable through the same configuration surfaces as other settings (env plus the admin control plane), never hard-coded. Exceeding any budget MUST finalize the run as partial with a typed terminal status, keeping everything already placed.

#### Scenario: Q&A limits untouched
- **WHEN** a non-agent-mode chat turn runs
- **THEN** it is governed by the existing `AGENT_MAX_TOOL_STEPS` and `AGENT_TIMEOUT_SECONDS` values only

#### Scenario: Outline phase exhausts its step budget
- **WHEN** the planning turn reaches `AGENT_MODE_OUTLINE_MAX_STEPS` before emitting outline JSON
- **THEN** the turn fails with code `AGENT_CANVAS_OUTLINE_BUDGET_EXCEEDED`, a message naming the budget, and a log line distinct from a provider rejection — not the generic "rephrase and retry" message

#### Scenario: Budget exhaustion keeps partial results
- **WHEN** a running agent-mode run exceeds `AGENT_MODE_TIMEOUT_SECONDS`
- **THEN** the run finalizes with a typed partial status and all previously placed blocks remain on the page

### Requirement: Runs can be stopped anytime and keep partial results
The user SHALL be able to stop an active run. Stopping sets a cancel flag honored between tool calls; the run finalizes with `status: stopped`, all placed content is kept, and the canvas soft lock is released.

#### Scenario: Stop mid-run
- **WHEN** the user stops a run after some charts have been placed
- **THEN** no further tool calls execute, the run finalizes as `stopped`, and the placed blocks remain on the page

### Requirement: Per-chart failures do not abort the run
A failed chart item SHALL NOT terminate the run. The failure is recorded on the op log as an error-placeholder op, the run continues with the next item, and the terminal summary reports per-item outcomes.

#### Scenario: One chart fails, run continues
- **WHEN** a `place_chart` execution fails for one outline item
- **THEN** an error-placeholder op is appended for that item and execution proceeds to the next item

#### Scenario: Terminal summary reports outcomes
- **WHEN** a run finalizes
- **THEN** the terminal payload includes counts of placed, failed, and skipped items

### Requirement: Starting a run requires workspace editor role
Because an agent-mode run mutates the workspace canvas, the backend MUST require the requesting user to hold at least the `editor` role on the target workspace before the outline phase begins.

#### Scenario: Non-editor rejected
- **WHEN** a user without editor role on the workspace sends an agent-mode request
- **THEN** the backend rejects the turn with an authorization error and creates no run
