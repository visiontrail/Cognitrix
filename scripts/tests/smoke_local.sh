#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

API_HOST="${API_HOST:-127.0.0.1}"
API_PORT="${API_PORT:-8000}"
WEB_HOST="${WEB_HOST:-127.0.0.1}"
WEB_PORT="${WEB_PORT:-3000}"
API_BASE_URL="http://${API_HOST}:${API_PORT}"
WEB_BASE_URL="http://${WEB_HOST}:${WEB_PORT}"

.venv/bin/python scripts/checks/env_check.py --web-env-file apps/web/.env --api-env-file apps/api/.env

API_LOG="/tmp/smarthrbi-smoke-api.log"
WEB_LOG="/tmp/smarthrbi-smoke-web.log"

bash scripts/dev_api.sh >"$API_LOG" 2>&1 &
API_PID=$!

bash scripts/dev_web.sh >"$WEB_LOG" 2>&1 &
WEB_PID=$!

cleanup() {
  kill "$API_PID" "$WEB_PID" >/dev/null 2>&1 || true
}

trap cleanup EXIT INT TERM

wait_http_ok() {
  local target="$1"
  local max_tries="$2"
  for _ in $(seq 1 "$max_tries"); do
    if curl -fsS "$target" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

if ! wait_http_ok "${API_BASE_URL}/healthz" 60; then
  echo "[smoke-local] API health check failed. Last logs:"
  tail -n 80 "$API_LOG" || true
  exit 1
fi

if ! wait_http_ok "${WEB_BASE_URL}" 90; then
  echo "[smoke-local] Web health check failed. Last logs:"
  tail -n 120 "$WEB_LOG" || true
  exit 1
fi

.venv/bin/python tests/smoke/run_smoke_flow.py \
  --api-base-url "$API_BASE_URL" \
  --web-base-url "$WEB_BASE_URL"

echo "[smoke-local] Completed"
