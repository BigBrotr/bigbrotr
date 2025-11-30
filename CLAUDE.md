# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

BigBrotr is a modular, production-grade Nostr data archiving and monitoring system built on Python and PostgreSQL. It uses a three-layer architecture (Core, Service, Implementation) with dependency injection, making the codebase highly testable and maintainable.

**Current Status**: Core layer complete, service layer in progress
- **Core layer** (`src/core/`): 4 components production-ready
- **Service layer** (`src/services/`): 2/7 services implemented (Initializer, Finder)
- **Unit tests**: 90 tests passing
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
docker-compose exec postgres psql -U admin -d bigbrotr -c "\dt"
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
# Run services via CLI (from implementations/bigbrotr/)
cd implementations/bigbrotr
python -m services initializer
python -m services finder
python -m services finder --log-level DEBUG
python -m services finder --config yaml/services/finder.yaml
```

### Database Operations
```bash
# Initialize database with SQL schemas (apply in numerical order)
cd implementations/bigbrotr/postgres/init
psql -U admin -d bigbrotr -f 00_extensions.sql
psql -U admin -d bigbrotr -f 01_utility_functions.sql
psql -U admin -d bigbrotr -f 02_tables.sql
psql -U admin -d bigbrotr -f 03_indexes.sql
psql -U admin -d bigbrotr -f 04_integrity_functions.sql
psql -U admin -d bigbrotr -f 05_procedures.sql
psql -U admin -d bigbrotr -f 06_views.sql
psql -U admin -d bigbrotr -f 99_verify.sql
```

## Architecture

### Three-Layer Design Philosophy

```
Implementation Layer (implementations/bigbrotr/)
          ↑ Uses (YAML configs, SQL schemas)
Service Layer (src/services/)
          ↑ Leverages (Initializer, Finder - others PENDING)
Core Layer (src/core/)
          PRODUCTION READY (Pool, Brotr, BaseService, Logger)
```

**Key Principle**: Core layer is implementation-agnostic and reusable. Services compose core components via dependency injection. Implementations customize behavior via YAML configuration.

### Core Components

| Component | Purpose |
|-----------|---------|
| **Pool** | PostgreSQL connection pooling with asyncpg, retry logic, health checks |
| **Brotr** | Database interface with stored procedure wrappers, bulk inserts |
| **BaseService** | Abstract base class with lifecycle, state persistence, run_forever() |
| **Logger** | Structured logging wrapper |

### Service Layer (2/7 Complete)

| Service | Status | Description |
|---------|--------|-------------|
| **Initializer** | Complete | Database bootstrap, schema verification, seed data |
| **Finder** | Complete | Relay discovery from APIs |
| Monitor | Stub | Relay health monitoring |
| Synchronizer | Stub | Event synchronization |
| Priority Synchronizer | Stub | Priority-based sync |
| API | Stub | REST API |
| DVM | Stub | NIP-90 Data Vending Machine |

### Design Patterns

| Pattern | Application |
|---------|-------------|
| **Dependency Injection** | Services receive `Brotr` instance |
| **Composition** | Brotr HAS-A Pool |
| **Template Method** | `BaseService.run_forever()` calls `run()` |
| **Factory Method** | `from_yaml()`, `from_dict()` |
| **Abstract Base Class** | `BaseService` |

### BaseService Architecture

```python
class BaseService(ABC):
    SERVICE_NAME: str                    # Unique identifier
    CONFIG_CLASS: type[BaseModel]        # For auto config parsing

    # Core attributes
    _brotr: Brotr                        # Database interface
    _config: BaseModel                   # Pydantic config
    _state: dict[str, Any]               # Persisted state
    _is_running: bool                    # Lifecycle flag
    _shutdown_event: asyncio.Event       # For graceful shutdown

    # Abstract (must implement)
    async def run(self) -> None          # Single cycle logic

    # Provided methods
    async def run_forever(interval)      # Continuous operation loop
    async def health_check() -> bool     # Database connectivity check
    def request_shutdown()               # Sync-safe shutdown trigger
    async def wait(timeout) -> bool      # Interruptible sleep
    async def _load_state()              # Load from service_state table
    async def _save_state()              # Save to service_state table

    # Context manager
    async with service:                  # Calls _load_state on enter, _save_state on exit
```

## Configuration System

### YAML-Based Configuration
- **Core**: `yaml/core/brotr.yaml` (includes pool config under `pool:` key)
- **Services**: `yaml/services/<service>.yaml`

### Service Configuration Pattern

```python
class Finder(BaseService):
    SERVICE_NAME = "finder"
    CONFIG_CLASS = FinderConfig  # Pydantic model

    def __init__(self, brotr: Brotr, config: Optional[FinderConfig] = None):
        super().__init__(brotr=brotr, config=config or FinderConfig())
```

Factory methods use `CONFIG_CLASS` automatically:
```python
finder = Finder.from_yaml("yaml/services/finder.yaml", brotr=brotr)
finder = Finder.from_dict(data, brotr=brotr)
```

### Configuration Examples

**Initializer** (`yaml/services/initializer.yaml`):
```yaml
verification:
  extensions: true
  tables: true
  procedures: true

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
      timeout: 30.0
    - url: https://api.nostr.watch/v1/offline
      enabled: true
      timeout: 30.0
  request_delay: 1.0

discovery_interval: 3600.0
```

### Environment Variables
- `DB_PASSWORD`: Database password (**required**, loaded by Pool)

## Working with the Codebase

### Adding New Services

1. Create service file in `src/services/`
2. Inherit from `BaseService`
3. Set `SERVICE_NAME` and `CONFIG_CLASS` class attributes
4. Implement `run()` method
5. Create YAML config in `implementations/bigbrotr/yaml/services/`
6. Add runner to `SERVICE_RUNNERS` in `src/services/__main__.py`
7. Export from `src/services/__init__.py`

Example:
```python
from pydantic import BaseModel, Field
from core.base_service import BaseService
from core.brotr import Brotr

SERVICE_NAME = "monitor"

class MonitorConfig(BaseModel):
    check_interval: float = Field(default=300.0)

class Monitor(BaseService):
    SERVICE_NAME = SERVICE_NAME
    CONFIG_CLASS = MonitorConfig

    def __init__(self, brotr: Brotr, config: Optional[MonitorConfig] = None):
        super().__init__(brotr=brotr, config=config or MonitorConfig())
        self._config: MonitorConfig

    async def run(self) -> None:
        # Single cycle logic here
        pass
```

### Database Schema

SQL files in `implementations/bigbrotr/postgres/init/` (apply in order):

1. `00_extensions.sql` - pgcrypto, btree_gin
2. `01_utility_functions.sql` - tags_to_tagvalues, hash functions
3. `02_tables.sql` - relays, events, events_relays, nip11, nip66, relay_metadata, service_state
4. `03_indexes.sql` - Performance indexes
5. `04_integrity_functions.sql` - delete_orphan_* functions
6. `05_procedures.sql` - insert_event, insert_relay, insert_relay_metadata
7. `06_views.sql` - relay_metadata_latest, statistics views
8. `99_verify.sql` - Schema validation

### Key Tables

| Table | Purpose |
|-------|---------|
| `relays` | Known relay URLs with network type |
| `events` | Nostr events (BYTEA IDs) |
| `events_relays` | Event-relay junction with seen_at |
| `nip11` | Deduplicated NIP-11 info documents |
| `nip66` | Deduplicated NIP-66 test results |
| `relay_metadata` | Time-series metadata snapshots |
| `service_state` | Service state persistence (JSONB) |

## Testing

**Test Files**:
- `tests/unit/test_pool.py` - Pool tests
- `tests/unit/test_brotr.py` - Brotr tests
- `tests/unit/test_initializer.py` - Initializer tests
- `tests/unit/test_finder.py` - Finder tests
- `tests/unit/test_logger.py` - Logger tests

**Running Tests**:
```bash
pytest tests/unit/ -v              # All tests
pytest tests/unit/ -q              # Quiet mode
pytest --cov=src                   # With coverage
pytest -k "health_check"           # Pattern matching
```

## Important Implementation Details

### Services Receive Brotr

```python
class Finder(BaseService):
    def __init__(self, brotr: Brotr, config: Optional[FinderConfig] = None):
        super().__init__(brotr=brotr, config=config or FinderConfig())
        # Access pool via self._brotr.pool
```

### State Persistence

State is automatically loaded/saved via context manager:

```python
async with brotr.pool:
    async with finder:  # _load_state() called here
        await finder.run_forever(interval=3600)
    # _save_state() called here
```

Access state dict directly:
```python
self._state["last_run_at"] = int(time.time())
self._state["total_count"] = self._state.get("total_count", 0) + new_count
```

### Context Manager Usage

```python
async with brotr.pool:
    async with service:
        await service.run()           # One-shot
        # or
        await service.run_forever(interval=3600)  # Continuous
```

### Graceful Shutdown

```python
# In signal handler (sync-safe)
service.request_shutdown()

# In service run() - interruptible wait
if await self.wait(60):  # Returns True if shutdown requested
    return
```

## Project Structure

```
src/
├── core/
│   ├── __init__.py          # Exports: Pool, Brotr, BaseService, Logger
│   ├── pool.py              # PostgreSQL connection pool
│   ├── brotr.py             # Database interface
│   ├── base_service.py      # Abstract service base class
│   └── logger.py            # Logging wrapper
│
├── services/
│   ├── __init__.py          # Exports: Initializer, Finder, configs
│   ├── __main__.py          # CLI entry point
│   ├── initializer.py       # Schema verification, seeding
│   ├── finder.py            # Relay discovery
│   └── ...                  # Stub services

implementations/bigbrotr/
├── yaml/
│   ├── core/brotr.yaml      # Pool + Brotr config
│   └── services/            # Service configs
├── postgres/
│   ├── init/                # SQL schemas (00-99)
│   └── postgresql.conf      # PostgreSQL config
├── pgbouncer/               # PGBouncer config
├── docker-compose.yaml
└── .env                     # DB_PASSWORD

tests/unit/                  # 90 unit tests
```

## Git Workflow

- **Main branch**: `main` (stable)
- **Development branch**: `develop` (active)
- **PR target**: `main`
- **Commit style**: Conventional commits (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`)

## Technology Stack

- **Python 3.9+**
- **PostgreSQL 14+** with PGBouncer
- **asyncpg 0.30.0** - Async PostgreSQL driver
- **Pydantic 2.10.4** - Configuration validation
- **aiohttp 3.13.2** - Async HTTP client
- **nostr-tools 1.4.0** - Nostr protocol library
- **Docker + Docker Compose**

## Key Exports

**From `core`**:
```python
from core import Pool, PoolConfig, Brotr, BrotrConfig, BaseService, Logger
```

**From `services`**:
```python
from services import Initializer, InitializerConfig, Finder, FinderConfig
from services import INITIALIZER_SERVICE_NAME, FINDER_SERVICE_NAME
```

## Notes for AI Assistants

- **Services receive `Brotr`**, access pool via `self._brotr.pool`
- **`CONFIG_CLASS`** enables automatic config parsing in `from_dict()`
- **State is a simple dict** (`self._state`), persisted to `service_state` table
- **`run()` is single-cycle**, `run_forever()` handles the loop
- **Context manager** handles `_load_state()` and `_save_state()` automatically
- **`request_shutdown()`** is sync-safe for signal handlers
- **90 unit tests** validate current implementation
- **YAML keys must match Pydantic field names** exactly
