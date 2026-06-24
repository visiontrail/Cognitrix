#!/usr/bin/env bash
# Verify that the Docker restart/rebuild workflow preserves persistent storage.
#
# It writes a sentinel file and a state-directory marker into the storage
# volume (via the running storage container), runs the normal restart workflow,
# and asserts both survive with identical contents and that state/ is still
# writable. This is the runtime proof that "restart the app" is not "destroy
# data".
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../lib/docker.sh"

require_docker
ensure_env_file

cd "${PROJECT_ROOT}"

STORAGE_SERVICE="storage"
API_SERVICE="api"
SENTINEL_PATH="/storage/uploads/.persistence_sentinel"
STATE_MARKER_PATH="/storage/uploads/state/.persistence_state_marker"
API_SENTINEL_PATH="/app/data/uploads/.persistence_api_sentinel"
API_SENTINEL_STORAGE_PATH="/storage/uploads/.persistence_api_sentinel"
SENTINEL_CONTENT="cognitrix-persistence-$(date +%s)-$$"

fail() {
  echo "[docker-persistence] FAIL: $*" >&2
  exit 1
}

echo "[docker-persistence] Bringing up the stack (storage owns the volume)..."
compose up -d --build

# Wait for the storage service to report healthy before writing markers.
echo "[docker-persistence] Waiting for storage service to become healthy..."
for _ in $(seq 1 30); do
  status="$(compose ps "${STORAGE_SERVICE}" --format '{{.Health}}' 2>/dev/null || true)"
  if [[ "${status}" == "healthy" ]]; then
    break
  fi
  sleep 2
done

echo "[docker-persistence] Waiting for API service to become healthy..."
for _ in $(seq 1 30); do
  status="$(compose ps "${API_SERVICE}" --format '{{.Health}}' 2>/dev/null || true)"
  if [[ "${status}" == "healthy" ]]; then
    break
  fi
  sleep 2
done

echo "[docker-persistence] Writing sentinel and state marker into the volume..."
compose exec -T "${STORAGE_SERVICE}" /bin/sh -c \
  "printf '%s' '${SENTINEL_CONTENT}' > '${SENTINEL_PATH}' \
   && mkdir -p /storage/uploads/state \
   && printf '%s' '${SENTINEL_CONTENT}' > '${STATE_MARKER_PATH}'" \
  || fail "could not write sentinel/state marker"

echo "[docker-persistence] Writing API sentinel through UPLOAD_DIR..."
compose exec -T "${API_SERVICE}" /bin/sh -c \
  "test \"\${UPLOAD_DIR}\" = '/app/data/uploads' \
   && test \"\${DATABASE_URL}\" = 'sqlite:////app/data/uploads/state/ai_views.sqlite3' \
   && printf '%s' '${SENTINEL_CONTENT}' > '${API_SENTINEL_PATH}'" \
  || fail "api is not configured to write persistent state under /app/data/uploads"

echo "[docker-persistence] Running the normal restart/rebuild workflow..."
bash scripts/docker_restart.sh

# Re-wait for storage health after restart.
for _ in $(seq 1 30); do
  status="$(compose ps "${STORAGE_SERVICE}" --format '{{.Health}}' 2>/dev/null || true)"
  if [[ "${status}" == "healthy" ]]; then
    break
  fi
  sleep 2
done

for _ in $(seq 1 30); do
  status="$(compose ps "${API_SERVICE}" --format '{{.Health}}' 2>/dev/null || true)"
  if [[ "${status}" == "healthy" ]]; then
    break
  fi
  sleep 2
done

echo "[docker-persistence] Verifying sentinel survived..."
after_sentinel="$(compose exec -T "${STORAGE_SERVICE}" /bin/sh -c "cat '${SENTINEL_PATH}' 2>/dev/null || true")"
[[ "${after_sentinel}" == "${SENTINEL_CONTENT}" ]] \
  || fail "sentinel missing or changed after restart (got: '${after_sentinel}')"

echo "[docker-persistence] Verifying state/ marker survived..."
after_state="$(compose exec -T "${STORAGE_SERVICE}" /bin/sh -c "cat '${STATE_MARKER_PATH}' 2>/dev/null || true")"
[[ "${after_state}" == "${SENTINEL_CONTENT}" ]] \
  || fail "state marker missing or changed after restart (got: '${after_state}')"

echo "[docker-persistence] Verifying API-written marker survived in the shared volume..."
after_api_sentinel="$(compose exec -T "${STORAGE_SERVICE}" /bin/sh -c "cat '${API_SENTINEL_STORAGE_PATH}' 2>/dev/null || true")"
[[ "${after_api_sentinel}" == "${SENTINEL_CONTENT}" ]] \
  || fail "api marker missing or changed after restart (got: '${after_api_sentinel}')"

echo "[docker-persistence] Verifying state/ remains writable after restart..."
compose exec -T "${STORAGE_SERVICE}" /bin/sh -c \
  "touch /storage/uploads/state/.persistence_writecheck && rm -f /storage/uploads/state/.persistence_writecheck" \
  || fail "state/ is not writable after restart"

# Clean up the markers we created so the volume is left as we found it.
compose exec -T "${STORAGE_SERVICE}" /bin/sh -c \
  "rm -f '${SENTINEL_PATH}' '${STATE_MARKER_PATH}' '${API_SENTINEL_STORAGE_PATH}'" || true

echo "[docker-persistence] PASS: restart preserved storage and API-written data, and state/ is writable."
