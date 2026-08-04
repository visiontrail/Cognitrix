# Cognitrix — AI-Native 智能商业智能平台

[English](README.md) | 简体中文 | [日本語](README_JA.md)

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Node 20+](https://img.shields.io/badge/node-20%2B-green.svg)](https://nodejs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-15-black.svg)](https://nextjs.org/)
[![DuckDB](https://img.shields.io/badge/DuckDB-powered-yellow.svg)](https://duckdb.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

> **上传 Excel → 用自然语言提问 → 获取图表与分析看板。**
> 一个开源的 AI-Native 商业智能平台，把任意结构化表格变成可交互的分析工作台 —— 无需 SQL、无需数据仓库、无需预先搭建看板。

---

## Cognitrix 是什么？

**Cognitrix** 是一个面向结构化数据分析的 AI-Native BI 平台。它用一个懂业务问题、能自动生成图表的对话式 AI Agent，替代传统 BI 工具链（ETL 管道 + 固定看板 + SQL 门槛）。

与传统 BI 工具（Tableau、Power BI、Metabase）的核心差异：

| 能力 | 传统 BI | Cognitrix |
|---|---|---|
| 数据接入 | 数据仓库 + ETL | 直接上传 Excel |
| 查询方式 | 拖拽配置 / 手写 SQL | 自然语言对话 |
| 图表生成 | 手动配置 | AI 自动生成（Spec 驱动）|
| 即席分析 | 依赖分析师 | 业务人员自助，即时响应 |
| 访问控制 | 看板级别 | 行级别安全（RLS）+ 角色隔离 |
| 分享协作 | 静态链接 | 版本化视图，RBAC 权限门控 |

---

## 核心功能

- **自然语言分析（Natural Language Analytics）** — 直接提问"按部门看离职率""找出高风险项目"，即时获得图表、表格和业务洞察。
- **Excel 即席入库（Excel to Insights）** — 上传任意结构化表格，Agentic Ingestion 流程自动推断 Schema、解析列名，生成可查询的 DuckDB 数据集。
- **Agentic Query 引擎** — 基于 ReAct 循环（兼容 Claude/DeepSeek），Agent 自动探索表结构、选择语义指标、生成只读 SQL，全过程透明流式推送到 UI。
- **语义指标层（Semantic Metric Layer）** — YAML 驱动的指标定义，防止 AI 在计算业务 KPI 时产生幻觉（人员总数、离职率、项目 Velocity、预算消耗比等）。
- **AI 自动生成图表** — JSON Spec 流式输出，经 ECharts（热力图、Sankey、仪表盘、关系图）和 Recharts（柱状图、折线图、饼图、散点图、漏斗图、KPI 卡片）渲染。
- **可视化工作台与 Agent Canvas** — 在多格式画布中手工编排图表，或启用长任务 Agent，在用户确认多页看板大纲后持续生成整个仪表盘。
- **多图生成与 Saved Prompts** — 一次问题可生成一组经确认的图表；带变量和能力预设的 Prompt 可保存复用。
- **可靠持久化与协作** — 工作区、会话、消息、图表资产和画布快照均已服务端持久化；localStorage 作为快速离线缓存和旧数据迁移来源保留。
- **成员、邀请与发布** — 支持 owner/editor/viewer 角色、带期限的邀请链接，以及公开、仅注册用户、指定用户三种发布可见性，并提供只读公共助手。
- **版本化视图与分享** — 保存、版本化、回滚并按角色脱敏共享分析视图。
- **企业级安全** — JWT 鉴权、RBAC 权限范围、行级安全注入、SQL 只读校验、审计日志、越狱防护。
- **可选联网研究** — 受 Feature Flag 控制的博查或 Tavily 搜索/抓取工具具有明确的单轮预算，不绕过 BI 工具守卫。
- **运维管理后台** — superadmin 可管理运行配置、模型凭据、用户、角色、用量指标与 Agent Skills；Secret 只写不读。
- **Anthropic 兼容 Agent 运行时** — 默认使用 DeepSeek Anthropic 网关，也可通过环境配置切换到原生 Anthropic/Claude 或其他兼容端点。
- **自托管开源** — 本地或 Docker 部署，无云厂商绑定，无 SaaS 费用。

---

## 典型应用场景

- **HR 分析（HR Analytics）** — 人员编制、离职趋势、薪酬基准、绩效分布、部门钻取。
- **项目管理 BI（Project Management BI）** — Sprint Velocity、预算消耗率、任务完成率、资源利用率、风险热力图。
- **销售与营收** — 销售漏斗、赢率分析、配额完成率、区域对比（来自 CRM 导出的 Excel）。
- **财务与运营** — 成本中心拆解、预算对比、运营 KPI —— 均可从现有 Excel 报表直接加载。
- **管理驾驶舱** — 组合多图表工作台，保存为版本化视图，按权限分享给不同受众。

---

## 功能架构

[![Cognitrix 功能架构](docs/diagrams/functional-architecture-zh-cn.svg)](docs/diagrams/functional-architecture-zh-cn.html)

---

## 技术栈

| 层次 | 技术 |
|---|---|
| **后端** | FastAPI, Pydantic Settings, Python 3.11+ |
| **分析引擎** | DuckDB（进程内 OLAP），Pandas，sqlglot |
| **Agent 运行时** | Claude Agent SDK / Anthropic Messages 协议 |
| **前端** | Next.js 15 App Router, React 18, TypeScript |
| **状态管理** | Zustand, TanStack Query |
| **可视化** | ECharts, Recharts, React Flow |
| **认证与安全** | JWT, RBAC, 行级安全, SQL 只读校验 |
| **存储** | DuckDB（分析）, SQLite（状态）, 文件系统（上传）|
| **交付** | Docker Compose, Makefile |

---

## 快速开始

**环境要求：** Python 3.11+、Node.js 20+、npm 10+、GNU Make

```bash
# 1. 安装所有依赖，生成 .env 文件
make bootstrap

# 2. 校验环境变量
make env-check

# 3. 启动 API（8000 端口）和 Web（3000 端口）
make dev
```

打开 **http://127.0.0.1:3000** —— 上传示例 Excel 文件即可开始查询。

> 详细配置见 [本地配置](#本地配置) 章节。

---

## 后台管理

使用 `.env.example` 初始化的全新本地环境会内置一个开发用 superadmin：

- 邮箱：`admin@cognitrix.local`
- 密码：`Admin@123456`
- 后台入口：`http://127.0.0.1:3000/admin`

首次启动前可以覆盖 `AUTH_BOOTSTRAP_ADMIN_EMAIL`、
`AUTH_BOOTSTRAP_ADMIN_PASSWORD` 和 `AUTH_BOOTSTRAP_SUPERADMIN_EMAIL`；把这些值
设为空即可禁用引导账号。`APP_ENV=production` 时后端会拒绝文档中的默认密码。
后台支持 Agent Skills、全部已声明后端环境变量、模型与 API Key、注册用户以及
逐用户使用指标管理。敏感值只写不读，需要重启 API 的配置会在界面中明确标记。

## 当前进展

- 产品工作台已提供 Chat、Canvas、Split、Catalog 四种模式，快捷键为 `⌘/Ctrl + 1/2/3/4`；`⌘/Ctrl + B` 控制侧栏，分屏宽度可拖动或键盘调整。
- `POST /chat/stream` 会产生 `planning`、`tool_use`、`tool_result`、`spec`、`final`、`error`；可选 Agent Canvas 还会产生可恢复、有序的 `canvas_op`。`reasoning`、`tool` 兼容镜像仍保留。
- 画布支持图表、文本、便签、分隔线、Section 和分组节点；已实现多种页面/打印格式、背景、Web Design 网格、多页看板、导出、打印、自动保存和整次运行撤销。
- Conversations、Messages、Chart Assets、Workspace 元数据与 Canvas Snapshot 均已有服务端存储。浏览器会先加载本地缓存保证响应速度，再与服务端副本合并，实现跨设备恢复。
- 工作区协作已包含 owner/editor/viewer 成员角色、带期限邀请、硬删除清理，以及 `public`、`registered`、`allowlist` 三种发布可见性。
- 管理后台可控制配置、模型连通性、用户、角色、账号状态、用量指标和 Agent Skills。仓库的开发环境模板默认关闭 Agent Canvas、联网研究和运行时 Skill 加载，必须显式启用。
- 仓库包含后端、安全、集成、评测、性能、脚本、smoke、前端单元测试与 Playwright 覆盖。项目仍在持续演进，不应视为已经完成的企业正式版。

---

## 核心能力详解

### 把 Excel 变成可分析的数据资产

- 业务团队可以直接上传任意结构化表格（HR、销售、财务、运营等），无需先建数仓、写 SQL 或整理复杂模板。
- 系统会自动识别常见字段含义，合并多份表格，并产出可继续分析的数据集。
- 上传后会给出数据质量反馈，帮助团队判断这份数据是否完整、是否适合进一步分析。
- 内置可扩展的语义指标层（YAML 驱动），支持跨领域指标口径定义，让各类业务问题可以直接被理解和计算。

### 用对话完成即席分析（Conversational Analytics）

- 用户可以像问业务分析师一样提问，例如"按部门看离职率""找出高风险项目""展示入职年份分布"。
- Agent 会根据问题自动探索表结构、读取样例、选择语义指标或生成只读 SQL，减少人工反复试表和改口径。
- 对于标准指标，系统会优先使用稳定口径；对于临时问题，也能让 AI 分析助手完成更灵活的数据探索。
- 回答不仅给出结果，还会配套生成图表和简短结论，帮助用户快速判断下一步该看哪里。
- 多轮对话会保留 `agent_session_id` 和最近一次结构化结果，支持类似"改成折线图""再按部门拆一下"的追问。

### 从洞察到可视化工作台

- 对话中生成的图表可以沉淀为图表资产，继续放入工作台里组合、拖拽和整理。
- 用户可以在对话、画布、分屏和目录模式之间切换，把一次问答延展成可复用的分析看板。
- GenUI Catalog 已覆盖分组/负值柱状图、堆叠折线图、饼图、面积图、散点与聚类、雷达图、Treemap、单/多漏斗、表格、KPI 卡、热力图、仪表盘、Sankey、旭日图、箱线图、K 线图、关系图、地图、平行坐标和词云等常用及高级形式。
- 分析过程可以保留上下文，让后续追问、补充筛选和图表调整更自然。

### 让视图按权限被看见

- 关键分析可以保存为视图，并进入独立的展示入口，登录用户可读取自己或有权限访问的内容。
- 分享入口同样要求 Bearer 鉴权，并按调用者角色对保存的 AI state 做响应层脱敏。
- 发布后的工作区页面可以完全公开、仅限注册用户或仅限指定用户。旧版 Saved View 分享仍执行 owner/admin 与 `views:share` 权限规则。
- 同一份视图支持版本更新和回滚，适合持续迭代周报、项目复盘和管理驾驶舱。
- 上传、查询、分析操作、权限调整和回滚都会留下记录，方便团队追踪数据使用与分析过程。

---

## 目录结构

```text
.
├── apps/api              # FastAPI 后端（Agent 运行时、语义层、安全）
├── apps/web              # Next.js 前端（Chat、Workspace、Share、Catalog）
├── models                # HR / PM 语义指标定义（YAML）
├── sample_data           # 示例 Excel 数据（用于本地测试）
├── tests                 # 后端、集成、安全、评测、smoke 测试
├── scripts               # 开发/启动/发布入口与分组辅助脚本
│   ├── checks            # 环境校验、lint、build 检查
│   ├── maintenance       # 本地数据重置与一次性迁移脚本
│   ├── setup             # bootstrap 与本地服务初始化脚本
│   └── tests             # 测试与 smoke runner
├── deploy                # 服务器与 Hugging Face 部署文档/资产
├── docs/adr              # 架构决策记录
├── infra/docker          # 备用 Docker Compose 配置
├── openspec              # Change Proposal、Spec 与实现任务
└── packages/shared       # 共享包占位
```

---

## 环境要求

- Python 3.11+
- Node.js 20+
- npm 10+
- GNU Make
- Docker Desktop，可选，仅容器交付和 Docker smoke 需要

---

## 常用命令

```bash
make help              # 查看命令
make bootstrap         # 安装 Python / Web 依赖并初始化 .env
make env-check         # 校验 apps/api/.env 与 apps/web/.env
make dev               # 同时启动 API 和 Web
make dev-api           # 仅启动 FastAPI
make dev-web           # 仅启动 Next.js
make dev-local         # 调试模式启动，日志写入 logs/dev-local
make lint              # 后端 compileall + 前端 lint
make test              # 默认运行后端 pytest
make build             # 后端编译检查 + 前端生产构建
make smoke-local       # 本地端到端 smoke flow
make smoke-docker      # Docker 端到端 smoke flow
make test-all          # 预期完整门禁；当前限制见「已知边界」
make reset-local-data  # 清理本地运行数据
make docker-up         # 构建并启动 Docker Compose
make docker-down       # 停止 Docker Compose
make docker-publish    # 构建 API/Web 镜像并推送到 Docker Hub
make docker-start      # 启动/重建服务器栈并打印入口
make docker-restart    # 重建/重启但不删除持久化数据
make deploy            # 一键进行生产式服务器部署
make hf-deploy         # 部署到指定 Hugging Face Space
```

---

## 本地配置

`make bootstrap` 会在缺失时从模板生成：

- `apps/api/.env`
- `apps/web/.env`

后端关键变量：

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
AGENTIC_INGESTION_ENABLED=false
AGENT_CANVAS_MODE_ENABLED=false
WEB_SEARCH_ENABLED=false
AGENT_SKILLS_ENABLED=false
AUTH_SECRET=replace-with-a-strong-secret
UPLOAD_DIR=./data/uploads
CORS_ALLOW_ORIGINS=http://127.0.0.1:3000,http://localhost:3000
```

Excel 上传始终使用 Agentic Ingestion 生命周期。`AGENTIC_INGESTION_ENABLED` 仅为兼容旧环境文件保留，不再关闭 `/ingestion/*` 路由。

前端关键变量：

```env
API_BASE_URL=http://127.0.0.1:8000
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
NEXTAUTH_URL=http://127.0.0.1:3000
NEXTAUTH_SECRET=replace-with-a-strong-secret
```

浏览器端会请求同源代理路径 `/api/backend/*`。`API_BASE_URL` 是首选的纯运行时转发目标；本地 Bootstrap 模板中的 `NEXT_PUBLIC_API_BASE_URL` 作为兼容回退保留。这样公共 Web 镜像不会绑定部署机器 IP，也不需要把地址写进 `NEXT_PUBLIC_*` 构建变量。

前端对话默认上下文可通过这些可选变量调整：

```env
NEXT_PUBLIC_DEFAULT_USER_ID=demo-user
NEXT_PUBLIC_DEFAULT_PROJECT_ID=demo-project
NEXT_PUBLIC_DEFAULT_ROLE=hr
NEXT_PUBLIC_DEFAULT_DEPARTMENT=HR
NEXT_PUBLIC_DEFAULT_CLEARANCE=1
NEXT_PUBLIC_DEFAULT_DATASET_TABLE=employees_wide
```

Agentic Query 通过 Claude Agent SDK 运行，但默认接入 DeepSeek 的 Anthropic 兼容接口；`AI_API_KEY` 会传给 SDK CLI 作为 `ANTHROPIC_API_KEY` 与 `ANTHROPIC_AUTH_TOKEN`，`ANTHROPIC_BASE_URL` 默认指向 `https://api.deepseek.com/anthropic`，`AI_MODEL` 默认使用 `deepseek-chat`。如果需要单独覆盖 Claude Code CLI 的 token，可填写 `ANTHROPIC_AUTH_TOKEN`。

---

## Agentic Query

对话入口统一走 Agent 编排主路径，旧的规则式聊天链路不再作为运行时分支。

Agent 相关配置：

```env
CLAUDE_AGENT_SDK_ENABLED=true
AGENTIC_INGESTION_ENABLED=false
AGENT_CANVAS_MODE_ENABLED=false
AGENT_MAX_TOOL_STEPS=20
AGENT_MAX_SQL_ROWS=2000
AGENT_MAX_SQL_SCAN_ROWS=10000
AGENT_TIMEOUT_SECONDS=120
```

Agent 工具面限制在 BI 相关操作：

- `list_tables`
- `describe_table`
- `sample_rows`
- `get_metric_catalog`
- `run_semantic_query`
- `execute_readonly_sql`
- `get_distinct_values`
- `save_view`

启用联网研究后会增加 `web_search`、`web_fetch`、`save_web_research`。Agent Canvas 使用另一组受约束的画布工具并产生有序 `canvas_op`，不会因此获得任意文件系统或网络访问权限。

运行时会将 `conversation_id` 映射到可恢复的 `agent_session_id`，并把会话状态持久化到 `UPLOAD_DIR/state/agent_sessions.sqlite3`。所有工具调用仍复用现有 SQL 只读校验、RLS 注入、敏感字段过滤、响应脱敏和审计日志。

`POST /chat/stream` 当前主要事件：

- `planning`
- `tool_use`
- `tool_result`
- `spec`
- `final`
- `error`
- `canvas_op`（仅 Agent Canvas）

兼容事件：`reasoning`、`tool`

设计细节见 `docs/adr/0001-agentic-query-runtime.md`。

---

## API 概览

绝大多数业务 API 都需要 `Authorization: Bearer <token>`。注册和邮箱登录是公开入口；无凭据的旧版 `/auth/login` 仅供开发环境使用，生产环境会直接拒绝。前端会缓存登录会话并自动发送 Bearer token。

| Method | Path | 说明 |
|---|---|---|
| `GET` | `/healthz` | 服务健康检查 |
| `POST` | `/auth/register` | 注册邮箱密码账号 |
| `POST` | `/auth/email-login` | 登录账号 |
| `GET` | `/auth/me` | 获取当前身份 |
| `POST` | `/auth/roles/{user_id}` | 管理用户角色覆盖 |
| `GET` | `/audit/events` | 查询审计事件 |
| `POST` | `/ingestion/uploads` | 上传 Excel 并创建 Agentic ingestion job |
| `POST` | `/ingestion/plan` | 由 Write Ingestion Agent 生成写入方案 |
| `POST` | `/ingestion/setup/confirm` | 在需要时确认 Catalog 设置 |
| `POST` | `/ingestion/approve` | 审批 Agent 写入方案 |
| `POST` | `/ingestion/execute` | 执行已审批写入方案 |
| `GET` | `/semantic/metrics` | 获取语义指标目录 |
| `POST` | `/semantic/query` | 执行语义查询 |
| `POST` | `/chat/tool-call` | 直接调用 BI 工具 |
| `POST` | `/chat/stream` | 流式 AI 对话与图表生成 |
| `GET` | `/chat/capabilities` | 获取已启用的生成能力 |
| `GET/POST` | `/saved-prompts` | 列出或创建可复用 Prompt |
| `GET/POST` | `/workspaces` | 列出或创建工作区 |
| `POST` | `/workspaces/{workspace_id}/invites` | 创建工作区邀请 |
| `POST` | `/workspaces/{workspace_id}/publish` | 发布工作区页面 |
| `POST` | `/views` | 保存 AI view |
| `GET` | `/views/{view_id}` | 读取私有 view |
| `GET` | `/share/{view_id}` | 读取分享 view |
| `POST` | `/views/{view_id}/rollback/{version}` | 回滚 view 版本 |

---

## 端到端验证

本地 smoke flow：

```bash
make smoke-local
```

覆盖链路：

```text
healthz → auth/login → upload Excel → semantic query → chat stream → save view → share view
```

预期完整测试门禁（当前会被缺失的前端 `test` Package Script 阻断，见[已知边界](#已知边界)）：

```bash
make test-all
```

---

## Docker 交付

服务器部署用一条命令，无需事先准备 `.env`，也不需要模型 API Key：

```bash
PUBLIC_URL=http://172.16.5.38:3000 bash scripts/deploy.sh
```

`scripts/deploy.sh` 会生成随机 `AUTH_SECRET` / `NEXTAUTH_SECRET` 与随机超管口令，
启用 Agent Canvas，构建并启动全栈，等待健康检查，最后打印访问地址与登录凭据。模型 Key、联网检索、
Agent 参数等登录后在管理后台 `/admin` 配置，保存即生效。重复执行等于升级重启，
不会覆盖已有密钥或删除数据卷。运维完整说明见 [deploy/README.md](deploy/README.md)。

也可以手工构建并启动（需要自己准备一份合法的 `.env`）：

```bash
docker compose up -d --build
docker compose ps
```

运行时 API 路由：

- 浏览器请求 web 同源地址，例如 `http://localhost:3000/api/backend/jobs`。
- web 容器再把请求转发到 `API_BASE_URL`。
- Docker Compose 中 web 服务应设置 `API_BASE_URL=http://api:8000`，仓库内 Compose 文件已默认配置。

假设部署主机为 `172.16.5.38`，`.env` 示例：

```env
TAG=1.0.1
API_BASE_URL=http://api:8000
APP_URL=http://172.16.5.38:3000
NEXTAUTH_URL=http://172.16.5.38:3000
CORS_ALLOW_ORIGINS=http://172.16.5.38:3000,http://localhost:3000
```

只有浏览器直接访问 API 时才需要把公网 web origin 加入 `CORS_ALLOW_ORIGINS`。内置 web UI 默认通过同源代理访问 API，因此通常不会遇到浏览器 CORS。

停止：

```bash
docker compose down --remove-orphans
```

Make 包装命令：

```bash
make docker-up
make docker-down
make smoke-docker
```

默认 Compose 暴露：

- Web：`127.0.0.1:3000`
- API：`127.0.0.1:8000`

Compose 栈包含专用的 `cognitrix-storage` 服务，负责初始化并持有 named volume `cognitrix_upload_data`。API 是唯一的应用数据写入方；上传文件、DuckDB、SQLite 状态、审计日志、Agent Session、Saved View 与 Catalog Metadata 都保存在该卷中。正常启动、停止、重启和镜像重建不会传入 `--volumes`，因此不会删除这些数据。

---

## 示例数据

可用于本地上传验证的 Excel 样例：

- `sample_data/hr_workforce_upload_sample.xlsx`
- `sample_data/hr_workforce_upload_sample_zh.xlsx`
- `sample_data/sales_pipeline_sample.xlsx`
- `sample_data/finance_operations_sample.xlsx`
- `sample_data/project_management_sample.xlsx`

上传后，API 会返回 `batch_id`、`dataset_table`、`quality_report`、`diagnostics` 等信息。后续语义查询和对话请求需要使用返回的 `dataset_table`。

---

## 数据重置

预览将要清理的本地运行数据：

```bash
.venv/bin/python scripts/maintenance/reset_local_data.py --dry-run
```

执行本地重置：

```bash
make reset-local-data
```

只有显式使用 `--include-docker-volumes` 并确认后才会删除 Docker Compose 数据卷；普通 Restart/Start/Stop/Rebuild 流程均保留数据。

---

## 参与贡献

欢迎参与贡献！请阅读 [CONTRIBUTING.md](CONTRIBUTING.md) 了解提交 Issue、提议功能和发起 Pull Request 的相关规范。

---

## 已知边界

- Agent Canvas、联网研究和 Agent Skills 均受 Feature Flag 控制。开发模板默认全部关闭；`scripts/deploy.sh` 生成的服务器环境会启用 Agent Canvas。依赖外部供应商的可选能力仍需配置凭据与合适的运行限制。
- localStorage 仍是同步实时缓存，服务端同步采用 best-effort；网络临时失败时，某台设备可能保留仅本地副本，直到下一次成功提交或 Hydration。
- 模型质量、成本控制、长会话体验与领域评测覆盖仍需针对生产环境调优。
- Vitest 与 Playwright 测试已经存在，但 `apps/web/package.json` 暂未提供统一的 `npm test`、`test:ui`、`test:e2e` 脚本。
