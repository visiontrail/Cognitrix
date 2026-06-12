# Cognitrix — AI-Native BI & Analytics Platform

English | [简体中文](README_CN.md)

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Node 20+](https://img.shields.io/badge/node-20%2B-green.svg)](https://nodejs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688.svg)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-15-black.svg)](https://nextjs.org/)
[![DuckDB](https://img.shields.io/badge/DuckDB-powered-yellow.svg)](https://duckdb.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

> **Upload Excel → Ask in natural language → Get charts & dashboards.**
> An open-source, AI-native business intelligence platform that turns any structured spreadsheet into an interactive analytics workspace — no SQL, no data warehouse, no pre-built dashboards required.

---

## What is Cognitrix?

**Cognitrix** is an AI-native BI platform for structured data analytics. It replaces the traditional BI stack — ETL pipelines, fixed dashboards, SQL expertise — with a conversational AI agent that understands business questions and generates charts on demand.

Key differentiators versus traditional BI tools (Tableau, Power BI, Metabase):

| Capability | Traditional BI | Cognitrix |
|---|---|---|
| Data onboarding | Warehouse + ETL pipeline | Upload Excel directly |
| Querying | Drag-and-drop / SQL | Natural language conversation |
| Chart creation | Manual configuration | AI-generated, spec-driven |
| Ad-hoc analysis | Requires analyst support | Self-service, instant |
| Access control | Dashboard-level | Row-level security (RLS) per role |
| Share & collaborate | Static links | Versioned views, RBAC-gated |

---

## Key Features

- **Natural Language Analytics** — Ask questions like "show attrition by department" or "find high-risk projects" and get charts, tables, and takeaways instantly.
- **Excel to Insights in Minutes** — Upload any structured spreadsheet; the Agentic Ingestion pipeline infers schema, resolves column names, and creates a queryable DuckDB dataset.
- **Agentic Query Engine** — A ReAct agent loop (Claude/DeepSeek-compatible) explores table structures, selects semantic metrics, and generates read-only SQL — all transparently streamed to the UI.
- **Semantic Metric Layer** — YAML-driven metric definitions prevent AI hallucinations on business KPIs (headcount, attrition rate, project velocity, budget burn, etc.).
- **AI-Generated Dashboards** — Specs streamed as JSON are rendered by ECharts (heatmap, sankey, gauge, graph) and Recharts (bar, line, pie, scatter, funnel, table, KPI card).
- **Visual Workspace** — Drag-and-drop React Flow canvas lets you compose charts into shareable analytical dashboards.
- **Versioned Views & Sharing** — Save, version, and share analysis views with role-aware data redaction at the API layer.
- **Enterprise-Grade Security** — JWT auth, RBAC permission scopes, row-level security injection, SQL read-only validation, audit logging, and jailbreak guardrails.
- **LLM-Provider Agnostic** — Works with DeepSeek, Claude (Anthropic), Kimi, or any OpenAI-compatible endpoint via a single env-var swap.
- **Self-Hosted & Open Source** — Runs locally or in Docker; no cloud lock-in, no SaaS fees.

---

## Use Cases

- **HR Analytics** — Workforce headcount, attrition trends, compensation benchmarking, performance distribution, department-level drill-downs.
- **Project Management BI** — Sprint velocity, budget burn rate, task completion rates, resource utilization, risk heatmaps.
- **Sales & Revenue** — Pipeline analysis, win/loss rates, quota attainment, territory comparisons from CRM exports.
- **Finance & Operations** — Cost center breakdowns, budget vs actuals, operational KPIs — all from existing Excel reports.
- **Executive Dashboards** — Compose multi-chart workspaces, save them as versioned views, and share with role-restricted audiences.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Next.js Frontend (Port 3000)              │
│  ChatPanel · WorkspaceCanvas · CatalogView · ShareView       │
│  Zustand · TanStack Query · React Flow · ECharts · Recharts  │
└───────────────────────────┬─────────────────────────────────┘
                            │  SSE stream (planning/tool_use/spec/final)
┌───────────────────────────▼─────────────────────────────────┐
│                    FastAPI Backend (Port 8000)                │
│                                                              │
│  AgentRuntime ──► ReAct Loop ──► ToolCallingService          │
│       │               │               │                      │
│  AgentGuardrails  LLM Client     SemanticLayer (YAML)        │
│  (SQL/jailbreak)  (OpenAI-compat) MetricCompiler             │
│       │               │               │                      │
│  ChartStrategyRouter ◄─────── secure_query_sql()             │
│  (ECharts / Recharts)         RLS · RBAC · Audit             │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│              Data Layer                                      │
│  DuckDB (per-user session) · SQLite (views, sessions)        │
│  UPLOAD_DIR/state/  ·  sample_data/*.xlsx                    │
└─────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Backend** | FastAPI, Pydantic Settings, Python 3.11+ |
| **Analytics Engine** | DuckDB (in-process OLAP), Pandas, sqlglot |
| **Agent Runtime** | Claude Agent SDK / DeepSeek (OpenAI-compatible) |
| **Frontend** | Next.js 15 App Router, React 18, TypeScript |
| **State Management** | Zustand, TanStack Query |
| **Visualization** | ECharts, Recharts, React Flow |
| **Auth & Security** | JWT, RBAC, Row-Level Security, SQL Validator |
| **Storage** | DuckDB (analytics), SQLite (state), filesystem (uploads) |
| **Delivery** | Docker Compose, Makefile |

---

## Quick Start

**Requirements:** Python 3.11+, Node.js 20+, npm 10+, GNU Make

```bash
# 1. Install all dependencies and generate .env files
make bootstrap

# 2. Validate environment variables
make env-check

# 3. Start API (port 8000) and Web (port 3000)
make dev
```

Open **http://127.0.0.1:3000** — upload one of the sample Excel files to start querying.

> See [Local Configuration](#local-configuration) for API keys and provider setup.

---

## Current Status

- All 45 tasks across M0–M9 in `SPEC_PLAN.md` have been completed. The project now supports local development, Docker delivery, backend/security/integration/smoke tests, and the main Agentic Query workflow.
- The frontend has evolved from a single-page integration console into a product-style workspace: a global left sidebar manages Conversations / Workspaces, while the center area supports Chat, Canvas, and Split layouts with `Cmd/Ctrl + 1/2/3/B` shortcuts.
- The main Chat entry calls the backend `POST /chat/stream`, consumes `planning/tool_use/tool_result/spec/final/error` SSE events, and archives returned specs as chart assets. Legacy `reasoning/tool` compatibility events are still retained.
- Workspaces use a React Flow canvas with chart nodes, text nodes, draggable layouts, rename, duplicate, delete, and local persistence.
- The Share page reads backend-saved view state and can re-render charts plus saved conversation context through `/share/[viewId]` without calling the model again.
- The backend already includes upload handling, the semantic layer, a controlled BI tool surface, Claude Agent SDK powered Agentic Query, authorization, audit logging, view versioning, and agent session resume.
- The project is still in prototype/internal-testing stage: frontend Conversations / Workspaces / Chart Assets lists and canvas state are mostly managed through mock APIs and localStorage. The backend already handles real data uploads, queries, agent chat streams, and shared view storage.

---

## Core Capabilities

### Turn Excel into analyzable data assets

- Business teams can upload arbitrary structured spreadsheets — HR, sales, finance, or operations data — without first building a warehouse, writing SQL, or conforming to complex templates.
- The system automatically recognizes common field meanings, combines multiple spreadsheets, and produces datasets that can continue into analysis.
- After upload, it returns data quality feedback so teams can judge whether the data is complete and suitable for further analysis.
- A built-in extensible semantic metric layer, driven by YAML, supports cross-domain metric definitions so business questions can be understood and calculated directly.

### Analyze ad-hoc questions through conversation

- Users can ask questions as if speaking with a business analyst — "show attrition by department", "find high-risk projects", "show the distribution by hire year".
- The agent explores table structures, reads samples, chooses semantic metrics, or generates read-only SQL based on the question, reducing manual schema trial-and-error and metric refinement.
- For standard metrics, the system prioritizes stable definitions. For ad-hoc questions, the AI analysis assistant can still perform flexible data exploration.
- Answers include results, generated charts, and short takeaways to help users decide what to inspect next.
- Multi-turn conversations retain `agent_session_id` and the latest structured result, supporting follow-ups like "change it to a line chart" or "break it down by department".

### Move from insight to visual workspace

- Charts generated in conversation can be saved as chart assets and then arranged in the workspace.
- Users can switch between conversation, canvas, and split modes, turning one-off Q&A into reusable analytical dashboards.
- Current chart support includes bar, line, pie, area, scatter, funnel, table, single-metric cards, heatmap, gauge, sankey, sunburst, boxplot, graph.
- Analysis context is preserved so later follow-ups, filters, and chart adjustments feel natural.

### Make views visible with permissions

- Key analyses can be saved as views and opened through a dedicated presentation entry. Authenticated users can read content they own or are allowed to access.
- The share entry also requires Bearer authentication and redacts saved AI state in the response according to the caller role.
- Private view reads follow owner/admin access rules. Shared views are exposed to authenticated roles through the `views:share` permission.
- A view can be updated and rolled back by version, which is useful for weekly reports, project reviews, and management dashboards that evolve over time.
- Uploads, queries, analysis actions, permission changes, and rollbacks are audited for traceability.

---

## Repository Layout

```text
.
├── apps/api              # FastAPI backend (agent runtime, semantic layer, security)
├── apps/web              # Next.js frontend (chat, workspace, share, catalog)
├── models                # HR / PM semantic metric definitions (YAML)
├── sample_data           # Example Excel files for local testing
├── tests                 # Backend, integration, security, eval, and smoke tests
├── scripts               # Dev/start/deploy entrypoints plus grouped helper scripts
│   ├── checks            # Env validation, lint, and build checks
│   ├── maintenance       # Local data reset and one-off migration helpers
│   ├── setup             # Bootstrap and local service setup helpers
│   └── tests             # Test and smoke-test runners
├── docs/adr              # Architecture decision records
├── infra/docker          # Alternative Docker Compose configurations
└── packages/shared       # Shared package placeholder
```

---

## Requirements

- Python 3.11+
- Node.js 20+
- npm 10+
- GNU Make
- Docker Desktop — optional; only required for container delivery and Docker smoke tests

---

## Common Commands

```bash
make help              # Show available commands
make bootstrap         # Install Python / Web dependencies and initialize .env files
make env-check         # Validate apps/api/.env and apps/web/.env
make dev               # Start API and Web together
make dev-api           # Start only FastAPI
make dev-web           # Start only Next.js
make dev-local         # Start in debug mode, writing logs to logs/dev-local
make lint              # Backend compileall + frontend lint
make test              # Backend pytest; add frontend tests when RUN_WEB_TESTS=1
make build             # Backend compile check + frontend production build
make smoke-local       # Local end-to-end smoke flow
make smoke-docker      # Docker end-to-end smoke flow
make test-all          # lint + test + build + smoke-local + optional smoke-docker
make reset-local-data  # Clear local runtime data
make docker-up         # Build and start Docker Compose
make docker-down       # Stop Docker Compose
```

---

## Local Configuration

`make bootstrap` generates the following files from templates when they are missing:

- `apps/api/.env`
- `apps/web/.env`

Key backend variables:

```env
DATABASE_URL=sqlite:///./data/uploads/state/ai_views.sqlite3
MODEL_PROVIDER_URL=https://api.deepseek.com
AI_API_KEY=
AI_MODEL=deepseek-chat
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
ANTHROPIC_AUTH_TOKEN=
ANTHROPIC_DEFAULT_HAIKU_MODEL=deepseek-chat
API_TIMEOUT_MS=600000
CLAUDE_AGENT_SDK_ENABLED=true
AGENTIC_INGESTION_ENABLED=true
AUTH_SECRET=replace-with-a-strong-secret
UPLOAD_DIR=./data/uploads
CORS_ALLOW_ORIGINS=http://127.0.0.1:3000,http://localhost:3000
```

Excel uploads always use Agentic ingestion. `AGENTIC_INGESTION_ENABLED` is kept only for compatibility with older environment files and no longer disables `/ingestion/*`.

Key frontend variables:

```env
API_BASE_URL=http://127.0.0.1:8000
NEXTAUTH_URL=http://127.0.0.1:3000
NEXTAUTH_SECRET=replace-with-a-strong-secret
```

The browser client calls the same-origin proxy path `/api/backend/*`. `API_BASE_URL` is read by the Next.js server at runtime and controls where that proxy forwards requests. This keeps public web images portable: do not bake deployment IPs into `NEXT_PUBLIC_*` variables.

Optional context overrides:

```env
NEXT_PUBLIC_DEFAULT_USER_ID=demo-user
NEXT_PUBLIC_DEFAULT_PROJECT_ID=demo-project
NEXT_PUBLIC_DEFAULT_ROLE=hr
NEXT_PUBLIC_DEFAULT_DEPARTMENT=HR
NEXT_PUBLIC_DEFAULT_CLEARANCE=1
NEXT_PUBLIC_DEFAULT_DATASET_TABLE=employees_wide
```

Agentic Query runs through the Claude Agent SDK, but defaults to DeepSeek's Anthropic-compatible endpoint. `AI_API_KEY` is passed to the SDK CLI as `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN`; `ANTHROPIC_BASE_URL` defaults to `https://api.deepseek.com/anthropic`; `AI_MODEL` defaults to `deepseek-chat`. If you need to override the Claude Code CLI token separately, set `ANTHROPIC_AUTH_TOKEN`.

---

## Agentic Query

The conversation entry always uses the agent orchestration path. The older rule-based chat path is no longer a runtime branch.

Agent configuration:

```env
CLAUDE_AGENT_SDK_ENABLED=true
AGENTIC_INGESTION_ENABLED=true
AGENT_MAX_TOOL_STEPS=20
AGENT_MAX_SQL_ROWS=2000
AGENT_MAX_SQL_SCAN_ROWS=10000
AGENT_TIMEOUT_SECONDS=120
```

The agent tool surface is limited to BI-related operations:

- `list_tables`
- `describe_table`
- `sample_rows`
- `get_metric_catalog`
- `run_semantic_query`
- `execute_readonly_sql`
- `get_distinct_values`
- `save_view`

At runtime, `conversation_id` maps to a resumable `agent_session_id`, and session state is persisted to `UPLOAD_DIR/state/agent_sessions.sqlite3`. All tool calls continue to reuse the existing SQL read-only validation, RLS injection, sensitive-field filtering, response redaction, and audit logging.

Current major events from `POST /chat/stream`:

- `planning`
- `tool_use`
- `tool_result`
- `spec`
- `final`
- `error`

Compatibility events: `reasoning`, `tool`

Design details are available in `docs/adr/0001-agentic-query-runtime.md`.

---

## API Overview

All business APIs except `/healthz` and `/auth/login` require `Authorization: Bearer <token>`. The frontend automatically calls `/auth/login` and caches the token.

| Method | Path | Description |
|---|---|---|
| `GET` | `/healthz` | Service health check |
| `POST` | `/auth/login` | Issue access token |
| `POST` | `/auth/roles/{user_id}` | Manage user role overrides |
| `GET` | `/audit/events` | Query audit events |
| `POST` | `/ingestion/uploads` | Upload Excel and create an Agentic ingestion job |
| `POST` | `/ingestion/plan` | Generate a write plan through the Write Ingestion Agent |
| `POST` | `/ingestion/approve` | Approve an agent write plan |
| `POST` | `/ingestion/execute` | Execute an approved write plan |
| `GET` | `/semantic/metrics` | Fetch semantic metric catalog |
| `POST` | `/semantic/query` | Run semantic query |
| `POST` | `/chat/tool-call` | Call BI tools directly |
| `POST` | `/chat/stream` | Stream AI conversation and chart generation |
| `POST` | `/views` | Save AI view |
| `GET` | `/views/{view_id}` | Read private view |
| `GET` | `/share/{view_id}` | Read shared view |
| `POST` | `/views/{view_id}/rollback/{version}` | Roll back a view version |

---

## End-to-End Validation

Local smoke flow:

```bash
make smoke-local
```

Covered workflow:

```text
healthz → auth/login → upload Excel → semantic query → chat stream → save view → share view
```

Full quality gate:

```bash
make test-all
```

Focused checks:

```bash
.venv/bin/python -m pytest tests -q
.venv/bin/python -m pytest tests/security -q
.venv/bin/python -m pytest tests/integration -q
npm run --prefix apps/web build
```

---

## Docker Delivery

Build and start:

```bash
docker compose up -d --build
docker compose ps
```

Runtime API routing:

- Browser requests go to the web origin, for example `http://localhost:3000/api/backend/jobs`.
- The web container forwards those requests to `API_BASE_URL`.
- In Docker Compose, set `API_BASE_URL=http://api:8000` for the web service. This is the default in the repository Compose files.

Example `.env` for a host reachable at `172.16.5.38`:

```env
TAG=1.0.1
API_BASE_URL=http://api:8000
APP_URL=http://172.16.5.38:3000
NEXTAUTH_URL=http://172.16.5.38:3000
CORS_ALLOW_ORIGINS=http://172.16.5.38:3000,http://localhost:3000
```

`CORS_ALLOW_ORIGINS` only needs the public web origin if you call the API directly from the browser. The built-in web UI normally avoids CORS by using the same-origin proxy.

Stop:

```bash
docker compose down --remove-orphans
```

Make wrappers:

```bash
make docker-up
make docker-down
make smoke-docker
```

Default Compose exposure:

- Web: `127.0.0.1:3000`
- API: `127.0.0.1:8000`

Uploads and state data are stored in the Docker named volume `cognitrix_upload_data`.

---

## Sample Data

Upload these files via the ingestion UI or `POST /ingestion/uploads` to create a working DuckDB session:

- `sample_data/hr_workforce_upload_sample.xlsx`
- `sample_data/hr_workforce_upload_sample_zh.xlsx`

After upload, use the returned `dataset_table` for subsequent semantic query and chat requests.

---

## Data Reset

Clear local runtime data, uploads, DuckDB / SQLite state, logs, and test artifacts:

```bash
make reset-local-data
```

Preview what will be deleted:

```bash
.venv/bin/python scripts/maintenance/reset_local_data.py --dry-run
```

Also reset the database referenced by `apps/api/.env`:

```bash
.venv/bin/python scripts/maintenance/reset_local_data.py --with-db-reset
```

Also remove Docker Compose named volumes:

```bash
.venv/bin/python scripts/maintenance/reset_local_data.py --include-docker-volumes
```

---

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on how to submit issues, propose features, and open pull requests.

---

## Known Boundaries

- Frontend session, workspace, and chart asset lists are still mock/localStorage based, and are not equivalent to backend-persisted objects. Browser refresh can restore local state, but switching devices or clearing cache will not sync it automatically.
- `ChatWorkbench` is still kept for testing/integration purposes, while the current main route renders `AppShell`.
- The default `NEXT_PUBLIC_DEFAULT_DATASET_TABLE=employees_wide` must align with the actual DuckDB session table. After uploading a new file, use the returned `dataset_table`.
- Agent mode has runtime and test coverage, but production model integration, evaluation set expansion, cost control, and long-session UX still need more iteration.
- Frontend test files and configuration exist, but `package.json` does not currently provide unified `npm test` / `test:ui` / `test:e2e` script entries. These should be organized before wiring them into `make test`.
