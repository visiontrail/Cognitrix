#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

.venv/bin/python scripts/checks/env_check.py --web-env-file apps/web/.env --api-env-file apps/api/.env
.venv/bin/python -m compileall -q apps/api
npm run --prefix apps/web build

echo "[build] Completed"
