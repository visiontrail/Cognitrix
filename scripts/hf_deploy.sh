#!/usr/bin/env bash
# Deploy Cognitrix to Hugging Face Spaces.
#
# Prerequisites:
#   - hf CLI installed and authenticated (hf login)
#   - Space already created: https://huggingface.co/spaces/LeoGuo/CogniTrix
#
# Usage:
#   ./scripts/hf_deploy.sh                    # defaults
#   HF_SPACE=LeoGuo/CogniTrix ./scripts/hf_deploy.sh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

HF_SPACE="${HF_SPACE:-LeoGuo/CogniTrix}"
DEPLOY_BRANCH="${DEPLOY_BRANCH:-main}"
DEPLOY_DIR="$(mktemp -d)"

echo "[hf-deploy] Space: ${HF_SPACE}"
echo "[hf-deploy] Staging in: ${DEPLOY_DIR}"

# Clone the HF Space repo (sparse — only metadata)
git clone --depth 1 "https://huggingface.co/spaces/${HF_SPACE}" "$DEPLOY_DIR" 2>/dev/null || {
  echo "[hf-deploy] Initializing fresh Space repo..."
  mkdir -p "$DEPLOY_DIR"
  cd "$DEPLOY_DIR"
  git init
  git remote add origin "https://huggingface.co/spaces/${HF_SPACE}"
  cd "$ROOT_DIR"
}

# Clean deploy dir (keep .git)
find "$DEPLOY_DIR" -mindepth 1 -maxdepth 1 ! -name '.git' -exec rm -rf {} +

# Copy project files needed for the Docker build
rsync -a --exclude='.git' \
         --exclude='.venv' \
         --exclude='node_modules' \
         --exclude='.next' \
         --exclude='__pycache__' \
         --exclude='.pytest_cache' \
         --exclude='apps/api/data' \
         --exclude='*.pyc' \
         --exclude='.DS_Store' \
         --exclude='logs' \
         --exclude='coverage' \
         --exclude='test-results' \
         --exclude='.env' \
         --exclude='.env.local' \
         "$ROOT_DIR/" "$DEPLOY_DIR/"

# Rename Dockerfile.hf → Dockerfile for HF Spaces (HF expects "Dockerfile")
cp "$DEPLOY_DIR/Dockerfile.hf" "$DEPLOY_DIR/Dockerfile"

# Write the HF Space README (metadata header)
cat > "$DEPLOY_DIR/README.md" << 'HFREADME'
---
title: CogniTrix
emoji: 📊
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
fullWidth: true
---

# CogniTrix — AI-Native BI & Analytics Platform

Upload Excel → Ask in natural language → Get charts & dashboards.

An open-source, AI-native business intelligence platform that turns any structured
spreadsheet into an interactive analytics workspace.

## Setup

Set these **Secrets** in the Space Settings:

| Secret | Required | Description |
|--------|----------|-------------|
| `AI_API_KEY` | Yes | API key for your LLM provider (DeepSeek, OpenAI-compatible, etc.) |
| `AUTH_BOOTSTRAP_ADMIN_EMAIL` | Recommended | Admin account email for first-time setup |
| `AUTH_BOOTSTRAP_ADMIN_PASSWORD` | Recommended | Admin account password |
| `AUTH_SECRET` | Recommended | JWT signing secret (auto-generated if empty) |

Optional secrets: `MODEL_PROVIDER_URL`, `AI_MODEL`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL`.

## Usage

1. Register or log in with the admin account
2. Upload an Excel file via the ingestion panel
3. Ask questions in natural language — get charts and dashboards instantly
HFREADME

cd "$DEPLOY_DIR"

# Configure git for HF
git add -A
git status

CHANGES=$(git diff --cached --stat)
if [ -z "$CHANGES" ]; then
  echo "[hf-deploy] No changes to deploy."
  rm -rf "$DEPLOY_DIR"
  exit 0
fi

echo ""
echo "[hf-deploy] Changes to deploy:"
echo "$CHANGES" | tail -5
echo ""
read -rp "[hf-deploy] Push to ${HF_SPACE}? [y/N] " confirm
if [[ "$confirm" != [yY]* ]]; then
  echo "[hf-deploy] Aborted."
  rm -rf "$DEPLOY_DIR"
  exit 0
fi

git commit -m "Deploy Cognitrix to HF Spaces"
git push origin "${DEPLOY_BRANCH}" --force

echo "[hf-deploy] Deployed! https://huggingface.co/spaces/${HF_SPACE}"

# Cleanup
rm -rf "$DEPLOY_DIR"
