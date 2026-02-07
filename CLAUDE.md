# CLAUDE.md

Development reference for the BigBrotr codebase.

## Project Overview

BigBrotr is a modular Nostr data archiving and monitoring system built with Python 3.11+ and PostgreSQL. It provides relay discovery, health monitoring (NIP-11/NIP-66), and event synchronization with multi-network support (clearnet, Tor, I2P, Lokinet).

## Common Commands

```bash
# Install dependencies (from lock files for reproducible builds)
pip install -r requirements.txt -r requirements-dev.txt
pre-commit install

# Update dependencies (edit .in files, then regenerate lock files)
pip install pip-tools
pip-compile requirements.in -o requirements.txt --strip-extras
pip-compile requirements-dev.in -o requirements-dev.txt --strip-extras

# Run tests
pytest tests/ -v                             # All tests
pytest tests/unit/services/test_synchronizer.py -v # Single file
pytest -k "health_check" -v                  # Pattern match
pytest tests/ --cov=src --cov-report=html    # With coverage

# Code quality
ruff check src/ tests/                       # Lint
ruff format src/ tests/                      # Format
mypy src/                                    # Type check
pre-commit run --all-files                   # All hooks

# Run services (from implementations/bigbrotr/)
python -m services seeder
python -m services finder --log-level DEBUG
python -m services monitor
python -m services synchronizer

# Docker deployment
cd implementations/bigbrotr
docker-compose up -d
docker-compose exec postgres psql -U admin -d bigbrotr
```

## Architecture

Four-layer architecture separating concerns:

```
Implementation Layer (implementations/bigbrotr/, implementations/lilbrotr/)
  └── YAML configs, SQL schemas, Docker, seed data
        |
        v
Service Layer (src/services/)
  └── seeder.py, finder.py, validator.py, monitor.py, synchronizer.py
        |
        v
Core Layer (src/core/)
  └── pool.py, brotr.py, queries.py, service.py (BatchProgress), metrics.py, logger.py
        |
        v
Utils Layer (src/utils/)
  └── NetworkConfig, KeysConfig, create_client, load_yaml, resolve_host
        |
        v
Models Layer (src/models/)
  └── Event, Relay, EventRelay, Metadata, RelayMetadata, NetworkType, MetadataType
  └── NIP models in subpackages: src/models/nips/nip11/, src/models/nips/nip66/
  └── NIP utilities: src/models/nips/base.py, src/models/nips/parsing.py
```

**Data Storage**: The `Nip11` and `Nip66` Python models are stored in the unified `metadata` table using content-addressed deduplication (SHA-256 hash). The `relay_metadata` table links relays to metadata records via the `metadata_type` column (`nip11_fetch`, `nip66_rtt`, `nip66_ssl`, `nip66_geo`, `nip66_net`, `nip66_dns`, `nip66_http`).

### Core Components

- **Pool** (`src/core/pool.py`): Async PostgreSQL client with asyncpg and unified `RetryConfig` (max_attempts, initial_delay, max_delay, exponential_backoff) for connect, query retry, and acquire_healthy (connects via PGBouncer in Docker)
- **Brotr** (`src/core/brotr.py`): Generic database facade with private `_pool`; exposes `fetch()`, `fetchrow()`, `fetchval()`, `execute()`, `transaction()`, and `pool_config` property. Zero domain logic — all SQL lives in `core/queries.py`
- **Queries** (`src/core/queries.py`): All domain-specific SQL queries. Services import query functions instead of writing inline SQL. Each function accepts a `Brotr` instance as first parameter
- **BaseService** (`src/core/service.py`): Abstract service base with state persistence and lifecycle management
- **BaseServiceConfig** (`src/core/service.py`): Base configuration class for all services
- **MetricsServer** (`src/core/metrics.py`): Prometheus HTTP metrics endpoint
- **MetricsConfig** (`src/core/metrics.py`): Prometheus metrics configuration
- **Logger** (`src/core/logger.py`): Structured key=value logging
- **ConfigT**: TypeVar for typed configuration in generic service classes

### Services

- **Seeder**: One-shot relay seeding for validation
- **Finder**: Continuous relay URL discovery from APIs and events
- **Validator**: Streaming relay validation with multi-network support
- **Monitor**: NIP-11/NIP-66 health monitoring with SSL and geolocation checks
- **Synchronizer**: Multicore event collection using aiomultiprocess

### Key Patterns

- Services receive `Brotr` via constructor (dependency injection)
- All services inherit from `BaseService[ConfigClass]`
- Services import query functions from `core.queries` — zero inline SQL in service files
- Services use `async with brotr:` for lifecycle (NOT `async with brotr.pool:`)
- Atomic operations use `self._brotr.transaction()` (e.g., `promote_candidates` in queries.py)
- Configuration uses Pydantic models with YAML loading (`from utils.yaml import load_yaml`)
- Passwords loaded from `DB_PASSWORD` environment variable only
- Keys loaded from `PRIVATE_KEY` environment variable (required for Monitor write tests)
- Services use `NetworkConfig` for unified network settings (Tor, I2P, Lokinet)
- Services use `BatchProgress` (from `core.service`) for tracking batch processing progress
- Monitor uses `CheckResult` NamedTuple for health check results
- Monitor runs health checks in parallel via `asyncio.gather` (SSL, DNS, Geo, Net, HTTP)
- Monitor wraps blocking I/O with `asyncio.to_thread` (GeoLite2 downloads, Reader init)
- All models cache `to_db_params()` result in `__post_init__` — no repeated allocation
- Models and Utils layers have zero core dependencies (use stdlib `logging` only)
- `BrotrConfig` has two fields: `batch` (BatchConfig) and `timeouts` (TimeoutsConfig)

## Adding a New Service

1. Create `src/services/myservice.py` with:
   - `MyServiceConfig(BaseServiceConfig)` for configuration
   - `MyService(BaseService[MyServiceConfig])` with `run()` method

2. Add configuration: `implementations/bigbrotr/yaml/services/myservice.yaml`

3. Register in `src/services/__main__.py` (maps service name to class and YAML config path):
   ```python
   SERVICE_REGISTRY = {
       "myservice": (MyService, YAML_BASE / "services" / "myservice.yaml"),
   }
   ```

4. Export from `src/services/__init__.py`

5. Write tests in `tests/unit/services/test_myservice.py`

## Creating a New Implementation

Implementations are deployment configurations that use the shared core/service layers:

```bash
# Copy an existing implementation
cp -r implementations/bigbrotr implementations/myimpl
cd implementations/myimpl

# Key files to customize:
# - yaml/core/brotr.yaml          Database connection settings
# - yaml/services/*.yaml          Service configurations
# - postgres/init/02_tables.sql   SQL schema (e.g., remove tags/content columns)
# - docker-compose.yaml           Container config, ports (avoid conflicts)
# - .env.example                  Environment template
```

**Common customizations:**

- **Essential metadata only**: Remove `tags`, `tagvalues`, `content` columns from events table (like lilbrotr -- indexes all events but omits heavy fields, ~60% disk savings)
- **Overlay networks disabled**: Set `networks.tor.enabled: false`, etc. in service YAML files
- **Lower concurrency**: Reduce `networks.*.max_tasks` and `concurrency.max_processes`
- **Different ports**: Change PostgreSQL/Prometheus/Grafana/Tor ports in docker-compose.yaml
- **Event filtering**: Set `filter.kinds` in synchronizer.yaml to store only specific event types

## Git Workflow

- **Main branch**: `main` (stable releases)
- **Development branch**: `develop` (active development)
- **Feature branches**: `feature/<name>` (from develop)
- **Commit style**: Conventional commits (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`)
