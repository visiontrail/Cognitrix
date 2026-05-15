## Why

Today, every Agent in Cognitrix has its capabilities hard-coded — the WriteIngestionAgent's Excel parsing logic, in particular, lives inside our own Python modules and cannot be swapped, upgraded, or extended without a code release. The Claude Agent SDK now supports composable "Skills" (filesystem-packaged capability bundles, e.g. Anthropic's official xlsx skill), and we want a controlled way for super-admins to load these into specific agents at runtime — replacing fragile hand-rolled parsers with vetted, drop-in capability packages — without exposing skill management to ordinary users.

## What Changes

- Introduce a first-class **Agent Skill** concept inside the API: a versioned, filesystem-stored bundle (`SKILL.md` + assets) attached to one or more named agents (`WriteIngestionAgent`, `QueryAgent`, `ChartQueryAgent`, etc.).
- Add a **super-admin–only** REST surface under `/admin/skills` to upload, list, enable/disable, assign-to-agent, and delete skill packages. Authentication via existing JWT + a new `skills:admin` permission scope granted only to the `superadmin` role.
- Add a **super-admin admin console** route in the Next.js frontend (`/admin/skills`) — hidden from the regular sidebar and gated by role — for managing skill packages and per-agent assignments through a UI (upload `.zip`, browse loaded skills, toggle on/off per agent).
- Wire `AgentRuntime` and the ingestion agent loop to load assigned skills into `ClaudeAgentOptions` at run time so the Claude Agent SDK can dispatch tool calls into the skill.
- **Default-install** Anthropic's official `xlsx` skill (sourced from `https://mcpservers.org/agent-skills/anthropic/xlsx`) and assign it to `WriteIngestionAgent` on bootstrap; the existing hand-written xlsx parsing path in `agentic_ingestion/` is deprecated and routed through the skill instead.
- **BREAKING (internal)**: The current `agentic_ingestion` Excel parsing code paths (column inspection, type inference helpers that duplicate what the xlsx skill provides) are removed once the skill-backed path is verified; ingestion lifecycle endpoints keep their public contract.
- New super-admin bootstrap env var `AUTH_BOOTSTRAP_SUPERADMIN_EMAIL` (optional) — promotes a single account to the `superadmin` role on startup.

## Capabilities

### New Capabilities
- `agent-skills-management`: Super-admin–owned lifecycle for uploading, validating, storing, assigning, and loading Claude Agent SDK skills into named agents at runtime; includes the default-bundled xlsx skill for `WriteIngestionAgent`.

### Modified Capabilities
<!-- None — touches internal agent runtime and ingestion implementation details, not the public spec-level behavior of existing capabilities. -->

## Impact

- **Backend (`apps/api/`)**:
  - New module `agent_skills/` (loader, registry, validator, storage layout).
  - New router `admin_skills.py` mounted at `/admin/skills`.
  - `auth.py` — add `superadmin` role and `skills:admin` permission scope; honor `AUTH_BOOTSTRAP_SUPERADMIN_EMAIL`.
  - `agent_runtime.py` and `agentic_ingestion/` — load per-agent skills into `ClaudeAgentOptions` (`agents=` / `setting_sources` per SDK docs).
  - `config.py` — new settings: `AGENT_SKILLS_DIR`, `AGENT_SKILLS_ENABLED`, `AGENT_SKILLS_MAX_UPLOAD_MB`, `AUTH_BOOTSTRAP_SUPERADMIN_EMAIL`.
  - SQLite state: new `agent_skills` and `agent_skill_assignments` tables under `UPLOAD_DIR/state/`.
  - Bootstrap script to seed Anthropic xlsx skill into `AGENT_SKILLS_DIR` on first launch.
- **Frontend (`apps/web/`)**:
  - New `/admin/skills` route + `AdminSkillsPage` component (upload, list, assign), gated by `superadmin` role.
  - `lib/auth/` — expose current user role; admin route guard.
  - No changes to chat/workspace surfaces.
- **Data / Filesystem**:
  - `UPLOAD_DIR/agent_skills/<skill_id>/` — extracted skill bundles (read-only at runtime).
  - SQLite tables for skill metadata and agent assignments.
- **Tests**:
  - New unit tests: skill validator, loader, RBAC on `/admin/skills`.
  - New integration test: WriteIngestionAgent runs end-to-end ingestion using the xlsx skill instead of hand-written parsing.
  - Security tests: non-superadmin gets 403; uploaded skill cannot escape its sandbox dir.
- **Risk**: Skill upload is a remote code-loading surface — validation, path traversal protection, and execution sandboxing (per Claude Agent SDK guidance) are critical. Detailed mitigations in `design.md`.
