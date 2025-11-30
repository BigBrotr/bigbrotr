# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

BigBrotr is a modular Nostr data archiving and monitoring system built on Python and PostgreSQL. It uses a three-layer architecture (Core, Service, Implementation) with dependency injection.

**Current Status**: In Development
- **Core layer** (`src/core/`): 4 components functional (~1,090 lines)
- **Service layer** (`src/services/`): 4/6 services (Initializer, Finder partial, Monitor, Synchronizer)
- **Unit tests**: 174 passing (~3,500 lines)
- **Primary branch**: `develop` (create PRs to `main`)

**Known Incomplete Features**:
- Finder: `_find_from_events()` is empty (TODO)
- API service: stub file only
- DVM service: stub file only
- No database backup strategy
- No integration tests

## Common Commands

### Development Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Set up environment
cp implementations/bigbrotr/.env.example implementations/bigbrotr/.env
nano implementations/bigbrotr/.env  # Set DB_PASSWORD

# Run with Docker Compose
cd implementations/bigbrotr
docker-compose up -d
```

### Testing
```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

# Run all unit tests
pytest tests/unit/ -v

# Run with coverage
pytest tests/unit/ --cov=src --cov-report=html

# Run specific test file
pytest tests/unit/test_synchronizer.py -v

# Run tests matching pattern
pytest -k "health_check" -v
```

### Running Services
```bash
# From implementations/bigbrotr/
cd implementations/bigbrotr
python -m services initializer
python -m services finder
python -m services monitor
python -m services synchronizer
python -m services finder --log-level DEBUG
python -m services finder --config yaml/services/finder.yaml
```

## Architecture

### Three-Layer Design

```
Implementation Layer (implementations/bigbrotr/)
    YAML configs, SQL schemas, Docker, seed data
          ↑ Uses
Service Layer (src/services/)
    Initializer [DONE], Finder [PARTIAL], Monitor [DONE], Synchronizer [DONE]
    API [NOT IMPL], DVM [NOT IMPL]
          ↑ Leverages
Core Layer (src/core/)
    Pool, Brotr, BaseService, Logger [ALL DONE]
```

**Key Principle**: Core layer is implementation-agnostic. Services compose core components via dependency injection. Implementations customize behavior via YAML configuration.

### Core Components

| Component | Purpose | Lines |
|-----------|---------|-------|
| **Pool** | PostgreSQL connection pooling with asyncpg, retry logic | ~410 |
| **Brotr** | Database interface with stored procedure wrappers | ~430 |
| **BaseService** | Abstract base class with lifecycle, state persistence | ~200 |
| **Logger** | Structured logging wrapper | ~50 |

### Service Layer Status

| Service | Status | Description |
|---------|--------|-------------|
| **Initializer** | Done | Database bootstrap, schema verification, seed data |
| **Finder** | Partial | API discovery works; `_find_from_events()` is TODO |
| **Monitor** | Done | NIP-11/NIP-66 health checking with Tor support |
| **Synchronizer** | Done | Multicore event sync via aiomultiprocess |
| API | Not implemented | Stub file only |
| DVM | Not implemented | Stub file only |

### Design Patterns

| Pattern | Application |
|---------|-------------|
| **Dependency Injection** | Services receive `Brotr` instance |
| **Composition** | Brotr HAS-A Pool |
| **Template Method** | `BaseService.run_forever()` calls `run()` |
| **Factory Method** | `from_yaml()`, `from_dict()` |
| **Context Manager** | `async with brotr:`, `async with service:` |

## Configuration

### YAML Configuration
- **Core**: `yaml/core/brotr.yaml` (pool config under `pool:` key)
- **Services**: `yaml/services/<service>.yaml`

**Note**: Stored procedure names are hardcoded in `src/core/brotr.py` for security (not configurable).

### Environment Variables
- `DB_PASSWORD`: Database password (**required**)
- `MONITOR_PRIVATE_KEY`: Nostr key for NIP-66 write tests (optional)

### Service Configuration Pattern

```python
class MyService(BaseService[MyServiceConfig]):
    SERVICE_NAME = "myservice"
    CONFIG_CLASS = MyServiceConfig  # Pydantic model

    def __init__(self, brotr: Brotr, config: MyServiceConfig | None = None):
        super().__init__(brotr=brotr, config=config or MyServiceConfig())
```

Factory methods use `CONFIG_CLASS` automatically:
```python
service = MyService.from_yaml("yaml/services/myservice.yaml", brotr=brotr)
```

## Working with the Codebase

### Adding New Services

1. Create `src/services/myservice.py`:

```python
from pydantic import BaseModel, Field
from core.base_service import BaseService
from core.brotr import Brotr

SERVICE_NAME = "myservice"

class MyServiceConfig(BaseModel):
    interval: float = Field(default=300.0, ge=60.0)

class MyService(BaseService[MyServiceConfig]):
    SERVICE_NAME = SERVICE_NAME
    CONFIG_CLASS = MyServiceConfig

    def __init__(self, brotr: Brotr, config: MyServiceConfig | None = None):
        super().__init__(brotr=brotr, config=config or MyServiceConfig())
        self._config: MyServiceConfig

    async def run(self) -> None:
        """Single cycle logic."""
        pass
```

2. Create YAML config in `implementations/bigbrotr/yaml/services/myservice.yaml`
3. Register in `src/services/__main__.py` (add to `SERVICE_REGISTRY`)
4. Export from `src/services/__init__.py`

### BaseService Interface

```python
class BaseService(ABC, Generic[ConfigT]):
    SERVICE_NAME: str                    # Unique identifier
    CONFIG_CLASS: type[ConfigT]          # For auto config parsing

    _brotr: Brotr                        # Database interface
    _config: ConfigT                     # Pydantic config
    _state: dict[str, Any]               # Persisted state (JSONB)

    # Abstract (must implement)
    async def run(self) -> None          # Single cycle logic

    # Provided methods
    async def run_forever(interval)      # Continuous loop
    async def health_check() -> bool     # Database connectivity
    def request_shutdown()               # Sync-safe shutdown trigger
    async def wait(timeout) -> bool      # Interruptible sleep

    # Context manager
    async with service:                  # Calls _load_state on enter, _save_state on exit
```

### State Persistence

State is automatically loaded/saved via context manager:

```python
async with brotr:
    async with finder:  # _load_state() called here
        await finder.run_forever(interval=3600)
    # _save_state() called here
```

Access state dict directly:
```python
self._state["last_run_at"] = int(time.time())
self._state["total_count"] = self._state.get("total_count", 0) + count
```

### Graceful Shutdown

```python
# In signal handler (sync-safe)
service.request_shutdown()

# In service run() - interruptible wait
if await self.wait(60):  # Returns True if shutdown requested
    return
```

## Database Schema

SQL files in `implementations/bigbrotr/postgres/init/` (apply in numerical order):

| File | Purpose |
|------|---------|
| `00_extensions.sql` | pgcrypto, btree_gin |
| `01_utility_functions.sql` | tags_to_tagvalues, hash functions |
| `02_tables.sql` | All tables |
| `03_indexes.sql` | Performance indexes |
| `04_integrity_functions.sql` | delete_orphan_* functions |
| `05_procedures.sql` | insert_event, insert_relay, insert_relay_metadata |
| `06_views.sql` | Statistics and metadata views |
| `99_verify.sql` | Schema validation |

### Key Tables

| Table | Purpose |
|-------|---------|
| `relays` | Known relay URLs with network type |
| `events` | Nostr events (BYTEA IDs for 50% space savings) |
| `events_relays` | Event-relay junction with seen_at |
| `nip11` | Deduplicated NIP-11 documents |
| `nip66` | Deduplicated NIP-66 test results |
| `relay_metadata` | Time-series metadata snapshots |
| `service_state` | Service state persistence (JSONB) |

## Project Structure

```
src/
├── core/
│   ├── __init__.py          # Exports: Pool, Brotr, BaseService, Logger
│   ├── pool.py              # PostgreSQL connection pool (~410 lines)
│   ├── brotr.py             # Database interface (~430 lines)
│   ├── base_service.py      # Abstract service base (~200 lines)
│   └── logger.py            # Logging wrapper (~50 lines)
│
├── services/
│   ├── __init__.py          # Service exports
│   ├── __main__.py          # CLI entry point
│   ├── initializer.py       # Schema verification, seeding (~310 lines)
│   ├── finder.py            # Relay discovery (~220 lines)
│   ├── monitor.py           # Health monitoring (~400 lines)
│   ├── synchronizer.py      # Event sync (~740 lines)
│   ├── api.py               # NOT IMPLEMENTED (stub)
│   └── dvm.py               # NOT IMPLEMENTED (stub)

implementations/bigbrotr/
├── yaml/
│   ├── core/brotr.yaml      # Pool + Brotr config
│   └── services/            # Service configs
├── postgres/init/           # SQL schemas (00-99)
├── data/seed_relays.txt     # 8,865 seed relay URLs
├── docker-compose.yaml
└── .env.example

tests/unit/                  # 174 unit tests
```

## Git Workflow

- **Main branch**: `main` (stable)
- **Development branch**: `develop` (active)
- **PR target**: `main`
- **Commit style**: Conventional commits (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`)

## Technology Stack

- **Python 3.9+**
- **PostgreSQL 16+** with PGBouncer
- **asyncpg 0.30.0** - Async PostgreSQL driver
- **Pydantic 2.10.4** - Configuration validation
- **aiohttp 3.13.2** - Async HTTP client
- **aiohttp-socks 0.10.1** - SOCKS5 proxy for Tor
- **aiomultiprocess 0.9.1** - Multicore processing
- **nostr-tools 1.4.1** - Nostr protocol library

## Key Exports

**From `core`**:
```python
from core import Pool, PoolConfig, Brotr, BrotrConfig, BaseService, Logger
```

**From `services`**:
```python
from services import Initializer, InitializerConfig
from services import Finder, FinderConfig
from services import Monitor, MonitorConfig
from services import Synchronizer, SynchronizerConfig
```

## Notes for AI Assistants

- **Services receive `Brotr`**, access pool via `self._brotr.pool`
- **`CONFIG_CLASS`** enables automatic config parsing in `from_yaml()`
- **State is a dict** (`self._state`), persisted to `service_state` table automatically
- **`run()` is single-cycle**, `run_forever()` handles the loop
- **Context manager** handles `_load_state()` and `_save_state()` automatically
- **`request_shutdown()`** is sync-safe for signal handlers
- **Stored procedures** are hardcoded in `brotr.py` constants (not YAML configurable)
- **YAML keys must match Pydantic field names** exactly

### Known TODOs in Code

1. `src/services/finder.py`: `_find_from_events()` is empty
2. `src/services/api.py`: Stub only
3. `src/services/dvm.py`: Stub only
4. No database backup strategy
5. No integration tests
6. Views may need optimization for large datasets