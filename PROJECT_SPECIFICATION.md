# BigBrotr Project Specification v4.0

**Last Updated**: 2025-11-13
**Status**: Core Development Phase
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

**BigBrotr** is a modular, production-grade Nostr data archiving and monitoring system built on Python and PostgreSQL. It provides comprehensive network monitoring, event synchronization, and statistical analysis of the Nostr protocol ecosystem.

### Key Features

- ✅ **Scalable Architecture**: Three-layer design (Core, Service, Implementation)
- ✅ **Production Ready**: Enterprise-grade connection pooling, retry logic, configuration management
- ✅ **Dependency Injection**: Clean, testable component composition
- ✅ **Nostr Protocol Support**: Full integration with nostr-tools library
- ✅ **Comprehensive Monitoring**: Relay health checks (NIP-11, NIP-66)
- ✅ **Flexible Deployment**: Docker Compose orchestration
- ✅ **Network Support**: Clearnet and Tor (SOCKS5 proxy)

### Design Philosophy

1. **Separation of Concerns**: Core (reusable) → Services (modular) → Implementation (config)
2. **Dependency Injection**: Explicit dependencies, easy testing, flexible composition
3. **Configuration-Driven**: YAML configs, environment variables, no hardcoded values
4. **Design Patterns**: DI, Composition, Factory, Template Method, Wrapper/Decorator
5. **Type Safety**: Full type hints, Pydantic validation
6. **No Backward Compatibility (Yet)**: Free to evolve architecture during development

---

## Architecture

### Three-Layer Design

```
┌──────────────────────────────────────────────────────┐
│                 Implementation Layer                 │
│                                                      │
│  • YAML Configurations (pool, brotr, services)     │
│  • PostgreSQL Schemas (tables, views, procedures)  │
│  • Deployment Specs (Docker Compose, env vars)     │
│  • Seed Data (relay lists, priority lists)         │
│                                                      │
│  Purpose: Define HOW this instance behaves         │
└──────────────────────────────────────────────────────┘
                        ▲
                        │ Uses
                        │
┌──────────────────────────────────────────────────────┐
│                    Service Layer                     │
│                                                      │
│  • Finder: Relay discovery                         │
│  • Monitor: Health checks (NIP-11, NIP-66)         │
│  • Synchronizer: Event collection                  │
│  • Priority Synchronizer: Priority relays          │
│  • Initializer: Database bootstrap                 │
│  • API: REST endpoints (Phase 3)                   │
│  • DVM: Data Vending Machine (Phase 3)             │
│                                                      │
│  Purpose: Business logic, coordination             │
└──────────────────────────────────────────────────────┘
                        ▲
                        │ Leverages
                        │
┌──────────────────────────────────────────────────────┐
│                     Core Layer                       │
│                                                      │
│  • ConnectionPool: PostgreSQL connection mgmt      │
│  • Brotr: Database interface + stored procedures   │
│  • Service: Generic lifecycle wrapper              │
│  • Logger: Structured logging                      │
│  • Config: Configuration management                │
│  • Utils: Shared utilities                         │
│                                                      │
│  Purpose: Reusable foundation, zero business logic │
└──────────────────────────────────────────────────────┘
```

### Design Principles

| Principle | Application |
|-----------|-------------|
| **Single Responsibility** | Pool = connections, Brotr = DB ops, Services = business logic |
| **Dependency Injection** | Services receive dependencies (pool, brotr) vs creating them |
| **Composition over Inheritance** | Brotr HAS-A pool (public property), not IS-A pool |
| **Open/Closed** | Core is closed for modification, open for extension via DI |
| **DRY** | Helper methods, Service wrapper, factory methods |
| **Explicit is Better** | `brotr.pool.fetch()` vs `brotr.fetch()` - clear source |

---

## Core Components

### 1. ConnectionPool (`src/core/pool.py`)

**Purpose**: Enterprise-grade PostgreSQL connection management using asyncpg.

**Status**: ✅ Production Ready (~580 lines)

#### Features

- ✅ Async connection pooling (asyncpg)
- ✅ Automatic retry with exponential backoff
- ✅ PGBouncer compatibility (transaction mode)
- ✅ Connection recycling (max queries, max idle time)
- ✅ Configurable pool sizes and timeouts
- ✅ Environment variable password loading
- ✅ YAML/dict configuration support
- ✅ Type-safe Pydantic validation
- ✅ Context manager support
- ✅ Comprehensive docstrings

#### Configuration

```yaml
# implementations/bigbrotr/config/core/pool.yaml
database:
  host: localhost
  port: 5432
  database: brotr
  user: admin
  # password: loaded from DB_PASSWORD env var

limits:
  min_size: 5                           # Minimum pool size
  max_size: 20                          # Maximum pool size
  max_queries: 50000                    # Queries before connection recycling
  max_inactive_connection_lifetime: 300.0  # Seconds before idle connection closes

timeouts:
  acquisition: 10.0                     # Timeout for getting connection from pool

retry:
  max_attempts: 3                       # Connection retry attempts
  initial_delay: 1.0                    # Initial retry delay (seconds)
  max_delay: 10.0                       # Maximum retry delay (seconds)
  exponential_backoff: true             # Use exponential backoff

server_settings:
  application_name: bigbrotr            # PostgreSQL application name
  timezone: UTC                         # Connection timezone
```

#### API Examples

```python
from core.pool import ConnectionPool

# Create from YAML
pool = ConnectionPool.from_yaml("config/pool.yaml")

# Or from dict
config = {
    "database": {"host": "localhost", "database": "brotr"},
    "limits": {"min_size": 5, "max_size": 20}
}
pool = ConnectionPool.from_dict(config)

# Or direct instantiation
pool = ConnectionPool(
    host="localhost",
    database="brotr",
    user="admin",
    min_size=5,
    max_size=20
)

# Use with context manager
async with pool:
    # Simple query
    events = await pool.fetch("SELECT * FROM events LIMIT 10")

    # Parameterized query
    await pool.execute(
        "INSERT INTO events (event_id, pubkey) VALUES ($1, $2)",
        event_id_bytes,
        pubkey_bytes
    )

    # Transaction with manual connection
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("INSERT ...")
            await conn.execute("UPDATE ...")

# Access configuration
print(pool.config.limits.max_size)  # 20
print(pool.is_connected)  # True
```

#### Key Design Decisions

1. **Password Loading**: From environment variable (`DB_PASSWORD`) for security
2. **Retry Logic**: Exponential backoff prevents overwhelming database during issues
3. **Connection Recycling**: Prevents connection staleness, respects PGBouncer limits
4. **Pydantic Validation**: Type-safe config with clear defaults and constraints
5. **Acquisition Timeout**: Pool-level timeout separate from query timeouts

---

### 2. Brotr (`src/core/brotr.py`)

**Purpose**: High-level database interface with stored procedure wrappers and dependency injection.

**Status**: ✅ Production Ready (~775 lines)

#### Features

- ✅ **Dependency Injection**: Inject ConnectionPool or use default
- ✅ **Stored Procedure Wrappers**: insert_event, insert_relay, insert_relay_metadata
- ✅ **Batch Operations**: Configurable batch sizes with validation
- ✅ **Cleanup Operations**: Delete orphaned events, NIP-11, NIP-66 records
- ✅ **Helper Methods**: DRY via _validate_batch_size(), _call_delete_procedure()
- ✅ **Hex to Bytea**: Efficient storage conversion
- ✅ **Type Safety**: Full type hints, Pydantic validation
- ✅ **YAML/Dict Support**: Factory methods for configuration
- ✅ **Pool Sharing**: Multiple Brotr instances can share one pool

#### Configuration

```yaml
# implementations/bigbrotr/config/core/brotr.yaml
pool:
  # ConnectionPool configuration (optional - creates default if omitted)
  database:
    host: localhost
    database: brotr
  limits:
    min_size: 5
    max_size: 20

batch:
  default_batch_size: 100               # Default for batch operations
  max_batch_size: 1000                  # Maximum allowed batch size

procedures:
  insert_event: insert_event            # Stored procedure names
  insert_relay: insert_relay
  insert_relay_metadata: insert_relay_metadata
  delete_orphan_events: delete_orphan_events
  delete_orphan_nip11: delete_orphan_nip11
  delete_orphan_nip66: delete_orphan_nip66

timeouts:
  query: 60.0                           # Standard query timeout (seconds)
  procedure: 90.0                       # Stored procedure timeout (seconds)
  batch: 120.0                          # Batch operation timeout (seconds)
```

#### API Examples

```python
from core.brotr import Brotr
from core.pool import ConnectionPool

# Option 1: Use default pool
brotr = Brotr(default_batch_size=200)

# Option 2: Inject custom pool (Dependency Injection)
pool = ConnectionPool(host="localhost", database="brotr", min_size=10)
brotr = Brotr(pool=pool, default_batch_size=200)

# Option 3: From YAML (pool created internally)
brotr = Brotr.from_yaml("config/brotr.yaml")

# Option 4: From dict
config = {
    "pool": {"database": {"host": "localhost", "database": "brotr"}},
    "batch": {"default_batch_size": 200}
}
brotr = Brotr.from_dict(config)

# Option 5: Pool sharing (multiple services, one pool)
shared_pool = ConnectionPool(...)
brotr = Brotr(pool=shared_pool)
finder = Finder(pool=shared_pool)  # Same pool!

# Usage
async with brotr.pool:
    # Insert single event
    await brotr.insert_event(
        event_id="abc123...",          # 64-char hex
        pubkey="def456...",            # 64-char hex
        created_at=1699876543,
        kind=1,
        tags=[["e", "..."], ["p", "..."]],
        content="Hello Nostr!",
        sig="789ghi...",               # 128-char hex
        relay_url="wss://relay.example.com",
        relay_network="clearnet",
        relay_inserted_at=1699876000,
        seen_at=1699876543
    )

    # Batch insert events
    events = [
        {"event_id": "...", "pubkey": "...", ...},
        {"event_id": "...", "pubkey": "...", ...},
        # ... more events
    ]
    await brotr.insert_events_batch(events, batch_size=100)

    # Insert relay
    await brotr.insert_relay(
        url="wss://relay.example.com",
        network="clearnet",
        inserted_at=1699876000
    )

    # Insert relay metadata (NIP-11 + NIP-66)
    await brotr.insert_relay_metadata(
        relay_url="wss://relay.example.com",
        relay_network="clearnet",
        relay_inserted_at=1699876000,
        generated_at=1699876543,
        nip66_present=True,
        nip66_openable=True,
        nip66_rtt_open=150,
        nip11_present=True,
        nip11_name="Example Relay",
        nip11_supported_nips=[1, 2, 9, 11],
        # ... other NIP-11/NIP-66 fields
    )

    # Cleanup orphaned records
    deleted = await brotr.cleanup_orphans()
    print(deleted)  # {"events": 10, "nip11": 5, "nip66": 3}

    # Access pool directly for custom queries
    result = await brotr.pool.fetch("SELECT COUNT(*) FROM events")
```

#### Key Design Decisions

1. **Dependency Injection**: Pool as parameter (not 16 ConnectionPool params) - 57% reduction
2. **Public Pool Property**: `brotr.pool.fetch()` vs `brotr.insert_event()` - explicit API
3. **Helper Methods**: `_validate_batch_size()`, `_call_delete_procedure()` - DRY principle
4. **Timeout Separation**: Pool handles acquisition, Brotr handles operation timeouts
5. **Factory Methods**: `from_yaml()`, `from_dict()` for configuration-driven construction
6. **Hex to Bytea**: Automatic conversion for event IDs, pubkeys, signatures

---

### 3. Service Wrapper (`src/core/service.py`)

**Purpose**: Generic lifecycle management wrapper for any service (logging, health checks, statistics).

**Status**: ⚠️ Design Complete, Implementation Pending

#### Why Service Wrapper?

**Problem**: Should we add logging, health checks, and stats to Pool? Brotr? Every service?

**Solution**: Create a **reusable generic wrapper** that can wrap ANY service.

**Benefits**:
- ✅ Write once, use everywhere (DRY)
- ✅ Services stay focused on business logic
- ✅ Uniform interface for all services
- ✅ Easy to extend (circuit breaker, rate limiting, tracing)
- ✅ Separation of concerns

#### Protocol

```python
from typing import Protocol

class ManagedService(Protocol):
    """Interface for services that can be wrapped by Service."""

    async def connect(self) -> None:
        """Start/connect the service."""
        ...

    async def close(self) -> None:
        """Stop/disconnect the service."""
        ...

    @property
    def is_connected(self) -> bool:
        """Check if service is running/connected."""
        ...
```

#### Configuration

```python
from pydantic import BaseModel, Field

class ServiceConfig(BaseModel):
    """Service wrapper configuration."""

    enable_logging: bool = Field(default=True, description="Enable automatic logging")
    log_level: str = Field(default="INFO", description="Log level")
    enable_health_checks: bool = Field(default=True, description="Enable periodic health checks")
    health_check_interval: float = Field(default=60.0, ge=1.0, description="Health check interval (seconds)")
    enable_warmup: bool = Field(default=False, description="Enable warmup phase after start")
    enable_stats: bool = Field(default=True, description="Enable statistics collection")
```

#### Planned API

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
    # 1. Logs: "[database_pool] Starting service..."
    # 2. Calls: await pool.connect()
    # 3. Starts: Health check loop (every 60s)
    # 4. Tracks: Statistics (uptime, health check success rate)

    # Access wrapped instance
    result = await service.instance.fetch("SELECT * FROM events")

    # Manual health check
    is_healthy = await service.health_check()
    print(f"Healthy: {is_healthy}")

    # Get statistics
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
    #   "custom": {}
    # }

    # Update custom stats
    service.update_custom_stats("queries_executed", 1000)

# Service automatically:
# 1. Stops health checks
# 2. Logs: "[database_pool] Stopping service..."
# 3. Calls: await pool.close()
# 4. Updates: Final statistics
```

#### Wrapping Multiple Services

```python
# Create services
pool_service = Service(ConnectionPool(...), name="pool")
brotr_service = Service(Brotr(...), name="brotr")
finder_service = Service(Finder(...), name="finder")

services = [pool_service, brotr_service, finder_service]

# Start all in parallel
await asyncio.gather(*[s.start() for s in services])

# Health check all
health_checks = await asyncio.gather(*[s.health_check() for s in services])
all_healthy = all(health_checks)

# Get stats from all
stats = [s.get_stats() for s in services]

# Stop all
await asyncio.gather(*[s.stop() for s in services])
```

#### Key Design Decisions

1. **Generic/Reusable**: Works with ANY service implementing ManagedService protocol
2. **Decorator Pattern**: Wraps service without modifying it
3. **Separation of Concerns**: Services focus on logic, wrapper handles monitoring
4. **Protocol-Based**: Duck typing via Protocol (not inheritance)
5. **Configurable**: Enable/disable features per service
6. **Future-Proof**: Easy to add circuit breaker, rate limiting, tracing

---

### 4. Logger (`src/core/logger.py`)

**Purpose**: Structured logging for all components.

**Status**: ⚠️ Not Started

**Planned Features**:
- Structured logging (JSON format for production)
- Log levels per component
- Contextual information (service name, request ID)
- Integration with Service wrapper
- Optional metrics export

---

### 5. Config (`src/core/config.py`)

**Purpose**: Global configuration management.

**Status**: ⚠️ Not Started

**Planned Features**:
- Load implementation-specific config
- Environment variable overrides
- Config validation
- Secrets management
- Multi-environment support (dev, staging, prod)

---

## Service Layer

### Service Architecture

All services follow common patterns:

1. **Dependency Injection**: Receive pool/brotr via constructor
2. **Service Wrapper**: Wrapped by `Service` for lifecycle management
3. **Configuration**: YAML-based, implementation-specific
4. **Async/Await**: Full asyncio support
5. **Error Handling**: Graceful degradation, retry logic

### Planned Services

#### 1. Finder (`src/services/finder.py`)

**Purpose**: Discover Nostr relays from known sources.

**Status**: ⚠️ Pending

**Features**:
- Relay discovery from seed lists
- Crawling relay references from events
- Deduplication
- Network detection (clearnet/tor)
- Batch insertion to database

**Dependencies**: Brotr, nostr-tools

---

#### 2. Monitor (`src/services/monitor.py`)

**Purpose**: Monitor relay health (NIP-11, NIP-66 checks).

**Status**: ⚠️ Pending

**Features**:
- Periodic relay health checks
- NIP-11 metadata fetching
- NIP-66 connectivity tests (open, read, write RTT)
- Relay metadata updates
- Health status tracking

**Dependencies**: Brotr, nostr-tools, Service wrapper

---

#### 3. Synchronizer (`src/services/synchronizer.py`)

**Purpose**: Synchronize events from relays.

**Status**: ⚠️ Pending

**Features**:
- Event streaming from relays
- Batch event insertion
- Deduplication
- Filter-based synchronization
- Progress tracking

**Dependencies**: Brotr, nostr-tools

---

#### 4. Priority Synchronizer (`src/services/priority_synchronizer.py`)

**Purpose**: Priority-based event synchronization for critical relays.

**Status**: ⚠️ Pending

**Features**:
- Priority relay list
- Higher frequency checks
- Dedicated resources
- Guaranteed sync intervals

**Dependencies**: Brotr, nostr-tools

---

#### 5. Initializer (`src/services/initializer.py`)

**Purpose**: Bootstrap database and services.

**Status**: ⚠️ Pending

**Features**:
- Database schema validation
- Seed data loading (relay lists)
- Service startup orchestration
- Health checks on startup

**Dependencies**: ConnectionPool, Brotr

---

#### 6. API (`src/services/api.py`)

**Purpose**: REST API for querying data.

**Status**: ⚠️ Pending (Phase 3)

**Features**:
- FastAPI-based REST endpoints
- Query events, relays, statistics
- Rate limiting
- Authentication (future)
- OpenAPI documentation

**Dependencies**: Brotr, FastAPI

---

#### 7. DVM (`src/services/dvm.py`)

**Purpose**: Data Vending Machine (NIP-90) for Nostr-native queries.

**Status**: ⚠️ Pending (Phase 3)

**Features**:
- NIP-90 implementation
- Event-based queries
- Result publishing
- Payment integration (future)

**Dependencies**: Brotr, nostr-tools, FastAPI

---

## Database Schema

### Tables

#### 1. `events`

Core event storage with full Nostr event data.

```sql
CREATE TABLE events (
    event_id BYTEA PRIMARY KEY,
    pubkey BYTEA NOT NULL,
    created_at BIGINT NOT NULL,
    kind INTEGER NOT NULL,
    tags JSONB NOT NULL,
    content TEXT NOT NULL,
    sig BYTEA NOT NULL,
    inserted_at BIGINT NOT NULL
);

CREATE INDEX idx_events_pubkey ON events (pubkey);
CREATE INDEX idx_events_created_at ON events (created_at);
CREATE INDEX idx_events_kind ON events (kind);
```

#### 2. `relays`

Relay metadata and status.

```sql
CREATE TABLE relays (
    url TEXT PRIMARY KEY,
    network TEXT NOT NULL CHECK (network IN ('clearnet', 'tor')),
    inserted_at BIGINT NOT NULL,
    last_seen BIGINT,
    status TEXT
);
```

#### 3. `event_relay`

Many-to-many relationship between events and relays.

```sql
CREATE TABLE event_relay (
    event_id BYTEA NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    relay_url TEXT NOT NULL REFERENCES relays(url) ON DELETE CASCADE,
    seen_at BIGINT NOT NULL,
    PRIMARY KEY (event_id, relay_url)
);

CREATE INDEX idx_event_relay_relay_url ON event_relay (relay_url);
```

#### 4. `relay_metadata`

NIP-11 and NIP-66 metadata.

```sql
CREATE TABLE relay_metadata (
    relay_url TEXT NOT NULL REFERENCES relays(url) ON DELETE CASCADE,
    relay_network TEXT NOT NULL,
    relay_inserted_at BIGINT NOT NULL,
    generated_at BIGINT NOT NULL,

    -- NIP-66 fields
    nip66_present BOOLEAN NOT NULL DEFAULT FALSE,
    nip66_openable BOOLEAN,
    nip66_readable BOOLEAN,
    nip66_writable BOOLEAN,
    nip66_rtt_open INTEGER,
    nip66_rtt_read INTEGER,
    nip66_rtt_write INTEGER,

    -- NIP-11 fields
    nip11_present BOOLEAN NOT NULL DEFAULT FALSE,
    nip11_name TEXT,
    nip11_description TEXT,
    nip11_pubkey TEXT,
    nip11_contact TEXT,
    nip11_supported_nips JSONB,
    nip11_software TEXT,
    nip11_version TEXT,
    -- ... additional NIP-11 fields

    PRIMARY KEY (relay_url, relay_network, relay_inserted_at, generated_at)
);
```

### Stored Procedures

#### `insert_event()`

Insert event with relay association.

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
    -- Insert event (on conflict do nothing)
    INSERT INTO events (event_id, pubkey, created_at, kind, tags, content, sig, inserted_at)
    VALUES (p_event_id, p_pubkey, p_created_at, p_kind, p_tags, p_content, p_sig, p_seen_at)
    ON CONFLICT (event_id) DO NOTHING;

    -- Insert relay (on conflict update last_seen)
    INSERT INTO relays (url, network, inserted_at, last_seen)
    VALUES (p_relay_url, p_relay_network, p_relay_inserted_at, p_seen_at)
    ON CONFLICT (url) DO UPDATE SET last_seen = p_seen_at;

    -- Insert event-relay association
    INSERT INTO event_relay (event_id, relay_url, seen_at)
    VALUES (p_event_id, p_relay_url, p_seen_at)
    ON CONFLICT (event_id, relay_url) DO NOTHING;
END;
$$ LANGUAGE plpgsql;
```

#### `delete_orphan_events()`

Remove events without relay associations.

```sql
CREATE OR REPLACE FUNCTION delete_orphan_events() RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM events
    WHERE event_id NOT IN (SELECT DISTINCT event_id FROM event_relay);

    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;
```

---

## Configuration

### Configuration Hierarchy

```
implementations/bigbrotr/
└── config/
    ├── core/
    │   ├── pool.yaml          # ConnectionPool config
    │   └── brotr.yaml         # Brotr config (includes pool)
    ├── services/
    │   ├── finder.yaml        # Finder service config
    │   ├── monitor.yaml       # Monitor service config
    │   ├── synchronizer.yaml  # Synchronizer config
    │   └── ...
    ├── postgres/
    │   └── postgresql.conf    # PostgreSQL server config
    └── pgbouncer/
        └── pgbouncer.ini      # PGBouncer config
```

### Environment Variables

```bash
# Database credentials
DB_PASSWORD=your_secure_password

# Tor proxy (optional)
SOCKS5_PROXY_URL=socks5://127.0.0.1:9050

# Service configs
IMPLEMENTATION=bigbrotr
CONFIG_DIR=implementations/bigbrotr/config
```

---

## Deployment

### Docker Compose

```yaml
# implementations/bigbrotr/docker-compose.yaml
version: "3.8"

services:
  postgres:
    image: postgres:14
    environment:
      POSTGRES_DB: brotr
      POSTGRES_USER: admin
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
    volumes:
      - ./config/postgres/init:/docker-entrypoint-initdb.d
      - ./data/postgres:/var/lib/postgresql/data
    secrets:
      - db_password

  pgbouncer:
    image: pgbouncer/pgbouncer
    depends_on:
      - postgres
    volumes:
      - ./config/pgbouncer/pgbouncer.ini:/etc/pgbouncer/pgbouncer.ini

  initializer:
    build: ../../src/dockerfiles/initializer
    depends_on:
      - pgbouncer
    environment:
      CONFIG_DIR: /app/config
      DB_PASSWORD_FILE: /run/secrets/db_password
    volumes:
      - ./config:/app/config
    secrets:
      - db_password

  finder:
    build: ../../src/dockerfiles/finder
    depends_on:
      - initializer
    environment:
      CONFIG_DIR: /app/config
      DB_PASSWORD_FILE: /run/secrets/db_password
    volumes:
      - ./config:/app/config
    secrets:
      - db_password

  monitor:
    build: ../../src/dockerfiles/monitor
    depends_on:
      - initializer
    environment:
      CONFIG_DIR: /app/config
      DB_PASSWORD_FILE: /run/secrets/db_password
    volumes:
      - ./config:/app/config
    secrets:
      - db_password

secrets:
  db_password:
    file: ./.env.db_password
```

---

## Development Roadmap

### Phase 1: Core Infrastructure ✅ (60% Complete)

- ✅ ConnectionPool implementation
- ✅ Brotr implementation
- ✅ Dependency Injection refactoring
- ✅ Helper methods and DRY improvements
- ⚠️ Service wrapper implementation (design complete)
- ⚠️ Logger module
- ⚠️ Config module

### Phase 2: Service Layer (0% Complete)

- ⚠️ Initializer service
- ⚠️ Finder service
- ⚠️ Monitor service
- ⚠️ Synchronizer service
- ⚠️ Priority Synchronizer service

### Phase 3: Public Access (Not Started)

- ⚠️ REST API service
- ⚠️ DVM service
- ⚠️ Authentication
- ⚠️ Rate limiting

### Phase 4: Production Hardening (Not Started)

- ⚠️ Comprehensive test suite
- ⚠️ Performance optimization
- ⚠️ Monitoring and observability
- ⚠️ Documentation
- ⚠️ Deployment automation

---

## Technology Stack

### Core

- **Language**: Python 3.9+
- **Database**: PostgreSQL 14+
- **Connection Pooling**: asyncpg + PGBouncer
- **Validation**: Pydantic 2.x
- **Config Format**: YAML

### Libraries

- **asyncpg**: PostgreSQL async driver
- **pydantic**: Configuration validation
- **PyYAML**: YAML parsing
- **nostr-tools** (1.4.0): Nostr protocol library

### Future

- **FastAPI**: REST API framework (Phase 3)
- **pytest**: Testing framework
- **structlog**: Structured logging
- **prometheus-client**: Metrics

### Infrastructure

- **Docker**: Containerization
- **Docker Compose**: Orchestration
- **PostgreSQL**: Data storage
- **PGBouncer**: Connection pooling
- **Tor**: Network privacy (optional)

---

## Design Patterns Reference

| Pattern | Where | Why |
|---------|-------|-----|
| Dependency Injection | Brotr receives pool | Testability, flexibility, composition |
| Composition over Inheritance | Brotr HAS-A pool | Clear API, separation of concerns |
| Decorator/Wrapper | Service wraps services | Cross-cutting concerns, reusability |
| Factory Method | from_yaml(), from_dict() | Configuration-driven construction |
| Template Method | _call_delete_procedure() | DRY for similar operations |
| Context Manager | Pool, Service (future) | Resource management, cleanup |
| Protocol/Duck Typing | ManagedService | Flexible, non-invasive |
| Single Responsibility | Each class has one job | Maintainability, testability |

---

## Contributing

**Note**: This project is in early development. No public contributions accepted yet.

**Internal Guidelines**:
- Type hints required for all public APIs
- Docstrings for all classes and methods
- DRY principle - no code duplication
- Design patterns over quick hacks
- Tests for new features

---

## License

**TBD** - To be determined before public release.

---

**End of Specification**
