# Development Guide

This document provides comprehensive guidance for developing and contributing to BigBrotr.

## Table of Contents

- [Development Setup](#development-setup)
- [Project Structure](#project-structure)
- [Running Tests](#running-tests)
- [Code Quality](#code-quality)
- [Adding New Services](#adding-new-services)
- [Working with the Database](#working-with-the-database)
- [Debugging](#debugging)
- [Contributing](#contributing)

---

## Development Setup

### Prerequisites

- Python 3.9 or higher
- Docker and Docker Compose (for database)
- Git

### Initial Setup

```bash
# Clone repository
git clone https://github.com/bigbrotr/bigbrotr.git
cd bigbrotr

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # Linux/macOS
# or: .venv\Scripts\activate  # Windows

# Install all dependencies
pip install -r requirements.txt -r requirements-dev.txt

# Install pre-commit hooks
pre-commit install

# Verify installation
python -c "from core import Pool, Brotr, BaseService, Logger; print('OK')"
```

### Environment Configuration

```bash
# Set database password for tests
export DB_PASSWORD=test_password

# Optional: Set for NIP-66 write tests
export MONITOR_PRIVATE_KEY=your_hex_private_key
```

### Running Local Database

```bash
# Start database only
cd implementations/bigbrotr
docker-compose up -d postgres pgbouncer

# Verify database
docker-compose exec postgres psql -U admin -d bigbrotr -c "\dt"
```

---

## Project Structure

```
bigbrotr/
├── src/                              # Source code
│   ├── __init__.py                   # Package root
│   ├── core/                         # Core layer (foundation)
│   │   ├── __init__.py               # Exports: Pool, Brotr, BaseService, Logger
│   │   ├── pool.py                   # PostgreSQL connection pool (~410 lines)
│   │   ├── brotr.py                  # Database interface (~430 lines)
│   │   ├── base_service.py           # Abstract service base (~200 lines)
│   │   └── logger.py                 # Structured logging (~50 lines)
│   │
│   └── services/                     # Service layer (business logic)
│       ├── __init__.py               # Service exports
│       ├── __main__.py               # CLI entry point
│       ├── initializer.py            # Database bootstrap (~310 lines)
│       ├── finder.py                 # Relay discovery (~220 lines)
│       ├── monitor.py                # Health monitoring (~400 lines)
│       ├── synchronizer.py           # Event sync (~740 lines)
│       ├── api.py                    # REST API (planned)
│       └── dvm.py                    # DVM service (planned)
│
├── implementations/                  # Implementation layer
│   ├── bigbrotr/                     # Full-featured implementation
│   │   ├── yaml/                     # Configuration files
│   │   │   ├── core/brotr.yaml
│   │   │   └── services/*.yaml
│   │   ├── postgres/init/            # SQL schema (full storage)
│   │   ├── data/seed_relays.txt      # 8,865 seed relay URLs
│   │   ├── pgbouncer/                # PGBouncer config
│   │   ├── docker-compose.yaml       # Ports: 5432, 6432, 9050
│   │   ├── Dockerfile
│   │   └── .env.example
│   │
│   └── lilbrotr/                     # Lightweight implementation
│       ├── yaml/                     # Minimal config overrides
│       ├── postgres/init/            # SQL schema (no tags/content)
│       ├── docker-compose.yaml       # Ports: 5433, 6433, 9051
│       └── Dockerfile
│
├── tests/                            # Test suite
│   ├── conftest.py                   # Shared fixtures
│   └── unit/                         # Unit tests
│       ├── __init__.py
│       ├── test_pool.py
│       ├── test_brotr.py
│       ├── test_initializer.py
│       ├── test_finder.py
│       ├── test_monitor.py
│       ├── test_synchronizer.py
│       └── test_logger.py
│
├── docs/                             # Documentation
│   ├── ARCHITECTURE.md
│   ├── CONFIGURATION.md
│   ├── DATABASE.md
│   ├── DEVELOPMENT.md
│   └── DEPLOYMENT.md
│
├── releases/                         # Release notes
│   ├── v1.0.0.md
│   └── v2.0.0.md
│
├── .github/                          # GitHub configuration
│   ├── workflows/ci.yml              # CI pipeline
│   ├── ISSUE_TEMPLATE/               # Issue templates
│   └── PULL_REQUEST_TEMPLATE.md
│
├── CHANGELOG.md                      # Version history
├── CONTRIBUTING.md                   # Contribution guide
├── SECURITY.md                       # Security policy
├── CODE_OF_CONDUCT.md                # Code of conduct
├── requirements.txt                  # Runtime dependencies
├── requirements-dev.txt              # Development dependencies
├── pyproject.toml                    # Project configuration
├── .pre-commit-config.yaml           # Pre-commit hooks
├── .gitignore
└── README.md
```

### Key Files

| File | Purpose |
|------|---------|
| `src/core/__init__.py` | Public API for core layer |
| `src/services/__init__.py` | Public API for services |
| `src/services/__main__.py` | CLI entry point (`python -m services`) |
| `pyproject.toml` | Project metadata, tool configuration |
| `conftest.py` | Shared pytest fixtures |

---

## Running Tests

### All Tests

```bash
# Run all unit tests
pytest tests/unit/ -v

# Run with coverage report
pytest tests/unit/ --cov=src --cov-report=html

# Open coverage report
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
```

### Specific Tests

```bash
# Run single test file
pytest tests/unit/test_pool.py -v

# Run single test class
pytest tests/unit/test_pool.py::TestPool -v

# Run single test method
pytest tests/unit/test_pool.py::TestPool::test_init_with_defaults -v

# Run tests matching pattern
pytest -k "health_check" -v

# Run tests with specific marker
pytest -m "not slow" -v
```

### Test Options

```bash
# Verbose output
pytest -v

# Show print statements
pytest -s

# Stop on first failure
pytest -x

# Run last failed tests
pytest --lf

# Parallel execution (requires pytest-xdist)
pytest -n auto

# With timeout
pytest --timeout=60
```

### Test Markers

```python
# In test file
@pytest.mark.slow
def test_slow_operation():
    ...

@pytest.mark.integration
def test_database_integration():
    ...

# Run with markers
pytest -m "not slow"
pytest -m "integration"
```

### Test Fixtures

Common fixtures are defined in `conftest.py`:

```python
# Mock asyncpg pool
@pytest.fixture
def mock_asyncpg_pool() -> MagicMock:
    ...

# Mock Pool with injected asyncpg
@pytest.fixture
def mock_connection_pool(mock_asyncpg_pool, monkeypatch) -> Pool:
    ...

# Mock Brotr with mock Pool
@pytest.fixture
def mock_brotr(mock_connection_pool) -> Brotr:
    ...

# Sample data fixtures
@pytest.fixture
def sample_event() -> dict:
    ...

@pytest.fixture
def sample_relay() -> dict:
    ...

@pytest.fixture
def sample_metadata() -> dict:
    ...
```

---

## Code Quality

### Linting with Ruff

```bash
# Check for issues
ruff check src/ tests/

# Auto-fix issues
ruff check src/ tests/ --fix

# Show all violations
ruff check src/ tests/ --show-fixes
```

### Formatting with Ruff

```bash
# Format code
ruff format src/ tests/

# Check formatting (no changes)
ruff format src/ tests/ --check

# Show diff
ruff format src/ tests/ --diff
```

### Type Checking with MyPy

```bash
# Check types
mypy src/

# Strict mode
mypy src/ --strict

# Show error codes
mypy src/ --show-error-codes
```

### Pre-commit Hooks

```bash
# Run all hooks on staged files
pre-commit run

# Run all hooks on all files
pre-commit run --all-files

# Run specific hook
pre-commit run ruff --all-files
pre-commit run mypy --all-files

# Update hooks
pre-commit autoupdate
```

### Configured Hooks

From `.pre-commit-config.yaml`:

1. **pre-commit-hooks**: trailing whitespace, end-of-file, YAML/JSON check
2. **ruff**: linting and formatting
3. **mypy**: type checking
4. **yamllint**: YAML linting
5. **detect-secrets**: secret detection

---

## Adding New Services

### 1. Create Service File

```python
# src/services/myservice.py
"""
My Service - Description of what it does.
"""

from pydantic import BaseModel, Field

from core.base_service import BaseService
from core.brotr import Brotr
from core.logger import Logger

SERVICE_NAME = "myservice"


class MyServiceConfig(BaseModel):
    """Configuration for MyService."""

    interval: float = Field(default=300.0, ge=60.0, description="Cycle interval in seconds")
    some_setting: str = Field(default="value", description="Description")


class MyService(BaseService[MyServiceConfig]):
    """
    My Service implementation.

    Does X, Y, Z.
    """

    SERVICE_NAME = SERVICE_NAME
    CONFIG_CLASS = MyServiceConfig

    def __init__(self, brotr: Brotr, config: MyServiceConfig | None = None) -> None:
        super().__init__(brotr=brotr, config=config or MyServiceConfig())
        self._config: MyServiceConfig  # Type hint for IDE
        self._logger = Logger(SERVICE_NAME)

    async def run(self) -> None:
        """Execute single service cycle."""
        self._logger.info("cycle_started")

        # Your service logic here
        await self._do_work()

        self._logger.info("cycle_completed")

    async def _do_work(self) -> None:
        """Internal work method."""
        # Access config: self._config.some_setting
        # Access database: self._brotr.pool.fetch(...)
        # Access state: self._state["key"]
        pass
```

### 2. Create Configuration File

```yaml
# implementations/bigbrotr/yaml/services/myservice.yaml
interval: 300.0
some_setting: "custom_value"
```

### 3. Register Service

```python
# src/services/__main__.py
from services.myservice import MyService, MyServiceConfig

SERVICE_REGISTRY = {
    # ... existing services ...
    "myservice": (MyService, MyServiceConfig),
}
```

### 4. Export from Package

```python
# src/services/__init__.py
from services.myservice import MyService, MyServiceConfig

__all__ = [
    # ... existing exports ...
    "MyService",
    "MyServiceConfig",
]
```

### 5. Write Tests

```python
# tests/unit/test_myservice.py
"""Unit tests for MyService."""

import pytest
from unittest.mock import MagicMock, AsyncMock

from services.myservice import MyService, MyServiceConfig


class TestMyServiceConfig:
    """Tests for MyServiceConfig."""

    def test_default_values(self) -> None:
        config = MyServiceConfig()
        assert config.interval == 300.0
        assert config.some_setting == "value"


class TestMyService:
    """Tests for MyService."""

    @pytest.fixture
    def mock_brotr(self) -> MagicMock:
        brotr = MagicMock()
        brotr.pool = MagicMock()
        brotr.pool.fetch = AsyncMock(return_value=[])
        return brotr

    def test_init(self, mock_brotr: MagicMock) -> None:
        service = MyService(brotr=mock_brotr)
        assert service.SERVICE_NAME == "myservice"

    @pytest.mark.asyncio
    async def test_run(self, mock_brotr: MagicMock) -> None:
        service = MyService(brotr=mock_brotr)
        await service.run()
        # Add assertions
```

### 6. Add Docker Service (Optional)

```yaml
# implementations/bigbrotr/docker-compose.yaml
myservice:
  build:
    context: ../../
    dockerfile: implementations/bigbrotr/Dockerfile
  container_name: bigbrotr-myservice
  restart: unless-stopped
  environment:
    DB_PASSWORD: ${DB_PASSWORD}
  volumes:
    - ./yaml:/app/yaml:ro
  networks:
    - bigbrotr-network
  depends_on:
    pgbouncer:
      condition: service_healthy
    initializer:
      condition: service_completed_successfully
  command: ["python", "-m", "services", "myservice"]
```

---

## Working with the Database

### Direct Database Access

```bash
# Via Docker
docker-compose exec postgres psql -U admin -d bigbrotr

# Via PGBouncer
docker-compose exec pgbouncer psql -h localhost -p 5432 -U admin -d bigbrotr

# Local (if postgres running locally)
psql -h localhost -p 5432 -U admin -d bigbrotr
```

### Common Queries

```sql
-- Relay summary
SELECT
    COUNT(*) AS total,
    COUNT(*) FILTER (WHERE network = 'clearnet') AS clearnet,
    COUNT(*) FILTER (WHERE network = 'tor') AS tor
FROM relays;

-- Recent events
SELECT encode(id, 'hex'), kind, created_at
FROM events
ORDER BY created_at DESC
LIMIT 10;

-- Relay status
SELECT relay_url, nip66_openable, nip66_readable, nip66_writable
FROM relay_metadata_latest
WHERE generated_at > EXTRACT(EPOCH FROM NOW() - INTERVAL '24 hours')
ORDER BY nip66_openable DESC, nip66_readable DESC;

-- Event kind distribution
SELECT * FROM kind_counts_total LIMIT 20;
```

### Testing with Real Database

```python
# tests/integration/test_brotr_integration.py
import pytest
import os

@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("DB_PASSWORD") is None,
    reason="DB_PASSWORD not set"
)
async def test_brotr_connection():
    from core.brotr import Brotr

    brotr = Brotr.from_yaml("implementations/bigbrotr/yaml/core/brotr.yaml")
    async with brotr:
        result = await brotr.pool.fetchval("SELECT 1")
        assert result == 1
```

---

## Debugging

### Logging

```python
from core.logger import Logger

logger = Logger("mymodule")
logger.debug("detailed_info", key="value")
logger.info("operation_completed", count=10)
logger.warning("potential_issue", reason="something")
logger.error("operation_failed", error=str(e))
```

### Debug Mode

```bash
# Run service with debug logging
python -m services finder --log-level DEBUG
```

### Async Debugging

```python
import asyncio

# Enable asyncio debug mode
asyncio.get_event_loop().set_debug(True)

# Or via environment
# PYTHONASYNCIODEBUG=1 python -m services finder
```

### VS Code Configuration

```json
// .vscode/launch.json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Debug Service",
            "type": "python",
            "request": "launch",
            "module": "services",
            "args": ["finder", "--log-level", "DEBUG"],
            "cwd": "${workspaceFolder}/implementations/bigbrotr",
            "env": {
                "PYTHONPATH": "${workspaceFolder}/src",
                "DB_PASSWORD": "your_password"
            }
        },
        {
            "name": "Debug Tests",
            "type": "python",
            "request": "launch",
            "module": "pytest",
            "args": ["tests/unit/", "-v", "-s"],
            "env": {
                "PYTHONPATH": "${workspaceFolder}/src",
                "DB_PASSWORD": "test_password"
            }
        }
    ]
}
```

### PyCharm Configuration

1. **Run Configuration**:
   - Module: `services`
   - Parameters: `finder --log-level DEBUG`
   - Working directory: `implementations/bigbrotr`
   - Environment: `PYTHONPATH=../../src;DB_PASSWORD=your_password`

2. **Test Configuration**:
   - Target: `tests/unit/`
   - Additional arguments: `-v -s`

---

## Contributing

For detailed contribution guidelines, see [CONTRIBUTING.md](../CONTRIBUTING.md).

### Git Workflow

1. **Fork** the repository
2. **Clone** your fork
3. **Create branch** from `develop`
4. **Make changes** and commit
5. **Push** to your fork
6. **Create PR** to `main`

### Branch Naming

```
feature/add-api-service
fix/connection-timeout
refactor/pool-retry-logic
docs/update-readme
test/add-monitor-tests
```

### Commit Messages

Follow conventional commits:

```
feat: add API service with REST endpoints
fix: handle connection timeout in pool
refactor: simplify retry logic in pool
docs: update architecture documentation
test: add monitor health check tests
chore: update dependencies
```

### Pull Request Checklist

- [ ] Tests pass: `pytest tests/unit/ -v`
- [ ] Code quality: `pre-commit run --all-files`
- [ ] Documentation updated if needed
- [ ] Commit messages follow conventions
- [ ] PR description explains changes

### Code Standards

1. **Type Hints**: Required for all public interfaces
2. **Docstrings**: Classes and public methods
3. **Tests**: Unit tests for new features
4. **Config**: Pydantic models for configuration
5. **Async**: Use async/await for I/O operations

### Review Process

1. CI checks must pass
2. At least one approval required
3. Address all review comments
4. Squash commits if requested

---

## Useful Commands Reference

```bash
# Development
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pre-commit install

# Testing
pytest tests/unit/ -v
pytest tests/unit/ --cov=src --cov-report=html
pytest -k "pattern" -v

# Code Quality
ruff check src/ tests/
ruff format src/ tests/
mypy src/
pre-commit run --all-files

# Running Services
cd implementations/bigbrotr
python -m services initializer
python -m services finder --log-level DEBUG

# Docker
docker-compose up -d
docker-compose logs -f
docker-compose exec postgres psql -U admin -d bigbrotr
docker-compose down

# Git
git checkout -b feature/my-feature
git add .
git commit -m "feat: description"
git push origin feature/my-feature
```

---

## Related Documentation

| Document | Description |
|----------|-------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System architecture overview |
| [CONFIGURATION.md](CONFIGURATION.md) | Complete configuration reference |
| [DATABASE.md](DATABASE.md) | Database schema documentation |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Deployment instructions |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | Contribution guidelines |
| [CHANGELOG.md](../CHANGELOG.md) | Version history |
