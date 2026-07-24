## ADDED Requirements

### Requirement: Registered-user inventory
The system SHALL provide a paginated, searchable user inventory containing account identity, status, effective role, job, creation and last-login timestamps, workspace count, and summarized usage. Password hashes and credentials MUST never be returned.

#### Scenario: Admin searches users
- **WHEN** a superadmin searches by email or display name
- **THEN** the API returns matching users with pagination metadata and no credential fields

### Requirement: User role administration
The system SHALL allow a superadmin to change a user's effective application role and SHALL audit the previous and new roles. The system MUST prevent removal of the last active superadmin.

#### Scenario: Promote a user
- **WHEN** a superadmin changes an active user's role to `superadmin`
- **THEN** subsequent authentication reflects the new role and an audit event is recorded

#### Scenario: Demote the last superadmin
- **WHEN** an update would leave no active superadmin
- **THEN** the API rejects the update with HTTP 409

### Requirement: Account activation lifecycle
The system SHALL allow active accounts to be suspended and suspended accounts to be reactivated. A superadmin MUST NOT suspend their own currently authenticated account.

#### Scenario: Suspend another user
- **WHEN** a superadmin suspends an active user
- **THEN** new login attempts fail and existing tokens are rejected on their next request

#### Scenario: Suspend self
- **WHEN** a superadmin attempts to suspend their own account
- **THEN** the API rejects the operation with HTTP 409
