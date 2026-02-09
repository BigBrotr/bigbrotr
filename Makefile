# ============================================================================
# BigBrotr Development Makefile
# ============================================================================

.DEFAULT_GOAL := help
.PHONY: help lint format typecheck test test-fast coverage ci docker-build docker-up docker-down clean

DEPLOYMENT ?= bigbrotr

# --------------------------------------------------------------------------
# Development
# --------------------------------------------------------------------------

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

lint: ## Run ruff linter
	ruff check src/ tests/

format: ## Run ruff formatter
	ruff format src/ tests/

typecheck: ## Run mypy type checker
	mypy src/bigbrotr

test: ## Run all tests with verbose output
	pytest tests/ --ignore=tests/integration/ -v --tb=short

test-fast: ## Run tests without slow markers
	pytest tests/ --ignore=tests/integration/ -v --tb=short -m "not slow"

coverage: ## Run tests with coverage report
	pytest tests/ --ignore=tests/integration/ --cov=src/bigbrotr --cov-report=term-missing --cov-report=html -v

ci: lint format typecheck test ## Run all quality checks (lint, format, typecheck, test)

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
	rm -rf build/ dist/ *.egg-info .eggs/
	rm -rf .mypy_cache/ .pytest_cache/ .ruff_cache/
	rm -rf htmlcov/ coverage.xml .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
