## Context

Cognitrix is a single FastAPI/Next.js deployment backed by SQLite application state and per-session DuckDB files. Email/password authentication already supports role overrides, and Agent Skills already have a superadmin-only API and runtime registry. Configuration is currently loaded once through Pydantic Settings from `apps/api/.env`; user lifecycle controls and usage aggregation do not exist.

The administration surface is security-sensitive and cross-cutting. It must remain usable in the local single-process deployment, avoid exposing credentials, and preserve current non-admin behavior.

## Goals / Non-Goals

**Goals:**

- Provide one coherent superadmin control plane for overview, users, configuration, models, usage, and Agent Skills.
- Make every declared API setting discoverable and editable with type validation and secret masking.
- Apply safe settings immediately and label infrastructure/security settings that require restart.
- Bootstrap a deterministic development Admin through the checked-in environment template while retaining environment overrides and an opt-out.
- Produce useful per-user usage data without requiring a third-party telemetry system.
- Keep all mutations audited and deny suspended accounts on both login and existing-token requests.

**Non-Goals:**

- Editing arbitrary undeclared operating-system environment variables.
- Building a distributed metrics pipeline, billing engine, or exact provider-cost ledger.
- Rotating the currently authenticated Admin's password through browser automation.
- Supporting non-SQLite application-state deployments in this local control-plane iteration.
- Replacing the existing Agent Skill validation, registry, or sandboxing implementation.

## Decisions

### 1. Add a dedicated `admin:control` permission granted only to `superadmin`

Admin routes will use one explicit permission instead of reusing `auth:manage`, because the existing `admin` business role currently has that permission and must not gain access to secrets or global controls. The frontend will use the effective role returned by `/auth/me`, but the backend remains the authority.

Alternative considered: treat both `admin` and `superadmin` as control-plane operators. Rejected because model credentials and global configuration require a narrower trust boundary.

### 2. Store runtime overrides and usage in a dedicated SQLite control-plane database

`UPLOAD_DIR/state/admin_control.sqlite3` will contain typed setting overrides, setting history, and usage events. The bootstrap `UPLOAD_DIR` from the process environment locates this database; the effective Settings object is then rebuilt from base values plus validated overrides. This avoids mixing operational configuration with business-domain tables and avoids a `DATABASE_URL` location cycle.

Alternative considered: rewrite `.env` directly. Rejected because comments/order are fragile, container filesystems may be immutable, concurrent writes are unsafe, and secrets could be accidentally exposed in diffs.

### 3. Treat Pydantic Settings as the configuration schema

The admin API derives key names, types, defaults, and validation from `Settings.model_fields`. It manages all declared Settings keys, not arbitrary process variables. Updates construct a complete candidate Settings object before persistence. Secret-like names (`KEY`, `SECRET`, `TOKEN`, `PASSWORD`) are write-only: list/read responses expose only `configured` and a short mask.

Settings affecting storage location, auth signing, CORS middleware, bootstrap identity, or process wiring are marked `restart_required`; other settings clear the Settings cache and become visible to subsequent requests.

Alternative considered: duplicate a hand-maintained allowlist. Rejected because it would drift from the actual configuration contract.

### 4. Keep model settings as a curated view over the same setting keys

The model page reads and writes the same configuration service, filtered to provider/model/key/timeout fields. There is no second source of truth. A connection-test endpoint performs a minimal OpenAI-compatible request with the effective candidate settings and returns sanitized latency/error information.

### 5. Enforce account status on every authenticated request

Login rejects non-active accounts. `get_current_identity` also reads current user status after token verification so suspending a user invalidates practical access immediately without a separate token blacklist. Admin mutations cannot suspend the acting account or remove the last superadmin.

Role remains stored through the existing role override directory for compatibility; user status remains in the users table.

### 6. Use append-only usage events with bounded dimensions

An HTTP middleware records authenticated API requests, response status, and latency. Chat and tool paths add explicit `chat_turn` and `tool_call` events. Agent-runtime usage metadata is recorded when the SDK provides input/output token counts; absent fields remain null rather than estimated. Aggregation endpoints support overview, daily series, and per-user breakdowns over a bounded date range.

Alternative considered: derive everything from text audit logs. Rejected because logs are not structured for efficient aggregation and may be rotated.

### 7. Build the frontend as a self-contained operations cockpit

`/admin` will be a responsive client-side console with a persistent section rail, warm-black control surfaces, amber status accents, dense tables, and clear secret/restart states. Existing `/admin/skills` will redirect into the unified skills section. Non-superadmins receive a 404-style page and API 403 responses.

## Risks / Trade-offs

- [Known development credentials can be unsafe outside local use] → Keep credentials in `.env.example`, allow empty values to disable bootstrap, emit a startup warning, and reject the documented default password when `APP_ENV=production`.
- [Per-request user-status lookup adds SQLite reads] → Use an indexed primary-key lookup and keep the record small; optimize with a short TTL cache only if profiling shows pressure.
- [Some setting changes cannot truly hot-reload] → Maintain an explicit restart-required set and show pending restart state in API/UI.
- [Usage events can grow indefinitely] → Index timestamp/user/type and add a retention cleanup hook with a configurable retention period.
- [Provider connection tests may incur a tiny request charge] → Require an explicit button action, use minimal tokens, and return no provider response content.
- [Existing admin-skills routes are feature-flagged] → Mount the unified admin router always, return skills availability/loading state, and preserve the skill feature toggle for runtime execution.

## Migration Plan

1. Add the control-plane SQLite schema idempotently during application startup.
2. Add the default development bootstrap values to `.env.example`; existing `.env` files remain unchanged.
3. Mount the new admin router and usage middleware, then extend authentication response/status checks.
4. Ship the unified `/admin` frontend and redirect the legacy skills page.
5. Run backend security/API tests, frontend unit tests, build checks, and local browser acceptance tests.

Rollback is code-only: old application versions ignore the separate control-plane database. User status and role mutations remain compatible with the existing schema and role override store.

## Open Questions

None blocking. Exact provider cost is intentionally reported only when supplied by the runtime or a future configured price catalog; token counts are never converted to fabricated currency values.
