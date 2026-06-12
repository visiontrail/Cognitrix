#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

.venv/bin/python -m compileall -q apps/api
npm run --prefix apps/web lint

echo "[lint] Completed"
