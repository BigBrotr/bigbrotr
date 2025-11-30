# BigBrotr Project Specification v7.0

**Last Updated**: 2025-11-30
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

---

## Project Overview

### What is BigBrotr?

**BigBrotr** is a modular, production-grade Nostr data archiving and monitoring system built on Python and PostgreSQL. It provides comprehensive network monitoring, event synchronization, and relay discovery for the Nostr protocol ecosystem.

### Mission

Archive and monitor the Nostr protocol network, providing reliable data access for analysis, research, and applications.

### Key Features

- **Scalable Architecture**: Three-layer design (Core, Service, Implementation)
- **Production-Ready Core**: Enterprise-grade pooling, retry logic, lifecycle management
- **State Persistence**: Services automatically save/load state to database
- **Dependency Injection**: Clean, testable component composition
- **Flexible Deployment**: Docker Compose orchestration
- **Network Support**: Clearnet and Tor (SOCKS5 proxy)
- **Type Safety**: Full type hints and Pydantic validation

### Design Philosophy

1. **Separation of Concerns**: Core (reusable) -> Services (modular) -> Implementation (config-driven)
2. **Dependency Injection**: Services receive `Brotr` via constructor
3. **Configuration-Driven**: YAML configs, environment variables, zero hardcoded values
4. **Abstract Base Class**: All services inherit from `BaseService`
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
  - Logger: Structured logging

  Purpose: Reusable foundation, zero business logic
  Status: PRODUCTION READY
```

### Layer Responsibilities

| Layer | Responsibility | Status |
|-------|---------------|--------|
| **Implementation** | Configuration, deployment, data | Complete |
| **Service** | Business logic, orchestration | 2/7 Complete |
| **Core** | Infrastructure, utilities | Complete |

---

## Core Components

### Overview

The core layer (`src/core/`) is production-ready with four components.

| Component | Purpose |
|-----------|---------|
| Pool | PostgreSQL connection management with asyncpg |
| Brotr | Database interface with stored procedure wrappers |
| BaseService | Abstract base class with lifecycle and state persistence |
| Logger | Structured logging wrapper |

---

### 1. Pool (`src/core/pool.py`)

**Purpose**: Enterprise-grade PostgreSQL connection management using asyncpg.

**Features**:
- Async pooling with asyncpg
- Automatic retry logic with exponential backoff
- PGBouncer compatibility (transaction mode)
- Environment variable password loading (`DB_PASSWORD`)
- YAML/dict configuration support via factory methods
- Context manager support

**Configuration**:
```yaml
pool:
  database:
    host: localhost
    port: 5432
    database: bigbrotr
    user: admin

  limits:
    min_size: 5
    max_size: 20

  retry:
    max_attempts: 3
    initial_delay: 1.0
    max_delay: 10.0
```

**API**:
```python
from core import Pool

pool = Pool.from_yaml("yaml/core/brotr.yaml")

async with pool:
    result = await pool.fetch("SELECT * FROM relays LIMIT 10")
    await pool.execute("INSERT INTO relays ...")
```

---

### 2. Brotr (`src/core/brotr.py`)

**Purpose**: High-level database interface with stored procedure wrappers.

**Features**:
- Composition pattern: HAS-A pool (public property)
- Stored procedure wrappers (insert_event, insert_relay, etc.)
- Batch operations with configurable sizes
- YAML/dict configuration support

**API**:
```python
from core import Brotr

# From YAML (creates Pool internally)
brotr = Brotr.from_yaml("yaml/core/brotr.yaml")

# Usage
async with brotr.pool:
    await brotr.insert_relays(records)
    await brotr.cleanup_orphans()
```

---

### 3. BaseService (`src/core/base_service.py`)

**Purpose**: Abstract base class that all services inherit from. Provides consistent lifecycle, logging, and state persistence.

**Features**:
- `CONFIG_CLASS` attribute for automatic config parsing
- State persistence via `_load_state()` / `_save_state()`
- Continuous operation via `run_forever(interval)`
- Factory methods `from_yaml()` / `from_dict()`
- Context manager support (auto load/save state)
- Graceful shutdown via `request_shutdown()`

**API**:
```python
class BaseService(ABC):
    SERVICE_NAME: str                    # Unique identifier
    CONFIG_CLASS: type[BaseModel]        # For auto config parsing

    # Core attributes
    _brotr: Brotr                        # Database interface
    _config: BaseModel                   # Pydantic config
    _state: dict[str, Any]               # Persisted state (auto saved)
    _is_running: bool                    # Lifecycle flag

    # Abstract (must implement)
    async def run(self) -> None          # Single cycle logic

    # Provided methods
    async def run_forever(interval)      # Continuous operation loop
    async def health_check() -> bool     # Database connectivity
    def request_shutdown()               # Sync-safe shutdown trigger
    async def wait(timeout) -> bool      # Interruptible sleep
    async def _load_state()              # Load from service_state table
    async def _save_state()              # Save to service_state table
```

**Service Implementation Pattern**:
```python
from pydantic import BaseModel
from core.base_service import BaseService
from core.brotr import Brotr

SERVICE_NAME = "my_service"

class MyServiceConfig(BaseModel):
    setting: str = "default"

class MyService(BaseService):
    SERVICE_NAME = SERVICE_NAME
    CONFIG_CLASS = MyServiceConfig

    def __init__(self, brotr: Brotr, config: Optional[MyServiceConfig] = None):
        super().__init__(brotr=brotr, config=config or MyServiceConfig())
        self._config: MyServiceConfig

    async def run(self) -> None:
        # Single cycle logic
        self._state["last_run"] = int(time.time())
```

---

### 4. Logger (`src/core/logger.py`)

**Purpose**: Structured logging wrapper.

**API**:
```python
from core import Logger

logger = Logger("finder")
logger.info("run_completed", relays_found=100)
logger.error("connection_failed", error=str(e))
```

---

## Service Layer

### Overview

The service layer (`src/services/`) contains all business logic for BigBrotr.

**Status**: 29% complete (2/7 services implemented)

| Service | Status | Description |
|---------|--------|-------------|
| **Initializer** | Complete | Database bootstrap, schema verification |
| **Finder** | Complete | Relay discovery from APIs |
| Monitor | Pending | Relay health monitoring |
| Synchronizer | Pending | Event collection |
| Priority Synchronizer | Pending | Priority-based sync |
| API | Pending (Phase 3) | REST endpoints |
| DVM | Pending (Phase 3) | Data Vending Machine |

---

### 1. Initializer Service (`src/services/initializer.py`)

**Purpose**: Database bootstrap and schema verification.

**Features**:
- PostgreSQL extension verification (pgcrypto, btree_gin)
- Table existence verification
- Stored procedure verification
- Seed data loading from text files

**Configuration** (`yaml/services/initializer.yaml`):
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

**API**:
```python
from services import Initializer
from core import Brotr

brotr = Brotr.from_yaml("yaml/core/brotr.yaml")

async with brotr.pool:
    initializer = Initializer.from_yaml("yaml/services/initializer.yaml", brotr=brotr)
    await initializer.run()
```

---

### 2. Finder Service (`src/services/finder.py`)

**Purpose**: Discover Nostr relay URLs from external APIs.

**Features**:
- External API fetching (nostr.watch)
- Batch relay insertion
- Configurable discovery interval
- State persistence

**Configuration** (`yaml/services/finder.yaml`):
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

**API**:
```python
from services import Finder
from core import Brotr

brotr = Brotr.from_yaml("yaml/core/brotr.yaml")

async with brotr.pool:
    finder = Finder.from_yaml("yaml/services/finder.yaml", brotr=brotr)

    # Continuous operation
    async with finder:
        await finder.run_forever(interval=3600)
```

---

## Database Schema

### Overview

PostgreSQL schemas are located in `implementations/bigbrotr/postgres/init/` and must be applied in numerical order.

**Schema Files** (apply in order):
1. `00_extensions.sql` - PostgreSQL extensions (pgcrypto, btree_gin)
2. `01_utility_functions.sql` - Helper functions
3. `02_tables.sql` - Table definitions
4. `03_indexes.sql` - Performance indexes
5. `04_integrity_functions.sql` - Data integrity checks
6. `05_procedures.sql` - Stored procedures
7. `06_views.sql` - Database views
8. `99_verify.sql` - Schema validation

### Core Tables

| Table | Purpose |
|-------|---------|
| `relays` | Known relay URLs with network type |
| `events` | Nostr events (BYTEA IDs for efficiency) |
| `events_relays` | Event-relay junction with seen_at |
| `nip11` | Deduplicated NIP-11 info documents |
| `nip66` | Deduplicated NIP-66 test results |
| `relay_metadata` | Time-series metadata snapshots |
| `service_state` | Service state persistence (JSONB) |

### Stored Procedures

- `insert_relay(url, network, inserted_at)`: Insert relay with conflict handling
- `insert_event(...)`: Insert event with deduplication
- `insert_relay_metadata(...)`: Insert metadata with NIP-11/NIP-66 deduplication
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
│   │   └── brotr.yaml          # Pool + Brotr config
│   └── services/
│       ├── initializer.yaml
│       ├── finder.yaml
│       └── ...
├── .env                        # DB_PASSWORD (not in git)
└── .env.example
```

### Environment Variables

```bash
DB_PASSWORD=your_secure_password
```

---

## Deployment

### Docker Compose

**File**: `implementations/bigbrotr/docker-compose.yaml`

Includes:
- PostgreSQL 14
- PGBouncer (transaction mode)
- Health checks

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

- Pool implementation
- Brotr implementation
- BaseService abstract class
- Logger module

### Phase 2: Service Layer - IN PROGRESS

**Completed**:
1. Initializer service
2. Finder service
3. pytest infrastructure (90 tests)

**Immediate Priority**:
- Monitor service
- Synchronizer service

### Phase 3: Public Access - PLANNED

- REST API service
- Data Vending Machine (DVM)

---

## Technology Stack

| Technology | Version | Purpose |
|------------|---------|---------|
| Python | 3.9+ | Programming language |
| PostgreSQL | 14+ | Database storage |
| asyncpg | 0.30.0 | Async PostgreSQL driver |
| Pydantic | 2.10.4 | Configuration validation |
| PyYAML | 6.0.2 | YAML parsing |
| aiohttp | 3.13.2 | Async HTTP client |
| nostr-tools | 1.4.0 | Nostr protocol library |
| Docker | - | Containerization |
| PGBouncer | - | Connection pooling |

---

**End of Project Specification**

**Version**: 7.0
**Last Updated**: 2025-11-30
