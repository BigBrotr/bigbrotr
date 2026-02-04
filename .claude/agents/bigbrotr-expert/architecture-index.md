# Architecture Index

Quick reference for BigBrotr component relationships and design patterns.

---

## Four-Layer Architecture

```
+===============================================================+
|                    Implementation Layer                       |
+---------------------------------------------------------------+
|  +--------------------+       +--------------------+          |
|  |    bigbrotr/       |       |    lilbrotr/       |          |
|  +--------------------+       +--------------------+          |
|  | - Full schema      |       | - Lightweight      |          |
|  | - All columns      |       | - Essential only   |          |
|  | - ~100% disk       |       | - ~40% disk        |          |
|  +--------------------+       +--------------------+          |
|                                                               |
+=============================+=================================+
                              |
                              v
+===============================================================+
|                      Service Layer                            |
+---------------------------------------------------------------+
|  +--------+ +--------+ +-----------+ +---------+ +----------+ |
|  | Seeder | | Finder | | Validator | | Monitor | |   Sync   | |
|  +--------+ +--------+ +-----------+ +---------+ +----------+ |
|                                                               |
+=============================+=================================+
                              |
                              v
+===============================================================+
|                        Core Layer                             |
+---------------------------------------------------------------+
|  +--------+     +--------+     +-------------+     +--------+ |
|  |  Pool  |---->| Brotr  |     | BaseService |     | Logger | |
|  +--------+     +--------+     +------+------+     +--------+ |
|                                       |                       |
|                              +--------v--------+              |
|                              | MetricsServer   |              |
|                              +-----------------+              |
+=============================+=================================+
                              |
                              v
+===============================================================+
|                         Models                                |
+---------------------------------------------------------------+
|  Event   Relay   EventRelay   RelayMetadata   Metadata        |
|  Nip11   Nip66   NetworkType  MetadataType                    |
+===============================================================+
```

---

## Component Relationships

### Core Components

**Pool** ← **Brotr** ← **Services**
- Pool: Async PostgreSQL client (connects via PGBouncer in Docker)
- Brotr: High-level database interface
- Services: Business logic using Brotr

**BaseService** ← **All Services**
- Provides lifecycle management
- Handles graceful shutdown
- Implements run_forever loop

**Logger** ← **All Components**
- Structured key=value logging
- Used by Pool, Brotr, Services

**MetricsServer** ← **BaseService**
- Prometheus /metrics HTTP endpoint
- SERVICE_INFO, SERVICE_GAUGE, SERVICE_COUNTER metrics
- CYCLE_DURATION_SECONDS histogram

### Service Dependencies

```
+----------+
|  Seeder  |  (one-shot)
+----+-----+
     |
     v
+----------+
|  Finder  |  (continuous) --> Discovers relay URLs
+----+-----+                    Stores candidates
     |
     v
+-----------+
| Validator |  (continuous) --> Validates URLs
+-----+-----+                    Inserts relays
      |
      v
+-----------+
|  Monitor  |  (continuous) --> Health checks
+-----+-----+                    NIP-11/NIP-66
      |
      v
+--------------+
| Synchronizer |  (continuous) --> Event collection
+--------------+
```

### Data Flow

```
External Sources
       |
       v
+-------------+
|   Finder    |  Discovers URLs
+------+------+
       | stores candidates
       v
+-------------+
|  Validator  |  Validates URLs
+------+------+
       | inserts relays
       v
+-------------+
|   Monitor   |  Health checks
+------+------+
       | inserts metadata
       v
+--------------+
| Synchronizer |  Collects events
+------+-------+
       | inserts events
       v
   Database
```

---

## Design Patterns

### 1. Dependency Injection

**Pattern:** Services receive dependencies via constructor

```python
# Constructor injection
class MyService(BaseService[MyServiceConfig]):
    def __init__(self, brotr: Brotr, config: MyServiceConfig | None = None):
        super().__init__(config)  # Defaults to CONFIG_CLASS() if None
        self._brotr = brotr  # Injected dependency

# Usage
service = MyService.from_yaml(config_path, brotr=brotr)
# Or with default config:
service = MyService(brotr=brotr)  # Uses MyServiceConfig()
```

**Benefits:**
- Easy mocking for tests
- Decouples components
- Supports factory pattern

---

### 2. Factory Pattern

**Pattern:** Create instances from YAML/dict configs

```python
# Factory methods on all core components
pool = Pool.from_yaml("config.yaml")
pool = Pool.from_dict(config_dict)

brotr = Brotr.from_yaml("config.yaml")
service = MyService.from_yaml("config.yaml", brotr=brotr)
```

**Benefits:**
- Consistent initialization
- Validates configuration
- Supports multiple config sources

---

### 3. Context Manager Protocol

**Pattern:** Auto-manage resource lifecycle

```python
# Pool
async with Pool.from_yaml("config.yaml") as pool:
    # Auto-connects on enter
    await pool.fetch("SELECT 1")
    # Auto-closes on exit

# Brotr
async with brotr:
    await brotr.insert_events(events)

# Service
async with service:
    # Clears shutdown event
    await service.run()
    # Sets shutdown event
```

**Benefits:**
- Automatic cleanup
- Exception safety
- Clear resource scope

---

### 4. Async-First Design

**Pattern:** All I/O operations are async

```python
# Async methods throughout
async def run(self):
    rows = await self._brotr.pool.fetch("SELECT ...")
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()
```

**Benefits:**
- High concurrency
- Non-blocking I/O
- Efficient resource usage

---

### 5. Cursor-Based Pagination

**Pattern:** Resumable processing with composite cursor

```python
# Load cursor
cursor = await brotr.get_service_data("finder", "cursor", "events")
last_timestamp = cursor[0]["value"]["timestamp"]
last_id = bytes.fromhex(cursor[0]["value"]["id"])

# Query with cursor (deterministic ordering)
query = """
    SELECT * FROM events
    WHERE (created_at > $1 OR (created_at = $1 AND id > $2))
    ORDER BY created_at ASC, id ASC
    LIMIT $3
"""

# Save new cursor
await brotr.upsert_service_data([
    ("finder", "cursor", "events", {"timestamp": ts, "id": id_hex})
])
```

**Benefits:**
- No offset/limit issues
- Handles timestamp collisions
- Survives restarts
- Efficient resumption

---

### 6. Immutable Data Objects

**Pattern:** Frozen dataclasses with custom __new__

```python
@dataclass(frozen=True)
class Relay:
    _url_without_scheme: str
    network: str
    discovered_at: Optional[int] = None

    def __new__(cls, raw: str, discovered_at: Optional[int] = None):
        # Validation and normalization
        parsed = RelayUrl.parse(raw)
        normalized = parsed.normalize()
        network = cls._detect_network(parsed.host)
        return object.__new__(cls)

# Usage
relay = Relay("wss://relay.example.com")
# relay._url_without_scheme = "..."  # ERROR: frozen
```

**Benefits:**
- No accidental mutations
- Type safety
- Validation on construction
- Safe for concurrent access

---

### 7. Stored Procedures for Mutations

**Pattern:** All database writes via stored procedures

```python
# Python side (hardcoded procedure names)
await pool.execute(
    "CALL insert_event($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)",
    event_id, pubkey, created_at, kind, tags, content, sig,
    relay_url, relay_network, relay_discovered_at, seen_at
)

# PostgreSQL side
CREATE OR REPLACE PROCEDURE insert_event(...)
AS $$
BEGIN
    INSERT INTO relays VALUES (...) ON CONFLICT DO NOTHING;
    INSERT INTO events VALUES (...) ON CONFLICT DO NOTHING;
    INSERT INTO events_relays VALUES (...) ON CONFLICT DO NOTHING;
END;
$$ LANGUAGE plpgsql;
```

**Benefits:**
- SQL injection prevention
- Atomic operations
- Database-side logic
- Consistent error handling

---

### 8. Content-Addressed Storage

**Pattern:** Deduplication via hashing

```python
# PostgreSQL function
CREATE OR REPLACE FUNCTION sha256(data JSONB) RETURNS BYTEA AS $$
    SELECT digest(data::TEXT, 'sha256')
$$ LANGUAGE SQL IMMUTABLE;

# Stored procedure
INSERT INTO metadata (id, data) VALUES (sha256($1), $1)
ON CONFLICT (id) DO NOTHING;

# Python usage
metadata = Metadata(data={"key": "value"})
await brotr.insert_relay_metadata([
    RelayMetadata(
        relay=relay,
        metadata=metadata,  # Hash computed in PostgreSQL
        metadata_type="nip11",
        snapshot_at=timestamp
    )
])
```

**Benefits:**
- Automatic deduplication
- ~90% space savings for repeated metadata
- No application-side hashing
- Guaranteed uniqueness

---

### 9. Graceful Shutdown

**Pattern:** asyncio.Event as single source of truth

```python
class BaseService:
    def __init__(self):
        self._shutdown_event = asyncio.Event()  # Single source

    def request_shutdown(self):
        """Thread-safe (sync) shutdown signal."""
        self._shutdown_event.set()

    @property
    def is_running(self) -> bool:
        """Async-safe check."""
        return not self._shutdown_event.is_set()

    async def wait(self, timeout: float) -> bool:
        """Interruptible wait."""
        try:
            await asyncio.wait_for(self._shutdown_event.wait(), timeout)
            return True  # Shutdown requested
        except asyncio.TimeoutError:
            return False  # Timeout

# Usage in service
async def run_forever(self, interval: float):
    while self.is_running:
        await self.run()
        if await self.wait(interval):
            break  # Shutdown during wait
```

**Benefits:**
- Thread-safe for signal handlers
- Atomic state checks
- Interruptible waits
- Clean resource cleanup

---

### 10. Service State as Key-Value Store

**Pattern:** Generic service_data table for all state

```python
# Generic schema
CREATE TABLE service_data (
    service_name TEXT,  -- finder, validator, monitor, synchronizer
    data_type TEXT,     -- candidate, cursor, checkpoint
    data_key TEXT,      -- specific identifier (usually relay URL)
    data JSONB,         -- flexible data
    updated_at BIGINT,
    PRIMARY KEY (service_name, data_type, data_key)
);

# Usage
# Store candidates (Seeder and Finder write to validator/candidate)
await brotr.upsert_service_data([
    ("validator", "candidate", "wss://relay.com", {"failed_attempts": 0})
])

# Store cursor
await brotr.upsert_service_data([
    ("synchronizer", "cursor", "relay.example.com", {"timestamp": 123456})
])

# Query candidates (Validator reads from validator/candidate)
candidates = await brotr.get_service_data("validator", "candidate")
```

**Benefits:**
- Flexible for future services
- No schema changes needed
- Queryable with SQL
- Atomic updates

---

## Architecture Decision Records

### ADR-001: Four-Layer Separation

**Decision:** Separate Implementation, Service, Core, and Utils layers

**Rationale:**
- Multiple implementations (bigbrotr, lilbrotr) share same services
- Services focus on business logic, not database details
- Core provides reusable infrastructure
- Utils provides shared utilities (NetworkConfig, BatchProgress, transport, etc.)
- Clear separation of concerns

**Consequences:**
- Easy to add new implementations
- Services are implementation-agnostic
- Core components are service-agnostic
- Testing each layer independently

---

### ADR-002: Stored Procedures for Mutations

**Decision:** All database writes via stored procedures

**Rationale:**
- SQL injection prevention
- Atomic multi-table operations
- Database-side validation
- Consistent error handling

**Consequences:**
- Changes require SQL migration
- Harder to debug (logic in DB)
- Better security
- Guaranteed atomicity

---

### ADR-003: Cursor-Based Pagination

**Decision:** Use (created_at, id) composite cursor

**Rationale:**
- OFFSET/LIMIT skips or duplicates rows if data changes
- Timestamp collisions require tiebreaker
- Resumable from exact position
- Efficient with proper indexes

**Consequences:**
- Requires index on (created_at, id)
- Slightly more complex queries
- Deterministic ordering
- No missed or duplicate events

---

### ADR-004: Content-Addressed Metadata

**Decision:** Hash metadata for deduplication

**Rationale:**
- NIP-11 info rarely changes
- Same content = same hash = single row
- ~90% reduction in metadata table size
- Automatic deduplication

**Consequences:**
- Cannot modify existing metadata
- Hash collisions theoretically possible (SHA-256)
- Time-series in relay_metadata junction table
- Query latest via materialized view

---

### ADR-005: Async-First Design

**Decision:** All I/O operations are async

**Rationale:**
- High concurrency without threads
- Non-blocking database queries
- Efficient HTTP requests
- Native asyncio ecosystem

**Consequences:**
- Requires async/await throughout
- No blocking calls allowed
- Event loop management needed
- Higher concurrency capacity

---

### ADR-006: Multiprocessing for Synchronizer

**Decision:** Use aiomultiprocess instead of threads

**Rationale:**
- Python GIL limits thread parallelism
- Event collection is CPU-bound (parsing, validation)
- True parallelism across cores
- Each worker has own event loop

**Consequences:**
- Higher memory usage (process overhead)
- Inter-process communication via queues
- Auto-restart on crashes
- Scales with CPU cores

---

### ADR-007: Multi-Network Support

**Decision:** First-class support for overlay networks (Tor, I2P, Lokinet)

**Rationale:**
- Nostr values censorship resistance
- .onion, .i2p, .loki relays exist
- SOCKS5 proxy for both HTTP and WebSocket
- Network type differentiation
- Unified NetworkConfig for all services

**Consequences:**
- Requires appropriate proxy running (Tor, I2P, Lokinet)
- Separate timeouts per network type
- Network detection in Relay model
- Per-network concurrency limits via max_tasks

---

### ADR-008: Graceful Shutdown via asyncio.Event

**Decision:** Single Event as shutdown source of truth

**Rationale:**
- Signal handlers are sync but asyncio is async
- Need thread-safe communication
- asyncio.Event supports both sync set() and async wait()
- No race conditions

**Consequences:**
- Consistent shutdown semantics
- Interruptible waits
- Clean resource cleanup
- No polling needed

---

## File Organization

```
bigbrotr/
├── src/
│   ├── core/                      # Core infrastructure
│   │   ├── __init__.py
│   │   ├── logger.py              # Structured logging
│   │   ├── pool.py                # Connection pooling
│   │   ├── brotr.py               # Database interface
│   │   ├── base_service.py        # Service base class
│   │   └── metrics.py             # Prometheus metrics server
│   │
│   ├── models/                    # Data models
│   │   ├── __init__.py
│   │   ├── event.py               # Nostr event wrapper
│   │   ├── relay.py               # Relay URL model
│   │   ├── event_relay.py         # Event+Relay junction
│   │   ├── keys.py                # Nostr keys wrapper
│   │   ├── metadata.py            # JSONB metadata
│   │   ├── nip11.py               # NIP-11 info doc
│   │   ├── nip66.py               # NIP-66 monitoring
│   │   └── relay_metadata.py      # Relay metadata junction
│   │
│   └── services/                  # Business logic
│       ├── __init__.py
│       ├── __main__.py            # Service registry
│       ├── seeder.py         # Database bootstrap
│       ├── finder.py              # Relay discovery
│       ├── validator.py           # Relay validation
│       ├── monitor.py             # Health monitoring
│       └── synchronizer.py        # Event collection
│
├── implementations/
│   ├── bigbrotr/                  # Full-featured
│   │   ├── yaml/
│   │   │   ├── core/
│   │   │   │   └── brotr.yaml     # Pool + Brotr config
│   │   │   └── services/
│   │   │       ├── seeder.yaml
│   │   │       ├── finder.yaml
│   │   │       ├── validator.yaml
│   │   │       ├── monitor.yaml
│   │   │       └── synchronizer.yaml
│   │   ├── postgres/
│   │   │   └── init/              # SQL schema
│   │   ├── docker-compose.yaml
│   │   └── .env.example
│   │
│   └── lilbrotr/                  # Lightweight
│       └── (same structure, different schema)
│
└── tests/
    ├── conftest.py                # Shared fixtures
    └── unit/
        ├── core/
        │   ├── test_logger.py
        │   ├── test_pool.py
        │   ├── test_brotr.py
        │   └── test_base_service.py
        ├── models/
        │   └── test_*.py
        ├── services/
        │   └── test_*.py
        └── utils/
            └── test_*.py
```

---

## Quick Navigation

- **Core Layer:** [core-reference.md](core-reference.md)
- **Service Layer:** [services-reference.md](services-reference.md)
- **Models:** [models-reference.md](models-reference.md)
- **Database:** [database-reference.md](database-reference.md)
- **Testing:** [testing-reference.md](testing-reference.md)
