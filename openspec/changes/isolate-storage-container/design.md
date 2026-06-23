## Context

Cognitrix persists runtime BI state under `UPLOAD_DIR`, which defaults to `/app/data/uploads` in Docker. That tree contains uploaded source files, per-user/project DuckDB databases, SQLite state databases under `state/`, audit logs, agent session state, saved views, catalog metadata, and workspace-related artifacts. The current Compose files mount a named volume directly into the `api` service:

- `docker-compose.yml`: `cognitrix_upload_data:/app/data/uploads`
- `infra/docker/docker-compose.yml`: `cognitrix_upload_data:/app/data/uploads`

This is better than container-local storage, but the volume is still treated as an implementation detail of the API container. Operational scripts also model lifecycle too coarsely: `scripts/docker_restart.sh` stops the stack and rebuilds services, while destructive storage reset behavior lives elsewhere and is easy to confuse with normal restart/rebuild workflows.

SQLite and DuckDB are embedded file databases. Moving them to a networked storage protocol just to satisfy "separate container" would be a bad trade: file locks, fsync semantics, and latency become more fragile. The right boundary is a Docker-managed persistent volume with a dedicated storage service that owns initialization, health, permissions, and lifecycle semantics, while only the API writes application data.

## Goals / Non-Goals

**Goals:**

- Make persistent storage an explicit Docker service/container with its own lifecycle boundary.
- Preserve all data across app restarts, image rebuilds, and ordinary `docker compose down --remove-orphans` flows.
- Keep DuckDB and SQLite on a local Docker volume to preserve file-locking and durability behavior.
- Ensure the API starts only after the storage service has initialized expected directories.
- Make data deletion explicit through reset/maintenance scripts, never as part of restart/start/stop.
- Reuse or migrate the existing Docker named volume without deleting current user/test data.
- Add tests or script checks that prove restart/rebuild flows preserve a sentinel file and state directories.

**Non-Goals:**

- Replacing DuckDB/SQLite with Postgres or another external database.
- Introducing NFS, SMB, object storage, MinIO, or a distributed filesystem for embedded database files.
- Building backup/restore scheduling, encryption-at-rest, or multi-host replication in this change.
- Changing application-level workspace deletion semantics, where explicit workspace deletion may still remove that workspace's files.

## Decisions

### Decision 1: Add a `storage` service as the persistent data owner

Create a lightweight `storage` service in both Compose files. It mounts the persistent volume at a storage-owned path such as `/storage/uploads`, creates required subdirectories (`state`, `audit`, and any existing upload/workspace parents), normalizes permissions, writes a small readiness marker, and then stays alive.

The API service will consume the same volume at `/app/data/uploads`, but the Compose topology makes storage ownership explicit:

- `storage` declares and initializes the volume.
- `api` depends on `storage` health.
- `api` continues to use `UPLOAD_DIR=/app/data/uploads`.
- `web` remains dependent on `api`, not on storage directly.

Alternative considered: put all persistent files inside a separate database/storage product. Rejected because the current persistence model is filesystem-native, and moving embedded DuckDB/SQLite files over a network storage service would increase corruption and locking risk without solving the immediate lifecycle problem.

Alternative considered: keep only the existing named volume and patch `docker_restart.sh`. Rejected as incomplete. It fixes one command path but leaves no architectural boundary, no initialization service, and no explicit storage lifecycle contract.

### Decision 2: Preserve the existing named volume identity

The implementation must not rename or delete the current Docker volume as part of this change. The safest path is to keep the logical volume key `cognitrix_upload_data` and, if needed, add an explicit Docker volume `name` that maps to the existing project volume after confirming the actual Compose volume name. If an explicit rename is unavoidable, provide a migration command that copies data from the old volume to the new volume before the new stack starts.

Alternative considered: create a fresh volume with a cleaner name and accept data loss in development. Rejected. The user explicitly reported data loss as the bug; a storage-isolation change that deletes existing data would be self-defeating.

### Decision 3: Restart scripts are non-destructive

`scripts/docker_restart.sh`, `scripts/docker_up.sh`, and `scripts/docker_down.sh` must never pass `--volumes` and must not call reset logic. `docker_restart.sh` should be allowed to stop/recreate/rebuild compute containers while leaving `cognitrix_upload_data` intact.

Destructive reset remains available only through an explicit maintenance path, for example `make reset-local-data` with `--include-docker-volumes`, and should continue to require a clear flag and confirmation unless `--yes` is supplied.

Alternative considered: add a `--keep-data` flag to restart. Rejected because preservation should be the default invariant. Flags for normal behavior are easy to forget.

### Decision 4: Storage readiness is checked before API startup

The storage service healthcheck should validate that:

- the mounted storage directory exists;
- `state/` exists and is writable;
- an initialization marker can be written/read.

The API's `depends_on.storage.condition` should use `service_healthy` where supported by the current Compose setup. The API should still create missing app-specific subdirectories defensively at runtime because healthchecks are an operational guardrail, not a substitute for application robustness.

Alternative considered: let the API continue to initialize directories alone. Rejected because storage isolation needs an observable boundary and a health signal before the API starts.

### Decision 5: Verification uses sentinel persistence plus real state paths

Add a Docker/script test that creates a sentinel file under the persistent upload volume, runs the restart script or equivalent compose restart/rebuild sequence, and verifies the sentinel still exists. The check should also verify that `state/` survives and remains writable, because the practical failure mode affects SQLite state as much as uploaded spreadsheets.

Alternative considered: rely on `docker compose config` validation only. Rejected because config validation cannot prove data survives lifecycle operations.

## Risks / Trade-offs

- Storage service and API still share the same Docker volume mount -> This is intentional for DuckDB/SQLite correctness; mitigate by documenting that only the API writes application data and the storage service performs initialization only.
- Compose `depends_on.condition: service_healthy` compatibility can vary by Compose implementation -> The project already requires Docker Compose v2 or `docker-compose`; verify both supported paths or document the minimum supported version.
- Existing volumes may have root-owned files or inconsistent permissions -> Storage initialization should avoid destructive `chown -R` on large trees by default; apply narrow permission creation for missing directories and document manual repair if needed.
- Changing volume names can orphan existing data -> Keep the current volume key/name or provide an explicit migration script and test it before switching defaults.
- Tests that require Docker may be slow or unavailable in CI -> Put Docker persistence checks in script/smoke coverage and keep unit-level script assertions for command construction.

## Migration Plan

1. Inspect the actual existing Docker volume name generated by the current Compose project.
2. Add the `storage` service to root and infra Compose files while preserving the existing volume identity.
3. Update API service dependency ordering so it waits for storage readiness.
4. Keep `UPLOAD_DIR` and `DATABASE_URL` defaults compatible with the existing `/app/data/uploads` path to avoid application code churn.
5. Update restart/start/stop scripts to document and enforce non-destructive behavior.
6. Add or update tests that create a sentinel file, restart/rebuild the stack, and verify persistence.
7. Update documentation/env examples with the storage container contract and reset procedure.

Rollback is straightforward if the volume name is preserved: remove the `storage` service and return the API direct mount to the prior Compose shape. The Docker volume remains intact and can be remounted by the old configuration.

## Open Questions

- Should the final implementation use `volumes_from: storage` for a stronger data-container expression, or keep explicit shared volume mounts for clearer modern Compose compatibility?
- Should the storage service image be plain `alpine`, `busybox`, or a tiny project-owned image with a checked-in init script?
- Should `make docker-down` print a reminder that storage is preserved and name the reset command for intentional deletion?
