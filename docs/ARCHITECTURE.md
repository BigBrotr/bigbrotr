# Architecture

This document provides a comprehensive overview of BigBrotr's architecture, design patterns, and component interactions.

## Table of Contents

- [Overview](#overview)
- [Three-Tier Architecture](#three-tier-architecture)
- [Core Layer](#core-layer)
- [Service Layer](#service-layer)
- [Utils Layer](#utils-layer)
- [Models Layer](#models-layer)
- [Implementation Layer](#implementation-layer)
- [Design Patterns](#design-patterns)
- [Data Flow](#data-flow)
- [Concurrency Model](#concurrency-model)

---

## Overview

BigBrotr organizes its five sub-layers into three conceptual tiers:

| Tier | Layers | Role |
|------|--------|------|
| **Foundation** | Core + Models | Stable infrastructure and data structures -- rarely changes |
| **Active** | Services + Utils | Business logic, queries, mixins, constants -- where new features land |
| **Implementation** | Implementations | Deployment-specific configuration and customization |

The five sub-layers within those tiers are:

1. **Core Layer** - Reusable infrastructure components with zero business logic
2. **Models Layer** - Immutable data structures with validation and database mapping
3. **Service Layer** - Business logic, shared infrastructure, and service orchestration
4. **Utils Layer** - Shared utilities (dns, network, transport, YAML, keys)
5. **Implementation Layer** - Deployment-specific configuration and customization

This design allows:
- Multiple deployments from the same codebase
- Easy testing through dependency injection
- Configuration-driven behavior without code changes
- Clear separation between stable foundation and evolving business logic

---

## Three-Tier Architecture

```
  IMPLEMENTATION TIER
 =====================

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

  ACTIVE TIER
 =============

+-----------------------------------------------------------------------------+
|                             SERVICE LAYER                                    |
|                                                                              |
|   src/services/                                                              |
|   ├── common/           Shared service infrastructure                       |
|   │   ├── constants.py  ServiceName and DataType StrEnum enumerations       |
|   │   ├── mixins.py     BatchProgressMixin, NetworkSemaphoreMixin           |
|   │   └── queries.py    13 domain-specific SQL query functions              |
|   ├── seeder.py         Relay seeding for validation                        |
|   ├── finder.py         Relay URL discovery from APIs and events            |
|   ├── validator.py      Candidate relay validation                          |
|   ├── monitor.py        Relay health monitoring (NIP-11/NIP-66)             |
|   └── synchronizer.py   Event collection and sync                           |
|                                                                              |
|   Purpose: Business logic, service coordination, data transformation         |
+----------------------------------+------------------------------------------+
                                   |
                                   | Leverages
                                   v
+-----------------------------------------------------------------------------+
|                              UTILS LAYER                                     |
|                                                                              |
|   src/utils/                                                                 |
|   ├── dns.py           DNS resolution utilities                             |
|   ├── network.py       Network detection and proxy configuration            |
|   ├── transport.py     HTTP/WebSocket transport helpers                     |
|   ├── yaml.py          YAML loading with environment variable support       |
|   └── keys.py          Nostr key management utilities                       |
|                                                                              |
|   Purpose: Shared utilities used across core and services                    |
+----------------------------------+------------------------------------------+
                                   |
                                   | Uses
                                   v

  FOUNDATION TIER
 =================

+-----------------------------------------------------------------------------+
|                              CORE LAYER                                      |
|                                                                              |
|   src/core/                                                                  |
|   ├── pool.py           PostgreSQL connection pooling                       |
|   ├── brotr.py          Database interface + stored procedures              |
|   ├── base_service.py   Abstract service base class                         |
|   ├── metrics.py        Prometheus metrics server                           |
|   └── logger.py         Structured key=value logging                        |
|                                                                              |
|   Purpose: Reusable foundation, zero business logic                          |
+----------------------------------+------------------------------------------+
                                   |
                                   | Uses
                                   v
+-----------------------------------------------------------------------------+
|                             MODELS LAYER                                     |
|                                                                              |
|   src/models/                                                                |
|   ├── event.py         Nostr event with validation                          |
|   ├── relay.py         Relay URL with network detection                     |
|   ├── event_relay.py   Event-relay junction                                 |
|   ├── metadata.py      Generic metadata container                           |
|   ├── relay_metadata.py RelayMetadata junction with MetadataType            |
|   └── nips/            NIP model subpackages                                |
|       ├── nip11/       NIP-11 relay information (data, fetch, logs, nip11)  |
|       └── nip66/       NIP-66 monitoring (rtt, ssl, geo, net, dns, http)    |
|                                                                              |
|   Purpose: Immutable data structures, validation, database mapping           |
+-----------------------------------------------------------------------------+
```

### Layer Responsibilities

| Tier | Layer | Responsibility | Changes When |
|------|-------|----------------|--------------|
| **Foundation** | Core | Infrastructure, abstractions | Rarely -- foundation is stable |
| **Foundation** | Models | Data structures, validation | Schema changes, new data types |
| **Active** | Services | Business logic, shared queries, mixins, constants | Feature additions, protocol updates |
| **Active** | Utils | Shared utilities, helpers | When adding cross-cutting functionality |
| **Implementation** | Implementations | Configuration, customization | Per-deployment or environment |

---

## Core Layer

The core layer (`src/core/`) provides reusable infrastructure components.

### Pool (`pool.py`)

**Purpose**: Async PostgreSQL client with asyncpg driver.

**Key Features**:
- Async connection management with asyncpg (works behind PGBouncer)
- Configurable pool size limits
- Retry logic with exponential backoff
- Environment variable password loading (`DB_PASSWORD`)
- Connection health checking
- Async context manager support

**Note**: In Docker deployments, services connect to PGBouncer (port 6432/6433) which handles connection pooling at the infrastructure level. The Pool class provides application-level connection management and query methods.

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

**Stored Functions** (array-based bulk operations):
- `relays_insert` - Bulk insert relays
- `events_insert` - Bulk insert events
- `metadata_insert` - Bulk insert metadata (hash computed in Python)
- `events_relays_insert` - Bulk insert event-relay junctions
- `events_relays_insert_cascade` - Atomic bulk insert events + relays + junctions
- `relay_metadata_insert` - Bulk insert relay-metadata junctions
- `relay_metadata_insert_cascade` - Atomic bulk insert relays + metadata + junctions
- `service_data_upsert/get/delete` - Service data operations
- `orphan_events_delete` - Cleanup orphaned events
- `orphan_metadata_delete` - Cleanup unreferenced metadata

**Usage**:
```python
brotr = Brotr.from_yaml("yaml/core/brotr.yaml")

async with brotr:
    # Insert relays
    count = await brotr.insert_relays(relays_list)

    # Insert events
    count = await brotr.insert_events(events_list)

    # Insert events with relays (cascade)
    count = await brotr.insert_events_relays(event_relays_list)

    # Insert relay metadata (cascade)
    count = await brotr.insert_relay_metadata(relay_metadata_list)

    # Cleanup orphaned records
    deleted = await brotr.delete_orphan_events()
    deleted = await brotr.delete_orphan_metadata()
```

### BaseService (`base_service.py`)

**Purpose**: Abstract base class for all services.

**Key Features**:
- Generic type parameter for configuration class
- `SERVICE_NAME` and `CONFIG_CLASS` class attributes
- Continuous operation via `run_forever(interval)` with failure tracking
- Factory methods: `from_yaml()`, `from_dict()`
- Async context manager for lifecycle management
- Graceful shutdown via `request_shutdown()`
- Interruptible wait via `wait(timeout)`

**Interface**:
```python
class BaseService(ABC, Generic[ConfigT]):
    SERVICE_NAME: str              # Unique identifier for the service
    CONFIG_CLASS: type[ConfigT]    # For automatic config parsing

    _brotr: Brotr                  # Database interface
    _config: ConfigT               # Pydantic configuration

    @abstractmethod
    async def run(self) -> None:
        """Single cycle logic - must be implemented by subclasses."""
        pass

    async def run_forever(self, interval: float, max_consecutive_failures: int = 10) -> None:
        """Continuous loop with configurable interval and failure tracking."""
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

### Logger (`core/logger.py`)

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

## Utils Layer

The utils layer (`src/utils/`) provides shared utilities used across core and services.

### Modules

| Module | Purpose |
|--------|---------|
| `dns.py` | DNS resolution utilities |
| `network.py` | Network detection and proxy configuration |
| `transport.py` | HTTP/WebSocket transport helpers |
| `yaml.py` | YAML loading with environment variable support |
| `keys.py` | Nostr key management utilities |

These utilities are stateless functions and classes that can be imported by any layer above Models.

---

## Models Layer

The models layer (`src/models/`) contains immutable data structures with validation.

### Data Models

| Model | Purpose |
|-------|---------|
| `Event` | Nostr event with cryptographic validation |
| `Relay` | Relay URL with network type detection |
| `EventRelay` | Event-relay junction with seen_at timestamp |
| `Metadata` | Generic metadata container (JSON data) |
| `RelayMetadata` | Relay-metadata junction with type and timestamp |
| `Nip11` | NIP-11 relay information document |
| `Nip66` | NIP-66 relay monitoring data |

### Key Types

| Type | Values |
|------|--------|
| `NetworkType` | `clearnet`, `tor`, `i2p`, `loki`, `local`, `unknown` |
| `MetadataType` | `nip11_fetch`, `nip66_rtt`, `nip66_ssl`, `nip66_geo`, `nip66_net`, `nip66_dns`, `nip66_http` |

All models use `@dataclass(frozen=True)` for immutability and provide `to_db_params()` for database insertion.

---

## Service Layer

The service layer (`src/services/`) contains business logic implementations.

### Service Architecture

All services follow the same pattern:

1. **Configuration Class** - Pydantic model inheriting from `BaseServiceConfig`
2. **Service Class** - Inherits from `BaseService[ConfigClass]`
3. **`run()` Method** - Single cycle logic (abstract method implementation)
4. **Factory Methods** - `from_yaml()`, `from_dict()` inherited from base

```python
# Example service structure
SERVICE_NAME = "myservice"

class MyServiceConfig(BaseServiceConfig):
    # Inherits: interval, max_consecutive_failures, metrics
    some_setting: str = Field(default="value")
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

### Shared Service Infrastructure (`services/common/`)

The `services/common/` package provides shared infrastructure used by all services:

| Module | Purpose |
|--------|---------|
| `constants.py` | `ServiceName` and `DataType` StrEnum enumerations eliminating hardcoded strings |
| `mixins.py` | `BatchProgressMixin` for batch tracking, `NetworkSemaphoreMixin` for per-network concurrency limits |
| `queries.py` | 13 domain-specific SQL query functions (relay lookups, candidate lifecycle, cursor management) |

Services import from `services.common` instead of writing inline SQL or using string literals. This consolidation keeps business logic in individual service files focused on orchestration rather than query construction.

### Seeder Service

**Purpose**: Relay seeding for validation.

**Lifecycle**: One-shot (runs once, then exits)

**Operations**:
1. Parse seed relay URLs from configured file
2. Validate URLs and detect network type (clearnet/tor/i2p/loki)
3. Store as candidates in `service_data` table for Validator

### Finder Service

**Purpose**: Relay URL discovery from multiple sources.

**Lifecycle**: Continuous (`run_forever`)

**Operations**:
1. Fetch relay lists from configured API sources (e.g., nostr.watch)
2. Scan stored events for relay URLs (NIP-65 relay lists, kind 2/3 events)
3. Validate URLs using the Relay model
4. Store discovered URLs as candidates in `service_data` table

**Note**: Finder stores candidates, not relays. The Validator service tests and promotes valid candidates to the `relays` table.

### Validator Service

**Purpose**: Test and validate candidate relay URLs.

**Lifecycle**: Continuous (`run_forever`)

**Architecture**: Streaming with batch processing

**Operations**:
1. Cleanup exhausted candidates (optional, based on `max_failures`)
2. Fetch chunk of candidates from `service_data` table
3. Validate in parallel with per-network semaphores
4. Persist results (promote or increment failure count)
5. Repeat until all candidates processed

**Features**:
- Multi-network support (clearnet, Tor, I2P, Lokinet)
- Per-network concurrency limits via `max_tasks`
- Configurable connection timeout per network
- Prometheus metrics integration

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

**Multi-Network Support**:
- Configurable SOCKS5 proxy for overlay networks (Tor, I2P, Lokinet)
- Automatic network detection from URL
- Per-network timeout and concurrency settings
- SSL certificate validation and geolocation

### Synchronizer Service

**Purpose**: Event collection from relays.

**Lifecycle**: Continuous (`run_forever`)

**Key Features**:
- **Multicore Processing**: Uses `aiomultiprocess` for parallel processing
- **Time-Window Stack**: Algorithm for handling large event volumes
- **Incremental Sync**: Per-relay timestamp tracking
- **Per-Relay Overrides**: Custom settings for specific relays
- **Graceful Shutdown**: Clean worker process termination via `atexit`
- **Tor Support**: SOCKS5 proxy for .onion relay synchronization

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
     └─── Continue cycle           │
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
│       ├── seeder.yaml          # Seed file configuration
│       ├── finder.yaml          # API sources, intervals
│       ├── validator.yaml       # Multi-network validation (Tor enabled)
│       ├── monitor.yaml         # Health check settings, Tor proxy
│       └── synchronizer.yaml    # High concurrency (10 parallel, 4 processes)
├── postgres/
│   └── init/                    # SQL schema files (00-99)
│       ├── 02_tables.sql        # Full schema with tags, tagvalues, content
│       └── ...
├── prometheus/
│   └── prometheus.yaml          # Prometheus scrape configuration
├── grafana/
│   ├── provisioning/            # Dashboard and datasource provisioning
│   └── dashboards/              # Pre-built dashboards
├── static/
│   └── seed_relays.txt          # 8,865 initial relay URLs
├── docker-compose.yaml          # Ports: 5432, 6432 (PGBouncer), 9090, 3000, 9050
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
│       ├── synchronizer.yaml    # Overlay networks disabled, lower concurrency (5 parallel)
│       └── ...                  # Other services inherit defaults
├── postgres/
│   └── init/
│       ├── 02_tables.sql        # Minimal schema (NO tags, tagvalues, content)
│       └── ...
├── prometheus/
│   └── prometheus.yaml          # Prometheus scrape configuration
├── grafana/
│   ├── provisioning/            # Dashboard and datasource provisioning
│   └── dashboards/              # Pre-built dashboards
├── docker-compose.yaml          # Different ports: 5433, 6433 (PGBouncer), 9091, 3001
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
   networks:
     clearnet:
       enabled: true
       max_tasks: 3  # Lower concurrency
     tor:
       enabled: false  # Disable Tor
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
        self.pool = pool or Pool(...)
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
    async with service:     # Lifecycle management
        await service.run_forever(interval=3600)
```

---

## Data Flow

### Event Synchronization Flow

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Seeder    │     │   Finder    │     │  Validator  │     │   Monitor   │
└──────┬──────┘     └──────┬──────┘     └──────┬──────┘     └──────┬──────┘
       │                   │                   │                   │
       │ Seed URLs         │ Discover URLs     │ Test candidates   │ Check health
       │ (one-shot)        │ from APIs/events  │ Promote to relays │ NIP-11/NIP-66
       v                   v                   v                   v
┌─────────────────────────────────────────────────────────────────────────┐
│                              PostgreSQL                                  │
│  ┌─────────────────┐  ┌─────────┐  ┌──────┐  ┌─────────────────┐       │
│  │  service_data   │  │ relays  │  │events│  │ relay_metadata  │       │
│  │  (candidates)   │  │         │  │      │  │    + metadata   │       │
│  └─────────────────┘  └─────────┘  └──────┘  └─────────────────┘       │
│                              │          │              │                │
│                              └──────────┴──────────────┘                │
│                                   events_relays                         │
└─────────────────────────────────────────────────────────────────────────┘
                                        ^
                                        │
                              ┌─────────────────┐
                              │  Synchronizer   │
                              │ Collect events  │
                              └─────────────────┘
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
│                                    │ (links relay to metadata││
│                                    │  by metadata_type and   ││
│                                    │  hash ID)               ││
│                                    └─────────────────────────┘│
└──────────────────────────────────────────────────────────────┘

**Metadata Types**: `nip11_fetch`, `nip66_rtt`, `nip66_ssl`, `nip66_geo`, `nip66_net`, `nip66_dns`, `nip66_http`
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

1. **Modularity** - Three-tier, five-layer separation enables independent development and testing
2. **Flexibility** - Configuration-driven behavior without code changes
3. **Testability** - Dependency injection enables comprehensive unit testing
4. **Scalability** - Multicore processing and connection pooling for high throughput
5. **Reliability** - Graceful shutdown, failure tracking, and retry logic
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
