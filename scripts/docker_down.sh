#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/docker.sh"

require_docker

cd "${PROJECT_ROOT}"

echo "[docker-down] Stopping Cognitrix Docker stack..."
echo "[docker-down] Persistent storage volume 'cognitrix_upload_data' is preserved; this stop never deletes data."
compose down --remove-orphans
echo
echo "[docker-down] Uploads, DuckDB, and SQLite state under the storage volume were preserved."
echo "[docker-down] To intentionally delete persisted Docker data, run:"
echo "              .venv/bin/python scripts/maintenance/reset_local_data.py --include-docker-volumes"
