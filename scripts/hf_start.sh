#!/usr/bin/env bash
# Startup script for Hugging Face Spaces deployment.
# Launches FastAPI (internal :8000) + Next.js (:7860) via supervisord.
set -euo pipefail

export HOME=/home/user
cd "$HOME/app"

# Ensure data directories exist
mkdir -p data/uploads/state

# Inject HF Spaces secrets into the supervisor environment.
# Secrets set in the Space Settings are available as env vars at runtime.
# The supervisord config references env vars with %(ENV_XXX)s syntax for
# the ones it sets inline; for the rest, we export them so child processes
# inherit them automatically.

# Export all HF-provided secrets so supervisord children inherit them
export AI_API_KEY="${AI_API_KEY:-}"
export AI_MODEL="${AI_MODEL:-deepseek-chat}"
export MODEL_PROVIDER_URL="${MODEL_PROVIDER_URL:-https://api.deepseek.com}"
export AI_TIMEOUT_SECONDS="${AI_TIMEOUT_SECONDS:-120}"
export ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL:-https://api.deepseek.com/anthropic}"
export ANTHROPIC_AUTH_TOKEN="${ANTHROPIC_AUTH_TOKEN:-}"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="${ANTHROPIC_DEFAULT_HAIKU_MODEL:-deepseek-chat}"
export AUTH_SECRET="${AUTH_SECRET:-hf-cognitrix-secret}"
export AUTH_BOOTSTRAP_ADMIN_EMAIL="${AUTH_BOOTSTRAP_ADMIN_EMAIL:-}"
export AUTH_BOOTSTRAP_ADMIN_PASSWORD="${AUTH_BOOTSTRAP_ADMIN_PASSWORD:-}"
export APP_URL="${APP_URL:-}"
export AGENT_MAX_TOOL_STEPS="${AGENT_MAX_TOOL_STEPS:-20}"
export AGENT_MAX_SQL_ROWS="${AGENT_MAX_SQL_ROWS:-2000}"
export AGENT_MAX_SQL_SCAN_ROWS="${AGENT_MAX_SQL_SCAN_ROWS:-10000}"
export AGENT_TIMEOUT_SECONDS="${AGENT_TIMEOUT_SECONDS:-120}"

exec supervisord -c /etc/supervisor/conf.d/cognitrix.conf
