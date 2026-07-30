#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
COMPOSE_FILE="${PROJECT_ROOT}/docker-compose.yml"
ENV_TEMPLATE="${PROJECT_ROOT}/.env.example"
ENV_FILE="${PROJECT_ROOT}/.env"

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  echo "[docker] Docker Compose is not installed. Install Docker Compose v2 or docker-compose." >&2
  exit 1
fi

# Compose interpolation prefers the invoking shell's environment over the
# project .env. Shells that run Anthropic tooling export ANTHROPIC_BASE_URL,
# ANTHROPIC_AUTH_TOKEN and API_TIMEOUT_MS, which silently replaced the values in
# .env and pointed the container's agent SDK at the wrong endpoint (every agent
# turn then failed with HTTP 401, reported by the SDK as ordinary model text).
# The .env file is the single source of truth for the stack, so drop these from
# the environment handed to compose.
HOST_ENV_SHADOWED_VARS=(
  ANTHROPIC_BASE_URL
  ANTHROPIC_AUTH_TOKEN
  ANTHROPIC_API_KEY
  ANTHROPIC_MODEL
  ANTHROPIC_DEFAULT_HAIKU_MODEL
  ANTHROPIC_SMALL_FAST_MODEL
  API_TIMEOUT_MS
)

warn_shadowed_host_env() {
  local var
  for var in "${HOST_ENV_SHADOWED_VARS[@]}"; do
    if [[ -n "${!var:-}" ]]; then
      echo "[docker] Ignoring host env ${var}; the value in .env is used instead." >&2
    fi
  done
}

compose() {
  local unset_args=()
  local var
  for var in "${HOST_ENV_SHADOWED_VARS[@]}"; do
    unset_args+=(-u "${var}")
  done
  env "${unset_args[@]}" "${COMPOSE[@]}" -f "${COMPOSE_FILE}" "$@"
}

require_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "[docker] Docker is not installed." >&2
    exit 1
  fi

  if ! docker info >/dev/null 2>&1; then
    echo "[docker] Docker daemon is not reachable. Start Docker first." >&2
    exit 1
  fi
}

ensure_env_file() {
  warn_shadowed_host_env
  if [[ ! -f "${ENV_FILE}" ]]; then
    if [[ ! -f "${ENV_TEMPLATE}" ]]; then
      echo "[docker] Missing env template: ${ENV_TEMPLATE}" >&2
      exit 1
    fi
    cp "${ENV_TEMPLATE}" "${ENV_FILE}"
    echo "[docker] Created .env from .env.example. Fill AI/auth secrets before shared testing."
  fi
}

env_value() {
  local key="$1"
  local default="$2"
  local value="${!key:-}"

  if [[ -z "${value}" && -f "${ENV_FILE}" ]]; then
    value="$(
      awk -F= -v key="${key}" '
        $0 !~ /^[[:space:]]*#/ && $1 == key {
          sub(/^[^=]*=/, "")
          print
          exit
        }
      ' "${ENV_FILE}"
    )"
    value="${value%\"}"
    value="${value#\"}"
    value="${value%\'}"
    value="${value#\'}"
  fi

  if [[ -n "${value}" ]]; then
    printf '%s' "${value}"
  else
    printf '%s' "${default}"
  fi
}

print_endpoints() {
  local api_port web_port app_url
  api_port="$(env_value API_PORT 8000)"
  web_port="$(env_value WEB_PORT 3000)"
  app_url="$(env_value APP_URL "http://localhost:${web_port}")"

  echo
  echo "Endpoints:"
  echo "  Web:        ${app_url}"
  echo "  API:        http://localhost:${api_port}"
  echo "  Health:     http://localhost:${api_port}/healthz"
  echo "  API docs:   http://localhost:${api_port}/docs"
}
