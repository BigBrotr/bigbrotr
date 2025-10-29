# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Last Updated**: 2025-10-29 (Post-Critical Fixes)

## Project Overview

Bigbrotr is a full-network archival system for the Nostr protocol. It continuously monitors, archives, and analyzes all public events across both clearnet and Tor relays. The system provides deep insights into relay behavior, event redundancy, network topology, and relay health metrics.

**Built with [nostr-tools](https://pypi.org/project/nostr-tools/)**: Bigbrotr leverages the nostr-tools Python library (v1.2.1) for all Nostr protocol interactions, including event validation, relay communication, and metadata fetching.

## Recent Critical Fixes (2025-10-29)

✅ **All critical issues have been resolved**:
1. **Database Schema Alignment**: `bigbrotr.py` now correctly matches the normalized NIP-11/NIP-66 schema
2. **Event Loop Optimization**: Synchronizers now reuse event loops per thread instead of creating new ones per relay
3. **Connection Pool Efficiency**: Database connections are pooled per thread, reducing connections from 400+ to 80-400 total
4. **Finder Health Checks**: Added health check endpoints to finder service (port 8084)
5. **Startup Performance**: `wait_for_services()` now checks immediately instead of waiting 30 seconds

See `IMPROVEMENTS_ROADMAP.md` for 89 additional improvements planned.

## Architecture

Bigbrotr uses a **microservices architecture** with Docker containers coordinating through a shared PostgreSQL database with PgBouncer connection pooling. Each service runs independently and handles a specific aspect of network archival.

### Core Services

All services are fully async using `asyncpg` with proper connection pooling, graceful shutdown handlers (SIGTERM/SIGINT), and health check endpoints.

1. **Initializer** (`src/initializer.py`)
   - Runs once on startup
   - Seeds the database with initial relay URLs from `seed_relays.txt`
   - Uses `Bigbrotr.insert_relay_batch()` to bulk insert relays
   - Connects directly to database (not through PgBouncer)
   - Uses async file I/O with context managers

2. **Finder** (`src/finder.py`)
   - Discovers new relays across the network
   - Periodically runs based on `FINDER_FREQUENCY_HOUR`
   - Health check endpoint: `http://localhost:8084/health` and `/ready` ✅ NEW
   - Framework in place for:
     - Fetching kind 10002 (relay list metadata) events
     - Parsing NIP-11 documents for relay cross-references
     - Extracting relay URLs from event tags
   - Implements graceful shutdown with `shutdown_flag` and `service_ready`

3. **Monitor** (`src/monitor.py`)
   - Tests relay health and connectivity
   - Uses `nostr-tools.fetch_relay_metadata()` to get NIP-11 and NIP-66 data
   - Uses multiprocessing with configurable cores and chunk sizes
   - Tests relay capabilities (openable, readable, writable, RTT) via nostr-tools
   - Stores results in normalized `relay_metadata` table with timestamped snapshots
   - Health check endpoint: `http://localhost:8081/health` and `/ready`
   - Each worker process creates own connection pool (2-5 connections)
   - Event loop created once per worker process and reused

4. **Synchronizer** (`src/synchronizer.py`)
   - Main event archival service
   - Fetches events from relays with `readable = TRUE` and recent metadata
   - Processes relays in parallel using multiprocessing + threading + async
   - **Optimized**: Creates ONE event loop per thread (reused across all relays) ✅
   - **Optimized**: Creates ONE database pool per thread (reused across all relays) ✅
   - Uses `process_relay()` with custom optimized batching and pagination logic
   - Validates events using nostr-tools Event class
   - Excludes relays listed in `priority_relays.txt`
   - Health check endpoint: `http://localhost:8082/health` and `/ready`
   - Proper timeout handling with `asyncio.wait_for()`
   - Configurable batch size and metadata threshold
   - Checks `shutdown_flag` in worker threads for graceful shutdown

5. **Priority Synchronizer** (`src/priority_synchronizer.py`)
   - Identical to synchronizer but exclusively processes relays in `priority_relays.txt`
   - Allows high-priority relays to be processed with dedicated resources
   - **Optimized**: Same event loop and connection pool improvements as synchronizer ✅
   - Health check endpoint: `http://localhost:8083/health` and `/ready`
   - Full event processing implementation with timeout protection
   - Checks `shutdown_flag` in worker threads for graceful shutdown

### Infrastructure Services

6. **PgBouncer** (`pgbouncer`)
   - Connection pooling layer between services and PostgreSQL
   - Transaction pooling mode for optimal performance
   - Configuration: 1000 max clients, 25 default pool size, 100 max DB connections
   - Userlist generated dynamically from environment variables at runtime
   - All worker services connect via `pgbouncer:6432`

7. **TorProxy** (`torproxy`)
   - SOCKS5 proxy for accessing .onion relays
   - Used by monitor and synchronizer services
   - Configured via `TORPROXY_HOST` and `TORPROXY_PORT`

### Core Classes

- **Bigbrotr** (`src/bigbrotr.py`): Async database wrapper using `asyncpg` with connection pooling. Provides methods for inserting events, relays, and metadata in batches. Handles conversion between nostr-tools data structures and PostgreSQL schema. Uses async context managers for automatic cleanup. **Updated**: Now correctly matches normalized NIP-11/NIP-66 schema with `nip11_present` and `nip66_present` flags.

- **HealthCheckServer** (`src/healthcheck.py`): Lightweight HTTP server for health checks. Provides `/health` (liveness) and `/ready` (readiness) endpoints for Kubernetes/Docker health probes. Used by all long-running services (monitor, synchronizer, priority_synchronizer, finder).

- **Event** (from `nostr-tools`): Nostr event dataclass with automatic validation (ID verification, signature verification). Imported directly from nostr-tools.

- **Relay** (from `nostr-tools`): Relay dataclass that auto-detects network type (clearnet vs tor) from URL. Imported directly from nostr-tools.

- **RelayMetadata** (from `nostr-tools`): Relay metadata with nested `Nip11` (relay information) and `Nip66` (connection/performance data) structures. Imported directly from nostr-tools.

### Database Schema

The database uses PostgreSQL 15 (Alpine) with a **normalized schema** (v2.0):

**Core Tables**:
- **events**: Stores all Nostr events (id, pubkey, created_at, kind, tags, content, sig)
- **relays**: Relay registry (url, network, inserted_at)
- **events_relays**: Junction table tracking which relays host which events (event_id, relay_url, seen_at)

**Normalized Metadata Tables** (NEW):
- **nip11**: Deduplicated NIP-11 relay information (hash-based deduplication)
- **nip66**: Deduplicated NIP-66 connection test results (hash-based deduplication)
- **relay_metadata**: Time-series snapshots linking relays to NIP-11/NIP-66 data (composite PK: relay_url + generated_at)

**Benefits of Normalized Schema**:
- Reduces duplication when multiple relays share same NIP-11 metadata
- Reduces duplication when same relay has identical metadata across multiple snapshots
- Uses SHA-256 hash-based primary keys for NIP-11 and NIP-66 tables
- Stored procedures handle deduplication automatically

Constraint: Events cannot exist without at least one relay reference. Use `delete_orphan_events()` to clean up orphaned events.

The schema includes stored procedures for batch operations:
- `insert_event()`: Inserts event + relay + events_relays relation atomically
- `insert_relay()`: Inserts relay with conflict handling
- `insert_relay_metadata()`: Inserts relay metadata snapshot with automatic NIP-11/NIP-66 deduplication
- `delete_orphan_nip11()`: Cleanup unused NIP-11 records
- `delete_orphan_nip66()`: Cleanup unused NIP-66 records

**Views**:
- `relay_metadata_latest`: Latest metadata per relay (joins with NIP-11 and NIP-66)
- `readable_relays`: Relays with readable=TRUE in latest test (sorted by RTT)

## Development Commands

### Docker Services

Start all services:
```bash
docker-compose up -d
```

Stop all services (graceful shutdown within 1 second):
```bash
docker-compose down
```

View logs for a specific service:
```bash
docker-compose logs -f <service_name>
# Examples: initializer, finder, monitor, synchronizer, priority_synchronizer, pgbouncer
```

Rebuild a service after code changes:
```bash
docker-compose up -d --build <service_name>
```

### Health Checks

Check service health (all services now have health endpoints):
```bash
curl http://localhost:8081/health  # Monitor
curl http://localhost:8082/health  # Synchronizer
curl http://localhost:8083/health  # Priority Synchronizer
curl http://localhost:8084/health  # Finder (NEW ✅)

# Check readiness (returns 200 OK when ready, 503 when not)
curl http://localhost:8081/ready
curl http://localhost:8082/ready
curl http://localhost:8083/ready
curl http://localhost:8084/ready
```

### Database Access

Connect to PostgreSQL directly:
```bash
docker exec -it bigbrotr_database psql -U $POSTGRES_USER -d $POSTGRES_DB
```

Connect via PgBouncer:
```bash
docker exec -it bigbrotr_database psql -U $POSTGRES_USER -d bigbrotr -h pgbouncer -p 6432
```

Check connection pool usage:
```bash
docker exec -it bigbrotr_pgbouncer psql -p 6432 -U admin pgbouncer -c "SHOW POOLS;"
```

Access pgAdmin web UI:
- Navigate to `http://localhost:8080` (or your configured `PGADMIN_PORT`)
- Login with credentials from `.env`

### Python Dependencies

Dependencies are managed via `requirements.txt`:
- `nostr-tools==1.2.1`: Nostr protocol library providing Event, Relay, Client, and utility functions
- `asyncpg==0.29.0`: Async PostgreSQL adapter (replaces psycopg2)
- `aiohttp==3.9.3`: Async HTTP client (used by nostr-tools and health checks)
- `aiohttp-socks==0.8.4`: Tor proxy support (used by nostr-tools)
- `secp256k1`: Nostr signature verification (used by nostr-tools)
- `bech32`: Nostr key encoding (used by nostr-tools)
- `pandas==2.2.3`: Data processing
- `typing-extensions==4.9.0`: Extended type hints

## Configuration

All services are configured via environment variables in `.env` (see `env.example` for template):

### Critical Settings

- **Tor Support**: The `torproxy` service runs automatically. Monitor and synchronizer services use `TORPROXY_HOST` and `TORPROXY_PORT` to connect to `.onion` relays

- **Nostr Keypair**: `SECRET_KEY` and `PUBLIC_KEY` are used by the monitor service for signed AUTH requests. Must be valid Nostr keypair (64 hex chars each).

- **Parallelization**: All services use configurable core counts and request limits:
  - Monitor: `MONITOR_NUM_CORES`, `MONITOR_REQUESTS_PER_CORE`, `MONITOR_CHUNK_SIZE`, `MONITOR_LOOP_INTERVAL_MINUTES`
  - Synchronizer: `SYNCHRONIZER_NUM_CORES`, `SYNCHRONIZER_REQUESTS_PER_CORE`, `SYNCHRONIZER_LOOP_INTERVAL_MINUTES`
  - Priority Synchronizer: `PRIORITY_SYNCHRONIZER_NUM_CORES` (shares other synchronizer settings)

- **Batch Configuration**:
  - `SYNCHRONIZER_BATCH_SIZE`: Number of events to fetch per pagination request (default: 500)
  - `SYNCHRONIZER_RELAY_METADATA_THRESHOLD_HOURS`: Only sync relays with metadata newer than this (default: 12)

- **Time Range**: Synchronizer can be bounded with `SYNCHRONIZER_START_TIMESTAMP` and `SYNCHRONIZER_STOP_TIMESTAMP` (use -1 for "now")

- **Event Filtering**: `SYNCHRONIZER_EVENT_FILTER` accepts JSON filters (e.g., `{"kinds": [0, 1, 3]}`)

- **File Paths**:
  - `SEED_RELAYS_PATH`: Initial relay list for initializer (default: `./seed_relays.txt`)
  - `SYNCHRONIZER_PRIORITY_RELAYS_PATH`: High-priority relays (default: `./priority_relays.txt`)

## Key Implementation Patterns

### Async Architecture

All services use fully async code with `asyncpg`:
- Async context managers for automatic resource cleanup
- Connection pooling (configurable min/max per service)
- Proper error handling with async exception patterns
- No blocking operations in async code

Example pattern:
```python
async with Bigbrotr(host, port, user, password, dbname) as db:
    await db.insert_event_batch(events, relay)
```

### Graceful Shutdown

All services implement graceful shutdown:
- Signal handlers for SIGTERM and SIGINT
- Global `shutdown_flag` checked in main loops and worker threads
- Sleep intervals use 1-second polling for quick response
- Cleanup code in `finally` blocks
- Responds to shutdown within 1 second
- Health server properly stopped in `finally` block

Example pattern:
```python
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

shutdown_flag = False
service_ready = False

def signal_handler(signum: int, frame) -> None:
    global shutdown_flag
    shutdown_flag = True

# In main loop:
while not shutdown_flag:
    # Do work...
    for _ in range(sleep_seconds):
        if shutdown_flag:
            break
        await asyncio.sleep(1)
```

### Optimized Multiprocessing Pattern (NEW ✅)

Services use a three-level concurrency model with **optimized resource management**:

1. **Process-level**: Multiple worker processes (`Pool` or `Process`)
2. **Thread-level**: Multiple threads per process (`threading.Thread`)
3. **Async-level**: Async tasks within threads (reusing event loop)

**Key Optimization**: Each thread creates resources ONCE and reuses them:

```python
def worker_thread(config, shared_queue, end_time):
    """Worker thread with optimized resource management."""
    # Create event loop ONCE per thread (not per relay)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Create database pool ONCE per thread (not per relay)
    db = Bigbrotr(
        config["database_host"],
        config["database_port"],
        config["database_user"],
        config["database_password"],
        config["database_name"],
        min_pool_size=2,
        max_pool_size=5
    )

    try:
        # Connect pool once
        loop.run_until_complete(db.connect())

        # Process multiple relays, reusing loop and pool
        while not shutdown_flag:
            relay = shared_queue.get(timeout=1)
            loop.run_until_complete(process_relay(db, relay, ...))

    finally:
        # Cleanup resources
        loop.run_until_complete(db.close())
        loop.close()
```

**Benefits**:
- **Before**: 10 threads × 8 cores × 5 connections = 400 connections
- **After**: 10 threads × 8 cores × 1 pool = 80 pools (80-400 connections total)
- **Savings**: Up to 80% reduction in database connections
- **Performance**: No event loop creation/destruction overhead per relay

Example flow (monitor.py):
- Split relays into chunks
- Assign chunks to worker processes
- Each process spawns threads
- **Each thread creates ONE event loop and ONE database pool**
- Thread reuses loop and pool for all relays it processes
- Results are batch-inserted to the database

### Database Interaction

Always use the `Bigbrotr` class wrapper instead of raw SQL. Batch operations are significantly more efficient:
- Use `insert_event_batch()` instead of calling `insert_event()` in a loop
- Use `insert_relay_metadata_batch()` for bulk metadata insertion
- All insert operations use `ON CONFLICT DO NOTHING` for idempotency
- Always use async context managers: `async with Bigbrotr(...) as db:`

**Important**: When calling `insert_relay_metadata()`, the function automatically:
- Detects if NIP-11 and NIP-66 objects are present
- Computes SHA-256 hashes for deduplication
- Inserts to normalized tables (nip11, nip66, relay_metadata)
- Reuses existing NIP-11/NIP-66 records when hashes match

### Connection Pooling Strategy

- **PgBouncer**: Transaction pooling mode, 1000 max clients, 25 default pool, 100 max DB connections
- **Per Thread** (OPTIMIZED ✅): Each worker thread creates ONE pool with 2-5 connections, reused across all relays
- **Initializer**: Direct connection (no PgBouncer) since it runs once
- **All other services**: Connect via `pgbouncer:6432`

### Error Handling

Services are resilient to failures:
- Database/Tor connections checked immediately on startup (no 30-second delay ✅)
- `wait_for_services()` only sleeps between retry attempts, not before first check
- Individual relay failures are logged but don't crash the service
- Services run in loops with configurable sleep intervals between runs
- Timeout protection on all relay operations (`asyncio.wait_for()`)
- Proper cleanup even on exceptions (async context managers)

### Health Checks

All long-running services provide health endpoints:
- `/health`: Liveness probe - returns 200 if process is running
- `/ready`: Readiness probe - returns 200 when service is ready, 503 when initializing
- Services set `service_ready = True` after successful initialization
- Health server runs in background using `aiohttp.web`
- Health server properly stopped in `finally` block during shutdown

**Port Mapping**:
- Monitor: 8081
- Synchronizer: 8082
- Priority Synchronizer: 8083
- Finder: 8084 (NEW ✅)

## Code Locations

- Event processing: `src/process_relay.py` (custom optimized WebSocket handling with nostr-tools Event validation)
- Utility functions: `src/functions.py` (database/network utilities, all async)
- Database adapter: `src/bigbrotr.py` (async wrapper using asyncpg, converts nostr-tools objects to PostgreSQL)
- Health checks: `src/healthcheck.py` (lightweight HTTP server for Kubernetes/Docker probes)
- Logging configuration: `src/logging_config.py` (centralized logging setup)
- Configuration: `src/config.py` (environment variable loading with validation)
- Constants: `src/constants.py` (shared constants like pool sizes, timeouts, logging prefixes)
- Relay loading: `src/relay_loader.py` (database and file-based relay fetching)
- Service entry points: `src/initializer.py`, `src/finder.py`, `src/monitor.py`, `src/synchronizer.py`, `src/priority_synchronizer.py`

## Using nostr-tools in Bigbrotr

### Importing from nostr-tools

All Nostr protocol classes and functions are imported from `nostr-tools`:

```python
from nostr_tools import Event, Relay, RelayMetadata, Client, Filter
from nostr_tools import fetch_events, stream_events, fetch_relay_metadata
from nostr_tools import generate_keypair, validate_keypair, sanitize
```

### RelayMetadata Structure

The nostr-tools `RelayMetadata` has a nested structure:
- `relay`: Relay instance
- `generated_at`: Unix timestamp
- `nip11`: Optional `Nip11` object with relay information (name, description, supported_nips, etc.)
- `nip66`: Optional `Nip66` object with connection data (openable, readable, writable, rtt_*)

When inserting to database, `Bigbrotr.insert_relay_metadata()` automatically:
1. Detects if `nip11` and `nip66` objects are present (uses boolean flags)
2. Computes SHA-256 hashes of NIP-11 and NIP-66 data
3. Inserts to normalized `nip11` and `nip66` tables (with deduplication)
4. Creates reference in `relay_metadata` table with foreign keys to deduplicated records

### Event Validation

Events from nostr-tools are automatically validated on creation:
- ID verification (SHA-256 hash check)
- Signature verification (Schnorr signature)
- Type checking and format validation

Use `Event.from_dict(data)` to parse relay responses - validation happens automatically.

### Client Configuration

When creating clients for relay connections:

```python
# For clearnet relays
client = Client(relay=relay, timeout=timeout)

# For Tor relays (.onion)
socks5_proxy_url = f"socks5://{torhost}:{torport}"
client = Client(
    relay=relay,
    timeout=timeout,
    socks5_proxy_url=socks5_proxy_url if relay.network == "tor" else None
)
```

Always use async context managers:
```python
async with client:
    # Client automatically connects
    await process_relay(db, client, event_filter)
    # Client automatically disconnects
```

## Best Practices

### Adding New Services

When adding a new service:
1. Import and use `from healthcheck import HealthCheckServer`
2. Add signal handlers for graceful shutdown with `shutdown_flag` and `service_ready`
3. Use `async with Bigbrotr(...)` for database access
4. Add health check port mapping in `docker-compose.yml`
5. Use centralized logging: `from logging_config import setup_logging`
6. Check `shutdown_flag` in main loops AND worker threads
7. Sleep in 1-second intervals for quick shutdown response
8. Connect via PgBouncer (`pgbouncer:6432`) unless one-time initialization
9. Start health server BEFORE long-running initialization
10. Stop health server in `finally` block

Example template:
```python
import asyncio
import signal
from healthcheck import HealthCheckServer
from constants import HEALTH_CHECK_PORT

shutdown_flag = False
service_ready = False

def signal_handler(signum, frame):
    global shutdown_flag
    shutdown_flag = True

async def my_service():
    global service_ready

    # Start health server
    async def is_ready():
        return service_ready

    health_server = HealthCheckServer(port=HEALTH_CHECK_PORT, ready_check=is_ready)
    await health_server.start()

    try:
        # Initialize
        await wait_for_services(config)
        service_ready = True

        # Main loop
        while not shutdown_flag:
            # Work...
            pass

    finally:
        await health_server.stop()

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    asyncio.run(my_service())
```

### Database Operations

- Always use async context managers
- Prefer batch operations over individual inserts
- Validate input parameters in public methods
- Handle exceptions and log appropriately
- Use `nip11_present` and `nip66_present` boolean flags when inserting metadata
- Let stored procedures handle NIP-11/NIP-66 deduplication automatically

### Concurrency

- Use multiprocessing for CPU-intensive work
- Use threading for I/O-bound work within processes
- Use asyncio for network I/O
- **Create event loop ONCE per thread, reuse across all tasks** ✅
- **Create database pool ONCE per thread, reuse across all relays** ✅
- Use semaphores to control concurrent async operations
- Never share database connections across process boundaries
- Never share event loops across threads

### Timeout Handling

Always wrap relay operations in timeouts:
```python
relay_timeout = config["timeout"] * RELAY_TIMEOUT_MULTIPLIER  # Usually 2x
await asyncio.wait_for(
    process_relay(db, client, event_filter),
    timeout=relay_timeout
)
```

## Troubleshooting

### Service Won't Start
- Check health endpoint: `curl http://localhost:808X/ready`
- View logs: `docker-compose logs -f <service_name>`
- Verify environment variables in `.env`
- Ensure PgBouncer and database are running
- Check that service waits for dependencies (no 30-second delay anymore ✅)

### Connection Pool Exhausted
- Check PgBouncer stats: `docker exec -it bigbrotr_pgbouncer psql -p 6432 -U admin pgbouncer -c "SHOW POOLS;"`
- **After optimization, this should be rare** (80% reduction in connections ✅)
- Adjust `max_pool_size` in worker processes if needed
- Increase PgBouncer limits in `pgbouncer.ini`

### Relay Processing Slow
- Increase `SYNCHRONIZER_NUM_CORES`
- Increase `SYNCHRONIZER_REQUESTS_PER_CORE`
- Adjust `SYNCHRONIZER_BATCH_SIZE`
- Check relay metadata freshness threshold
- Verify optimal connection pooling is working (check worker thread logs)

### Memory Issues
- Reduce `MONITOR_CHUNK_SIZE`
- Reduce `SYNCHRONIZER_BATCH_SIZE`
- Decrease connection pool sizes per thread
- Monitor with `docker stats`
- Check for event loop or connection pool leaks (should be fixed ✅)

### Schema Mismatch Errors
- If you see errors about `connection_success` or `nip11_success` parameters, this is from old code
- **This has been fixed** - make sure you're using latest `bigbrotr.py` ✅
- The new schema uses `nip11_present` and `nip66_present` boolean flags
- Verify stored procedure signature matches: `insert_relay_metadata(... p_nip66_present BOOLEAN, ...)`

## Known Limitations & Future Work

See `IMPROVEMENTS_ROADMAP.md` for comprehensive list of 89 planned improvements including:

- **High Priority** (12 items): Remove deprecated code, optimize queries, add validation
- **Performance** (10 items): Relay-specific batch sizes, Redis caching, prepared statements
- **Security** (10 items): Docker secrets, SSL/TLS, rate limiting, container scanning
- **Operational** (14 items): Monitoring dashboards, log aggregation, backup automation
- **Code Quality** (10 items): Type hints, unit tests, documentation
- **Documentation** (10 items): API docs, architecture diagrams, runbooks
- **Features** (4 items): Event search API, relay discovery implementation, uptime tracking

Total estimated time: 25-45 days for all improvements.

## Version History

See `FIXES_SUMMARY.md` for detailed critical fixes (2025-10-29).
See `CHANGELOG.md` for full version history and changes.

## References

- [Nostr Protocol NIPs](https://github.com/nostr-protocol/nips)
- [NIP-01: Basic Protocol](https://github.com/nostr-protocol/nips/blob/master/01.md)
- [NIP-11: Relay Information Document](https://github.com/nostr-protocol/nips/blob/master/11.md)
- [NIP-66: Relay Monitoring](https://github.com/nostr-protocol/nips/blob/master/66.md)
- [Nostr Tools (Python)](https://github.com/jeffthibault/python-nostr-tools)
- [asyncpg Documentation](https://magicstack.github.io/asyncpg/)
- [PgBouncer Documentation](https://www.pgbouncer.org/)
