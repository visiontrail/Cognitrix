# Design: add-agent-canvas-mode

## Context

Charts reach the canvas today only through user clicks: `ChatPanel` archives `spec` SSE payloads as chart assets, and `chart-message-card.tsx` calls `addNode`/`addNodeToWebDesign` when the user clicks "add to canvas". Canvas state is client-owned: the Zustand `workspace-store` is the single source of truth, and the server persists it verbatim as an opaque JSON blob (`workspace_snapshots.payload`, last-writer-wins, 900 ms debounced autosave). All layout intelligence — `findSlot`, `compactLayout`, the 12-column fluid grid, per-format node buckets — lives in `apps/web/lib/workspace/web-design-layout.ts`.

The agent runtime (`agent_runtime.py`) already has the pieces a long-horizon mode needs: a resumable session store (`agent_sessions.sqlite3`), a confirmation state machine (`MultiChartPreflightPlanner` + `confirmation_required` SSE + validated confirm requests), server-side chart production (`MultiChartGenerationService._query_chart_rows` → rows → `ChartStrategyRouter` spec), a tool registration/whitelist pattern proven by the web-search tools, and SSE step pairing (`step_id`/`started_at`/`completed_at`).

Constraints:

- The model is DeepSeek via the Anthropic-compatible gateway — long-horizon planning quality is a known weakness; the design must minimize what the model is trusted to do per step.
- Existing Q&A limits (`AGENT_MAX_TOOL_STEPS=6`, `AGENT_TIMEOUT_SECONDS=25`) must not change.
- With `AGENT_CANVAS_MODE_ENABLED=false`, behavior must be byte-for-byte identical to today (the web-search flag is the precedent).

## Goals / Non-Goals

**Goals:**

- One user turn → approved outline → complete dashboard on a fresh web-design page, streamed block by block.
- The model never computes geometry; coordinates are always derived deterministically on the client.
- A run survives brief client disconnects: nothing already placed is ever lost.
- Per-chart failure isolation; user can stop anytime and keep partial results.
- Run-level undo in one action.

**Non-Goals:**

- Editing/iterating an existing canvas page (`read_canvas`, block mutation on user-authored content) — explicitly deferred; every run starts from a fresh page.
- Free-layout and fixed-size canvas formats (the wire contract carries the format; only `web-design` is implemented in v1).
- Concurrent user + agent editing of the same page (soft lock instead).
- Server-side canvas document / CRDT / multi-writer collaboration.
- Auto-publishing the result (`/p/{token}` flow remains a manual follow-up).

## Decisions

### D1. Canvas ops stream to the client; the client applies them to the existing store

The agent emits semantic operations (`canvas_op` SSE events). The client applies them to the Zustand store through the existing layout engine, and persistence continues through the existing autosave → `PUT /workspaces/{id}/canvas-snapshot` path.

- *Alternative — server writes `workspace_snapshots` directly*: rejected. The server does not understand the client-shaped blob; it would either duplicate the entire layout engine in Python or blind-write a blob that the client's debounced autosave then clobbers (last-writer-wins).
- *Alternative — server-side canvas document with op log/CRDT as source of truth*: rejected for v1. Correct long-term answer for multi-writer collaboration, but a rewrite of canvas ownership that nothing else currently needs.

### D2. The model decides structure; the layout engine decides geometry

Tool arguments accept only structure: section membership, order, and a `size_preset` enum (`kpi` 3×2, `half` 6×3, `wide` 12×3, `full` 12×4 grid units). The client computes coordinates with `findSlot`/`compactLayout` on the run's page. Because ops are strictly ordered (`seq`) and placement is a pure function of op order on an empty page, replaying the op log reproduces the identical layout.

- *Alternative — model emits x/y/w/h*: rejected; LLM geometry is unreliable (overlaps, unbalanced whitespace), doubly so on DeepSeek.

### D3. One chart = one atomic tool call (`place_chart` executes the query server-side)

`place_chart` args: `{section_id, title, chart_type, size_preset, query}` where `query` is a semantic-metric reference or read-only SQL. The tool executes through `secure_query_sql()` with existing row/scan caps, builds the spec via `ChartStrategyRouter`, persists a chart asset server-side via `WorkspaceStateStore.upsert_chart_asset` (scoped to the requesting user + workspace), appends the op to the log, and emits `spec` + `canvas_op` SSE. This mirrors `MultiChartGenerationService._query_chart_rows`.

Consequences: the model never echoes data rows back through its context (token-cheap, DeepSeek-friendly); failure isolation is exactly one tool call; retry = re-invoke with the same args; a chart exists server-side the moment its tool call succeeds, even if the client is gone.

- *Alternative — chart data flows through the model's final JSON answer (today's single-chart path)*: rejected for long runs; echoing rows across 10+ charts blows context and multiplies hallucination surface.

### D4. Tool surface and registration

Four tools, registered in `ToolCallingService` and whitelisted in `agent_guardrails` only when the run is an agent-mode run (same mechanism as the `WEB_SEARCH_ENABLED` tools):

| Tool | Effect |
|---|---|
| `add_section` | Appends a section header block; returns `section_id` |
| `add_text_block` | Appends a text block (title/subtitle/body style) to a section |
| `place_chart` | Atomic query → spec → asset → placement op (D3) |
| `finish_dashboard` | Declares the run complete with a summary; required terminal call |

The BI read tools (`list_tables`, `describe_table`, `sample_rows`, `get_metric_catalog`, `get_distinct_values`, `run_semantic_query`, `execute_readonly_sql`) remain available for exploration during the run. `save_view` and web tools follow their existing flags.

### D5. Server-side semantic shadow = the op log

New tables in `agent_sessions.sqlite3` (auto-created, no migration tooling needed):

- `agent_canvas_runs(run_id, conversation_id, workspace_id, user_id, page_id, canvas_format, status, outline_json, created_at, updated_at)` — `status ∈ {awaiting_approval, running, stopped, failed, completed}`.
- `agent_canvas_ops(run_id, seq, op_type, payload_json, created_at)` — append-only.

The shadow (what has been placed so far) is derived by reading the run's ops; it is injected into the model's context as a compact structural summary between steps and answers "what have I already done" without a `read_canvas` tool. `page_id` is generated server-side (`agent-<run_id>`) so op replay is idempotent — the client skips ops whose block ids already exist on the page.

### D6. Two-phase run with an approval gate (default on, per-request opt-out)

Phase 1 (outline): a short, budgeted SDK turn with read-only schema tools produces a JSON outline (sections, chart items with one-line descriptions + size presets, estimated count). The runtime emits `confirmation_required` with `confirmation_type: dashboard_outline` and a terminal `final` with `status: awaiting_confirmation` — the exact contract shape of the multi-chart confirmation. The user can deselect items or cancel; the confirm request is validated against the pending state (stale/oversized confirmations rejected).

Phase 2 (execution): on approval, the long run starts under agent-mode budgets.

The "skip approval" preference is stored client-side (localStorage, like locale) and sent as `auto_approve: true` on the request; the server still runs Phase 1 internally and proceeds without pausing. No new server-side user-settings store is introduced.

- *Alternative — server-persisted user setting*: rejected; there is no user-settings surface today and the preference is purely a UX choice with all safety enforced by server budgets regardless.

### D7. Run lifecycle survives disconnects; live stream is a tail of the op log

The execution task is shielded from SSE generator cancellation: every event is appended to the op log first, then pushed to the live queue. If the client disconnects mid-run, the run continues and keeps persisting ops and chart assets. On reload, the client asks `GET /chat/agent-runs/active?workspace_id=…` (plus `GET /chat/agent-runs/{run_id}/ops?after_seq=n`), replays missed ops onto the page, and — if the run is still `running` — re-attaches to a live SSE tail endpoint.

Stop: `POST /chat/agent-runs/{run_id}/stop` sets a cancel flag checked between tool calls; the run finalizes with `status: stopped` and everything placed is kept.

- *Alternative — cancel the run on disconnect*: rejected; it turns a reflexive F5 into losing a multi-minute task, the exact failure long-horizon mode exists to avoid.

### D8. Fresh page per run; undo = delete the page

The first op of every run is `create_page {page_id, title}`; the client creates a new web-design sidebar section/page and all subsequent ops target it. Existing pages are never touched, which is why v1 needs no canvas-read tool surface. "撤销本次生成" removes the page via the existing sidebar-item removal path (which already cascades page + zones).

### D9. Soft lock during a run

While a run is active for the visible workspace, the web-design editor disables drag/resize/edit interactions and shows a banner ("Agent 正在编排此页面") with a stop button. Chat remains usable. Lock state lives in `ui-store` keyed by the run, cleared on any terminal run status.

### D10. Budgets, flags, and enforcement

New settings (all parsed in `config.py`): `AGENT_CANVAS_MODE_ENABLED` (default `false`), `AGENT_MODE_MAX_STEPS` (default `40`), `AGENT_MODE_OUTLINE_MAX_STEPS` (default `16`, the planning turn's own `max_turns`), `AGENT_MODE_TIMEOUT_SECONDS` (default `600`), `AGENT_MODE_MAX_CHARTS` (default `12`). Guardrails enforce per-run caps: at most `AGENT_MODE_MAX_CHARTS` successful `place_chart` calls, a proportional cap on sections/text blocks, and the step/time budgets pass into `ClaudeAgentOptions.max_turns` / the run watchdog for agent-mode runs only. Existing Q&A limits are untouched.

### D11. RBAC and audit

Starting a run requires workspace **editor** role (the same bar as `PUT /canvas-snapshot`); the outline phase alone still requires editor since its purpose is canvas mutation. Audit events are metadata-only, consistent with the existing philosophy: `agent_run_start`, `agent_run_finish` (status, op count, chart count, duration), `agent_run_stop`, `agent_canvas_op` (type + duration only — never titles, SQL, or data).

### D12. Format gating at the contract level

The chat request carries `canvas_format` (the format the user's panel is on — the product principle is "operate the canvas the user is looking at"). v1 implements only `web-design`: any other format is rejected before Phase 1 with a typed error the UI preempts by offering a one-click switch to web-design. New formats later add an executor without changing the wire contract.

### D13. Agent dashboard chart types are a strict, executable catalog

The outline prompt and `place_chart.chart_type` schema expose the same fixed catalog of chart types that the agent-canvas spec builder can render faithfully. The planning prompt includes intent- and data-shape-based selection rules; execution must preserve the approved type. Every exposed type produces a complete ECharts option whose visual series matches that type, including after server hydration. Unsupported free-form strings are rejected rather than silently rendered as bars.

Chart diversity is not itself an optimization target: repeated bars are correct for repeated categorical comparisons. The invariant is that bars are selected only for categorical comparison/ranking, while KPI, time, composition, correlation, matrix, process, hierarchy, profile, target, signed-change, and detail intents use their corresponding chart families when the data shape supports them.

## Risks / Trade-offs

- **[DeepSeek drifts mid-run: wrong order, skipped `finish_dashboard`, malformed tool args]** → Approval gate pins the plan before execution; each chart is one atomic validated tool call; the between-step shadow summary re-grounds the model; watchdog finalizes the run as `failed`/partial if `finish_dashboard` never arrives; evals in `tests/evals/` cover outline quality and run protocol adherence.
- **[Client applies ops but closes the tab before debounced autosave persists the snapshot]** → Ops and chart assets are already server-persisted; on next load, replay reconciles the page by re-applying missed ops idempotently (deterministic block ids).
- **[User has multiple tabs open; a second tab's autosave clobbers blocks the first tab placed]** → Same-user overwrite is an existing platform property of blob autosave, not new to this change; the soft-lock banner renders in every tab with an active run, and replay-on-load reconverges a stale tab. Accepted for v1.
- **[Long-lived SSE connections killed by proxies during multi-minute runs]** → Periodic keepalive events on the stream; the reconnect/replay path (D7) makes any drop non-destructive.
- **[Runaway loops burning provider budget]** → Hard step/time/chart caps per run (D10) + user-visible stop; caps emit a typed terminal error so partial results are kept and labeled.
- **[Chart assets accumulate for abandoned runs]** → Assets are ordinary chart assets in the existing store, visible and deletable like any other; deleting the run's page removes their placements. Accepted; no GC in v1.
- **[Soft lock frustrates users who want to tweak while the agent works]** → Deliberate v1 trade-off; mixed editing is a multi-writer problem (Non-Goal). Stop-then-edit is always available and keeps partial results.

## Migration Plan

1. Ship dark: all backend + frontend code lands behind `AGENT_CANVAS_MODE_ENABLED=false`; new SQLite tables are created lazily on first use.
2. Enable in dev/Docker envs; run smoke (`tests/smoke`) extension: outline → approve → 3-chart run → page exists → undo deletes page.
3. Enable for production once evals on the DeepSeek gateway pass an agreed threshold.
4. Rollback = flip the flag off; runs in flight finalize, tables become inert, no data cleanup required.

## Open Questions

- Should `finish_dashboard` also propose a page title + one-paragraph summary text block automatically (nice for the social-publishing user), or leave summary text to explicit `add_text_block` calls in the outline? (Leaning: outline includes a summary text item by default; zero extra machinery.)
- Live re-attach SSE endpoint in v1, or poll-replay only until first user feedback? (Leaning: implement the tail endpoint — the op log makes it cheap, and reconnect UX is the feature's core promise.)
- Post-run CTA linking to the existing publish flow (`POST /workspaces/{id}/publish`) — v1 or fast-follow? (Leaning: fast-follow; zero coupling either way.)
