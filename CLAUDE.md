# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Bigbrotr is a full-network archival system for the Nostr protocol. It continuously monitors, archives, and analyzes all public events across both clearnet and Tor relays. The system provides deep insights into relay behavior, event redundancy, network topology, and relay health metrics.

**Built with [nostr-tools](https://pypi.org/project/nostr-tools/)**: Bigbrotr leverages the nostr-tools Python library (v1.2.0) for all Nostr protocol interactions, including event validation, relay communication, and metadata fetching.

## Architecture

Bigbrotr uses a **microservices architecture** with Docker containers coordinating through a shared PostgreSQL database. Each service runs independently and handles a specific aspect of network archival:

### Core Services

1. **Initializer** (`src/initializer.py`)
   - Runs once on startup
   - Seeds the database with initial relay URLs from `seed_relays.txt`
   - Uses `Bigbrotr.insert_relay_batch()` to bulk insert relays

2. **Finder** (`src/finder.py`)
   - Discovers new relays across the network
   - Periodically runs based on `FINDER_FREQUENCY_HOUR`
   - Currently stubbed out (TODO: implement relay discovery logic)

3. **Monitor** (`src/monitor.py`)
   - Tests relay health and connectivity
   - Uses `nostr-tools.fetch_relay_metadata()` to get NIP-11 and NIP-66 data
   - Uses multiprocessing with configurable cores and chunk sizes
   - Tests relay capabilities (openable, readable, writable, RTT) via nostr-tools
   - Stores results in `relay_metadata` table with timestamped snapshots

4. **Synchronizer** (`src/synchronizer.py`)
   - Main event archival service
   - Fetches all events from relays with `readable = TRUE`
   - Processes relays in parallel using multiprocessing + threading
   - Uses `process_relay()` with custom optimized batching and pagination logic
   - Validates events using nostr-tools Event class
   - Excludes relays listed in `priority_relays.txt`

5. **Priority Synchronizer** (`src/priority_synchronizer.py`)
   - Identical to synchronizer but exclusively processes relays in `priority_relays.txt`
   - Allows high-priority relays to be processed with dedicated resources

### Core Classes

- **Bigbrotr** (`src/bigbrotr.py`): Database wrapper with methods for inserting events, relays, and metadata in batches. Handles conversion between nostr-tools data structures and PostgreSQL schema.
- **Event** (from `nostr-tools`): Nostr event dataclass with automatic validation (ID verification, signature verification). Imported directly from nostr-tools.
- **Relay** (from `nostr-tools`): Relay dataclass that auto-detects network type (clearnet vs tor) from URL. Imported directly from nostr-tools.
- **RelayMetadata** (from `nostr-tools`): Relay metadata with nested `Nip11` (relay information) and `Nip66` (connection/performance data) structures. Imported directly from nostr-tools.

### Database Schema

The database uses PostgreSQL with three main tables:

- **events**: Stores all Nostr events (id, pubkey, created_at, kind, tags, content, sig)
- **relays**: Relay registry (url, network, inserted_at)
- **events_relays**: Junction table tracking which relays host which events (event_id, relay_url, seen_at)
- **relay_metadata**: Historical snapshots of relay health/capabilities (composite PK on relay_url + generated_at)

Constraint: Events cannot exist without at least one relay reference. Use `delete_orphan_events()` to clean up orphaned events.

The schema includes stored procedures for batch operations:
- `insert_event()`: Inserts event + relay + events_relays relation atomically
- `insert_relay()`: Inserts relay with conflict handling
- `insert_relay_metadata()`: Inserts relay metadata snapshot

## Development Commands

### Docker Services

Start all services:
```bash
docker-compose up -d
```

Stop all services:
```bash
docker-compose down
```

View logs for a specific service:
```bash
docker-compose logs -f <service_name>
# Examples: initializer, finder, monitor, synchronizer, priority_synchronizer
```

Rebuild a service after code changes:
```bash
docker-compose up -d --build <service_name>
```

### Database Access

Connect to PostgreSQL:
```bash
docker exec -it bigbrotr_database psql -U $POSTGRES_USER -d $POSTGRES_DB
```

Access pgAdmin web UI:
- Navigate to `http://localhost:8080` (or your configured `PGADMIN_PORT`)
- Login with credentials from `.env`

### Python Dependencies

Dependencies are managed via `requirements.txt`:
- `nostr-tools==1.2.0`: Nostr protocol library providing Event, Relay, Client, and utility functions
- `psycopg2-binary`: PostgreSQL adapter
- `aiohttp`: Async HTTP client (used by nostr-tools and custom WebSocket code)
- `aiohttp_socks`: Tor proxy support (used by nostr-tools)
- `secp256k1`: Nostr signature verification (used by nostr-tools)
- `bech32`: Nostr key encoding (used by nostr-tools)
- `pandas`: Data processing
- `requests`: HTTP requests

## Configuration

All services are configured via environment variables in `.env` (see `env.example` for template):

### Critical Settings

- **Tor Support**: The `torproxy` service runs automatically. Monitor and synchronizer services use `TORPROXY_HOST` and `TORPROXY_PORT` to connect to `.onion` relays
- **Nostr Keypair**: `SECRET_KEY` and `PUBLIC_KEY` are used by the monitor service for signed AUTH requests
- **Parallelization**: All services use configurable core counts and request limits:
  - Monitor: `MONITOR_NUM_CORES`, `MONITOR_REQUESTS_PER_CORE`, `MONITOR_CHUNK_SIZE`
  - Synchronizer: `SYNCHRONIZER_NUM_CORES`, `SYNCHRONIZER_REQUESTS_PER_CORE`
- **Time Range**: Synchronizer can be bounded with `SYNCHRONIZER_START_TIMESTAMP` and `SYNCHRONIZER_STOP_TIMESTAMP` (use -1 for "now")
- **Event Filtering**: `SYNCHRONIZER_EVENT_FILTER` accepts JSON filters (e.g., `{"kinds": [0, 1, 3]}`)

## Key Implementation Patterns

### Multiprocessing Pattern

Services use a three-level concurrency model:
1. **Process-level**: Multiple worker processes (`Pool` or `Process`)
2. **Thread-level**: Multiple threads per process (`threading.Thread`)
3. **Async-level**: Semaphore-controlled async tasks within threads (`asyncio.Semaphore`)

Example flow (monitor.py):
- Split relays into chunks
- Assign chunks to worker processes
- Each process spawns threads with semaphore-controlled async tasks
- Results are batch-inserted to the database

### Database Interaction

Always use the `Bigbrotr` class wrapper instead of raw SQL. Batch operations are significantly more efficient:
- Use `insert_event_batch()` instead of calling `insert_event()` in a loop
- Use `insert_relay_metadata_batch()` for bulk metadata insertion
- All insert operations use `ON CONFLICT DO NOTHING` for idempotency

### Error Handling

Services are resilient to failures:
- Database/Tor connections retry with exponential backoff (`wait_for_services()`)
- Individual relay failures are logged but don't crash the service
- Services run in infinite loops with sleep intervals between runs

## Code Locations

- Event processing: `src/process_relay.py` (custom optimized WebSocket handling with nostr-tools Event validation)
- Utility functions: `src/functions.py` (database/network utilities)
- Database adapter: `src/bigbrotr.py` (converts nostr-tools objects to PostgreSQL)
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

When inserting to database, `Bigbrotr.insert_relay_metadata()` automatically extracts nested data and flattens it for PostgreSQL.

### Event Validation

Events from nostr-tools are automatically validated on creation:
- ID verification (SHA-256 hash check)
- Signature verification (Schnorr signature)
- Type checking and format validation

Use `Event.from_dict(data)` to parse relay responses - validation happens automatically.
