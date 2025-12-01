# Architecture

This document provides a comprehensive overview of BigBrotr's architecture, design patterns, and component interactions.

## Table of Contents

- [Overview](#overview)
- [Three-Layer Architecture](#three-layer-architecture)
- [Core Layer](#core-layer)
- [Service Layer](#service-layer)
- [Implementation Layer](#implementation-layer)
- [Design Patterns](#design-patterns)
- [Data Flow](#data-flow)
- [Concurrency Model](#concurrency-model)

---

## Overview

BigBrotr follows a three-layer architecture that separates concerns and enables maximum flexibility:

1. **Core Layer** - Reusable infrastructure components with zero business logic
2. **Service Layer** - Business logic and service orchestration
3. **Implementation Layer** - Deployment-specific configuration and customization

This design allows:
- Multiple deployments from the same codebase
- Easy testing through dependency injection
- Configuration-driven behavior without code changes
- Clear separation between infrastructure and business logic

---

## Three-Layer Architecture

```
+-----------------------------------------------------------------------------+
|                           IMPLEMENTATION LAYER                               |
|                                                                              |
|   implementations/                                                           |
|   ├── bigbrotr/        Full-featured (stores tags, content, Tor support)    |
|   └── lilbrotr/        Lightweight (no tags/content, clearnet only)         |
|                                                                              |
|   Each implementation contains:                                              |
|   ├── yaml/           Configuration files (YAML)                            |
|   ├── postgres/init/  SQL schema definitions                                |
|   ├── data/           Seed data and static resources                        |
|   ├── docker-compose.yaml  Container orchestration                          |
|   └── Dockerfile      Application container                                 |
|                                                                              |
|   Purpose: Define HOW this specific deployment behaves                       |
+----------------------------------+------------------------------------------+
                                   |
                                   | Uses
                                   v
+-----------------------------------------------------------------------------+
|                             SERVICE LAYER                                    |
|                                                                              |
|   src/services/                                                              |
|   ├── initializer.py   Database bootstrap and verification                  |
|   ├── finder.py        Relay URL discovery                                  |
|   ├── monitor.py       Relay health monitoring (NIP-11/NIP-66)              |
|   ├── synchronizer.py  Event collection and sync                            |
|   ├── api.py           REST API (planned)                                   |
|   └── dvm.py           Data Vending Machine (planned)                       |
|                                                                              |
|   Purpose: Business logic, service coordination, data transformation         |
+----------------------------------+------------------------------------------+
                                   |
                                   | Leverages
                                   v
+-----------------------------------------------------------------------------+
|                              CORE LAYER                                      |
|                                                                              |
|   src/core/                                                                  |
|   ├── pool.py          PostgreSQL connection pooling                        |
|   ├── brotr.py         Database interface + stored procedures               |
|   ├── base_service.py  Abstract service base class                          |
|   └── logger.py        Structured logging                                   |
|                                                                              |
|   Purpose: Reusable foundation, zero business logic                          |
+-----------------------------------------------------------------------------+
```

### Layer Responsibilities

| Layer | Responsibility | Changes When |
|-------|----------------|--------------|
| **Core** | Infrastructure, utilities, abstractions | Rarely - foundation is stable |
| **Service** | Business logic, orchestration | Feature additions, protocol updates |
| **Implementation** | Configuration, customization | Per-deployment or environment |

---

## Core Layer

The core layer (`src/core/`) provides reusable infrastructure components.

### Pool (`pool.py`)

**Purpose**: PostgreSQL connection pooling with asyncpg.

**Key Features**:
- Async connection pool management
- Configurable pool size limits
- Retry logic with exponential backoff
- PGBouncer compatibility (transaction mode)
- Environment variable password loading (`DB_PASSWORD`)
- Connection health checking
- Async context manager support

**Configuration Model**:
```python
class PoolConfig(BaseModel):
    database: DatabaseConfig      # host, port, database, user, password
    limits: PoolLimitsConfig      # min_size, max_size, max_queries
    timeouts: PoolTimeoutsConfig  # acquisition, health_check
    retry: RetryConfig            # max_attempts, delays, backoff
    server_settings: dict         # application_name, timezone
```

**Usage**:
```python
pool = Pool.from_yaml("yaml/core/brotr.yaml")

async with pool:
    result = await pool.fetch("SELECT * FROM relays LIMIT 10")

# Or manual lifecycle
await pool.connect()
try:
    result = await pool.fetchval("SELECT COUNT(*) FROM events")
finally:
    await pool.close()
```

### Brotr (`brotr.py`)

**Purpose**: High-level database interface with stored procedure wrappers.

**Key Features**:
- Composition pattern: HAS-A Pool (publicly accessible)
- Stored procedure wrappers for all database operations
- Batch operations with configurable size limits
- Automatic hex-to-BYTEA conversion for event IDs
- Timeout configuration per operation type
- Context manager (delegates to Pool)

**Stored Procedures** (hardcoded for security):
```python
PROC_INSERT_EVENT = "insert_event"
PROC_INSERT_RELAY = "insert_relay"
PROC_INSERT_RELAY_METADATA = "insert_relay_metadata"
PROC_DELETE_ORPHAN_EVENTS = "delete_orphan_events"
PROC_DELETE_ORPHAN_NIP11 = "delete_orphan_nip11"
PROC_DELETE_ORPHAN_NIP66 = "delete_orphan_nip66"
```

**Usage**:
```python
brotr = Brotr.from_yaml("yaml/core/brotr.yaml")

async with brotr:
    # Insert events
    count = await brotr.insert_events(events_list)

    # Insert relays
    count = await brotr.insert_relays(relays_list)

    # Insert metadata with deduplication
    count = await brotr.insert_relay_metadata(metadata_list)

    # Cleanup orphaned records
    result = await brotr.cleanup_orphans()
```

### BaseService (`base_service.py`)

**Purpose**: Abstract base class for all services.

**Key Features**:
- Generic type parameter for configuration class
- `SERVICE_NAME` and `CONFIG_CLASS` class attributes
- State persistence via `_load_state()` / `_save_state()`
- Continuous operation via `run_forever(interval)`
- Factory methods: `from_yaml()`, `from_dict()`
- Async context manager (auto load/save state)
- Graceful shutdown via `request_shutdown()`
- Interruptible wait via `wait(timeout)`

**Interface**:
```python
class BaseService(ABC, Generic[ConfigT]):
    SERVICE_NAME: str              # Unique identifier for state persistence
    CONFIG_CLASS: type[ConfigT]    # For automatic config parsing

    _brotr: Brotr                  # Database interface
    _config: ConfigT               # Pydantic configuration
    _state: dict[str, Any]         # Persisted state (JSONB in database)

    @abstractmethod
    async def run(self) -> None:
        """Single cycle logic - must be implemented by subclasses."""
        pass

    async def run_forever(self, interval: float) -> None:
        """Continuous loop with configurable interval."""
        pass

    async def health_check(self) -> bool:
        """Database connectivity check."""
        pass

    def request_shutdown(self) -> None:
        """Sync-safe shutdown trigger for signal handlers."""
        pass

    async def wait(self, timeout: float) -> bool:
        """Interruptible sleep - returns True if shutdown requested."""
        pass
```

**State Persistence**:
```python
async with brotr:
    async with service:  # _load_state() called on enter
        await service.run_forever(interval=3600)
    # _save_state() called on exit
```

### Logger (`logger.py`)

**Purpose**: Structured logging wrapper with key=value formatting.

**Usage**:
```python
logger = Logger("synchronizer")
logger.info("sync_completed", events=1500, duration=45.2, relay="wss://relay.example.com")
# Output: 2025-01-01 12:00:00 INFO synchronizer: sync_completed events=1500 duration=45.2 relay=wss://relay.example.com

logger.error("connection_failed", relay="wss://relay.example.com", error="timeout")
logger.debug("processing_event", event_id="abc123")
```

---

## Service Layer

The service layer (`src/services/`) contains business logic implementations.

### Service Architecture

All services follow the same pattern:

1. **Configuration Class** - Pydantic model with validation
2. **Service Class** - Inherits from `BaseService[ConfigClass]`
3. **`run()` Method** - Single cycle logic (abstract method implementation)
4. **Factory Methods** - `from_yaml()`, `from_dict()` inherited from base

```python
# Example service structure
SERVICE_NAME = "myservice"

class MyServiceConfig(BaseModel):
    interval: float = Field(default=300.0, ge=60.0)
    # ... other config fields

class MyService(BaseService[MyServiceConfig]):
    SERVICE_NAME = SERVICE_NAME
    CONFIG_CLASS = MyServiceConfig

    def __init__(self, brotr: Brotr, config: MyServiceConfig | None = None):
        super().__init__(brotr=brotr, config=config or MyServiceConfig())

    async def run(self) -> None:
        """Single cycle implementation."""
        # Business logic here
        pass
```

### Initializer Service

**Purpose**: Database bootstrap and schema verification.

**Lifecycle**: One-shot (runs once, then exits)

**Operations**:
1. Verify PostgreSQL extensions (pgcrypto, btree_gin)
2. Verify all expected tables exist
3. Verify all stored procedures exist
4. Verify all views exist
5. Seed relay URLs from configured file

### Finder Service

**Purpose**: Relay URL discovery.

**Lifecycle**: Continuous (`run_forever`)

**Operations**:
1. Fetch relay lists from configured API sources
2. Validate URLs using nostr-tools
3. Detect network type (clearnet/tor) from URL
4. Batch insert discovered relays into database

### Monitor Service

**Purpose**: Relay health and capability assessment.

**Lifecycle**: Continuous (`run_forever`)

**Operations**:
1. Fetch list of relays needing health check
2. For each relay (concurrently):
   - Fetch NIP-11 information document
   - Test NIP-66 capabilities (open, read, write)
   - Measure round-trip times
3. Batch insert results with NIP-11/NIP-66 deduplication

**Tor Support**:
- Configurable SOCKS5 proxy for .onion addresses
- Automatic network detection from URL
- Separate timeout settings for Tor relays

### Synchronizer Service

**Purpose**: Event collection from relays.

**Lifecycle**: Continuous (`run_forever`)

**Key Features**:
- **Multicore Processing**: Uses `aiomultiprocess` for parallel processing
- **Time-Window Stack**: Algorithm for handling large event volumes
- **Incremental Sync**: Per-relay timestamp tracking
- **Per-Relay Overrides**: Custom settings for specific relays
- **Graceful Shutdown**: Clean worker process termination via `atexit`

**Processing Flow**:
```
Main Process                    Worker Processes
     │                               │
     ├─── Fetch relays ────────────>│
     │                               │
     ├─── Distribute to workers ───>│ ─── Connect to relay
     │                               │ ─── Request events
     │                               │ ─── Apply time-window stack
     │<── Receive batches ──────────│ ─── Return raw events
     │                               │
     ├─── Insert to database        │
     │                               │
     └─── Update state             │
```

---

## Implementation Layer

The implementation layer contains deployment-specific resources. Two implementations are provided:

### Included Implementations

| Implementation | Purpose | Key Differences |
|----------------|---------|-----------------|
| **bigbrotr** | Full-featured archiving | Stores tags/content, Tor support, high concurrency |
| **lilbrotr** | Lightweight indexing | Indexes all events but omits tags/content (~60% disk savings), clearnet only |

### BigBrotr Structure (Full-Featured)

```
implementations/bigbrotr/
├── yaml/
│   ├── core/
│   │   └── brotr.yaml           # Database connection, pool settings
│   └── services/
│       ├── initializer.yaml     # Schema verification, seed file
│       ├── finder.yaml          # API sources, intervals
│       ├── monitor.yaml         # Health check settings, Tor enabled
│       └── synchronizer.yaml    # High concurrency (10 parallel, 10 processes)
├── postgres/
│   └── init/                    # SQL schema files (00-99)
│       ├── 02_tables.sql        # Full schema with tags, tagvalues, content
│       └── ...
├── data/
│   └── seed_relays.txt          # 8,865 initial relay URLs
├── pgbouncer/
│   └── pgbouncer.ini            # Connection pooler config
├── docker-compose.yaml          # Ports: 5432, 6432, 9050
├── Dockerfile
└── .env.example
```

### LilBrotr Structure (Lightweight)

```
implementations/lilbrotr/
├── yaml/
│   ├── core/
│   │   └── brotr.yaml           # Same pool settings
│   └── services/
│       ├── synchronizer.yaml    # Tor disabled, lower concurrency (5 parallel)
│       └── ...                  # Other services inherit defaults
├── postgres/
│   └── init/
│       ├── 02_tables.sql        # Minimal schema (NO tags, tagvalues, content)
│       └── ...
├── docker-compose.yaml          # Different ports: 5433, 6433, 9051
├── Dockerfile
└── .env.example
```

**LilBrotr Schema Differences**:
```sql
-- BigBrotr events table (full)
CREATE TABLE events (
    id BYTEA PRIMARY KEY,
    pubkey BYTEA NOT NULL,
    created_at BIGINT NOT NULL,
    kind INTEGER NOT NULL,
    tags JSONB NOT NULL,                    -- Stored
    tagvalues TEXT[] GENERATED ALWAYS AS (tags_to_tagvalues(tags)) STORED,  -- Indexed
    content TEXT NOT NULL,                  -- Stored
    sig BYTEA NOT NULL
);

-- LilBrotr events table (lightweight)
CREATE TABLE events (
    id BYTEA PRIMARY KEY,
    pubkey BYTEA NOT NULL,
    created_at BIGINT NOT NULL,
    kind INTEGER NOT NULL,
    -- tags NOT stored (saves ~40% disk space)
    -- content NOT stored (saves ~20% disk space)
    sig BYTEA NOT NULL
);
```

### Creating Custom Implementations

To create a custom deployment:

1. Copy an existing implementation:
   ```bash
   cp -r implementations/bigbrotr implementations/mydeployment
   ```

2. Modify YAML configurations as needed:
   ```yaml
   # yaml/services/synchronizer.yaml
   tor:
     enabled: false  # Disable Tor
   concurrency:
     max_parallel: 3  # Lower concurrency
   ```

3. Optionally customize SQL schemas:
   ```sql
   -- Store only specific event kinds
   ALTER TABLE events ADD CONSTRAINT events_kind_check
     CHECK (kind IN (0, 1, 3, 6, 7));
   ```

4. Update Docker Compose ports to avoid conflicts:
   ```yaml
   ports:
     - "5434:5432"  # Different port
   ```

5. Deploy:
   ```bash
   cd implementations/mydeployment
   docker-compose up -d
   ```

The core and service layers remain unchanged - only configuration differs.

---

## Design Patterns

### Dependency Injection

Services receive their dependencies via constructor:

```python
# Brotr is injected, not created internally
service = MyService(brotr=brotr, config=config)

# This enables testing with mocks
mock_brotr = MagicMock(spec=Brotr)
service = MyService(brotr=mock_brotr)
```

### Composition

`Brotr` HAS-A `Pool` (rather than IS-A):

```python
class Brotr:
    def __init__(self, pool: Pool | None = None, ...):
        self._pool = pool or Pool(...)

    @property
    def pool(self) -> Pool:
        return self._pool
```

Benefits:
- Pool is publicly accessible: `brotr.pool.fetch(...)`
- Brotr can be used without Pool features if needed
- Easy to inject mock Pool for testing

### Template Method

`BaseService.run_forever()` calls abstract `run()`:

```python
class BaseService:
    async def run_forever(self, interval: float) -> None:
        while not self._shutdown_requested:
            await self.run()  # Template method
            if await self.wait(interval):
                break

    @abstractmethod
    async def run(self) -> None:
        """Implemented by subclasses."""
        pass
```

### Factory Method

Services provide multiple construction paths:

```python
# From YAML file
service = MyService.from_yaml("config.yaml", brotr=brotr)

# From dictionary
service = MyService.from_dict(config_dict, brotr=brotr)

# Direct construction
service = MyService(brotr=brotr, config=MyServiceConfig(...))
```

### Context Manager

Resources are automatically managed:

```python
async with brotr:           # Connect on enter, close on exit
    async with service:     # Load state on enter, save on exit
        await service.run_forever(interval=3600)
```

---

## Data Flow

### Event Synchronization Flow

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Finder    │     │   Monitor   │     │ Synchronizer│
└──────┬──────┘     └──────┬──────┘     └──────┬──────┘
       │                   │                   │
       │ Discover          │ Check health      │ Collect events
       │ relay URLs        │ NIP-11/NIP-66     │ from relays
       v                   v                   v
┌─────────────────────────────────────────────────────┐
│                      PostgreSQL                      │
│  ┌─────────┐  ┌──────┐  ┌─────────────────┐         │
│  │ relays  │  │events│  │ relay_metadata  │         │
│  └─────────┘  └──────┘  └─────────────────┘         │
│       │           │              │                   │
│       └───────────┴──────────────┘                   │
│                events_relays                         │
└─────────────────────────────────────────────────────┘
```

### Metadata Deduplication Flow

```
┌──────────────────────────────────────────────────────────────┐
│                       Monitor Service                         │
│                                                               │
│   ┌─────────────┐     ┌─────────────┐     ┌──────────────┐   │
│   │ Fetch NIP-11│────>│Compute Hash │────>│Check if exists│  │
│   └─────────────┘     └─────────────┘     └──────────────┘   │
│                                                  │            │
│                                    ┌─────────────┴──────────┐│
│                                    │                        ││
│                                    v                        v│
│                           ┌──────────────┐         ┌────────┐│
│                           │Insert new rec│         │Reuse ID││
│                           └──────────────┘         └────────┘│
│                                    │                        ││
│                                    └─────────────┬──────────┘│
│                                                  │            │
│                                                  v            │
│                                    ┌─────────────────────────┐│
│                                    │ Insert relay_metadata   ││
│                                    │ (links relay to nip11/  ││
│                                    │  nip66 by hash ID)      ││
│                                    └─────────────────────────┘│
└──────────────────────────────────────────────────────────────┘
```

---

## Concurrency Model

### Async I/O

All I/O operations are async using:
- `asyncpg` for database operations
- `aiohttp` for HTTP requests
- `aiohttp-socks` for SOCKS5 proxy

### Connection Pooling

```
Application                PGBouncer              PostgreSQL
    │                          │                      │
    ├── asyncpg pool ─────────>├── connection pool ──>│
    │   (20 connections)       │   (25 pool size)     │ (100 max_connections)
    │                          │                      │
    ├── Service 1 ────────────>│                      │
    ├── Service 2 ────────────>│                      │
    ├── Service 3 ────────────>│                      │
    └── Service 4 ────────────>│                      │
```

### Multicore Processing (Synchronizer)

```
┌─────────────────────────────────────────────────────────────────┐
│                        Main Process                              │
│                                                                  │
│   ┌────────────────────────────────────────────────────────┐    │
│   │                   aiomultiprocess Pool                  │    │
│   │                                                         │    │
│   │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐       │    │
│   │  │  Worker 1   │ │  Worker 2   │ │  Worker N   │       │    │
│   │  │             │ │             │ │             │       │    │
│   │  │ relay batch │ │ relay batch │ │ relay batch │       │    │
│   │  │     │       │ │     │       │ │     │       │       │    │
│   │  │     v       │ │     v       │ │     v       │       │    │
│   │  │  events     │ │  events     │ │  events     │       │    │
│   │  └──────┬──────┘ └──────┬──────┘ └──────┬──────┘       │    │
│   │         │               │               │               │    │
│   └─────────┴───────────────┴───────────────┴───────────────┘    │
│                             │                                     │
│                             v                                     │
│                    ┌────────────────┐                            │
│                    │ Aggregate and  │                            │
│                    │ insert to DB   │                            │
│                    └────────────────┘                            │
└─────────────────────────────────────────────────────────────────┘
```

### Graceful Shutdown

```python
# Signal handler (sync context)
def handle_signal(signum, frame):
    service.request_shutdown()  # Sets flag, doesn't await

# Service main loop
async def run_forever(self, interval: float) -> None:
    while not self._shutdown_requested:
        await self.run()
        if await self.wait(interval):  # Returns early if shutdown
            break
    # Cleanup happens in context manager __aexit__
```

---

## Summary

BigBrotr's architecture provides:

1. **Modularity** - Three-layer separation enables independent development and testing
2. **Flexibility** - Configuration-driven behavior without code changes
3. **Testability** - Dependency injection enables comprehensive unit testing
4. **Scalability** - Multicore processing and connection pooling for high throughput
5. **Reliability** - Graceful shutdown, state persistence, and retry logic
6. **Maintainability** - Clear patterns and consistent structure throughout

---

## Related Documentation

| Document | Description |
|----------|-------------|
| [CONFIGURATION.md](CONFIGURATION.md) | Complete configuration reference |
| [DATABASE.md](DATABASE.md) | Database schema documentation |
| [DEVELOPMENT.md](DEVELOPMENT.md) | Development setup and guidelines |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Deployment instructions |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | Contribution guidelines |
| [CHANGELOG.md](../CHANGELOG.md) | Version history |
