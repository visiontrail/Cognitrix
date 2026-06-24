## Why

The Docker stack currently couples application runtime and persistent BI state too tightly: uploaded files, DuckDB session files, SQLite state, audit logs, and generated workspace artifacts are all exposed to the API container as its local `/app/data/uploads` tree. Even if a named volume survives ordinary `docker compose down`, the architecture has no explicit storage service boundary, no storage lifecycle contract, and no guardrail that distinguishes "restart the app" from "destroy data".

This is now operationally visible because `scripts/docker_restart.sh` is used as a normal restart path, yet prior test data can disappear during restart or rebuild flows. A restart must be a compute lifecycle event; data deletion must be explicit, rare, named, and confirmation-gated.

## What Changes

- Introduce an isolated Docker storage container/service that owns the persistent Cognitrix data volume and keeps its lifecycle separate from the API and web services.
- Update Docker Compose so API runtime containers consume storage through the storage boundary instead of treating persistence as an incidental API-local mount.
- Preserve all runtime data across `docker_restart.sh`, `docker_up.sh`, image rebuilds, and ordinary `docker compose down --remove-orphans` flows.
- Make destructive storage reset behavior explicit and separate from restart/start/stop scripts.
- Add storage initialization checks so the expected directory structure exists before the API starts.
- Add verification coverage that proves restart/rebuild does not delete uploaded files, DuckDB files, SQLite state, or audit/state directories.
- Document the storage container contract and the supported operational commands for restarting services versus resetting data.

## Capabilities

### New Capabilities
- `containerized-storage`: Defines the persistent-storage isolation contract for Docker deployments, including storage service lifecycle, API attachment behavior, restart preservation, explicit reset semantics, and verification requirements.

### Modified Capabilities

## Impact

- `docker-compose.yml` and `infra/docker/docker-compose.yml`: service topology, volumes, health/dependency ordering, and storage mount semantics.
- `scripts/docker_restart.sh`, `scripts/docker_up.sh`, `scripts/docker_down.sh`, `scripts/lib/docker.sh`, and reset/maintenance scripts: operational lifecycle behavior and explicit destructive reset handling.
- `apps/api/Dockerfile` or Docker entrypoint/init logic if needed: storage directory initialization and permission expectations.
- `apps/api/config.py` and storage-path assumptions if any hard-coded local paths need to be normalized around `UPLOAD_DIR`.
- Tests under `tests/scripts/`, smoke tests, or Docker-focused checks: persistence verification across restart/rebuild.
- Project documentation and env examples: storage container usage, data retention guarantees, and reset procedures.
