## 1. Control-plane foundation

- [x] 1.1 Add the `admin:control` superadmin-only permission and admin authorization tests
- [x] 1.2 Add idempotent control-plane SQLite schema initialization for setting overrides, setting history, and usage events
- [x] 1.3 Add default development Admin values to the API environment template and production-safety validation

## 2. Runtime configuration and models

- [x] 2.1 Implement typed Settings inventory, categories, secret detection/masking, sources, and restart-required metadata
- [x] 2.2 Implement validated persistent setting override create/update/reset with cache refresh and secret-safe audit events
- [x] 2.3 Implement admin configuration list/history endpoints and focused model settings endpoint
- [x] 2.4 Implement sanitized minimal model connection-test endpoint
- [x] 2.5 Add backend tests for complete inventory, validation, persistence, reset, masking, authorization, and connection-test sanitization

## 3. User administration and authentication

- [x] 3.1 Extend authentication login/me responses with effective role and account status
- [x] 3.2 Reject suspended users at login and on requests using previously issued tokens
- [x] 3.3 Implement paginated admin user inventory with search, workspace count, role, status, and usage summary
- [x] 3.4 Implement audited role and status mutations with self-lockout and last-superadmin protections
- [x] 3.5 Add backend tests for user inventory, role changes, suspension, immediate token rejection, and lockout protections

## 4. Usage analytics

- [x] 4.1 Implement append-only usage recorder and retention cleanup
- [x] 4.2 Instrument authenticated HTTP requests and chat/tool activity without recording request content
- [x] 4.3 Capture model token metadata when supplied by the agent runtime
- [x] 4.4 Implement admin overview, UTC trend, and paginated per-user usage endpoints
- [x] 4.5 Add backend tests for event recording, aggregation, date bounds, sorting, and data minimization

## 5. Agent Skill integration

- [x] 5.1 Mount admin control-plane endpoints independently of the Agent Skills feature flag and expose skill availability metadata
- [x] 5.2 Integrate the existing skill list/upload/status/assignment/removal operations into the unified admin client
- [x] 5.3 Add tests for disabled-feature visibility and runtime cache invalidation

## 6. Administration console

- [x] 6.1 Add typed frontend admin API client and authentication role/status session fields
- [x] 6.2 Implement `/admin` operations-cockpit shell, overview cards, trends, and responsive navigation
- [x] 6.3 Implement configuration editor with type-aware controls, secret semantics, validation errors, source badges, reset, and restart indicators
- [x] 6.4 Implement model settings and explicit connection-test workflow
- [x] 6.5 Implement searchable user table with role/status actions and lockout feedback
- [x] 6.6 Integrate Agent Skills management and redirect the legacy `/admin/skills` route
- [x] 6.7 Add superadmin entry/redirect behavior and generic not-found state for unauthorized users
- [x] 6.8 Add frontend component/API tests for authorization, navigation, config editing, user actions, usage rendering, and skills state

## 7. Verification and handoff

- [x] 7.1 Run focused backend admin/security/auth tests and fix all failures
- [x] 7.2 Run frontend Vitest, lint/type/build checks and fix all failures
- [x] 7.3 Run the wider backend regression suite and local smoke checks
- [x] 7.4 Start the local stack and verify default Admin login plus every admin section and mutation through Browser
- [x] 7.5 Inspect the rendered console and responsive state through Computer Use, then document credentials, override/disable behavior, restart semantics, and validation evidence
