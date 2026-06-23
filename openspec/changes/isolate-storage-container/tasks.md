## 1. Storage Volume Discovery And Compatibility

- [ ] 1.1 Inspect the current Compose-generated Docker volume name for `cognitrix_upload_data` and record the expected preserved name in implementation notes or docs.
- [ ] 1.2 Decide whether to keep direct shared volume mounts or use `volumes_from: storage`, then apply the same decision consistently to root and infra Compose files.
- [ ] 1.3 Ensure the implementation reuses the existing upload/state volume without deleting or replacing current contents.
- [ ] 1.4 If a volume rename is required, add a documented migration command that copies data from the old volume to the new volume before startup.

## 2. Docker Storage Service

- [ ] 2.1 Add a dedicated `storage` service to `docker-compose.yml` that mounts the persistent data volume and runs lightweight initialization.
- [ ] 2.2 Add the same `storage` service topology to `infra/docker/docker-compose.yml`.
- [ ] 2.3 Make the storage service create required directories such as `state`, `audit`, and runtime upload parents without deleting existing files.
- [ ] 2.4 Add a storage healthcheck that verifies the mounted directory and `state` path are writable.
- [ ] 2.5 Update the API service dependency graph so API startup waits for healthy storage.
- [ ] 2.6 Keep Docker `UPLOAD_DIR` and default SQLite `DATABASE_URL` compatible with `/app/data/uploads`.

## 3. Lifecycle Scripts And Reset Boundaries

- [ ] 3.1 Audit `scripts/docker_restart.sh`, `scripts/docker_up.sh`, `scripts/docker_down.sh`, and `scripts/lib/docker.sh` for any accidental destructive storage behavior.
- [ ] 3.2 Keep restart/start/down workflows free of `--volumes`, reset calls, or direct deletion of persistent storage paths.
- [ ] 3.3 Add operator-facing output to restart/down scripts that states persistent storage is preserved and names the explicit reset workflow.
- [ ] 3.4 Verify `scripts/maintenance/reset_local_data.py` remains the only Docker-volume deletion path and still requires `--include-docker-volumes` plus confirmation or `--yes`.

## 4. Verification

- [ ] 4.1 Add a Docker persistence script or test that creates a sentinel file in the persistent storage volume.
- [ ] 4.2 Make the persistence verification run the normal restart/rebuild workflow and assert the sentinel file still exists with the same contents.
- [ ] 4.3 Extend verification to assert `state/` survives restart and remains writable after restart.
- [ ] 4.4 Add configuration/script tests that validate the Compose topology contains the `storage` service and that normal restart/down commands do not request volume deletion.
- [ ] 4.5 Run the relevant script tests and, where Docker is available, the Docker persistence verification.

## 5. Documentation

- [ ] 5.1 Document the storage container role, retained data paths, and the fact that app restarts preserve data.
- [ ] 5.2 Document the explicit destructive reset command path for deleting persisted Docker data.
- [ ] 5.3 Update any Docker setup or troubleshooting notes that currently imply storage belongs to the API container.
