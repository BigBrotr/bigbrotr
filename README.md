<p align="center">
  <img src="https://img.shields.io/badge/python-3.9+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/postgresql-16+-4169E1?style=for-the-badge&logo=postgresql&logoColor=white" alt="PostgreSQL">
  <img src="https://img.shields.io/badge/docker-ready-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker">
  <img src="https://img.shields.io/badge/tests-174_passing-brightgreen?style=for-the-badge" alt="Tests">
  <img src="https://img.shields.io/badge/status-in_development-yellow?style=for-the-badge" alt="Status">
</p>

<h1 align="center">BigBrotr</h1>

<p align="center">
  <strong>A Modular Nostr Data Archiving and Monitoring System</strong>
</p>

<p align="center">
  <em>Infrastructure for indexing, monitoring, and analyzing the Nostr protocol ecosystem</em>
</p>

---

## Table of Contents

- [Overview](#overview)
- [Current Status](#current-status)
- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Installation](#installation)
- [Services](#services)
- [Configuration](#configuration)
- [Database Schema](#database-schema)
- [Development](#development)
- [Known Limitations & TODOs](#known-limitations--todos)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)

---

## Overview

BigBrotr is a modular system for archiving and monitoring the Nostr protocol ecosystem. Built with Python and PostgreSQL, it provides:

- **Relay Discovery**: Find and track Nostr relays across clearnet and Tor
- **Health Monitoring**: Test relay connectivity and capabilities (NIP-11/NIP-66)
- **Event Synchronization**: Archive events from multiple relays with multicore support
- **Data Analysis**: SQL views for statistics and analytics

### Design Philosophy

| Principle | Description |
|-----------|-------------|
| **Three-Layer Architecture** | Core (reusable) → Services (modular) → Implementation (config-driven) |
| **Dependency Injection** | Services receive `Brotr` via constructor for testability |
| **Configuration-Driven** | YAML configs with Pydantic validation |
| **Type Safety** | Full type hints throughout the codebase |
| **Async-First** | Built on asyncio, asyncpg, aiohttp for concurrency |

---

## Current Status

> **This project is under active development. Core services are functional but there are known limitations and missing features.**

### What's Working

| Component | Status | Notes |
|-----------|--------|-------|
| **Core Layer** | Functional | Pool, Brotr, BaseService, Logger (~1,080 lines) |
| **Initializer** | Functional | Database bootstrap, schema verification, seeding |
| **Finder** | Partial | API discovery works; event scanning NOT implemented |
| **Monitor** | Functional | NIP-11/NIP-66 checking with Tor support |
| **Synchronizer** | Functional | Event sync with multicore support (~740 lines) |
| **Unit Tests** | 174 passing | ~3,500 lines of tests |
| **Docker Compose** | Functional | PostgreSQL, PGBouncer, Tor proxy, all services |

### What's Missing or Incomplete

| Component | Status | Description |
|-----------|--------|-------------|
| **API Service** | Not implemented | REST endpoints (stub file only) |
| **DVM Service** | Not implemented | NIP-90 Data Vending Machine (stub file only) |
| **Event Scanning** | Not implemented | Finder's `_find_from_events()` is empty (TODO) |
| **Integration Tests** | Missing | Only unit tests exist |
| **Database Backup** | Not implemented | No backup/restore strategy |
| **Query Optimization** | Needs work | Views and indexes may need tuning for scale |

### Metrics

| Metric | Value |
|--------|-------|
| Source Code | ~3,120 lines |
| Test Code | ~3,500 lines |
| SQL Schema | 8 files (~600 lines) |
| Seed Relays | 8,865 URLs |
| Unit Tests | 174 passing |

---

## Architecture

### Three-Layer Design

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      IMPLEMENTATION LAYER                               │
│         implementations/bigbrotr/ (YAML configs, SQL schemas)           │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ Uses
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         SERVICE LAYER                                   │
│   src/services/ (Initializer, Finder, Monitor, Synchronizer)            │
│   Status: 4 implemented, 2 stubs (API, DVM)                             │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ Leverages
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          CORE LAYER                                     │
│          src/core/ (Pool, Brotr, BaseService, Logger)                   │
└─────────────────────────────────────────────────────────────────────────┘
```

### Core Components

| Component | Purpose | Lines |
|-----------|---------|-------|
| **Pool** | PostgreSQL connection pooling with asyncpg, retry logic, health checks | ~410 |
| **Brotr** | High-level database interface with stored procedure wrappers | ~430 |
| **BaseService** | Abstract base class with lifecycle, state persistence, factory methods | ~200 |
| **Logger** | Structured logging wrapper with key=value formatting | ~50 |

### Design Patterns

| Pattern | Application |
|---------|-------------|
| Dependency Injection | Services receive `Brotr` instance at construction |
| Composition | `Brotr` HAS-A `Pool` |
| Template Method | `BaseService.run_forever()` calls abstract `run()` |
| Factory Method | `from_yaml()`, `from_dict()` for flexible instantiation |
| Context Manager | Automatic resource cleanup with `async with` |

### Implementation Layer

The `implementations/` directory contains deployment-specific configurations. The default implementation is `bigbrotr/`:

```
implementations/bigbrotr/
├── yaml/
│   ├── core/brotr.yaml         # Database connection, pool settings
│   └── services/               # Service-specific configs
├── postgres/
│   └── init/                   # SQL schema files (00-99)
├── data/
│   └── seed_relays.txt         # Initial relay URLs
├── docker-compose.yaml         # Container orchestration
├── Dockerfile                  # Application container
└── .env.example                # Environment template
```

**Why separate implementations?** This structure allows:
- Different database configurations (local dev vs production)
- Custom SQL schemas (e.g., additional indexes, partitioning)
- Alternative seed data sources
- Multiple deployment targets from the same codebase

To create a custom implementation, copy `implementations/bigbrotr/` and modify the YAML/SQL files as needed. The core and service layers remain unchanged.

---

## Quick Start

### Prerequisites

- Python 3.9+
- Docker & Docker Compose
- Git

### Setup

```bash
# Clone repository
git clone https://github.com/yourusername/bigbrotr.git
cd bigbrotr

# Configure environment
cp implementations/bigbrotr/.env.example implementations/bigbrotr/.env
# Edit .env and set DB_PASSWORD

# Start all services
cd implementations/bigbrotr
docker-compose up -d

# Check logs
docker-compose logs -f initializer
docker-compose logs -f finder
```

### What Happens

1. **PostgreSQL** starts with schema from `postgres/init/` scripts
2. **PGBouncer** provides connection pooling
3. **Tor** proxy enables .onion relay support (optional)
4. **Initializer** verifies schema and seeds ~8,800 relay URLs
5. **Finder** discovers new relays from nostr.watch APIs
6. **Monitor** checks relay health (NIP-11/NIP-66)
7. **Synchronizer** collects events from readable relays

---

## Installation

### Docker Compose (Recommended)

```bash
cd implementations/bigbrotr
cp .env.example .env
nano .env  # Set DB_PASSWORD

docker-compose up -d

# Verify
docker-compose exec postgres psql -U admin -d bigbrotr -c "\dt"
```

### Manual Installation

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt  # For development

# Set environment
export DB_PASSWORD=your_secure_password

# Run services (from implementations/bigbrotr/)
cd implementations/bigbrotr
python -m services initializer
python -m services finder
python -m services monitor
python -m services synchronizer
```

### Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `asyncpg` | 0.30.0 | Async PostgreSQL driver |
| `aiohttp` | 3.13.2 | Async HTTP client |
| `aiohttp-socks` | 0.10.1 | SOCKS5 proxy for Tor |
| `aiomultiprocess` | 0.9.1 | Multicore async processing |
| `pydantic` | 2.10.4 | Configuration validation |
| `PyYAML` | 6.0.2 | YAML parsing |
| `nostr-tools` | 1.4.1 | Nostr protocol library |

---

## Services

### Overview

| Service | Status | Description | Default Interval |
|---------|--------|-------------|------------------|
| **Initializer** | Functional | Database bootstrap, schema verification | One-shot |
| **Finder** | Partial | Relay discovery from APIs | 1 hour |
| **Monitor** | Functional | Relay health checks (NIP-11/NIP-66) | 1 hour |
| **Synchronizer** | Functional | Event collection with multicore | 15 min |
| **API** | Not implemented | REST endpoints (stub only) | - |
| **DVM** | Not implemented | NIP-90 Data Vending Machine (stub only) | - |

### Initializer

**Purpose**: Database bootstrap and verification (one-shot)

**What it does**:
- Verifies PostgreSQL extensions (pgcrypto, btree_gin)
- Checks all tables, procedures, and views exist
- Seeds relay URLs from `data/seed_relays.txt` (~8,865 relays)

```bash
python -m services initializer
```

### Finder

**Purpose**: Relay URL discovery

**Implemented**:
- Fetches relay lists from nostr.watch APIs
- Validates URLs with nostr-tools
- Inserts discovered relays into database

**NOT Implemented** (TODO in code):
- `_find_from_events()` - Scanning stored events for relay hints

```bash
python -m services finder
python -m services finder --log-level DEBUG
```

### Monitor

**Purpose**: Relay health and capability assessment

**What it does**:
- Fetches NIP-11 relay information documents
- Tests NIP-66 capabilities (open, read, write) with RTT measurements
- Supports Tor proxy for .onion relays
- Stores results in `relay_metadata` with NIP-11/NIP-66 deduplication

```bash
python -m services monitor
# With NIP-66 write tests (requires Nostr key):
MONITOR_PRIVATE_KEY=<hex> python -m services monitor
```

### Synchronizer

**Purpose**: Event collection from relays

**Features**:
- Multicore processing via `aiomultiprocess`
- Time-window stack algorithm for handling large event volumes
- Per-relay override settings (e.g., extended timeouts for high-traffic relays)
- Network-specific timeouts (clearnet vs Tor)
- Incremental sync with per-relay state tracking

```bash
python -m services synchronizer
```

---

## Configuration

### File Structure

```
implementations/bigbrotr/yaml/
├── core/
│   └── brotr.yaml          # Database pool and Brotr settings
└── services/
    ├── initializer.yaml    # Schema verification, seed file path
    ├── finder.yaml         # API sources, intervals
    ├── monitor.yaml        # Timeouts, concurrency, Tor config
    ├── synchronizer.yaml   # Filters, timeouts, multicore settings
    ├── api.yaml            # Empty (not implemented)
    └── dvm.yaml            # Empty (not implemented)
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DB_PASSWORD` | Yes | PostgreSQL password |
| `MONITOR_PRIVATE_KEY` | No | Nostr private key for NIP-66 write tests |

### Example: Synchronizer Configuration

```yaml
# yaml/services/synchronizer.yaml
interval: 900.0  # 15 minutes between cycles

tor:
  enabled: true
  host: "tor"
  port: 9050

filter:
  kinds: null      # null = all kinds
  limit: 500       # Events per request

timeouts:
  clearnet:
    request: 30.0
    relay: 1800.0  # 30 min max per relay
  tor:
    request: 60.0
    relay: 3600.0  # 60 min max for Tor relays

concurrency:
  max_parallel: 10
  max_processes: 1  # Set >1 for multicore

# Per-relay overrides
overrides:
  - url: "wss://relay.damus.io"
    timeouts:
      request: 60.0
      relay: 7200.0  # 2 hours for high-traffic relay
```

---

## Database Schema

### Tables

| Table | Purpose |
|-------|---------|
| `relays` | Registry of known relay URLs with network type |
| `events` | Nostr events (BYTEA IDs for 50% space savings) |
| `events_relays` | Junction table tracking event provenance per relay |
| `nip11` | Deduplicated NIP-11 documents (content-addressed) |
| `nip66` | Deduplicated NIP-66 test results (content-addressed) |
| `relay_metadata` | Time-series metadata snapshots |
| `service_state` | Service state persistence (JSONB) |

### Views

| View | Purpose |
|------|---------|
| `relay_metadata_latest` | Latest metadata per relay with NIP-11/NIP-66 joins |
| `events_statistics` | Global event counts, category breakdown, time metrics |
| `relays_statistics` | Per-relay event counts and average RTT |
| `kind_counts_total` | Event counts by kind |
| `kind_counts_by_relay` | Event counts by kind per relay |
| `pubkey_counts_total` | Event counts by public key |
| `pubkey_counts_by_relay` | Event counts by pubkey per relay |

### Stored Procedures

| Procedure | Purpose |
|-----------|---------|
| `insert_event` | Atomic insert of event + relay + junction record |
| `insert_relay` | Idempotent relay insertion |
| `insert_relay_metadata` | Insert with automatic NIP-11/NIP-66 deduplication |
| `delete_orphan_events` | Cleanup events without relay associations |
| `delete_orphan_nip11` | Cleanup unreferenced NIP-11 records |
| `delete_orphan_nip66` | Cleanup unreferenced NIP-66 records |

### SQL Initialization Order

```
00_extensions.sql       # pgcrypto, btree_gin
01_utility_functions.sql # tags_to_tagvalues, hash functions
02_tables.sql           # All tables
03_indexes.sql          # Performance indexes
04_integrity_functions.sql # Orphan cleanup functions
05_procedures.sql       # insert_event, insert_relay, etc.
06_views.sql            # Statistics and metadata views
99_verify.sql           # Schema validation notice
```

---

## Development

### Project Structure

```
bigbrotr/
├── src/
│   ├── core/                       # Foundation layer (~1,080 lines)
│   │   ├── pool.py                 # PostgreSQL connection pool
│   │   ├── brotr.py                # Database interface
│   │   ├── base_service.py         # Abstract service base
│   │   └── logger.py               # Structured logging
│   │
│   └── services/                   # Service layer (~2,040 lines)
│       ├── __main__.py             # CLI entry point
│       ├── initializer.py          # Database bootstrap
│       ├── finder.py               # Relay discovery
│       ├── monitor.py              # Health monitoring
│       ├── synchronizer.py         # Event sync
│       ├── api.py                  # NOT IMPLEMENTED (stub)
│       └── dvm.py                  # NOT IMPLEMENTED (stub)
│
├── implementations/bigbrotr/       # Primary implementation
│   ├── yaml/                       # Configuration files
│   ├── postgres/init/              # SQL schema (8 files)
│   ├── data/seed_relays.txt        # 8,865 seed relay URLs
│   ├── docker-compose.yaml         # Container orchestration
│   ├── Dockerfile                  # Multi-stage build
│   └── .env.example                # Environment template
│
├── tests/unit/                     # Unit tests (~3,500 lines)
├── requirements.txt                # Runtime dependencies
└── requirements-dev.txt            # Development dependencies
```

### Running Tests

```bash
source .venv/bin/activate

# Run all tests
pytest tests/unit/ -v

# With coverage
pytest tests/unit/ --cov=src --cov-report=html

# Specific test file
pytest tests/unit/test_synchronizer.py -v

# Pattern matching
pytest -k "health_check" -v
```

### Adding a New Service

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
        # Service logic here
        pass
```

2. Create `yaml/services/myservice.yaml`
3. Register in `src/services/__main__.py` (add to `SERVICE_REGISTRY`)
4. Export from `src/services/__init__.py`

### Git Workflow

- **Main branch**: `main` (stable)
- **Development branch**: `develop` (active work)
- **Commit style**: Conventional commits (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`)

---

## Known Limitations & TODOs

### Code TODOs

1. **Finder** (`src/services/finder.py:141-142`):
   ```python
   async def _find_from_events(self) -> None:
       """Discover relay URLs from database events."""
       # TODO: Implement event scanning logic
       pass
   ```

2. **API Service** (`src/services/api.py`): Stub file, not implemented

3. **DVM Service** (`src/services/dvm.py`): Stub file, not implemented

### Infrastructure TODOs

- **Database Backup**: No backup/restore strategy implemented
- **Integration Tests**: Only unit tests exist
- **Query Optimization**: Views like `relays_statistics` may be slow on large datasets (uses window functions over last 10 measurements)
- **Index Tuning**: May need additional indexes based on actual query patterns at scale
- **Health Endpoints**: No HTTP health check endpoints for container orchestration

### Known Issues

- No rate limiting on API fetch in Finder (relies on `delay_between_requests` config)
- `pubkey_counts_by_relay` and `kind_counts_by_relay` views can be expensive on large datasets

---

## Roadmap

### Phase 1 (Current)
- [x] Core layer (Pool, Brotr, BaseService, Logger)
- [x] Initializer service
- [x] Finder service (API discovery)
- [x] Monitor service
- [x] Synchronizer service with multicore
- [x] Docker Compose deployment
- [x] Unit tests (174 passing)

### Phase 2 (Next)
- [ ] Finder: Implement event scanning for relay discovery
- [ ] Database backup strategy (pg_dump scripts, WAL archiving)
- [ ] Integration tests with real database
- [ ] Query/index optimization for scale
- [ ] Health check endpoints

### Phase 3 (Future)
- [ ] API service: REST endpoints with OpenAPI docs
- [ ] DVM service: NIP-90 Data Vending Machine
- [ ] Metrics export (Prometheus)
- [ ] Admin dashboard

---

## Contributing

1. Fork the repository
2. Create a feature branch from `develop`
3. Write tests for new functionality
4. Ensure all tests pass: `pytest tests/unit/ -v`
5. Submit a pull request to `main`

### Code Standards

- Type hints required for all public interfaces
- Docstrings for classes and public methods
- Pydantic models for all configuration
- Unit tests for new features

---

## License

**TBD** - License to be determined.

---

<p align="center">
  <strong>Built for the Nostr ecosystem</strong>
</p>

<p align="center">
  <a href="https://nostr.com">Learn about Nostr</a> •
  <a href="https://github.com/nostr-protocol/nips">NIPs Repository</a>
</p>
