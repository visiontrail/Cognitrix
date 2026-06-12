#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -x ".venv/bin/python" ]]; then
  echo "[reset-local-data] Missing .venv/bin/python. Run: make bootstrap"
  exit 1
fi

.venv/bin/python scripts/maintenance/reset_local_data.py "$@"
