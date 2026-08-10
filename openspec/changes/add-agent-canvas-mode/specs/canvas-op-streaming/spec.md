# canvas-op-streaming Specification (delta)

## ADDED Requirements

### Requirement: canvas_op is a new SSE event type with a stable contract
Agent-mode runs SHALL emit `canvas_op` SSE events alongside the existing event types. Every `canvas_op` payload carries `run_id`, `canvas_format`, `seq`, `op_type` (`create_page`, `add_section`, `add_text_block`, `place_chart`, `error_placeholder`), an op-type-specific payload, and deterministic block ids derived from `run_id` + `seq`. Consumers that do not understand `canvas_op` are unaffected because the event type is additive.

#### Scenario: Ops stream during execution
- **WHEN** an approved run places its first chart
- **THEN** the client receives a `canvas_op` event with `op_type: place_chart`, the run's `run_id`, a `seq` greater than that of the `create_page` op, and the referenced chart asset id

#### Scenario: Event type is additive
- **WHEN** a non-agent-mode turn streams
- **THEN** no `canvas_op` events are emitted and all existing event types behave as before

### Requirement: Every run begins by creating a fresh page or isolated region
The first op of every run SHALL be `create_page` with a server-generated `page_id` (`agent-<run_id>`), canvas format, and title. The client creates a web-design sidebar page, an isolated infinite-canvas region, or a fresh bounded physical page as appropriate. Pre-existing content MUST never be modified by a run.

#### Scenario: New target created on run start
- **WHEN** the client receives the run's `create_page` op
- **THEN** a new target with the server-provided page id appears in the recorded canvas format

#### Scenario: Existing content untouched
- **WHEN** a run executes on a workspace whose target canvas already has content
- **THEN** no page, node, zone, text zone, or sidebar item outside the run target is modified or removed

### Requirement: The client computes all geometry deterministically
On receiving ops, the client SHALL derive block coordinates using the format-specific deterministic layout engine in strict `seq` order, mapping each `size_preset` to a grid span or pixel footprint. Given the same op sequence and starting snapshot, the resulting layout MUST be identical across sessions and reloads. Bounded formats MUST add physical pages rather than place nodes outside page boundaries.

#### Scenario: Preset maps to grid span
- **WHEN** a `place_chart` op with `size_preset: kpi` is applied
- **THEN** the block occupies the preset's fixed grid span at the next available slot computed by the layout engine

#### Scenario: Replay reproduces layout
- **WHEN** the same op sequence is replayed onto a fresh page after a reload
- **THEN** every block occupies the same grid position as in the original live application

### Requirement: Op application is idempotent
Block ids are deterministic, and the client MUST skip any op whose block id already exists on the run's page, so that overlapping live delivery and replay never duplicate blocks.

#### Scenario: Duplicate op skipped
- **WHEN** the client receives an op whose block id is already present on the page
- **THEN** the op is ignored and the page state is unchanged

### Requirement: Runs survive client disconnects and support replay
The run execution task SHALL be shielded from SSE consumer cancellation: ops are appended to the op log before being pushed to the live stream, and chart assets are persisted server-side at tool time. The backend SHALL expose endpoints to query the active/latest run for a workspace conversation and to fetch ops after a given `seq`. On reload, the client detects an interrupted or ongoing run, replays missed ops onto the page, and re-attaches to a live tail for a still-running run.

#### Scenario: Disconnect does not kill the run
- **WHEN** the client disconnects while a run is executing
- **THEN** the run continues, subsequent ops are appended to the op log, and chart assets continue to be persisted

#### Scenario: Reload replays missed ops
- **WHEN** the user reloads the page while a run is `running`
- **THEN** the client fetches ops after its last applied `seq`, applies them idempotently, and resumes receiving live ops

### Requirement: Error placeholders are visible and retryable
A failed chart item SHALL appear on the run's page as an error placeholder block identifying the failed item, with a retry affordance. Retry re-executes only that item; success replaces the placeholder with the chart block in place.

#### Scenario: Placeholder rendered on failure
- **WHEN** the client receives an `error_placeholder` op
- **THEN** an error block for that item renders at the position the chart would have occupied

#### Scenario: Retry replaces placeholder
- **WHEN** the user retries a failed item and the retry succeeds
- **THEN** the placeholder is replaced by the chart block without moving other blocks

### Requirement: The canvas is soft-locked during an active run
While a run is active for the visible workspace, the target canvas-format editor SHALL disable user drag, resize, and edit interactions and display a run banner with a stop control. Chat remains fully usable. The lock MUST clear on every terminal run status.

#### Scenario: Editing disabled during run
- **WHEN** a run is `running` on the visible workspace
- **THEN** block drag/resize/edit interactions on the target canvas format are disabled and a banner with a stop button is shown

#### Scenario: Lock released on completion
- **WHEN** the run reaches any terminal status (`completed`, `stopped`, `failed`, partial)
- **THEN** the soft lock clears and normal editing is restored

### Requirement: A run can be undone without touching other content
The UI SHALL offer a run-level undo that removes the run's web page cascade or all provenance-matching React Flow nodes. Undo affects only the run target; chart assets remain in the asset library.

#### Scenario: Undo removes only the run target
- **WHEN** the user invokes undo for a completed run
- **THEN** the run's page or generated nodes are removed, other content is unchanged, and the run's chart assets remain available in the asset library

### Requirement: Persistence continues through the existing snapshot path
Applied ops mark the workspace dirty and are persisted by the existing debounced canvas-snapshot autosave. The server MUST NOT write the canvas snapshot directly during a run; reconciliation after missed autosaves happens through idempotent op replay on load.

#### Scenario: Autosave persists agent placements
- **WHEN** ops are applied and the autosave debounce fires
- **THEN** the saved snapshot contains the run's page and blocks

#### Scenario: Server never writes the snapshot
- **WHEN** a run executes with no connected client
- **THEN** `workspace_snapshots` is not modified by the server, and the page is reconstructed by op replay on the next client load
