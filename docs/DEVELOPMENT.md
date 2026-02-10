# Development Guide

Setup, testing, code quality, and contribution guidelines for BigBrotr development.

---

## Quick Start

```bash
# Clone and install
git clone https://github.com/bigbrotr/bigbrotr.git
cd bigbrotr
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install

# Run all checks
make ci
```

---

## Prerequisites

- Python 3.11+ (tested on 3.11, 3.12, 3.13, 3.14)
- Git
- PostgreSQL 16+ (for integration tests, or use Docker)

---

## Project Structure

```text
bigbrotr/
+-- src/bigbrotr/                     # Source package
|   +-- __init__.py
|   +-- __main__.py                   # CLI entry point
|   +-- core/                         # Pool, Brotr, BaseService, Logger, Metrics, YAML
|   |   +-- exceptions.py             # Exception hierarchy (BigBrotrError)
|   +-- models/                       # Frozen dataclasses (pure, zero I/O)
|   |   +-- service_state.py          # ServiceState, ServiceStateKey
|   +-- nips/                         # NIP-11 and NIP-66 protocol I/O
|   |   +-- nip11/                    # Relay info document fetch/parse
|   |   +-- nip66/                    # Monitoring: dns, geo, http, net, rtt, ssl
|   +-- services/                     # Business logic (5 services)
|   |   +-- monitor.py                # Health check orchestration (~600 lines)
|   |   +-- monitor_publisher.py      # Nostr event broadcasting (~230 lines)
|   |   +-- monitor_tags.py           # NIP-66 tag building (~280 lines)
|   |   +-- common/                   # Shared constants, configs, queries, mixins
|   +-- utils/                        # DNS, keys, transport helpers
+-- tests/
|   +-- conftest.py                   # Root fixtures (mock_pool, mock_brotr, etc.)
|   +-- fixtures/
|   |   +-- relays.py                 # Shared relay fixtures (registered via pytest_plugins)
|   +-- unit/                         # Unit tests mirroring src/ structure
|   |   +-- core/
|   |   +-- models/
|   |   +-- nips/
|   |   +-- services/
|   |   +-- utils/
|   +-- integration/                  # Integration tests (require database)
+-- deployments/
|   +-- Dockerfile                    # Single parametric Dockerfile
|   +-- bigbrotr/                     # Full-featured deployment
|   +-- lilbrotr/                     # Lightweight deployment
|   +-- _template/                    # Template for new deployments
+-- docs/                             # Documentation
+-- .github/                          # CI/CD workflows
+-- Makefile                          # Development commands
+-- pyproject.toml                    # Project configuration
+-- .pre-commit-config.yaml           # Pre-commit hooks
```

---

## Development Commands

### Makefile Targets

```bash
make lint           # ruff check src/ tests/
make format         # ruff format src/ tests/
make typecheck      # mypy src/bigbrotr
make test-unit        # pytest unit tests (excluding integration)
make test-integration # pytest integration tests (requires Docker)
make test-fast        # pytest -m "not slow"
make coverage         # pytest with HTML coverage report
make ci               # All checks: lint + format + typecheck + test-unit

make docs             # Build MkDocs documentation site
make docs-serve       # Serve docs locally with live reload
make build            # Build Python package (sdist + wheel)

make docker-build     # Build Docker image (DEPLOYMENT=bigbrotr)
make docker-up        # Start Docker stack
make docker-down      # Stop Docker stack

make clean            # Remove build artifacts and caches
```

### Direct Commands

```bash
# Run specific tests
pytest tests/unit/core/test_pool.py -v
pytest tests/unit/core/test_pool.py::TestPool -v
pytest -k "health_check" -v

# Coverage with HTML report
pytest tests/ --cov=src/bigbrotr --cov-report=html

# Lint with auto-fix
ruff check src/ tests/ --fix
ruff format src/ tests/

# Type check
mypy src/bigbrotr

# All pre-commit hooks
pre-commit run --all-files

# Run a service locally (from deployment directory)
cd deployments/bigbrotr
python -m bigbrotr seeder --once
python -m bigbrotr finder --log-level DEBUG
```

---

## Testing

### Configuration

From `pyproject.toml`:

- **Test runner**: pytest with `asyncio_mode = "auto"` (no `@pytest.mark.asyncio` needed)
- **Timeout**: 120s global (`--timeout=120`)
- **Markers**: `slow`, `integration`, `unit`
- **Coverage**: Branch coverage, 80% minimum (`fail_under = 80`)

### Test Structure

Tests mirror the source package layout:

```text
tests/unit/
+-- core/           # test_pool.py, test_brotr.py, test_logger.py, test_metrics.py, ...
+-- models/         # test_event.py, test_relay.py, test_metadata.py, ...
+-- nips/
|   +-- nip11/      # test_fetch.py, test_data.py, test_nip11.py, ...
|   +-- nip66/      # test_rtt.py, test_ssl.py, test_dns.py, test_geo.py, ...
+-- services/       # test_finder.py, test_validator.py, test_monitor.py, ...
|   +-- common/     # test_constants.py, test_queries.py, test_mixins.py
+-- utils/          # test_dns.py, test_keys.py, test_transport.py, ...
```

### Fixtures

**Root conftest** (`tests/conftest.py`): `mock_pool`, `mock_brotr`, `mock_connection`, `sample_event`, `sample_relay`, `sample_metadata`, `create_mock_record()`

**Shared relay fixtures** (`tests/fixtures/relays.py`, registered via `pytest_plugins`):

- `relay_clearnet`, `relay_clearnet_with_port`, `relay_clearnet_ws`
- `relay_tor`, `relay_i2p`, `relay_loki`, `relay_ipv6`
- `relay_overlay` (parametrized: tor/i2p/loki)
- `relay_batch` (10 clearnet relays)

### Mocking Patterns

```python
# Mock at the service module namespace (not core.queries)
@patch("bigbrotr.services.validator.is_nostr_relay")
async def test_validation(mock_is_nostr):
    mock_is_nostr.return_value = True
    ...

# Mock Brotr methods for database operations
mock_brotr.fetch.return_value = [mock_record]
mock_brotr.fetchval.return_value = 42
mock_brotr.execute.return_value = "DELETE 5"
```

### Running Tests

```bash
# All unit tests
make test-unit

# Skip slow tests
make test-fast

# Single file or class
pytest tests/unit/core/test_pool.py -v
pytest tests/unit/core/test_pool.py::TestPoolRetry -v

# Pattern matching
pytest -k "test_health_check" -v

# Integration tests (requires database)
pytest tests/integration/ -v

# Coverage report
make coverage
open htmlcov/index.html
```

---

## Code Quality

### Ruff (Linting and Formatting)

- **Line length**: 100
- **Target**: Python 3.11
- **Source paths**: `src/`, `tests/`
- **26 enabled rule categories** including: E, W, F, I, B, C4, UP, ARG, SIM, TCH, S (Bandit), PT (pytest), N (naming), T20 (print), ASYNC, FBT, FURB

Key rules:

- `ban-relative-imports = "parents"` -- only sibling-relative imports allowed
- `known-first-party = ["bigbrotr"]`
- Tests have relaxed rules (S101, E501, PLR0913, FBT, etc.)

### mypy (Type Checking)

- **Strict mode** enabled on `src/bigbrotr`
- External libraries with missing stubs are configured with `ignore_missing_imports`
- Special override: `bigbrotr.utils.transport` allows `allow_subclassing_any = true`

### Pre-commit Hooks

All hooks run automatically on `git commit`. The full set:

| Hook | Purpose |
|------|---------|
| trailing-whitespace, end-of-file-fixer | Whitespace cleanup |
| check-yaml, check-json, check-toml | Config file validation |
| check-added-large-files (1 MB) | Prevent large file commits |
| detect-private-key, detect-secrets | Secret detection |
| ruff, ruff-format | Python lint + format |
| mypy | Type checking |
| yamllint | YAML linting |
| markdownlint | Markdown linting (MD013, MD033, MD041 disabled) |
| hadolint | Dockerfile linting |
| sqlfluff-fix | SQL formatting |

Run all hooks manually:

```bash
pre-commit run --all-files
```

### SQL Formatting

- **Dialect**: PostgreSQL
- **Tool**: sqlfluff
- **Keywords**: UPPER, identifiers: lower, types: UPPER
- **Max line length**: 150
- **Tab size**: 4 spaces

---

## Architecture Rules

### Diamond DAG

Imports flow downward only:

```text
         services
        /   |   \
     core  nips  utils
        \   |   /
         models
```

- **models**: Pure -- zero I/O, zero package dependencies, stdlib `logging` only
- **core**: Depends only on models
- **utils**: Depends only on models
- **nips**: Depends on models and utils (has I/O: HTTP, DNS, SSL, WebSocket, GeoIP)
- **services**: Depends on all layers above

### Import Conventions

```python
# Cross-package: absolute with bigbrotr prefix
from bigbrotr.core.logger import Logger
from bigbrotr.models.relay import Relay
from bigbrotr.nips.nip11 import Nip11

# Within same package: relative
from .logger import Logger
from .common.constants import ServiceName

# Models layer: stdlib logging only
import logging
logger = logging.getLogger(__name__)
```

### Model Patterns

- All models are `@dataclass(frozen=True, slots=True)` -- immutable
- All models cache `to_db_params()` in `__post_init__` via `_db_params` field
- `NetworkType` lives in `models/constants.py`
- `MetadataType` lives in `models/metadata.py`
- `ServiceState` lives in `models/service_state.py`

### Exception Hierarchy

```text
BigBrotrError (base)
+-- ConfigurationError
+-- DatabaseError
|   +-- ConnectionPoolError (transient, retry)
|   +-- QueryError (permanent)
+-- ConnectivityError
|   +-- RelayTimeoutError
|   +-- RelaySSLError
+-- ProtocolError
+-- PublishingError
```

Defined in `src/bigbrotr/core/exceptions.py`. All `except Exception` blocks have been replaced with specific catches.

---

## CI/CD Pipeline

### GitHub Actions Workflows

#### ci.yml (Main Pipeline)

Triggers on push/PR to `main`/`develop`.

| Job | Steps |
|-----|-------|
| **pre-commit** | All pre-commit hooks |
| **test** | Matrix: Python 3.11-3.14, pip-audit, pytest with coverage |
| **build** | Docker build (BigBrotr + LilBrotr), Trivy vulnerability scan |
| **ci-success** | Status check gate for branch protection |

Coverage is uploaded to Codecov on Python 3.11 only. Python 3.14 allows pre-release.

#### codeql.yml (Static Analysis)

Runs on push/PR and weekly. Python analysis with CodeQL.

### Dependabot

Configured for three ecosystems:

- **pip**: Weekly Python dependency updates
- **docker**: Weekly Docker image updates
- **github-actions**: Weekly action version updates

All PRs labeled appropriately and assigned to maintainers.

---

## Commit Conventions

Use [Conventional Commits](https://www.conventionalcommits.org/):

```text
feat: add REST API service
fix: handle connection timeout in validator
refactor: split monitor into 3 modules
docs: update architecture documentation
test: add monitor publisher tests
chore: update dependencies
```

### Branch Naming

```text
feature/add-api-service
fix/connection-timeout
refactor/pool-retry-logic
docs/update-readme
test/add-monitor-tests
```

---

## Adding a New Service

1. Create `src/bigbrotr/services/myservice.py`:

    ```python
    from bigbrotr.core.base_service import BaseService, BaseServiceConfig

    class MyServiceConfig(BaseServiceConfig):
        # Pydantic model with service-specific fields
        my_setting: int = 42

    class MyService(BaseService[MyServiceConfig]):
        config_class = MyServiceConfig

        async def run(self) -> None:
            # Service logic for one cycle
            ...
    ```

1. Register in `src/bigbrotr/__main__.py`:

    ```python
    SERVICE_REGISTRY[ServiceName.MYSERVICE] = ServiceEntry(
        cls=MyService,
        config_path=Path("config/services/myservice.yaml"),
    )
    ```

1. Add `ServiceName.MYSERVICE` to `src/bigbrotr/services/common/constants.py`

1. Create `deployments/*/config/services/myservice.yaml`

1. Add tests in `tests/unit/services/test_myservice.py`

---

## Debugging

### Local Service Debugging

```bash
cd deployments/bigbrotr
python -m bigbrotr finder --log-level DEBUG --once
```

### VS Code Launch Configuration

```json
{
    "name": "BigBrotr Finder",
    "type": "debugpy",
    "request": "launch",
    "module": "bigbrotr",
    "args": ["finder", "--log-level", "DEBUG", "--once"],
    "cwd": "${workspaceFolder}/deployments/bigbrotr",
    "env": {
        "DB_PASSWORD": "your_password"
    }
}
```

### PyCharm Run Configuration

- Module: `bigbrotr`
- Parameters: `finder --log-level DEBUG --once`
- Working directory: `deployments/bigbrotr`
- Environment variables: `DB_PASSWORD=your_password`

---

## Related Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) -- System architecture and module reference
- [CONFIGURATION.md](CONFIGURATION.md) -- YAML configuration reference
- [DATABASE.md](DATABASE.md) -- Database schema and stored procedures
- [DEPLOYMENT.md](DEPLOYMENT.md) -- Docker and manual deployment guide
