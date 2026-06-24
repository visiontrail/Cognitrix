# containerized-storage Specification

## Purpose
TBD - created by archiving change isolate-storage-container. Update Purpose after archive.
## Requirements
### Requirement: Dedicated Docker Storage Service
Docker deployments SHALL define a dedicated storage service/container that owns initialization and lifecycle signaling for Cognitrix persistent runtime data.

#### Scenario: Storage service is present in Compose topology
- **WHEN** the Docker Compose configuration is rendered
- **THEN** it includes a storage service separate from the API and web services
- **AND** the storage service mounts the persistent Cognitrix upload/state volume

#### Scenario: Storage service initializes required directories
- **WHEN** the storage service starts with an empty persistent volume
- **THEN** it creates the directories required for uploads, state databases, audit logs, and runtime artifacts
- **AND** it exposes a healthy status only after the required storage paths are writable

### Requirement: API Consumes Isolated Persistent Storage
The API service SHALL consume persistent runtime data from the storage-owned Docker volume while keeping application configuration compatible with `UPLOAD_DIR` and `DATABASE_URL`.

#### Scenario: API waits for initialized storage
- **WHEN** the Docker stack starts
- **THEN** the API service starts only after the storage service has reported healthy

#### Scenario: API uses the persistent upload path
- **WHEN** the API runs in Docker
- **THEN** `UPLOAD_DIR` resolves to the mounted persistent storage path
- **AND** the default SQLite `DATABASE_URL` resolves under that same persistent storage tree

### Requirement: Restart Preserves Runtime Data
Normal Docker restart, start, stop, and rebuild commands SHALL preserve uploaded files, DuckDB databases, SQLite state, audit logs, and other runtime data stored in the persistent volume.

#### Scenario: Restart script preserves a sentinel file
- **WHEN** a file exists in the persistent storage volume before `scripts/docker_restart.sh` runs
- **THEN** the file still exists with the same contents after the script completes

#### Scenario: Rebuild preserves state directories
- **WHEN** the API image is rebuilt through the normal Docker restart workflow
- **THEN** the persistent `state` directory and its database files are not deleted or recreated from scratch

#### Scenario: Docker down preserves storage
- **WHEN** the normal Docker stop/down script runs
- **THEN** it does not remove the persistent storage volume

### Requirement: Destructive Storage Reset Is Explicit
The system SHALL provide destructive storage reset only through an explicitly named reset path that is separate from restart, start, and stop workflows.

#### Scenario: Restart command is non-destructive
- **WHEN** a user runs `make docker-restart` or `scripts/docker_restart.sh`
- **THEN** no command in that workflow removes Docker volumes or deletes persistent storage directories

#### Scenario: Reset command requires explicit intent
- **WHEN** a user invokes the local data reset workflow with Docker volume deletion
- **THEN** the workflow requires an explicit Docker-volume reset flag
- **AND** it requires confirmation unless a non-interactive confirmation flag is supplied

### Requirement: Existing Docker Data Is Migrated Or Reused
The implementation SHALL preserve existing Docker volume data during the transition to the storage service.

#### Scenario: Existing volume is reused
- **WHEN** the current deployment already has a Cognitrix upload data volume
- **THEN** the new storage service uses that volume without deleting or replacing its contents

#### Scenario: Volume rename requires migration
- **WHEN** the implementation changes the Docker volume name
- **THEN** it provides and documents a migration path that copies existing data before the new stack starts
- **AND** the migration path is verified before the old volume is no longer used

### Requirement: Storage Persistence Is Verified
The repository SHALL include automated or scripted verification for Docker storage persistence across restart/rebuild workflows.

#### Scenario: Persistence check passes after restart
- **WHEN** the storage persistence verification creates test data and runs the Docker restart workflow
- **THEN** the verification confirms the test data remains present and readable afterward

#### Scenario: Compose validation includes storage service
- **WHEN** Docker-related script or configuration tests run
- **THEN** they validate that the Compose topology includes the storage service and that restart/down workflows do not request volume deletion

### Requirement: Storage Operations Are Documented
The project documentation SHALL describe the storage container, retained data paths, non-destructive restart behavior, and the explicit reset procedure.

#### Scenario: Operator reads Docker storage documentation
- **WHEN** a developer or operator reads the Docker usage documentation
- **THEN** they can identify which commands restart services without deleting data
- **AND** they can identify the explicit command path that intentionally removes persisted Docker data

