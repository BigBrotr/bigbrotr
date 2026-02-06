<p align="center">
  <img src="https://img.shields.io/badge/version-3.0.2-blue?style=for-the-badge" alt="Version">
  <img src="https://img.shields.io/badge/python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/postgresql-16+-4169E1?style=for-the-badge&logo=postgresql&logoColor=white" alt="PostgreSQL">
  <img src="https://img.shields.io/badge/docker-ready-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker">
  <img src="https://img.shields.io/badge/license-MIT-green?style=for-the-badge" alt="License">
</p>

<h1 align="center">BigBrotr</h1>

<p align="center">
  <strong>A Modular Nostr Data Archiving and Monitoring System</strong>
</p>

---

## Overview

BigBrotr is a production-ready system for archiving and monitoring the [Nostr protocol](https://nostr.com) ecosystem. Built with Python and PostgreSQL, it provides relay discovery, health monitoring, and event synchronization across clearnet and overlay networks.

### Key Features

- **Relay Discovery** -- Automatically discover Nostr relays from public APIs and seed lists
- **Health Monitoring** -- Continuous NIP-11 and NIP-66 compliance testing with RTT measurements
- **Event Synchronization** -- High-performance multicore event collection with incremental sync
- **Multi-Network Support** -- Clearnet, Tor (.onion), I2P (.i2p), and Lokinet (.loki) relay connectivity
- **Data Deduplication** -- Content-addressed storage for NIP-11/NIP-66 documents (SHA-256)
- **Prometheus Metrics** -- Built-in metrics server for Grafana dashboards
- **SQL Analytics** -- Pre-built views for statistics, event analysis, and relay metrics
- **Docker Ready** -- Complete containerized deployment with PostgreSQL, Prometheus, Grafana, and Tor

### Design Principles

| Principle | Description |
|-----------|-------------|
| **Four-Layer Architecture** | Implementation > Services > Core > Utils > Models |
| **Dependency Injection** | Services receive database interface via constructor |
| **Configuration-Driven** | YAML configuration with Pydantic validation |
| **Type Safety** | Full type hints with strict mypy checking |
| **Async-First** | Built on asyncio, asyncpg, and aiohttp |

---

## Quick Start

### Prerequisites

- Python 3.11 or higher
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
docker-compose logs -f seeder
```

### What Happens on First Run

1. **PostgreSQL** initializes with the complete database schema
2. **Tor proxy** enables .onion relay connectivity (optional)
3. **Prometheus** starts collecting metrics from all services
4. **Grafana** provides monitoring dashboards (http://localhost:3000)
5. **Seeder** seeds 8,865 relay URLs as candidates for validation
6. **Finder** begins discovering additional relays from nostr.watch APIs
7. **Validator** tests candidate relays and promotes valid ones
8. **Monitor** starts health checking relays (NIP-11/NIP-66)
9. **Synchronizer** collects events from readable relays using multicore processing

---

## Architecture

BigBrotr uses a four-layer architecture that separates concerns and enables flexibility:

```
+=============================================================================+
|                         IMPLEMENTATION LAYER                                |
|                      implementations/bigbrotr/                              |
|                 (YAML configs, SQL schemas, Docker, seed data)              |
+=====================================+=======================================+
                                      |
                                      v
+=============================================================================+
|                           SERVICE LAYER                                     |
|                          src/services/                                      |
+-----------------------------------------------------------------------------+
|                                                                             |
|  +--------+  +--------+  +-----------+  +---------+  +--------------+       |
|  | Seeder |  | Finder |  | Validator |  | Monitor |  | Synchronizer |       |
|  | (seed) |  |(disco) |  |  (test)   |  |(health) |  |   (events)   |       |
|  +--------+  +--------+  +-----------+  +---------+  +--------------+       |
|                                                                             |
+=====================================+=======================================+
                                      |
                                      v
+=============================================================================+
|                            CORE LAYER                                       |
|                           src/core/                                         |
+-----------------------------------------------------------------------------+
|                                                                             |
|  +--------+     +--------+     +-------------+     +---------+  +--------+  |
|  |  Pool  |---->| Brotr  |     | BaseService |     | Metrics |  | Logger |  |
|  +--------+     +--------+     +-------------+     +---------+  +--------+  |
|                                                                             |
+=====================================+=======================================+
                                      |
                                      v
+=============================================================================+
|                           UTILS LAYER                                       |
|                           src/utils/                                        |
+-----------------------------------------------------------------------------+
|                                                                             |
|  NetworkConfig, KeysConfig, BatchProgress, create_client, load_yaml         |
|                                                                             |
+=====================================+=======================================+
                                      |
                                      v
+=============================================================================+
|                          MODELS LAYER                                       |
|                          src/models/                                        |
+-----------------------------------------------------------------------------+
|                                                                             |
|  Event, Relay, EventRelay, Metadata, Nip11, Nip66, RelayMetadata            |
|  NetworkType, MetadataType                                                  |
|                                                                             |
+=============================================================================+
```

### Core Components

| Component | Description | Key Features |
|-----------|-------------|--------------|
| **Pool** | PostgreSQL connection pooling | Async pooling with asyncpg, retry with backoff, health checks |
| **Brotr** | High-level database interface | Stored procedure wrappers, bulk array operations, configurable timeouts |
| **BaseService** | Abstract service base class | State persistence, lifecycle management, Prometheus metrics integration |
| **MetricsServer** | Prometheus metrics endpoint | HTTP /metrics endpoint, per-service gauges and counters |
| **Logger** | Structured logging | Key=value formatting, configurable levels |

### Services

| Service | Status | Description |
|---------|--------|-------------|
| **Seeder** | Complete | Relay seeding for validation |
| **Finder** | Complete | Relay URL discovery from external APIs and database events |
| **Validator** | Complete | Candidate relay testing with streaming architecture and multi-network support |
| **Monitor** | Complete | NIP-11/NIP-66 health monitoring with SSL validation and geolocation |
| **Synchronizer** | Complete | Multicore event synchronization with incremental sync |
| **API** | Planned | REST API endpoints with OpenAPI documentation |
| **DVM** | Planned | NIP-90 Data Vending Machine protocol support |

For detailed architecture documentation, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Implementations

The four-layer architecture enables multiple deployment configurations from the same codebase.

### BigBrotr (Full-Featured)

The default implementation with complete event storage:

| Feature | Description |
|---------|-------------|
| **Full Event Storage** | Stores all event fields including tags and content |
| **Multi-Network** | Clearnet + Tor enabled, I2P/Lokinet available |
| **High Concurrency** | 10 parallel connections, 4 worker processes |
| **Monitoring** | Prometheus (9090), Grafana (3000), PostgreSQL (5432), PGBouncer (6432), Tor (9050) |

```bash
cd implementations/bigbrotr
docker-compose up -d
```

### LilBrotr (Lightweight)

A lightweight implementation that indexes all events but omits storage-heavy fields:

| Feature | Description |
|---------|-------------|
| **Essential Metadata** | Stores id, pubkey, created_at, kind, sig (omits tags/content, saves ~60% disk) |
| **Clearnet Only** | Overlay networks disabled by default |
| **Lower Concurrency** | 5 parallel connections for reduced resource usage |
| **Monitoring** | Prometheus (9091), Grafana (3001), PostgreSQL (5433), PGBouncer (6433) |

```bash
cd implementations/lilbrotr
docker-compose up -d
```

### Creating Custom Implementations

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

### Seeder

**Purpose**: Relay seeding for validation (one-shot)

The Seeder runs once at startup to seed the database:

- Parses and validates relay URLs from `static/seed_relays.txt`
- Stores URLs as candidates in `service_data` table
- Network type (clearnet/tor) is auto-detected from URL

```bash
python -m services seeder
```

### Finder

**Purpose**: Continuous relay URL discovery

The Finder service discovers new Nostr relays:

- Fetches relay lists from configurable API sources (default: nostr.watch)
- Scans stored events for relay URLs (NIP-65 relay lists, kind 2/3 events)
- Validates URLs and stores as candidates for Validator
- Runs continuously with configurable intervals

```bash
python -m services finder
python -m services finder --log-level DEBUG
```

### Validator

**Purpose**: Test and validate candidate relay URLs

The Validator service tests candidates discovered by Finder and Seeder:

- Tests WebSocket connectivity for each candidate
- Supports Tor proxy for .onion addresses
- Promotes successful candidates to `relays` table
- Tracks failed attempts and removes persistently failing candidates
- Uses probabilistic selection based on retry count

```bash
python -m services validator
```

### Monitor

**Purpose**: Relay health and capability assessment

The Monitor service continuously evaluates relay health:

- Fetches NIP-11 relay information documents
- Tests NIP-66 capabilities (openable, readable, writable)
- Measures round-trip times (RTT) for all operations
- Validates SSL certificates and performs geolocation
- Deduplicates NIP-11/NIP-66 documents via content hashing
- Supports Tor proxy for .onion relays

```bash
python -m services monitor

# With NIP-66 write tests (requires Nostr private key)
PRIVATE_KEY=<hex_private_key> python -m services monitor
```

### Synchronizer

**Purpose**: High-performance event collection from relays

The Synchronizer is the core data collection engine:

- **Multicore Processing**: Uses `aiomultiprocess` for parallel relay processing
- **Time-Window Stack Algorithm**: Handles large event volumes efficiently
- **Incremental Sync**: Tracks per-relay timestamps for efficient updates
- **Per-Relay Overrides**: Custom timeouts for high-traffic relays
- **Tor Proxy Support**: SOCKS5 proxy for .onion relay synchronization
- **Graceful Shutdown**: Clean worker process termination

```bash
python -m services synchronizer
```

For service configuration details, see [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

---

## Configuration

BigBrotr uses a YAML-driven configuration system with Pydantic validation.

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DB_PASSWORD` | **Yes** | PostgreSQL database password |
| `PRIVATE_KEY` | **Yes** for Monitor/Sync | Nostr private key (hex or nsec) for NIP-66 write tests and NIP-42 auth |
| `GRAFANA_PASSWORD` | No | Grafana admin password (defaults to admin) |

### Configuration Files

```
implementations/bigbrotr/yaml/
├── core/
│   └── brotr.yaml              # Database pool and connection settings
└── services/
    ├── seeder.yaml             # Seed file path
    ├── finder.yaml             # API sources, discovery intervals
    ├── validator.yaml          # Validation settings, Tor proxy
    ├── monitor.yaml            # Health check settings, Tor config
    └── synchronizer.yaml       # Sync filters, timeouts, concurrency
```

For complete configuration documentation, see [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

---

## Database

BigBrotr uses PostgreSQL 16+ with PGBouncer connection pooling and asyncpg async driver.

### Schema Overview

| Table | Purpose |
|-------|---------|
| `relays` | Registry of validated relay URLs with network type (clearnet/tor) |
| `events` | Nostr events with BYTEA IDs for 50% space savings |
| `events_relays` | Junction table tracking event provenance per relay |
| `metadata` | Deduplicated NIP-11/NIP-66 documents (content-addressed by SHA-256) |
| `relay_metadata` | Time-series metadata snapshots linking relays to metadata records |
| `service_data` | Per-service operational data (candidates, cursors, checkpoints) |

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

### Stored Functions

| Function | Purpose |
|----------|---------|
| `relays_insert` | Bulk insert relays (array parameters) |
| `events_insert` | Bulk insert events (array parameters) |
| `metadata_insert` | Bulk insert metadata with content-addressed deduplication |
| `events_relays_insert_cascade` | Atomic bulk insert of events + relays + junctions |
| `relay_metadata_insert_cascade` | Atomic bulk insert of relays + metadata + junctions |
| `service_data_upsert` | Bulk upsert service operational data |
| `service_data_get` | Retrieve service data with optional key filter |
| `service_data_delete` | Bulk delete service data records |
| `orphan_events_delete` | Cleanup events without relay associations |
| `orphan_metadata_delete` | Cleanup unreferenced metadata records |

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
python -m services seeder
python -m services finder &
python -m services validator &
python -m services monitor &
python -m services synchronizer &
```

---

## Development

### Setup Development Environment

```bash
git clone https://github.com/bigbrotr/bigbrotr.git
cd bigbrotr

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt -r requirements-dev.txt
pre-commit install
```

### Running Tests

```bash
pytest tests/ -v                             # All tests
pytest tests/ --cov=src --cov-report=html    # With coverage
pytest tests/unit/services/test_synchronizer.py -v  # Single file
pytest -k "health_check" -v                  # Pattern match
```

### Code Quality

```bash
ruff check src/ tests/      # Linting
ruff format src/ tests/      # Formatting
mypy src/                    # Type checking
pre-commit run --all-files   # All pre-commit hooks
```

### Project Structure

```
bigbrotr/
├── src/
│   ├── __init__.py
│   ├── core/                          # Foundation layer
│   │   ├── __init__.py
│   │   ├── pool.py                    # PostgreSQL connection pool
│   │   ├── brotr.py                   # Database interface
│   │   ├── service.py                 # Abstract service base
│   │   ├── metrics.py                 # Prometheus metrics server
│   │   └── logger.py                  # Structured key=value logging
│   │
│   ├── utils/                         # Shared utilities
│   │   ├── __init__.py
│   │   ├── dns.py                     # DNS resolution
│   │   ├── keys.py                    # Nostr key management
│   │   ├── network.py                 # Network detection and proxy config
│   │   ├── progress.py                # Batch progress tracking
│   │   ├── transport.py               # HTTP/WebSocket transport helpers
│   │   └── yaml.py                    # YAML loading with env var support
│   │
│   ├── models/                        # Data models
│   │   ├── __init__.py
│   │   ├── event.py                   # Nostr event model
│   │   ├── relay.py                   # Relay URL model
│   │   ├── event_relay.py             # Event-relay junction
│   │   ├── metadata.py                # Content-addressed metadata
│   │   ├── relay_metadata.py          # Relay-metadata junction
│   │   └── nips/                      # NIP model subpackages
│   │       ├── base.py                # Base NIP model
│   │       ├── parsing.py             # NIP data parsing utilities
│   │       ├── nip11/                 # NIP-11 relay information
│   │       └── nip66/                 # NIP-66 monitoring data
│   │
│   └── services/                      # Service layer
│       ├── __init__.py
│       ├── __main__.py                # CLI entry point
│       ├── seeder.py                  # Relay seeding
│       ├── finder.py                  # Relay discovery
│       ├── validator.py               # Relay validation
│       ├── monitor.py                 # Health monitoring
│       └── synchronizer.py            # Event sync
│
├── implementations/
│   ├── bigbrotr/                      # Full-featured implementation
│   │   ├── yaml/                      # Configuration files
│   │   ├── postgres/init/             # SQL schema (full storage)
│   │   ├── static/seed_relays.txt     # 8,865 seed relay URLs
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
│   ├── unit/                          # Unit tests
│   │   ├── core/                      # Core layer tests
│   │   ├── utils/                     # Utils layer tests
│   │   ├── models/                    # Models tests (incl. nips/)
│   │   └── services/                  # Service layer tests
│   └── integration/                   # Integration tests (planned)
│
├── docs/                              # Documentation
│   ├── OVERVIEW.md
│   ├── ARCHITECTURE.md
│   ├── CONFIGURATION.md
│   ├── DATABASE.md
│   ├── DEVELOPMENT.md
│   └── TECHNICAL.md
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
| **Python** | 3.11+ | Primary programming language |
| **PostgreSQL** | 16+ | Primary data storage |
| **asyncpg** | 0.30.0 | Async PostgreSQL driver |
| **Pydantic** | 2.10.4 | Configuration validation and serialization |
| **aiohttp** | 3.13.2 | Async HTTP client |
| **aiohttp-socks** | 0.10.1 | SOCKS5 proxy support for overlay networks |
| **aiomultiprocess** | 0.9.1 | Multicore async processing |
| **nostr-sdk** | 0.39.0 | Nostr protocol library (rust-nostr PyO3 bindings) |
| **prometheus-client** | latest | Metrics collection and exposition |
| **PyYAML** | 6.0.2 | YAML configuration parsing |
| **Prometheus** | latest | Metrics storage and querying |
| **Grafana** | latest | Metrics visualization dashboards |
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

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines.

Quick start:

1. Fork the repository
2. Create a feature branch from `develop`
3. Write tests for new functionality
4. Ensure all tests pass: `pytest tests/ -v`
5. Run code quality checks: `pre-commit run --all-files`
6. Submit a pull request to `develop`

For security issues, see [SECURITY.md](SECURITY.md).

---

## Roadmap

### Completed

- [x] Core layer (Pool, Brotr, BaseService, MetricsServer, Logger)
- [x] Seeder service with relay seeding
- [x] Validator service with streaming architecture and multi-network support
- [x] Finder service with API discovery
- [x] Monitor service with NIP-11/NIP-66 support, SSL validation, geolocation
- [x] Synchronizer service with multicore processing
- [x] Prometheus metrics integration for all services
- [x] Grafana dashboards for monitoring
- [x] Multi-network support (Clearnet, Tor, I2P, Lokinet)
- [x] Docker Compose deployment
- [x] Unit test suite (1776 tests)
- [x] Pre-commit hooks and CI configuration

### Planned

- [ ] API service (REST endpoints with OpenAPI)
- [ ] DVM service (NIP-90 Data Vending Machine)
- [ ] Integration tests with real database
- [ ] Additional Grafana dashboards
- [ ] Database backup automation

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

---

## Links

- [Nostr Protocol](https://nostr.com) -- Learn about Nostr
- [NIPs Repository](https://github.com/nostr-protocol/nips) -- Nostr Implementation Possibilities
- [NIP-11](https://github.com/nostr-protocol/nips/blob/master/11.md) -- Relay Information Document
- [NIP-66](https://github.com/nostr-protocol/nips/blob/master/66.md) -- Relay Discovery and Monitoring
