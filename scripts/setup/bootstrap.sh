#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

copy_env() {
  local src="$1"
  local dst="$2"
  if [[ ! -f "$dst" ]]; then
    cp "$src" "$dst"
    echo "[bootstrap] Created $dst from template"
  fi
}

if [[ ! -d ".venv" ]]; then
  python3 -m venv .venv
  echo "[bootstrap] Created Python virtual environment at .venv"
fi

.venv/bin/python -m pip install --upgrade pip >/dev/null
.venv/bin/python -m pip install -r apps/api/requirements.txt -r requirements-dev.txt

copy_env apps/api/.env.example apps/api/.env
copy_env apps/web/.env.example apps/web/.env

if command -v pnpm >/dev/null 2>&1; then
  pnpm install --dir apps/web
else
  npm install --prefix apps/web
fi

echo "[bootstrap] Completed"
