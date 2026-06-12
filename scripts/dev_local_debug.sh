#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -x ".venv/bin/python" ]]; then
  echo "[dev-local] Missing virtual environment. Run: make bootstrap"
  exit 1
fi

LOG_DIR="${DEV_LOG_DIR:-$ROOT_DIR/logs/dev-local}"
mkdir -p "$LOG_DIR"

export API_LOG_FILE="${API_LOG_FILE:-$LOG_DIR/api.log}"
export WEB_LOG_FILE="${WEB_LOG_FILE:-$LOG_DIR/web.log}"

# Bind to all interfaces to allow local LAN access
export API_HOST="0.0.0.0"
export WEB_HOST="0.0.0.0"


echo "[dev-local] Validating environment variables"
.venv/bin/python scripts/checks/env_check.py --web-env-file apps/web/.env --api-env-file apps/api/.env

echo "[dev-local] Starting local debug stack (web + api)"
echo "[dev-local] API log: $API_LOG_FILE"
echo "[dev-local] Web log: $WEB_LOG_FILE"
bash scripts/dev_all.sh
