## ADDED Requirements

### Requirement: Super-admin role and permission scope

The system SHALL define a `superadmin` role distinct from the existing `admin` role, and a `skills:admin` permission scope granted exclusively to that role. All agent-skill management endpoints and admin UI routes MUST require this permission.

#### Scenario: Non-superadmin denied access to skill management API
- **WHEN** a user with role `admin`, `editor`, `viewer`, or any role other than `superadmin` calls any `/admin/skills` endpoint
- **THEN** the API responds with HTTP 403 Forbidden and no skill metadata is leaked in the response body

#### Scenario: Superadmin can call skill management API
- **WHEN** a user with role `superadmin` calls `GET /admin/skills`
- **THEN** the API responds with HTTP 200 and the list of installed skills

#### Scenario: Superadmin bootstrap via environment variable
- **WHEN** `AUTH_BOOTSTRAP_SUPERADMIN_EMAIL` is set to an email that matches an existing user, and the API starts
- **THEN** that user's role is promoted to `superadmin` and the promotion is recorded in the audit log

### Requirement: Skill bundle upload, validation, and storage

The system SHALL accept zip-format skill bundles via authenticated upload, validate them against safety rules, and store validated bundles on the filesystem under `${UPLOAD_DIR}/agent_skills/<skill_id>/`. Invalid bundles MUST be rejected before extraction completes.

#### Scenario: Valid skill bundle is accepted and stored
- **WHEN** a superadmin uploads a zip containing a top-level `SKILL.md` with valid frontmatter (`name`, `description`), no symlinks, no path-traversal entries, and total size ≤ `AGENT_SKILLS_MAX_UPLOAD_MB`
- **THEN** the system extracts the bundle to `${UPLOAD_DIR}/agent_skills/<uuid>/`, persists metadata (id, name, version, sha256, uploaded_by, uploaded_at, status=`enabled`), and returns HTTP 201 with the skill id

#### Scenario: Oversized upload is rejected
- **WHEN** a superadmin uploads a zip whose size exceeds `AGENT_SKILLS_MAX_UPLOAD_MB`
- **THEN** the system responds with HTTP 413 Payload Too Large and no files are written to disk

#### Scenario: Path-traversal entry is rejected
- **WHEN** a zip is uploaded that contains an entry whose resolved path escapes the destination directory (e.g. `../etc/passwd` or an absolute path)
- **THEN** the system rejects the upload with HTTP 400, no files are written, and the attempt is recorded in the audit log

#### Scenario: Missing or malformed SKILL.md is rejected
- **WHEN** a zip is uploaded without a top-level `SKILL.md`, or with a `SKILL.md` missing required frontmatter fields
- **THEN** the system rejects the upload with HTTP 400 and the error response identifies the missing field

#### Scenario: Symlink entry is rejected
- **WHEN** a zip is uploaded that contains a symlink entry
- **THEN** the system rejects the upload with HTTP 400 and no files are written

### Requirement: Skill assignment to named agents

The system SHALL allow superadmins to assign zero or more installed skills to each named agent (`WriteIngestionAgent`, `QueryAgent`, `ChartQueryAgent`, and any future named agent). Assignments MUST be system-wide (not per workspace or per user) and MUST be queryable per agent.

#### Scenario: Superadmin assigns a skill to an agent
- **WHEN** a superadmin calls `POST /admin/skills/{skill_id}/assignments` with body `{ "agent_name": "WriteIngestionAgent" }`
- **THEN** the system persists the assignment and a subsequent `GET /admin/skills/agents/WriteIngestionAgent` includes the skill

#### Scenario: Superadmin removes an assignment
- **WHEN** a superadmin calls `DELETE /admin/skills/{skill_id}/assignments/{agent_name}`
- **THEN** the assignment is removed and the skill no longer appears in that agent's assignment list

#### Scenario: Assigning to an unknown agent is rejected
- **WHEN** a superadmin attempts to assign a skill to an `agent_name` not in the registered agent list
- **THEN** the system responds with HTTP 400 and no assignment is persisted

### Requirement: Skill enable/disable toggle

The system SHALL allow superadmins to toggle an installed skill between `enabled` and `disabled` without deleting its bundle. Disabled skills MUST NOT be loaded into any agent runtime, regardless of existing assignments.

#### Scenario: Disabling a skill stops it from loading
- **WHEN** a skill assigned to `WriteIngestionAgent` is toggled to `status=disabled` and a new chat turn starts
- **THEN** the agent runtime loads `WriteIngestionAgent` without that skill, and assignments to it remain visible in the admin UI

#### Scenario: Re-enabling a skill restores loading
- **WHEN** a previously disabled skill is toggled back to `status=enabled` and a new chat turn starts
- **THEN** the agent runtime loads the skill on that turn

### Requirement: Skill deletion

The system SHALL allow superadmins to delete a skill, removing both its on-disk bundle and all its assignments. Deletion MUST be irreversible.

#### Scenario: Skill is deleted with assignments
- **WHEN** a superadmin calls `DELETE /admin/skills/{skill_id}` on a skill that is assigned to one or more agents
- **THEN** the bundle directory under `${UPLOAD_DIR}/agent_skills/` is removed, all assignment rows are removed, the metadata row is removed, and an audit event is emitted

### Requirement: Runtime loading of assigned skills into Claude Agent SDK

The agent runtime (`AgentRuntime` and the ingestion agent) SHALL load all enabled, assigned skills for the active agent into `ClaudeAgentOptions` at the start of each turn, using the Claude Agent SDK's documented skill-loading mechanism. Skills MUST NOT be loaded for agents they are not assigned to.

#### Scenario: Assigned skill is available to the agent at runtime
- **WHEN** a chat turn invokes an agent that has at least one enabled, assigned skill, and `AGENT_SKILLS_ENABLED=true`
- **THEN** the agent's `ClaudeAgentOptions` includes the skill's filesystem path, and the model can invoke tools the skill exposes

#### Scenario: Skill load failure does not crash the agent
- **WHEN** a skill assigned to an agent fails to load (e.g. corrupted manifest, missing files)
- **THEN** the agent runtime continues with the remaining enabled skills, the failure is logged, and the failure is exposed via `GET /admin/skills` so a superadmin can see it

#### Scenario: Disabling the global feature flag bypasses skill loading
- **WHEN** `AGENT_SKILLS_ENABLED=false` and a chat turn starts
- **THEN** no skills are loaded into any agent, regardless of assignments

### Requirement: Default Anthropic xlsx skill for WriteIngestionAgent

On API startup, the system SHALL ensure that the Anthropic xlsx skill (vendored at `apps/api/vendor/skills/`) is installed under the name `anthropic/xlsx` and assigned to `WriteIngestionAgent`, unless a skill with that name already exists. The vendored zip's sha256 MUST be verified against a checksum recorded in source control before installation.

#### Scenario: First-time bootstrap installs the xlsx skill
- **WHEN** the API starts, `AGENT_SKILLS_ENABLED=true`, and no skill named `anthropic/xlsx` is present in the registry
- **THEN** the system verifies the vendored zip's sha256, installs it as `anthropic/xlsx`, creates an assignment to `WriteIngestionAgent`, and records both actions in the audit log

#### Scenario: Bootstrap is idempotent on subsequent starts
- **WHEN** the API starts and a skill named `anthropic/xlsx` already exists
- **THEN** the system does not reinstall it and does not duplicate the assignment

#### Scenario: Bootstrap fails loudly on checksum mismatch
- **WHEN** the vendored zip's computed sha256 does not match the checksum recorded in source control
- **THEN** the system logs an error, refuses to install the skill, and does not assign it to `WriteIngestionAgent`

#### Scenario: WriteIngestionAgent uses the xlsx skill instead of the legacy parser
- **WHEN** `AGENT_SKILLS_ENABLED=true`, `LEGACY_XLSX_PARSER_ENABLED=false`, the xlsx skill is installed and assigned, and a user uploads an Excel file through the ingestion lifecycle
- **THEN** the WriteIngestionAgent parses the file by invoking the xlsx skill, and no code path in `agentic_ingestion/` calls the hand-written Excel parser

### Requirement: Hidden super-admin frontend route

The frontend SHALL expose a `/admin/skills` route that is NOT linked from the global sidebar or any user-visible navigation, and that is accessible only to users with role `superadmin`. The route MUST provide UI for uploading skills, viewing installed skills and their manifests, toggling enable/disable, assigning to agents, and deleting skills.

#### Scenario: Non-superadmin sees nothing about the admin route
- **WHEN** a non-superadmin user is logged in
- **THEN** no link to `/admin/skills` appears in the sidebar, and navigating directly to `/admin/skills` shows a generic "Not found" page

#### Scenario: Superadmin uploads a skill via the UI
- **WHEN** a superadmin drags a valid zip onto the upload control in `/admin/skills`
- **THEN** the UI calls `POST /admin/skills`, displays the new skill in the list, and shows its parsed `SKILL.md` manifest

#### Scenario: Superadmin assigns a skill to an agent via the UI
- **WHEN** a superadmin toggles the `WriteIngestionAgent` checkbox for a skill row in the admin UI
- **THEN** the UI calls the corresponding assignment endpoint and the checkbox reflects the persisted state

### Requirement: Audit logging of skill management actions

The system SHALL emit an audit event for every skill management action: upload, enable, disable, assign, unassign, delete, and bootstrap install. Each event MUST record actor identity, action type, target skill id (where applicable), target agent name (where applicable), and timestamp.

#### Scenario: Upload emits an audit event
- **WHEN** a superadmin successfully uploads a skill
- **THEN** an audit event with `action=skill_upload`, actor=superadmin user id, and `skill_id` is written

#### Scenario: Rejected upload emits an audit event
- **WHEN** a skill upload is rejected for any reason (oversize, path-traversal, malformed manifest, symlink)
- **THEN** an audit event with `action=skill_upload_rejected` and the rejection reason is written
