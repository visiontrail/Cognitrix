## ADDED Requirements

### Requirement: Complete declared-setting inventory
The admin API SHALL enumerate every environment-backed field declared by the backend `Settings` model with its key, category, value type, effective source, secret flag, editability, validation metadata, and restart requirement.

#### Scenario: Admin views configuration
- **WHEN** a superadmin opens the configuration section
- **THEN** every declared backend setting appears exactly once and secrets appear only as configured state plus a mask

### Requirement: Validated persistent overrides
The system SHALL validate an update by constructing a complete candidate Settings object before persisting it. Valid overrides MUST survive restart; invalid overrides MUST return HTTP 422 and leave the previous effective configuration unchanged.

#### Scenario: Valid live setting update
- **WHEN** a superadmin changes `AGENT_MAX_TOOL_STEPS` to a valid positive integer
- **THEN** the override is persisted, the Settings cache is refreshed, and subsequent requests observe the new value

#### Scenario: Invalid setting update
- **WHEN** a superadmin changes `AGENT_MAX_TOOL_STEPS` to zero
- **THEN** the API returns HTTP 422 and retains the prior effective value

### Requirement: Secret-safe update semantics
Secret settings MUST never return plaintext through list, detail, history, validation, or error responses. Sending an empty secret value SHALL keep the existing secret unless the request explicitly asks to clear it.

#### Scenario: Existing API key
- **WHEN** `AI_API_KEY` is configured and a superadmin loads the model settings
- **THEN** the response reports it as configured with a mask and does not contain the plaintext key

### Requirement: Model settings and connection test
The console SHALL provide a focused model settings view over provider URL, model name, credential, protocol endpoint, and timeout fields. It SHALL offer an explicit minimal connection test whose response contains only success status, latency, provider/model identifiers, and a sanitized error.

#### Scenario: Working provider configuration
- **WHEN** a superadmin runs the model connection test with valid settings
- **THEN** the API performs a minimal request and returns success with measured latency without returning generated content
