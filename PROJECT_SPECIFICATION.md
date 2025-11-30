# BigBrotr Project Specification

**Last Updated**: 2025-11-30
**Version**: 1.0.0-dev
**Status**: In Development

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Architecture](#architecture)
3. [Core Layer](#core-layer)
4. [Service Layer](#service-layer)
5. [Implementation Layer](#implementation-layer)
6. [Database Schema](#database-schema)
7. [Configuration](#configuration)
8. [Deployment](#deployment)
9. [Development Roadmap](#development-roadmap)

---

## Project Overview

### What is BigBrotr?

BigBrotr is a modular Nostr data archiving and monitoring system built on Python and PostgreSQL. It provides relay discovery, health monitoring, and event synchronization for the Nostr protocol ecosystem.

### Goals

- Archive Nostr events from multiple relays with provenance tracking
- Monitor relay health and capabilities (NIP-11, NIP-66)
- Discover new relays via APIs and event scanning
- Provide SQL-based analytics via views

### Design Philosophy

| Principle | Description |
|-----------|-------------|
| **Three-Layer Architecture** | Core (reusable) → Services (modular) → Implementation (config-driven) |
| **Dependency Injection** | Services receive `Brotr` via constructor for testability |
| **Configuration-Driven** | YAML configs with Pydantic validation, no hardcoded values |
| **Type Safety** | Full type hints throughout, Pydantic models for all configs |
| **Async-First** | Built on asyncio, asyncpg, aiohttp |

---

## Architecture

### Three-Layer Design

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      IMPLEMENTATION LAYER                               │
│         implementations/bigbrotr/                                       │
│         (YAML configs, SQL schemas, Docker, seed data)                  │
│                                                                         │
│         Purpose: Define HOW this deployment behaves                     │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ Uses
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         SERVICE LAYER                                   │
│         src/services/                                                   │
│                                                                         │
│         Initializer  - Database bootstrap         [DONE]                │
│         Finder       - Relay discovery            [PARTIAL - no events] │
│         Monitor      - Health checks (NIP-11/66)  [DONE]                │
│         Synchronizer - Event collection           [DONE]                │
│         API          - REST endpoints             [NOT IMPLEMENTED]     │
│         DVM          - Data Vending Machine       [NOT IMPLEMENTED]     │
│                                                                         │
│         Purpose: Business logic, coordination                           │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ Leverages
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          CORE LAYER                                     │
│         src/core/                                                       │
│                                                                         │
│         Pool        - PostgreSQL connection pooling                     │
│         Brotr       - Database interface + stored procedures            │
│         BaseService - Abstract base class with lifecycle                │
│         Logger      - Structured logging                                │
│                                                                         │
│         Purpose: Reusable foundation, zero business logic               │
└─────────────────────────────────────────────────────────────────────────┘
```

### Layer Responsibilities

| Layer | Responsibility | Contains |
|-------|----------------|----------|
| **Core** | Infrastructure, utilities | Pool, Brotr, BaseService, Logger |
| **Service** | Business logic, orchestration | Initializer, Finder, Monitor, Synchronizer |
| **Implementation** | Configuration, deployment | YAML, SQL, Docker, seed data |

---

## Core Layer

Location: `src/core/`

### Pool (`pool.py`, ~410 lines)

**Purpose**: PostgreSQL connection pooling with asyncpg.

**Features**:
- Async connection pooling
- Retry logic with exponential backoff
- PGBouncer compatibility (transaction mode)
- Environment variable password loading (`DB_PASSWORD`)
- Health check support
- Context manager (`async with pool:`)

**Configuration**:
```yaml
pool:
  database:
    host: pgbouncer
    port: 5432
    database: bigbrotr
    user: admin
  limits:
    min_size: 5
    max_size: 20
  retry:
    max_attempts: 3
    exponential_backoff: true
```

### Brotr (`brotr.py`, ~430 lines)

**Purpose**: High-level database interface with stored procedure wrappers.

**Features**:
- Composition: HAS-A Pool (public property)
- Stored procedure wrappers (insert_event, insert_relay, insert_relay_metadata)
- Batch operations with configurable limits
- Hex-to-BYTEA conversion for event IDs
- Context manager (delegates to Pool)

**Note**: Stored procedure names are hardcoded in constants for security (not configurable via YAML).

**API**:
```python
brotr = Brotr.from_yaml("yaml/core/brotr.yaml")

async with brotr:
    await brotr.insert_events([...])
    await brotr.insert_relays([...])
    await brotr.cleanup_orphans()
```

### BaseService (`base_service.py`, ~200 lines)

**Purpose**: Abstract base class for all services.

**Features**:
- `SERVICE_NAME` and `CONFIG_CLASS` class attributes
- State persistence via `_load_state()` / `_save_state()`
- Continuous operation via `run_forever(interval)`
- Factory methods: `from_yaml()`, `from_dict()`
- Context manager (auto load/save state)
- Graceful shutdown via `request_shutdown()`

**Interface**:
```python
class BaseService(ABC, Generic[ConfigT]):
    SERVICE_NAME: str
    CONFIG_CLASS: type[ConfigT]

    async def run(self) -> None           # Abstract - single cycle
    async def run_forever(interval)       # Continuous loop
    async def health_check() -> bool      # Database connectivity
    def request_shutdown()                # Sync-safe shutdown
```

### Logger (`logger.py`, ~50 lines)

**Purpose**: Structured logging wrapper with key=value formatting.

**API**:
```python
logger = Logger("finder")
logger.info("cycle_completed", relays_found=100, duration=2.5)
# Output: 2025-01-01 12:00:00 INFO finder: cycle_completed relays_found=100 duration=2.5
```

---

## Service Layer

Location: `src/services/`

### Initializer (`initializer.py`, ~310 lines)

**Status**: Done

**Purpose**: Database bootstrap and schema verification.

**What it does**:
- Verifies PostgreSQL extensions (pgcrypto, btree_gin)
- Verifies tables, procedures, and views exist
- Seeds relay URLs from `data/seed_relays.txt`

**Mode**: One-shot (runs once, exits)

### Finder (`finder.py`, ~220 lines)

**Status**: Partial

**Purpose**: Relay URL discovery.

**Implemented**:
- Fetches relay lists from nostr.watch APIs
- Validates URLs with nostr-tools
- Batch insertion into database

**NOT Implemented**:
- `_find_from_events()` - Event scanning for relay hints (TODO in code)

**Mode**: Continuous (`run_forever`)

### Monitor (`monitor.py`, ~400 lines)

**Status**: Done

**Purpose**: Relay health and capability assessment.

**What it does**:
- Fetches NIP-11 relay information documents
- Tests NIP-66 capabilities (open, read, write) with RTT
- Supports Tor proxy for .onion relays
- Concurrent checking with semaphore
- Stores in `relay_metadata` with deduplication

**Mode**: Continuous (`run_forever`)

### Synchronizer (`synchronizer.py`, ~740 lines)

**Status**: Done

**Purpose**: Event collection from relays.

**Features**:
- Multicore processing via `aiomultiprocess`
- Time-window stack algorithm for large event volumes
- Per-relay override settings
- Network-specific timeouts (clearnet vs Tor)
- Incremental sync with per-relay state tracking
- Worker process cleanup via `atexit`

**Mode**: Continuous (`run_forever`)

### API (`api.py`)

**Status**: Not Implemented (stub file)

**Planned**: REST endpoints with OpenAPI documentation

### DVM (`dvm.py`)

**Status**: Not Implemented (stub file)

**Planned**: NIP-90 Data Vending Machine protocol

---

## Implementation Layer

Location: `implementations/bigbrotr/`

### Purpose

The implementation layer contains deployment-specific configurations. This separation allows:
- Different database configurations (local dev vs production)
- Custom SQL schemas (additional indexes, partitioning)
- Alternative seed data sources
- Multiple deployments from the same codebase

### Structure

```
implementations/bigbrotr/
├── yaml/
│   ├── core/
│   │   └── brotr.yaml              # Database pool and Brotr settings
│   └── services/
│       ├── initializer.yaml        # Schema verification, seed file path
│       ├── finder.yaml             # API sources, intervals
│       ├── monitor.yaml            # Timeouts, concurrency, Tor config
│       ├── synchronizer.yaml       # Filters, timeouts, multicore
│       ├── api.yaml                # Empty (not implemented)
│       └── dvm.yaml                # Empty (not implemented)
├── postgres/
│   └── init/                       # SQL schema files (00-99)
├── data/
│   └── seed_relays.txt             # ~8,865 seed relay URLs
├── docker-compose.yaml             # Container orchestration
├── Dockerfile                      # Multi-stage build
└── .env.example                    # Environment template
```

### Creating a Custom Implementation

1. Copy `implementations/bigbrotr/` to `implementations/mydeployment/`
2. Modify YAML configs as needed
3. Optionally customize SQL schemas
4. Update `docker-compose.yaml` paths
5. The core and service layers remain unchanged

---

## Database Schema

Location: `implementations/bigbrotr/postgres/init/`

### Schema Files (apply in order)

| File | Purpose |
|------|---------|
| `00_extensions.sql` | pgcrypto, btree_gin extensions |
| `01_utility_functions.sql` | tags_to_tagvalues, hash functions |
| `02_tables.sql` | All table definitions |
| `03_indexes.sql` | Performance indexes |
| `04_integrity_functions.sql` | Orphan cleanup functions |
| `05_procedures.sql` | insert_event, insert_relay, insert_relay_metadata |
| `06_views.sql` | Statistics and metadata views |
| `99_verify.sql` | Schema validation notice |

### Tables

| Table | Purpose |
|-------|---------|
| `relays` | Known relay URLs with network type (clearnet/tor) |
| `events` | Nostr events (BYTEA IDs for 50% space savings) |
| `events_relays` | Junction table tracking event provenance per relay |
| `nip11` | Deduplicated NIP-11 documents (content-addressed by hash) |
| `nip66` | Deduplicated NIP-66 test results (content-addressed by hash) |
| `relay_metadata` | Time-series metadata snapshots |
| `service_state` | Service state persistence (JSONB) |

### Views

| View | Purpose | Performance Note |
|------|---------|------------------|
| `relay_metadata_latest` | Latest metadata per relay | Uses DISTINCT ON |
| `events_statistics` | Global event counts and categories | Full table scan |
| `relays_statistics` | Per-relay event counts and RTT | Window functions |
| `kind_counts_total` | Event counts by kind | GROUP BY |
| `kind_counts_by_relay` | Event counts by kind per relay | JOIN + GROUP BY |
| `pubkey_counts_total` | Event counts by pubkey | GROUP BY |
| `pubkey_counts_by_relay` | Event counts by pubkey per relay | JOIN + GROUP BY |

**Note**: Some views may be slow on large datasets. Index tuning may be needed at scale.

---

## Configuration

### Philosophy

1. **YAML-Driven**: All non-sensitive configuration in YAML files
2. **Environment Variables**: Only sensitive data (passwords) from environment
3. **Pydantic Validation**: All configs validated at startup
4. **CONFIG_CLASS**: Services use class attribute for automatic parsing

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DB_PASSWORD` | Yes | PostgreSQL password |
| `MONITOR_PRIVATE_KEY` | No | Nostr private key for NIP-66 write tests |

### Core Configuration (`yaml/core/brotr.yaml`)

```yaml
pool:
  database:
    host: pgbouncer
    port: 5432
    database: bigbrotr
    user: admin
  limits:
    min_size: 5
    max_size: 20
  timeouts:
    acquisition: 10.0
  retry:
    max_attempts: 3
    exponential_backoff: true

batch:
  max_batch_size: 1000

timeouts:
  query: 60.0
  procedure: 90.0
  batch: 120.0
```

---

## Deployment

### Docker Compose

Services included:
- **PostgreSQL 16**: Primary database
- **PGBouncer**: Connection pooling (transaction mode)
- **Tor**: SOCKS5 proxy for .onion relays (optional)
- **Initializer**: One-shot database bootstrap
- **Finder**: Continuous relay discovery
- **Monitor**: Continuous health checking
- **Synchronizer**: Continuous event collection

### Deployment Steps

```bash
# 1. Configure environment
cd implementations/bigbrotr
cp .env.example .env
nano .env  # Set DB_PASSWORD

# 2. Start infrastructure
docker-compose up -d postgres pgbouncer tor

# 3. Run initializer (one-shot)
docker-compose up initializer

# 4. Start services
docker-compose up -d finder monitor synchronizer
```

---

## Development Roadmap

### Phase 1: Core Infrastructure - DONE

- [x] Pool implementation
- [x] Brotr implementation
- [x] BaseService abstract class
- [x] Logger module

### Phase 2: Core Services - IN PROGRESS

- [x] Initializer service
- [x] Finder service (API discovery)
- [ ] Finder service (event scanning) - TODO in code
- [x] Monitor service
- [x] Synchronizer service (multicore)
- [x] Unit tests (174 passing)
- [ ] Integration tests

### Phase 3: Public Access - PLANNED

- [ ] API service (REST endpoints)
- [ ] DVM service (NIP-90)

### Infrastructure TODOs

- [ ] Database backup strategy
- [ ] Query/index optimization for scale
- [ ] Health check endpoints for containers
- [ ] Metrics export (Prometheus)

---

## Technology Stack

| Technology | Version | Purpose |
|------------|---------|---------|
| Python | 3.9+ | Programming language |
| PostgreSQL | 16+ | Database storage |
| asyncpg | 0.30.0 | Async PostgreSQL driver |
| Pydantic | 2.10.4 | Configuration validation |
| PyYAML | 6.0.2 | YAML parsing |
| aiohttp | 3.13.2 | Async HTTP client |
| aiohttp-socks | 0.10.1 | SOCKS5 proxy for Tor |
| aiomultiprocess | 0.9.1 | Multicore processing |
| nostr-tools | 1.4.1 | Nostr protocol library |
| Docker | - | Containerization |
| PGBouncer | - | Connection pooling |

---

**End of Project Specification**
