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

BigBrotr runs a pipeline of five async services that continuously map and monitor the Nostr relay ecosystem:

```text
Seeder ──> Finder ──> Validator ──> Monitor ──> Synchronizer
(seed URLs)  (discover)  (test)    (health)     (archive events)
```

1. **Seeder** loads relay URLs from a seed file (one-shot)
2. **Finder** discovers new relays from stored events (NIP-65 relay lists, kind 2/3) and external APIs
3. **Validator** tests WebSocket connectivity for each candidate, promoting valid relays
4. **Monitor** performs NIP-11 info document fetches and NIP-66 health checks (RTT, SSL, DNS, GeoIP, ASN, HTTP headers), then publishes results as kind 10166/30166 Nostr events
5. **Synchronizer** connects to all validated relays, subscribes to events, and archives them with per-relay cursor tracking for incremental sync

All services expose Prometheus metrics, run behind PGBouncer connection pooling, and support clearnet + Tor + I2P + Lokinet connectivity.

---

## Architecture

Diamond DAG with strict import direction (top to bottom only):

```text
              services         src/bigbrotr/services/
             /   |   \
          core  nips  utils    src/bigbrotr/{core,nips,utils}/
             \   |   /
              models           src/bigbrotr/models/
```

- **models** -- Pure frozen dataclasses. Zero I/O, zero package dependencies, stdlib logging only.
- **core** -- Pool (asyncpg), Brotr (DB facade), BaseService, Logger, Metrics, Exceptions.
- **nips** -- NIP-11 relay info fetch/parse, NIP-66 health checks (RTT, SSL, DNS, Geo, Net, HTTP). Has I/O.
- **utils** -- DNS resolution, Nostr key management, WebSocket/HTTP transport with SOCKS5 proxy.
- **services** -- Business logic: Seeder, Finder, Validator, Monitor (+ Publisher + Tags), Synchronizer.

---

## Quick Start

### Prerequisites

- Docker and Docker Compose
- (Optional) Python 3.11+ for local development

### Deploy with Docker Compose

```bash
git clone https://github.com/BigBrotr/bigbrotr.git
cd bigbrotr/deployments/bigbrotr

# Configure secrets
cp .env.example .env
# Edit .env: set DB_PASSWORD, PRIVATE_KEY, GRAFANA_PASSWORD

# Start everything
docker compose up -d

# Watch the pipeline start
docker compose logs -f seeder
```

This starts PostgreSQL, PGBouncer, Tor proxy, all 5 services, Prometheus, and Grafana.

| Endpoint | URL |
|----------|-----|
| Grafana | `http://localhost:3000` |
| Prometheus | `http://localhost:9090` |
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

Stores complete Nostr events (id, pubkey, created_at, kind, tags, content, sig). 7 materialized views for analytics. Tor enabled. All 5 services + Prometheus + Grafana.

```bash
cd deployments/bigbrotr && docker compose up -d
```

### LilBrotr (Lightweight)

Stores event metadata only (id, pubkey, created_at, kind, tagvalues). Omits tags JSON, content, and sig for approximately 60% disk savings. No materialized views. Same service pipeline.

```bash
cd deployments/lilbrotr && docker compose up -d
```

### Custom Deployment

```bash
cp -r deployments/_template deployments/myrelay
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
| `event_relay` | Junction: which events were seen at which relays |
| `metadata` | Content-addressed NIP-11/NIP-66 documents (SHA-256 dedup, `data` JSONB) |
| `relay_metadata` | Time-series snapshots linking relays to metadata records (`metadata_type` column) |
| `service_state` | Per-service operational data (candidates, cursors, checkpoints) |

### Stored Functions (22)

- **1 utility**: `tags_to_tagvalues` (extracts single-char tag values for GIN indexing)
- **10 CRUD**: `relay_insert`, `event_insert`, `metadata_insert`, `event_relay_insert`, `relay_metadata_insert`, `event_relay_insert_cascade`, `relay_metadata_insert_cascade`, `service_state_upsert`, `service_state_get`, `service_state_delete`
- **3 cleanup**: `orphan_event_delete`, `orphan_metadata_delete`, `relay_metadata_delete_expired` (all batched)
- **8 refresh**: one per materialized view + `all_statistics_refresh`

All functions use `SECURITY INVOKER`, bulk array parameters, and `ON CONFLICT DO NOTHING`.

### Materialized Views (7, BigBrotr Only)

`relay_metadata_latest`, `event_stats`, `relay_stats`, `kind_counts`, `kind_counts_by_relay`, `pubkey_counts`, `pubkey_counts_by_relay` -- all support `REFRESH CONCURRENTLY` via unique indexes.

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

### Alert Rules (4)

| Alert | Condition | Severity |
|-------|-----------|----------|
| ServiceDown | `up == 0` for 5m | critical |
| HighFailureRate | error rate > 0.1/s for 5m | warning |
| PoolExhausted | zero available connections for 2m | critical |
| DatabaseSlow | p99 query latency > 5s for 5m | warning |

### Grafana Dashboard

Auto-provisioned dashboard with per-service panels: last cycle time, cycle duration, error counts (24h), consecutive failures. Validator has additional candidate progress panels.

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
| 2 | Consumed | Deprecated relay recommendation (content = URL) |
| 3 | Consumed | Contact list (content = JSON with relay URLs as keys) |
| 10002 | Consumed | NIP-65 relay list ("r" tags) |
| 10166 | Published | Monitor announcement (capabilities, timeouts) |
| 30166 | Published | Relay discovery (addressable, one per relay, full metadata tags) |

### NIP-66 Health Checks

| Check | What It Measures |
|-------|-----------------|
| RTT | WebSocket open/read/write latency (ms) |
| SSL | Certificate validity, expiry, issuer, cipher suite |
| DNS | A/AAAA/CNAME/NS/PTR records, query time |
| Geo | Country, city, coordinates, timezone, geohash (GeoLite2) |
| Net | IP address, ASN, organization (GeoLite2 ASN) |
| HTTP | Server header, X-Powered-By |

---

## Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DB_PASSWORD` | Yes | PostgreSQL password |
| `PRIVATE_KEY` | For Monitor | Nostr private key (hex or nsec) for event publishing and RTT write tests |
| `GRAFANA_PASSWORD` | No | Grafana admin password |

### Configuration Files

```text
deployments/bigbrotr/config/
+-- brotr.yaml                  # Pool, batch size, timeouts
+-- services/
    +-- seeder.yaml             # Seed file path
    +-- finder.yaml             # API sources, scan interval (default: 1h)
    +-- validator.yaml          # Validation interval (8h), cleanup, networks
    +-- monitor.yaml            # Check interval (1h), retry per check type, networks
    +-- synchronizer.yaml       # Sync interval (15m), per-relay overrides, concurrency
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
make lint          # ruff check src/ tests/
make format        # ruff format src/ tests/
make typecheck     # mypy src/bigbrotr (strict mode)
make test-unit        # pytest unit tests (2049 tests)
make test-integration # pytest integration tests (requires Docker)
make test-fast        # pytest -m "not slow"
make coverage         # pytest --cov with HTML report
make ci               # all checks: lint + format + typecheck + test-unit
make docs             # build MkDocs documentation site
make docs-serve       # serve docs locally with live reload
make build            # build Python package (sdist + wheel)
make docker-build     # build Docker image (DEPLOYMENT=bigbrotr)
make docker-up        # start Docker stack
make docker-down      # stop Docker stack
make clean            # remove build artifacts and caches
```

### Test Suite

- **2049 unit tests** + **8 integration tests** (testcontainers PostgreSQL)
- `asyncio_mode = "auto"` -- no `@pytest.mark.asyncio` needed
- Global timeout: 120s per test
- Shared fixtures via `tests/fixtures/relays.py` (registered as pytest plugin)
- Coverage threshold: 80% (branch coverage enabled)

### CI/CD Pipeline

| Stage | Tool | Purpose |
|-------|------|---------|
| Pre-commit | ruff, mypy, yamllint, detect-secrets, markdownlint, hadolint, sqlfluff | Code quality gates |
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
+-- src/bigbrotr/                    # Main package (namespace)
|   +-- __main__.py                  # CLI entry point
|   +-- core/                        # Foundation
|   |   +-- pool.py                  # asyncpg connection pool with retry
|   |   +-- brotr.py                 # High-level DB facade (stored procedures)
|   |   +-- base_service.py          # Abstract service with run_forever loop
|   |   +-- exceptions.py            # Exception hierarchy (10 classes)
|   |   +-- metrics.py               # Prometheus metrics server
|   |   +-- logger.py                # Structured key=value / JSON logging
|   |   +-- yaml.py                  # YAML config loader
|   +-- models/                      # Pure frozen dataclasses (zero I/O)
|   |   +-- relay.py                 # URL validation, network detection
|   |   +-- event.py                 # Nostr event wrapper
|   |   +-- metadata.py              # Content-addressed metadata (SHA-256)
|   |   +-- service_state.py         # ServiceState, ServiceStateType, ServiceStateDbParams
|   |   +-- constants.py             # NetworkType, ServiceName, EventKind enums
|   |   +-- event_relay.py           # Event-relay junction
|   |   +-- relay_metadata.py        # Relay-metadata junction
|   +-- nips/                        # NIP protocol implementations (I/O)
|   |   +-- nip11/                   # Relay information document
|   |   +-- nip66/                   # Health checks: rtt, ssl, dns, geo, net, http
|   +-- utils/                       # DNS, keys, transport
|   +-- services/                    # Business logic
|       +-- seeder.py
|       +-- finder.py
|       +-- validator.py
|       +-- monitor.py               # Health check orchestration
|       +-- monitor_publisher.py     # Nostr event broadcasting
|       +-- monitor_tags.py          # NIP-66 tag building
|       +-- synchronizer.py
|       +-- common/                  # Shared queries, configs, mixins
+-- deployments/
|   +-- Dockerfile                   # Single parametric (ARG DEPLOYMENT)
|   +-- bigbrotr/                    # Full archive deployment
|   |   +-- config/                  # YAML configs
|   |   +-- postgres/init/           # SQL schema (10 files, 22 functions)
|   |   +-- monitoring/              # Prometheus + Grafana provisioning
|   |   +-- docker-compose.yaml
|   +-- lilbrotr/                    # Lightweight deployment
|   +-- _template/                   # Custom deployment template
+-- tests/
|   +-- fixtures/relays.py           # Shared relay fixtures
|   +-- unit/                        # 2049 tests (mirrors src/ structure)
|   +-- integration/                 # 8 tests (testcontainers PostgreSQL)
+-- docs/                            # Architecture, Database, Deployment, Development, Configuration
+-- Makefile                         # Development targets
+-- pyproject.toml                   # All config: deps, ruff, mypy, pytest, coverage
```

---

## Exception Hierarchy

```text
BigBrotrError
+-- ConfigurationError          # YAML, env vars, CLI
+-- DatabaseError
|   +-- ConnectionPoolError     # Transient (retry)
|   +-- QueryError              # Permanent (don't retry)
+-- ConnectivityError
|   +-- RelayTimeoutError       # Connection/response timed out
|   +-- RelaySSLError           # TLS/SSL failures
+-- ProtocolError               # NIP parsing/validation
+-- PublishingError             # Event broadcast failures
```

---

## Docker Infrastructure

### Container Stack

| Container | Image | Purpose | Resources |
|-----------|-------|---------|-----------|
| postgres | `postgres:16-alpine` | Primary storage | 2 CPU, 2 GB |
| pgbouncer | `edoburu/pgbouncer:v1.25.1-p0` | Transaction-mode connection pooling | 0.5 CPU, 256 MB |
| tor | `osminogin/tor-simple:0.4.8.10` | SOCKS5 proxy for .onion relays | 0.5 CPU, 256 MB |
| finder | bigbrotr (parametric) | Relay discovery | 1 CPU, 512 MB |
| validator | bigbrotr (parametric) | Candidate validation | 1 CPU, 512 MB |
| monitor | bigbrotr (parametric) | Health monitoring | 1 CPU, 512 MB |
| synchronizer | bigbrotr (parametric) | Event archiving | 1 CPU, 512 MB |
| prometheus | `prom/prometheus:v2.51.0` | Metrics collection (30d retention) | 0.5 CPU, 512 MB |
| grafana | `grafana/grafana:10.4.1` | Dashboards | 0.5 CPU, 512 MB |

### Networks

- `data-network` -- postgres, pgbouncer, tor, all services
- `monitoring-network` -- prometheus, grafana, all services (metrics scraping)

### Security

- All ports bound to `127.0.0.1` (no external exposure)
- Non-root container execution (UID 1000)
- `tini` as PID 1 for proper signal handling
- SCRAM-SHA-256 authentication (PostgreSQL + PGBouncer)
- Real healthchecks via `/metrics` endpoint (not fake PID checks)

---

## Technology Stack

| Category | Technologies |
|----------|-------------|
| Language | Python 3.11+ (fully typed, strict mypy) |
| Database | PostgreSQL 16, asyncpg, PGBouncer |
| Async | asyncio, aiohttp, aiomultiprocess |
| Nostr | nostr-sdk (Rust FFI via PyO3/uniffi) |
| Validation | Pydantic v2, rfc3986 |
| Monitoring | Prometheus, Grafana, structured logging |
| Networking | aiohttp-socks (SOCKS5), dnspython, geoip2, tldextract |
| Testing | pytest, pytest-asyncio, pytest-cov, testcontainers |
| Quality | ruff (lint+format), mypy (strict), pre-commit (21 hooks) |
| CI/CD | GitHub Actions, uv-secure, Trivy, CodeQL, Dependabot |
| Containers | Docker, Docker Compose, tini |

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
