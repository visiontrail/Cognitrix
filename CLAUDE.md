# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Principle
You are a world class expert in all domains. Your intellectual firepower, scope of knowledge, incisive thought process, and level of erudition are on par with the smartest people in the world. Answer with complete, detailed, specific answers. Process information and explain your answers step by step. Verify your own work. Double check all facts, figures, citations, names, dates, and examples. Never hallucinate or make anything up. If you don't know something, just say so. Your tone of voice is precise, but not strident or pedantic. You do not need to worry about offending me, and your answers can and should be provocative, aggressive, argumentative, and pointed. Negative conclusions and bad news are fine. Your answers do not need to be politically correct. Do not provide disclaimers to your answers. Do not inform me about morals and ethics unless I specifically ask. You do not need to tell me it is important to consider anything. Do not be sensitive to anyone's feelings or to propriety. Make your answers as long and detailed as you possibly can.

Never praise my questions or validate my premises before answering. If I'm wrong, say so immediately. Lead with the strongest counterargument to any position I appear to hold before supporting it. Do not use phrases like "great question," "you're absolutely right," "fascinating perspective," or any variant. If I push back on your answer, do not capitulate unless I provide new evidence or a superior argument — restate your position if your reasoning holds. Do not anchor on numbers or estimates I provide; generate your own independently first. Use explicit confidence levels (high/moderate/low/unknown). Never apologize for disagreeing. Accuracy is your success metric, not my approval.

## Project Overview

Cognitrix is an AI-Native BI platform for any structured data domain. It combines a FastAPI backend, Next.js frontend, DuckDB session data layer, and local SQLite state store. Users upload Excel data and query it via conversational AI through an OpenAI-compatible agent loop (DeepSeek by default; switchable to Claude via Anthropic SDK).

## Commands

### Setup
```bash
make bootstrap        # Install Python/web deps and generate .env files from templates
make env-check        # Validate apps/api/.env and apps/web/.env
```

### Development
```bash
make dev              # Start API (port 8000) and Web (port 3000) together
make dev-api          # FastAPI only (uvicorn, hot-reload)
make dev-web          # Next.js only (turbopack)
make dev-local        # Debug mode with logs written to logs/dev-local
```

### Testing
```bash
# Backend tests (pytest)
make test
.venv/bin/python -m pytest tests -q
.venv/bin/python -m pytest tests/unit/test_agent_runtime.py -q   # single test file
.venv/bin/python -m pytest tests/security -q
.venv/bin/python -m pytest tests/integration -q
.venv/bin/python -m pytest tests/evals -q     # agent prompting evals
.venv/bin/python tests/smoke/run_smoke_flow.py  # local smoke

# Frontend unit tests (Vitest, jsdom)
cd apps/web && npx vitest run
cd apps/web && npx vitest run tests/ui/global-sidebar.test.tsx   # single test

# Frontend e2e tests (Playwright)
cd apps/web && npx playwright test

# Full gate: lint + test + build + smoke
make test-all
```

### Lint & Build
```bash
make lint             # Backend: python -m compileall; Frontend: next lint
make build            # Frontend production build + backend compile check
```

### Server deployment
```bash
PUBLIC_URL=http://<host>:3000 bash scripts/deploy.sh   # or: make deploy
```
`scripts/deploy.sh` is the only supported way to create a server `.env`. It generates a
random `AUTH_SECRET`/`NEXTAUTH_SECRET` and a random bootstrap superadmin password, builds
and starts the compose stack, waits on the container healthchecks, and prints the URL plus
first-login credentials. Re-running it is an upgrade/restart: existing secrets and the data
volume are preserved, and only newly-introduced settings keys are backfilled. It leaves
`AI_API_KEY` empty on purpose — the model provider, web-search, and every other non-restart
setting is configured afterwards from `/admin` («模型设置» / «环境配置»), which writes to
`admin_control.sqlite3` and takes effect immediately via `_clear_runtime_caches()`. Operator
documentation lives in `deploy/README.md`.

Two facts that make the deploy-then-configure flow work, and that break it if changed:
the browser only ever calls the same-origin path `/api/backend` (`apps/web/lib/api-base.ts`
is a constant), so no deployment URL is baked into the web image at build time; and
`_bootstrap_admin()` creates the first account **only while the `users` table holds no
password account at all** — a later boot can promote an existing user but never create one.

Because of that one-shot window, bootstrapping needs no configuration at all:
`AUTH_BOOTSTRAP_ADMIN_EMAIL` defaults to `admin@cognitrix.local`, and an empty
`AUTH_BOOTSTRAP_ADMIN_PASSWORD` makes `_bootstrap_admin()` generate one and log it in a
banner (`grep -A6 "BOOTSTRAP ADMIN"`) exactly once, at creation. `_bootstrap_superadmin()`
then promotes that account so `/admin/control` is reachable. Setting the password
configures it explicitly (nothing is generated or logged); setting the *email* empty opts
out of bootstrapping entirely. There is deliberately no hardcoded default password: it
would be public to everyone who can read this repository.

### Kubernetes
`scripts/deploy.sh` is compose-only. For an orchestrator the image itself carries
`APP_ENV=production`, `UPLOAD_DIR` and `DATABASE_URL` (image `ENV`, not code defaults —
`UPLOAD_DIR` resolves relative paths against `apps/api/`, so a manifest that mounts a
volume but omits the variable would silently write outside it), and `MODEL_PROVIDER_URL`
/ `LOG_LEVEL` fall back to code defaults. That leaves **`AUTH_SECRET` as the only variable
a manifest must inject**. The data layer is DuckDB + SQLite on local files, so a
deployment must be `replicas: 1` with `strategy: Recreate` and an RWO PVC at
`/app/data/uploads`; anything else corrupts data silently. See `deploy/README.md`.

`scripts/lib/docker.sh:ensure_env_file()` deliberately refuses to synthesize a `.env` from
`.env.example`: the template ships no secrets, and an empty `AUTH_SECRET` still signs
structurally valid JWTs, so a copied template would fail open. `Settings` rejects an empty
or repository-known `AUTH_SECRET` whenever `APP_ENV=production` (`PUBLIC_PLACEHOLDER_SECRETS`
in `config.py`; keep it in sync with `PUBLIC_SECRETS` in `scripts/deploy.sh`).

### Smoke & Docker
```bash
make smoke-local      # End-to-end: healthz → login → upload → query → chat → save → share
make docker-up        # Build and start Docker Compose stack
make docker-down      # Stop Docker Compose
make smoke-docker     # Smoke flow against the Docker stack
make reset-local-data # Clear uploads, DuckDB/SQLite state, logs, test artifacts
```

## Architecture

### Backend (`apps/api/`)

FastAPI app defined in `main.py`. All routes (except `/healthz` and `/auth/login`) require `Authorization: Bearer <token>`.

**Key modules:**
- `config.py` — `Settings` (Pydantic BaseSettings); all env vars parsed and validated here; use `get_settings()` everywhere
- `auth.py` — JWT-based token issuance, `AuthIdentity`, RBAC permission scopes (`require_permission`), role overrides stored in-process
- `security.py` — `SQLReadOnlyValidator`, `RLSInjector`, `AccessContext`; combined through `secure_query_sql()`
- `data_policy.py` — `redact_rows()`, `redact_structure()`, `forbidden_sensitive_columns()` based on role
- `agent_prompting.py` — `build_agent_system_prompt()`; owns the static BI system prompt injected into every chat turn
- `agent_runtime.py` — ReAct agent loop built on the Claude Agent SDK (`ClaudeSDKClient` + `ClaudeAgentOptions`); orchestrates BI tool dispatch and maps SDK events to SSE format. Anthropic Messages API is the wire protocol; the underlying model is whatever `ANTHROPIC_BASE_URL` / `ANTHROPIC_DEFAULT_HAIKU_MODEL` point at (DeepSeek's `/anthropic` gateway by default).
- `chart_query_agent.py` — `ClaudeSDKClient`-backed agent that produces chart specs for follow-up chart queries
- `agent_logging.py` — `format_agent_debug_blocks()`; structured debug log formatter for AI input/output/tool traces
- `chat.py` — `ChatStreamService` routes `POST /chat/stream` into `AgentRuntime.run_turn()`; handles SSE streaming
- `agent_guardrails.py` — blocks jailbreak attempts, validates tool names and SQL before execution; owns the per-run agent-canvas budgets (`enforce_canvas_chart_budget`/`enforce_canvas_block_budget`) and the agent-mode tool whitelist (`agent_mode_allowed_tools` — base read-only tools + canvas tools, only when `AGENT_CANVAS_MODE_ENABLED=true`)
- `tool_calling.py` — `ToolCallingService`; executes the 8 BI tools (list_tables, describe_table, sample_rows, get_metric_catalog, run_semantic_query, execute_readonly_sql, get_distinct_values, save_view). When `WEB_SEARCH_ENABLED=true`, also exposes 3 web-research tools (`web_search`, `web_fetch`, `save_web_research`); each emits a metadata-only audit event (domain/count/rows/duration — never page body or full query). When `AGENT_CANVAS_MODE_ENABLED=true`, also hosts the 5 agent-canvas tools (`add_page`, `add_section`, `add_text_block`, `place_chart`, `finish_dashboard`) — callable only during an agent-mode run (the runtime injects a `_agent_run` context; without it every call is rejected). `place_chart` is one atomic step: query via `secure_query_sql()`, spec via `ChartStrategyRouter`, chart-asset persistence, op-log append; its result returns metadata only (never data rows), and a failed item becomes a retryable `error_placeholder` op instead of aborting the run
- `agent_canvas.py` — agent-canvas-run persistence: `AgentCanvasRunStore` (tables `agent_canvas_runs` + append-only `agent_canvas_ops` with monotonic per-run `seq`, created lazily in `agent_sessions.sqlite3`), canvas tool schemas, structure-only argument validation (`size_preset` enum, `level` ∈ {1,2}, geometry fields rejected), deterministic block ids (`agent-block-<run_id>-<seq>`) and page ids (`agent-<run_id>` for the run root, `agent-<run_id>-p<seq>` for every page opened by `add_page`)
- `agent_canvas_mode.py` — `AgentCanvasModeService`; two-phase agent-canvas runs: outline planning turn (read-only tools → outline JSON → `confirmation_required` with `confirmation_type: dashboard_outline`, or `auto_approve`) then a **detached** execution task under agent-mode budgets (first op `create_page` for the run root page, per-item failure isolation, semantic-shadow progress injected into each tool result, watchdog finalization when `finish_dashboard` never arrives). Ops are persisted before any live push, so disconnects never lose placed content; run control endpoints: `GET /chat/agent-runs/active`, `GET /chat/agent-runs/{id}/ops`, `GET /chat/agent-runs/{id}/tail` (SSE re-attach), `POST /chat/agent-runs/{id}/stop`, `POST /chat/agent-runs/{id}/retry`
- `web_research.py` — search-provider abstraction (`SearchProvider` protocol; `BochaSearchProvider`/`TavilySearchProvider` chosen by `WEB_SEARCH_PROVIDER`), SSRF-hardened `fetch_page()` (https-only, DNS-resolved IPs rejected for private/loopback/link-local/metadata ranges, per-hop redirect re-validation ≤3 hops, size/char caps), and trafilatura body extraction. The single outbound-HTTP surface for the agent
- `chart_strategy.py` — `ChartStrategyRouter`; routes chart rendering to ECharts or Recharts based on chart type and complexity score
- `semantic.py` — metric registry, `IntentParser`, `MetricCompiler`; semantic layer lives in `models/` YAML files
- `schema_inference.py` — LLM-powered inference for arbitrary Excel uploads; maps Chinese/unknown column headers to canonical snake_case names and infers metric definitions
- `session_titles.py` — `SessionTitleService`; calls the LLM to generate a short title for a new chat session
- `datasets.py` — DuckDB session manager, per-user/project connection isolation
- `table_catalog.py` — `TableCatalogRouter`; SQLite-backed catalog of uploaded tables with business type, write mode, and time-grain metadata; router at `/table-catalog`
- `views.py` — SQLite-backed view persistence with versioning and rollback
- `saved_prompts.py` — user-owned saved prompt library; `SavedPromptStore` (SQLite at `${UPLOAD_DIR}/state/saved_prompts.sqlite3`), `{variable}` template parser, capability-hint allowlist, and router at `/saved-prompts` gated by `prompts:read` / `prompts:write`. Every query is owner-filtered by `identity.user_id`; lifecycle/use audit events are metadata-only (never the prompt name or body)
- `workspaces.py` — workspace RBAC enforcement; router mounted at `/workspaces`
- `agentic_ingestion/` — isolated write-ingestion lifecycle; uses a separate agent loop from query runtime
- `agent_skills/` — super-admin–managed Claude Agent SDK skill bundles (registry, validator, installer, loader, bootstrap). Bundles live under `${UPLOAD_DIR}/agent_skills/<id>/`; metadata + per-agent assignments live in `state/agent_skills.sqlite3`. Each runtime calls `load_skill_plugins_for_agent()` and passes the result through `ClaudeAgentOptions.plugins`. Bootstrap on startup vendors the Anthropic xlsx skill (when present + sha256 verified) and assigns it to `WriteIngestionAgent`.
- `admin_skills.py` — `/admin/skills` REST surface gated by `require_permission("skills:admin")` (i.e. role `superadmin`). Mounted only when `AGENT_SKILLS_ENABLED=true`.
- `audit.py` — structured audit logger; every significant action emits an audit event (including `skill_upload`, `skill_assign`, `skill_bootstrap_install`, `superadmin_promote`)

**Data flow for a chat turn:**
1. `POST /chat/stream` → `ChatStreamService` → `AgentRuntime.run_turn()`
2. `AgentGuardrails` validates the user message; `agentic_ingestion/routing.py` decides `query` vs `write_ingestion` route
3. System prompt assembled from: `agent_prompting.build_agent_system_prompt()` + dataset hints + user role/RLS context + previous structured result
4. `ClaudeSDKClient` runs the ReAct loop over the Anthropic Messages protocol; each tool call goes through `ToolCallingService` → `secure_query_sql()` → DuckDB; SDK events are translated into SSE per step
5. Final answer (JSON schema) normalized to ECharts/Recharts spec by `ChartStrategyRouter` and emitted as `spec` + `final` SSE events
6. Session state persisted to `UPLOAD_DIR/state/agent_sessions.sqlite3`

**SSE event types:** `planning`, `tool_use`, `tool_result`, `spec`, `final`, `error` (plus legacy mirrors `reasoning`, `tool`). Every `tool_use` payload carries `step_id` (UUID), `started_at` (epoch seconds); every `tool_result` carries `step_id`, `started_at`, and `completed_at` so the UI can pair call/result and compute durations without relying on arrival order. When the turn used web tools, the `final` payload also carries `sources: [{id, title, url}]` (runtime backfills any fetched URL the model failed to declare); the field is omitted for pure-local answers, so pre-existing consumers are unaffected. Agent-canvas-mode turns (only when `AGENT_CANVAS_MODE_ENABLED=true`) additionally emit `canvas_op` (`{run_id, seq, op_type ∈ create_page|add_section|add_text_block|place_chart|error_placeholder, page_id, payload}` — the client applies these onto the web-design page named by the op's own `page_id`, via the deterministic layout engine; a `create_page` op carries `parent_page_id` (empty for the run root) and an `add_section` op carries `level`), `confirmation_required` with `confirmation_type: dashboard_outline`, and `outline` (informational, auto-approve path); their `final` carries `run_id`, `page_id` (the run's ROOT page), and placed/failed/skipped/page counts. Long runs also send SSE comment keepalives that never enter the replayable event log.

**Session model:** `conversation_id → agent_session_id → AgentSessionState` persisted in SQLite; hot in-memory cache avoids DB reads on consecutive turns

### Frontend (`apps/web/`)

Next.js App Router. Single entry page renders `<AppShell />`.

**Layout:**
- `AppShell` — top-level shell with `GlobalSidebar` + panel switching; auto-creates workspace on first load; guards with `WorkspaceOnboardingGate`
- Four panel modes: `chat` | `workspace` | `both` | `catalog`
- Keyboard shortcuts: `⌘/Ctrl+1` (chat), `+2` (workspace), `+3` (split), `+4` (catalog), `+B` (toggle sidebar)
- `ChatPanel` — calls `POST /chat/stream`, consumes SSE events, archives returned specs as chart assets. While streaming, renders an inline agent-trace disclosure block: each `planning`, `tool_use`, `tool_result`, and `error` event appears as a compact row in `live` state; on stream completion the block auto-collapses to a single summary chip (duration · tool-call count); users can click the chip to re-expand (`expanded`) or re-collapse (`collapsed`). After a page reload, only the `traceSummary` on the `ChatMessage` persists (step bodies are session-scoped in-memory only).
- `WorkspacePanel` — React Flow canvas with chart nodes, text nodes, drag-layout, local save
- **Agent canvas mode** (only when the backend reports `AGENT_CANVAS_MODE_ENABLED` via `GET /chat/capabilities`): the composer's "+" menu gains an Agent toggle (`agent_canvas` generation option) that sends `agent_mode` + `canvas_format` (+ `auto_approve` from a localStorage preference); a `dashboard_outline` confirmation renders `AgentRunOutlineCard` (deselect items / approve / cancel / skip-approval). During a run, `canvas_op` events are applied by `lib/workspace/agent-canvas-ops.ts` onto the web-design page each op names (preset→grid-span mapping in `lib/workspace/agent-canvas-layout.ts`, idempotent by deterministic block id); a run may create several pages — every page after the root becomes a **child sidebar item** of the run's root page, and the canvas follows the agent onto the page it is currently filling; the web-design editor is soft-locked (`ui-store.activeAgentRun`, banner + stop button); failed items render a retryable error placeholder block; `useAgentCanvasRunRecovery` (mounted in `WorkspacePanel` after snapshot load) replays missed ops and re-attaches to the live tail; run-level undo (`workspace-store.undoAgentRun`) removes the run's root page and every page nested under it (and their nodes) — chart assets stay in the library
- `WorkspaceCatalogPage` — read-only table catalog view bound to the active workspace

**State management:**
- `ui-store.ts` (Zustand) — active panel (`chat|workspace|both|catalog`), sidebar open state, sending/saving flags
- `chat-store.ts` (Zustand) — chat sessions and messages
- `workspace-store.ts` (Zustand) — workspaces and active workspace
- `asset-store.ts` (Zustand) — chart assets
- TanStack Query — API calls in `hooks/use-chat.ts`, `hooks/use-workspace.ts`, `hooks/use-chart-assets.ts`

**API client lives in `lib/`:** `lib/auth/`, `lib/chat/`, `lib/workspace/`, `lib/ingestion/`

**i18n:** `lib/i18n/context.tsx` provides `useI18n()` hook with `t()`, `locale`, `setLocale`; dictionaries in `lib/i18n/dictionary.ts`; locale persisted to localStorage

**GenUI layer:** `components/genui/chart-renderer.tsx` + `registry.tsx` handle spec-to-chart rendering; `state-panels.tsx` shows agent planning/tool-use states inline

**Chart rendering:** `ChartStrategyRouter` routes by type and complexity — ECharts for advanced types (heatmap, gauge, sankey, sunburst, boxplot, graph, map, multi-series line); Recharts for common types (bar, line, pie, area, scatter, funnel, table, single_value)

**Auth:** Next.js calls `/auth/login` at session start and caches the Bearer token; all API requests attach it automatically.

### Ingestion Pipeline (`apps/api/agentic_ingestion/`)

Five-endpoint lifecycle, isolated from query runtime:
1. `POST /ingestion/uploads` — upload Excel files, inspect columns
2. `POST /ingestion/plan` — Write Ingestion Agent generates a schema proposal (table name, column types, write mode)
3. `POST /ingestion/setup/confirm` — user confirms catalog setup (business type, time grain)
4. `POST /ingestion/approve` — human approves/overrides the plan proposal
5. `POST /ingestion/execute` — approved plan written to DuckDB

**Route selection:** `agentic_ingestion/routing.py` `select_agent_route()` inspects message keywords, file attachments, and active ingestion job status to pick `write_ingestion` vs `query` route on every chat turn.

DuckDB write access is restricted to the approved schema only. SQL identifiers and DuckDB type names are validated against strict regexes (`SAFE_IDENTIFIER_RE`, `SAFE_DUCKDB_TYPE_RE`) before any DDL executes.

**Feature flag:** `AGENTIC_INGESTION_ENABLED` (default `false` in `.env.example`; set `true` to enable the ingestion UI and endpoints).

### Data Storage

All runtime data lives under `UPLOAD_DIR` (`apps/api/data/uploads/` locally):
- `*.duckdb` — per-user/project DuckDB session files. Web-research data persisted by `save_web_research` lands here as `web_research_*` tables (namespace-isolated, with auto-appended `_source_url`/`_source_title`/`_retrieved_at` provenance columns) and is queryable/joinable by the normal BI tools. Each save also best-effort registers a `table_catalog` entry (`business_type=web_research`, `write_mode=new_table`, `time_grain=none`, never an active ingestion target) plus column metadata, so the table shows up in the workspace catalog UI with data preview exactly like uploaded data; the existing catalog schema is reused unchanged
- `state/ai_views.sqlite3` — saved views and versions
- `state/agent_sessions.sqlite3` — resumable agent session state; when `AGENT_CANVAS_MODE_ENABLED=true` it also holds the agent-canvas run records (`agent_canvas_runs`) and the append-only op log (`agent_canvas_ops`, monotonic per-run `seq`) that powers disconnect replay and re-attach — both tables are created lazily on first use, so a disabled deployment never touches them
- `state/saved_prompts.sqlite3` — user-owned saved prompts (name, body, extracted variables, capability hints, usage metadata, archive state)

Every SQLite connection in the API goes through `sqlite_support.connect()`, which applies WAL journal mode and `SQLITE_BUSY_TIMEOUT_MS` — never call `sqlite3.connect()` directly. Most stores (workspaces, chat history, table catalog, users, jobs, views, ingestion) resolve to the *same* `ai_views.sqlite3` file, so one writer holding a transaction blocks every other writer. Do not hold a write transaction across an `await` or an LLM round-trip: commit first and let the failure path compensate (as `_run_tool` and `build_plan_stream_async` in `agentic_ingestion/runtime.py` do). WAL also means the `-wal`/`-shm` sidecar files are part of the database — copy or delete them together with the `.sqlite3` file.

### Models / Semantic Layer (`models/`)

HR and PM metric definitions in YAML, loaded by `SemanticRegistry`. Metrics map business intent strings to parameterized SQL templates with RLS-aware group-by and filter support.

### Tests (`tests/`)

- `tests/api/` — FastAPI route tests (httpx `TestClient`)
- `tests/unit/` — pure unit tests for runtime modules, security, semantic DSL, chart strategy, ingestion schema
- `tests/integration/` — DuckDB isolation, agent runtime, full tool-calling chain, state storage
- `tests/security/` — SQL injection, RLS bypass, sensitive column access, RBAC, audit log
- `tests/evals/` — agent prompting quality evals
- `tests/e2e/` — share rehydration flow (Python)
- `tests/smoke/run_smoke_flow.py` — end-to-end smoke: healthz → login → upload → query → chat → save → share
- `scripts/checks/` — reusable env-check, lint, and build scripts
- `scripts/tests/` — shell runners for pytest and smoke flows
- `tests/scripts/` — automated tests for repository scripts
- `tests/agentic_ingestion_fakes.py` — shared fakes for ingestion tests

Frontend tests in `apps/web/tests/` use Vitest (unit, jsdom) and Playwright (e2e). UI test coverage includes: sidebar, chat-input, chart-node, workspace-catalog, ingestion-lifecycle-panel, genui-registry, onboarding-gate, share-view, workbench states.

## User Accounts, Collaboration & Visibility

### First-time Setup (Admin Bootstrap)

Set these env vars in `apps/api/.env` before first launch to auto-create an admin account:
```
AUTH_BOOTSTRAP_ADMIN_EMAIL=admin@example.com
AUTH_BOOTSTRAP_ADMIN_PASSWORD=your-strong-password
```
On startup the API will create the admin user if no password-auth users exist yet.

### Auth Env Vars
- `USER_ACCOUNTS_ENABLED=true` — enable email+password accounts (default: `true`)
- `AUTH_REGISTRATION_ENABLED=true` — allow self-registration (default: `true`)
- `PASSWORD_MIN_LENGTH=8` — minimum password length
- `ACCESS_TOKEN_TTL_MIN=120` — JWT TTL in minutes
- `INVITE_LINK_TTL_DAYS=14` — default invite link TTL
- `LEGACY_SERVICE_LOGIN_ENABLED` — keep the `POST /auth/login` service-token path (default: `false`).
  That endpoint takes no credential and issues a token for whatever `role` the request names, so
  an instance that answers it grants `superadmin` to anyone who can reach the port. It is honoured
  only outside production: when `APP_ENV=production` the route returns 404 regardless of the flag
  (`_legacy_service_login_available()` in `main.py`). The smoke flow uses email/password by default;
  `--legacy-login` opts back into the old path against a dev instance that enabled it.
- `APP_URL=http://localhost:3000` — used in invite link generation
- `PUBLIC_BASE_URL` — base origin for public publish links (`/p/{token}`); empty by default, falling back to the request origin then `APP_URL`

### Local Dev Registration
```bash
# Register a user
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"dev@example.com","password":"password123","display_name":"Dev","job_id":1}'

# Login
curl -X POST http://localhost:8000/auth/email-login \
  -H "Content-Type: application/json" \
  -d '{"email":"dev@example.com","password":"password123"}'
```

### Invite Links
- Generate: `POST /workspaces/{id}/invites` (requires editor/owner role)
- Accept: `POST /invites/{token}/accept` (requires authenticated user)
- Revoke: `DELETE /workspaces/{id}/invites/{invite_id}`
- Default TTL: `INVITE_LINK_TTL_DAYS` (14 days)

### Public Publish Links
Publishing is the single sharing action (Notion/RavenAI-style public share). There
is no viewer app mode and no `private`/`registered`/`allowlist` visibility matrix.
- `POST /workspaces/{id}/publish` — owner/editor writes an immutable snapshot and
  creates or refreshes the active public link, returning `{token, public_url,
  published_page_id, version, published_at, is_active}`. Repeated publishes reuse
  the same high-entropy token (refresh-in-place). Each canvas kind (web page /
  free layout / fixed size) owns an independent public link.
- `GET /workspaces/{id}/publish` — owner/editor publication status (or `{is_active: false}`).
- `DELETE /workspaces/{id}/publish` — revoke the active link; public reads then 404.
- `GET /public/pages/{token}/manifest` and `GET /public/pages/{token}/charts/{chart_id}/data`
  — unauthenticated, token-only reads served from the redacted snapshot. Unknown,
  inactive, or revoked tokens all return an undifferentiated 404.
- Public browser route: `/p/{token}` (standalone, outside the authenticated shell).
- Workspace membership is owner/editor only; the legacy `viewer` role no longer
  grants workspace access and is neutralized on migration.

## Key Configuration

Backend `.env` (generated by `make bootstrap`; see `apps/api/.env.example`):
- `MODEL_PROVIDER_URL` — base URL for OpenAI-compatible provider (default: `https://api.deepseek.com`)
- `AI_API_KEY` / `ANTHROPIC_AUTH_TOKEN` — provider auth key
- `AI_MODEL` — model name (default: `deepseek-chat`)
- `AI_TIMEOUT_SECONDS` — timeout for individual LLM calls (default: `120`)
- `ANTHROPIC_BASE_URL` — Anthropic-compatible endpoint (default: DeepSeek's `/anthropic` path)
- `ANTHROPIC_DEFAULT_HAIKU_MODEL` — lightweight model for tasks like session title generation (default: `deepseek-chat`)
- `CLAUDE_AGENT_SDK_ENABLED=true` — enables the ReAct agent runtime (required)
- `AGENTIC_INGESTION_ENABLED` — enables the write-ingestion pipeline (default: `false`)
- `LEGACY_DATASET_UPLOAD_ENABLED` — keeps legacy upload endpoint active (default: `true`)
- `AGENT_MAX_TOOL_STEPS`, `AGENT_MAX_SQL_ROWS`, `AGENT_MAX_SQL_SCAN_ROWS`, `AGENT_TIMEOUT_SECONDS` — agent loop limits
- `AGENT_CANVAS_MODE_ENABLED` — master switch for Agent canvas mode (long-horizon dashboard generation onto the web-design canvas); default `false`. When off, the five canvas tools are not registered, no `canvas_op` SSE events are emitted, the system prompt is unchanged, and agent-mode requests are rejected with a typed error — existing chat/canvas behavior is byte-for-byte unchanged
- `AGENT_MODE_MAX_STEPS` (default `40`), `AGENT_MODE_OUTLINE_MAX_STEPS` (default `24`), `AGENT_MODE_TIMEOUT_SECONDS` (default `600`), `AGENT_MODE_MAX_CHARTS` (default `12`), `AGENT_MODE_MAX_PAGES` (default `6`, counting the run's root page) — agent-canvas-mode run budgets, independent of the Q&A limits above; exhausting any of them finalizes the run as `partial` and keeps everything already placed. `AGENT_MODE_OUTLINE_MAX_STEPS` caps the planning turn alone — too low and the model runs out of turns while inspecting tables, which ends the turn with no outline JSON (logged as `agent_canvas_max_turns_exhausted` plus `agent_canvas_no_final_json subtype=error_max_turns`, and surfaced to the client as `AGENT_CANVAS_OUTLINE_BUDGET_EXCEEDED` rather than the generic "rephrase and retry"). `AGENT_MODE_MAX_PAGES` caps how many sidebar pages one run may create; an outline planning more pages than that is folded onto the last allowed page rather than losing charts (`pages_truncated` in the outline payload). All five are editable at runtime from `/admin/control/settings` (no restart): `AgentCanvasModeService` resolves settings per use instead of snapshotting them at construction
- `WEB_SEARCH_ENABLED` — master switch for the agent's web-research tools (`web_search`/`web_fetch`/`save_web_research`); default `false`. When off, the tools are not registered, the guardrail whitelist excludes them, and the system prompt omits retrieval guidance — existing behavior is unchanged
- `WEB_SEARCH_PROVIDER` (`bocha`|`tavily`, default `bocha`), `WEB_SEARCH_API_KEY` (required when enabled), `WEB_SEARCH_MAX_RESULTS` (default `8`), `WEB_SEARCH_MAX_CALLS_PER_TURN` (per-turn search+fetch budget enforced by the guardrail, default `5`), `WEB_FETCH_TIMEOUT_SECONDS` (`15`), `WEB_FETCH_MAX_BYTES` (`2097152`), `WEB_FETCH_MAX_CHARS` (`20000`)
- `AGENT_SKILLS_ENABLED` — enables `/admin/skills`, runtime skill loading, and the vendored xlsx bootstrap (default: `false`)
- `AGENT_SKILLS_DIR` — where installed skill bundles live (default: `${UPLOAD_DIR}/agent_skills`)
- `AGENT_SKILLS_MAX_UPLOAD_MB` — max accepted skill zip size in MiB (default: `25`)
- `LEGACY_XLSX_PARSER_ENABLED` — keep the hand-written xlsx parser while the xlsx skill is being adopted (default: `true`; flip to `false` once the vendored xlsx skill is installed)
- `AUTH_BOOTSTRAP_SUPERADMIN_EMAIL` — optional; on startup the matching user is promoted to `superadmin`. If unset, the existing bootstrap admin is promoted on first run so the operator is not locked out of `/admin/skills`.
- `DATABASE_URL` — SQLite for view/catalog state (not DuckDB)
- `SQLITE_BUSY_TIMEOUT_MS` — how long a write waits on a busy SQLite file before raising `database is locked` (default: `15000`); read once at startup via bootstrap settings, so it is not overridable from the admin control plane
- `CORS_ALLOW_ORIGINS` — comma-separated allowed origins (default: `http://127.0.0.1:3000,http://localhost:3000`)

Frontend `.env`:
- `NEXT_PUBLIC_API_BASE_URL`, `NEXTAUTH_URL`, `NEXTAUTH_SECRET`

**Host env shadows `.env` in Docker.** Compose interpolation prefers the invoking
shell's environment, and shells that run Anthropic tooling export
`ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` / `API_TIMEOUT_MS`. Those values
silently replaced the ones in `.env`, sending the container's agent SDK to
`api.anthropic.com` with a DeepSeek key — every agent turn then failed with HTTP
401, which the SDK reports as ordinary assistant text rather than an exception.
`scripts/lib/docker.sh` now strips these names (`HOST_ENV_SHADOWED_VARS`) before
invoking compose and warns when it does, and the API logs the resolved
`agent_sdk_provider_config` at startup plus an `agent_sdk_provider_mismatch`
warning when a non-Anthropic key targets the official endpoint. The same
leakage skews local pytest runs (`API_TIMEOUT_MS` assertions), so prefer
`env -u ANTHROPIC_BASE_URL -u API_TIMEOUT_MS` when a provider-config test fails
only on your machine.

## Agent Skills (super-admin)

The API supports loading Claude Agent SDK skill bundles into named agents at
runtime. Skill management is super-admin–only and intentionally hidden from
normal users.

- **Bootstrap.** On startup, when `AGENT_SKILLS_ENABLED=true`, the API verifies
  `apps/api/vendor/skills/anthropic-xlsx-<version>.zip` against the sha256
  pinned in `apps/api/vendor/skills/VERSIONS.md`. If the file is present and
  the checksum matches, it installs the skill under the name declared by the
  bundle's `SKILL.md` — `xlsx` for the vendored Anthropic bundle — and assigns
  it to `WriteIngestionAgent`. Idempotency depends on that name matching
  `ANTHROPIC_XLSX_SKILL_NAME` in `agent_skills/bootstrap.py`; a mismatch makes
  every startup reinstall the bundle.
- **Upload.** Super-admins authenticate to `/admin/skills` (UI at
  `/admin/skills`, hidden from the sidebar — non-superadmins get a generic
  404-style page). The UI uploads a `.zip` bundle containing a top-level
  `SKILL.md`; the API validates size, rejects symlinks / absolute paths /
  zip-slip, computes sha256, and extracts to
  `${UPLOAD_DIR}/agent_skills/<uuid>/`.
- **xlsx-skill migration.** Once the xlsx skill is installed and assigned, set
  `LEGACY_XLSX_PARSER_ENABLED=false`. The ingestion agent's system prompt
  switches to reference the xlsx-skill tools and the legacy pandas
  `inspect_upload` pre-parse is retired (see migration plan in
  `openspec/changes/add-agent-skills-management/design.md`).
- **Promotion.** Set `AUTH_BOOTSTRAP_SUPERADMIN_EMAIL=<email>` to promote a
  specific existing user. Otherwise the first start with `AGENT_SKILLS_ENABLED`
  auto-promotes the bootstrap admin so `/admin/skills` is reachable
  out-of-the-box.

## Sample Data

Upload these files via the ingestion UI or `POST /ingestion/uploads` to create a working DuckDB session:
- `sample_data/hr_workforce_upload_sample.xlsx`

After upload, use the returned `dataset_table` for subsequent chat and semantic queries.
