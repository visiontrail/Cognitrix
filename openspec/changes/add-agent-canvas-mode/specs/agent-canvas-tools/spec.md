# agent-canvas-tools Specification (delta)

## ADDED Requirements

### Requirement: Canvas tools are registered only for agent-mode runs
The tool surface `add_section`, `add_text_block`, `place_chart`, and `finish_dashboard` SHALL be registered through `ToolCallingService` and admitted by the guardrail whitelist only when the current turn is an agent-mode run under an enabled feature flag. The existing read-only BI tools remain available during a run for exploration.

#### Scenario: Canvas tools absent outside agent mode
- **WHEN** a normal Q&A turn executes with `AGENT_CANVAS_MODE_ENABLED=true`
- **THEN** the guardrail whitelist for that turn excludes all four canvas tools

#### Scenario: Canvas tools present during a run
- **WHEN** an approved agent-mode run is executing
- **THEN** the whitelist includes the four canvas tools plus the read-only BI tools

### Requirement: Tools accept structure only, never geometry
Canvas tool arguments SHALL be limited to structural fields: section membership, order, titles, text content/style, chart definition, and a `size_preset` drawn from a fixed enum (`kpi`, `half`, `wide`, `full`). Tool schemas MUST NOT accept coordinates, pixel sizes, or grid positions, and the backend MUST reject unknown size presets.

#### Scenario: Size preset validated
- **WHEN** a `place_chart` call arrives with a `size_preset` outside the enum
- **THEN** the tool call fails validation and no op is appended

#### Scenario: No geometry fields accepted
- **WHEN** a canvas tool call includes coordinate-like fields not in the schema
- **THEN** the call is rejected by argument validation

### Requirement: place_chart is one atomic chart production step
`place_chart` SHALL, in a single tool call: execute the referenced semantic metric or read-only SQL through `secure_query_sql()` with existing row/scan caps, build the chart spec via `ChartStrategyRouter`, persist a chart asset scoped to the requesting user and workspace, append a placement op to the run's op log, and emit the corresponding `spec` and `canvas_op` SSE events. Chart data rows MUST NOT be returned into the model context; the tool result carries only metadata (asset id, row count, duration).

#### Scenario: Successful placement is fully persisted
- **WHEN** a `place_chart` call succeeds
- **THEN** a chart asset exists in the workspace state store, an op with a monotonically increasing `seq` exists in the op log, and `spec` and `canvas_op` events are emitted

#### Scenario: Data stays out of model context
- **WHEN** a `place_chart` call succeeds
- **THEN** the tool result returned to the model contains no data rows

#### Scenario: Query failure yields error placeholder
- **WHEN** the query inside `place_chart` fails or violates SQL validation
- **THEN** the tool returns an error result, an error-placeholder op is appended, and no chart asset is persisted

### Requirement: Agent selects from a faithful chart catalog
The dashboard outline prompt and `place_chart.chart_type` schema SHALL expose one shared, fixed catalog with explicit analytical-intent and data-shape guidance. The agent MUST preserve the approved outline type during execution. Every exposed type MUST produce a complete chart option whose rendered visual family matches the selected type; unsupported values MUST be rejected and MUST NOT silently downgrade to a bar chart.

#### Scenario: Time trend uses a trend chart
- **WHEN** an outline item represents values over a time or ordered-sequence dimension
- **THEN** the planning guidance directs the agent to `line` or, for cumulative volume, `area`, rather than a categorical `bar`

#### Scenario: Selected type matches rendered series
- **WHEN** `place_chart` succeeds with any chart type in the exposed catalog
- **THEN** the persisted chart asset and streamed spec retain that chart type and contain a complete option for the same visual family

#### Scenario: Unsupported type is rejected
- **WHEN** `place_chart` receives a chart type outside the exposed catalog
- **THEN** validation fails before query execution, no chart asset or canvas op is persisted, and no bar fallback is generated

### Requirement: finish_dashboard is the required terminal call
The run protocol SHALL require the model to call `finish_dashboard` with a completion summary to end a run as `completed`. If the model stops without calling it, or budgets expire, a watchdog MUST finalize the run with a partial/failed status so no run remains `running` indefinitely.

#### Scenario: Normal completion
- **WHEN** the model calls `finish_dashboard` after placing items
- **THEN** the run status becomes `completed` and the terminal `final` event carries the summary and per-item outcomes

#### Scenario: Watchdog finalization
- **WHEN** the model ends its turn without calling `finish_dashboard`
- **THEN** the watchdog finalizes the run with a partial status and emits a terminal event

### Requirement: Server maintains a semantic shadow via an append-only op log
Every canvas mutation SHALL be recorded as an append-only op (`agent_canvas_ops`: run id, monotonic seq, op type, payload) with run metadata in `agent_canvas_runs`, both stored in `agent_sessions.sqlite3`. Between execution steps, the runtime SHALL inject a compact structural summary of ops so far into the model context. The op log is the source for disconnect replay; tables are created lazily and their absence when the flag is off has no effect.

#### Scenario: Ops are strictly ordered
- **WHEN** multiple canvas tool calls succeed within one run
- **THEN** their ops carry strictly increasing `seq` values with no gaps caused by concurrent writes

#### Scenario: Shadow summary reflects prior ops
- **WHEN** an execution step begins after previous placements
- **THEN** the model context includes a structural summary listing existing sections and placed items of the current run

### Requirement: Per-run op budgets are enforced
The guardrail layer SHALL enforce per-run caps: successful `place_chart` calls up to `AGENT_MODE_MAX_CHARTS`, and a proportional cap on section/text ops. Exceeding a cap fails the tool call with a typed error and the run finalizes as partial.

#### Scenario: Chart cap enforced
- **WHEN** a run attempts a `place_chart` beyond `AGENT_MODE_MAX_CHARTS`
- **THEN** the call is rejected with a typed budget error and previously placed charts are unaffected

### Requirement: Canvas tool activity emits metadata-only audit events
The audit logger SHALL record `agent_run_start`, `agent_run_finish`, `agent_run_stop`, and per-op `agent_canvas_op` events containing only metadata (op type, counts, durations, status). Audit payloads MUST NOT contain chart titles, SQL text, text-block content, or data values.

#### Scenario: Run lifecycle audited
- **WHEN** a run starts and later finalizes
- **THEN** `agent_run_start` and `agent_run_finish` audit events exist with status, op count, chart count, and duration

#### Scenario: No content in audit payloads
- **WHEN** any agent-canvas audit event is written
- **THEN** its payload contains no SQL, titles, body text, or row data
