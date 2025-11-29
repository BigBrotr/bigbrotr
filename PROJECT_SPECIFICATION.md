# BigBrotr Project Specification v6.0

**Last Updated**: 2025-11-29
**Status**: Core Complete, Service Layer in Progress (2/7)
**Version**: 1.0.0-dev

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Architecture](#architecture)
3. [Core Components](#core-components)
4. [Service Layer](#service-layer)
5. [Database Schema](#database-schema)
6. [Configuration](#configuration)
7. [Deployment](#deployment)
8. [Development Roadmap](#development-roadmap)
9. [Design Patterns](#design-patterns)

---

## Project Overview

### What is BigBrotr?

**BigBrotr** is a modular, production-grade Nostr data archiving and monitoring system built on Python and PostgreSQL. It provides comprehensive network monitoring, event synchronization, and relay discovery for the Nostr protocol ecosystem.

### Mission

Archive and monitor the Nostr protocol network, providing reliable data access for analysis, research, and applications.

### Key Features

- **Scalable Architecture**: Three-layer design (Core, Service, Implementation)
- **Production-Ready Core**: Enterprise-grade pooling, retry logic, lifecycle management
- **Dependency Injection**: Clean, testable component composition
- **Structured Logging**: JSON-formatted logs for all operations
- **Flexible Deployment**: Docker Compose orchestration
- **Network Support**: Clearnet and Tor (SOCKS5 proxy)
- **Type Safety**: Full type hints and Pydantic validation

### Design Philosophy

1. **Separation of Concerns**: Core (reusable) -> Services (modular) -> Implementation (config-driven)
2. **Dependency Injection**: Services receive `Brotr` via constructor
3. **Configuration-Driven**: YAML configs, environment variables, zero hardcoded values
4. **Abstract Base Class**: All services inherit from `BaseService[StateT]`
5. **Type Safety Everywhere**: Full type hints, Pydantic validation for all configs

---

## Architecture

### Three-Layer Design

```
Implementation Layer (implementations/bigbrotr/)

  - YAML Configurations (core, services)
  - PostgreSQL Schemas (tables, views, procedures)
  - Deployment Specs (Docker Compose, env vars)
  - Seed Data (relay lists)

  Purpose: Define HOW this instance behaves
          ↑
          │ Uses
          │
Service Layer (src/services/)

  - Initializer: Database bootstrap (DONE)
  - Finder: Relay discovery (DONE)
  - Monitor: Health checks (NIP-11, NIP-66) - PENDING
  - Synchronizer: Event collection - PENDING
  - Priority Synchronizer: Priority relays - PENDING
  - API: REST endpoints (Phase 3) - PENDING
  - DVM: Data Vending Machine (Phase 3) - PENDING

  Purpose: Business logic, coordination
  Status: 2/7 COMPLETE
          ↑
          │ Leverages
          │
Core Layer (src/core/)

  - Pool: PostgreSQL connection management
  - Brotr: Database interface + stored procedures
  - BaseService: Abstract base class for all services
  - Logger: Structured JSON logging
  - Utils: Shared utilities

  Purpose: Reusable foundation, zero business logic
  Status: PRODUCTION READY (~1,715 LOC)
```

### Layer Responsibilities

| Layer | Responsibility | Status |
|-------|---------------|--------|
| **Implementation** | Configuration, deployment, data | Partial |
| **Service** | Business logic, orchestration | 2/7 Complete |
| **Core** | Infrastructure, utilities | Complete |

---

## Core Components

### Overview

The core layer (`src/core/`) is production-ready with five components totaling ~1,715 lines of code.

| Component | LOC | Purpose |
|-----------|-----|---------|
| Pool | ~410 | PostgreSQL connection management |
| Brotr | ~413 | Database interface with stored procedures |
| BaseService | ~455 | Abstract base class for all services |
| Logger | ~331 | Structured JSON logging |
| Utils | ~106 | Shared utilities |

---

### 1. Pool (`src/core/pool.py`)

**Purpose**: Enterprise-grade PostgreSQL connection management using asyncpg.

**Features**:
- Async pooling with asyncpg
- Automatic retry logic with exponential backoff
- PGBouncer compatibility (transaction mode)
- Connection lifecycle management
- Configurable pool sizes and timeouts
- Connection recycling
- Environment variable password loading (`DB_PASSWORD`)
- YAML/dict configuration support via factory methods
- Context manager support

**Configuration**:
```yaml
pool:
  database:
    host: localhost
    port: 5432
    database: brotr
    user: admin

  limits:
    min_size: 5
    max_size: 20
    max_queries: 50000
    max_inactive_connection_lifetime: 300.0

  timeouts:
    acquisition: 10.0

  retry:
    max_attempts: 3
    initial_delay: 1.0
    max_delay: 10.0
    exponential_backoff: true
```

**API**:
```python
from core.pool import Pool

# From YAML
pool = Pool.from_yaml("yaml/core/brotr.yaml")

# Direct instantiation
pool = Pool(host="localhost", database="brotr", min_size=5, max_size=20)

# Context manager usage
async with pool:
    result = await pool.fetch("SELECT * FROM events LIMIT 10")
    await pool.execute("INSERT INTO events ...")
```

---

### 2. Brotr (`src/core/brotr.py`)

**Purpose**: High-level database interface with stored procedure wrappers.

**Features**:
- Composition pattern: HAS-A pool (public property)
- Stored procedure wrappers (insert_event, insert_relay, etc.)
- Batch operations with configurable sizes
- Cleanup operations (delete orphaned records)
- Hex to bytea conversion for efficient storage
- YAML/dict configuration support

**Key Design Decision**: Brotr HAS-A pool, not IS-A pool
- Clear separation: `brotr.pool.fetch()` vs `brotr.insert_event()`
- No method name conflicts
- Easy pool sharing across services

**Configuration**:
```yaml
pool:
  # Pool configuration...

batch:
  max_batch_size: 10000

procedures:
  insert_event: insert_event
  insert_relay: insert_relay
  delete_orphan_events: delete_orphan_events

timeouts:
  query: 60.0
  procedure: 90.0
  batch: 120.0
```

**API**:
```python
from core.brotr import Brotr
from core.pool import Pool

# Option 1: From YAML
brotr = Brotr.from_yaml("yaml/core/brotr.yaml")

# Option 2: Inject custom pool
pool = Pool(host="localhost", database="brotr")
brotr = Brotr(pool=pool)

# Usage
async with brotr.pool:
    await brotr.insert_event(event_id="...", pubkey="...", ...)
    await brotr.insert_relays(records)
    deleted = await brotr.cleanup_orphans()
```

---

### 3. BaseService (`src/core/base_service.py`)

**Purpose**: Abstract base class that all services inherit from. Provides consistent lifecycle, logging, and state persistence.

**Features**:
- Generic type parameter for state: `BaseService[StateT]`
- `CONFIG_CLASS` attribute for automatic config parsing
- Structured logging via `self._logger`
- State persistence via `_load_state()` / `_save_state()`
- Lifecycle management via `start()` / `stop()`
- Factory methods `from_yaml()` / `from_dict()`
- Context manager support
- Continuous operation via `run_forever(interval)`

**Abstract Methods (subclasses MUST implement)**:
```python
async def run(self) -> Outcome           # Main service logic
async def health_check(self) -> bool     # Health status
def _create_default_state(self) -> StateT
def _state_from_dict(self, data: dict) -> StateT
```

**Key Types**:

```python
@dataclass
class Step:
    """Individual operation step."""
    name: str
    success: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0

@dataclass
class Outcome:
    """Service run result."""
    success: bool
    message: str
    steps: list[Step] = field(default_factory=list)
    duration_s: float = 0.0
    errors: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
```

**Service Implementation Pattern**:
```python
from core.base_service import BaseService, Outcome
from core.brotr import Brotr

SERVICE_NAME = "my_service"

class MyServiceConfig(BaseModel):
    setting: str = "default"

@dataclass
class MyServiceState:
    last_run_at: int = 0

    def to_dict(self) -> dict:
        return {"last_run_at": self.last_run_at}

    @classmethod
    def from_dict(cls, data: dict) -> "MyServiceState":
        return cls(last_run_at=data.get("last_run_at", 0))

class MyService(BaseService[MyServiceState]):
    SERVICE_NAME = SERVICE_NAME
    CONFIG_CLASS = MyServiceConfig

    def __init__(self, brotr: Brotr, config: Optional[MyServiceConfig] = None):
        super().__init__(brotr=brotr, config=config)
        self._config = config or MyServiceConfig()

    def _create_default_state(self) -> MyServiceState:
        return MyServiceState()

    def _state_from_dict(self, data: dict) -> MyServiceState:
        return MyServiceState.from_dict(data)

    async def health_check(self) -> bool:
        return self._pool.is_connected

    async def run(self) -> Outcome:
        # Implementation
        return Outcome(success=True, message="Done")
```

---

### 4. Logger (`src/core/logger.py`)

**Purpose**: Structured JSON logging system for all BigBrotr services.

**Features**:
- JSON-formatted structured logging
- Contextual fields (service_name, component, timestamp, level)
- Configurable log levels
- Console and file output support
- Thread-safe logging

**API**:
```python
from core.logger import get_logger, configure_logging

# Configure once at startup
configure_logging(level="INFO")

# Get logger for a service
logger = get_logger("finder", component="Finder")

# Log with structured fields
logger.info("run_completed", relays_found=100, duration_s=5.2)
logger.error("connection_failed", error=str(e))
```

---

### 5. Utils (`src/core/utils.py`)

**Purpose**: Shared utility functions used by services.

**Functions**:
- `build_relay_records(urls, timestamp)`: Build relay records from URLs
- `load_service_state(pool, service_name, timeout)`: Load state from database

---

## Service Layer

### Overview

The service layer (`src/services/`) contains all business logic for BigBrotr.

**Status**: 29% complete (2/7 services implemented)

| Service | LOC | Status |
|---------|-----|--------|
| **Initializer** | ~493 | Production Ready |
| **Finder** | ~492 | Production Ready |
| Monitor | 14 | Pending |
| Synchronizer | 14 | Pending |
| Priority Synchronizer | 14 | Pending |
| API | 14 | Pending (Phase 3) |
| DVM | 14 | Pending (Phase 3) |

---

### 1. Initializer Service (`src/services/initializer.py`)

**Purpose**: Database bootstrap and schema verification.

**Features**:
- PostgreSQL extension verification (pgcrypto, btree_gin)
- Table existence verification
- Stored procedure verification
- Seed data loading from text files
- Batch insertion with configurable batch size
- Retry logic with exponential backoff
- State persistence

**Configuration** (`yaml/services/initializer.yaml`):
```yaml
verification:
  tables: true
  procedures: true
  extensions: true

expected_schema:
  extensions:
    - pgcrypto
    - btree_gin
  tables:
    - relays
    - events
    - events_relays
    - nip11
    - nip66
    - relay_metadata
    - service_state
  procedures:
    - insert_event
    - insert_relay
    - delete_orphan_events

seed:
  enabled: true
  path: data/seed_relays.txt
  batch_size: 100

retry:
  max_attempts: 3
  initial_delay: 1.0
  max_delay: 10.0
  exponential_backoff: true
```

**API**:
```python
from services.initializer import Initializer
from core.brotr import Brotr

brotr = Brotr.from_yaml("yaml/core/brotr.yaml")

async with brotr.pool:
    initializer = Initializer.from_yaml("yaml/services/initializer.yaml", brotr=brotr)
    result = await initializer.run()

    if result.success:
        print(f"Seeded {result.metrics['relays_seeded']} relays")
```

---

### 2. Finder Service (`src/services/finder.py`)

**Purpose**: Discover Nostr relay URLs from multiple sources.

**Features**:
- Database event scanning for relay URLs
- External API fetching (nostr.watch)
- Watermark-based batch processing
- Atomic commits for crash consistency
- State persistence via `service_state` table
- Configurable batch sizes and intervals

**Configuration** (`yaml/services/finder.yaml`):
```yaml
event_scan:
  enabled: true
  batch_size: 1000
  max_events_per_cycle: 100000

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

logging:
  log_progress: true
  log_level: INFO
  progress_interval: 5000

timeouts:
  db_query: 30.0

insert_batch_size: 100
discovery_interval: 3600.0
```

**API**:
```python
from services.finder import Finder
from core.brotr import Brotr

brotr = Brotr.from_yaml("yaml/core/brotr.yaml")

async with brotr.pool:
    finder = Finder.from_yaml("yaml/services/finder.yaml", brotr=brotr)

    # Single run
    result = await finder.run()
    print(f"Found {result.metrics['relays_found']} relays")

    # Continuous operation
    async with finder:
        await finder.run_forever(interval=3600)
```

**Atomic Batch Processing**:
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

---

### 3. Monitor Service (Pending)

**Purpose**: Monitor relay health and collect metadata.

**Planned Features**:
- NIP-11 relay information documents
- NIP-66 relay monitoring data
- Connection health checks
- Uptime tracking

---

### 4. Synchronizer Service (Pending)

**Purpose**: Synchronize events from Nostr relays.

**Planned Features**:
- Connect to relays via WebSocket
- Subscribe to event filters
- Store events in database
- Handle reconnections and errors

---

## Database Schema

### Overview

PostgreSQL schemas are located in `implementations/bigbrotr/postgres/init/` and must be applied in numerical order.

**Schema Files** (apply in order):
1. `00_extensions.sql` - PostgreSQL extensions
2. `01_utility_functions.sql` - Helper functions
3. `02_tables.sql` - Table definitions
4. `03_indexes.sql` - Performance indexes
5. `04_integrity_functions.sql` - Data integrity checks
6. `05_procedures.sql` - Stored procedures
7. `06_views.sql` - Database views
8. `99_verify.sql` - Schema validation

### Core Tables

**relays**
```sql
CREATE TABLE relays (
    relay_url TEXT PRIMARY KEY,
    network TEXT NOT NULL,  -- 'clearnet' or 'tor'
    first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status TEXT NOT NULL DEFAULT 'unknown'
);
```

**events**
```sql
CREATE TABLE events (
    id SERIAL PRIMARY KEY,
    event_id BYTEA NOT NULL UNIQUE,  -- 32-byte event ID
    pubkey BYTEA NOT NULL,           -- 32-byte public key
    created_at BIGINT NOT NULL,
    kind INTEGER NOT NULL,
    tags JSONB NOT NULL DEFAULT '[]',
    content TEXT NOT NULL DEFAULT '',
    sig BYTEA NOT NULL
);
```

**service_state**
```sql
CREATE TABLE service_state (
    service_name TEXT PRIMARY KEY,
    state JSONB NOT NULL DEFAULT '{}',
    updated_at BIGINT NOT NULL
);
```

### Stored Procedures

- `insert_relay(url, network, inserted_at)`: Insert or update relay
- `insert_event(...)`: Insert event with deduplication
- `delete_orphan_events()`: Clean up orphaned events
- `delete_orphan_nip11()`: Clean up orphaned NIP-11 data
- `delete_orphan_nip66()`: Clean up orphaned NIP-66 data

---

## Configuration

### Configuration Philosophy

1. **YAML-Driven**: All configuration in YAML files
2. **Environment Variables**: Sensitive data (passwords) from environment
3. **Pydantic Validation**: All configs validated at startup
4. **CONFIG_CLASS**: Services use `CONFIG_CLASS` for automatic parsing

### Configuration Structure

```
implementations/bigbrotr/
├── yaml/
│   ├── core/
│   │   └── brotr.yaml          # Core configuration (Pool + Brotr)
│   └── services/
│       ├── initializer.yaml    # Initializer service config
│       ├── finder.yaml         # Finder service config
│       └── ...                 # Other service configs
├── .env                        # Environment variables (not in git)
└── .env.example                # Example environment variables
```

### Environment Variables

```bash
# .env (not in git)
DB_PASSWORD=your_secure_password
SOCKS5_PROXY_URL=socks5://127.0.0.1:9050  # Optional: Tor proxy
```

---

## Deployment

### Docker Compose

**File**: `implementations/bigbrotr/docker-compose.yaml`

```yaml
version: '3.8'

services:
  postgres:
    image: postgres:14
    environment:
      POSTGRES_DB: brotr
      POSTGRES_USER: admin
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./postgres/init:/docker-entrypoint-initdb.d
    ports:
      - "5432:5432"

  pgbouncer:
    image: pgbouncer/pgbouncer:latest
    environment:
      DATABASES_HOST: postgres
      DATABASES_PORT: 5432
      DATABASES_USER: admin
      DATABASES_PASSWORD: ${DB_PASSWORD}
      DATABASES_DBNAME: brotr
      PGBOUNCER_POOL_MODE: transaction
    ports:
      - "6432:6432"
    depends_on:
      - postgres

volumes:
  postgres_data:
```

### Deployment Steps

```bash
# 1. Set up environment
cp implementations/bigbrotr/.env.example implementations/bigbrotr/.env
nano implementations/bigbrotr/.env  # Set DB_PASSWORD

# 2. Start services
cd implementations/bigbrotr
docker-compose up -d

# 3. Run initialization
python -m services initializer

# 4. Run finder
python -m services finder
```

---

## Development Roadmap

### Phase 1: Core Infrastructure - COMPLETE

- Pool implementation (~410 lines)
- Brotr implementation (~413 lines)
- BaseService abstract class (~455 lines)
- Logger module (~331 lines)
- Utils module (~106 lines)

**Total Core Layer**: ~1,715 lines of production-ready code

### Phase 2: Service Layer - IN PROGRESS

**Completed**:
1. Initializer service (~493 lines)
2. Finder service (~492 lines)
3. pytest infrastructure (108 tests)

**Immediate Priority**:
- Monitor service
- Synchronizer service

**Medium Priority**:
- Priority Synchronizer
- Integration tests

### Phase 3: Public Access - PLANNED

- REST API service
- Data Vending Machine (DVM)
- Authentication and authorization
- Rate limiting

---

## Design Patterns

### Patterns Applied

| Pattern | Component | Purpose |
|---------|-----------|---------|
| **Dependency Injection** | Services receive Brotr | Testability, flexibility |
| **Composition over Inheritance** | Brotr HAS-A pool | Clear separation |
| **Abstract Base Class** | BaseService[StateT] | Consistent service interface |
| **Factory Method** | from_yaml(), from_dict() | Config-driven construction |
| **Template Method** | BaseService.run() | DRY for service lifecycle |
| **Context Manager** | Pool, Services | Resource management |

### Pattern Examples

**Dependency Injection**:
```python
# Services receive Brotr, not Pool
class Finder(BaseService[FinderState]):
    def __init__(self, brotr: Brotr, config: Optional[FinderConfig] = None):
        super().__init__(brotr=brotr, config=config)
        # Access pool via self._pool (convenience reference)
```

**CONFIG_CLASS for Automatic Parsing**:
```python
class Finder(BaseService[FinderState]):
    SERVICE_NAME = "finder"
    CONFIG_CLASS = FinderConfig  # Pydantic model

# Factory methods use CONFIG_CLASS automatically
finder = Finder.from_yaml("config.yaml", brotr=brotr)
finder = Finder.from_dict(data, brotr=brotr)
```

**Atomic Commits**:
```python
async with self._pool.transaction() as conn:
    # All operations in same transaction
    await conn.execute("INSERT INTO relays ...")
    await conn.execute("UPDATE service_state ...")

# Update in-memory state AFTER commit
self._state.last_seen_at = new_watermark
```

---

## Technology Stack

### Core Technologies

| Technology | Version | Purpose |
|------------|---------|---------|
| Python | 3.9+ | Programming language |
| PostgreSQL | 14+ | Database storage |
| asyncpg | 0.30.0 | Async PostgreSQL driver |
| Pydantic | 2.10.4 | Configuration validation |
| PyYAML | 6.0.2 | YAML parsing |
| aiohttp | 3.13.2 | Async HTTP client |
| nostr-tools | 1.4.0 | Nostr protocol library |

### Infrastructure

| Technology | Purpose |
|------------|---------|
| Docker | Containerization |
| Docker Compose | Service orchestration |
| PGBouncer | Connection pooling |
| Tor | Network privacy (optional) |

---

**End of Project Specification**

**Version**: 6.0
**Last Updated**: 2025-11-29
**Next Update**: After Monitor service implementation