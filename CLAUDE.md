# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

BigBrotr is a modular, production-grade Nostr data archiving and monitoring system built on Python and PostgreSQL. It uses a three-layer architecture (Core, Service, Implementation) with dependency injection, making the codebase highly testable and maintainable.

**Current Status**: Core layer complete (100%), service layer pending (0%)
- **Core layer** (src/core/): 4/4 components production-ready (2,853 LOC)
- **Service layer** (src/services/): 0/7 services implemented
- **Overall progress**: ~41% complete (weighted)
- **Primary branch**: `develop` (create PRs to `main`)

## Common Commands

### Development Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Set up environment (requires PostgreSQL)
cp implementations/bigbrotr/.env.example implementations/bigbrotr/.env
nano implementations/bigbrotr/.env  # Set DB_PASSWORD

# Run with Docker Compose
cd implementations/bigbrotr
docker-compose up -d

# Verify database
docker-compose exec postgres psql -U admin -d brotr -c "\dt"
```

### Testing
```bash
# Create virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

# Run all unit tests
pytest tests/unit/ -v

# Run with coverage
pytest tests/unit/ --cov=src --cov-report=html

# Run specific test file
pytest tests/unit/test_pool.py -v

# Run tests matching pattern
pytest -k "health_check" -v
```

### Database Operations
```bash
# Initialize database with SQL schemas (apply in numerical order)
cd implementations/bigbrotr/postgres/init
psql -U admin -d brotr -f 00_extensions.sql
psql -U admin -d brotr -f 01_utility_functions.sql
psql -U admin -d brotr -f 02_tables.sql
psql -U admin -d brotr -f 03_indexes.sql
psql -U admin -d brotr -f 04_integrity_functions.sql
psql -U admin -d brotr -f 05_procedures.sql
psql -U admin -d brotr -f 06_views.sql
psql -U admin -d brotr -f 99_verify.sql
```

## Architecture

### Three-Layer Design Philosophy

```
Implementation Layer (implementations/bigbrotr/)
          ↑ Uses (YAML configs, SQL schemas)
Service Layer (src/services/)
          ↑ Leverages (Finder, Monitor, Synchronizer - PENDING)
Core Layer (src/core/)
          ✅ PRODUCTION READY (Pool, Brotr, Service, Logger)
```

**Key Principle**: Core layer is implementation-agnostic and reusable. Services compose core components via dependency injection. Implementations customize behavior via YAML configuration.

### Core Components (✅ Production Ready)

| Component | LOC | Purpose | Status |
|-----------|-----|---------|--------|
| **ConnectionPool** | ~632 | PostgreSQL connection management | ✅ Complete |
| **Brotr** | ~803 | Database interface + stored procedures | ✅ Complete |
| **Service** | ~1,021 | Generic lifecycle wrapper | ✅ Complete |
| **Logger** | ~397 | Structured JSON logging | ✅ Complete |
| **Total** | **2,853** | Production-ready foundation | **100%** |

#### 1. ConnectionPool ([src/core/pool.py](src/core/pool.py))
- Enterprise-grade PostgreSQL connection management with asyncpg
- Auto-retry with exponential backoff, PGBouncer compatibility, connection recycling
- Password from `DB_PASSWORD` env var (never in config files)
- Configuration via YAML or constructor
- **`acquire_healthy()`**: Health-checked connection acquisition with automatic retry

#### 2. Brotr ([src/core/brotr.py](src/core/brotr.py))
- High-level database interface with stored procedure wrappers
- **Composition pattern**: HAS-A pool (public property), not IS-A pool
- Access: `brotr.pool.fetch()` for pool operations, `brotr.insert_event()` for business logic
- **Dependency Injection**: Reduced `__init__` parameters from 28 to 12 (57% reduction)
- Receives ConnectionPool via injection or creates default

#### 3. Service ([src/core/service.py](src/core/service.py))
- Generic wrapper for lifecycle management, logging, health checks
- Wraps ANY service implementing `DatabaseService` or `BackgroundService` protocol
- **Protocol-based**: Non-invasive, services don't need to inherit from anything
- Provides uniform interface for all services
- **Health check retry**: Configurable retry attempts before reporting failure

#### 4. Logger ([src/core/logger.py](src/core/logger.py))
- Structured JSON logging for all services
- Contextual fields: service_name, service_type, timestamp, level
- Integration with Service wrapper (automatic when `enable_logging=True`)

### Design Patterns in Use

| Pattern | Application | Purpose |
|---------|-------------|---------|
| **Dependency Injection** | `Brotr(pool=ConnectionPool())` | Flexibility, testability, pool sharing |
| **Composition over Inheritance** | Brotr HAS-A pool (public), not IS-A | Clear API, explicit separation |
| **Wrapper/Decorator** | Service wraps any service | Cross-cutting concerns (DRY) |
| **Factory Method** | `from_yaml()`, `from_dict()` | Config-driven construction |
| **Template Method** | `_call_delete_procedure()` | DRY for similar operations |
| **Protocol/Duck Typing** | DatabaseService, BackgroundService | Non-invasive, flexible |
| **Single Responsibility** | Each component has one job | Clear boundaries, easier testing |

### Why Composition with Public Pool?

The `Brotr` class exposes its pool as a **public property** (`brotr.pool`) rather than inheriting from ConnectionPool:

**Benefits**:
- **Clear API**: `brotr.pool.fetch()` vs `brotr.insert_event()` - obvious which is which
- **Separation of concerns**: Pool handles connections, Brotr handles business logic
- **Easy pool sharing**: Multiple services can inject the same pool instance
- **Better testability**: Mock the pool independently
- **Self-documenting**: Code is explicit about what it does

**Impact**: This design reduced `Brotr.__init__` parameters from 28 to 12 (57% reduction).

## Configuration System

### YAML-Based Configuration
All components support configuration via YAML files in [implementations/bigbrotr/yaml/](implementations/bigbrotr/yaml/):
- **Core**: [yaml/core/brotr.yaml](implementations/bigbrotr/yaml/core/brotr.yaml) (includes pool config under `pool:` key)
- **Services**: [yaml/services/finder.yaml](implementations/bigbrotr/yaml/services/finder.yaml), [yaml/services/monitor.yaml](implementations/bigbrotr/yaml/services/monitor.yaml), etc. (empty, pending)

### Configuration Loading Pattern
```python
# Option 1: From YAML (recommended)
brotr = Brotr.from_yaml("implementations/bigbrotr/yaml/core/brotr.yaml")

# Option 2: From dict (useful for testing)
config = {"pool": {"database": {"host": "localhost"}}, "batch": {"max_batch_size": 10000}}
brotr = Brotr.from_dict(config)

# Option 3: Dependency injection with custom pool (for pool sharing)
pool = ConnectionPool(host="localhost", database="brotr", min_size=10)
brotr = Brotr(pool=pool, max_batch_size=10000)

# Option 4: All defaults (creates default pool internally)
brotr = Brotr()

# Option 5: Pool sharing (multiple services, one pool)
shared_pool = ConnectionPool(host="localhost", database="brotr")
brotr1 = Brotr(pool=shared_pool)
brotr2 = Brotr(pool=shared_pool)  # Same pool instance!
```

### Pydantic Validation
All configuration uses Pydantic BaseModel for type safety and validation:
- Automatic field validation (min/max values, string length, etc.)
- Self-documenting via `Field(description=...)`
- IDE autocomplete support
- Clear defaults and error messages

### Environment Variables
- `DB_PASSWORD`: Database password (**required**, loaded automatically by ConnectionPool)
- `SOCKS5_PROXY_URL`: Tor proxy URL (optional)
- **Config files should NEVER contain passwords**

## Working with the Codebase

### Adding New Core Components

Core components should:
1. Be **implementation-agnostic** (no business logic)
2. Support **dependency injection** (receive dependencies via constructor)
3. Provide **factory methods**: `from_yaml()` and `from_dict()`
4. Use **Pydantic** for configuration validation
5. Include **comprehensive docstrings** and **type hints**

Example pattern:
```python
from pydantic import BaseModel, Field
from typing import Optional

class NewComponentConfig(BaseModel):
    """Configuration for NewComponent."""
    setting: str = Field(default="value", description="What this setting does")

class NewComponent:
    """Purpose of this component."""

    def __init__(self, pool: Optional[ConnectionPool] = None, setting: str = "default"):
        self.pool = pool or ConnectionPool()
        self.config = NewComponentConfig(setting=setting)

    @classmethod
    def from_yaml(cls, path: str) -> "NewComponent":
        """Load configuration from YAML file and construct instance."""
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> "NewComponent":
        """Construct from dictionary."""
        config = NewComponentConfig(**data.get("config", {}))
        return cls(setting=config.setting)
```

### Adding New Services (When Ready)

Services (when implemented) should:
1. Implement either **`DatabaseService`** or **`BackgroundService`** protocol
2. Receive dependencies via **constructor injection** (Brotr, ConnectionPool, etc.)
3. Use the core components (ConnectionPool, Brotr)
4. Be **wrappable by Service** for monitoring/logging/health checks
5. Load configuration from [implementations/bigbrotr/yaml/services/](implementations/bigbrotr/yaml/services/)

Example pattern:
```python
from core.brotr import Brotr
from core.service import Service, ServiceConfig

class MyService:
    """Business logic service."""

    def __init__(self, brotr: Brotr, config: MyServiceConfig):
        self.brotr = brotr
        self.config = config
        self._running = False

    async def start(self) -> None:
        """Start the service."""
        self._running = True
        # Service logic here

    async def stop(self) -> None:
        """Stop the service."""
        self._running = False
        # Cleanup here

    @property
    def is_running(self) -> bool:
        return self._running

# Wrap with Service for lifecycle management
service = Service(
    MyService(brotr, config),
    name="my_service",
    config=ServiceConfig(enable_logging=True, enable_health_checks=True)
)

async with service:
    # Automatic logging, health checks, statistics
    pass
```

### Database Schema

SQL files in [implementations/bigbrotr/postgres/init/](implementations/bigbrotr/postgres/init/) must be applied in numerical order:

1. [00_extensions.sql](implementations/bigbrotr/postgres/init/00_extensions.sql) - PostgreSQL extensions
2. [01_utility_functions.sql](implementations/bigbrotr/postgres/init/01_utility_functions.sql) - Helper functions
3. [02_tables.sql](implementations/bigbrotr/postgres/init/02_tables.sql) - Table definitions
4. [03_indexes.sql](implementations/bigbrotr/postgres/init/03_indexes.sql) - Performance indexes
5. [04_integrity_functions.sql](implementations/bigbrotr/postgres/init/04_integrity_functions.sql) - Data integrity checks
6. [05_procedures.sql](implementations/bigbrotr/postgres/init/05_procedures.sql) - Stored procedures (called by Brotr)
7. [06_views.sql](implementations/bigbrotr/postgres/init/06_views.sql) - Database views
8. [99_verify.sql](implementations/bigbrotr/postgres/init/99_verify.sql) - Schema validation

### Helper Methods and DRY Principle

This codebase emphasizes eliminating duplication:
- If you see **repeated validation logic**, extract to a helper method (e.g., `_validate_batch_size()` in [brotr.py:line](src/core/brotr.py))
- If you see **repeated procedure call patterns**, use template method pattern (e.g., `_call_delete_procedure()` in [brotr.py:line](src/core/brotr.py))
- Document the **"why"** in helper method docstrings, not the "what"
- ~50 lines of duplication eliminated in Brotr via helper methods

### Async Context Managers

Core components use async context managers for resource management:
```python
async with pool:
    # Pool automatically connects on enter, closes on exit
    result = await pool.fetch("SELECT * FROM events")

async with service:
    # Service automatically starts, adds logging, runs health checks, stops
    await service.instance.do_work()
```

## Testing Infrastructure

**Current State**: Comprehensive pytest-based unit tests (112 tests, 100% passing)
- [tests/unit/test_pool.py](tests/unit/test_pool.py) - 29 tests for ConnectionPool
- [tests/unit/test_brotr.py](tests/unit/test_brotr.py) - 21 tests for Brotr
- [tests/unit/test_service.py](tests/unit/test_service.py) - 42 tests for Service wrapper
- [tests/unit/test_logger.py](tests/unit/test_logger.py) - 20 tests for Logger

**Test Configuration**:
- [pyproject.toml](pyproject.toml) - pytest, coverage, ruff, mypy configuration
- [tests/conftest.py](tests/conftest.py) - Shared fixtures and pytest configuration
- [requirements-dev.txt](requirements-dev.txt) - Development dependencies

**Running Tests**:
```bash
source .venv/bin/activate
pytest tests/unit/ -v              # All unit tests
pytest --cov=src                   # With coverage
pytest -k "health_check"           # Pattern matching
```

When adding tests:
- Test **dependency injection** (pool sharing, custom pools)
- Test **factory methods** (`from_yaml`, `from_dict`)
- Test **default construction**
- Verify **composition pattern** (public properties accessible)
- Use **mocks** for external dependencies (database, network)
- Mark integration tests with `@pytest.mark.integration`

## Documentation Standards

### Code Documentation
- **Docstrings**: Required for all classes and public methods
- **Type Hints**: Required for all function signatures
- **Field Descriptions**: Use Pydantic `Field(description=...)` for config fields
- **Inline Comments**: Explain "why", not "what" (code should be self-documenting)

### Project Documentation
- [PROJECT_SPECIFICATION.md](PROJECT_SPECIFICATION.md): Complete technical specification (architecture, APIs, schema)
- [PROJECT_STATUS.md](PROJECT_STATUS.md): Current development status, metrics, next steps
- [README.md](README.md): User-facing documentation, quick start, examples
- [docs/old/](docs/old/): Archived refactoring documents (historical reference)

## Important Implementation Details

### Timeout Separation
- **Pool**: Handles `acquisition` timeout (getting connection from pool)
- **Brotr**: Handles operation timeouts (`query`, `procedure`, `batch` execution)

This separation maintains clear responsibilities and allows independent configuration.

**Example**:
```yaml
pool:
  timeouts:
    acquisition: 10.0  # Getting connection from pool

timeouts:
  query: 60.0          # Standard queries
  procedure: 90.0      # Stored procedures
  batch: 120.0         # Batch operations
```

### Hex to Bytea Conversion
Brotr converts hex strings to bytea for efficient PostgreSQL storage:
```python
# Event IDs and pubkeys are hex strings in Nostr (64 chars)
# Brotr automatically converts to bytea (32 bytes) for storage
await brotr.insert_event(
    event_id="abc123...",  # 64-char hex → 32-byte bytea
    pubkey="def456...",    # 64-char hex → 32-byte bytea
    ...
)
```

### Batch Operations
Batch methods use `executemany()` for performance (up to 1000x improvement over single inserts):
- Default batch size: 100
- Max batch size: 10,000 (configurable, validated)
- Automatic batch size validation in all batch methods

### Connection Recycling
Connections are recycled after:
- `max_queries` per connection (default: 50,000 queries)
- `max_inactive_connection_lifetime` seconds idle (default: 300 seconds)

This prevents connection staleness in long-running applications.

## Common Patterns

### Dependency Injection Pattern
```python
# Create shared pool
pool = ConnectionPool.from_yaml("implementations/bigbrotr/yaml/core/brotr.yaml")

# Inject into multiple services (pool sharing)
brotr = Brotr(pool=pool)
finder = Finder(pool=pool)  # When implemented
monitor = Monitor(pool=pool)  # When implemented

# All services use same connection pool
```

### Factory Method Pattern
```python
# Every core component supports these patterns
component = Component.from_yaml("config.yaml")
component = Component.from_dict({"setting": "value"})
component = Component(direct_params)
```

### Template Method Pattern
```python
# Generic delete procedure caller (internal helper in Brotr)
async def _call_delete_procedure(
    self,
    procedure_name: str,
    timeout: float
) -> int:
    """Template for all delete operations."""
    # Common logic here - eliminates duplication
```

## Project Structure Notes

- [src/core/](src/core/): Production-ready foundation components (pool, brotr, service, logger) ✅
- [src/services/](src/services/): Service implementations (all pending except stubs) ⚠️
- [implementations/bigbrotr/](implementations/bigbrotr/): Primary implementation with configs, schemas, Docker Compose
- [tests/](tests/): Test scripts (manual tests currently, pytest planned)
- [docs/old/](docs/old/): Archived design documents (refactoring history, decisions)

## Git Workflow

- **Main branch**: `main` (stable releases, none yet)
- **Development branch**: `develop` (active development, current branch)
- **PR target**: Create PRs from feature branches to `main`
- **Commit style**: Conventional commits (e.g., `feat:`, `fix:`, `refactor:`, `docs:`, `test:`)

## Technology Stack

### Core Dependencies
- **Python 3.9+**: Language
- **PostgreSQL 14+**: Database
- **asyncpg 0.30.0**: Async PostgreSQL driver
- **Pydantic 2.10.4**: Configuration validation
- **PyYAML 6.0.2**: YAML parsing
- **aiohttp 3.13.2**: Async HTTP client (with SOCKS5 support)
- **nostr-tools 1.4.0**: Nostr protocol library
- **python-dotenv 1.0.1**: Environment variable loading

### Infrastructure
- **Docker + Docker Compose**: Container orchestration
- **PGBouncer**: Connection pooling (between app and PostgreSQL)
- **Tor (optional)**: Network privacy via SOCKS5 proxy

## Recent Major Refactorings

### 1. Dependency Injection Refactoring (2025-11-13)
- Reduced Brotr parameters from 28 to 12 (57% reduction)
- Pool injection instead of parameter explosion
- See: [docs/old/BROTR_DEPENDENCY_INJECTION_REFACTORING.md](docs/old/BROTR_DEPENDENCY_INJECTION_REFACTORING.md)

### 2. Helper Methods Addition (2025-11-13)
- `_validate_batch_size()` eliminates duplication
- `_call_delete_procedure()` template method pattern
- See: [docs/old/BROTR_IMPROVEMENTS_SUMMARY.md](docs/old/BROTR_IMPROVEMENTS_SUMMARY.md)

### 3. Timeout Separation (2025-11-13)
- Pool: acquisition timeout (infrastructure concern)
- Brotr: operation timeouts (business logic concern)
- See: [docs/old/TIMEOUT_REFACTORING_SUMMARY.md](docs/old/TIMEOUT_REFACTORING_SUMMARY.md)

### 4. Service Wrapper Implementation (2025-11-14)
- Full implementation of generic service lifecycle wrapper (~1,021 lines)
- Protocol-based design (DatabaseService, BackgroundService)
- Health checks, circuit breaker, statistics collection

### 5. Logger Module Addition (2025-11-14)
- Structured JSON logging system (~397 lines)
- Service-aware logging with contextual fields
- Integration with Service wrapper

## Development Principles

1. **Core Before Services**: Build strong foundation before service layer
2. **No Backward Compatibility Requirement** (yet): Architecture evolves freely during development
3. **Design Patterns Over Quick Hacks**: Take time to design properly
4. **DRY Principle**: Eliminate all code duplication via helper methods
5. **Type Safety Everywhere**: Full type hints + Pydantic validation
6. **Clear Separation**: Each component has one responsibility
7. **Explicit Over Implicit**: `brotr.pool.fetch()` is clearer than `brotr.fetch()`
8. **Protocol-Based Design**: Non-invasive, flexible service wrapping

## Next Steps (Priority Order)

### Immediate Priority
1. **Implement Initializer Service** (~3-4 days) - CRITICAL
   - Bootstrap database, validate schemas, seed initial data
   - Needed for testing all other services

2. **Implement Finder Service** (~4-5 days) - HIGH
   - Discover Nostr relays from various sources
   - First production service using core layer

3. **Implement Monitor Service** (~5-7 days) - HIGH
   - Monitor relay health (NIP-11, NIP-66 checks)
   - Validates Service wrapper with real usage

4. **Set Up pytest Infrastructure** (~2-3 days) - HIGH (Parallel track)
   - Replace manual testing with automated tests
   - Core layer unit tests, integration tests

### Medium Priority
5. **Implement Synchronizer Service** (~7-10 days)
   - Synchronize events from Nostr relays
   - Main functionality of BigBrotr

6. **Implement Priority Synchronizer** (~5-7 days)
   - Priority-based event synchronization
   - Handles important relays differently

## Notes for AI Assistants

- **Read [PROJECT_SPECIFICATION.md](PROJECT_SPECIFICATION.md) first** for detailed API documentation
- **Check [PROJECT_STATUS.md](PROJECT_STATUS.md)** for current development phase and completion status (~41%)
- **Core layer is stable** (100% complete): Avoid breaking changes to ConnectionPool, Brotr, Service, Logger
- **Service layer is pending** (0% complete): Services can be designed/implemented freely
- **Configuration is YAML-driven**: Prefer config changes over code changes
- **Dependency injection is required**: Never create dependencies internally when they can be injected
- **Documentation is essential**: Update docstrings and project docs when changing code
- **Use helper methods**: Extract repeated logic into private helper methods with descriptive names
- **Protocol-based design**: Services don't need to inherit from anything, just implement protocol methods

## Quick Reference

### File Locations
- Core components: [src/core/](src/core/) (pool.py, brotr.py, service.py, logger.py)
- Services: [src/services/](src/services/) (empty stubs, pending implementation)
- Core config: [implementations/bigbrotr/yaml/core/brotr.yaml](implementations/bigbrotr/yaml/core/brotr.yaml)
- Service configs: [implementations/bigbrotr/yaml/services/](implementations/bigbrotr/yaml/services/) (empty, pending)
- SQL schemas: [implementations/bigbrotr/postgres/init/](implementations/bigbrotr/postgres/init/)
- Unit tests: [tests/unit/](tests/unit/) (test_pool.py, test_brotr.py, test_service.py, test_logger.py)
- Test config: [tests/conftest.py](tests/conftest.py), [pyproject.toml](pyproject.toml)

### Development Tools
- [pyproject.toml](pyproject.toml) - Project config (pytest, ruff, mypy, coverage)
- [requirements-dev.txt](requirements-dev.txt) - Development dependencies
- [.pre-commit-config.yaml](.pre-commit-config.yaml) - Pre-commit hooks (ruff, mypy, yamllint)
- [.gitignore](.gitignore) - Git ignore patterns

### Key Metrics
- Core layer: ~3,000 lines (100% complete)
- Service layer: 0 lines (0% complete)
- Unit tests: 112 tests (100% passing)
- Overall project: ~41% complete (weighted)

### Important Links
- [PROJECT_SPECIFICATION.md](PROJECT_SPECIFICATION.md) - Complete technical spec (v5.0, updated 2025-11-14)
- [PROJECT_STATUS.md](PROJECT_STATUS.md) - Current status and metrics (updated 2025-11-14)
- [README.md](README.md) - User-facing documentation
- [docs/old/](docs/old/) - Archived refactoring documents