SHELL := /bin/bash

PYTHON_VERSION := 3.12
SEED := 20260819
DATABASE_PATH := data/generated/customer_signal.duckdb
BACKEND_HOST := 127.0.0.1
BACKEND_PORT := 8000
FRONTEND_HOST := 127.0.0.1
FRONTEND_PORT := 3000
API_BASE_URL := http://$(BACKEND_HOST):$(BACKEND_PORT)
ARTIFACT_DIRECTORY := data/run-artifacts
HACKATHON_SEED_PATH := data/seeding/hackathon-2week
ONBOARDED_SOURCES_DIR ?= $(HACKATHON_SEED_PATH)/onboarded-sources

.DEFAULT_GOAL := help
COMPOSE_FLAGS ?=
.PHONY: compose-init compose-up compose-verify compose-ps compose-down

compose-init:
	python3 scripts/compose.py init

compose-up:
	python3 scripts/compose.py up $(COMPOSE_FLAGS)

compose-verify:
	python3 scripts/compose.py verify

compose-ps:
	python3 scripts/compose.py ps

compose-down:
	python3 scripts/compose.py down

.PHONY: help setup seed seed-hackathon dev dev-auto dev-fixture dev-gemini dev-bedrock serve-backend-fixture serve-frontend test e2e e2e-generic e2e-legacy

help:
	@echo "make setup        의존성과 Playwright Chromium 설치"
	@echo "make seed         seed=$(SEED) 합성 DuckDB 생성"
	@echo "make seed-hackathon  개선 전후 2주 테이블형 합성 데이터 생성"
	@echo "make dev          해커톤 시딩 후 Bedrock 실행: investigator Sonnet 4.6, 나머지 Opus 4.6 (기본)"
	@echo "make dev-auto     API Key 유무로 모드를 고르는 auto 모드로 실행"
	@echo "make dev-bedrock  해커톤 시딩 후 Bedrock 전용 모드로 실행"
	@echo "make dev-fixture  결정론적 fixture 모드로 실행"
	@echo "make dev-gemini   Gemini 전용 모드로 실행"
	@echo "make test         Backend/Frontend 전체 자동 검증"
	@echo "make e2e          fixture 기반 실제 브라우저 E2E"
	@echo "make e2e-generic  범용 분석 Desktop/Mobile E2E"
	@echo "make e2e-legacy   기존 Journey 문구의 단일 Agent 호환 E2E"

setup:
	uv sync --project backend --python $(PYTHON_VERSION)
	npm --prefix frontend ci
	npm --prefix frontend run e2e:install

seed:
	uv run --project backend python -m customer_signal.data.cli \
		--database "$(DATABASE_PATH)" --seed "$(SEED)"

seed-hackathon:
	uv run --project backend python -m customer_signal.seeding.cli \
		--output "$(HACKATHON_SEED_PATH)" --seed 20260831 --force

dev: dev-bedrock

dev-auto:
	bash scripts/dev.sh auto

dev-fixture:
	bash scripts/dev.sh fixture

dev-gemini:
	bash scripts/dev.sh gemini

dev-bedrock: seed-hackathon
	ONBOARDED_SOURCES_DIR="$(ONBOARDED_SOURCES_DIR)" bash scripts/dev.sh bedrock

serve-backend-fixture: seed
	@set -Eeuo pipefail; \
		repository_dir="$$(git rev-parse --show-toplevel)"; \
		env_file="$${ENV_FILE:-}"; \
		if [[ -n "$$env_file" ]]; then \
			[[ "$$env_file" = /* ]] || env_file="$$repository_dir/$$env_file"; \
			if [[ ! -f "$$env_file" ]]; then \
				echo "ENV_FILE이 존재하지 않습니다: $$env_file" >&2; \
				exit 2; \
			fi; \
		elif [[ -f "$$repository_dir/.env" ]]; then \
			env_file="$$repository_dir/.env"; \
		elif [[ -f "$$repository_dir/backend/.env" ]]; then \
			env_file="$$repository_dir/backend/.env"; \
		else \
			common_dir="$$(git -C "$$repository_dir" rev-parse --git-common-dir)"; \
			[[ "$$common_dir" = /* ]] || common_dir="$$repository_dir/$$common_dir"; \
			main_checkout="$$(cd "$$(dirname "$$common_dir")" && pwd -P)"; \
			if [[ -f "$$main_checkout/.env" ]]; then \
				env_file="$$main_checkout/.env"; \
			elif [[ -f "$$main_checkout/backend/.env" ]]; then \
				env_file="$$main_checkout/backend/.env"; \
			fi; \
		fi; \
		env_args=(--no-env-file); \
		env_isolation=(env); \
		if [[ -n "$$env_file" ]]; then \
			env_args=(--env-file "$$env_file"); \
			env_isolation=( \
				env \
				-u LANGSMITH_PROJECT \
				-u LANGSMITH_TRACING \
				-u LANGSMITH_API_KEY \
				-u LANGSMITH_ENDPOINT \
				-u LANGSMITH_WORKSPACE_ID \
				-u LANGSMITH_TRACING_SAMPLING_RATE \
				-u LANGCHAIN_PROJECT \
				-u LANGCHAIN_TRACING_V2 \
				-u LANGCHAIN_API_KEY \
				-u LANGCHAIN_ENDPOINT \
				-u LANGCHAIN_TRACING_SAMPLING_RATE \
				-u LANGFUSE_SECRET_KEY \
				-u LANGFUSE_PUBLIC_KEY \
				-u LANGFUSE_BASE_URL \
				-u LANGFUSE_DEBUG \
				-u LANGFUSE_TRACING_ENVIRONMENT \
				-u LANGFUSE_RELEASE \
			); \
			printf 'Starting fixture Uvicorn: uv run --env-file %s ... --host %s --port %s\n' \
				"$$env_file" "$(BACKEND_HOST)" "$(BACKEND_PORT)"; \
		else \
			printf 'Starting fixture Uvicorn without an env file on %s:%s\n' \
				"$(BACKEND_HOST)" "$(BACKEND_PORT)"; \
		fi; \
		AGENT_MODE=fixture DATABASE_PATH="$(DATABASE_PATH)" \
			ARTIFACT_DIRECTORY="$(ARTIFACT_DIRECTORY)" \
			API_HOST="$(BACKEND_HOST)" API_PORT="$(BACKEND_PORT)" \
			FRONTEND_ORIGIN="http://$(FRONTEND_HOST):$(FRONTEND_PORT)" \
			"$${env_isolation[@]}" uv run "$${env_args[@]}" --project backend \
			uvicorn customer_signal.api:create_app --factory \
			--host "$(BACKEND_HOST)" --port "$(BACKEND_PORT)"

serve-frontend:
	NEXT_PUBLIC_API_BASE_URL="$(API_BASE_URL)" \
		env \
			-u GEMINI_API_KEY \
			-u GOOGLE_API_KEY -u AWS_BEARER_TOKEN_BEDROCK \
			-u GEMINI_MODEL \
			-u GEMINI_FALLBACK_MODEL \
			-u LANGSMITH_PROJECT \
			-u LANGSMITH_TRACING \
			-u LANGSMITH_API_KEY \
			-u LANGSMITH_ENDPOINT \
			-u LANGSMITH_WORKSPACE_ID \
			-u LANGSMITH_TRACING_SAMPLING_RATE \
			-u LANGCHAIN_PROJECT \
			-u LANGCHAIN_TRACING_V2 \
			-u LANGCHAIN_API_KEY \
			-u LANGCHAIN_ENDPOINT \
			-u LANGCHAIN_TRACING_SAMPLING_RATE \
			-u LANGFUSE_SECRET_KEY \
			-u LANGFUSE_PUBLIC_KEY \
			-u LANGFUSE_BASE_URL \
			-u LANGFUSE_DEBUG \
			-u LANGFUSE_TRACING_ENVIRONMENT \
			-u LANGFUSE_RELEASE \
			npm --prefix frontend run dev -- --port "$(FRONTEND_PORT)"

test:
	uv run --project backend pytest backend/tests -q
	uv run --project backend ruff check backend
	npm --prefix frontend test -- --run
	npm --prefix frontend run typecheck
	NEXT_PUBLIC_API_BASE_URL="$(API_BASE_URL)" npm --prefix frontend run build

e2e:
	npm --prefix frontend run e2e

e2e-generic:
	npm --prefix frontend run e2e -- generic-analysis.spec.ts

e2e-legacy:
	npm --prefix frontend run e2e -- working-demo.spec.ts
