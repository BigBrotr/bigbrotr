# BigBrotr Project - Complete Technical Documentation

## Project Overview

**BigBrotr** is a distributed Nostr network archival system designed to discover, monitor, and synchronize events from Nostr relays across both clearnet and Tor networks. The system provides comprehensive relay monitoring, metadata collection (NIP-11/NIP-66), and event archival capabilities.

### Architecture Type
- **Microservices Architecture**: 7 independent services orchestrated via Docker Compose
- **Database-Centric**: PostgreSQL 15 with normalized schema and optimized indexing
- **Connection Pooling**: PgBouncer in transaction mode for efficient database access
- **Multi-Process/Multi-Threaded**: Concurrent processing using Python multiprocessing and threading

---

## System Components

### 1. Database (PostgreSQL 15)
**Purpose**: Central data store for events, relays, and metadata

**Schema Design**:
- **Core Tables**: `relays`, `events`, `events_relays`
- **Metadata Tables**: `nip11`, `nip66`, `relay_metadata`
- **Normalization**: NIP-11 and NIP-66 data deduplicated using SHA-256 hashing
- **Indexes**: 15 specialized indexes for query optimization

**Key Features**:
- Stored procedures: `insert_event`, `insert_relay`, `insert_relay_metadata`
- Utility functions: `delete_orphan_events`, `delete_orphan_nip11`, `delete_orphan_nip66`
- Hash functions: `compute_nip11_hash`, `compute_nip66_hash`
- Views: `relay_metadata_latest`, `readable_relays`

**Performance Configuration**:
- `shared_buffers`: 16GB
- `effective_cache_size`: 48GB
- `max_connections`: 300
- `max_worker_processes`: 300
- `max_parallel_workers`: 300

### 2. PgBouncer
**Purpose**: Connection pooling and traffic management

**Configuration**:
- **Pool Mode**: `transaction` (optimal for microservices)
- **Authentication**: SCRAM-SHA-256
- **Connection Limits**: 1000 max clients, 25 default pool size
- **Timeouts**: Server idle (600s), server lifetime (3600s)

**Why Transaction Mode**:
- No prepared statements (disabled in BigBrotr client)
- Better resource utilization
- Handles bursty workloads effectively

### 3. Tor Proxy (dperson/torproxy)
**Purpose**: Provides SOCKS5 proxy for accessing .onion relays

**Integration**:
- SOCKS5 proxy at `torproxy:9050`
- Automatic network detection in `Relay` class
- Conditional proxy usage based on relay URL

### 4. Initializer Service
**Purpose**: One-time database seeding with initial relay list

**Implementation**: [src/initializer.py](src/initializer.py)

**Process**:
1. Wait for database availability
2. Read `seed_relays.txt` (8,865 relay URLs)
3. Validate relay URLs
4. Batch insert using `BigBrotr.insert_relay_batch()`
5. Exit (`restart: no`)

### 5. Finder Service
**Purpose**: Relay discovery (currently pending implementation)

**Implementation**: [src/finder.py](src/finder.py)

**Planned Features**:
- Query events for kind 10002 (relay list metadata)
- Extract relay URLs from event tags
- Fetch from aggregator websites (nostr.watch, relay.exchange)
- Insert discovered relays to database

**Current Status**: Skeleton with health check server, awaiting full implementation

### 6. Monitor Service
**Purpose**: Relay health monitoring and metadata collection

**Implementation**: [src/monitor.py](src/monitor.py)

**Architecture**:
- **Multiprocessing**: `num_cores` processes
- **Per-Process**: Multiple async requests (`requests_per_core`)
- **Database**: Each worker has its own connection pool (2-5 connections)

**Process Flow**:
1. Fetch relays needing metadata updates (frequency_hour threshold)
2. Split into chunks (`chunk_size`)
3. Distribute chunks across worker processes
4. Each worker:
   - Fetches relay metadata (NIP-11, NIP-66)
   - Measures RTT (round-trip time)
   - Batch inserts metadata
5. Repeat every `loop_interval_minutes`

**Configuration**:
- Frequency: Every 8 hours (default)
- Chunk Size: 50 relays per worker
- Concurrent Requests: 10 per core
- Health Check: Port 8080

### 7. Synchronizer Service
**Purpose**: Event synchronization from readable relays

**Implementation**: [src/synchronizer.py](src/synchronizer.py)

**Architecture**:
- **Multiprocessing**: `num_cores` processes
- **Threading**: `requests_per_core` threads per process
- **Queue-Based**: Shared queue for relay distribution

**Process Flow**:
1. Fetch readable relays from database (with metadata < threshold_hours)
2. Load priority relays from file (excluded from standard sync)
3. Create shared queue with all relays
4. Spawn worker processes:
   - Each process spawns worker threads
   - Each thread:
     - Gets relay from queue
     - Determines start_time from last seen event
     - Creates Filter (since, until, batch_size)
     - Processes relay using binary search algorithm
     - Inserts events in batches
5. Repeat every `loop_interval_minutes`

**Binary Search Algorithm**: [src/process_relay.py](src/process_relay.py:155)
- Handles pagination limits intelligently
- Detects relay behavior inconsistencies
- Optimizes event retrieval efficiency

**Configuration**:
- Start Timestamp: 0 (from beginning)
- Stop Timestamp: -1 (current time - 1 day)
- Batch Size: 500 events
- Event Filter: `{}` (all events)

### 8. Priority Synchronizer Service
**Purpose**: Dedicated synchronization for high-priority relays

**Implementation**: [src/priority_synchronizer.py](src/priority_synchronizer.py)

**Differences from Standard Synchronizer**:
- Reads exclusively from `priority_relays.txt`
- Same architecture and algorithm
- Separate resource allocation
- Independent scheduling

**Use Case**: Ensure critical relays (e.g., relay.damus.io, nos.lol) are always up-to-date

---

## Core Library: BigBrotr Database Wrapper

**File**: [src/bigbrotr.py](src/bigbrotr.py)

**Purpose**: Async database abstraction with connection pooling

**Key Features**:
- **Connection Pool**: asyncpg-based with configurable size
- **Context Manager**: `async with BigBrotr(...) as db`
- **Type Safety**: Extensive type checking and validation
- **Batch Operations**: Optimized for bulk inserts
- **Error Handling**: Comprehensive exception management

**Methods**:
- `insert_event()` / `insert_event_batch()` - Event insertion
- `insert_relay()` / `insert_relay_batch()` - Relay insertion
- `insert_relay_metadata()` / `insert_relay_metadata_batch()` - Metadata insertion
- `execute()`, `fetch()`, `fetchone()` - Generic query execution

**Connection Pool Configuration**:
- Disabled prepared statements (PgBouncer transaction mode compatibility)
- Configurable min/max pool sizes per worker
- Command timeout: 60 seconds

---

## nostr-tools Library (v1.4.0) - Complete Reference

### Overview

**nostr-tools** is a comprehensive Python library developed by BigBrotr for building Nostr protocol applications. Version 1.4.0 provides production-ready async APIs with full NIP-01, NIP-11, and NIP-66 support.

### Installation
```bash
pip install nostr-tools==1.4.0
```

### Core Classes

#### 1. Event
**Purpose**: Represents Nostr events

**Properties**:
- `id` (str): SHA-256 event ID (64 hex chars)
- `pubkey` (str): Author's public key (64 hex chars)
- `created_at` (int): Unix timestamp
- `kind` (int): Event type (0-65535)
- `tags` (List[List[str]]): Tag arrays
- `content` (str): Event content
- `sig` (str): Schnorr signature (128 hex chars)

**Methods**:
- `Event.from_dict(data: dict) -> Event` - Deserialize from dict
- `event.to_dict() -> dict` - Serialize to dict
- `event.is_valid -> bool` - Validation property
- `event.has_tag(tag_name: str) -> bool` - Check tag existence
- `event.get_tag_values(tag_name: str) -> List[str]` - Extract tag values

**Example**:
```python
from nostr_tools import Event

event_dict = {
    "id": "abc123...",
    "pubkey": "def456...",
    "created_at": 1234567890,
    "kind": 1,
    "tags": [["t", "nostr"]],
    "content": "Hello Nostr!",
    "sig": "789xyz..."
}

event = Event.from_dict(event_dict)
if event.is_valid:
    print(f"Valid event: {event.content}")
```

#### 2. Relay
**Purpose**: Represents relay connections

**Properties**:
- `url` (str): WebSocket URL (wss:// or ws://)
- `network` (str): "clearnet" or "tor" (auto-detected)
- `is_valid` (bool): URL validation

**Methods**:
- `Relay(url: str)` - Constructor with validation
- `relay.to_dict() -> dict` - Serialize
- `Relay.from_dict(data: dict) -> Relay` - Deserialize

**Network Detection**:
```python
from nostr_tools import Relay

clearnet_relay = Relay("wss://relay.damus.io")
print(clearnet_relay.network)  # "clearnet"

tor_relay = Relay("wss://oxtr...onion")
print(tor_relay.network)  # "tor"
```

#### 3. Client
**Purpose**: WebSocket client for relay communication

**Constructor**:
```python
Client(
    relay: Relay,
    timeout: int = 10,
    socks5_proxy_url: Optional[str] = None
)
```

**Properties**:
- `client.relay` - Associated Relay instance
- `client.is_connected` - Connection status
- `client.is_valid` - Validation state
- `client.active_subscriptions` - Current subscription IDs

**Methods**:
- `async connect()` - Establish WebSocket connection
- `async disconnect()` - Close connection
- `async publish(event: Event) -> bool` - Publish event
- `subscribe(filter: Filter) -> str` - Create subscription (returns ID)
- `unsubscribe(subscription_id: str)` - Cancel subscription
- `async listen_events(subscription_id: str) -> AsyncGenerator` - Event stream

**Context Manager**:
```python
async with Client(relay, timeout=10) as client:
    # Automatic connect/disconnect
    subscription_id = client.subscribe(filter)
    async for message in client.listen_events(subscription_id):
        print(message)
```

#### 4. Filter
**Purpose**: Event query criteria

**Properties**:
- `ids` (Optional[List[str]]): Event IDs
- `authors` (Optional[List[str]]): Author pubkeys
- `kinds` (Optional[List[int]]): Event kinds
- `since` (Optional[int]): Unix timestamp (inclusive)
- `until` (Optional[int]): Unix timestamp (inclusive)
- `limit` (Optional[int]): Max results
- Tag filters: `#e`, `#p`, `#t`, etc. (as dict keys with `#` prefix)

**Methods**:
- `Filter(**kwargs)` - Constructor
- `filter.to_dict() -> dict` - Serialize
- `filter.is_valid` - Validation property

**Example**:
```python
from nostr_tools import Filter

# Text notes from specific author in last 24 hours
filter = Filter(
    kinds=[1],
    authors=["pubkey..."],
    since=int(time.time()) - 86400,
    limit=100
)

# Events tagged with specific event ID
filter_with_tags = Filter(
    kinds=[1, 6, 7],
    **{"#e": ["event_id..."]}
)
```

#### 5. RelayMetadata
**Purpose**: Comprehensive relay information

**Properties**:
- `relay` (Relay): Associated relay
- `generated_at` (int): Timestamp
- `nip11` (Optional[Nip11]): NIP-11 information document
- `nip66` (Optional[Nip66]): NIP-66 test results
- `is_valid` (bool): Validation property

**Sub-Classes**:

**Nip11** (Relay Information Document):
- `name`, `description`, `banner`, `icon` (str)
- `pubkey`, `contact` (str)
- `supported_nips` (List[int])
- `software`, `version` (str)
- `privacy_policy`, `terms_of_service` (str)
- `limitation` (dict): Rate limits, file size, etc.
- `extra_fields` (dict): Custom fields

**Nip66** (Connection Test Results):
- `openable` (bool): WebSocket opens successfully
- `readable` (bool): Accepts REQ subscriptions
- `writable` (bool): Accepts EVENT messages
- `rtt_open` (int): WebSocket handshake RTT (ms)
- `rtt_read` (int): REQ/EOSE cycle RTT (ms)
- `rtt_write` (int): EVENT/OK cycle RTT (ms)

### Key Functions

#### Cryptography

**generate_keypair() -> Tuple[str, str]**
```python
from nostr_tools import generate_keypair

private_key, public_key = generate_keypair()
```

**to_bech32(key: str, prefix: str) -> str**
```python
from nostr_tools import to_bech32

nsec = to_bech32(private_key, "nsec")
npub = to_bech32(public_key, "npub")
```

**from_bech32(encoded: str) -> str**
```python
from nostr_tools import from_bech32

private_key = from_bech32(nsec)
public_key = from_bech32(npub)
```

**validate_keypair(private_key: str, public_key: str) -> bool**
```python
from nostr_tools import validate_keypair

if validate_keypair(sk, pk):
    print("Valid keypair!")
```

#### Event Operations

**generate_event(private_key: str, public_key: str, kind: int, tags: List[List[str]], content: str) -> dict**
```python
from nostr_tools import generate_event

event_dict = generate_event(
    private_key=sk,
    public_key=pk,
    kind=1,
    tags=[["t", "test"]],
    content="Hello World"
)
```

**fetch_events(client: Client, filter: Filter) -> List[Event]**
```python
from nostr_tools import fetch_events

async with Client(relay) as client:
    events = await fetch_events(client, filter)
```

**stream_events(client: Client, filter: Filter) -> AsyncGenerator[Event, None]**
```python
from nostr_tools import stream_events

async with Client(relay) as client:
    async for event in stream_events(client, filter):
        print(event.content)
```

#### Relay Testing

**check_connectivity(client: Client) -> Tuple[bool, Optional[int]]**
```python
from nostr_tools import check_connectivity

async with Client(relay) as client:
    is_open, rtt_ms = await check_connectivity(client)
```

**check_readability(client: Client) -> Tuple[bool, Optional[int]]**
```python
from nostr_tools import check_readability

async with Client(relay) as client:
    can_read, rtt_ms = await check_readability(client)
```

**check_writability(client: Client, event: Event) -> Tuple[bool, Optional[int]]**
```python
from nostr_tools import check_writability

async with Client(relay) as client:
    can_write, rtt_ms = await check_writability(client, test_event)
```

**fetch_nip11(relay: Relay, timeout: int = 10) -> Optional[Nip11]**
```python
from nostr_tools import fetch_nip11

nip11 = await fetch_nip11(relay)
if nip11:
    print(f"Relay: {nip11.name}")
```

**fetch_relay_metadata(client: Client) -> RelayMetadata**
```python
from nostr_tools import fetch_relay_metadata, Client

async with Client(relay, timeout=20) as client:
    metadata = await fetch_relay_metadata(client)
    print(f"Openable: {metadata.nip66.openable}")
    print(f"Readable: {metadata.nip66.readable}")
    print(f"RTT: {metadata.nip66.rtt_read}ms")
```

#### Utility Functions

**sanitize(data: Any) -> Any**
```python
from nostr_tools import sanitize

# Removes potentially dangerous content
clean_data = sanitize(untrusted_input)
```

### Advanced Usage Patterns

#### 1. Multi-Relay Broadcasting
```python
relays = [
    Relay("wss://relay.damus.io"),
    Relay("wss://nos.lol"),
    Relay("wss://relay.nostr.band")
]

event = Event.from_dict(generate_event(...))

results = []
for relay in relays:
    async with Client(relay) as client:
        success = await client.publish(event)
        results.append((relay.url, success))
```

#### 2. Event Filtering with Tags
```python
# Find all reactions to a specific note
filter = Filter(
    kinds=[7],  # Reaction kind
    **{"#e": ["note_id_here"]},
    limit=1000
)

async with Client(relay) as client:
    reactions = await fetch_events(client, filter)
    print(f"Found {len(reactions)} reactions")
```

#### 3. Tor Relay Connection
```python
tor_relay = Relay("wss://oxtr...onion")
socks5_url = "socks5://torproxy:9050"

async with Client(tor_relay, timeout=30, socks5_proxy_url=socks5_url) as client:
    # Automatically routes through Tor
    events = await fetch_events(client, Filter(kinds=[1], limit=10))
```

#### 4. Batch Event Processing
```python
from bigbrotr import BigBrotr

events = [Event.from_dict(e) for e in event_dicts]
relay = Relay("wss://relay.example.com")

async with BigBrotr(host, port, user, password, dbname) as db:
    await db.insert_event_batch(
        events=events,
        relay=relay,
        seen_at=int(time.time())
    )
```

---

## Configuration Management

### Environment Variables

**File**: [src/config.py](src/config.py)

**Configuration Loaders**:
- `load_monitor_config()` - Monitor service
- `load_synchronizer_config()` - Synchronizer/Priority Synchronizer
- `load_finder_config()` - Finder service
- `load_initializer_config()` - Initializer service

**Validation Functions**:
- `_validate_port(port, name)` - Port range (0-65535)
- `_validate_positive(value, name)` - Positive integers

**Special Handling**:
- CPU core validation (warns if exceeds available cores)
- Keypair validation (uses `nostr_tools.validate_keypair()`)
- Event filter JSON parsing and NIP-01 key filtering
- Priority relays file auto-creation

### Constants

**File**: [src/constants.py](src/constants.py)

**Categories**:
- Database: `DB_POOL_MIN_SIZE_PER_WORKER`, `DB_POOL_MAX_SIZE_PER_WORKER`
- Health: `HEALTH_CHECK_PORT`
- Time: `SECONDS_PER_HOUR`, `SECONDS_PER_DAY`
- Relay: `RELAY_TIMEOUT_MULTIPLIER`
- Binary Search: `BINARY_SEARCH_MIN_RANGE`
- Tor: `TOR_CHECK_HTTP_URL`, `TOR_CHECK_WS_URL`
- Logging: Emoji prefixes for log parsing

---

## Utility Functions

### File: [src/functions.py](src/functions.py)

#### RelayFailureTracker
**Purpose**: Monitor and alert on relay processing failures

**Usage**:
```python
tracker = RelayFailureTracker(alert_threshold=0.1, check_interval=100)

# In processing loop
try:
    process_relay(relay)
    tracker.record_success()
except Exception:
    tracker.record_failure()

# Get statistics
stats = tracker.get_stats()
print(f"Failure rate: {stats['failure_rate']:.1%}")
```

**Features**:
- Configurable alert threshold (default: 10%)
- Periodic status logging
- Comprehensive statistics

#### chunkify()
```python
def chunkify(lst: List[T], n: int) -> Generator[List[T], None, None]
```
**Purpose**: Split list into equal chunks for parallel processing

#### test_database_connection_async()
```python
async def test_database_connection_async(
    host: str, port: int, user: str, password: str, dbname: str, logger=None
) -> bool
```

#### connect_bigbrotr_with_retry()
```python
async def connect_bigbrotr_with_retry(
    bigbrotr: BigBrotr, max_retries: int = 5, base_delay: int = 1, logger=None
) -> None
```
**Purpose**: Exponential backoff retry logic for database connections

#### test_torproxy_connection()
```python
async def test_torproxy_connection(
    host: str, port: int, timeout: int = 10, logger=None
) -> bool
```

#### wait_for_services()
```python
async def wait_for_services(
    config: Dict[str, Any], retries: int = 5, delay: int = 30
) -> None
```
**Purpose**: Wait for database and Tor proxy availability before starting service

### File: [src/relay_loader.py](src/relay_loader.py)

#### fetch_relays_from_database()
```python
async def fetch_relays_from_database(
    config: Dict[str, Any],
    threshold_hours: int = 12,
    readable_only: bool = True,
    shuffle: bool = True
) -> List[Relay]
```
**Purpose**: Fetch relays with recent metadata

**SQL Optimization**: Uses window functions (ROW_NUMBER) instead of correlated subqueries

#### fetch_relays_from_file()
```python
async def fetch_relays_from_file(filepath: str, shuffle: bool = True) -> List[Relay]
```
**Purpose**: Load relays from text file (supports comments with #)

#### fetch_all_relays_from_database()
```python
async def fetch_all_relays_from_database(config: Dict[str, Any]) -> List[Relay]
```

#### fetch_relays_needing_metadata()
```python
async def fetch_relays_needing_metadata(
    config: Dict[str, Any], frequency_hours: int
) -> List[Relay]
```
**Purpose**: Find relays with outdated or missing metadata

**SQL Optimization**: Uses LATERAL join for better performance

### File: [src/process_relay.py](src/process_relay.py)

#### get_start_time_async()
```python
async def get_start_time_async(
    default_start_time: int,
    bigbrotr: BigBrotr,
    relay: Relay,
    retries: int = 5,
    delay: int = 30
) -> int
```
**Purpose**: Determine starting timestamp for synchronization (last seen event + 1)

**Logic**:
1. Get MAX(seen_at) for relay
2. Find event_id at that timestamp
3. Get created_at for that event
4. Return created_at + 1 (or default if not found)

#### insert_batch()
```python
async def insert_batch(
    bigbrotr: BigBrotr,
    batch: List[Dict[str, Any]],
    relay: Relay,
    seen_at: int
) -> int
```
**Purpose**: Batch event insertion with error handling

#### RawEventBatch
**Purpose**: Container for managing event batches during pagination

**Properties**:
- `since`, `until`, `limit` - Filter parameters
- `raw_events` - List of raw event dicts
- `min_created_at`, `max_created_at` - Timestamp bounds

**Methods**:
- `append(raw_event)` - Add event (returns False if full or invalid)
- `is_full()` - Check capacity
- `is_empty()` - Check if no events

#### process_batch()
```python
async def process_batch(client: Client, filter: Filter) -> RawEventBatch
```
**Purpose**: Fetch one batch of events

#### process_relay()
```python
async def process_relay(bigbrotr: BigBrotr, client: Client, filter: Filter) -> None
```
**Purpose**: Complete relay synchronization using binary search algorithm

**Binary Search Logic**:
1. Fetch [since, until] interval
2. If empty → mark interval done
3. If full AND single timestamp → insert and continue
4. If full AND multiple timestamps:
   - Fetch [since, min_created_at]
   - Validate relay behavior
   - If more events exist before min → split interval
   - If only min_created_at events → fetch [since, min-1]
   - Continue splitting until all events retrieved

**Why Binary Search**:
- Handles relay limit restrictions
- Detects relay misbehavior
- Optimizes network roundtrips

---

## Health Check System

**File**: [src/healthcheck.py](src/healthcheck.py)

**Class**: `HealthCheckServer`

**Endpoints**:
- `GET /health` - Liveness probe (returns 200 if running)
- `GET /ready` - Readiness probe (calls optional `ready_check` callback)
- `GET /` - Service info

**Usage**:
```python
async def is_ready():
    return service_ready

health_server = HealthCheckServer(port=8080, ready_check=is_ready)
await health_server.start()

# Later
await health_server.stop()
```

**Docker Integration**:
```yaml
healthcheck:
  test: ["CMD-SHELL", "wget --no-verbose --tries=1 --spider http://localhost:8080/health || exit 1"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 30s
```

---

## Logging System

**File**: [src/logging_config.py](src/logging_config.py)

**Function**: `setup_logging(service_name: str, level: str = "INFO")`

**Configuration**:
- Format: `%(asctime)s - {service_name} - %(levelname)s - %(message)s`
- Handler: `StreamHandler(sys.stdout)` (Docker-friendly)
- Noise Reduction: aiohttp and asyncio set to WARNING

**Service Names**:
- `FINDER`, `MONITOR`, `SYNCHRONIZER`, `PRIORITY_SYNCHRONIZER`, `INITIALIZER`

---

## Docker Configuration

### Multi-Stage Builds

All Python services use optimized multi-stage Dockerfiles:

**Stage 1 (Build)**:
- Base: `python:3.11-alpine`
- Install build dependencies: build-base, libffi-dev, openssl-dev
- Install Python packages to `/install`

**Stage 2 (Runtime)**:
- Base: `python:3.11-alpine`
- Copy only `/install` from build stage
- Install runtime dependencies: libffi, openssl
- Create non-root user `bigbrotr:bigbrotr` (UID/GID 1000)
- Copy application code
- Health checks (where applicable)

**Benefits**:
- Smaller image size (no build tools in runtime)
- Security (non-root user)
- Layer caching efficiency

### Service Dependencies

**Dependency Graph**:
```
database
 ├── pgbouncer
 ├── initializer
 └── (all services)

pgbouncer
 ├── finder
 ├── monitor
 ├── synchronizer
 └── priority_synchronizer

torproxy
 ├── finder
 ├── monitor
 ├── synchronizer
 └── priority_synchronizer
```

### Resource Limits

**Database**:
- CPUs: 1-4 cores
- Memory: 512MB-4GB

**Monitor/Synchronizers**:
- CPUs: 1-6 cores
- Memory: 512MB-4GB

---

## Deployment Guide

### Prerequisites
- Docker 20.10+
- Docker Compose 2.0+
- 8GB+ RAM recommended
- SSD storage for PostgreSQL

### Quick Start

1. **Clone Repository**:
```bash
git clone https://github.com/bigbrotr/bigbrotr.git
cd bigbrotr
```

2. **Configure Environment**:
```bash
cp env.example .env
nano .env
```

**Critical Variables**:
```env
# Security (CHANGE THESE!)
POSTGRES_PASSWORD=your_strong_password_here
PGBOUNCER_ADMIN_PASSWORD=another_strong_password
PGADMIN_DEFAULT_PASSWORD=yet_another_strong_password

# Nostr Keys (for signed requests)
SECRET_KEY=your_64_hex_char_private_key
PUBLIC_KEY=your_64_hex_char_public_key
```

3. **Generate Nostr Keypair**:
```python
from nostr_tools import generate_keypair, to_bech32

sk, pk = generate_keypair()
print(f"SECRET_KEY={sk}")
print(f"PUBLIC_KEY={pk}")
```

4. **Customize Relay Lists**:
```bash
nano seed_relays.txt        # Initial relays
nano priority_relays.txt     # High-priority relays
```

5. **Start Services**:
```bash
docker-compose up -d
```

6. **Monitor Logs**:
```bash
docker-compose logs -f
```

7. **Verify Health**:
```bash
curl http://localhost:8081/health  # Monitor
curl http://localhost:8082/health  # Synchronizer
curl http://localhost:8083/health  # Priority Synchronizer
curl http://localhost:8084/health  # Finder
```

### Service Management

**Stop All Services**:
```bash
docker-compose down
```

**Stop Without Removing Volumes**:
```bash
docker-compose stop
```

**Restart Specific Service**:
```bash
docker-compose restart monitor
```

**View Service Logs**:
```bash
docker-compose logs -f synchronizer
```

**Rebuild After Code Changes**:
```bash
docker-compose up -d --build
```

---

## Database Management

### Accessing Database

**Via psql**:
```bash
docker exec -it bigbrotr_database psql -U admin -d bigbrotr
```

**Via PgBouncer**:
```bash
psql "host=localhost port=6432 user=admin dbname=bigbrotr"
```

**Via pgAdmin**:
- URL: http://localhost:8080
- Email: admin@example.com (from .env)
- Password: (from PGADMIN_DEFAULT_PASSWORD)

### Useful Queries

**Count Events**:
```sql
SELECT COUNT(*) FROM events;
```

**Count Relays**:
```sql
SELECT COUNT(*) FROM relays;
SELECT network, COUNT(*) FROM relays GROUP BY network;
```

**Latest Relay Metadata**:
```sql
SELECT * FROM relay_metadata_latest LIMIT 10;
```

**Readable Relays**:
```sql
SELECT * FROM readable_relays;
```

**Top Relays by Event Count**:
```sql
SELECT relay_url, COUNT(*) as event_count
FROM events_relays
GROUP BY relay_url
ORDER BY event_count DESC
LIMIT 10;
```

**Recent Events**:
```sql
SELECT id, kind, created_at, content
FROM events
ORDER BY created_at DESC
LIMIT 10;
```

**Relay Statistics**:
```sql
SELECT
    r.url,
    r.network,
    COUNT(DISTINCT er.event_id) as event_count,
    rm.generated_at as last_check,
    n66.readable,
    n66.rtt_read
FROM relays r
LEFT JOIN events_relays er ON r.url = er.relay_url
LEFT JOIN relay_metadata_latest rm ON r.url = rm.relay_url
LEFT JOIN nip66 n66 ON rm.nip66_id = n66.id
GROUP BY r.url, r.network, rm.generated_at, n66.readable, n66.rtt_read
ORDER BY event_count DESC;
```

### Maintenance

**Delete Orphan Events**:
```sql
SELECT delete_orphan_events();
```

**Delete Orphan Metadata**:
```sql
SELECT delete_orphan_nip11();
SELECT delete_orphan_nip66();
```

**Vacuum Database**:
```bash
docker exec -it bigbrotr_database psql -U admin -d bigbrotr -c "VACUUM ANALYZE;"
```

---

## Troubleshooting

### Database Connection Issues

**Symptom**: Services can't connect to database

**Solutions**:
1. Check database is running: `docker ps | grep database`
2. Check health: `docker exec bigbrotr_database pg_isready -U admin`
3. Verify credentials in .env
4. Check logs: `docker-compose logs database`

### Tor Proxy Timeouts

**Symptom**: .onion relay connections timeout

**Solutions**:
1. Increase timeouts in .env:
   ```env
   MONITOR_REQUEST_TIMEOUT=30
   SYNCHRONIZER_REQUEST_TIMEOUT=30
   ```
2. Check Tor proxy: `docker logs bigbrotr_torproxy`
3. Test connectivity: `docker exec bigbrotr_torproxy wget -qO- https://check.torproject.org/api/ip`

### High CPU Usage

**Symptom**: Services consuming too many resources

**Solutions**:
1. Reduce worker counts:
   ```env
   MONITOR_NUM_CORES=4
   SYNCHRONIZER_NUM_CORES=4
   ```
2. Reduce concurrency:
   ```env
   MONITOR_REQUESTS_PER_CORE=5
   SYNCHRONIZER_REQUESTS_PER_CORE=5
   ```
3. Increase loop intervals:
   ```env
   MONITOR_LOOP_INTERVAL_MINUTES=30
   SYNCHRONIZER_LOOP_INTERVAL_MINUTES=30
   ```

### Disk Space Issues

**Symptom**: Database filling disk

**Solutions**:
1. Enable auto-vacuum in postgresql.conf
2. Implement retention policy:
   ```sql
   DELETE FROM events WHERE created_at < EXTRACT(EPOCH FROM NOW() - INTERVAL '90 days');
   SELECT delete_orphan_events();
   VACUUM FULL;
   ```
3. Monitor disk usage: `docker exec bigbrotr_database df -h`

### PgBouncer Connection Errors

**Symptom**: "prepared statement does not exist"

**Solution**: Already handled - BigBrotr disables prepared statements:
```python
self.pool = await asyncpg.create_pool(
    ...
    statement_cache_size=0  # Required for PgBouncer transaction mode
)
```

---

## Performance Optimization

### Database Tuning

**Index Maintenance**:
```sql
REINDEX INDEX CONCURRENTLY idx_events_pubkey;
REINDEX INDEX CONCURRENTLY idx_events_created_at;
REINDEX INDEX CONCURRENTLY idx_events_relays_relay_seen;
```

**Statistics Update**:
```sql
ANALYZE events;
ANALYZE events_relays;
ANALYZE relay_metadata;
```

**Connection Pool Sizing**:
- Monitor active connections: `SELECT count(*) FROM pg_stat_activity;`
- Adjust PgBouncer `default_pool_size` if needed
- Adjust worker pool sizes in .env:
  ```env
  MONITOR_DB_MIN_POOL=2
  MONITOR_DB_MAX_POOL=5
  SYNCHRONIZER_DB_MIN_POOL=2
  SYNCHRONIZER_DB_MAX_POOL=5
  ```

### Synchronizer Optimization

**Batch Size Tuning**:
- Small batches (100-200): More roundtrips, better real-time performance
- Large batches (500-1000): Fewer roundtrips, better throughput
- Current default: 500

**Relay Selection**:
- Use `threshold_hours` to sync only healthy relays
- Prioritize low-latency relays (sort by nip66.rtt_read)

### Monitor Optimization

**Chunk Size**:
```env
MONITOR_CHUNK_SIZE=50  # Increase for fewer workers, decrease for more parallelism
```

**Request Timeout**:
```env
MONITOR_REQUEST_TIMEOUT=20  # Increase for slow relays, decrease for faster feedback
```

---

## Security Considerations

### Network Isolation

**Best Practice**: Create isolated Docker network
```yaml
networks:
  network:
    driver: bridge
    internal: false  # Set to true for complete isolation
```

### Secrets Management

**Do NOT commit**:
- `.env` file
- Private keys
- Passwords

**Use**:
- Docker secrets (Swarm mode)
- Kubernetes secrets
- External secret managers (Vault, AWS Secrets Manager)

### Database Security

1. **Change default passwords** (POSTGRES_PASSWORD, PGBOUNCER_ADMIN_PASSWORD)
2. **Restrict network access**: Bind PostgreSQL to localhost or Docker network only
3. **Enable SSL** for production:
   ```yaml
   database:
     environment:
       - POSTGRES_SSL_MODE=require
     volumes:
       - ./certs:/var/lib/postgresql/certs:ro
   ```
4. **Regular backups**:
   ```bash
   docker exec bigbrotr_database pg_dump -U admin bigbrotr > backup_$(date +%Y%m%d).sql
   ```

### Application Security

1. **Non-root containers**: All services run as user `bigbrotr:bigbrotr`
2. **Read-only filesystems** (optional):
   ```yaml
   synchronizer:
     read_only: true
     tmpfs:
       - /tmp
   ```
3. **Resource limits**: All services have CPU/memory limits
4. **No privileged mode**: No containers use `privileged: true`

---

## Monitoring and Observability

### Health Checks

All services expose `/health` endpoint:
```bash
curl http://localhost:8081/health  # Monitor → 200 OK
curl http://localhost:8082/health  # Synchronizer → 200 OK
curl http://localhost:8083/health  # Priority Synchronizer → 200 OK
curl http://localhost:8084/health  # Finder → 200 OK
```

### Logs

**Structured Logging Format**:
```
2025-01-03 12:34:56,789 - SYNCHRONIZER - INFO - 🔄 Processing relay wss://relay.damus.io from 1234567890 to 1234577890
```

**Emoji Prefixes**:
- ❌ Error
- ⚠️ Warning
- ✅ Success
- 📦 Info
- 🔄 Process
- ⏳ Wait
- 🚀 Start
- 🔍 Search
- 🌐 Network
- ⏰ Timer

**Log Aggregation**:
```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f synchronizer

# Filter by level
docker-compose logs synchronizer | grep ERROR

# Follow with timestamps
docker-compose logs -f --timestamps
```

### Metrics (Future Enhancement)

**Recommended**: Add Prometheus + Grafana

**Metrics to Track**:
- Events/second ingestion rate
- Relay response times
- Database connection pool utilization
- Worker process/thread counts
- Failure rates (via RelayFailureTracker)

---

## Development Guide

### Local Development Setup

1. **Install Dependencies**:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

2. **Run Database Locally**:
```bash
docker-compose up -d database pgbouncer
```

3. **Run Service**:
```bash
export POSTGRES_HOST=localhost
export POSTGRES_PORT=6432
export POSTGRES_USER=admin
export POSTGRES_PASSWORD=yourpassword
export POSTGRES_DB=bigbrotr
# ... other environment variables

python src/monitor.py
```

### Testing

**Unit Tests** (Future Enhancement):
```bash
pytest tests/
```

**Integration Tests**:
```bash
pytest tests/integration/
```

**Relay Testing**:
```python
from nostr_tools import Client, Relay, check_connectivity

relay = Relay("wss://relay.example.com")
async with Client(relay, timeout=10) as client:
    is_open, rtt = await check_connectivity(client)
    print(f"Relay: {relay.url}, Open: {is_open}, RTT: {rtt}ms")
```

### Code Quality

**Type Checking**:
```bash
mypy src/
```

**Linting**:
```bash
pylint src/
```

**Formatting**:
```bash
black src/
```

---

## API Reference Summary

### BigBrotr Database Wrapper

```python
from bigbrotr import BigBrotr

# Initialize
db = BigBrotr(host, port, user, password, dbname, min_pool_size=5, max_pool_size=20)

# Connect
await db.connect()

# Context manager (recommended)
async with BigBrotr(...) as db:
    # Insert single event
    await db.insert_event(event, relay, seen_at)

    # Insert batch
    await db.insert_event_batch(events, relay, seen_at)

    # Insert relay
    await db.insert_relay(relay, inserted_at)

    # Insert relay metadata
    await db.insert_relay_metadata(relay_metadata, relay_inserted_at)

    # Raw queries
    results = await db.fetch("SELECT * FROM relays")
    row = await db.fetchone("SELECT * FROM relays WHERE url = $1", url)
    await db.execute("DELETE FROM events WHERE id = $1", event_id)

# Close
await db.close()
```

### nostr-tools Quick Reference

```python
from nostr_tools import (
    # Classes
    Event, Relay, Client, Filter, RelayMetadata,

    # Crypto
    generate_keypair, to_bech32, from_bech32, validate_keypair,

    # Events
    generate_event, fetch_events, stream_events,

    # Relay Testing
    check_connectivity, check_readability, check_writability,
    fetch_nip11, fetch_relay_metadata,

    # Utility
    sanitize
)

# Basic workflow
private_key, public_key = generate_keypair()
relay = Relay("wss://relay.damus.io")
client = Client(relay, timeout=10)

async with client:
    # Publish
    event_dict = generate_event(private_key, public_key, kind=1, tags=[], content="Hello!")
    event = Event.from_dict(event_dict)
    await client.publish(event)

    # Query
    filter = Filter(kinds=[1], limit=10)
    events = await fetch_events(client, filter)

    # Stream
    async for event in stream_events(client, filter):
        print(event.content)
```

---

## Future Enhancements

### 1. Finder Service Implementation
- Implement kind 10002 relay list parsing
- Add aggregator website scraping (nostr.watch, relay.exchange)
- Scheduled discovery runs

### 2. Advanced Event Filtering
- NIP-12 generic tag queries
- NIP-40 expiration handling
- Event kind-specific processing

### 3. Monitoring Dashboard
- Real-time relay statistics
- Event ingestion graphs
- Network topology visualization
- Relay health maps

### 4. Data Retention Policies
- Configurable event TTL
- Automated archival to cold storage
- Selective event kind retention

### 5. Performance Improvements
- Implement connection pooling at relay level
- Add event caching layer (Redis)
- Optimize batch insert sizes dynamically
- Implement adaptive timeout adjustment

### 6. High Availability
- Multi-region deployment
- Database replication (PostgreSQL streaming replication)
- Service redundancy
- Automatic failover

### 7. API Server
- REST API for querying events
- WebSocket API for real-time subscriptions
- NIP-50 search implementation
- Rate limiting and authentication

---

## Glossary

**Nostr**: Notes and Other Stuff Transmitted by Relays - a decentralized social protocol

**Relay**: WebSocket server that stores and distributes Nostr events

**Event**: Signed JSON object containing content, metadata, and cryptographic proof

**NIP**: Nostr Implementation Possibility - protocol extension specification

**NIP-01**: Core protocol specification (events, filters, subscriptions)

**NIP-11**: Relay information document (metadata, capabilities, policies)

**NIP-66**: Relay monitoring and testing specification (connectivity, RTT)

**Clearnet**: Regular internet (wss://)

**Tor**: The Onion Router - anonymity network (.onion relays)

**SOCKS5**: Proxy protocol used for Tor connections

**RTT**: Round-Trip Time - latency measurement in milliseconds

**PgBouncer**: Connection pooler for PostgreSQL

**Multiprocessing**: Python module for spawning separate OS processes

**Async/Await**: Python coroutine syntax for concurrent I/O operations

---

## Support and Resources

### Official Links
- **Repository**: https://github.com/bigbrotr/bigbrotr
- **nostr-tools**: https://github.com/bigbrotr/nostr-tools
- **Documentation**: https://bigbrotr.github.io/

### Nostr Protocol
- **Main Site**: https://nostr.com
- **NIPs Repository**: https://github.com/nostr-protocol/nips
- **Nostr Resources**: https://nostr.net

### Community
- **Nostr Discord**: [Link if available]
- **Issue Tracker**: https://github.com/bigbrotr/bigbrotr/issues
- **Pull Requests**: https://github.com/bigbrotr/bigbrotr/pulls

---

## License

MIT License - Copyright (c) 2025 BigBrotr

See [LICENSE](LICENSE) file for details.

---

## Changelog

### Version 2.0.0 (Current)
- Normalized NIP-11/NIP-66 schema with deduplication
- Implemented comprehensive relay metadata tracking
- Added health check servers to all services
- Optimized database queries with window functions
- Enhanced error handling and logging
- Added RelayFailureTracker for monitoring
- Improved Docker multi-stage builds
- Updated to nostr-tools 1.4.0

### Version 1.x
- Initial implementation
- Basic relay synchronization
- PostgreSQL schema v1
- Simple metadata tracking

---

**Document Version**: 1.0
**Last Updated**: 2025-01-03
**Maintainer**: BigBrotr Team
