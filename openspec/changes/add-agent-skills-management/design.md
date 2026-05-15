## Context

Cognitrix agents (`AgentRuntime`, `ChartQueryAgent`, the ingestion agent inside `agentic_ingestion/`) are built on the Claude Agent SDK using `ClaudeSDKClient` + `ClaudeAgentOptions`. The SDK supports composable "Skills" — filesystem bundles consisting of an `SKILL.md` manifest and accompanying assets/scripts — that the model can autonomously invoke as tools. See `https://code.claude.com/docs/en/agent-sdk/skills` for the SDK contract.

Today the WriteIngestionAgent parses Excel uploads with hand-written Python (`agentic_ingestion/` schema inference, column inspection). This duplicates the functionality of Anthropic's official `xlsx` skill (`https://mcpservers.org/agent-skills/anthropic/xlsx`), is harder to keep current with edge cases (merged cells, multi-sheet, formula-bearing cells), and forces a code release for every parser fix.

We have no admin surface today. Only the `admin` role exists for workspace-level RBAC; there is no system-wide super-admin concept, and skills are not modeled at all.

Stakeholders:
- **Super-admin operator** (single or small set of accounts): wants to upload/replace skill packages without redeploying.
- **WriteIngestionAgent** (and future agents): consumes skills at runtime via the Claude Agent SDK.
- **Security**: skill bundles can contain executable code — must be sandboxed and authenticated tightly.
- **End users**: see no UI change; ingestion just gets more capable.

## Goals / Non-Goals

**Goals:**
- Provide a super-admin-only mechanism to upload, list, assign, enable/disable, and delete Claude Agent SDK skills, scoped per agent.
- Load assigned skills into the Claude Agent SDK runtime for each agent invocation so the model can use them as tools.
- Ship the Anthropic `xlsx` skill pre-installed and pre-assigned to `WriteIngestionAgent`, and retire the duplicated hand-written xlsx parsing path.
- Keep the management surface invisible to ordinary users (hidden route, RBAC-enforced).
- Bound the security risk of accepting executable skill bundles via validation, path-traversal protection, size limits, and SDK-managed execution.

**Non-Goals:**
- A general plug-in marketplace, automatic skill discovery from the internet, or skill version dependency resolution graph — manual upload/assign only.
- Per-user or per-workspace skill assignment — assignment is system-wide per agent.
- Replacing all hand-written tool code with skills — only the xlsx parsing path is migrated in this change.
- Multi-tenant skill isolation (each Cognitrix instance has one set of skills).
- Hot-reloading running agent loops mid-turn; new skill assignments take effect on the next turn.

## Decisions

### 1. Storage layout: filesystem bundles + SQLite metadata

Skills live on disk under `${UPLOAD_DIR}/agent_skills/<skill_id>/` after upload-time extraction. Metadata (id, name, version, sha256, uploaded_by, uploaded_at, status) and per-agent assignments live in a new `state/agent_skills.sqlite3` (or a new table in the existing state DB).

**Why**: The Claude Agent SDK expects skills as a directory; serving them straight from disk avoids re-extraction per turn. SQLite gives us cheap RBAC-checked queries and an audit trail. Alternative — keeping everything in DuckDB or a single tar blob — was rejected because the SDK loader works file-by-file and we'd just re-extract on every run.

### 2. Skill bundle format and validation

Accept `.zip` uploads only. On upload:
1. Reject if size > `AGENT_SKILLS_MAX_UPLOAD_MB` (default 25MB).
2. Stream-extract into a temp dir; reject any entry whose resolved path escapes the temp root (path-traversal guard).
3. Require a top-level `SKILL.md` with valid frontmatter (`name`, `description`, optional `version`).
4. Reject symlinks and entries with mode bits implying setuid/setgid.
5. Compute sha256 of the original zip; store alongside metadata.
6. Atomically move the validated tree to `${UPLOAD_DIR}/agent_skills/<uuid>/`.

**Why**: Skills are remote code; the upload surface is the single point we must harden. Zip is the format Anthropic distributes skills in and what the SDK docs reference.

### 3. RBAC: a new `superadmin` role with `skills:admin` scope

Extend `auth.py` with a `superadmin` role above the existing `admin` role. Add the `skills:admin` permission, granted only to `superadmin`. All `/admin/skills/**` routes use `require_permission("skills:admin")`.

Bootstrap: if `AUTH_BOOTSTRAP_SUPERADMIN_EMAIL` is set and the matching user exists, promote them on startup. Otherwise, the existing bootstrap admin is promoted to `superadmin` on first run if no `superadmin` exists yet (so we don't lock the operator out).

**Why**: `admin` today is workspace-scoped; conflating it with system-level skill management would let any workspace admin install code. A separate role keeps blast radius minimal. Alternative — environment-variable gating — was rejected because it can't survive a UI-driven workflow.

### 4. Loading skills into the Claude Agent SDK

In `agent_runtime.py` (and the ingestion equivalent), before instantiating `ClaudeAgentOptions`, look up assignments for the current agent's logical name (`WriteIngestionAgent`, `QueryAgent`, `ChartQueryAgent`) and pass their filesystem paths through the SDK's skill-loading mechanism (`setting_sources` / `agents=` per the SDK docs cited in the proposal). Cache the assignment list per agent in memory with a short TTL (e.g. 30s) to avoid SQLite reads every turn; bust the cache on any admin write.

**Why**: This is the path the SDK is designed for; we don't need to re-implement tool dispatch.

### 5. WriteIngestionAgent xlsx skill: pre-bundled at build/bootstrap

Ship Anthropic's xlsx skill as a vendored zip in `apps/api/vendor/skills/anthropic-xlsx-<version>.zip`. On API startup, if no skill with name `anthropic/xlsx` exists, install it from the vendored zip and create an assignment to `WriteIngestionAgent`.

The current hand-written xlsx parsing code in `agentic_ingestion/` is removed. The ingestion agent's system prompt is updated to reference the xlsx skill's tools instead of the deprecated in-process helpers.

**Why**: Vendoring guarantees deterministic bootstrap (no runtime fetch of remote zips, which would add a supply-chain attack surface and a network dependency at startup). Replacing the in-process parser eliminates a class of edge-case bugs we currently maintain.

### 6. Frontend: hidden `/admin/skills` route gated by role

Add a Next.js route at `/admin/skills`. The route checks the current user's role via the existing auth client; non-`superadmin` users get a 404-style "Not found" page (not 403 — we don't want to advertise the route's existence). The route is NOT linked from the global sidebar.

UI provides: skill list, upload form (drag-drop zip), per-skill detail (manifest preview, assignments), and per-agent assignment toggles.

**Why**: Hidden + RBAC is a common pattern for admin consoles; mirroring it avoids the user-onboarding-gate / workspace plumbing that ordinary panels live in.

### 7. Audit and observability

Every `/admin/skills` mutation emits an `audit.py` event (`actor`, `action`, `skill_id`, `agent_name`). Skill load failures at agent boot are logged but do NOT crash the agent — the agent runs without that skill and surfaces a warning to the super-admin in the next admin-console fetch.

## Risks / Trade-offs

- **Remote code execution surface**: Anyone with a `superadmin` token can upload arbitrary code that runs inside the agent process. → Mitigation: tight RBAC (one role, narrowly scoped), upload validation (zip-only, size cap, path-traversal guard, no symlinks), audit log on every action, recommend running the agent process under a restricted OS user. Document the threat model in the admin console.
- **Path-traversal / zip-slip in extraction**: → Mitigation: explicit `Path.resolve()` check against the destination root for every zip entry; reject any entry that escapes; reject entries with absolute paths.
- **Skill load failures**: A broken skill could brick `WriteIngestionAgent`. → Mitigation: load failures are caught per-skill; the agent continues with the remaining (good) skills and an explicit warning surfaces in the admin console.
- **Stale assignment cache**: A toggle in the admin UI might not take effect for an in-flight turn. → Mitigation: 30s TTL + explicit cache bust on writes; document that effect is "next turn."
- **Migration risk for WriteIngestionAgent**: Removing the hand-written xlsx parser changes ingestion behavior. → Mitigation: keep the legacy parser behind a feature flag `LEGACY_XLSX_PARSER_ENABLED` (default `false`) for one release; integration test runs full ingestion against the sample xlsx in `sample_data/` using the skill-backed path before deletion.
- **Vendored xlsx skill drift**: Anthropic ships skill updates; ours becomes stale. → Mitigation: vendored version recorded in `vendor/skills/VERSIONS.md`; super-admin can upload a newer version to replace it via the same UI, so we are not blocked on a code release to upgrade.
- **Supply chain (vendored zip)**: A poisoned commit of the vendored zip is a quiet RCE. → Mitigation: store the upstream sha256 of the Anthropic xlsx zip in source control alongside the vendored file; verify on every startup install; fail loud if it mismatches.

## Migration Plan

1. Ship the new schema, routes, and admin UI behind `AGENT_SKILLS_ENABLED=false` (default). Existing ingestion path unchanged.
2. Deploy; super-admins set `AGENT_SKILLS_ENABLED=true` and `AUTH_BOOTSTRAP_SUPERADMIN_EMAIL`.
3. On next start, bootstrap installs the vendored Anthropic xlsx skill and assigns it to `WriteIngestionAgent`.
4. Verify a real ingestion run goes through the skill-backed path (smoke test).
5. In the following release, flip `LEGACY_XLSX_PARSER_ENABLED` default to `false` and delete the hand-written parser code.

**Rollback**: Set `AGENT_SKILLS_ENABLED=false` (or `LEGACY_XLSX_PARSER_ENABLED=true` during the transition window). The vendored skill files stay on disk but are not loaded.
