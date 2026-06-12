## 1. Config & feature flags

- [x] 1.1 Add `AGENT_SKILLS_ENABLED` (default `false`), `AGENT_SKILLS_DIR` (default `${UPLOAD_DIR}/agent_skills`), `AGENT_SKILLS_MAX_UPLOAD_MB` (default `25`), `LEGACY_XLSX_PARSER_ENABLED` (default `true`), `AUTH_BOOTSTRAP_SUPERADMIN_EMAIL` (optional) to `apps/api/config.py` `Settings`
- [x] 1.2 Update `apps/api/.env.example` with the new vars and inline comments
- [x] 1.3 Update `make env-check` script (in `scripts/checks/`) to validate the new vars when `AGENT_SKILLS_ENABLED=true`

## 2. RBAC: superadmin role

- [x] 2.1 Add `superadmin` role and `skills:admin` permission scope to `apps/api/auth.py`
- [x] 2.2 Implement `AUTH_BOOTSTRAP_SUPERADMIN_EMAIL` promotion on startup in `apps/api/main.py` (or wherever bootstrap currently runs)
- [x] 2.3 On first run, if no `superadmin` exists, auto-promote the existing bootstrap admin so the operator is never locked out
- [x] 2.4 Unit test: `tests/security/test_superadmin_rbac.py` — non-superadmin denied, superadmin allowed, env-var promotion path

## 3. Skill storage layer

- [x] 3.1 Create `apps/api/agent_skills/` module with `registry.py` (SQLite-backed metadata + assignments)
- [x] 3.2 Define SQLite schema: `agent_skills` (id, name, version, sha256, status, uploaded_by, uploaded_at, manifest_json, load_error) and `agent_skill_assignments` (skill_id, agent_name, assigned_by, assigned_at)
- [x] 3.3 Implement migrations / table-create-if-missing on startup (mirroring existing `state/*.sqlite3` patterns)
- [x] 3.4 Implement registry CRUD: list, get, upsert, set_status, delete, list_assignments_for_agent, assign, unassign
- [x] 3.5 Unit test: `tests/unit/test_agent_skills_registry.py`

## 4. Skill bundle validator & extractor

- [x] 4.1 Implement `agent_skills/validator.py`: size check, zip-only check, path-traversal guard (resolve every entry against destination root), symlink rejection, absolute-path rejection
- [x] 4.2 Implement `agent_skills/manifest.py`: parse `SKILL.md` frontmatter, require `name` + `description`, optional `version`
- [x] 4.3 Implement `agent_skills/installer.py`: validate → extract to temp → atomically move to `${AGENT_SKILLS_DIR}/<uuid>/` → upsert registry row → return skill id
- [x] 4.4 Compute sha256 of original zip and persist
- [x] 4.5 Unit test: `tests/unit/test_agent_skills_validator.py` — oversize, path-traversal (zip-slip), absolute-path entry, symlink, missing SKILL.md, malformed frontmatter, happy path
- [x] 4.6 Security test: `tests/security/test_agent_skills_upload_sandbox.py` — confirm no file written outside `${AGENT_SKILLS_DIR}/<uuid>/` even for malicious zips

## 5. Admin API surface

- [x] 5.1 Create `apps/api/admin_skills.py` router, all routes guarded by `require_permission("skills:admin")`
- [x] 5.2 `POST /admin/skills` — multipart upload, calls installer, returns skill row
- [x] 5.3 `GET /admin/skills` — list installed skills with status, assignments, last `load_error`
- [x] 5.4 `GET /admin/skills/{skill_id}` — single skill + parsed manifest
- [x] 5.5 `PATCH /admin/skills/{skill_id}` — toggle `status` between `enabled`/`disabled`
- [x] 5.6 `DELETE /admin/skills/{skill_id}` — delete bundle dir + assignments + row
- [x] 5.7 `POST /admin/skills/{skill_id}/assignments` body `{ "agent_name": ... }`, validates against registered agent names
- [x] 5.8 `DELETE /admin/skills/{skill_id}/assignments/{agent_name}`
- [x] 5.9 `GET /admin/skills/agents/{agent_name}` — assignments for an agent
- [x] 5.10 Mount router in `apps/api/main.py` behind `AGENT_SKILLS_ENABLED`
- [x] 5.11 API tests: `tests/api/test_admin_skills.py` — RBAC, happy paths for every endpoint, unknown agent rejection

## 6. Audit events

- [x] 6.1 Add audit event types to `apps/api/audit.py`: `skill_upload`, `skill_upload_rejected`, `skill_enable`, `skill_disable`, `skill_delete`, `skill_assign`, `skill_unassign`, `skill_bootstrap_install`, `superadmin_promote`
- [x] 6.2 Wire each admin route + the bootstrap installer to emit the corresponding event
- [x] 6.3 Unit test: `tests/unit/test_agent_skills_audit.py`

## 7. Runtime integration with Claude Agent SDK

- [x] 7.1 Add named-agent registry: a constant list of known agent names (`WriteIngestionAgent`, `QueryAgent`, `ChartQueryAgent`) used by both the API and the runtime
- [x] 7.2 Implement `agent_skills/loader.py` `load_skills_for_agent(agent_name) -> list[Path]`, reading registry, filtering by `status=enabled`, returning filesystem paths
- [x] 7.3 Add 30-second TTL in-memory cache; invalidate on any admin write
- [x] 7.4 Wire `apps/api/agent_runtime.py` to pass loaded skill paths into `ClaudeAgentOptions` per Claude Agent SDK skill-loading docs
- [x] 7.5 Wire `apps/api/agentic_ingestion/` ingestion agent invocation the same way for `WriteIngestionAgent`
- [x] 7.6 Wire `apps/api/chart_query_agent.py` the same way for `ChartQueryAgent`
- [x] 7.7 Catch and persist per-skill load failures into `agent_skills.load_error`; do not crash the agent
- [x] 7.8 Integration test: `tests/integration/test_agent_runtime_skills.py` — assigned skill is loaded; disabled skill is skipped; broken skill does not crash

## 8. Vendored Anthropic xlsx skill

- [ ] 8.1 Download Anthropic xlsx skill zip from `https://mcpservers.org/agent-skills/anthropic/xlsx` and place at `apps/api/vendor/skills/anthropic-xlsx-<version>.zip` (PENDING — operator must drop the zip in; bootstrap then picks it up automatically)
- [x] 8.2 Record upstream sha256 and version in `apps/api/vendor/skills/VERSIONS.md` (template in place; operator fills `Version` + `Upstream sha256` lines after vendoring the real zip)
- [x] 8.3 Implement bootstrap routine: on startup, if `AGENT_SKILLS_ENABLED=true` and no skill named `anthropic/xlsx` exists, verify sha256 of vendored zip, install via the installer, and assign to `WriteIngestionAgent`
- [x] 8.4 Make bootstrap idempotent (skip when present, no duplicate assignment)
- [x] 8.5 Fail-loud-but-not-crash on sha256 mismatch (log, skip install, surface in `/admin/skills`)
- [x] 8.6 Integration test: `tests/integration/test_xlsx_skill_bootstrap.py`

## 9. Migrate WriteIngestionAgent to xlsx skill

- [x] 9.1 Update `apps/api/agentic_ingestion/` ingestion agent system prompt to reference xlsx skill tools instead of hand-written parser
- [x] 9.2 Add `LEGACY_XLSX_PARSER_ENABLED` branch: when `true` (default for now), retain old code path; when `false`, route entirely through the skill
- [x] 9.3 Integration test: `tests/integration/test_write_ingestion_via_xlsx_skill.py` — full ingestion lifecycle (`/ingestion/uploads` → `/ingestion/plan` → `/ingestion/approve` → `/ingestion/execute`) on `sample_data/hr_workforce_upload_sample.xlsx` with `LEGACY_XLSX_PARSER_ENABLED=false`
- [x] 9.4 Deprecation TODO comment on the hand-written parser, scheduled for removal in the next release per `design.md` migration plan

## 10. Frontend admin console

- [x] 10.1 Extend `apps/web/lib/auth/` to expose the current user's role and a `useIsSuperadmin()` hook
- [x] 10.2 Add Next.js route `apps/web/app/admin/skills/page.tsx`; render generic "Not found" for non-superadmin (no leakage)
- [x] 10.3 Build `AdminSkillsPage` component: upload (drag-drop zip), table of installed skills, manifest preview drawer, enable/disable toggle, per-agent assignment checkboxes, delete confirm modal
- [x] 10.4 Create `apps/web/lib/admin/skills.ts` API client wrapping the `/admin/skills` endpoints
- [x] 10.5 Ensure no link to `/admin/skills` is added to the global sidebar
- [x] 10.6 Frontend unit test: `apps/web/tests/ui/admin-skills.test.tsx` (Vitest, jsdom) — role gating, upload happy path, assignment toggle
- [x] 10.7 i18n: add admin-console strings to `apps/web/lib/i18n/dictionary.ts` (en + zh)

## 11. Documentation

- [x] 11.1 Update `CLAUDE.md` "Architecture" section with the `agent_skills/` module and admin route
- [x] 11.2 Update `CLAUDE.md` "Key Configuration" with new env vars
- [x] 11.3 Add a short "Agent Skills (super-admin)" section to `CLAUDE.md` describing bootstrap, upload, and the xlsx-skill migration
- [x] 11.4 Update `apps/api/.env.example` (already in 1.2) — verify final wording

## 12. Smoke & gate

- [x] 12.1 Extend `tests/smoke/run_smoke_flow.py` with an optional `--with-skills` mode that exercises the bootstrap-installed xlsx skill end-to-end
- [ ] 12.2 Run `make test-all` and ensure full gate passes (PENDING — change-scoped pytest set (81 tests) all pass; full repo gate still depends on operator-side env / vendored zip / LLM connectivity)
- [ ] 12.3 Manual verification: start the stack with `AGENT_SKILLS_ENABLED=true`, log in as superadmin, upload a second skill, assign to `QueryAgent`, confirm via API and UI (PENDING — operator task, requires running stack)
