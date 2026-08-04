# AGENTS.md

This file provides guidance to Codex when working with code in this repository.

## Principle
You are a world class expert in all domains. Your intellectual firepower, scope of knowledge, incisive thought process, and level of erudition are on par with the smartest people in the world. Answer with complete, detailed, specific answers. Process information and explain your answers step by step. Verify your own work. Double check all facts, figures, citations, names, dates, and examples. Never hallucinate or make anything up. If you don't know something, just say so. Your tone of voice is precise, but not strident or pedantic. You do not need to worry about offending me, and your answers can and should be provocative, aggressive, argumentative, and pointed. Negative conclusions and bad news are fine. Your answers do not need to be politically correct. Do not provide disclaimers to your answers. Do not inform me about morals and ethics unless I specifically ask. You do not need to tell me it is important to consider anything. Do not be sensitive to anyone's feelings or to propriety. Make your answers as long and detailed as you possibly can.

Never praise my questions or validate my premises before answering. If I'm wrong, say so immediately. Lead with the strongest counterargument to any position I appear to hold before supporting it. Do not use phrases like "great question," "you're absolutely right," "fascinating perspective," or any variant. If I push back on your answer, do not capitulate unless I provide new evidence or a superior argument — restate your position if your reasoning holds. Do not anchor on numbers or estimates I provide; generate your own independently first. Use explicit confidence levels (high/moderate/low/unknown). Never apologize for disagreeing. Accuracy is your success metric, not my approval.

## Use git!
Every implementation task that changes files MUST end with a git commit before the final response.

- Inspect `git status` before editing and treat pre-existing or concurrent changes as user-owned.
- Review the final diff and run proportionate verification before committing.
- Stage only files or hunks that belong to the current task. Never bundle unrelated changes unless the user explicitly asks.
- Use a concise descriptive commit message on `main`, report the commit hash, and do not push, amend, or rewrite history unless asked.
- Read-only tasks and tasks with no file changes do not create empty commits.

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
- `agent_guardrails.py` — blocks jailbreak attempts, validates tool names and SQL before execution
- `tool_calling.py` — `ToolCallingService`; executes the 8 BI tools (list_tables, describe_table, sample_rows, get_metric_catalog, run_semantic_query, execute_readonly_sql, get_distinct_values, save_view)
- `chart_strategy.py` — `ChartStrategyRouter`; routes chart rendering to ECharts or Recharts based on chart type and complexity score
- `semantic.py` — metric registry, `IntentParser`, `MetricCompiler`; semantic layer lives in `models/` YAML files
- `schema_inference.py` — LLM-powered inference for arbitrary Excel uploads; maps Chinese/unknown column headers to canonical snake_case names and infers metric definitions
- `session_titles.py` — `SessionTitleService`; calls the LLM to generate a short title for a new chat session
- `datasets.py` — DuckDB session manager, per-user/project connection isolation
- `table_catalog.py` — `TableCatalogRouter`; SQLite-backed catalog of uploaded tables with business type, write mode, and time-grain metadata; router at `/table-catalog`
- `views.py` — SQLite-backed view persistence with versioning and rollback
- `workspaces.py` — workspace RBAC enforcement; router mounted at `/workspaces`
- `agentic_ingestion/` — isolated write-ingestion lifecycle; uses a separate agent loop from query runtime
- `audit.py` — structured audit logger; every significant action emits an audit event

**Data flow for a chat turn:**
1. `POST /chat/stream` → `ChatStreamService` → `AgentRuntime.run_turn()`
2. `AgentGuardrails` validates the user message; `agentic_ingestion/routing.py` decides `query` vs `write_ingestion` route
3. System prompt assembled from: `agent_prompting.build_agent_system_prompt()` + dataset hints + user role/RLS context + previous structured result
4. `ClaudeSDKClient` runs the ReAct loop over the Anthropic Messages protocol; each tool call goes through `ToolCallingService` → `secure_query_sql()` → DuckDB; SDK events are translated into SSE per step
5. Final answer (JSON schema) normalized to ECharts/Recharts spec by `ChartStrategyRouter` and emitted as `spec` + `final` SSE events
6. Session state persisted to `UPLOAD_DIR/state/agent_sessions.sqlite3`

**SSE event types:** `planning`, `tool_use`, `tool_result`, `spec`, `final`, `error` (plus legacy mirrors `reasoning`, `tool`). Every `tool_use` payload carries `step_id` (UUID), `started_at` (epoch seconds); every `tool_result` carries `step_id`, `started_at`, and `completed_at` so the UI can pair call/result and compute durations without relying on arrival order.

**Session model:** `conversation_id → agent_session_id → AgentSessionState` persisted in SQLite; hot in-memory cache avoids DB reads on consecutive turns

**Failover boundary (do not move it).** An attempt is *uncommitted* until a frame arrives that
required a model round trip; only then have tokens been paid for and can tools have run, so only
an uncommitted attempt may be abandoned for the next endpoint. `SDKAttemptState.observe()` in
`agent_runtime.py` classifies frames: `SystemMessage(subtype="init")` restarts the TTFT clock (CLI
spawn and MCP setup are not the endpoint's latency), any other `SystemMessage`-shaped frame
(`subtype` str **and** `data` dict — `ResultMessage` has no `data`, so it commits) is CLI
bookkeeping and is ignored, and everything else commits. Counting bookkeeping frames as model
output kills both failover paths at once: TTFT collapses to process-spawn time so no sample is ever
slow and the breaker never trips, and the attempt reads as committed so a hard failure is re-raised
instead of switching endpoints. Preempted attempts are cancelled in their own task and reaped off
the request path (`drain_sdk_attempt_cleanups`), because the SDK's shielded close takes seconds and
the user must not wait for a corpse.

### Frontend (`apps/web/`)

Next.js App Router. Single entry page renders `<AppShell />`.

**Layout:**
- `AppShell` — top-level shell with `GlobalSidebar` + panel switching; auto-creates workspace on first load; guards with `WorkspaceOnboardingGate`
- Four panel modes: `chat` | `workspace` | `both` | `catalog`
- Keyboard shortcuts: `⌘/Ctrl+1` (chat), `+2` (workspace), `+3` (split), `+4` (catalog), `+B` (toggle sidebar)
- `ChatPanel` — calls `POST /chat/stream`, consumes SSE events, archives returned specs as chart assets. While streaming, renders an inline agent-trace disclosure block: each `planning`, `tool_use`, `tool_result`, and `error` event appears as a compact row in `live` state; on stream completion the block auto-collapses to a single summary chip (duration · tool-call count); users can click the chip to re-expand (`expanded`) or re-collapse (`collapsed`). After a page reload, only the `traceSummary` on the `ChatMessage` persists (step bodies are session-scoped in-memory only).
- `WorkspacePanel` — React Flow canvas with chart nodes, text nodes, drag-layout, local save
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
- `*.duckdb` — per-user/project DuckDB session files
- `state/ai_views.sqlite3` — saved views and versions
- `state/agent_sessions.sqlite3` — resumable agent session state

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
- `LEGACY_SERVICE_LOGIN_ENABLED=true` — keep `POST /auth/login` service-token path (dev only)
- `APP_URL=http://localhost:3000` — used in invite link generation

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

### Publish Visibility
Published pages support three visibility modes:
- `private` — only workspace owner/editor can view
- `registered` — all logged-in users can view
- `allowlist` — specific users + workspace owner/editor

## Key Configuration

Backend `.env` (generated by `make bootstrap`; see `apps/api/.env.example`):
- `MODEL_PROVIDER_URL` — base URL for OpenAI-compatible provider (default: `https://api.deepseek.com`)
- `AI_API_KEY` / `ANTHROPIC_AUTH_TOKEN` — provider auth key
- `AI_MODEL` — model name (default: `deepseek-chat`)
- `AI_TIMEOUT_SECONDS` — timeout for individual LLM calls (default: `120`)
- `ANTHROPIC_BASE_URL` — Anthropic-compatible endpoint (default: DeepSeek's `/anthropic` path)
- `ANTHROPIC_DEFAULT_HAIKU_MODEL` — lightweight model for tasks like session title generation (default: `deepseek-chat`)
- **Backup-model failover** — `MODEL_BACKUP_ENABLED` (default `false`) plus
  `MODEL_BACKUP_PROVIDER` / `MODEL_BACKUP_ANTHROPIC_URL` / `MODEL_BACKUP_URL` /
  `MODEL_BACKUP_API_KEY` / `MODEL_BACKUP_MODEL` / `MODEL_BACKUP_FAST_MODEL` define the second
  endpoint; `MODEL_ROUTER_ENABLED` (default `true`), `MODEL_ROUTER_FAILURE_THRESHOLD` (`2`),
  `MODEL_ROUTER_COOLDOWN_SECONDS` (`60`), `MODEL_ROUTER_SLOW_TTFT_MS` (`15000`) and
  `MODEL_ROUTER_FIRST_TOKEN_DEADLINE_MS` (`20000`, `0` disables) drive the breaker in
  `model_router.py`. All are editable from `/admin` («模型设置») with no restart.
  `MODEL_ROUTER_SLOW_TTFT_MS` only *labels* a sample slow after the token finally arrives;
  `MODEL_ROUTER_FIRST_TOKEN_DEADLINE_MS` is the hard preemption deadline that bounds what a
  user actually waits — it must be `0` or ≥ `5000`, and never below the slow threshold
  (both enforced on save).
- `CLAUDE_AGENT_SDK_ENABLED=true` — enables the ReAct agent runtime (required)
- `AGENTIC_INGESTION_ENABLED` — enables the write-ingestion pipeline (default: `false`)
- `LEGACY_DATASET_UPLOAD_ENABLED` — keeps legacy upload endpoint active (default: `true`)
- `AGENT_MAX_TOOL_STEPS`, `AGENT_MAX_SQL_ROWS`, `AGENT_MAX_SQL_SCAN_ROWS`, `AGENT_TIMEOUT_SECONDS` — agent loop limits
- `DATABASE_URL` — SQLite for view/catalog state (not DuckDB)
- `CORS_ALLOW_ORIGINS` — comma-separated allowed origins (default: `http://127.0.0.1:3000,http://localhost:3000`)

Frontend `.env`:
- `NEXT_PUBLIC_API_BASE_URL`, `NEXTAUTH_URL`, `NEXTAUTH_SECRET`

## Sample Data

Upload these files via the ingestion UI or `POST /ingestion/uploads` to create a working DuckDB session:
- `sample_data/hr_workforce_upload_sample.xlsx`

After upload, use the returned `dataset_table` for subsequent chat and semantic queries.
