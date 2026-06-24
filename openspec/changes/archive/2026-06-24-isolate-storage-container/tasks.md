## 1. Storage Volume Discovery And Compatibility

- [x] 1.1 Inspect the current Compose-generated Docker volume name for `cognitrix_upload_data` and record the expected preserved name in implementation notes or docs.
- [x] 1.2 Decide whether to keep direct shared volume mounts or use `volumes_from: storage`, then apply the same decision consistently to root and infra Compose files.
- [x] 1.3 Ensure the implementation reuses the existing upload/state volume without deleting or replacing current contents.
- [x] 1.4 If a volume rename is required, add a documented migration command that copies data from the old volume to the new volume before startup.

## 2. Docker Storage Service

- [x] 2.1 Add a dedicated `storage` service to `docker-compose.yml` that mounts the persistent data volume and runs lightweight initialization.
- [x] 2.2 Add the same `storage` service topology to `infra/docker/docker-compose.yml`.
- [x] 2.3 Make the storage service create required directories such as `state`, `audit`, and runtime upload parents without deleting existing files.
- [x] 2.4 Add a storage healthcheck that verifies the mounted directory and `state` path are writable.
- [x] 2.5 Update the API service dependency graph so API startup waits for healthy storage.
- [x] 2.6 Keep Docker `UPLOAD_DIR` and default SQLite `DATABASE_URL` compatible with `/app/data/uploads`.

## 3. Lifecycle Scripts And Reset Boundaries

- [x] 3.1 Audit `scripts/docker_restart.sh`, `scripts/docker_up.sh`, `scripts/docker_down.sh`, and `scripts/lib/docker.sh` for any accidental destructive storage behavior.
- [x] 3.2 Keep restart/start/down workflows free of `--volumes`, reset calls, or direct deletion of persistent storage paths.
- [x] 3.3 Add operator-facing output to restart/down scripts that states persistent storage is preserved and names the explicit reset workflow.
- [x] 3.4 Verify `scripts/maintenance/reset_local_data.py` remains the only Docker-volume deletion path and still requires `--include-docker-volumes` plus confirmation or `--yes`.

## 4. Verification

- [x] 4.1 Add a Docker persistence script or test that creates a sentinel file in the persistent storage volume.
- [x] 4.2 Make the persistence verification run the normal restart/rebuild workflow and assert the sentinel file still exists with the same contents.
- [x] 4.3 Extend verification to assert `state/` survives restart and remains writable after restart.
- [x] 4.4 Add configuration/script tests that validate the Compose topology contains the `storage` service and that normal restart/down commands do not request volume deletion.
- [x] 4.5 Run the relevant script tests and, where Docker is available, the Docker persistence verification.

## 5. Documentation

- [x] 5.1 Document the storage container role, retained data paths, and the fact that app restarts preserve data.
- [x] 5.2 Document the explicit destructive reset command path for deleting persisted Docker data.
- [x] 5.3 Update any Docker setup or troubleshooting notes that currently imply storage belongs to the API container.

## Implementation Notes

- **1.1 Preserved volume name:** The live volume is `cognitrix_cognitrix_upload_data`
  (Compose project `name: cognitrix` + volume key `cognitrix_upload_data`),
  confirmed via `docker volume ls` and `docker compose config`. The key was kept
  unchanged so the generated name is identical. Recorded in compose comments and
  the README "Persistent Storage Container" section.
- **1.2 Mount strategy:** Kept explicit shared volume mounts (not `volumes_from`)
  for clear Compose v2 compatibility, applied identically to `docker-compose.yml`
  and `infra/docker/docker-compose.yml`. The `storage` service mounts the volume
  at `/storage/uploads`; the `api` service keeps `/app/data/uploads`.
- **1.4 No migration required:** Because the volume key/identity is preserved,
  no rename and therefore no copy-migration is needed. Documented the
  preserved-identity decision in compose comments and README.
- **Storage image:** `alpine:3.20` with an inline `mkdir -p` init + `tail -f`
  keep-alive (no project-owned image needed).
- **4.5 Verification:** `tests/scripts/test_docker_storage_topology.py` (14
  config/script guards) and the full `tests/scripts` suite pass. The live 6-hour
  stack was NOT torn down; instead the exact storage init command, restart-safe
  re-init, named-volume survival across container recreation, and the exact
  healthcheck command were verified in isolation on a throwaway volume (all
  PASS). `scripts/tests/docker_persistence.sh` is the full end-to-end check to
  run against a Docker host when a live restart is acceptable.
