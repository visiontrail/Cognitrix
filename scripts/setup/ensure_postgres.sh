#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -x ".venv/bin/python" ]]; then
  echo "[postgres] Missing virtual environment. Run: make bootstrap"
  exit 1
fi

if [[ "${SKIP_POSTGRES_BOOTSTRAP:-0}" == "1" ]]; then
  echo "[postgres] Skipped bootstrap by SKIP_POSTGRES_BOOTSTRAP=1"
  exit 0
fi

DATABASE_URL="${DATABASE_URL:-}"
if [[ -z "$DATABASE_URL" && -f "apps/api/.env" ]]; then
  DATABASE_URL="$(awk -F= '$1=="DATABASE_URL" {sub(/^[^=]*=/, "", $0); print $0; exit}' apps/api/.env)"
fi

if [[ -z "$DATABASE_URL" ]]; then
  echo "[postgres] DATABASE_URL is not set and apps/api/.env has no DATABASE_URL"
  exit 1
fi

read_host_port() {
  local database_url="$1"
  .venv/bin/python - "$database_url" <<'PY'
from urllib.parse import urlparse
import sys

url = urlparse(sys.argv[1])
host = url.hostname or "127.0.0.1"
port = int(url.port or 5432)
print(host)
print(port)
PY
}

check_tcp() {
  local host="$1"
  local port="$2"
  .venv/bin/python - "$host" "$port" <<'PY'
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])
try:
    with socket.create_connection((host, port), timeout=1.2):
        pass
except OSError:
    sys.exit(1)
PY
}

HOST_AND_PORT="$(read_host_port "$DATABASE_URL")"
DB_HOST="$(echo "$HOST_AND_PORT" | sed -n '1p')"
DB_PORT="$(echo "$HOST_AND_PORT" | sed -n '2p')"

if check_tcp "$DB_HOST" "$DB_PORT"; then
  echo "[postgres] Reachable at ${DB_HOST}:${DB_PORT}"
  exit 0
fi

if [[ "$DB_HOST" != "127.0.0.1" && "$DB_HOST" != "localhost" ]]; then
  echo "[postgres] PostgreSQL ${DB_HOST}:${DB_PORT} is unreachable and auto-start only supports localhost"
  exit 1
fi

if [[ "${DISABLE_DOCKER_POSTGRES_BOOTSTRAP:-0}" == "1" ]]; then
  echo "[postgres] PostgreSQL is not reachable at ${DB_HOST}:${DB_PORT}, and Docker auto-start is disabled"
  echo "[postgres] Please start local PostgreSQL manually for debug mode"
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "[postgres] PostgreSQL is not reachable at ${DB_HOST}:${DB_PORT}, and Docker is unavailable for auto-start"
  exit 1
fi

echo "[postgres] Starting local postgres container via docker compose"
docker compose up -d postgres

for _ in $(seq 1 30); do
  if check_tcp "$DB_HOST" "$DB_PORT"; then
    echo "[postgres] Ready at ${DB_HOST}:${DB_PORT}"
    exit 0
  fi
  sleep 1
done

echo "[postgres] Failed to start postgres within timeout"
exit 1
