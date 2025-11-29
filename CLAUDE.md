# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

BigBrotr is a modular, production-grade Nostr data archiving and monitoring system built on Python and PostgreSQL. It uses a three-layer architecture (Core, Service, Implementation) with dependency injection, making the codebase highly testable and maintainable.

**Current Status**: Core layer complete, service layer in progress
- **Core layer** (`src/core/`): 5 components production-ready (~1,715 LOC)
- **Service layer** (`src/services/`): 2/7 services implemented (Initializer, Finder)
- **Unit tests**: 108 tests passing
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

### Running Services
```bash
# Run services via CLI
cd implementations/bigbrotr
python -m services initializer
python -m services finder --log-level DEBUG
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
          ↑ Leverages (Initializer, Finder - others PENDING)
Core Layer (src/core/)
          PRODUCTION READY (Pool, Brotr, BaseService, Logger, Utils)
```

**Key Principle**: Core layer is implementation-agnostic and reusable. Services compose core components via dependency injection. Implementations customize behavior via YAML configuration.

### Core Components (Production Ready)

| Component | LOC | Purpose |
|-----------|-----|---------|
| **Pool** | ~410 | PostgreSQL connection management |
| **Brotr** | ~413 | Database interface + stored procedures |
| **BaseService** | ~455 | Abstract base class for all services |
| **Logger** | ~331 | Structured JSON logging |
| **Utils** | ~106 | Shared utilities (relay parsing, etc.) |

### Service Layer (2/7 Complete)

| Service | LOC | Status |
|---------|-----|--------|
| **Initializer** | ~493 | Production Ready |
| **Finder** | ~492 | Production Ready |
| Monitor | 14 | Pending |
| Synchronizer | 14 | Pending |
| Priority Synchronizer | 14 | Pending |
| API | 14 | Pending (Phase 3) |
| DVM | 14 | Pending (Phase 3) |

### Design Patterns in Use

| Pattern | Application | Purpose |
|---------|-------------|---------|
| **Dependency Injection** | Services receive `Brotr` | Flexibility, testability |
| **Composition over Inheritance** | Brotr HAS-A pool | Clear API, explicit separation |
| **Template Method** | `BaseService.run()` | DRY for service lifecycle |
| **Factory Method** | `from_yaml()`, `from_dict()` | Config-driven construction |
| **Abstract Base Class** | `BaseService[StateT]` | Consistent service interface |

### BaseService Architecture

All services inherit from `BaseService[StateT]` which provides:

```python
class BaseService(ABC, Generic[StateT]):
    SERVICE_NAME: str               # Unique service identifier
    CONFIG_CLASS: type[BaseModel]   # For automatic config parsing

    # Abstract methods (subclasses MUST implement)
    async def run(self) -> Outcome          # Main service logic
    async def health_check(self) -> bool    # Health status
    def _create_default_state(self) -> StateT
    def _state_from_dict(self, data) -> StateT

    # Provided methods
    async def start() / stop()              # Lifecycle
    async def run_forever(interval)         # Continuous operation
    async def _load_state() / _save_state() # Persistence
```

**Key Types**:
- `Step`: Individual operation step with name, success, message, details
- `Outcome`: Service run result with success, message, steps, duration, errors, metrics

## Configuration System

### YAML-Based Configuration
All components support configuration via YAML files in `implementations/bigbrotr/yaml/`:
- **Core**: `yaml/core/brotr.yaml` (includes pool config under `pool:` key)
- **Services**: `yaml/services/initializer.yaml`, `yaml/services/finder.yaml`

### Service Configuration Pattern

Services use `CONFIG_CLASS` for automatic YAML parsing:

```python
class Finder(BaseService[FinderState]):
    SERVICE_NAME = "finder"
    CONFIG_CLASS = FinderConfig  # Pydantic model

    def __init__(self, brotr: Brotr, config: Optional[FinderConfig] = None):
        super().__init__(brotr=brotr, config=config)
        self._config = config or FinderConfig()
```

Factory methods automatically use `CONFIG_CLASS`:
```python
# from_yaml calls from_dict which uses CONFIG_CLASS
finder = Finder.from_yaml("yaml/services/finder.yaml", brotr=brotr)
finder = Finder.from_dict(data, brotr=brotr)
```

### Configuration Examples

**Initializer** (`yaml/services/initializer.yaml`):
```yaml
verification:
  tables: true
  procedures: true
  extensions: true

seed:
  enabled: true
  path: data/seed_relays.txt
  batch_size: 100
```

**Finder** (`yaml/services/finder.yaml`):
```yaml
event_scan:
  enabled: true
  batch_size: 1000

api:
  enabled: true
  sources:
    - url: https://api.nostr.watch/v1/online
      enabled: true
```

### Environment Variables
- `DB_PASSWORD`: Database password (**required**, loaded automatically by Pool)
- `SOCKS5_PROXY_URL`: Tor proxy URL (optional)

## Working with the Codebase

### Adding New Services

1. Create service file in `src/services/`
2. Inherit from `BaseService[YourStateT]`
3. Set `SERVICE_NAME` and `CONFIG_CLASS` class attributes
4. Implement abstract methods: `run()`, `health_check()`, `_create_default_state()`, `_state_from_dict()`
5. Create YAML config in `implementations/bigbrotr/yaml/services/`
6. Add to `SERVICE_RUNNERS` in `src/services/__main__.py`
7. Export from `src/services/__init__.py`

Example:
```python
from core.base_service import BaseService, Outcome, Step
from core.brotr import Brotr

SERVICE_NAME = "monitor"

class MonitorConfig(BaseModel):
    check_interval: float = 300.0

@dataclass
class MonitorState:
    last_check_at: int = 0

    def to_dict(self) -> dict:
        return {"last_check_at": self.last_check_at}

    @classmethod
    def from_dict(cls, data: dict) -> "MonitorState":
        return cls(last_check_at=data.get("last_check_at", 0))

class Monitor(BaseService[MonitorState]):
    SERVICE_NAME = SERVICE_NAME
    CONFIG_CLASS = MonitorConfig

    def __init__(self, brotr: Brotr, config: Optional[MonitorConfig] = None):
        super().__init__(brotr=brotr, config=config)
        self._config = config or MonitorConfig()

    def _create_default_state(self) -> MonitorState:
        return MonitorState()

    def _state_from_dict(self, data: dict) -> MonitorState:
        return MonitorState.from_dict(data)

    async def health_check(self) -> bool:
        return self._pool.is_connected

    async def run(self) -> Outcome:
        # Implementation here
        pass
```

### Database Schema

SQL files in `implementations/bigbrotr/postgres/init/` must be applied in numerical order:

1. `00_extensions.sql` - PostgreSQL extensions (pgcrypto, btree_gin)
2. `01_utility_functions.sql` - Helper functions
3. `02_tables.sql` - Table definitions
4. `03_indexes.sql` - Performance indexes
5. `04_integrity_functions.sql` - Data integrity checks
6. `05_procedures.sql` - Stored procedures (called by Brotr)
7. `06_views.sql` - Database views
8. `99_verify.sql` - Schema validation

### Key Tables

- `relays`: Known Nostr relays with network type
- `events`: Nostr events (bytea IDs for efficiency)
- `events_relays`: Event-relay associations with seen_at timestamp
- `nip11`, `nip66`: Relay metadata
- `service_state`: Service state persistence (JSON)

## Testing Infrastructure

**Test Files**:
- `tests/unit/test_pool.py` - Pool tests
- `tests/unit/test_brotr.py` - Brotr tests
- `tests/unit/test_initializer.py` - Initializer service tests
- `tests/unit/test_finder.py` - Finder service tests

**Running Tests**:
```bash
source .venv/bin/activate
pytest tests/unit/ -v              # All unit tests
pytest --cov=src                   # With coverage
pytest -k "health_check"           # Pattern matching
```

When adding tests:
- Test `from_yaml()` and `from_dict()` factory methods
- Test state persistence (`_load_state`, `_save_state`)
- Test `run()` outcomes (success/failure cases)
- Use mocks for database and external APIs

## Important Implementation Details

### Services Receive Brotr (Not Pool)

Services receive `Brotr` via constructor injection. Access pool via `self._pool` (convenience reference):

```python
class Finder(BaseService[FinderState]):
    def __init__(self, brotr: Brotr, config: Optional[FinderConfig] = None):
        super().__init__(brotr=brotr, config=config)  # Sets self._brotr and self._pool
```

### State Persistence

Services persist state to `service_state` table:

```python
# State is saved automatically on stop()
await self._save_state()

# State is loaded automatically on start()
await self._load_state()

# Access current state
self._state.last_seen_at
```

### Atomic Batch Processing

Finder demonstrates atomic commits for crash consistency:

```python
async with self._pool.transaction() as conn:
    # Insert relays
    for r in records:
        await conn.execute("SELECT insert_relay($1, $2, $3)", ...)

    # Update state atomically
    await conn.execute("INSERT INTO service_state ...")

# Update in-memory state AFTER successful commit
self._state.last_seen_at = new_watermark
```

### Context Manager Usage

Services and Pool support async context managers:

```python
async with brotr.pool:
    async with finder:
        result = await finder.run()
```

## Project Structure

```
src/
├── core/                    # Foundation components
│   ├── __init__.py          # Exports: Pool, Brotr, BaseService, Logger, Step, Outcome
│   ├── pool.py              # PostgreSQL connection management
│   ├── brotr.py             # Database interface + stored procedures
│   ├── base_service.py      # Abstract base class for services
│   ├── logger.py            # Structured JSON logging
│   └── utils.py             # Shared utilities
│
├── services/                # Service implementations
│   ├── __init__.py          # Exports service classes and constants
│   ├── __main__.py          # CLI entry point
│   ├── initializer.py       # Database bootstrap
│   ├── finder.py            # Relay discovery
│   └── ...                  # Other services (pending)
│
implementations/
└── bigbrotr/
    ├── yaml/
    │   ├── core/brotr.yaml     # Pool + Brotr config
    │   └── services/           # Service configs
    ├── postgres/init/          # SQL schemas
    ├── docker-compose.yaml     # Deployment
    └── .env                    # Environment variables

tests/
└── unit/                    # Unit tests (108 tests)
```

## Git Workflow

- **Main branch**: `main` (stable releases)
- **Development branch**: `develop` (active development)
- **PR target**: Create PRs from feature branches to `main`
- **Commit style**: Conventional commits (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`)

## Technology Stack

### Core Dependencies
- **Python 3.9+**: Language
- **PostgreSQL 14+**: Database
- **asyncpg 0.30.0**: Async PostgreSQL driver
- **Pydantic 2.10.4**: Configuration validation
- **PyYAML 6.0.2**: YAML parsing
- **aiohttp 3.13.2**: Async HTTP client
- **nostr-tools 1.4.0**: Nostr protocol library

### Infrastructure
- **Docker + Docker Compose**: Container orchestration
- **PGBouncer**: Connection pooling
- **Tor (optional)**: Network privacy via SOCKS5 proxy

## Development Principles

1. **Services receive Brotr**: All services receive `Brotr` via constructor, not `Pool`
2. **CONFIG_CLASS for auto-parsing**: Set `CONFIG_CLASS` on services for automatic YAML parsing
3. **State persistence**: Services save/load state via `service_state` table
4. **Atomic commits**: Batch operations commit data + state in single transaction
5. **Factory methods**: All components support `from_yaml()` and `from_dict()`
6. **Type safety**: Full type hints + Pydantic validation

## Quick Reference

### File Locations
- Core components: `src/core/` (pool.py, brotr.py, base_service.py, logger.py, utils.py)
- Services: `src/services/` (initializer.py, finder.py implemented; others pending)
- Core config: `implementations/bigbrotr/yaml/core/brotr.yaml`
- Service configs: `implementations/bigbrotr/yaml/services/`
- SQL schemas: `implementations/bigbrotr/postgres/init/`
- Unit tests: `tests/unit/`

### Key Exports

**From `core`**:
```python
from core import Pool, Brotr, BaseService, Step, Outcome, get_logger
```

**From `services`**:
```python
from services import Initializer, Finder, InitializerConfig, FinderConfig
```

### Service Name Constants
```python
from services.initializer import SERVICE_NAME as INITIALIZER_SERVICE_NAME  # "initializer"
from services.finder import SERVICE_NAME as FINDER_SERVICE_NAME            # "finder"
```

## Notes for AI Assistants

- **Services receive `Brotr`**, not `Pool` directly
- **`CONFIG_CLASS` enables automatic config parsing** via `from_dict()`
- **`Step` and `Outcome` are in `base_service.py`**, exported from `core`
- **State classes use dataclasses** with `to_dict()` and `from_dict()` methods
- **YAML keys must match Pydantic field names** (e.g., `seed:` not `seed_relays:`)
- **108 unit tests** validate current implementation
- **Service layer is 2/7 complete**: Monitor service is next priority