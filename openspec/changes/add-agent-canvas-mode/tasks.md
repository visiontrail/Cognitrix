# Tasks: add-agent-canvas-mode

## 1. Config, flags, and storage foundations

- [x] 1.1 Add `AGENT_CANVAS_MODE_ENABLED` (default `false`), `AGENT_MODE_MAX_STEPS` (40), `AGENT_MODE_TIMEOUT_SECONDS` (600), `AGENT_MODE_MAX_CHARTS` (12) to `config.py` with validators, and document them in `apps/api/.env.example` and CLAUDE.md
- [x] 1.2 Create `agent_canvas_runs` and `agent_canvas_ops` tables (lazy schema init) in `agent_sessions.sqlite3` with a store class exposing create-run, update-status, append-op (monotonic seq under a lock), list-ops-after-seq, and get-active-run
- [x] 1.3 Unit tests: store CRUD, seq monotonicity under concurrent appends, lazy table creation, flag-off inertness

## 2. Canvas tool surface (backend)

- [x] 2.1 Define tool schemas for `add_section`, `add_text_block`, `place_chart`, `finish_dashboard` (structure-only args, `size_preset` enum validation, no geometry fields) and register them in `ToolCallingService` behind the flag + agent-mode run context
- [x] 2.2 Implement `place_chart` as the atomic step: query via `secure_query_sql()` (metric or read-only SQL), spec via `ChartStrategyRouter`, chart-asset persistence via `WorkspaceStateStore.upsert_chart_asset`, op append, `spec` + `canvas_op` emission; tool result carries metadata only (no rows)
- [x] 2.3 Implement `add_section` / `add_text_block` (op append + emission) and `finish_dashboard` (terminal summary, run status transition)
- [x] 2.4 Extend `agent_guardrails`: admit canvas tools only for agent-mode runs; enforce per-run caps (`AGENT_MODE_MAX_CHARTS`, proportional section/text caps) with typed budget errors
- [x] 2.5 Audit events `agent_run_start` / `agent_run_finish` / `agent_run_stop` / `agent_canvas_op`, metadata-only payloads
- [x] 2.6 Unit tests: schema validation (bad presets, geometry-field rejection), place_chart failure → error-placeholder op, budget enforcement, audit payload contains no content; security tests: SQL validation path unchanged, non-editor rejection

## 3. Agent-mode runtime (backend)

- [x] 3.1 Route selection: `agent_mode: true` + `canvas_format` on `POST /chat/stream`; reject non-`web-design` formats with a typed error before planning; require workspace editor role at run start
- [x] 3.2 Outline phase: budgeted planning turn with read-only tools producing the outline JSON; emit `confirmation_required` (`confirmation_type: dashboard_outline`) + `final` `awaiting_confirmation`, persisting pending state on the run record (reuse the multi-chart confirmation state-machine pattern)
- [x] 3.3 Confirmation handling: validate `confirmation_id`, honor deselected items, reject stale/oversized confirmations; `auto_approve: true` path skips the pause but still records the outline
- [x] 3.4 Execution phase: SDK loop under agent-mode budgets (`max_turns`, watchdog timeout), first op `create_page` (`agent-<run_id>`), between-step semantic-shadow summary injected into context, per-item failure isolation, watchdog finalization when `finish_dashboard` never arrives
- [x] 3.5 Agent-mode system prompt section in `agent_prompting.py`: outline JSON schema, run protocol (sections → charts → finish), size-preset semantics, DeepSeek-friendly explicit phrasing
- [x] 3.6 Run detachment and control: shielded execution task (ops logged before live push), SSE keepalives, `POST /chat/agent-runs/{run_id}/stop`, `GET /chat/agent-runs/active`, `GET /chat/agent-runs/{run_id}/ops?after_seq=n`, live tail SSE endpoint for re-attach
- [x] 3.7 Integration tests over a fake provider: full outline → approve → multi-chart run → completed; stop mid-run; disconnect mid-run keeps appending ops; budget exhaustion → partial status; API tests for the new endpoints and SSE contract (`canvas_op` payload shape, seq ordering)

## 4. Frontend: mode entry and approval

- [x] 4.1 Agent-mode toggle in the chat composer (visible only when the backend reports the flag; follow the web-search toggle precedent), sending `agent_mode` + `canvas_format`; prompt a one-click switch when the active canvas is not web-design
- [x] 4.2 Outline approval card (reuse the multi-chart confirmation UI pattern): sections + chart items with deselection, approve/cancel, count display; "skip approval" preference persisted in localStorage and sent as `auto_approve`
- [x] 4.3 i18n dictionary entries for all new UI strings (zh/en)
- [x] 4.4 Vitest: toggle gating, format-switch prompt, approval card select/approve/cancel, auto-approve preference

## 5. Frontend: op application and run UX

- [x] 5.1 `canvas_op` SSE handling in the chat stream consumer; op dispatcher with deterministic block ids and idempotent skip of already-applied ops
- [x] 5.2 Workspace-store actions: create run page (sidebar section with server-provided id), apply section/text/chart/error-placeholder ops via `findSlot`/preset→grid-span mapping in strict seq order, mark dirty for autosave
- [x] 5.3 Soft lock: run-active flag in `ui-store`, disable web-design drag/resize/edit while running, banner with stop button wired to the stop endpoint, lock cleared on all terminal statuses
- [x] 5.4 Error placeholder block component with retry (re-executes the single item; success replaces the placeholder in place)
- [x] 5.5 Reconnect/replay: on load, query active/latest run, replay ops after last applied seq onto the run page, re-attach to live tail when still running
- [x] 5.6 Run-level undo ("撤销本次生成"): delete the run's page via the existing sidebar-item removal cascade; assets remain in the library
- [x] 5.7 Vitest: op application determinism (same ops → same layout), idempotent replay, soft-lock behavior, undo removes only the run page; Playwright e2e: happy-path run on the web-design canvas

## 6. Quality gates and rollout

- [x] 6.1 Evals in `tests/evals/`: outline quality and run-protocol adherence on the DeepSeek gateway (finish_dashboard called, no invalid tool args, sensible section/chart structure)
- [x] 6.2 Smoke-flow extension: enable flag → outline → approve → 3-chart run → page exists in snapshot → undo deletes page
- [x] 6.3 Verify flag-off byte-for-byte neutrality: no tools registered, no new SSE types, no prompt changes (regression test)
- [x] 6.4 `make test-all` green; update CLAUDE.md architecture notes (SSE event list, tool count, storage layout)
- [x] 6.5 Fix agent-dashboard chart selection: shared executable chart catalog, semantic selection guidance, faithful non-bar options, persisted asset parity, regression tests, and Browser verification
