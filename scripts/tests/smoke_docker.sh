#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../lib/docker.sh"

require_docker
ensure_env_file

cd "${PROJECT_ROOT}"

API_BASE_URL="${DOCKER_API_BASE_URL:-http://127.0.0.1:8000}"
WEB_BASE_URL="${DOCKER_WEB_BASE_URL:-http://127.0.0.1:3000}"

cleanup() {
  if [[ "${KEEP_DOCKER_STACK:-0}" != "1" ]]; then
    compose down --remove-orphans >/dev/null 2>&1 || true
  fi
}

trap cleanup EXIT INT TERM

compose up -d --build

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

if ! wait_http_ok "${API_BASE_URL}/healthz" 90; then
  echo "[smoke-docker] API health check failed"
  compose ps
  compose logs api --tail=200 || true
  exit 1
fi

if ! wait_http_ok "${WEB_BASE_URL}" 120; then
  echo "[smoke-docker] Web health check failed"
  compose ps
  compose logs web --tail=200 || true
  exit 1
fi

.venv/bin/python tests/smoke/run_smoke_flow.py \
  --api-base-url "$API_BASE_URL" \
  --web-base-url "$WEB_BASE_URL"

echo "[smoke-docker] Completed"
