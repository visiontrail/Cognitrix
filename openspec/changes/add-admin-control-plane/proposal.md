## Why

Cognitrix already has user accounts and a narrow superadmin-only Agent Skill API, but operators cannot administer the application from one secured interface. Configuration changes, model credentials, account lifecycle operations, and usage visibility currently require direct file or database access, which is slow, error-prone, and unaudited.

## What Changes

- Add a dedicated `/admin` login destination and responsive administration console available only to `superadmin`.
- Bootstrap a documented default development Admin account and promote it to `superadmin`, while allowing every credential to be overridden or disabled by environment configuration.
- Consolidate Agent Skill discovery, upload, enable/disable, assignment, loading status, and removal into the administration console.
- Add a database-backed runtime configuration overlay for all declared API environment settings, including validation, secret masking, audit history, and restart-required metadata.
- Add a focused model settings surface for provider URLs, model names, API keys, timeouts, and connection validation.
- Add registered-user administration with search, role changes, activation/suspension, and account metadata.
- Record and aggregate per-user product usage, including authenticated requests, chat turns, tool calls, errors, latency, and available model token/cost metadata.
- Add overview metrics and time-series/user breakdowns to the administration console.
- Extend authentication responses so the frontend can enforce admin routing without decoding tokens, and reject suspended users immediately.

## Capabilities

### New Capabilities

- `admin-control-plane`: Superadmin-only console navigation, overview, authorization behavior, and default Admin bootstrap.
- `admin-runtime-configuration`: Typed, audited, secret-safe administration of environment and model settings.
- `admin-user-management`: Registered-user listing, filtering, role changes, and account lifecycle management.
- `admin-usage-analytics`: Collection and aggregation of per-user operational and model-usage metrics.
- `admin-agent-skills`: Unified console integration for Agent Skill management and runtime loading state.

### Modified Capabilities

- `user-account`: Authentication exposes effective role and status, and suspended accounts cannot establish or continue authenticated sessions.

## Impact

- Backend: authentication/RBAC, settings loading, SQLite migrations, admin routers, request/chat/tool instrumentation, audit logging, and Agent Skill routing.
- Frontend: authentication session shape, `/admin` routes, admin API client, console components, navigation, internationalized copy, and tests.
- Operations: development bootstrap credentials in `.env.example`; runtime configuration overrides stored in the application state database; settings that cannot be safely hot-reloaded are explicitly marked as restart-required.
- Security: all admin endpoints require `superadmin`; secret values are write-only/masked in responses and never included in audit payloads.
