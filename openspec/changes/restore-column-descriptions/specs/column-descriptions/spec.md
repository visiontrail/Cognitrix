## ADDED Requirements

### Requirement: Persist uploaded column descriptions
The system SHALL persist per-column metadata for ingested Excel tables, including the physical SQL column name and a human-readable description or original uploaded header when available.

#### Scenario: Non-English header is normalized
- **WHEN** a user ingests an Excel file whose header is normalized to a generated physical column name
- **THEN** the system stores the generated physical column name together with the original header or inferred description

#### Scenario: Existing mapping has no explicit description
- **WHEN** ingestion execution receives only a physical-to-source column mapping
- **THEN** the system uses the mapped source header as the column description fallback

### Requirement: Expose column descriptions through data discovery APIs
The system SHALL include persisted column descriptions in table description and catalog data-preview API responses without changing the physical column names used for SQL execution.

#### Scenario: Catalog preview has column metadata
- **WHEN** the Workspace table catalog opens a table with stored column metadata
- **THEN** the data-preview response includes each column's physical name, type, original header, and description

#### Scenario: Agent describes a table
- **WHEN** the agent calls `describe_table` for a table with stored column metadata
- **THEN** the tool result includes column descriptions alongside physical column names

### Requirement: Display human-readable column labels in the UI
The system SHALL show column descriptions or original headers before generated physical names in Workspace table catalog detail and chat `@` column suggestions.

#### Scenario: Catalog detail displays a described column
- **WHEN** a user opens a catalog table containing a column named `c_1` with description `员工姓名`
- **THEN** the table header displays `员工姓名` and still exposes `c_1` as the physical column name

#### Scenario: Chat mention suggestions display described columns
- **WHEN** a user types `@` in the chat input for a workspace table with described generated columns
- **THEN** the suggestion list displays the human-readable description or original header instead of only `c_1`-style names
