#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/docker.sh"

require_docker
ensure_env_file

cd "${PROJECT_ROOT}"

echo "[docker-restart] Restarting Cognitrix Docker stack..."
compose down --remove-orphans
compose up -d --build

echo
compose ps
print_endpoints
