# BigBrotr Project Specification v5.0

**Last Updated**: 2025-11-14
**Status**: Core Development Complete, Service Implementation Phase
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

**BigBrotr** is a modular, production-grade Nostr data archiving and monitoring system built on Python and PostgreSQL. It provides comprehensive network monitoring, event synchronization, and statistical analysis of the Nostr protocol ecosystem.

### Mission

Archive and monitor the entire Nostr protocol network, providing reliable data access for analysis, research, and applications.

### Key Features

- ✅ **Scalable Architecture**: Three-layer design (Core, Service, Implementation)
- ✅ **Production-Ready Core**: Enterprise-grade connection pooling, retry logic, lifecycle management
- ✅ **Dependency Injection**: Clean, testable component composition
- ✅ **Structured Logging**: JSON-formatted logs for all operations
- ✅ **Protocol-Based Design**: Flexible, non-invasive service wrapping
- ✅ **Comprehensive Monitoring**: Relay health checks (NIP-11, NIP-66)
- ✅ **Flexible Deployment**: Docker Compose orchestration
- ✅ **Network Support**: Clearnet and Tor (SOCKS5 proxy)
- ✅ **Type Safety**: Full type hints and Pydantic validation

### Design Philosophy

1. **Separation of Concerns**: Core (reusable) → Services (modular) → Implementation (config-driven)
2. **Dependency Injection**: Explicit dependencies, easy testing, flexible composition
3. **Configuration-Driven**: YAML configs, environment variables, zero hardcoded values
4. **Design Patterns First**: DI, Composition, Factory, Template Method, Wrapper/Decorator, Protocol
5. **Type Safety Everywhere**: Full type hints, Pydantic validation for all configs
6. **DRY Principle**: No code duplication via helper methods and wrappers
7. **Explicit Over Implicit**: `brotr.pool.fetch()` is clearer than `brotr.fetch()`

---

## Architecture

### Three-Layer Design

```
┌──────────────────────────────────────────────────────┐
│                 Implementation Layer                 │
│                                                      │
│  • YAML Configurations (core, services)            │
│  • PostgreSQL Schemas (tables, views, procedures)  │
│  • Deployment Specs (Docker Compose, env vars)     │
│  • Seed Data (relay lists, priority lists)         │
│                                                      │
│  Purpose: Define HOW this instance behaves         │
│  Location: implementations/bigbrotr/               │
└──────────────────────────────────────────────────────┘
                        ▲
                        │ Uses
                        │
┌──────────────────────────────────────────────────────┐
│                    Service Layer                     │
│                                                      │
│  • Initializer: Database bootstrap                 │
│  • Finder: Relay discovery                         │
│  • Monitor: Health checks (NIP-11, NIP-66)         │
│  • Synchronizer: Event collection                  │
│  • Priority Synchronizer: Priority relays          │
│  • API: REST endpoints (Phase 3)                   │
│  • DVM: Data Vending Machine (Phase 3)             │
│                                                      │
│  Purpose: Business logic, coordination             │
│  Location: src/services/ (PENDING)                │
└──────────────────────────────────────────────────────┘
                        ▲
                        │ Leverages
                        │
┌──────────────────────────────────────────────────────┐
│                     Core Layer ✅                    │
│                                                      │
│  • ConnectionPool: PostgreSQL connection mgmt      │
│  • Brotr: Database interface + stored procedures   │
│  • Service: Generic lifecycle wrapper              │
│  • Logger: Structured JSON logging                 │
│                                                      │
│  Purpose: Reusable foundation, zero business logic │
│  Location: src/core/ (PRODUCTION READY)           │
└──────────────────────────────────────────────────────┘
```

### Layer Responsibilities

| Layer | Responsibility | Examples | Status |
|-------|---------------|----------|--------|
| **Implementation** | Configuration, deployment, data | YAML files, SQL schemas, Docker Compose, seed data | ✅ Partial |
| **Service** | Business logic, orchestration | Finder, Monitor, Synchronizer, API, DVM | ⚠️ Pending |
| **Core** | Infrastructure, utilities | ConnectionPool, Brotr, Service, Logger | ✅ Complete |

### Design Principles

| Principle | Application | Benefit |
|-----------|-------------|---------|
| **Single Responsibility** | Pool = connections, Brotr = DB ops, Services = business logic | Clear boundaries, easier testing |
| **Dependency Injection** | Services receive dependencies vs creating them | Flexibility, testability, composition |
| **Composition over Inheritance** | Brotr HAS-A pool (public property), not IS-A pool | Clear API, no method conflicts |
| **Open/Closed** | Core closed for modification, open for extension via DI | Stability with flexibility |
| **DRY** | Helper methods, Service wrapper, factory methods | Less duplication, easier maintenance |
| **Explicit > Implicit** | `brotr.pool.fetch()` vs `brotr.fetch()` | Self-documenting code |
| **Protocol-Based** | DatabaseService, BackgroundService protocols | Non-invasive, flexible |

---

## Core Components

### Overview

The core layer (`src/core/`) is **100% complete** with four production-ready components totaling ~2,853 lines of code.

| Component | LOC | Status | Purpose |
|-----------|-----|--------|---------|
| ConnectionPool | ~632 | ✅ Production Ready | PostgreSQL connection management |
| Brotr | ~803 | ✅ Production Ready | Database interface with stored procedures |
| Service | ~1,021 | ✅ Production Ready | Generic lifecycle wrapper |
| Logger | ~397 | ✅ Production Ready | Structured JSON logging |

---

### 1. ConnectionPool (`src/core/pool.py`)

**Purpose**: Enterprise-grade PostgreSQL connection management using asyncpg.

**Lines of Code**: ~632

#### Features

- ✅ Async connection pooling with asyncpg
- ✅ Automatic retry logic with exponential backoff
- ✅ PGBouncer compatibility (transaction mode)
- ✅ Connection lifecycle management (acquire, release, close)
- ✅ Configurable pool sizes and timeouts
- ✅ Connection recycling (max queries per connection, max idle time)
- ✅ Environment variable password loading (DB_PASSWORD)
- ✅ YAML/dict configuration support via factory methods
- ✅ Type-safe Pydantic validation
- ✅ Context manager support for automatic cleanup
- ✅ Comprehensive documentation and type hints

#### Configuration

```yaml
# Loaded as part of Brotr configuration
# implementations/bigbrotr/yaml/core/brotr.yaml (pool section)
pool:
  database:
    host: localhost
    port: 5432
    database: brotr
    user: admin
    # password: loaded from DB_PASSWORD env var

  limits:
    min_size: 5                           # Minimum pool size
    max_size: 20                          # Maximum pool size
    max_queries: 50000                    # Queries before recycling
    max_inactive_connection_lifetime: 300.0  # Idle timeout (seconds)

  timeouts:
    acquisition: 10.0                     # Timeout for pool.acquire() (seconds)

  retry:
    max_attempts: 3                       # Connection retry attempts
    initial_delay: 1.0                    # Initial retry delay (seconds)
    max_delay: 10.0                       # Maximum retry delay (seconds)
    exponential_backoff: true             # Use exponential backoff

  server_settings:
    application_name: bigbrotr            # PostgreSQL application name
    timezone: UTC                         # Connection timezone
```

#### API

```python
from core.pool import ConnectionPool

# Direct instantiation
pool = ConnectionPool(
    host="localhost",
    port=5432,
    database="brotr",
    user="admin",
    min_size=5,
    max_size=20
)

# Context manager usage
async with pool:
    # Simple query
    events = await pool.fetch("SELECT * FROM events LIMIT 10")

    # Parameterized query
    await pool.execute(
        "INSERT INTO events (event_id, pubkey) VALUES ($1, $2)",
        event_id_bytes,
        pubkey_bytes
    )

    # Manual connection management
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("INSERT ...")
            await conn.execute("UPDATE ...")

# Check status
print(pool.is_connected)  # True/False
print(pool.config.limits.max_size)  # 20
```

#### Key Design Decisions

1. **Password Security**: Loaded from `DB_PASSWORD` environment variable, never in config files
2. **Exponential Backoff**: Prevents overwhelming database during connection issues
3. **Connection Recycling**: Prevents stale connections, respects PGBouncer limits
4. **Pydantic Validation**: Type-safe config with automatic validation and clear defaults
5. **Acquisition Timeout**: Separate from query timeouts (different concerns)

---

### 2. Brotr (`src/core/brotr.py`)

**Purpose**: High-level database interface with stored procedure wrappers and dependency injection.

**Lines of Code**: ~803

#### Features

- ✅ Dependency injection for ConnectionPool (or creates default)
- ✅ Stored procedure wrappers (insert_event, insert_relay, insert_relay_metadata)
- ✅ Batch operations with configurable sizes (up to 1000x performance boost)
- ✅ Cleanup operations (delete orphaned events, NIP-11, NIP-66 records)
- ✅ Hex to bytea conversion for efficient PostgreSQL storage
- ✅ Type-safe parameter handling with Pydantic
- ✅ YAML/dict configuration support via factory methods
- ✅ Helper methods eliminate code duplication
- ✅ Template Method pattern for delete operations
- ✅ Public pool property for clear separation of concerns
- ✅ Comprehensive documentation and type hints

#### Key Design Decisions

**Composition over Inheritance**: Brotr HAS-A pool (public property), not IS-A pool
- Clear separation: `brotr.pool.fetch()` vs `brotr.insert_event()`
- No method name conflicts
- Easy pool sharing across services
- Self-documenting API

**Dependency Injection**: Reduced `__init__` parameters from 28 to 12 (57% reduction)
- Pool injection instead of 16 ConnectionPool parameters
- Pool can be shared across multiple services
- Easy to mock for testing
- Cleaner API

**Helper Methods**: DRY principle applied
- `_validate_batch_size()`: Eliminates validation duplication
- `_call_delete_procedure()`: Template method for all delete operations
- ~50 lines of duplication eliminated

#### Configuration

```yaml
# implementations/bigbrotr/yaml/core/brotr.yaml
pool:
  # ConnectionPool configuration (see above)
  database: { host: localhost, database: brotr }
  limits: { min_size: 5, max_size: 20 }

batch:
  max_batch_size: 10000                  # Maximum batch size validation

procedures:
  # Stored procedure names (customizable per implementation)
  insert_event: insert_event
  insert_relay: insert_relay
  insert_relay_metadata: insert_relay_metadata
  delete_orphan_events: delete_orphan_events
  delete_orphan_nip11: delete_orphan_nip11
  delete_orphan_nip66: delete_orphan_nip66

timeouts:
  query: 60.0                            # Standard query timeout (seconds)
  procedure: 90.0                        # Stored procedure timeout (seconds)
  batch: 120.0                           # Batch operation timeout (seconds)
```

#### API

```python
from core.brotr import Brotr
from core.pool import ConnectionPool

# Option 1: From YAML (recommended)
brotr = Brotr.from_yaml("implementations/bigbrotr/yaml/core/brotr.yaml")

# Option 2: Inject custom pool (for pool sharing)
pool = ConnectionPool(host="localhost", database="brotr")
brotr = Brotr(pool=pool, max_batch_size=10000)

# Option 3: From dict (useful for testing)
config = {
    "pool": {"database": {"host": "localhost", "database": "brotr"}},
    "batch": {"max_batch_size": 10000}
}
brotr = Brotr.from_dict(config)

# Option 4: All defaults (creates default pool internally)
brotr = Brotr()

# Option 5: Pool sharing (multiple services, one pool)
shared_pool = ConnectionPool(host="localhost", database="brotr")
brotr1 = Brotr(pool=shared_pool)
brotr2 = Brotr(pool=shared_pool)  # Shares same pool!

# Usage
async with brotr.pool:
    # Insert single event
    await brotr.insert_event(
        event_id="abc123...",      # Hex string (auto-converted to bytea)
        pubkey="def456...",        # Hex string (auto-converted to bytea)
        created_at=1699876543,
        kind=1,
        tags=[["e", "..."], ["p", "..."]],
        content="Hello Nostr!",
        sig="789ghi...",
        relay_url="wss://relay.example.com",
        relay_network="clearnet",
        relay_inserted_at=1699876000,
        seen_at=1699876543
    )

    # Batch operations (executemany for 1000x performance)
    events = [
        {"event_id": "abc...", "pubkey": "def...", ...},
        {"event_id": "123...", "pubkey": "456...", ...},
        # ... more events
    ]
    await brotr.insert_events_batch(events, batch_size=100)

    # Cleanup orphaned records
    deleted = await brotr.cleanup_orphans()
    # Returns: {"events": 10, "nip11": 5, "nip66": 3}

    # Direct pool access when needed
    custom_result = await brotr.pool.fetch("SELECT * FROM custom_table")
```

#### Timeout Separation

**Pool Timeout** (acquisition): Getting a connection from the pool
**Brotr Timeouts** (operations): Query/procedure/batch execution

This separation allows independent tuning:
- Pool timeout: Infrastructure concern (10s default)
- Brotr timeouts: Business logic concern (60s/90s/120s defaults)

---

### 3. Service Wrapper (`src/core/service.py`)

**Purpose**: Generic wrapper for adding lifecycle management, logging, monitoring, and fault tolerance to ANY service.

**Lines of Code**: ~1,021

#### Why Service Wrapper?

Instead of adding logging, health checks, and statistics to each service individually, we created a **reusable generic wrapper** that works with ANY service implementing the protocol.

**Benefits**:
- ✅ **DRY**: Write lifecycle logic once, use everywhere
- ✅ **Separation of Concerns**: Services focus on business logic, wrapper handles cross-cutting concerns
- ✅ **Uniform Interface**: All services get `start()`, `stop()`, `health_check()`, `get_stats()`
- ✅ **Testability**: Service and wrapper testable independently
- ✅ **Extensibility**: Add features (circuit breaker, rate limiting) without touching services
- ✅ **Non-Invasive**: Services don't need to know about the wrapper (protocol-based)

#### Protocols

```python
from typing import Protocol

class DatabaseService(Protocol):
    """For database-style services (ConnectionPool, Brotr)."""
    async def connect(self) -> None: ...
    async def close(self) -> None: ...
    @property
    def is_connected(self) -> bool: ...

class BackgroundService(Protocol):
    """For background services (Finder, Monitor, Synchronizer)."""
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    @property
    def is_running(self) -> bool: ...
```

Any service implementing one of these protocols can be wrapped by the Service wrapper.

#### Features

- ✅ Automatic structured logging for all operations
- ✅ Health check functionality with configurable callbacks
- ✅ Circuit breaker pattern for fault tolerance
- ✅ Runtime statistics collection (uptime, health checks, etc.)
- ✅ Prometheus metrics export support
- ✅ Graceful startup and shutdown with warmup support
- ✅ Thread-safe statistics collection
- ✅ Context manager support
- ✅ Generic service wrapping (works with ANY protocol-implementing service)

#### Configuration

```python
from pydantic import BaseModel, Field

class ServiceConfig(BaseModel):
    """Service wrapper configuration."""

    # Logging
    enable_logging: bool = Field(default=True)
    log_level: str = Field(default="INFO")

    # Health checks
    enable_health_checks: bool = Field(default=True)
    health_check_interval: float = Field(default=60.0)  # seconds
    health_check_timeout: float = Field(default=10.0)

    # Circuit breaker
    enable_circuit_breaker: bool = Field(default=False)
    failure_threshold: int = Field(default=5)
    recovery_timeout: float = Field(default=60.0)

    # Statistics
    enable_statistics: bool = Field(default=True)
    statistics_interval: float = Field(default=300.0)  # 5 minutes
```

#### API

```python
from core.service import Service, ServiceConfig
from core.pool import ConnectionPool

# Wrap ConnectionPool
pool = ConnectionPool(host="localhost", database="brotr")
config = ServiceConfig(
    enable_logging=True,
    enable_health_checks=True,
    health_check_interval=60.0
)
service = Service(pool, name="database_pool", config=config)

# Use with context manager
async with service:
    # Service automatically:
    # - Logs: "[database_pool] Starting service..."
    # - Calls: await pool.connect()
    # - Starts: Background health checks every 60s
    # - Collects: Runtime statistics

    # Access wrapped service
    result = await service.instance.fetch("SELECT * FROM events")

    # Manual health check
    is_healthy = await service.health_check()
    print(f"Healthy: {is_healthy}")

    # Get runtime statistics
    stats = service.get_stats()
    print(stats)
    # {
    #   "name": "database_pool",
    #   "uptime_seconds": 123.45,
    #   "health_checks": {
    #     "total": 5,
    #     "failed": 0,
    #     "success_rate": 100.0
    #   },
    #   "circuit_breaker": {
    #     "state": "closed",
    #     "failure_count": 0
    #   }
    # }

# Service automatically handles:
# - Logging: "[database_pool] Stopping service..."
# - Cleanup: await pool.close()
# - Statistics: Final stats logged
```

#### Design Pattern

**Decorator/Wrapper Pattern** with **Protocol-Based Duck Typing**

The wrapper uses protocols (DatabaseService, BackgroundService) instead of abstract base classes, making it non-invasive. Services don't need to inherit from anything or be aware of the wrapper.

---

### 4. Logger (`src/core/logger.py`)

**Purpose**: Structured JSON logging system for all BigBrotr services.

**Lines of Code**: ~397

#### Features

- ✅ JSON-formatted structured logging
- ✅ Contextual fields (service_name, service_type, timestamp, level)
- ✅ Request ID and trace ID support for distributed tracing
- ✅ Configurable log levels (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- ✅ Console and file output support
- ✅ Integration with Service wrapper (automatic)
- ✅ ISO 8601 or Unix timestamp formats
- ✅ Custom field support for domain-specific data
- ✅ Thread-safe logging

#### Configuration

```python
from core.logger import configure_logging

# Configure once at application startup
configure_logging(
    level="INFO",                    # Log level
    output_file="logs/bigbrotr.log", # File output (optional)
    format_type="json",              # "json" or "text"
    include_timestamp=True,
    datetime_format="iso"            # "iso" or "unix"
)
```

#### API

```python
from core.logger import get_service_logger

# Get logger for a service
logger = get_service_logger("database_pool", "ConnectionPool")

# Log with structured fields
logger.info("service_started", elapsed_seconds=1.23, config={"max_size": 20})

# Log with additional context
logger.error("connection_failed",
    error=str(e),
    retry_attempt=3,
    host="localhost",
    database="brotr"
)

# Log with request ID (for distributed tracing)
logger.info("processing_event",
    event_id="abc123...",
    request_id="req-456def",
    trace_id="trace-789ghi"
)
```

#### Output Format

```json
{
  "timestamp": "2025-11-14T15:30:00.123456",
  "level": "INFO",
  "message": "service_started",
  "service_name": "database_pool",
  "service_type": "ConnectionPool",
  "elapsed_seconds": 1.23,
  "config": {"max_size": 20}
}
```

#### Integration with Service Wrapper

The Service wrapper automatically uses the Logger when `enable_logging=True`:

```python
service = Service(
    pool,
    name="database_pool",
    config=ServiceConfig(enable_logging=True)
)

# Logs automatically generated:
# - service_starting
# - service_started
# - health_check_passed / health_check_failed
# - service_stopping
# - service_stopped
```

---

## Service Layer

### Overview

The service layer (`src/services/`) contains all business logic for BigBrotr. All services are currently **pending implementation** (empty placeholder files).

**Status**: 0% complete (0/7 services implemented)

Services will leverage the production-ready core layer via dependency injection.

---

### Service Implementation Pattern

All services will follow this pattern:

```python
from core.brotr import Brotr
from core.service import Service, ServiceConfig
from core.pool import ConnectionPool
from typing import Protocol

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
    config=ServiceConfig(enable_logging=True)
)

async with service:
    # Automatic logging, health checks, statistics
    pass
```

---

### 1. Initializer Service

**File**: `src/services/initializer.py`
**Status**: ⚠️ Pending
**Priority**: Critical (needed for testing all other services)
**Estimated Effort**: 3-4 days

#### Purpose

Bootstrap the BigBrotr database:
- Validate PostgreSQL schemas
- Seed initial data (relay lists, priority lists)
- Run database migrations
- Verify stored procedures exist

#### Dependencies

- ConnectionPool (for schema operations)
- Brotr (for data seeding)
- PostgreSQL 14+

#### Configuration

```yaml
# implementations/bigbrotr/yaml/services/initializer.yaml
database:
  verify_schema: true           # Verify schemas on startup
  run_migrations: true          # Run pending migrations
  seed_data: true               # Seed initial data

schema:
  extensions_file: postgres/init/00_extensions.sql
  tables_file: postgres/init/02_tables.sql
  procedures_file: postgres/init/05_procedures.sql
  # ... other schema files

seed_data:
  relays_file: data/seed_relays.txt
  priority_relays_file: data/priority_relays.txt
```

#### API

```python
from services.initializer import Initializer

initializer = Initializer.from_yaml("yaml/services/initializer.yaml")

async with initializer:
    # Verify schemas
    schema_valid = await initializer.verify_schema()

    # Run migrations
    migrations_run = await initializer.run_migrations()

    # Seed data
    relays_seeded = await initializer.seed_relays()

    print(f"Database initialized: {schema_valid and migrations_run}")
```

---

### 2. Finder Service

**File**: `src/services/finder.py`
**Status**: ⚠️ Pending
**Priority**: High (first production service)
**Estimated Effort**: 4-5 days

#### Purpose

Discover Nostr relays from various sources:
- NIP-05 verification endpoints
- Well-known relay lists
- Relay discovery protocols
- Manual relay lists

#### Dependencies

- Brotr (for storing discovered relays)
- Service wrapper (for lifecycle management)
- aiohttp (for HTTP requests)
- aiohttp-socks (for Tor support)

#### Configuration

```yaml
# implementations/bigbrotr/yaml/services/finder.yaml
sources:
  - type: nip05
    enabled: true
    interval: 3600  # seconds

  - type: relay_list
    enabled: true
    url: https://api.nostr.watch/v1/public
    interval: 7200

  - type: manual
    enabled: true
    file: data/seed_relays.txt

discovery:
  concurrent_requests: 10
  request_timeout: 30.0
  retry_attempts: 3

storage:
  batch_size: 100
  deduplicate: true
```

#### API

```python
from services.finder import Finder

finder = Finder.from_yaml("yaml/services/finder.yaml")

async with finder:
    # Discover relays from all sources
    relays_found = await finder.discover_all()

    # Discover from specific source
    relays = await finder.discover_from_source("nip05")

    # Get statistics
    stats = finder.get_stats()
    print(f"Relays discovered: {stats['total_found']}")
```

---

### 3. Monitor Service

**File**: `src/services/monitor.py`
**Status**: ⚠️ Pending
**Priority**: High (core functionality)
**Estimated Effort**: 5-7 days

#### Purpose

Monitor relay health and collect metadata:
- NIP-11 relay information documents
- NIP-66 relay monitoring data
- Connection health checks
- Uptime tracking

#### Dependencies

- Brotr (for storing health data)
- Service wrapper (for lifecycle management)
- aiohttp (for HTTP requests)
- Periodic task scheduling

#### Configuration

```yaml
# implementations/bigbrotr/yaml/services/monitor.yaml
checks:
  nip11:
    enabled: true
    interval: 3600  # 1 hour
    timeout: 30.0

  nip66:
    enabled: true
    interval: 7200  # 2 hours
    timeout: 60.0

  connection:
    enabled: true
    interval: 300   # 5 minutes
    timeout: 10.0

monitoring:
  concurrent_checks: 20
  retry_attempts: 2
  failure_threshold: 3  # Mark as down after 3 failures

storage:
  batch_size: 50
  keep_history: true
  history_days: 30
```

#### API

```python
from services.monitor import Monitor

monitor = Monitor.from_yaml("yaml/services/monitor.yaml")

async with monitor:
    # Monitor all relays
    await monitor.check_all_relays()

    # Monitor specific relay
    health = await monitor.check_relay("wss://relay.example.com")

    # Get relay statistics
    stats = await monitor.get_relay_stats("wss://relay.example.com")
    print(f"Uptime: {stats['uptime_percentage']}%")
```

---

### 4. Synchronizer Service

**File**: `src/services/synchronizer.py`
**Status**: ⚠️ Pending
**Priority**: Medium (main functionality)
**Estimated Effort**: 7-10 days

#### Purpose

Synchronize events from Nostr relays:
- Connect to relays via WebSocket
- Subscribe to event filters
- Store events in database
- Handle reconnections and errors

#### Dependencies

- Brotr (for storing events)
- Service wrapper (for lifecycle management)
- nostr-tools Client (for Nostr protocol)
- WebSocket management

#### Configuration

```yaml
# implementations/bigbrotr/yaml/services/synchronizer.yaml
relays:
  max_concurrent: 50
  reconnect_delay: 5.0
  max_reconnect_attempts: 10

filters:
  - kinds: [0, 1, 3, 5, 6, 7]  # Basic event kinds
    limit: 1000
  - kinds: [10002]              # Relay lists
    limit: 100

synchronization:
  batch_size: 100
  checkpoint_interval: 60  # seconds
  deduplicate: true

storage:
  use_batch_insert: true
  batch_size: 200
```

#### API

```python
from services.synchronizer import Synchronizer

sync = Synchronizer.from_yaml("yaml/services/synchronizer.yaml")

async with sync:
    # Sync from all relays
    await sync.sync_all()

    # Sync from specific relay
    events = await sync.sync_relay("wss://relay.example.com")

    # Get sync statistics
    stats = sync.get_stats()
    print(f"Events synced: {stats['events_synced']}")
```

---

### 5. Priority Synchronizer Service

**File**: `src/services/priority_synchronizer.py`
**Status**: ⚠️ Pending
**Priority**: Medium
**Estimated Effort**: 5-7 days

#### Purpose

Priority-based event synchronization from important relays:
- Maintains priority queue of relays
- Allocates more resources to priority relays
- Ensures critical relays are always synced

#### Dependencies

- Synchronizer (base implementation)
- Priority queue logic
- Brotr (for data storage)

#### Configuration

```yaml
# implementations/bigbrotr/yaml/services/priority_synchronizer.yaml
priorities:
  high:
    - wss://relay.damus.io
    - wss://relay.nostr.band
    concurrent_connections: 10
    sync_interval: 60  # seconds

  medium:
    concurrent_connections: 20
    sync_interval: 300

  low:
    concurrent_connections: 50
    sync_interval: 3600

priority_file: data/priority_relays.txt
```

---

### 6. API Service (Phase 3)

**File**: `src/services/api.py`
**Status**: ⚠️ Pending (Phase 3)
**Priority**: Low
**Estimated Effort**: 10-14 days

#### Purpose

REST API for querying archived Nostr data:
- Query events by various filters
- Relay statistics and health
- Event counts and analytics
- Authentication and rate limiting

#### Dependencies

- Brotr (for data access)
- FastAPI (web framework)
- Authentication system
- Rate limiting

---

### 7. DVM Service (Phase 3)

**File**: `src/services/dvm.py`
**Status**: ⚠️ Pending (Phase 3)
**Priority**: Low
**Estimated Effort**: 7-10 days

#### Purpose

Data Vending Machine (Nostr-native API):
- Respond to Nostr data requests
- Provide archived data via Nostr events
- NIP-89/NIP-90 implementation

#### Dependencies

- Brotr (for data access)
- nostr-tools (for Nostr protocol)
- Service wrapper

---

## Database Schema

### Overview

PostgreSQL schemas are located in `implementations/bigbrotr/postgres/init/` and must be applied in numerical order.

**Schema Version**: 1.0.0
**PostgreSQL Version**: 14+
**Total Files**: 7 schema files + 1 verification file

### Schema Files (Apply in Order)

1. `00_extensions.sql` - PostgreSQL extensions (pgcrypto, etc.)
2. `01_utility_functions.sql` - Helper functions for conversions
3. `02_tables.sql` - Table definitions (events, relays, metadata)
4. `03_indexes.sql` - Performance indexes
5. `04_integrity_functions.sql` - Data integrity checks and triggers
6. `05_procedures.sql` - Stored procedures (called by Brotr)
7. `06_views.sql` - Database views for common queries
8. `99_verify.sql` - Schema validation queries

### Core Tables

#### `events`
Stores Nostr events (kinds 0-40000+).

```sql
CREATE TABLE events (
    event_id BYTEA PRIMARY KEY,           -- 32-byte event ID
    pubkey BYTEA NOT NULL,                -- 32-byte public key
    created_at BIGINT NOT NULL,           -- Unix timestamp
    kind INTEGER NOT NULL,                -- Event kind (NIP-01)
    tags JSONB NOT NULL DEFAULT '[]',     -- Event tags
    content TEXT NOT NULL DEFAULT '',     -- Event content
    sig BYTEA NOT NULL,                   -- 64-byte signature
    relay_url TEXT NOT NULL,              -- Source relay
    relay_network TEXT NOT NULL,          -- 'clearnet' or 'tor'
    relay_inserted_at BIGINT NOT NULL,    -- Relay timestamp
    seen_at BIGINT NOT NULL,              -- Our timestamp
    created_at_ts TIMESTAMPTZ,            -- Derived timestamp
    seen_at_ts TIMESTAMPTZ                -- Derived timestamp
);

CREATE INDEX idx_events_pubkey ON events(pubkey);
CREATE INDEX idx_events_kind ON events(kind);
CREATE INDEX idx_events_created_at ON events(created_at DESC);
```

#### `relays`
Stores known Nostr relays.

```sql
CREATE TABLE relays (
    relay_url TEXT PRIMARY KEY,           -- WebSocket URL
    network TEXT NOT NULL,                -- 'clearnet' or 'tor'
    first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status TEXT NOT NULL DEFAULT 'unknown', -- 'online', 'offline', 'unknown'
    failure_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_relays_network ON relays(network);
CREATE INDEX idx_relays_status ON relays(status);
```

#### `relay_metadata_nip11`
Stores NIP-11 relay information documents.

```sql
CREATE TABLE relay_metadata_nip11 (
    relay_url TEXT NOT NULL REFERENCES relays(relay_url) ON DELETE CASCADE,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    name TEXT,
    description TEXT,
    pubkey BYTEA,
    contact TEXT,
    supported_nips INTEGER[],
    software TEXT,
    version TEXT,
    limitation JSONB,
    retention JSONB,
    relay_countries TEXT[],
    language_tags TEXT[],
    tags TEXT[],
    posting_policy TEXT,
    payments_url TEXT,
    fees JSONB,
    icon TEXT,
    PRIMARY KEY (relay_url, fetched_at)
);
```

#### `relay_metadata_nip66`
Stores NIP-66 relay monitoring data.

```sql
CREATE TABLE relay_metadata_nip66 (
    relay_url TEXT NOT NULL REFERENCES relays(relay_url) ON DELETE CASCADE,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    network TEXT,
    last_check TIMESTAMPTZ,
    uptime_percentage NUMERIC(5,2),
    response_time_ms INTEGER,
    geo_country_code TEXT,
    geo_city TEXT,
    PRIMARY KEY (relay_url, fetched_at)
);
```

### Stored Procedures

Called by Brotr for data operations:

#### `insert_event`
```sql
CREATE OR REPLACE FUNCTION insert_event(
    p_event_id BYTEA,
    p_pubkey BYTEA,
    p_created_at BIGINT,
    p_kind INTEGER,
    p_tags JSONB,
    p_content TEXT,
    p_sig BYTEA,
    p_relay_url TEXT,
    p_relay_network TEXT,
    p_relay_inserted_at BIGINT,
    p_seen_at BIGINT
) RETURNS VOID AS $$
BEGIN
    INSERT INTO events (...)
    VALUES (...)
    ON CONFLICT (event_id) DO NOTHING;
END;
$$ LANGUAGE plpgsql;
```

#### `insert_relay`
```sql
CREATE OR REPLACE FUNCTION insert_relay(
    p_relay_url TEXT,
    p_network TEXT
) RETURNS VOID AS $$
BEGIN
    INSERT INTO relays (relay_url, network)
    VALUES (p_relay_url, p_network)
    ON CONFLICT (relay_url) DO UPDATE
    SET last_seen = NOW();
END;
$$ LANGUAGE plpgsql;
```

#### `delete_orphan_events`, `delete_orphan_nip11`, `delete_orphan_nip66`
Cleanup procedures for orphaned records.

---

## Configuration

### Configuration Philosophy

1. **YAML-Driven**: All configuration in YAML files, no hardcoded values
2. **Environment Variables**: Sensitive data (passwords) from environment
3. **Layered**: Core configs → Service configs → Implementation configs
4. **Validated**: Pydantic validation catches errors at startup
5. **Self-Documenting**: Field descriptions in Pydantic models

### Configuration Structure

```
implementations/bigbrotr/
├── yaml/
│   ├── core/
│   │   └── brotr.yaml          # Core configuration (Pool + Brotr)
│   └── services/
│       ├── initializer.yaml    # Initializer service config
│       ├── finder.yaml         # Finder service config
│       ├── monitor.yaml        # Monitor service config
│       ├── synchronizer.yaml   # Synchronizer service config
│       ├── priority_synchronizer.yaml
│       ├── api.yaml           # API service config (Phase 3)
│       └── dvm.yaml           # DVM service config (Phase 3)
├── .env                       # Environment variables (not in git)
└── .env.example               # Example environment variables
```

### Environment Variables

```bash
# .env (not in git)
DB_PASSWORD=your_secure_password_here
SOCKS5_PROXY_URL=socks5://127.0.0.1:9050  # Optional: Tor proxy
```

### Core Configuration Example

Complete example: `implementations/bigbrotr/yaml/core/brotr.yaml`

```yaml
# ConnectionPool + Brotr unified configuration
pool:
  database:
    host: localhost
    port: 5432
    database: brotr
    user: admin
    # password: loaded from DB_PASSWORD env var

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

batch:
  max_batch_size: 10000

procedures:
  insert_event: insert_event
  insert_relay: insert_relay
  insert_relay_metadata: insert_relay_metadata
  delete_orphan_events: delete_orphan_events
  delete_orphan_nip11: delete_orphan_nip11
  delete_orphan_nip66: delete_orphan_nip66

timeouts:
  query: 60.0
  procedure: 90.0
  batch: 120.0
```

---

## Deployment

### Docker Compose Deployment

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
      - ./postgres/postgresql.conf:/etc/postgresql/postgresql.conf
    ports:
      - "5432:5432"
    command: postgres -c config_file=/etc/postgresql/postgresql.conf

  pgbouncer:
    image: pgbouncer/pgbouncer:latest
    environment:
      DATABASES_HOST: postgres
      DATABASES_PORT: 5432
      DATABASES_USER: admin
      DATABASES_PASSWORD: ${DB_PASSWORD}
      DATABASES_DBNAME: brotr
      PGBOUNCER_POOL_MODE: transaction
      PGBOUNCER_MAX_CLIENT_CONN: 1000
      PGBOUNCER_DEFAULT_POOL_SIZE: 20
    ports:
      - "6432:6432"
    depends_on:
      - postgres

  tor:
    image: osminogin/tor-simple:latest
    ports:
      - "9050:9050"

volumes:
  postgres_data:
```

### Deployment Steps

```bash
# 1. Clone repository
git clone https://github.com/yourusername/bigbrotr.git
cd bigbrotr

# 2. Set up environment
cp implementations/bigbrotr/.env.example implementations/bigbrotr/.env
nano implementations/bigbrotr/.env  # Set DB_PASSWORD

# 3. Start services
cd implementations/bigbrotr
docker-compose up -d

# 4. Verify database
docker-compose exec postgres psql -U admin -d brotr -c "\dt"

# 5. Run initialization (when Initializer service is implemented)
python3 -m services.initializer
```

### Manual Deployment

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set up PostgreSQL
createdb brotr
psql -d brotr -f implementations/bigbrotr/postgres/init/00_extensions.sql
psql -d brotr -f implementations/bigbrotr/postgres/init/01_utility_functions.sql
# ... continue with other schema files

# 3. Set environment variables
export DB_PASSWORD="your_password"
export SOCKS5_PROXY_URL="socks5://127.0.0.1:9050"  # Optional

# 4. Run services (when implemented)
python3 -m services.initializer
python3 -m services.finder
python3 -m services.monitor
python3 -m services.synchronizer
```

---

## Development Roadmap

### Phase 1: Core Infrastructure ✅ COMPLETE

**Timeline**: Completed 2025-11-14
**Completion**: 100%

- ✅ ConnectionPool implementation (~632 lines)
- ✅ Brotr implementation with dependency injection (~803 lines)
- ✅ Service wrapper implementation (~1,021 lines)
- ✅ Logger module implementation (~397 lines)
- ✅ Helper methods and DRY improvements
- ✅ Comprehensive documentation

**Total Core Layer**: 2,853 lines of production-ready code

### Phase 2: Service Layer (In Progress)

**Timeline**: 2025-11-14 to 2026-Q1
**Completion**: 0%

**Immediate Priority** (November-December 2025):
1. ✅ Core layer complete
2. ⚠️ Implement Initializer service (3-4 days) - CRITICAL
3. ⚠️ Implement Finder service (4-5 days)
4. ⚠️ Implement Monitor service (5-7 days)
5. ⚠️ Set up pytest infrastructure (2-3 days) - Parallel track

**Medium Priority** (January-February 2026):
6. ⚠️ Implement Synchronizer service (7-10 days)
7. ⚠️ Implement Priority Synchronizer (5-7 days)
8. ⚠️ Add integration tests (2-3 days)
9. ⚠️ Performance optimization

**Phase 2 Completion Criteria**:
- All core services implemented and tested
- pytest coverage >80% for core, >70% for services
- Services running in production environment
- Basic monitoring and observability

### Phase 3: Public Access (Future)

**Timeline**: 2026-Q2 onwards
**Completion**: 0%

- ⚠️ REST API service (10-14 days)
- ⚠️ Data Vending Machine (DVM) (7-10 days)
- ⚠️ Authentication and authorization
- ⚠️ Rate limiting and quotas
- ⚠️ API documentation (Swagger/OpenAPI)
- ⚠️ Client libraries (Python, JavaScript)

**Phase 3 Completion Criteria**:
- Public API available and documented
- DVM service operational
- Authentication system secure and tested
- Rate limiting prevents abuse
- API documentation complete

### Phase 4: Production Hardening (Future)

**Timeline**: Ongoing
**Completion**: 0%

- ⚠️ Comprehensive test suite (>90% coverage)
- ⚠️ Performance optimization and profiling
- ⚠️ Monitoring and observability (Prometheus, Grafana)
- ⚠️ Security audit and hardening
- ⚠️ Deployment automation (CI/CD)
- ⚠️ Load balancing and horizontal scaling
- ⚠️ Disaster recovery and backups
- ⚠️ Documentation for operators

---

## Design Patterns

### Patterns Applied

| Pattern | Component | Purpose | Benefits |
|---------|-----------|---------|----------|
| **Dependency Injection** | Brotr ← ConnectionPool | Inject dependencies vs create | Testability, flexibility, pool sharing |
| **Composition over Inheritance** | Brotr HAS-A pool | Public pool property | Clear API, explicit separation |
| **Decorator/Wrapper** | Service wraps any service | Add cross-cutting concerns | DRY, uniform interface |
| **Factory Method** | `from_yaml()`, `from_dict()` | Config-driven construction | Environment flexibility |
| **Template Method** | `_call_delete_procedure()` | DRY for similar operations | Less duplication |
| **Context Manager** | Pool, Service | Resource management | Automatic cleanup |
| **Protocol/Duck Typing** | DatabaseService, BackgroundService | Flexible polymorphism | Non-invasive, extensible |
| **Single Responsibility** | Each component has one job | Separation of concerns | Easier to test and modify |

### Pattern Examples

#### Dependency Injection
```python
# Bad: Creating dependencies internally
class Brotr:
    def __init__(self, host, port, database, ...):  # 28 parameters!
        self.pool = ConnectionPool(host, port, ...)

# Good: Injecting dependencies
class Brotr:
    def __init__(self, pool: Optional[ConnectionPool] = None):  # 1 parameter
        self.pool = pool or ConnectionPool()
```

#### Composition over Inheritance
```python
# Bad: Inheritance creates unclear API
class Brotr(ConnectionPool):
    def fetch(...):  # Is this pool.fetch or brotr.fetch?
        pass

# Good: Composition creates clear API
class Brotr:
    def __init__(self, pool):
        self.pool = pool  # Public property

    # Clear: brotr.pool.fetch() vs brotr.insert_event()
```

#### Decorator/Wrapper
```python
# Wrap any service with lifecycle management
service = Service(
    ConnectionPool(...),  # Or Brotr, or Finder, or any service
    name="my_service",
    config=ServiceConfig(enable_logging=True)
)

# Automatic logging, health checks, statistics for ANY service
```

#### Factory Method
```python
# Multiple ways to construct, all type-safe
pool = ConnectionPool.from_yaml("config.yaml")
pool = ConnectionPool.from_dict({"database": {...}})
pool = ConnectionPool(host="localhost", database="brotr")
```

---

## Appendix: Technology Stack

### Core Technologies

| Technology | Version | Purpose |
|------------|---------|---------|
| Python | 3.9+ | Programming language |
| PostgreSQL | 14+ | Database storage |
| asyncpg | 0.30.0 | Async PostgreSQL driver |
| Pydantic | 2.10.4 | Configuration validation |
| PyYAML | 6.0.2 | YAML parsing |
| aiohttp | 3.13.2 | Async HTTP client |
| aiohttp-socks | 0.10.1 | SOCKS5 proxy support (Tor) |
| nostr-tools | 1.4.0 | Nostr protocol library |
| python-dotenv | 1.0.1 | Environment variable loading |
| aiofiles | 25.1.0 | Async file operations |
| typing-extensions | 4.12.2 | Type hints backports |

### Infrastructure

| Technology | Purpose |
|------------|---------|
| Docker | Containerization |
| Docker Compose | Service orchestration |
| PGBouncer | Connection pooling (between app and PostgreSQL) |
| Tor | Network privacy (optional SOCKS5 proxy) |

### Future Technologies (Phase 3)

| Technology | Purpose | Status |
|------------|---------|--------|
| FastAPI | REST API framework | Planned |
| pytest | Testing framework | Planned |
| prometheus-client | Metrics export | Planned |
| GitHub Actions | CI/CD pipeline | Planned |
| Grafana | Monitoring dashboards | Planned |

---

**End of Project Specification**

**Version**: 5.0
**Last Updated**: 2025-11-14
**Next Update**: After service implementation begins
