#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "[dev-api] Missing virtual environment. Run: make bootstrap"
  exit 1
fi

source "$ROOT_DIR/scripts/lib/env.sh"
API_ENV_FILE="${API_ENV_FILE:-$ROOT_DIR/apps/api/.env}"
export API_ENV_FILE
echo "[dev-api] Loading API env: $API_ENV_FILE"
load_env_file "$API_ENV_FILE"

HOST="${API_HOST:-127.0.0.1}"
PORT="${API_PORT:-8000}"
BASE_CMD=("$PYTHON_BIN" -m uvicorn apps.api.main:app --host "$HOST" --port "$PORT")
LOG_FILE="${API_LOG_FILE:-}"

if [[ -n "$LOG_FILE" ]]; then
  mkdir -p "$(dirname "$LOG_FILE")"
  : >"$LOG_FILE"
  exec > >(tee -a "$LOG_FILE") 2>&1
fi

if [[ "${ONE_SHOT:-0}" == "1" ]]; then
  LOG_FILE="${LOG_FILE:-/tmp/smarthrbi-dev-api.log}"
  "${BASE_CMD[@]}" >"$LOG_FILE" 2>&1 &
  PID=$!
  trap 'kill "$PID" >/dev/null 2>&1 || true' EXIT

  for _ in $(seq 1 40); do
    if curl -fsS "http://$HOST:$PORT/healthz" >/dev/null; then
      echo "[dev-api] Health check passed: http://$HOST:$PORT/healthz"
      exit 0
    fi
    sleep 1
  done

  echo "[dev-api] Health check failed. Last logs:"
  tail -n 40 "$LOG_FILE" || true
  exit 1
fi

exec "${BASE_CMD[@]}" --reload --reload-exclude "apps/api/data"
