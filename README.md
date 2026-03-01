<p align="center">
  <img src="https://img.shields.io/badge/python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/postgresql-16+-4169E1?style=for-the-badge&logo=postgresql&logoColor=white" alt="PostgreSQL 16+">
  <img src="https://img.shields.io/badge/async-asyncpg-00ADD8?style=for-the-badge" alt="Async">
  <img src="https://img.shields.io/badge/docker-compose-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker">
  <img src="https://img.shields.io/badge/license-MIT-green?style=for-the-badge" alt="MIT License">
  <a href="https://codecov.io/gh/Bigbrotr/bigbrotr"><img src="https://img.shields.io/codecov/c/github/Bigbrotr/bigbrotr?token=LM9D3ABW0L&style=for-the-badge&logo=codecov&logoColor=white&label=coverage" alt="Coverage"></a>
  <a href="https://bigbrotr.github.io/bigbrotr/"><img src="https://img.shields.io/badge/docs-latest-brightgreen?style=for-the-badge&logo=readthedocs&logoColor=white" alt="Documentation"></a>
</p>

<h1 align="center">BigBrotr</h1>

<p align="center">
  <strong>Nostr Relay Discovery, Monitoring, and Event Archiving System</strong>
</p>

<p align="center">
  Discovers relays across clearnet and overlay networks, monitors health with NIP-11/NIP-66 compliance checks, and archives events into PostgreSQL.
</p>

---

## What It Does

BigBrotr runs 8 **independent** async services that continuously map and monitor the Nostr relay ecosystem. Each service runs on its own schedule, reads and writes a shared PostgreSQL database, and has no direct dependency on any other service.

```text
                    ┌──────────────────────────────────────────────────────┐
                    │                    PostgreSQL Database               │
                    │                                                      │
                    │         relay ─── event_relay ─── event              │
                    │         metadata ─── relay_metadata                  │
                    │         service_state     11 materialized views      │
                    └──┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬──┘
                       │      │      │      │      │      │      │      │
                       ▼      ▼      ▼      ▼      ▼      ▼      ▼      ▼
                    Seeder Finder Valid. Monitor Sync. Refresh. Api    Dvm
                       │      │      │      │      │      │      │      │
                       ▼      ▼      ▼      ▼      ▼      │      ▼      ▼
                    seed   HTTP   Relays Relays  Relays (no I/O) HTTP  Nostr
                    file   APIs   (WS)  (NIP-11, (fetch               clients
                                         NIP-66)  events)               │
                                           │                            ▼
                                           ▼                       Nostr Network
                                      Nostr Network               (kind 5050/6050)
                                    (kind 10166/30166)
```

### Services

| Service | Schedule | What it does | Reads | Writes | External I/O |
|---------|----------|-------------|-------|--------|-------------|
| **Seeder** | One-shot | Loads relay URLs from a seed file | -- | relay or service_state (candidates) | Seed file |
| **Finder** | Every 5 min | Discovers relay URLs from event tag values and external APIs | relay, event_relay, service_state | service_state (candidates + cursors) | HTTP (nostr.watch APIs) |
| **Validator** | Every 5 min | Tests candidates via WebSocket handshake, promotes valid relays | service_state (candidates) | relay, service_state | WebSocket to relays |
| **Monitor** | Every 5 min | Runs 7 health checks per relay, publishes NIP-66 events | relay, service_state | metadata, relay_metadata, service_state | HTTP, WebSocket, DNS, SSL, GeoIP |
| **Synchronizer** | Every 5 min | Connects to relays, fetches and archives signed events | relay, service_state | event, event_relay, service_state | WebSocket to relays |
| **Refresher** | Every 60 min | Refreshes 11 materialized views in dependency order | (implicit via views) | 11 materialized views | None |
| **Api** | Continuous | Read-only REST API with auto-generated paginated endpoints | all tables, views | -- | HTTP (FastAPI) |
| **Dvm** | Continuous | NIP-90 Data Vending Machine for database queries | all tables, views | -- | WebSocket (Nostr) |

Services are **loosely coupled through the database**: Seeder and Finder populate candidates, Validator promotes them to relays, Monitor and Synchronizer operate on relays, Refresher materializes analytics. But each runs independently -- stopping one does not break the others.

---

## Architecture

### Code Organization (Diamond DAG)

Imports flow strictly downward:

```text
              services         src/bigbrotr/services/
             /   |   \
          core  nips  utils    src/bigbrotr/{core,nips,utils}/
             \   |   /
              models           src/bigbrotr/models/
```

- **models** -- Pure frozen dataclasses (Relay, Event, Metadata, ServiceState). Zero I/O, stdlib logging only.
- **core** -- Pool (asyncpg with retry), Brotr (DB facade), BaseService (lifecycle), Logger (structured kv/JSON), Metrics (Prometheus), YAML loader.
- **nips** -- NIP-11 relay info fetch/parse, NIP-66 health checks (RTT, SSL, DNS, Geo, Net, HTTP). Never raises -- errors in `logs.success`.
- **utils** -- DNS resolution, Nostr key management, WebSocket/HTTP transport, SSL fallback, SOCKS5 proxy support.
- **services** -- 8 independent services + shared queries, configs, and mixins.

### Database Schema

```text
┌─────────────────────┐         ┌──────────────────────────────────────┐
│      relay          │         │              event                   │
│─────────────────────│         │──────────────────────────────────────│
│ url          PK     │◄──┐ ┌──►│ id             PK  (BYTEA, 32B)      │
│ network      TEXT   │   │ │   │ pubkey         BYTEA (32B)           │
│ discovered_at BIGINT│   │ │   │ created_at     BIGINT                │
└─────────┬───────────┘   │ │   │ kind           INTEGER               │
          │               │ │   │ tags           JSONB                 │
          │               │ │   │ tagvalues      TEXT[]                │
          │               │ │   │ content        TEXT                  │
          │               │ │   │ sig            BYTEA (64B)           │
          │               │ │   └──────────────────────────────────────┘
          │               │ │
          │    ┌──────────┴─┴──────────────────┐
          │    │          event_relay          │
          │    │───────────────────────────────│
          ├───►│ relay_url    FK ──► relay.url |
          │    │ event_id     FK ──► event.id  |
          │    │ seen_at      BIGINT           |
          │    │ PK(event_id, relay_url)       |
          │    └───────────────────────────────┘
          │
          │    ┌───────────────────────────────────────────────┐
          │    │                   relay_metadata              │
          │    │───────────────────────────────────────────────│
          └───►│ relay_url    FK ──► relay.url                 |
               │ metadata_id  FK ──► metadata.id               |
               │ metadata_type FK ──► metadata.type            |
               │ generated_at BIGINT                           |
               │ PK(relay_url, generated_at, metadata_type)    |
               └──────────┬────────────────────────────────────┘
                          │
               ┌──────────┴────────────────────┐
               │          metadata             │
               │───────────────────────────────│
               │ id       PK  (BYTEA, SHA-256) |
               │ type     PK  (TEXT, 7 types)  |
               │ data     JSONB                |
               └───────────────────────────────┘


               ┌───────────────────────┐
               │    service_state      │
               │───────────────────────│
               │ service_name PK (TEXT)│
               │ state_type   PK (TEXT)│
               │ state_key    PK (TEXT)│
               │ state_value  JSONB    │
               │ updated_at   BIGINT   │
               └───────────────────────┘
```

**Key relationships**:
- `relay` is the central entity. Cascade deletes propagate to `event_relay` and `relay_metadata`.
- `metadata` is content-addressed: SHA-256 hash of canonical JSON + type as composite PK. Same data = same hash.
- `service_state` is a generic key-value store used by Finder (cursors), Validator (candidates), Monitor (checkpoints), Synchronizer (cursors).
- `event.tagvalues` is computed at insert time by `event_insert()` (from `tags_to_tagvalues(tags)`) and indexed with GIN for fast containment queries.

### Service-Database Interaction Map

```text
                 relay    event   event_   meta-   relay_    service_  materialized
                                  relay    data    metadata  state     views (11)
  ─────────────┬────────┬───────┬────────┬───────┬─────────┬─────────┬────────────
  Seeder       │  W(1)  │       │        │       │         │  W      │
  Finder       │  R     │       │  R     │       │         │  R/W    │
  Validator    │  W     │       │        │       │         │  R/W    │
  Monitor      │  R     │       │        │  W    │  W      │  R/W    │
  Synchronizer │  R     │  W    │  W     │       │         │  R/W    │
  Refresher    │        │       │        │       │         │         │  W
  Api          │  R     │  R    │  R     │  R    │  R      │  R      │  R
  Dvm          │  R     │  R    │  R     │  R    │  R      │  R      │  R
  ─────────────┴────────┴───────┴────────┴───────┴─────────┴─────────┴────────────

  R = reads    W = writes    (1) = only when to_validate=False
```

---

## Quick Start

### Prerequisites

- Docker and Docker Compose
- (Optional) Python 3.11+ and [uv](https://docs.astral.sh/uv/) for local development

### Deploy with Docker Compose

```bash
git clone https://github.com/BigBrotr/bigbrotr.git
cd bigbrotr/deployments/bigbrotr

# Configure secrets
cp .env.example .env
# Edit .env: set DB_ADMIN_PASSWORD, DB_WRITER_PASSWORD, DB_REFRESHER_PASSWORD, DB_READER_PASSWORD, NOSTR_PRIVATE_KEY, GRAFANA_PASSWORD

# Start everything
docker compose up -d

# Watch services start
docker compose logs -f seeder
```

This starts PostgreSQL 16, PGBouncer, Tor proxy, all 8 services, Prometheus, Alertmanager, and Grafana.

| Endpoint | URL |
|----------|-----|
| Grafana | `http://localhost:3000` |
| Prometheus | `http://localhost:9090` |
| Alertmanager | `http://localhost:9093` |
| PostgreSQL | `localhost:5432` |
| PGBouncer | `localhost:6432` |

### Run a Single Service Locally

```bash
uv sync --group dev
cd deployments/bigbrotr

# One cycle
python -m bigbrotr seeder --once

# Continuous with debug logging
python -m bigbrotr finder --log-level DEBUG
```

---

## Deployments

BigBrotr supports multiple deployment configurations from the same codebase via a single parametric Dockerfile (`deployments/Dockerfile` with `ARG DEPLOYMENT`).

### BigBrotr (Full Archive)

Stores complete Nostr events (id, pubkey, created_at, kind, tags, content, sig).

```bash
cd deployments/bigbrotr && docker compose up -d
```

### LilBrotr (Lightweight)

Stores all 8 event columns but keeps tags, content, and sig as NULL for approximately 60% disk savings.

```bash
cd deployments/lilbrotr && docker compose up -d
```

### Custom Deployment

```bash
cp -r deployments/bigbrotr deployments/myrelay
# Edit config, SQL schema, docker-compose.yaml
cd deployments/myrelay && docker compose up -d
```

---

## Database

PostgreSQL 16 with PGBouncer (transaction-mode pooling) and asyncpg async driver. All mutations via stored functions with bulk array parameters.

### Schema

| Table | Purpose |
|-------|---------|
| `relay` | Validated relay URLs with network type and discovery timestamp |
| `event` | Nostr events (BYTEA ids/pubkeys/sigs for space efficiency) |
| `event_relay` | Junction: which events were seen at which relays (with `seen_at`) |
| `metadata` | Content-addressed NIP-11/NIP-66 documents (SHA-256 dedup, composite PK `(id, type)`) |
| `relay_metadata` | Time-series snapshots linking relays to metadata records |
| `service_state` | Per-service operational data (candidates, cursors, checkpoints) |

### Stored Functions (25)

- **1 utility**: `tags_to_tagvalues` (extracts key-prefixed single-char tag values for GIN indexing)
- **10 CRUD**: `relay_insert`, `event_insert`, `metadata_insert`, `event_relay_insert`, `relay_metadata_insert`, `event_relay_insert_cascade`, `relay_metadata_insert_cascade`, `service_state_upsert`, `service_state_get`, `service_state_delete`
- **2 cleanup**: `orphan_event_delete`, `orphan_metadata_delete` (batched)
- **12 refresh**: one per materialized view + `all_statistics_refresh`

All functions use `SECURITY INVOKER`, bulk array parameters, and `ON CONFLICT DO NOTHING`.

### Materialized Views (11)

`relay_metadata_latest`, `event_stats`, `relay_stats`, `kind_counts`, `kind_counts_by_relay`, `pubkey_counts`, `pubkey_counts_by_relay`, `network_stats`, `relay_software_counts`, `supported_nip_counts`, `event_daily_counts` -- all support `REFRESH CONCURRENTLY` via unique indexes.

---

## Monitoring

### Prometheus Metrics

Every service exposes `/metrics` on its configured port with four metric types:

| Metric | Type | Description |
|--------|------|-------------|
| `service_info` | Info | Static service metadata |
| `service_gauge` | Gauge | Point-in-time state (consecutive_failures, last_cycle_timestamp, progress) |
| `service_counter` | Counter | Cumulative totals (cycles_success, cycles_failed, errors by type) |
| `cycle_duration_seconds` | Histogram | Cycle latency with 10 buckets (1s to 1h) |

### Alert Rules (6)

| Alert | Condition | Severity |
|-------|-----------|----------|
| ServiceDown | `up == 0` for 5m | critical |
| HighFailureRate | error rate > 0.1/s for 5m | warning |
| ConsecutiveFailures | 5+ consecutive cycle failures for 2m | critical |
| SlowCycles | p99 cycle duration > 300s for 5m | warning |
| DatabaseConnectionsHigh | > 80 active connections for 5m | warning |
| CacheHitRatioLow | buffer cache hit ratio < 95% for 10m | warning |

### Grafana Dashboard

Auto-provisioned dashboard with per-service panels: cycle duration, error counts, consecutive failures, and service-specific progress metrics.

### Structured Logging

```text
info finder cycle_completed relay_count=100 duration=2.5
error validator retry_failed attempt=3 url="wss://relay.example.com"
```

JSON mode available for cloud aggregation:

```json
{"timestamp": "2026-02-09T12:34:56+00:00", "level": "info", "service": "finder", "message": "cycle_completed", "relay_count": 100}
```

---

## Nostr Protocol Support

### NIPs Implemented

| NIP | Usage |
|-----|-------|
| **NIP-01** | Event model, relay communication |
| **NIP-02** | Contact list relay discovery (kind 3) |
| **NIP-11** | Relay information document fetch and parse |
| **NIP-65** | Relay list metadata (kind 10002) |
| **NIP-66** | Relay monitoring and discovery (kinds 10166, 30166) |

### Event Kinds

| Kind | Direction | Purpose |
|------|-----------|---------|
| 0 | Published | Monitor profile metadata |
| 2 | Consumed | Deprecated relay recommendation |
| 3 | Consumed | Contact list (relay URLs from tag values) |
| 10002 | Consumed | NIP-65 relay list (`r` tags) |
| 10166 | Published | Monitor announcement (capabilities, networks, timeouts) |
| 30166 | Published | Relay discovery (addressable, one per relay, health check tags) |

### NIP-66 Health Checks

| Check | What It Measures | Networks |
|-------|-----------------|----------|
| RTT | WebSocket open/read/write latency (ms), 3-phase with verification | All |
| SSL | Certificate validity, expiry, issuer, SANs, cipher, fingerprint | Clearnet |
| DNS | A/AAAA/CNAME/NS/PTR records, TTL | Clearnet |
| Geo | Country, city, coordinates, timezone, geohash (GeoLite2 City) | Clearnet |
| Net | IP address, ASN, organization, network ranges (GeoLite2 ASN) | Clearnet |
| HTTP | Server header, X-Powered-By (from WebSocket handshake) | All |

---

## Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DB_ADMIN_PASSWORD` | Yes | PostgreSQL admin password |
| `DB_WRITER_PASSWORD` | Yes | Writer role password (Seeder, Finder, Validator, Monitor, Synchronizer) |
| `DB_REFRESHER_PASSWORD` | Yes | Refresher role password (matview ownership) |
| `DB_READER_PASSWORD` | Yes | Reader role password (Api, Dvm, postgres-exporter) |
| `NOSTR_PRIVATE_KEY` | For Monitor, Validator, Synchronizer, Dvm | Nostr private key (hex or nsec) for event signing and NIP-42 auth |
| `GRAFANA_PASSWORD` | For Grafana | Grafana admin password |

### Configuration Files

```text
deployments/bigbrotr/config/
├── brotr.yaml                  # Pool, batch size, timeouts
└── services/
    ├── seeder.yaml             # Seed file path, validate mode
    ├── finder.yaml             # API sources (JMESPath), event scanning, concurrency
    ├── validator.yaml          # Networks, cleanup, processing chunk size
    ├── monitor.yaml            # Health checks, retry per type, publishing, GeoIP
    ├── synchronizer.yaml       # Networks, filter, time range, per-relay overrides
    ├── refresher.yaml          # View list, refresh interval
    ├── api.yaml                # Host, port, pagination, CORS
    └── dvm.yaml                # NIP-90 kind, relay list, response format
```

All configs use Pydantic v2 validation with typed defaults and constraints.

---

## Development

### Setup

```bash
git clone https://github.com/BigBrotr/bigbrotr.git && cd bigbrotr
curl -LsSf https://astral.sh/uv/install.sh | sh  # install uv (one-time)
uv sync --group dev
pre-commit install
```

### Quality Checks

```bash
make lint             # ruff check src/ tests/
make format           # ruff format src/ tests/
make typecheck        # mypy src/bigbrotr (strict mode)
make test             # pytest unit tests (~2400 tests)
make test-integration # pytest integration tests (requires Docker)
make test-fast        # pytest -m "not slow"
make coverage         # pytest --cov with HTML report
make ci               # all checks: lint + format-check + typecheck + test + sql-check + audit
make docs             # build MkDocs documentation site
make docs-serve       # serve docs locally with live reload
make build            # build Python package (sdist + wheel)
make docker-build     # build Docker image (DEPLOYMENT=bigbrotr)
make docker-up        # start Docker stack
make docker-down      # stop Docker stack
make clean            # remove build artifacts and caches
```

### Test Suite

- ~2,500 unit tests + ~94 integration tests (testcontainers PostgreSQL)
- `asyncio_mode = "auto"` -- no `@pytest.mark.asyncio` needed
- Global timeout: 120s per test
- Shared fixtures via `tests/fixtures/relays.py` (registered as pytest plugin)
- Coverage threshold: 80% (branch coverage enabled)

### CI/CD Pipeline

| Stage | Tool | Purpose |
|-------|------|---------|
| Pre-commit | ruff, mypy, yamllint, detect-secrets, markdownlint, hadolint, sqlfluff, codespell | Code quality gates |
| Unit Test | pytest (Python 3.11--3.14 matrix) | Unit tests + coverage |
| Integration Test | pytest + testcontainers | PostgreSQL integration tests |
| Build | Docker Buildx (matrix) | Multi-deployment image builds + Trivy scan |
| Security | uv-secure, Trivy, CodeQL | Dependency vulns, container scanning, static analysis |
| Release | PyPI (OIDC) + GHCR | Package + Docker image publishing, SBOM generation |
| Docs | MkDocs Material | Auto-generated API docs deployed to GitHub Pages |
| Dependencies | Dependabot | Weekly updates for uv, Docker, GitHub Actions |

---

## Project Structure

```text
bigbrotr/
├── src/bigbrotr/                    # Main package
│   ├── __main__.py                  # CLI entry point (service registry)
│   ├── core/                        # Infrastructure
│   │   ├── pool.py                  # asyncpg connection pool with retry/backoff
│   │   ├── brotr.py                 # DB facade (stored procedures, bulk inserts)
│   │   ├── base_service.py          # Abstract service with run_forever loop
│   │   ├── logger.py                # Structured key=value / JSON logging
│   │   ├── metrics.py               # Prometheus metrics server
│   │   └── yaml.py                  # YAML config loader
│   ├── models/                      # Pure frozen dataclasses (zero I/O)
│   │   ├── relay.py                 # URL validation (rfc3986), network detection
│   │   ├── event.py                 # Nostr event wrapper (nostr_sdk.Event)
│   │   ├── metadata.py              # Content-addressed metadata (SHA-256)
│   │   ├── event_relay.py           # Event-relay junction (cascade insert)
│   │   ├── relay_metadata.py        # Relay-metadata junction (cascade insert)
│   │   ├── service_state.py         # Operational state persistence
│   │   ├── constants.py             # NetworkType, ServiceName, EventKind enums
│   │   └── _validation.py           # Shared validation and sanitization
│   ├── nips/                        # NIP protocol implementations (I/O)
│   │   ├── base.py                  # Base data, logs, metadata models
│   │   ├── parsing.py               # Declarative field parsing (FieldSpec)
│   │   ├── event_builders.py        # Kind 0/10166/30166 event construction
│   │   ├── nip11/                   # Relay information document
│   │   └── nip66/                   # Health checks: rtt, ssl, dns, geo, net, http
│   ├── utils/                       # Network primitives
│   │   ├── protocol.py              # Nostr client, relay connection, broadcasting
│   │   ├── transport.py             # Insecure WebSocket transport, stderr filter
│   │   ├── dns.py                   # Async hostname resolution (A/AAAA)
│   │   ├── keys.py                  # Nostr key loading from environment
│   │   ├── http.py                  # Bounded HTTP response reading
│   │   └── parsing.py               # Tolerant model factory parsing
│   └── services/                    # Business logic
│       ├── seeder/                  # Seed file loading (one-shot)
│       ├── finder/                  # Relay discovery (APIs + event scanning)
│       ├── validator/               # WebSocket protocol validation
│       ├── monitor/                 # Health check orchestration + publishing
│       ├── synchronizer/            # Event collection (cursor-based)
│       ├── refresher/               # Materialized view refresh
│       ├── api/                     # REST API (FastAPI, read-only)
│       ├── dvm/                     # NIP-90 Data Vending Machine
│       └── common/                  # Shared queries, configs, mixins
├── deployments/
│   ├── Dockerfile                   # Single parametric (ARG DEPLOYMENT)
│   ├── bigbrotr/                    # Full archive deployment
│   │   ├── config/                  # YAML configs (brotr + 8 services)
│   │   ├── postgres/init/           # SQL schema (10 files, 25 functions)
│   │   ├── monitoring/              # Prometheus + Alertmanager + Grafana
│   │   └── docker-compose.yaml      # 15 containers, 2 networks
│   └── lilbrotr/                    # Lightweight deployment
├── tests/
│   ├── fixtures/relays.py           # Shared relay fixtures
│   ├── unit/                        # ~2,500 tests (mirrors src/ structure)
│   └── integration/                 # ~94 tests (testcontainers PostgreSQL)
├── docs/                            # MkDocs Material documentation
├── Makefile                         # Development targets
└── pyproject.toml                   # All config: deps, ruff, mypy, pytest, coverage
```

---

## Docker Infrastructure

### Container Stack

| Container | Image | Purpose |
|-----------|-------|---------|
| postgres | `postgres:16-alpine` | Primary storage |
| pgbouncer | `edoburu/pgbouncer:v1.25.1-p0` | Transaction-mode connection pooling |
| tor | `osminogin/tor-simple:0.4.8.10` | SOCKS5 proxy for .onion relays |
| seeder | bigbrotr (parametric) | Relay bootstrapping (one-shot) |
| finder | bigbrotr (parametric) | Relay discovery |
| validator | bigbrotr (parametric) | Candidate validation |
| monitor | bigbrotr (parametric) | Health monitoring + event publishing |
| synchronizer | bigbrotr (parametric) | Event archiving |
| refresher | bigbrotr (parametric) | Materialized view refresh |
| api | bigbrotr (parametric) | REST API (FastAPI) |
| dvm | bigbrotr (parametric) | NIP-90 Data Vending Machine |
| postgres-exporter | `prometheuscommunity/postgres-exporter:v0.16.0` | PostgreSQL metrics |
| prometheus | `prom/prometheus:v2.51.0` | Metrics collection (30d retention) |
| alertmanager | `prom/alertmanager:v0.27.0` | Alert routing and grouping |
| grafana | `grafana/grafana:10.4.1` | Dashboards |

### Networks

- `data-network` -- postgres, pgbouncer, tor, all services
- `monitoring-network` -- prometheus, grafana, alertmanager, postgres-exporter, all services

### Security

- All ports bound to `127.0.0.1` (no external exposure)
- Non-root container execution (UID 1000)
- `tini` as PID 1 for proper signal handling
- SCRAM-SHA-256 authentication (PostgreSQL + PGBouncer)
- Healthchecks via `pg_isready` and `/metrics` HTTP endpoint

---

## Technology Stack

| Category | Technologies |
|----------|-------------|
| Language | Python 3.11+ (fully typed, strict mypy) |
| Database | PostgreSQL 16, asyncpg, PGBouncer |
| Async | asyncio, aiohttp, aiohttp-socks |
| Nostr | nostr-sdk (Rust FFI via UniFFI) |
| Web Framework | FastAPI, uvicorn |
| Validation | Pydantic v2, rfc3986 |
| Monitoring | Prometheus, Grafana, Alertmanager, structured logging |
| Networking | dnspython, geoip2, geohash2, tldextract, cryptography |
| Testing | pytest, pytest-asyncio, pytest-cov, testcontainers |
| Quality | ruff (lint+format), mypy (strict), pre-commit (23 hooks) |
| CI/CD | GitHub Actions, uv-secure, Trivy, CodeQL, Dependabot |
| Containers | Docker, Docker Compose, tini |
| Build | uv (dependency management + build) |

---

## Documentation

Full documentation is available at **[bigbrotr.github.io/bigbrotr](https://bigbrotr.github.io/bigbrotr/)**.

| Section | Description |
|---------|-------------|
| [Getting Started](https://bigbrotr.github.io/bigbrotr/getting-started/) | Installation, quick start tutorial, first deployment |
| [User Guide](https://bigbrotr.github.io/bigbrotr/user-guide/) | Architecture, configuration, database, monitoring |
| [How-to Guides](https://bigbrotr.github.io/bigbrotr/how-to/) | Docker deploy, manual deploy, Tor setup, troubleshooting |
| [Development](https://bigbrotr.github.io/bigbrotr/development/) | Setup, testing, contributing |
| [API Reference](https://bigbrotr.github.io/bigbrotr/reference/) | Auto-generated Python API docs |
| [Changelog](CHANGELOG.md) | Version history and migration guides |

---

## Contributing

See the [Contributing Guide](https://bigbrotr.github.io/bigbrotr/development/contributing/) for detailed instructions.

1. Fork and clone
2. `uv sync --group dev` and `pre-commit install`
3. Write tests for new functionality
4. `make ci` -- all checks must pass
5. Submit a pull request

Conventional commits: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`

---

## License

MIT -- see [LICENSE](LICENSE).

---

## Links

- [Full Documentation](https://bigbrotr.github.io/bigbrotr/)
- [Changelog](CHANGELOG.md)
- [Nostr Protocol](https://nostr.com)
- [NIP-11: Relay Information Document](https://github.com/nostr-protocol/nips/blob/master/11.md)
- [NIP-66: Relay Discovery and Monitoring](https://github.com/nostr-protocol/nips/blob/master/66.md)
- [NIPs Repository](https://github.com/nostr-protocol/nips)
