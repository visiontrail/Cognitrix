#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/docker.sh"

require_docker
ensure_env_file

cd "${PROJECT_ROOT}"

echo "[docker-restart] Restarting Cognitrix Docker stack..."
echo "[docker-restart] Persistent storage volume 'cognitrix_upload_data' is preserved; this restart never deletes data."
compose down --remove-orphans
compose up -d --build

echo
compose ps
print_endpoints
echo
echo "[docker-restart] Uploads, DuckDB, and SQLite state under the storage volume were preserved."
echo "[docker-restart] To intentionally delete persisted Docker data, run:"
echo "                 .venv/bin/python scripts/maintenance/reset_local_data.py --include-docker-volumes"
