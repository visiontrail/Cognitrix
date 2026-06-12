#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

.venv/bin/python -m pytest tests -q

if [[ "${RUN_WEB_TESTS:-0}" == "1" ]]; then
  npm run --prefix apps/web test
else
  echo "[test] Web unit tests skipped (set RUN_WEB_TESTS=1 to enable)"
fi

echo "[test] Completed"
