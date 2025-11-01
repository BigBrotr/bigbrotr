# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Bigbrotr is a full-network archival system for the Nostr protocol. It's a microservices-based Python application that continuously monitors, archives, and analyzes all public events across the entire Nostr network (both clearnet and Tor relays). The system provides deep insights into relay behavior, event redundancy, network topology, and relay health metrics.

**Key Technologies**: Python 3.11+, asyncio, asyncpg, PostgreSQL 15, PgBouncer, Docker, Tor

## Development Commands

### Docker Operations

```bash
# Start all services
docker-compose up -d

# View logs (specific service)
docker-compose logs -f monitor
docker-compose logs -f synchronizer
docker-compose logs -f priority_synchronizer

# Restart a service
docker-compose restart monitor

# Stop all services
docker-compose down

# Rebuild after code changes
docker-compose build
docker-compose up -d
```

### Database Operations

```bash
# Access PostgreSQL directly
docker exec -it bigbrotr_database psql -U admin -d bigbrotr

# Check database connection pool (PgBouncer)
docker exec -it bigbrotr_pgbouncer psql -p 6432 -U admin pgbouncer -c "SHOW POOLS;"

# Run SQL query
docker exec -it bigbrotr_database psql -U admin -d bigbrotr -c "SELECT COUNT(*) FROM events;"

# Backup database
docker exec bigbrotr_database pg_dump -U admin bigbrotr | gzip > backup_$(date +%Y%m%d).sql.gz

# Restore database
gunzip -c backup_20250129.sql.gz | docker exec -i bigbrotr_database psql -U admin bigbrotr
```

### Health Checks

```bash
# Check service health
curl http://localhost:8081/health  # Monitor
curl http://localhost:8082/health  # Synchronizer
curl http://localhost:8083/health  # Priority Synchronizer

# Check service status
docker-compose ps
```

### Testing & Development

```bash
# Access pgAdmin web UI
# Navigate to: http://localhost:8080
# Credentials from .env file

# View real-time logs with filtering
docker-compose logs -f --tail=100 synchronizer | grep "ERROR"

# Monitor resource usage
docker stats bigbrotr_synchronizer bigbrotr_monitor

# Generate Nostr keypair (required for .env setup)
# Use any Nostr key generator, for example:
# npx nostr-keygen
# Or generate using Python nostr-tools library
```

## Architecture

### Service Responsibilities

**Bigbrotr uses a microservices architecture with per-service connection pooling:**

1. **Initializer** ([src/initializer.py](src/initializer.py)): One-time service that seeds the database with initial relays from `seed_relays.txt`. Runs once on startup.

2. **Monitor** ([src/monitor.py](src/monitor.py)): Tests relay health, fetches NIP-11/NIP-66 metadata, and measures RTT. Uses multiprocessing with connection pools. Runs periodically based on `MONITOR_FREQUENCY_HOUR`. Health check on port 8081.

3. **Synchronizer** ([src/synchronizer.py](src/synchronizer.py)): Archives events from all readable relays (excluding priority list). Uses multithreading with per-thread connection pools. Runs continuously with configurable intervals. Health check on port 8082.

4. **Priority Synchronizer** ([src/priority_synchronizer.py](src/priority_synchronizer.py)): Archives events from high-priority relays defined in `priority_relays.txt`. Separate service with dedicated resources. Health check on port 8083.

5. **PgBouncer**: Connection pooling layer (1000 max clients, 100 DB connections) that sits between services and PostgreSQL. Uses transaction pooling mode.

6. **TorProxy**: SOCKS5 proxy (dperson/torproxy) for accessing `.onion` relays.

### Core Architecture Patterns

**Connection Pooling Strategy:**
- Each service creates its own asyncpg connection pools (NOT shared across processes/threads)
- Monitor: One pool per worker process (`min_size=2, max_size=5` per worker)
- Synchronizer/Priority: One pool per worker thread (`min_size=2, max_size=5` per thread)
- All services connect through PgBouncer (port 6432) which provides an additional pooling layer
- This design reduces database connections by ~80% compared to direct connections

**Async/Concurrency Model:**
- Monitor uses `multiprocessing.Pool` with async functions (`asyncio.run()` per process)
- Synchronizers use `threading.Thread` with dedicated event loops per thread
- All I/O operations (database, HTTP, WebSocket) use asyncio
- Graceful shutdown via `multiprocessing.Event` or `threading.Event`

**Database Access Pattern:**
- All services use the `Bigbrotr` class ([src/bigbrotr.py](src/bigbrotr.py)) as an async database wrapper
- Connection pools are created per worker (process or thread), not globally
- Context managers (`async with`) for automatic connection lifecycle management
- Stored procedures for all inserts (deduplication handled by database)

### Database Schema (PostgreSQL 15)

**Core Tables:**
- `events`: Nostr events (id, pubkey, created_at, kind, tags, content, sig)
- `relays`: Relay registry (url, network, inserted_at)
- `events_relays`: Junction table tracking event distribution across relays
- `nip11`: Deduplicated NIP-11 relay information (SHA-256 hash PK)
- `nip66`: Deduplicated NIP-66 connection test results (SHA-256 hash PK)
- `relay_metadata`: Time-series snapshots linking relays to metadata

**Views:**
- `relay_metadata_latest`: Latest metadata snapshot per relay
- `readable_relays`: Relays marked as readable in latest metadata

**Stored Procedures** (see [init.sql](init.sql)):
- `insert_event()`: Atomic event insertion with relay tracking
- `insert_relay()`: Upsert relay (ON CONFLICT DO NOTHING)
- `insert_relay_metadata()`: Insert metadata with hash-based deduplication
- `delete_orphan_events()`: Cleanup events without relay associations

### Key Source Files

**Core Classes:**
- [src/bigbrotr.py](src/bigbrotr.py): Async database wrapper using asyncpg (connection pooling, all DB operations)
- [src/config.py](src/config.py): Centralized configuration loading and validation
- [src/functions.py](src/functions.py): Shared utilities (chunking, connection testing, retry logic, `RelayFailureTracker`)
- [src/constants.py](src/constants.py): System-wide constants and defaults

**Service Entrypoints:**
- [src/monitor.py](src/monitor.py): Monitor service main loop
- [src/synchronizer.py](src/synchronizer.py): Synchronizer service main loop
- [src/priority_synchronizer.py](src/priority_synchronizer.py): Priority synchronizer main loop
- [src/initializer.py](src/initializer.py): Database initialization

**Supporting Modules:**
- [src/process_relay.py](src/process_relay.py): Relay processing logic for synchronizers
- [src/relay_loader.py](src/relay_loader.py): Fetch relays from database or files
- [src/healthcheck.py](src/healthcheck.py): HTTP health check server for all services
- [src/logging_config.py](src/logging_config.py): Logging configuration

## Configuration

All configuration is via environment variables in `.env` (see [env.example](env.example) for reference).

**First-Time Setup:**
1. Copy `env.example` to `.env`: `cp env.example .env`
2. Generate Nostr keypair and add to `SECRET_KEY` and `PUBLIC_KEY` (64 hex chars each)
3. Change all `CHANGE_ME` password placeholders in `.env`
4. Adjust `*_NUM_CORES` based on your CPU (default: 8 cores per service)
5. Ensure `seed_relays.txt` and `priority_relays.txt` exist

**Critical Settings:**
- `SECRET_KEY` / `PUBLIC_KEY`: Nostr keypair for signed requests (64 hex chars each)
- `POSTGRES_PASSWORD`, `PGBOUNCER_ADMIN_PASSWORD`, `PGADMIN_DEFAULT_PASSWORD`: Change before deployment
- `*_NUM_CORES`: Number of CPU cores per service (monitor, synchronizer, priority_synchronizer)
- `*_REQUESTS_PER_CORE`: Parallel requests per core/thread
- `SYNCHRONIZER_RELAY_METADATA_THRESHOLD_HOURS`: Only sync relays with metadata fresher than X hours (default: 12)
- `SYNCHRONIZER_START_TIMESTAMP`: 0 = genesis, -1 = resume from last sync
- `SYNCHRONIZER_STOP_TIMESTAMP`: -1 = now (continuous)
- `*_LOOP_INTERVAL_MINUTES`: Sleep interval between service loops (default: 15)

**Database Pooling:**
- Service-level pools: `MONITOR_DB_MIN_POOL`, `MONITOR_DB_MAX_POOL` (default: 2-5 per worker)
- PgBouncer: Configured in [pgbouncer.ini](pgbouncer.ini) (1000 max clients, 100 default pool size)

## Best Practices

### Adding New Features

**When modifying database schema:**
1. Update [init.sql](init.sql) with new tables/functions
2. Create migration SQL if needed (no migration framework in use)
3. Update `Bigbrotr` class methods in [src/bigbrotr.py](src/bigbrotr.py)
4. Rebuild database: `docker-compose down -v && docker-compose up -d`

**When adding new services:**
1. Create service module in `src/`
2. Add Dockerfile in `dockerfiles/`
3. Add service definition to [docker-compose.yml](docker-compose.yml)
4. Add configuration loader in [src/config.py](src/config.py)
5. Add health check endpoint using `HealthCheckServer` class
6. Document environment variables in [env.example](env.example)

**When modifying async code:**
- Always use `async with` for connection pools and clients
- Use `asyncio.run()` or create event loops explicitly (no top-level await in services)
- Handle `asyncio.CancelledError` for graceful shutdown
- Use `asyncio.create_task()` for concurrent operations
- Never share connection pools across processes/threads

### Error Handling

- Services use `RelayFailureTracker` to monitor relay processing success rates
- Alert threshold: 10% failure rate (configurable)
- Retry logic with exponential backoff: `connect_bigbrotr_with_retry()` (5 retries)
- Graceful shutdown on SIGTERM/SIGINT via `shutdown_event`
- Health checks return 503 during startup, 200 when ready

### Connection Pool Management

**Critical Rule:** Never share asyncpg pools across processes or threads. Each worker must create its own pool.

```python
# CORRECT: Pool per worker
def worker_thread(config):
    async def run():
        async with Bigbrotr(...) as db:  # Creates pool
            # Use db connection
            pass
    asyncio.run(run())

# INCORRECT: Sharing pool across workers
db = Bigbrotr(...)  # Global pool
await db.connect()
# Then using db in multiple threads/processes
```

### Logging

- Use [src/logging_config.py](src/logging_config.py): `setup_logging(service_name)`
- Services log to stdout (captured by Docker)
- Log levels: INFO for normal operations, WARNING for recoverable issues, ERROR for failures

### Testing Changes

1. Modify code in `src/`
2. Rebuild specific service: `docker-compose build monitor`
3. Restart service: `docker-compose up -d monitor`
4. Check logs: `docker-compose logs -f monitor`
5. Verify health: `curl http://localhost:8081/health`

## Recent Improvements (November 1, 2025)

### Session 1: Critical Bug Fixes & Performance (7 tasks completed)
**Critical Bug Fixes:**
- ✅ Fixed inverted connection state validation in [process_relay.py](src/process_relay.py) - function now works correctly with async context managers
- ✅ Replaced private `pool._pool` access in [monitor.py](src/monitor.py) - future-proof against library updates
- ✅ Fixed race condition in health checks - replaced `service_ready` boolean with `asyncio.Event()` in all services
- ✅ Added connection pool timeout handling - all `pool.acquire()` calls now have 30s timeout to prevent deadlocks

**Performance Improvements:**
- ✅ Optimized `get_start_time_async()` - reduced database queries from 3 to 1 (66% reduction) using JOIN query
- ✅ Removed unused pandas dependency - saves ~100MB in Docker images

**Code Quality:**
- ✅ Added comprehensive module-level docstrings to 7+ core files
- ✅ Added `DB_POOL_ACQUIRE_TIMEOUT` constant in [constants.py](src/constants.py)

### Session 2: Configuration & Code Quality (5 tasks completed)
**Configuration Improvements:**
- ✅ Enhanced environment variable validation in [config.py](src/config.py)
  - Added validation helpers: `_validate_non_empty_string()`, `_validate_url()`, `_validate_hex_key()`
  - Comprehensive validation for all config loaders (empty strings, URL formats, hex keys, JSON structure)
  - Configuration errors now fail fast at startup with descriptive error messages

**Code Quality & Maintainability:**
- ✅ Extracted magic numbers to [constants.py](src/constants.py)
  - Added 13 new constants: retry settings, timeouts, defaults, thresholds
  - Updated 8 files to use constants: [functions.py](src/functions.py), [config.py](src/config.py), [monitor.py](src/monitor.py), [synchronizer.py](src/synchronizer.py), [priority_synchronizer.py](src/priority_synchronizer.py), [initializer.py](src/initializer.py), [process_relay.py](src/process_relay.py)
  - Clearer intent, easier to tune behavior
- ✅ Added `NetworkType` enum for network types
  - Created enum with `CLEARNET` and `TOR` values
  - Updated 3 services to use `NetworkType.TOR` instead of string literals
  - Better type safety, prevents typos
- ✅ Removed unused import from [process_relay.py](src/process_relay.py)

**Overall Progress:** 12/78 tasks completed (15% → previous session was 9%)

**See [TODO.md](TODO.md) for full task list and progress tracking.**

## Important Notes

- **Finder service is disabled** ([docker-compose.yml](docker-compose.yml):95-123): Implementation incomplete. Re-enable when relay discovery logic is fully implemented.
- **No type hints enforcement yet**: Codebase uses some type hints but not comprehensive. Improvements planned.
- **No test suite**: Unit and integration tests are on the roadmap.
- **Resource limits**: Docker resource limits are configured in [docker-compose.yml](docker-compose.yml) (adjust based on hardware).
- **PgBouncer transaction pooling**: Prepared statements are not supported. Use parameterized queries with `$1, $2, ...` syntax.
- **Nostr library**: Uses `nostr-tools` 1.2.1 (custom Python library, not the JavaScript one).
- **Storage requirements**: Plan for 100GB+ for event archival; database grows continuously over time.
- **RAM recommendation**: 8GB+ recommended for production use with default core settings.
- **Connection pool timeouts**: All database operations have 30-second timeout for connection acquisition
