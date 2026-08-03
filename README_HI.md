# Cognitrix — AI-Native BI और Analytics प्लेटफ़ॉर्म

[English](README.md) | [简体中文](README_CN.md) | हिन्दी | [Español](README_ES.md) | [日本語](README_JA.md)

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Node 20+](https://img.shields.io/badge/node-20%2B-green.svg)](https://nodejs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-15-black.svg)](https://nextjs.org/)
[![DuckDB](https://img.shields.io/badge/DuckDB-powered-yellow.svg)](https://duckdb.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

> **Excel अपलोड करें → सामान्य भाषा में प्रश्न पूछें → चार्ट और डैशबोर्ड पाएँ।**
> Cognitrix एक open-source, AI-native business intelligence प्लेटफ़ॉर्म है, जो structured spreadsheets को interactive analytics workspace में बदलता है—SQL, data warehouse या पहले से बने dashboard की आवश्यकता के बिना।

---

## Cognitrix क्या है?

Cognitrix पारंपरिक BI stack—ETL pipelines, स्थिर dashboards और SQL विशेषज्ञता—की जगह एक conversational AI agent देता है। Agent table schema को समझता है, semantic metrics चुनता है, सुरक्षित read-only SQL चलाता है और माँग के अनुसार charts बनाता है।

| क्षमता | पारंपरिक BI | Cognitrix |
|---|---|---|
| Data onboarding | Warehouse और ETL | सीधे Excel अपलोड |
| Query | Drag-and-drop या SQL | सामान्य भाषा में बातचीत |
| Chart creation | Manual configuration | AI-generated specifications |
| Ad-hoc analysis | Analyst पर निर्भर | Self-service |
| Access control | Dashboard स्तर | RBAC और row-level security |
| Collaboration | Static links | Durable workspaces, invites और publishing |

---

## प्रमुख विशेषताएँ

- **Natural Language Analytics** — workforce, project, sales, finance या operations data के बारे में प्रश्न पूछें और charts, tables तथा संक्षिप्त निष्कर्ष पाएँ।
- **Agentic Excel Ingestion** — workbook inspect करें, schema प्रस्ताव बनाएँ, catalog setup की पुष्टि करें, human approval लें और approved schema तक सीमित DuckDB write करें।
- **Agentic Query Engine** — Claude Agent SDK आधारित ReAct loop table structure खोजता है, semantic metrics चुनता है और केवल read-only SQL चलाता है।
- **Semantic Metric Layer** — YAML में परिभाषित metrics, जैसे headcount, attrition, velocity और budget burn, business KPI की गणना को स्थिर रखते हैं।
- **Rich Visualization** — ECharts advanced visualizations को और Recharts सामान्य charts, tables व KPI cards को render करता है।
- **Visual Workspace और Agent Canvas** — multi-format canvas पर charts को स्वयं व्यवस्थित करें, या optional Agent Canvas से स्वीकृत outline के आधार पर multi-page dashboard बनवाएँ।
- **Multi-Chart और Saved Prompts** — एक प्रश्न से पुष्टि की गई chart set बनाएँ और variables/capability presets वाले prompts दोबारा उपयोग करें।
- **Durable Collaboration** — workspace metadata, conversations, messages, chart assets और canvas snapshots server पर persist होते हैं; localStorage तेज़ cache और migration source बना रहता है।
- **Members, Invites और Publishing** — owner/editor/viewer roles, expiring invite links, तथा `public`, `registered` या `allowlist` visibility वाली published pages।
- **Security** — JWT, RBAC, RLS injection, sensitive-column redaction, read-only SQL validation, audit logging और jailbreak guardrails।
- **Optional Web Research** — feature-gated Bocha या Tavily tools, स्पष्ट per-turn limits के साथ।
- **Admin Control Plane** — runtime settings, model credentials, users, roles, account status, usage telemetry और Agent Skills का superadmin प्रबंधन। Secrets write-only रहते हैं।

---

## कार्यात्मक संरचना

[![Cognitrix कार्यात्मक संरचना](docs/diagrams/functional-architecture-hi.svg)](docs/diagrams/functional-architecture-hi.html)

### तकनीकी संरचना

| Layer | Technology |
|---|---|
| Backend | FastAPI, Pydantic Settings, Python 3.11+ |
| Analytics | DuckDB, Pandas, sqlglot |
| Agent Runtime | Claude Agent SDK, Anthropic Messages protocol |
| Frontend | Next.js 15, React 18, TypeScript |
| State | Zustand, TanStack Query |
| Visualization | ECharts, Recharts, React Flow |
| Security | JWT, RBAC, RLS, SQL validator |
| Storage | DuckDB, SQLite, filesystem और browser cache |

DeepSeek का Anthropic-compatible gateway default है। Native Anthropic/Claude या अन्य compatible endpoint environment settings से चुना जा सकता है।

---

## शीघ्र शुरुआत

आवश्यकताएँ: Python 3.11+, Node.js 20+, npm 10+ और GNU Make।

```bash
make bootstrap
make env-check
make dev
```

फिर [http://127.0.0.1:3000](http://127.0.0.1:3000) खोलें और `sample_data/` से Excel workbook अपलोड करें।

### स्थानीय admin account

`.env.example` से बने नए local development environment में default superadmin होता है:

- Email: `admin@cognitrix.local`
- Password: `Admin@123456`
- Console: `http://127.0.0.1:3000/admin`

पहली startup से पहले `AUTH_BOOTSTRAP_ADMIN_EMAIL`, `AUTH_BOOTSTRAP_ADMIN_PASSWORD` और `AUTH_BOOTSTRAP_SUPERADMIN_EMAIL` बदलें या खाली करके bootstrap बंद करें। `APP_ENV=production` में documented default password अस्वीकार कर दिया जाता है।

---

## वर्तमान स्थिति

- मुख्य workspace में Chat, Canvas, Split और Catalog modes हैं। Shortcuts: `Cmd/Ctrl + 1/2/3/4`; sidebar के लिए `Cmd/Ctrl + B`।
- Chat stream `planning`, `tool_use`, `tool_result`, `spec`, `final` और `error` events भेजता है। Agent Canvas चालू होने पर ordered, durable `canvas_op` events भी आते हैं।
- Canvas charts, text, sticky notes, dividers, sections और groups; अनेक page formats, backgrounds, web-design grids, multi-page dashboards, export, print, autosave और run-level undo को support करता है।
- Conversations, messages, assets और snapshots server-side persist होते हैं और cross-device hydration के दौरान local cache के साथ merge होते हैं।
- Repository का development template Agent Canvas, web research और runtime Agent Skills को default रूप से बंद रखता है; प्रत्येक के लिए स्पष्ट configuration आवश्यक है।
- Project में backend, security, integration, eval, performance, script, smoke, frontend unit और Playwright tests हैं; यह अभी भी सक्रिय रूप से विकसित product है।

---

## Repository संरचना

```text
.
├── apps/api              # FastAPI backend
├── apps/web              # Next.js frontend
├── models                # YAML semantic metrics
├── sample_data           # उदाहरण Excel workbooks
├── tests                 # Backend, security, integration, eval और smoke tests
├── scripts               # Setup, checks, tests, deploy और maintenance
├── deploy                # Server और Hugging Face deployment guide/assets
├── docs/adr              # Architecture decision records
├── infra/docker          # वैकल्पिक Compose configurations
├── openspec              # Change proposals, specs और implementation tasks
└── packages/shared       # Shared package placeholder
```

---

## सामान्य commands

```bash
make help              # उपलब्ध targets
make bootstrap         # Dependencies और .env files
make env-check         # Environment validation
make dev               # API और Web
make dev-api           # केवल FastAPI
make dev-web           # केवल Next.js
make lint              # Compile/lint checks
make test              # Backend pytest suite
make build             # Production web build + backend compile check
make smoke-local       # Local end-to-end smoke flow
make test-all          # नियोजित full gate; वर्तमान सीमा नीचे देखें
make docker-up         # Compose stack शुरू करें
make docker-down       # Compose stack रोकें
make docker-publish    # API/Web images build करके Docker Hub पर push करें
make docker-restart    # Data बचाते हुए rebuild/restart
make deploy            # One-command server deployment
make hf-deploy         # Hugging Face Space deployment
make reset-local-data  # Local runtime data साफ़ करें
```

---

## Configuration

`make bootstrap` अनुपस्थित होने पर `apps/api/.env` और `apps/web/.env` बनाता है। मुख्य backend settings:

```env
DATABASE_URL=sqlite:///./data/uploads/state/ai_views.sqlite3
MODEL_PROVIDER_URL=https://api.deepseek.com
AI_API_KEY=
AI_MODEL=deepseek-chat
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
ANTHROPIC_AUTH_TOKEN=
CLAUDE_AGENT_SDK_ENABLED=true
AGENTIC_INGESTION_ENABLED=false
AGENT_CANVAS_MODE_ENABLED=false
WEB_SEARCH_ENABLED=false
AGENT_SKILLS_ENABLED=false
AUTH_SECRET=replace-with-a-strong-secret
UPLOAD_DIR=./data/uploads
CORS_ALLOW_ORIGINS=http://127.0.0.1:3000,http://localhost:3000
```

Excel upload हमेशा Agentic Ingestion lifecycle का उपयोग करता है। `AGENTIC_INGESTION_ENABLED` केवल पुराने environment files के compatibility के लिए रखा गया है और `/ingestion/*` routes को बंद नहीं करता।

Web server browser requests को same-origin `/api/backend/*` proxy से API तक भेजता है। Runtime destination के लिए `API_BASE_URL` उपयोग करें; local bootstrap template में `NEXT_PUBLIC_API_BASE_URL` fallback के रूप में रहता है। Public deployment IP को `NEXT_PUBLIC_*` build variables में bake न करें।

---

## Agent runtime और ingestion

Base BI tools:

- `list_tables`
- `describe_table`
- `sample_rows`
- `get_metric_catalog`
- `run_semantic_query`
- `execute_readonly_sql`
- `get_distinct_values`
- `save_view`

Web research चालू करने पर `web_search`, `web_fetch` और `save_web_research` जुड़ते हैं। Agent Canvas की tool surface अलग और constrained है; यह arbitrary filesystem या network access नहीं देती।

Ingestion lifecycle:

1. `POST /ingestion/uploads`
2. `POST /ingestion/plan`
3. `POST /ingestion/setup/confirm`, यदि आवश्यक हो
4. `POST /ingestion/approve`
5. `POST /ingestion/execute`

प्रत्येक write केवल approved schema तक सीमित होता है। Identifiers और DuckDB type names strict allowlists से validate होते हैं।

---

## Accounts, collaboration और publishing

- Email/password registration: `POST /auth/register`
- Login: `POST /auth/email-login`
- Workspace members: owner, editor और viewer
- Invites: expiring links, जिन्हें authenticated user स्वीकार करता है
- Publishing: `public`, `registered` और `allowlist` visibility
- Published route: `/p/{token}`
- Legacy saved views: versioning, rollback और permission-aware `/share/{view_id}`

Credential-free legacy `POST /auth/login` केवल development में उपलब्ध है और production में अस्वीकार होता है।

---

## Testing और deployment

```bash
.venv/bin/python -m pytest tests -q
.venv/bin/python -m pytest tests/security -q
cd apps/web && npx vitest run
cd apps/web && npx playwright test
make smoke-local
```

One-command server deployment:

```bash
PUBLIC_URL=http://172.16.5.38:3000 bash scripts/deploy.sh
```

Script secrets और random superadmin password बनाता है, Agent Canvas चालू करता है, stack build/start करता है, health checks की प्रतीक्षा करता है और credentials print करता है। दोबारा चलाने पर persistent Docker volume हटाया नहीं जाता। अधिक जानकारी: [deploy/README.md](deploy/README.md)।

---

## Sample data और reset

`sample_data/` में HR, sales, finance, project-management और linked-table workbooks हैं, जिनमें English तथा Chinese samples शामिल हैं। Upload के बाद returned `dataset_table` को query/chat context में उपयोग करें।

Local data reset का preview:

```bash
.venv/bin/python scripts/maintenance/reset_local_data.py --dry-run
```

वास्तविक local reset के लिए `make reset-local-data` चलाएँ। Docker volumes केवल स्पष्ट `--include-docker-volumes` option और confirmation से हटते हैं; सामान्य start, stop, restart या rebuild data volume नहीं हटाते।

---

## ज्ञात सीमाएँ

- localStorage synchronous live cache है; server sync best-effort है। अस्थायी network failure के बाद device-local copy अगली सफल commit या hydration तक रह सकती है।
- Optional agent features के लिए provider credentials और production-specific limits आवश्यक हैं।
- Model quality, cost control, long-session UX और domain evaluation coverage को deployment के अनुसार tune करना होगा।
- Vitest और Playwright suites मौजूद हैं, लेकिन `apps/web/package.json` अभी unified `npm test`, `test:ui` या `test:e2e` scripts नहीं देता।

---

## योगदान

Issue, feature proposal और pull request guidelines के लिए [CONTRIBUTING.md](CONTRIBUTING.md) पढ़ें। Cognitrix MIT License के अंतर्गत उपलब्ध है।
