## ADDED Requirements

### Requirement: Unified Agent Skill administration
The `/admin` console SHALL expose installed skills, manifests, validation/load errors, status, runtime assignments, and upload/remove actions by reusing the existing validated Agent Skill registry and sandbox.

#### Scenario: Enable and assign a valid skill
- **WHEN** a superadmin enables an installed skill and assigns it to a supported agent
- **THEN** the runtime loader cache is invalidated and subsequent agent turns can load that skill

### Requirement: Skill feature availability
The console SHALL clearly report whether Agent Skills runtime loading is enabled and where validated bundles are stored, without exposing filesystem content outside the configured skills directory.

#### Scenario: Skills feature disabled
- **WHEN** `AGENT_SKILLS_ENABLED` is false
- **THEN** the admin skills section remains visible in read-only availability state and explains that runtime loading is disabled
