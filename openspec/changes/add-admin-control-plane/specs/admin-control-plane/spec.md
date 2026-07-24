## ADDED Requirements

### Requirement: Superadmin-only administration console
The system SHALL expose a unified `/admin` console and `/admin/*` API surface only to authenticated users with the effective `superadmin` role. Authorization MUST be enforced independently on the server for every admin endpoint.

#### Scenario: Superadmin opens the console
- **WHEN** an authenticated superadmin navigates to `/admin`
- **THEN** the system displays overview, users, configuration, models, usage, and Agent Skills sections

#### Scenario: Non-superadmin attempts access
- **WHEN** an authenticated non-superadmin requests an admin page or API
- **THEN** the page displays a generic not-found state and the API returns HTTP 403

### Requirement: Default development Admin bootstrap
The repository environment template SHALL define a default Admin email and password that bootstrap one active account and promote it to `superadmin` on first startup. Operators MUST be able to override or disable both values, and production configuration MUST reject the documented default password.

#### Scenario: Fresh local installation
- **WHEN** the API starts against an empty database using the repository environment template
- **THEN** exactly one active default Admin account is created and can log in to `/admin`

#### Scenario: Existing installation restarts
- **WHEN** the API restarts after the default Admin has already been created
- **THEN** bootstrap is idempotent and does not create another account or overwrite its password

### Requirement: Audited administration mutations
The system MUST write an audit event for each successful or rejected configuration, model, user, and skill mutation without including passwords, API keys, tokens, or secret values.

#### Scenario: Admin updates a secret
- **WHEN** a superadmin changes an API key
- **THEN** the audit event identifies the actor, setting name, outcome, and timestamp but omits both old and new secret values
