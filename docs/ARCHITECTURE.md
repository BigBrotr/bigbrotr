# Architecture

This document provides a comprehensive overview of BigBrotr v4.0.0's architecture, design patterns, and component interactions.

## Table of Contents

- [Overview](#overview)
- [Diamond DAG Architecture](#diamond-dag-architecture)
- [Core Layer](#core-layer)
- [NIPs Layer](#nips-layer)
- [Service Layer](#service-layer)
- [Utils Layer](#utils-layer)
- [Models Layer](#models-layer)
- [Deployment Layer](#deployment-layer)
- [Design Patterns](#design-patterns)
- [Data Flow](#data-flow)
- [Concurrency Model](#concurrency-model)

---

## Overview

BigBrotr v4.0.0 uses a **Diamond DAG** architecture where the service layer depends on three parallel mid-tier packages (core, nips, utils), all of which converge on the models layer at the bottom:

| Tier | Layers | Role |
|------|--------|------|
| **Top** | Services | Business logic, queries, mixins, constants -- where new features land |
| **Mid** | Core + NIPs + Utils | Infrastructure, NIP protocol models, shared utilities |
| **Foundation** | Models | Stable data structures -- rarely changes |
| **Deployment** | Deployments | Deployment-specific configuration and customization |

The layers within the `src/bigbrotr/` package namespace are:

1. **Services Layer** (`bigbrotr/services/`) - Business logic, shared infrastructure, and service orchestration
2. **Core Layer** (`bigbrotr/core/`) - Reusable infrastructure components with zero business logic
3. **NIPs Layer** (`bigbrotr/nips/`) - NIP-11 and NIP-66 protocol models (extracted from models)
4. **Utils Layer** (`bigbrotr/utils/`) - Shared utilities (dns, network, transport, YAML, keys)
5. **Models Layer** (`bigbrotr/models/`) - Immutable data structures with validation and database mapping
6. **Deployment Layer** (`deployments/`) - Deployment-specific configuration and customization

This design allows:
- Multiple deployments from the same codebase
- Easy testing through dependency injection
- Configuration-driven behavior without code changes
- Clear separation between stable foundation and evolving business logic

---

## Diamond DAG Architecture

```
  DEPLOYMENT TIER
 ==================

+-----------------------------------------------------------------------------+
|                           DEPLOYMENT LAYER                                   |
|                                                                              |
|   deployments/                                                               |
|   ├── bigbrotr/        Full-featured (stores tags, content, Tor support)    |
|   └── lilbrotr/        Lightweight (no tags/content, clearnet only)         |
|                                                                              |
|   Each deployment contains:                                                  |
|   ├── config/          Configuration files (YAML)                           |
|   ├── postgres/init/   SQL schema definitions                               |
|   ├── monitoring/      Grafana dashboards + Prometheus config               |
|   ├── static/          Seed data and static resources                       |
|   ├── docker-compose.yaml  Container orchestration                          |
|   └── Dockerfile       Application container                                |
|                                                                              |
|   Purpose: Define HOW this specific deployment behaves                       |
+----------------------------------+------------------------------------------+
                                   |
                                   | Uses
                                   v

  SERVICE TIER
 ==============

+-----------------------------------------------------------------------------+
|                             SERVICE LAYER                                    |
|                                                                              |
|   src/bigbrotr/services/                                                     |
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
                      +------------+------------+
                      |            |            |
                      v            v            v

  MID TIER (Diamond DAG — services depend on all three)
 =======================================================

+---------------------+ +---------------------+ +---------------------+
|     CORE LAYER      | |     NIPS LAYER      | |     UTILS LAYER     |
|                     | |                     | |                     |
| src/bigbrotr/core/  | | src/bigbrotr/nips/  | | src/bigbrotr/utils/ |
| ├── pool.py         | | ├── nip11/          | | ├── dns.py          |
| ├── brotr.py        | | │   ├── data.py     | | ├── network.py      |
| ├── base_service.py | | │   ├── fetch.py    | | ├── transport.py    |
| ├── metrics.py      | | │   ├── logs.py     | | ├── yaml.py         |
| └── logger.py       | | │   └── nip11.py    | | └── keys.py         |
|                     | | └── nip66/          | |                     |
| Purpose: Reusable   | |     ├── rtt.py      | | Purpose: Shared     |
| foundation, zero    | |     ├── ssl.py      | | utilities used      |
| business logic      | |     ├── geo.py      | | across layers       |
+----------+----------+ |     ├── net.py      | +----------+----------+
           |            |     ├── dns.py      |            |
           |            |     ├── http.py     |            |
           |            |     └── nip66.py    |            |
           |            |                     |            |
           |            | Purpose: NIP proto- |            |
           |            | col models          |            |
           |            +----------+----------+            |
           |                       |                       |
           +-----------+-----------+-----------+-----------+
                       |
                       v

  FOUNDATION TIER
 =================

+-----------------------------------------------------------------------------+
|                             MODELS LAYER                                     |
|                                                                              |
|   src/bigbrotr/models/                                                       |
|   ├── event.py         Nostr event with validation                          |
|   ├── relay.py         Relay URL with network detection                     |
|   ├── event_relay.py   Event-relay junction                                 |
|   ├── metadata.py      Generic metadata container                           |
|   └── relay_metadata.py RelayMetadata junction with MetadataType            |
|                                                                              |
|   Purpose: Immutable data structures, validation, database mapping           |
+-----------------------------------------------------------------------------+
```

### Layer Responsibilities

| Tier | Layer | Responsibility | Changes When |
|------|-------|----------------|--------------|
| **Foundation** | Models | Data structures, validation | Schema changes, new data types |
| **Mid** | Core | Infrastructure, abstractions | Rarely -- foundation is stable |
| **Mid** | NIPs | NIP-11/NIP-66 protocol models | Protocol updates, new NIP support |
| **Mid** | Utils | Shared utilities, helpers | When adding cross-cutting functionality |
| **Top** | Services | Business logic, shared queries, mixins, constants | Feature additions, protocol updates |
| **Deployment** | Deployments | Configuration, customization | Per-deployment or environment |

---

## Core Layer

The core layer (`src/bigbrotr/core/`) provides reusable infrastructure components.

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
    retry: PoolRetryConfig        # max_attempts, delays, backoff
    server_settings: dict         # application_name, timezone
```

**Usage**:
```python
pool = Pool.from_yaml("config/brotr.yaml")

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
brotr = Brotr.from_yaml("config/brotr.yaml")

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

### Logger (`bigbrotr/core/logger.py`)

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

## NIPs Layer

The NIPs layer (`src/bigbrotr/nips/`) contains NIP-11 and NIP-66 protocol models, extracted from the former `models/nips/` subpackage into a standalone mid-tier package.

### Subpackages

| Subpackage | Purpose |
|------------|---------|
| `nip11/` | NIP-11 relay information document models (data, fetch, logs, nip11) |
| `nip66/` | NIP-66 relay monitoring models (rtt, ssl, geo, net, dns, http, nip66) |

The NIPs layer depends on the Models layer (for `Relay`, `Metadata`, `RelayMetadata`, `MetadataType`) but has no dependency on Core or Utils. Services import from `bigbrotr.nips` to access NIP protocol models.

---

## Utils Layer

The utils layer (`src/bigbrotr/utils/`) provides shared utilities used across core and services.

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

The models layer (`src/bigbrotr/models/`) contains immutable data structures with validation.

### Data Models

| Model | Purpose |
|-------|---------|
| `Event` | Nostr event with cryptographic validation |
| `Relay` | Relay URL with network type detection |
| `EventRelay` | Event-relay junction with seen_at timestamp |
| `Metadata` | Generic metadata container (JSON data) |
| `RelayMetadata` | Relay-metadata junction with type and timestamp |

**Note**: NIP-11 and NIP-66 protocol models have been extracted to the separate `bigbrotr/nips/` layer (see [NIPs Layer](#nips-layer)).

### Key Types

| Type | Values |
|------|--------|
| `NetworkType` | `clearnet`, `tor`, `i2p`, `loki`, `local`, `unknown` |
| `MetadataType` | `nip11_info`, `nip66_rtt`, `nip66_ssl`, `nip66_geo`, `nip66_net`, `nip66_dns`, `nip66_http` |

All models use `@dataclass(frozen=True)` for immutability and provide `to_db_params()` for database insertion.

---

## Service Layer

The service layer (`src/bigbrotr/services/`) contains business logic implementations.

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

The `bigbrotr/services/common/` package provides shared infrastructure used by all services:

| Module | Purpose |
|--------|---------|
| `constants.py` | `ServiceName` and `DataType` StrEnum enumerations eliminating hardcoded strings |
| `mixins.py` | `BatchProgressMixin` for batch tracking, `NetworkSemaphoreMixin` for per-network concurrency limits |
| `queries.py` | 13 domain-specific SQL query functions (relay lookups, candidate lifecycle, cursor management) |

Services import from `bigbrotr.services.common` instead of writing inline SQL or using string literals. This consolidation keeps business logic in individual service files focused on orchestration rather than query construction.

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

## Deployment Layer

The deployment layer contains deployment-specific resources. Two deployments are provided:

### Included Deployments

| Deployment | Purpose | Key Differences |
|------------|---------|-----------------|
| **bigbrotr** | Full-featured archiving | Stores tags/content, Tor support, high concurrency |
| **lilbrotr** | Lightweight indexing | Indexes all events but omits tags/content (~60% disk savings), clearnet only |

### BigBrotr Structure (Full-Featured)

```
deployments/bigbrotr/
├── config/
│   ├── brotr.yaml               # Database connection, pool settings
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
├── monitoring/
│   ├── prometheus.yaml          # Prometheus scrape configuration
│   ├── provisioning/            # Grafana dashboard and datasource provisioning
│   └── dashboards/              # Pre-built Grafana dashboards
├── static/
│   └── seed_relays.txt          # 8,865 initial relay URLs
├── docker-compose.yaml          # Ports: 5432, 6432 (PGBouncer), 9090, 3000, 9050
├── Dockerfile
└── .env.example
```

### LilBrotr Structure (Lightweight)

```
deployments/lilbrotr/
├── config/
│   ├── brotr.yaml               # Same pool settings
│   └── services/
│       ├── synchronizer.yaml    # Overlay networks disabled, lower concurrency (5 parallel)
│       └── ...                  # Other services inherit defaults
├── postgres/
│   └── init/
│       ├── 02_tables.sql        # Minimal schema (NO tags, tagvalues, content)
│       └── ...
├── monitoring/
│   ├── prometheus.yaml          # Prometheus scrape configuration
│   ├── provisioning/            # Grafana dashboard and datasource provisioning
│   └── dashboards/              # Pre-built Grafana dashboards
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

### Creating Custom Deployments

To create a custom deployment:

1. Copy an existing deployment:
   ```bash
   cp -r deployments/bigbrotr deployments/mydeployment
   ```

2. Modify YAML configurations as needed:
   ```yaml
   # config/services/synchronizer.yaml
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
   cd deployments/mydeployment
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

**Metadata Types**: `nip11_info`, `nip66_rtt`, `nip66_ssl`, `nip66_geo`, `nip66_net`, `nip66_dns`, `nip66_http`
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

1. **Modularity** - Diamond DAG architecture with clear dependency flow enables independent development and testing
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
