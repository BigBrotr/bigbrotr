# ============================================================================
# BigBrotr Development Makefile
# ============================================================================

.DEFAULT_GOAL := help
.PHONY: help install pre-commit lint format format-check typecheck test test-unit test-integration test-fast coverage audit sql-generate sql-check ci docs docs-serve build docker-build docker-up docker-down clean

DEPLOYMENT ?= bigbrotr

# --------------------------------------------------------------------------
# Development
# --------------------------------------------------------------------------

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install package with dev dependencies and pre-commit hooks
	uv sync --group dev --group docs
	pre-commit install

pre-commit: ## Run all pre-commit hooks on all files
	pre-commit run --all-files

lint: ## Run ruff linter
	ruff check src/ tests/

format: ## Format code with ruff
	ruff format src/ tests/

format-check: ## Check formatting without modifying files
	ruff format --check src/ tests/

typecheck: ## Run mypy type checker
	mypy src/bigbrotr

# --------------------------------------------------------------------------
# Testing
# --------------------------------------------------------------------------

test: test-unit ## Run unit tests (alias for test-unit)

test-unit: ## Run unit tests
	pytest tests/ --ignore=tests/integration/

test-integration: ## Run integration tests (requires Docker)
	pytest tests/integration/

test-fast: ## Run unit tests without slow markers
	pytest tests/ --ignore=tests/integration/ -m "not slow"

coverage: ## Run unit tests with coverage report
	pytest tests/ --ignore=tests/integration/ --cov=src/bigbrotr --cov-report=term-missing --cov-report=html

# --------------------------------------------------------------------------
# Quality
# --------------------------------------------------------------------------

audit: ## Run uv-secure for dependency vulnerabilities
	uv-secure uv.lock

sql-generate: ## Regenerate SQL from templates
	python3 tools/generate_sql.py

sql-check: ## Verify generated SQL matches templates
	python3 tools/generate_sql.py --check

ci: lint format-check typecheck test-unit sql-check audit ## Run all quality checks

# --------------------------------------------------------------------------
# Documentation
# --------------------------------------------------------------------------

docs: ## Build documentation site (strict mode)
	mkdocs build --strict

docs-serve: ## Serve documentation locally with live reload
	mkdocs serve

# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------

build: ## Build Python package (sdist + wheel)
	uv build

# --------------------------------------------------------------------------
# Docker
# --------------------------------------------------------------------------

docker-build: ## Build Docker image (DEPLOYMENT=bigbrotr|lilbrotr)
	docker build -f deployments/Dockerfile --build-arg DEPLOYMENT=$(DEPLOYMENT) -t $(DEPLOYMENT):latest .

docker-up: ## Start deployment stack (DEPLOYMENT=bigbrotr|lilbrotr)
	docker compose -f deployments/$(DEPLOYMENT)/docker-compose.yaml up -d

docker-down: ## Stop deployment stack (DEPLOYMENT=bigbrotr|lilbrotr)
	docker compose -f deployments/$(DEPLOYMENT)/docker-compose.yaml down

# --------------------------------------------------------------------------
# Cleanup
# --------------------------------------------------------------------------

clean: ## Remove build artifacts and caches
	rm -rf build/ dist/ .eggs/
	rm -rf .mypy_cache/ .pytest_cache/ .ruff_cache/
	rm -rf htmlcov/ coverage.xml .coverage
	rm -rf site/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name '*.egg-info' -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete 2>/dev/null || true
