SHELL := /bin/bash
.DEFAULT_GOAL := help

.PHONY: help bootstrap env-check lint test build dev dev-local dev-web dev-api smoke smoke-local smoke-docker test-all docker-start docker-restart docker-up docker-down reset-local-data hf-deploy

help: ## Show all available commands
	@awk 'BEGIN {FS = ":.*##"; print "Available targets:"} /^[a-zA-Z0-9_-]+:.*##/ {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

bootstrap: ## Install dependencies and initialize local env files
	@bash scripts/setup/bootstrap.sh

env-check: ## Validate required environment variables for web/api
	@.venv/bin/python scripts/checks/env_check.py --web-env-file apps/web/.env --api-env-file apps/api/.env

lint: ## Run lint/compile checks
	@bash scripts/checks/lint.sh

test: ## Run automated tests
	@bash scripts/tests/test.sh

build: ## Build web and verify backend compile
	@bash scripts/checks/build.sh

dev: ## Run web/api locally
	@bash scripts/dev_all.sh

dev-local: ## Run local debug stack with local logs
	@bash scripts/dev_local_debug.sh

dev-web: ## Run Next.js frontend dev server
	@bash scripts/dev_web.sh

dev-api: ## Run FastAPI dev server
	@bash scripts/dev_api.sh

smoke: ## Alias of smoke-local
	@bash scripts/tests/smoke_local.sh

smoke-local: ## Run local end-to-end smoke flow (upload -> query -> save -> share)
	@bash scripts/tests/smoke_local.sh

smoke-docker: ## Run docker end-to-end smoke flow
	@bash scripts/tests/smoke_docker.sh

test-all: ## Run lint/test/build plus local smoke flow
	@bash scripts/tests/test_all.sh

docker-start: ## Start docker compose stack and print endpoints
	@bash scripts/docker_start.sh

docker-restart: ## Restart docker compose stack and print endpoints
	@bash scripts/docker_restart.sh

docker-up: ## Start docker compose stack
	@bash scripts/docker_up.sh

docker-down: ## Stop docker compose stack
	@bash scripts/docker_down.sh

docker-publish: ## Build and push api+web images to Docker Hub (DOCKER_USER / TAG env vars)
	@bash scripts/docker_publish.sh

reset-local-data: ## Clear local runtime databases, uploads, logs, and test artifacts
	@bash scripts/maintenance/reset_local_data.sh

hf-deploy: ## Deploy to Hugging Face Spaces (HF_SPACE env var, default LeoGuo/CogniTrix)
	@bash scripts/hf_deploy.sh
