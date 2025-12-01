<p align="center">
  <img src="https://img.shields.io/badge/version-2.0.0-blue?style=for-the-badge" alt="Version">
  <img src="https://img.shields.io/badge/python-3.9+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/postgresql-16+-4169E1?style=for-the-badge&logo=postgresql&logoColor=white" alt="PostgreSQL">
  <img src="https://img.shields.io/badge/docker-ready-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker">
  <img src="https://img.shields.io/badge/license-MIT-green?style=for-the-badge" alt="License">
</p>

<h1 align="center">BigBrotr</h1>

<p align="center">
  <strong>A Modular Nostr Data Archiving and Monitoring System</strong>
</p>

<p align="center">
  <em>Enterprise-grade infrastructure for indexing, monitoring, and analyzing the Nostr protocol ecosystem</em>
</p>

---

## Overview

BigBrotr is a production-ready, modular system for archiving and monitoring the [Nostr protocol](https://nostr.com) ecosystem. Built with Python and PostgreSQL, it provides comprehensive tools for relay discovery, health monitoring, and event synchronization across both clearnet and Tor networks.

### Key Features

- **Relay Discovery** - Automatically discover Nostr relays from public APIs and seed lists
- **Health Monitoring** - Continuous NIP-11 and NIP-66 compliance testing with RTT measurements
- **Event Synchronization** - High-performance multicore event collection with incremental sync
- **Tor Network Support** - Full support for .onion relay addresses via SOCKS5 proxy
- **Data Deduplication** - Content-addressed storage for NIP-11/NIP-66 documents
- **SQL Analytics** - Pre-built views for statistics, event analysis, and relay metrics
- **Docker Ready** - Complete containerized deployment with PostgreSQL, PGBouncer, and Tor

### Design Philosophy

| Principle | Implementation |
|-----------|----------------|
| **Three-Layer Architecture** | Core (reusable) -> Services (modular) -> Implementation (config-driven) |
| **Dependency Injection** | Services receive database interface via constructor for testability |
| **Configuration-Driven** | YAML configuration with Pydantic validation, minimal hardcoding |
| **Type Safety** | Full type hints with strict mypy checking throughout codebase |
| **Async-First** | Built on asyncio, asyncpg, and aiohttp for maximum concurrency |

---

## Quick Start

### Prerequisites

- Python 3.9 or higher
- Docker and Docker Compose
- Git

### Installation

```bash
# Clone repository
git clone https://github.com/bigbrotr/bigbrotr.git
cd bigbrotr

# Configure environment
cd implementations/bigbrotr
cp .env.example .env
nano .env  # Set DB_PASSWORD (required)

# Start all services
docker-compose up -d

# Verify deployment
docker-compose logs -f initializer
```

### What Happens on First Run

1. **PostgreSQL** initializes with the complete database schema
2. **PGBouncer** provides connection pooling in transaction mode
3. **Tor proxy** enables .onion relay connectivity (optional)
4. **Initializer** verifies the schema and seeds 8,865 relay URLs
5. **Finder** begins discovering additional relays from nostr.watch APIs
6. **Monitor** starts health checking relays (NIP-11/NIP-66)
7. **Synchronizer** collects events from readable relays using multicore processing

---

## Architecture

BigBrotr uses a three-layer architecture that separates concerns and enables flexibility:

```
+-----------------------------------------------------------------------------+
|                           IMPLEMENTATION LAYER                               |
|              implementations/bigbrotr/                                       |
|              (YAML configs, SQL schemas, Docker, seed data)                  |
+----------------------------------+------------------------------------------+
                                   | Uses
                                   v
+-----------------------------------------------------------------------------+
|                             SERVICE LAYER                                    |
|              src/services/                                                   |
|                                                                              |
|    Initializer    Finder    Monitor    Synchronizer    [API]    [DVM]       |
|       Done         Done      Done         Done         Planned  Planned     |
+----------------------------------+------------------------------------------+
                                   | Leverages
                                   v
+-----------------------------------------------------------------------------+
|                              CORE LAYER                                      |
|              src/core/                                                       |
|                                                                              |
|              Pool          Brotr        BaseService        Logger            |
|         (Connection    (Database     (Service Base    (Structured           |
|           Pooling)     Interface)       Class)         Logging)             |
+-----------------------------------------------------------------------------+
```

### Core Components

| Component | Description | Key Features |
|-----------|-------------|--------------|
| **Pool** | PostgreSQL connection pooling | Async pooling, retry with backoff, health checks, PGBouncer compatible |
| **Brotr** | High-level database interface | Stored procedure wrappers, batch operations, hex-to-BYTEA conversion |
| **BaseService** | Abstract service base class | State persistence, lifecycle management, factory methods |
| **Logger** | Structured logging wrapper | Key=value formatting, configurable levels |

### Services

| Service | Status | Description |
|---------|--------|-------------|
| **Initializer** | Complete | Database bootstrap, schema verification, relay seeding |
| **Finder** | Complete | Relay discovery from external APIs |
| **Monitor** | Complete | NIP-11/NIP-66 health monitoring with Tor support |
| **Synchronizer** | Complete | Multicore event synchronization with incremental sync |
| **API** | Planned | REST API endpoints with OpenAPI documentation |
| **DVM** | Planned | NIP-90 Data Vending Machine protocol support |

For detailed architecture documentation, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Implementations

The three-layer architecture enables multiple deployment configurations from the same codebase. Two implementations are included:

### BigBrotr (Full-Featured)

The default implementation with complete event storage:

| Feature | Description |
|---------|-------------|
| **Full Event Storage** | Stores all event fields including tags and content |
| **Tor Support** | Full .onion relay connectivity |
| **High Concurrency** | 10 parallel connections, 10 worker processes |
| **Ports** | PostgreSQL: 5432, PGBouncer: 6432, Tor: 9050 |

```bash
cd implementations/bigbrotr
docker-compose up -d
```

### LilBrotr (Lightweight)

A lightweight implementation that indexes all events but omits storage-heavy fields:

| Feature | Description |
|---------|-------------|
| **Essential Metadata** | Stores id, pubkey, created_at, kind, sig (omits tags/content, saves ~60% disk space) |
| **Clearnet Only** | Tor disabled by default |
| **Lower Concurrency** | 5 parallel connections for reduced resource usage |
| **Different Ports** | PostgreSQL: 5433, PGBouncer: 6433, Tor: 9051 |

```bash
cd implementations/lilbrotr
docker-compose up -d
```

### Creating Custom Implementations

You can create your own implementation for specific use cases:

```bash
# Copy an existing implementation
cp -r implementations/bigbrotr implementations/myimpl

# Customize configuration
nano implementations/myimpl/yaml/services/synchronizer.yaml

# Modify SQL schema if needed
nano implementations/myimpl/postgres/init/02_tables.sql

# Deploy
cd implementations/myimpl
docker-compose up -d
```

Common customization scenarios:
- **Archive-only**: Store only specific event kinds
- **Single-relay**: Monitor/sync from a single relay
- **Metrics-only**: Store only relay metadata, no events
- **Regional**: Use region-specific seed relays

---

## Services

### Initializer

**Purpose**: Database bootstrap and schema verification (one-shot)

The Initializer runs once at startup to ensure the database is properly configured:

- Verifies PostgreSQL extensions (pgcrypto, btree_gin)
- Validates all tables, procedures, and views exist
- Seeds the database with initial relay URLs from `data/seed_relays.txt`

```bash
# Run manually
python -m services initializer

# Check logs
docker-compose logs initializer
```

### Finder

**Purpose**: Continuous relay URL discovery

The Finder service discovers new Nostr relays:

- Fetches relay lists from configurable API sources (default: nostr.watch)
- Validates URLs using nostr-tools
- Batch inserts discovered relays into the database
- Runs continuously with configurable intervals

```bash
# Run with default config
python -m services finder

# Run with custom config
python -m services finder --config yaml/services/finder.yaml

# Debug mode
python -m services finder --log-level DEBUG
```

**Configuration highlights** (`yaml/services/finder.yaml`):
```yaml
interval: 3600.0  # 1 hour between discovery cycles

api:
  enabled: true
  sources:
    - url: https://api.nostr.watch/v1/online
      enabled: true
      timeout: 30.0
    - url: https://api.nostr.watch/v1/offline
      enabled: true
      timeout: 30.0
```

### Monitor

**Purpose**: Relay health and capability assessment

The Monitor service continuously evaluates relay health:

- Fetches NIP-11 relay information documents
- Tests NIP-66 capabilities (openable, readable, writable)
- Measures round-trip times (RTT) for all operations
- Supports Tor proxy for .onion relays
- Deduplicates NIP-11/NIP-66 documents via content hashing
- Processes relays concurrently with configurable parallelism

```bash
# Run with default config
python -m services monitor

# With NIP-66 write tests (requires Nostr private key)
MONITOR_PRIVATE_KEY=<hex_private_key> python -m services monitor
```

**Configuration highlights** (`yaml/services/monitor.yaml`):
```yaml
interval: 3600.0  # 1 hour between monitoring cycles

tor:
  enabled: true
  host: "tor"
  port: 9050

timeouts:
  clearnet: 30.0  # seconds
  tor: 60.0       # higher timeout for Tor

concurrency:
  max_parallel: 50    # concurrent relay checks
  batch_size: 50      # relays per database batch
```

### Synchronizer

**Purpose**: High-performance event collection from relays

The Synchronizer is the core data collection engine:

- **Multicore Processing**: Uses `aiomultiprocess` for parallel relay processing
- **Time-Window Stack Algorithm**: Handles large event volumes efficiently
- **Incremental Sync**: Tracks per-relay timestamps for efficient updates
- **Per-Relay Overrides**: Custom timeouts for high-traffic relays
- **Network-Aware**: Different timeouts for clearnet vs Tor relays
- **Graceful Shutdown**: Clean worker process termination

```bash
# Run with default config
python -m services synchronizer
```

**Configuration highlights** (`yaml/services/synchronizer.yaml`):
```yaml
interval: 900.0  # 15 minutes between sync cycles

filter:
  kinds: null     # null = all event kinds
  limit: 500      # events per request

timeouts:
  clearnet:
    request: 30.0   # WebSocket timeout
    relay: 1800.0   # 30 min max per relay
  tor:
    request: 60.0
    relay: 3600.0   # 60 min for Tor relays

concurrency:
  max_parallel: 10  # concurrent connections per process
  max_processes: 10 # worker processes

# Per-relay overrides
overrides:
  - url: "wss://relay.damus.io"
    timeouts:
      request: 60.0
      relay: 7200.0  # 2 hours for high-traffic relay
```

---

## Configuration

BigBrotr uses a YAML-driven configuration system with Pydantic validation.

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DB_PASSWORD` | **Yes** | PostgreSQL database password |
| `MONITOR_PRIVATE_KEY` | No | Nostr private key for NIP-66 write tests (hex format) |

### Configuration Files

```
implementations/bigbrotr/yaml/
├── core/
│   └── brotr.yaml              # Database pool and connection settings
└── services/
    ├── initializer.yaml        # Schema verification, seed file path
    ├── finder.yaml             # API sources, discovery intervals
    ├── monitor.yaml            # Health check settings, Tor config
    └── synchronizer.yaml       # Sync filters, timeouts, concurrency
```

For complete configuration documentation, see [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

---

## Database

BigBrotr uses PostgreSQL 16+ with PGBouncer for connection pooling.

### Schema Overview

| Table | Purpose |
|-------|---------|
| `relays` | Registry of known relay URLs with network type (clearnet/tor) |
| `events` | Nostr events with BYTEA IDs for 50% space savings |
| `events_relays` | Junction table tracking event provenance per relay |
| `nip11` | Deduplicated NIP-11 documents (content-addressed) |
| `nip66` | Deduplicated NIP-66 test results (content-addressed) |
| `relay_metadata` | Time-series metadata snapshots |
| `service_state` | Service state persistence (JSONB) |

### Pre-Built Views

| View | Purpose |
|------|---------|
| `relay_metadata_latest` | Latest metadata per relay with NIP-11/NIP-66 joins |
| `events_statistics` | Global event counts, category breakdown, time metrics |
| `relays_statistics` | Per-relay event counts and average RTT |
| `kind_counts_total` | Event counts aggregated by kind |
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

For complete database documentation, see [docs/DATABASE.md](docs/DATABASE.md).

---

## Deployment

### Docker Compose (Recommended)

```bash
cd implementations/bigbrotr

# Configure
cp .env.example .env
nano .env  # Set DB_PASSWORD

# Deploy
docker-compose up -d

# Verify
docker-compose ps
docker-compose logs -f

# Database access
docker-compose exec postgres psql -U admin -d bigbrotr

# Stop
docker-compose down

# Reset (WARNING: deletes all data)
docker-compose down && rm -rf data/postgres
```

### Manual Deployment

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set environment
export DB_PASSWORD=your_secure_password

# Run services (from implementations/bigbrotr/)
cd implementations/bigbrotr
python -m services initializer
python -m services finder &
python -m services monitor &
python -m services synchronizer &
```

For complete deployment documentation, see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

---

## Development

### Setup Development Environment

```bash
# Clone and setup
git clone https://github.com/bigbrotr/bigbrotr.git
cd bigbrotr

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install all dependencies
pip install -r requirements.txt -r requirements-dev.txt

# Install pre-commit hooks
pre-commit install
```

### Running Tests

```bash
# Run all unit tests
pytest tests/unit/ -v

# Run with coverage
pytest tests/unit/ --cov=src --cov-report=html

# Run specific test file
pytest tests/unit/test_synchronizer.py -v

# Run tests matching pattern
pytest -k "health_check" -v
```

### Code Quality

```bash
# Linting
ruff check src/ tests/

# Formatting
ruff format src/ tests/

# Type checking
mypy src/

# Run all pre-commit hooks
pre-commit run --all-files
```

### Project Structure

```
bigbrotr/
├── src/
│   ├── core/                          # Foundation layer
│   │   ├── __init__.py
│   │   ├── pool.py                    # PostgreSQL connection pool
│   │   ├── brotr.py                   # Database interface
│   │   ├── base_service.py            # Abstract service base
│   │   └── logger.py                  # Structured logging
│   │
│   └── services/                      # Service layer
│       ├── __init__.py
│       ├── __main__.py                # CLI entry point
│       ├── initializer.py             # Database bootstrap
│       ├── finder.py                  # Relay discovery
│       ├── monitor.py                 # Health monitoring
│       ├── synchronizer.py            # Event sync
│       ├── api.py                     # REST API (planned)
│       └── dvm.py                     # DVM service (planned)
│
├── implementations/
│   ├── bigbrotr/                      # Full-featured implementation
│   │   ├── yaml/                      # Configuration files
│   │   ├── postgres/init/             # SQL schema (full storage)
│   │   ├── data/seed_relays.txt       # 8,865 seed relay URLs
│   │   ├── docker-compose.yaml
│   │   └── Dockerfile
│   │
│   └── lilbrotr/                      # Lightweight implementation
│       ├── yaml/                      # Minimal config overrides
│       ├── postgres/init/             # SQL schema (no tags/content)
│       ├── docker-compose.yaml
│       └── Dockerfile
│
├── tests/
│   ├── conftest.py                    # Shared fixtures
│   └── unit/                          # Unit tests
│
├── docs/                              # Documentation
│   ├── ARCHITECTURE.md
│   ├── CONFIGURATION.md
│   ├── DATABASE.md
│   ├── DEPLOYMENT.md
│   └── DEVELOPMENT.md
│
├── releases/                          # Release notes
│   ├── v1.0.0.md
│   └── v2.0.0.md
│
├── .github/                           # GitHub configuration
│   ├── workflows/ci.yml               # CI pipeline
│   ├── ISSUE_TEMPLATE/                # Issue templates
│   └── PULL_REQUEST_TEMPLATE.md
│
├── CHANGELOG.md                       # Version history
├── CONTRIBUTING.md                    # Contribution guide
├── SECURITY.md                        # Security policy
├── CODE_OF_CONDUCT.md                 # Code of conduct
├── requirements.txt                   # Runtime dependencies
├── requirements-dev.txt               # Development dependencies
├── pyproject.toml                     # Project configuration
└── README.md
```

For complete development documentation, see [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

---

## Technology Stack

| Technology | Version | Purpose |
|------------|---------|---------|
| **Python** | 3.9+ | Primary programming language |
| **PostgreSQL** | 16+ | Primary data storage |
| **asyncpg** | 0.30.0 | Async PostgreSQL driver |
| **Pydantic** | 2.10.4 | Configuration validation and serialization |
| **aiohttp** | 3.13.2 | Async HTTP client for API calls |
| **aiohttp-socks** | 0.10.1 | SOCKS5 proxy support for Tor |
| **aiomultiprocess** | 0.9.1 | Multicore async processing |
| **nostr-tools** | 1.4.1 | Nostr protocol library |
| **PyYAML** | 6.0.2 | YAML configuration parsing |
| **PGBouncer** | latest | Connection pooling |
| **Docker** | - | Containerization |

---

## Git Workflow

- **Main branch**: `main` (stable releases)
- **Development branch**: `develop` (active development)
- **Feature branches**: `feature/<name>` (from develop)
- **PR target**: `main` (via develop)
- **Commit style**: Conventional commits (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`)

---

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines.

Quick start:

1. Fork the repository
2. Create a feature branch from `develop`
3. Write tests for new functionality
4. Ensure all tests pass: `pytest tests/unit/ -v`
5. Run code quality checks: `pre-commit run --all-files`
6. Submit a pull request to `develop` (or `main` for releases)

For security issues, please see [SECURITY.md](SECURITY.md).

---

## Roadmap

### Completed

- [x] Core layer (Pool, Brotr, BaseService, Logger)
- [x] Initializer service with schema verification
- [x] Finder service with API discovery
- [x] Monitor service with NIP-11/NIP-66 support
- [x] Synchronizer service with multicore processing
- [x] Docker Compose deployment
- [x] Unit test suite (174 tests)
- [x] Pre-commit hooks and CI configuration

### Planned

- [ ] API service (REST endpoints with OpenAPI)
- [ ] DVM service (NIP-90 Data Vending Machine)
- [ ] Integration tests with real database
- [ ] Prometheus metrics export
- [ ] Admin dashboard
- [ ] Database backup automation

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

---

## Links

- [Nostr Protocol](https://nostr.com) - Learn about Nostr
- [NIPs Repository](https://github.com/nostr-protocol/nips) - Nostr Implementation Possibilities
- [NIP-11](https://github.com/nostr-protocol/nips/blob/master/11.md) - Relay Information Document
- [NIP-66](https://github.com/nostr-protocol/nips/blob/master/66.md) - Relay Discovery and Monitoring

---

<p align="center">
  <strong>Built for the Nostr ecosystem</strong>
</p>
