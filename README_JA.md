# Cognitrix — AI-Native BI・アナリティクスプラットフォーム

[English](README.md) | [简体中文](README_CN.md) | [हिन्दी](README_HI.md) | [Español](README_ES.md) | 日本語

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Node 20+](https://img.shields.io/badge/node-20%2B-green.svg)](https://nodejs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-15-black.svg)](https://nextjs.org/)
[![DuckDB](https://img.shields.io/badge/DuckDB-powered-yellow.svg)](https://duckdb.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

> **Excel をアップロード → 自然言語で質問 → チャートとダッシュボードを生成。**
> Cognitrix は、構造化されたスプレッドシートをインタラクティブな分析ワークスペースへ変換する、オープンソースの AI-native BI プラットフォームです。SQL、データウェアハウス、事前構築済みダッシュボードは必要ありません。

---

## Cognitrix とは

Cognitrix は、ETL パイプライン、固定ダッシュボード、SQL の専門知識から成る従来型 BI スタックを、対話型 AI Agent で置き換えます。Agent はテーブルスキーマを把握し、セマンティック指標を選択し、安全な読み取り専用 SQL を実行して、必要な可視化をその場で生成します。

| 機能 | 従来型 BI | Cognitrix |
|---|---|---|
| データ導入 | Warehouse + ETL | Excel を直接アップロード |
| クエリ | Drag-and-drop / SQL | 自然言語で対話 |
| チャート作成 | 手動設定 | AI が Spec を生成 |
| アドホック分析 | アナリストに依存 | セルフサービス |
| アクセス制御 | ダッシュボード単位 | RBAC + 行レベルセキュリティ |
| コラボレーション | 静的リンク | 永続 Workspace、招待、公開 |

---

## 主な機能

- **自然言語分析** — 人事、プロジェクト、営業、財務、オペレーションのデータについて質問し、チャート、テーブル、簡潔な要点を得られます。
- **Agentic Excel Ingestion** — Workbook の検査、スキーマ提案、Catalog 設定確認、人による承認を経て、承認済みスキーマだけに DuckDB への書き込みを制限します。
- **Agentic Query Engine** — Claude Agent SDK ベースの ReAct loop がテーブルを探索し、セマンティック指標を選び、読み取り専用 SQL のみを実行します。
- **セマンティック指標レイヤー** — YAML 定義の指標により、Headcount、Attrition、Velocity、Budget burn などの KPI 計算を安定させます。
- **高度な可視化** — ECharts が複雑な可視化を、Recharts が一般的なチャート、テーブル、KPI カードを描画します。
- **Visual Workspace と Agent Canvas** — 複数フォーマット対応 Canvas に手動でチャートを配置するほか、任意機能の Agent Canvas が承認済み Outline から複数ページのダッシュボードを構築できます。
- **Multi-Chart と Saved Prompts** — 1 つの質問から確認済みのチャート群を生成し、変数や Capability preset を持つ Prompt を再利用できます。
- **永続的なコラボレーション** — Workspace、会話、メッセージ、Chart Asset、Canvas Snapshot はサーバーに保存されます。localStorage は高速 Cache と Migration source として残ります。
- **メンバー、招待、公開** — owner/editor/viewer Role、期限付き招待リンク、`public`・`registered`・`allowlist` の公開 Visibility を備えます。
- **セキュリティ** — JWT、RBAC、RLS injection、機密列の Redaction、読み取り専用 SQL 検証、監査ログ、Jailbreak Guardrail。
- **任意の Web Research** — Feature Flag で保護された Bocha / Tavily Tool に、Turn ごとの明示的な上限を設定します。
- **管理 Control Plane** — Superadmin が Runtime 設定、Model Credential、User、Role、Account status、Usage telemetry、Agent Skills を管理します。Secret は書き込み専用です。

---

## 機能アーキテクチャ

[![Cognitrix 機能アーキテクチャ](docs/diagrams/functional-architecture-ja.svg)](docs/diagrams/functional-architecture-ja.html)

### 技術スタック

| レイヤー | 技術 |
|---|---|
| Backend | FastAPI, Pydantic Settings, Python 3.11+ |
| Analytics | DuckDB, Pandas, sqlglot |
| Agent Runtime | Claude Agent SDK, Anthropic Messages protocol |
| Frontend | Next.js 15, React 18, TypeScript |
| State | Zustand, TanStack Query |
| Visualization | ECharts, Recharts, React Flow |
| Security | JWT, RBAC, RLS, SQL Validator |
| Storage | DuckDB, SQLite, Filesystem, Browser Cache |

既定の Provider は DeepSeek の Anthropic-compatible gateway です。環境変数により、Native Anthropic/Claude または別の互換 Endpoint を選択できます。

---

## クイックスタート

必要環境: Python 3.11+、Node.js 20+、npm 10+、GNU Make。

```bash
make bootstrap
make env-check
make dev
```

[http://127.0.0.1:3000](http://127.0.0.1:3000) を開き、`sample_data/` にある Excel Workbook をアップロードします。

### ローカル管理者アカウント

`.env.example` から作成した新しいローカル開発環境には、次の Superadmin が用意されます。

- Email: `admin@cognitrix.local`
- Password: `Admin@123456`
- Console: `http://127.0.0.1:3000/admin`

初回起動前に `AUTH_BOOTSTRAP_ADMIN_EMAIL`、`AUTH_BOOTSTRAP_ADMIN_PASSWORD`、`AUTH_BOOTSTRAP_SUPERADMIN_EMAIL` を変更するか、空にして Bootstrap を無効化してください。`APP_ENV=production` では、この文書に記載した既定 Password は拒否されます。

---

## 現在の状態

- メイン Workspace は Chat、Canvas、Split、Catalog の各 Mode を提供します。Shortcut は `Cmd/Ctrl + 1/2/3/4`、Sidebar の切り替えは `Cmd/Ctrl + B` です。
- Chat Stream は `planning`、`tool_use`、`tool_result`、`spec`、`final`、`error` を送信します。Agent Canvas を有効化すると、順序付きで永続化された `canvas_op` も追加されます。
- Canvas は Chart、Text、Sticky note、Divider、Section、Group に対応します。複数の Page format、Background、Web-design grid、複数ページ Dashboard、Export、Print、Autosave、Run 単位の Undo も実装済みです。
- Conversation、Message、Asset、Snapshot はサーバーに永続化され、Cross-device hydration 時に Local Cache と Merge されます。
- Repository の開発 Template は Agent Canvas、Web Research、Runtime Agent Skills を既定で無効化しており、それぞれ明示的な設定が必要です。
- Backend、Security、Integration、Evaluation、Performance、Script、Smoke、Frontend unit、Playwright の Test を備えています。製品は現在も継続的に開発されています。

---

## Repository 構成

```text
.
├── apps/api              # FastAPI Backend
├── apps/web              # Next.js Frontend
├── models                # YAML Semantic metrics
├── sample_data           # Excel Sample workbooks
├── tests                 # Backend, Security, Integration, Eval, Smoke tests
├── scripts               # Setup, Checks, Tests, Deploy, Maintenance
├── deploy                # Server / Hugging Face Deploy のガイドと Asset
├── docs/adr              # Architecture Decision Records
├── infra/docker          # 代替 Compose configurations
├── openspec              # Change proposal、Spec、実装 Task
└── packages/shared       # Shared package placeholder
```

---

## よく使うコマンド

```bash
make help              # 利用可能な Target
make bootstrap         # Dependency と .env file を準備
make env-check         # 環境変数を検証
make dev               # API と Web を起動
make dev-api           # FastAPI のみ起動
make dev-web           # Next.js のみ起動
make lint              # Compile / Lint check
make test              # Backend pytest suite
make build             # Production web build + Backend compile check
make smoke-local       # Local end-to-end smoke flow
make test-all          # 想定 Full gate。現在の制約は下記参照
make docker-up         # Compose stack を起動
make docker-down       # Compose stack を停止
make docker-publish    # API/Web Image を Build して Docker Hub へ Push
make docker-restart    # Data を保持して Rebuild / Restart
make deploy            # 1 コマンドで Server deploy
make hf-deploy         # Hugging Face Space へ Deploy
make reset-local-data  # Local runtime data を消去
```

---

## 設定

`make bootstrap` は、存在しない場合に `apps/api/.env` と `apps/web/.env` を作成します。主な Backend 設定:

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

Excel Upload は常に Agentic Ingestion lifecycle を使用します。`AGENTIC_INGESTION_ENABLED` は古い環境との互換性のためだけに残されており、`/ingestion/*` Route を無効化しません。

Web server は、同一 Origin の `/api/backend/*` Proxy 経由で Browser request を API へ転送します。Runtime の転送先には `API_BASE_URL` を使用し、Local bootstrap template の `NEXT_PUBLIC_API_BASE_URL` は Fallback として残ります。Deploy 先 IP を Build 時の `NEXT_PUBLIC_*` 変数へ埋め込まないでください。

---

## Agent Runtime と Ingestion

基本 BI Tool:

- `list_tables`
- `describe_table`
- `sample_rows`
- `get_metric_catalog`
- `run_semantic_query`
- `execute_readonly_sql`
- `get_distinct_values`
- `save_view`

Web Research を有効化すると `web_search`、`web_fetch`、`save_web_research` が追加されます。Agent Canvas は別の制約付き Tool surface を使い、任意の Filesystem / Network access は取得しません。

Ingestion lifecycle:

1. `POST /ingestion/uploads`
2. `POST /ingestion/plan`
3. 必要な場合は `POST /ingestion/setup/confirm`
4. `POST /ingestion/approve`
5. `POST /ingestion/execute`

すべての書き込みは承認済み Schema に限定されます。Identifier と DuckDB Type name は厳格な Allowlist で検証されます。

---

## アカウント、コラボレーション、公開

- 登録: `POST /auth/register`
- Login: `POST /auth/email-login`
- Workspace member: owner、editor、viewer
- 招待: 認証済み User が受け取る期限付き Link
- 公開: `public`、`registered`、`allowlist` Visibility
- 公開 Route: `/p/{token}`
- Legacy Saved view: Versioning、Rollback、Permission-aware `/share/{view_id}`

Credential を要求しない Legacy `POST /auth/login` は開発環境専用であり、本番環境では拒否されます。

---

## テストとデプロイ

```bash
.venv/bin/python -m pytest tests -q
.venv/bin/python -m pytest tests/security -q
cd apps/web && npx vitest run
cd apps/web && npx playwright test
make smoke-local
```

1 コマンドで Server deploy:

```bash
PUBLIC_URL=http://172.16.5.38:3000 bash scripts/deploy.sh
```

Script は Secret とランダムな Superadmin Password を生成し、Agent Canvas を有効化し、Stack を Build / Start して Health check を待ち、URL と Credential を表示します。再実行しても永続 Docker volume は削除されません。詳しくは [deploy/README.md](deploy/README.md) を参照してください。

---

## Sample data と Reset

`sample_data/` には、人事、営業、財務、Project management、Linked table 用の Workbook があり、英語・中国語の Sample を含みます。Upload 後は、返された `dataset_table` を Query / Chat context に使用してください。

Local reset の対象を Preview:

```bash
.venv/bin/python scripts/maintenance/reset_local_data.py --dry-run
```

実際の Local reset は `make reset-local-data` で実行します。Docker volume が削除されるのは、明示的な `--include-docker-volumes` Option と確認を使った場合だけです。通常の Start、Stop、Restart、Rebuild は Data を保持します。

---

## 既知の制約

- localStorage は同期 Live Cache であり、Server sync は Best-effort です。一時的な Network failure により、次の正常な Commit / Hydration まで Device-local copy が残る場合があります。
- 任意の Agent 機能には Provider credential と本番向けの適切な上限設定が必要です。
- Model quality、Cost control、Long-session UX、Domain evaluation coverage は Deploy 環境ごとに調整が必要です。
- Vitest / Playwright suite はありますが、`apps/web/package.json` は統一された `npm test`、`test:ui`、`test:e2e` Script をまだ公開していません。

---

## コントリビューション

Issue、機能提案、Pull request のガイドラインは [CONTRIBUTING.md](CONTRIBUTING.md) を参照してください。Cognitrix は MIT License で提供されます。
