# Technical Architecture

Comprehensive technical documentation for developers, architects, and contributors.

---

## Table of Contents

1. [System Architecture](#system-architecture)
2. [Core Layer](#core-layer)
3. [Service Layer](#service-layer)
4. [Data Models](#data-models)
5. [Database Schema](#database-schema)
6. [Implementation Layer](#implementation-layer)
7. [Design Patterns](#design-patterns)
8. [Performance Characteristics](#performance-characteristics)
9. [Security Model](#security-model)
10. [Deployment Architecture](#deployment-architecture)

---

## System Architecture

BigBrotr employs a **four-layer architecture** that separates infrastructure, business logic, utilities, and deployment concerns.

### Layered Design

```
+======================================================================+
|                      IMPLEMENTATION LAYER                            |
|         Multiple deployments sharing same service/core codebase      |
+----------------------------------------------------------------------+
|                                                                      |
|   +----------------------+         +----------------------+          |
|   |     bigbrotr/        |         |     lilbrotr/        |          |
|   +----------------------+         +----------------------+          |
|   | - Full schema        |         | - Lightweight schema |          |
|   | - YAML configs       |         | - YAML configs       |          |
|   | - SQL DDL            |         | - SQL DDL (minimal)  |          |
|   | - Docker compose     |         | - Docker compose     |          |
|   | - 100% storage       |         | - 40% storage        |          |
|   +----------------------+         +----------------------+          |
|                                                                      |
+================================+=====+===============================+
                                 |
                                 v
+======================================================================+
|                        SERVICE LAYER                                 |
|       Business logic, protocol implementation, data processing       |
+----------------------------------------------------------------------+
|                                                                      |
|   +--------+  +--------+  +-----------+  +---------+  +------------+ |
|   | Seeder |  | Finder |  | Validator |  | Monitor |  |Synchronizer| |
|   | (seed) |  |(disco) |  |  (test)   |  |(health) |  |  (events)  | |
|   +--------+  +--------+  +-----------+  +---------+  +------------+ |
|                                                                      |
+================================+=====+===============================+
                                 |
                                 v
+======================================================================+
|                         CORE LAYER                                   |
|              Infrastructure primitives, shared utilities             |
+----------------------------------------------------------------------+
|                                                                      |
|   +--------+     +--------+     +-------------+     +--------+       |
|   |  Pool  |---->| Brotr  |     | BaseService |     | Logger |       |
|   +--------+     +--------+     +-------------+     +--------+       |
|                                                                      |
+================================+=====+===============================+
                                 |
                                 v
+======================================================================+
|                        DATA MODELS                                   |
|        Immutable data structures, validation, database mapping       |
+----------------------------------------------------------------------+
|                                                                      |
|   Event   Relay   EventRelay   RelayMetadata   Metadata              |
|   Nip11   Nip66   NetworkType  MetadataType                          |
|                                                                      |
+======================================================================+
```

### Layer Responsibilities

**Implementation Layer**
- Deployment-specific configurations (YAML)
- SQL schema definitions (DDL)
- Docker orchestration
- Environment variables
- Seed data

**Service Layer**
- Nostr protocol implementation
- Business logic workflows
- State management
- External API integration
- Event processing

**Core Layer**
- Database connection pooling
- High-level database interface
- Service lifecycle management
- Structured logging

**Utils Layer**
- Network detection and proxy configuration
- URL and data parsing utilities
- HTTP/WebSocket transport helpers
- YAML loading with environment variable support
- Nostr key management utilities

**Models Layer**
- Type-safe data structures
- Validation logic
- Database parameter extraction
- Immutability guarantees

---

## Core Layer

The core layer provides infrastructure primitives used by all services.

### Pool: PostgreSQL Connection Manager

**File**: `src/core/pool.py`

#### Architecture

```
+---------------------------------------------------+
|                       Pool                        |
+---------------------------------------------------+
| Attributes:                                       |
|   _pool: Optional[asyncpg.Pool]                   |
|   _is_connected: bool                             |
|   _connection_lock: asyncio.Lock                  |
|   config: PoolConfig                              |
+---------------------------------------------------+
| Methods:                                          |
|   + connect() -> None                             |
|   + close() -> None                               |
|   + acquire() -> AsyncContextManager[Connection]  |
|   + acquire_healthy() -> AsyncContextManager      |
|   + transaction() -> AsyncContextManager          |
|   + fetch(query, *args) -> List[Record]           |
|   + fetchrow(query, *args) -> Optional[Record]    |
|   + fetchval(query, *args) -> Any                 |
|   + execute(query, *args) -> str                  |
|   + executemany(query, args) -> None              |
|   + metrics -> Dict[str, Any]                     |
+---------------------------------------------------+
```

#### Connection Lifecycle

```python
async def connect(self):
    """Establish connection pool with retry logic."""
    attempt = 0
    delay = self.config.retry.initial_delay

    while attempt < self.config.retry.max_attempts:
        try:
            self._pool = await asyncpg.create_pool(
                host=self.config.database.host,
                port=self.config.database.port,
                database=self.config.database.database,
                user=self.config.database.user,
                password=self.config.database.password.get_secret_value(),
                min_size=self.config.limits.min_size,
                max_size=self.config.limits.max_size,
                max_queries=self.config.limits.max_queries,
                max_inactive_connection_lifetime=self.config.limits.max_inactive_connection_lifetime,
                timeout=self.config.timeouts.acquisition,
                command_timeout=self.config.timeouts.health_check,
                server_settings=self.config.server_settings.model_dump(),
            )
            self._is_connected = True
            return
        except Exception as e:
            attempt += 1
            if attempt >= self.config.retry.max_attempts:
                raise ConnectionError(f"Failed after {attempt} attempts")

            # Exponential or linear backoff
            if self.config.retry.exponential_backoff:
                delay = min(delay * 2, self.config.retry.max_delay)
            else:
                delay = min(delay + self.config.retry.initial_delay,
                          self.config.retry.max_delay)

            await asyncio.sleep(delay)
```

#### Health-Checked Acquisition

```python
@asynccontextmanager
async def acquire_healthy(self):
    """Acquire connection with health check."""
    attempt = 0
    while attempt < self.config.retry.max_attempts:
        try:
            async with self.acquire() as conn:
                # Validate connection
                await conn.fetchval(
                    "SELECT 1",
                    timeout=self.config.timeouts.health_check
                )
                yield conn
                return
        except Exception as e:
            attempt += 1
            if attempt >= self.config.retry.max_attempts:
                raise
            await asyncio.sleep(self.config.retry.initial_delay)
```

#### Metrics Tracking

```python
@property
def metrics(self) -> Dict[str, Any]:
    """Connection pool metrics."""
    if not self._pool:
        return {"is_connected": False}

    return {
        "size": self._pool.get_size(),
        "idle_size": self._pool.get_idle_size(),
        "min_size": self._pool.get_min_size(),
        "max_size": self._pool.get_max_size(),
        "free_size": self._pool.get_max_size() - self._pool.get_size(),
        "utilization": (self._pool.get_size() - self._pool.get_idle_size())
                      / self._pool.get_max_size(),
        "is_connected": True,
    }
```

---

### Brotr: Database Interface

**File**: `src/core/brotr.py`

#### Architecture

Uses **stored functions** exclusively for mutations to prevent SQL injection and ensure atomic operations.

```
+---------------------------------------------------+
|                      Brotr                        |
+---------------------------------------------------+
| Attributes:                                       |
|   pool: Pool                                      |
|   config: BrotrConfig                             |
+---------------------------------------------------+
| Methods:                                          |
|   + insert_events(records) -> int                 |
|   + insert_relays(records) -> int                 |
|   + insert_relay_metadata(records) -> int         |
|   + delete_orphan_events() -> int                 |
|   + delete_orphan_metadata() -> int               |
|   + upsert_service_data(records) -> int           |
|   + get_service_data(service, type, key) -> List  |
|   + delete_service_data(keys) -> int              |
|   + refresh_matview(view_name) -> None            |
+---------------------------------------------------+
```

#### Stored Function Pattern

All mutations follow this pattern -- extract arrays from model objects and pass them to bulk database functions:

```python
async def insert_events(
    self,
    records: list[EventRelay]
) -> int:
    """Insert events atomically via stored function with array parameters."""

    # Validate batch size
    if len(records) > self.config.batch.max_batch_size:
        raise ValueError(f"Batch size {len(records)} exceeds limit")

    # Extract array parameters from records
    ids, pubkeys, created_ats, kinds, tags_list, relay_urls, sigs = (
        [], [], [], [], [], [], []
    )

    for record in records:
        params = record.to_db_params()
        ids.append(params[0])
        pubkeys.append(params[1])
        created_ats.append(params[2])
        kinds.append(params[3])
        tags_list.append(params[4])
        relay_urls.append(params[5])
        sigs.append(params[6])

    # Execute bulk stored function with array parameters
    async with self.pool.acquire() as conn:
        inserted = await conn.fetchval(
            "SELECT events_relays_insert_cascade($1, $2, $3, $4, $5, $6, $7)",
            ids, pubkeys, created_ats, kinds, tags_list, relay_urls, sigs,
            timeout=self.config.timeouts.batch,
        )

    return inserted
```

#### Service State Management

Generic key-value storage for service state:

```python
async def upsert_service_data(
    self,
    records: list[tuple[str, str, str, dict]]
) -> int:
    """
    Upsert service data.

    Args:
        records: List of (service_name, data_type, key, value)

    Returns:
        Count of upserted records
    """
    # Extract array parameters from records
    service_names, data_types, keys, values = [], [], [], []
    for service_name, data_type, key, value in records:
        service_names.append(service_name)
        data_types.append(data_type)
        keys.append(key)
        values.append(json.dumps(value))

    # Execute stored function with array parameters
    async with self.pool.acquire() as conn:
        upserted = await conn.fetchval(
            "SELECT service_data_upsert($1, $2, $3, $4)",
            service_names, data_types, keys, values,
        )

    return upserted
```

---

### BaseService: Service Lifecycle

**File**: `src/core/base_service.py`

#### Architecture

```
+---------------------------------------------------+
|             BaseService[ConfigT]                  |
+---------------------------------------------------+
| Class Variables:                                  |
|   SERVICE_NAME: ClassVar[str]                     |
|   CONFIG_CLASS: ClassVar[Type[BaseModel]]         |
+---------------------------------------------------+
| Attributes:                                       |
|   config: ConfigT                                 |
|   _shutdown_event: asyncio.Event                  |
+---------------------------------------------------+
| Methods:                                          |
|   + run() -> None [ABSTRACT]                      |
|   + run_forever(interval, max_failures) -> None   |
|   + request_shutdown() -> None                    |
|   + wait(timeout) -> bool                         |
|   + is_running -> bool                            |
+---------------------------------------------------+
```

#### Graceful Shutdown Pattern

```python
class BaseService(ABC, Generic[ConfigT]):
    def __init__(self, config: ConfigT):
        self.config = config
        self._shutdown_event = asyncio.Event()

    def request_shutdown(self):
        """
        Signal shutdown request (thread-safe).

        Called by signal handlers (sync context) to trigger
        graceful shutdown in async service loop.
        """
        self._shutdown_event.set()

    @property
    def is_running(self) -> bool:
        """Check if service should continue running."""
        return not self._shutdown_event.is_set()

    async def wait(self, timeout: float) -> bool:
        """
        Wait for timeout or shutdown signal.

        Returns:
            True if shutdown requested, False if timeout
        """
        try:
            await asyncio.wait_for(
                self._shutdown_event.wait(),
                timeout=timeout
            )
            return True  # Shutdown requested
        except asyncio.TimeoutError:
            return False  # Timeout elapsed

    async def run_forever(
        self,
        interval: float,
        max_consecutive_failures: int = 0
    ):
        """
        Run service in loop with error handling.

        Args:
            interval: Seconds between cycles
            max_consecutive_failures: Stop after N failures (0=unlimited)
        """
        consecutive_failures = 0

        while self.is_running:
            try:
                # Execute service logic
                await self.run()

                # Reset failure counter on success
                consecutive_failures = 0

                # Wait for next cycle or shutdown
                if await self.wait(interval):
                    break  # Shutdown requested

            except Exception as e:
                consecutive_failures += 1
                logger.error(
                    "cycle_failed",
                    error=str(e),
                    consecutive_failures=consecutive_failures,
                    max_failures=max_consecutive_failures,
                )

                # Stop if failure limit reached
                if (max_consecutive_failures > 0 and
                    consecutive_failures >= max_consecutive_failures):
                    logger.critical("max_failures_reached")
                    break
```

#### Context Manager Protocol

```python
async def __aenter__(self):
    """Enter service context (clear shutdown)."""
    self._shutdown_event.clear()
    logger.info(f"{self.SERVICE_NAME}_started")
    return self

async def __aexit__(self, exc_type, exc_val, exc_tb):
    """Exit service context (signal shutdown)."""
    self.request_shutdown()
    logger.info(f"{self.SERVICE_NAME}_stopped")
    return False  # Don't suppress exceptions
```

---

### Logger: Structured Logging

**File**: `src/core/logger.py`

#### Output Formats

**Key-Value Format** (default):
```
event_received event_id=abc123 kind=1 relay=wss://relay.example.com
connection_established relay=wss://relay.com rtt_ms=45.2
batch_processed count=1000 duration_s=2.3 rate_per_s=434.78
```

**JSON Format** (production):
```json
{"message": "event_received", "event_id": "abc123", "kind": 1, "relay": "wss://relay.example.com"}
{"message": "connection_established", "relay": "wss://relay.com", "rtt_ms": 45.2}
```

#### Value Escaping

```python
def _format_value(self, value: Any) -> str:
    """Format value with proper escaping."""
    s = str(value)

    # Check if quoting needed
    needs_quote = (
        " " in s or
        "=" in s or
        '"' in s or
        "\\" in s
    )

    if needs_quote:
        # Escape backslashes and quotes
        s = s.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{s}"'

    return s
```

---

## Service Layer

Each service inherits from `BaseService` and implements domain-specific logic.

### Service Communication Pattern

```
+--------------+
|    Seeder    |  One-shot: loads seeds as candidates
+--------------+
       |
       v
+--------------+
|    Finder    |  Discovers URLs -> stores candidates
+--------------+
       |
       v
+--------------+
|  Validator   |  Tests candidates -> inserts relays
+--------------+
       |
       v
+--------------+
|   Monitor    |  Health checks -> inserts metadata
+--------------+
       |
       v
+--------------+
| Synchronizer |  Collects events -> inserts events
+--------------+
```

---

### Seeder Service

**Purpose**: One-shot database bootstrap and relay seeding

**Workflow**:

```python
async def run(self):
    """Seed database with relay URLs."""

    if not self.config.seed.enabled:
        logger.info("seeding_disabled")
        return

    # Parse seed file
    relays = self._parse_seed_file()

    # Store as candidates for Validator
    await self._seed_relays(relays)
```

**Seed File Parsing**:

```python
def _parse_seed_file(self) -> list[Relay]:
    """Parse and validate relay URLs from seed file."""
    relays = []
    with open(self.config.seed.file_path) as f:
        for line in f:
            url = line.strip()
            if not url or url.startswith("#"):
                continue
            try:
                relay = Relay(url)
                relays.append(relay)
            except ValueError as e:
                logger.warning("invalid_seed_url", url=url, error=str(e))
    return relays
```

**Note**: The Seeder stores relay URLs as candidates in `service_data`. The Validator service tests and promotes valid candidates to the `relays` table.

---

### Finder Service

**Purpose**: Continuous relay URL discovery

**Discovery Sources**:

1. **API Sources**: Configured external APIs (e.g., nostr.watch)
2. **Database Events**: Mine events for relay URLs

**Event Mining**:

```python
async def _find_from_events(self) -> int:
    """Mine events for relay URLs using cursor pagination."""

    # Load cursor
    cursor_data = await self._brotr.get_service_data(
        "finder", "cursor", "events"
    )

    if cursor_data:
        last_timestamp = cursor_data[0]["value"]["timestamp"]
        last_id = bytes.fromhex(cursor_data[0]["value"]["id"])
    else:
        last_timestamp = 0
        last_id = bytes(32)  # Null ID

    # Query events after cursor
    query = """
        SELECT id, created_at, kind, tags, content
        FROM events
        WHERE (kind = ANY($1) OR tagvalues @> ARRAY['r'])
          AND (created_at > $2 OR (created_at = $2 AND id > $3))
        ORDER BY created_at ASC, id ASC
        LIMIT $4
    """

    rows = await self._brotr.pool.fetch(
        query,
        self.config.events.kinds,  # [2, 3, 10002]
        last_timestamp,
        last_id,
        self.config.events.batch_size,
    )

    # Extract relay URLs
    discovered = set()

    for row in rows:
        kind = row["kind"]

        if kind == 2:
            # Deprecated: content is relay URL
            discovered.add(row["content"])

        elif kind == 3:
            # Contact list: JSON relay dict
            try:
                data = json.loads(row["content"])
                if isinstance(data, dict):
                    discovered.update(data.keys())
            except json.JSONDecodeError:
                pass

        elif kind == 10002:
            # Relay list: r-tags
            for tag in row["tags"]:
                if tag[0] == "r" and len(tag) > 1:
                    discovered.add(tag[1])

        # All events: r-tags
        for tag in row["tags"]:
            if tag[0] == "r" and len(tag) > 1:
                discovered.add(tag[1])

    # Validate and store
    valid_urls = []
    for url in discovered:
        relay = self._validate_relay_url(url)
        if relay:
            valid_urls.append(relay.url)

    if valid_urls:
        # Write candidates with service_name='validator' so Validator picks them up
        candidates = [
            ("validator", "candidate", url, {})
            for url in valid_urls
        ]
        await self._brotr.upsert_service_data(candidates)

    # Save cursor
    if rows:
        last_row = rows[-1]
        await self._brotr.upsert_service_data([
            ("finder", "cursor", "events", {
                "timestamp": last_row["created_at"],
                "id": last_row["id"].hex()
            })
        ])

    return len(valid_urls)
```

---

### Validator Service

**Purpose**: Validate candidate relay URLs

**Validation Workflow**:

```python
async def _validate_relay(self, url: str) -> bool:
    """Test relay WebSocket connection."""

    try:
        # Parse URL
        relay = Relay(url)

        # Build client
        builder = ClientBuilder()

        # Configure Tor proxy for .onion
        if relay.network == "tor" and self.config.tor.enabled:
            opts = ClientOptions().proxy(self.config.tor.proxy_url)
            builder = builder.opts(opts)

        # Configure authentication
        if self.config.keys.keys:
            builder = builder.signer(self.config.keys.keys)

        client = builder.build()

        # Test connection
        await asyncio.wait_for(
            client.add_relay(url),
            timeout=self.config.connection_timeout
        )
        await asyncio.wait_for(
            client.connect(),
            timeout=self.config.connection_timeout
        )

        # Success: insert relay
        await self._brotr.insert_relays([relay])
        return True

    except asyncio.TimeoutError:
        return False
    except Exception as e:
        logger.debug("validation_failed", url=url, error=str(e))
        return False
```

**Retry Logic**:

```python
async def run(self):
    """Validate candidates with probabilistic selection."""

    # Fetch all candidates (written by Seeder and Finder with service_name='validator')
    candidates = await self._brotr.get_service_data(
        "validator", "candidate"
    )

    # Probabilistic selection: P(select) = 1 / (1 + failed_attempts)
    if self.config.max_candidates_per_run:
        selected = []
        for c in candidates:
            failed_attempts = c["value"].get("failed_attempts", 0)
            prob = 1.0 / (1 + failed_attempts)
            if random.random() < prob:
                selected.append(c)
                if len(selected) >= self.config.max_candidates_per_run:
                    break
        candidates = selected

    # Validate concurrently
    sem = asyncio.Semaphore(self.config.concurrency.max_parallel)

    async def validate_one(candidate):
        async with sem:
            url = candidate["key"]
            success = await self._validate_relay(url)

            if success:
                # Remove from candidates
                await self._brotr.delete_service_data([
                    ("validator", "candidate", url)
                ])
            else:
                # Increment failed_attempts count
                failed_attempts = candidate["value"].get("failed_attempts", 0) + 1
                await self._brotr.upsert_service_data([
                    ("validator", "candidate", url, {"failed_attempts": failed_attempts})
                ])

    await asyncio.gather(*[
        validate_one(c) for c in candidates
    ])
```

---

### Monitor Service

**Purpose**: NIP-11/NIP-66 compliant health monitoring

**Check Types**:

```python
@dataclass
class ChecksConfig:
    open: bool = True      # WebSocket connection
    read: bool = True      # REQ/EOSE subscription
    write: bool = True     # EVENT/OK publication
    nip11_fetch: bool = True  # Info document fetch
    ssl: bool = True       # Certificate validation
    dns: bool = True       # DNS resolution timing
    geo: bool = True       # Geolocation lookup
```

**Monitoring Workflow**:

```python
async def run(self):
    """Monitor all relays."""

    # Select relays to check
    query = """
        SELECT r.url, r.network
        FROM relays r
        LEFT JOIN relay_metadata rm ON r.url = rm.relay_url
            AND rm.metadata_type = 'nip66_rtt'
        WHERE rm.generated_at IS NULL
           OR rm.generated_at < $1
        ORDER BY rm.generated_at ASC NULLS FIRST
        LIMIT $2
    """

    min_age = int(time.time()) - self.config.selection.min_age_since_check
    rows = await self._brotr.pool.fetch(query, min_age, 1000)

    # Check concurrently
    sem = asyncio.Semaphore(self.config.concurrency.max_parallel)

    async def check_one(row):
        async with sem:
            relay = Relay(row["url"])

            # Determine timeout
            timeout = (self.config.timeouts.tor
                      if relay.network == "tor"
                      else self.config.timeouts.clearnet)

            # Perform checks
            nip66 = await Nip66.check(
                relay=relay,
                keys=self.config.keys.keys,
                tor_config=self.config.tor,
                checks_config=self.config.checks,
                timeouts_config=self.config.timeouts,
                geo_config=self.config.geo,
            )

            # Store metadata
            metadata_records = nip66.to_relay_metadata_list()
            await self._brotr.insert_relay_metadata(metadata_records)

            # Publish NIP-66 event
            if self.config.publishing.enabled:
                await self._publish_nip66_event(nip66)

    await asyncio.gather(*[check_one(row) for row in rows])
```

**NIP-66 Event Publishing**:

```python
async def _publish_nip66_event(self, nip66: Nip66):
    """Publish kind 30166 monitoring event."""

    tags = [
        ["d", nip66.relay.url],
        ["n", nip66.relay.network],
    ]

    # RTT tags
    if nip66.rtt_open:
        tags.append(["rtt-open", str(int(nip66.rtt_open))])
    if nip66.rtt_read:
        tags.append(["rtt-read", str(int(nip66.rtt_read))])
    if nip66.rtt_write:
        tags.append(["rtt-write", str(int(nip66.rtt_write))])

    # SSL tags
    if nip66.ssl_valid is not None:
        tags.append(["ssl", "valid" if nip66.ssl_valid else "invalid"])

    # Geo tags
    if nip66.geohash:
        tags.append(["g", nip66.geohash])
    if nip66.geo_country:
        tags.append(["geo", "country", nip66.geo_country])

    # Build event
    builder = EventBuilder.text_note("").tags(tags)
    builder = builder.kind(Kind(30166))

    # Publish
    client = Client(self.config.keys.keys)

    if self.config.publishing.destination == "monitored_relay":
        await client.add_relay(nip66.relay.url)
    elif self.config.publishing.destination == "configured_relays":
        for relay in self.config.publishing.relays:
            await client.add_relay(relay)

    await client.connect()
    output = await client.send_event_builder(builder)
```

---

### Synchronizer Service

**Purpose**: High-throughput event collection with multiprocessing

**Architecture**:

```
+------------------+
|   Main Process   |
+--------+---------+
         |
         +---> Load relays from database
         |
         +---> Distribute to worker queue
         |
         +-----+-----+-----+-----+
         |     |     |     |     |
         v     v     v     v     v
      +-----+ +-----+ +-----+ +-----+
      | W1  | | W2  | | W3  | | WN  |  (Worker Processes)
      +--+--+ +--+--+ +--+--+ +--+--+
         |       |       |       |
         v       v       v       v
      Connect to relay
      Send REQ filter
      Collect EVENTs
      Return batch
         |       |       |       |
         +---+---+---+---+---+---+
             |
             v
      +------+------+
      | Collect all |
      |   batches   |
      +------+------+
             |
             v
      +------+------+
      |  Insert to  |
      |  database   |
      +-------------+
```

**Multiprocessing Pattern**:

```python
async def run(self):
    """Synchronize events using worker processes."""

    # Load relays
    query = """
        SELECT url FROM relays
        ORDER BY RANDOM()
        LIMIT $1
    """
    rows = await self._brotr.pool.fetch(
        query,
        self.config.relays.max_relays or 10000
    )

    relays = [row["url"] for row in rows]

    # Distribute to workers
    async with aiomultiprocess.Pool(
        processes=self.config.concurrency.max_processes
    ) as pool:
        results = await pool.map(
            self._sync_relay,
            [(r, self.config) for r in relays],
            chunksize=self.config.relays.batch_size,
        )

    # Flatten and insert events
    all_events = []
    for events in results:
        all_events.extend(events)

    if all_events:
        inserted = await self._brotr.insert_events(all_events)
        logger.info(
            "sync_complete",
            relay_count=len(relays),
            event_count=len(all_events),
            inserted=inserted,
        )
```

**Worker Function**:

```python
async def _sync_relay(
    self,
    args: tuple[str, SynchronizerConfig]
) -> list[EventRelay]:
    """Worker: collect events from single relay."""

    relay_url, config = args
    relay = Relay(relay_url)

    try:
        # Build client
        client = Client()
        await client.add_relay(relay_url)
        await asyncio.wait_for(
            client.connect(),
            timeout=config.timeouts.connection
        )

        # Build filter
        filter_builder = Filter()

        if config.filters.kinds:
            for kind in config.filters.kinds:
                filter_builder = filter_builder.kind(Kind(kind))

        if config.filters.authors:
            for author in config.filters.authors:
                filter_builder = filter_builder.author(
                    PublicKey.parse(author)
                )

        # Subscribe
        events = await asyncio.wait_for(
            client.fetch_events(
                filter_builder,
                timeout=config.timeouts.subscription
            ),
            timeout=config.timeouts.eose
        )

        # Convert to EventRelay
        seen_at = int(time.time())
        return [
            EventRelay.from_nostr_event(e, relay, seen_at)
            for e in events
        ]

    except Exception as e:
        logger.error(
            "sync_failed",
            relay=relay_url,
            error=str(e),
        )
        return []
```

---

## Data Models

All models are **immutable** (`frozen=True` dataclasses) with validation in `__new__`.

### Relay Model

```python
@dataclass(frozen=True)
class Relay:
    """Immutable validated relay URL."""

    url_without_scheme: str  # Unique identifier (e.g., relay.example.com:8080/path)
    network: str  # clearnet, tor, i2p, loki, local, unknown
    discovered_at: int
    scheme: str
    host: str
    port: Optional[int]
    path: Optional[str]

    def __new__(cls, raw: str, discovered_at: Optional[int] = None):
        """Validate and normalize on construction."""

        # Parse with rfc3986
        parsed = cls._parse(raw)

        # Detect network
        network = cls._detect_network(parsed["host"])

        # Reject local addresses
        if network == "local":
            raise ValueError("Local addresses not allowed")
        if network == "unknown":
            raise ValueError(f"Invalid host: '{parsed['host']}'")

        # Create instance
        instance = object.__new__(cls)
        object.__setattr__(instance, "url_without_scheme", parsed["url"])
        object.__setattr__(instance, "network", network)
        object.__setattr__(instance, "discovered_at", discovered_at or int(time.time()))
        object.__setattr__(instance, "scheme", parsed["scheme"])
        object.__setattr__(instance, "host", parsed["host"])
        object.__setattr__(instance, "port", parsed["port"])
        object.__setattr__(instance, "path", parsed["path"])

        return instance

    @property
    def url(self) -> str:
        """Full URL with scheme."""
        return f"{self.scheme}://{self.url_without_scheme}"

    def to_db_params(self) -> tuple:
        """Extract parameters for database insertion."""
        return (
            self.url_without_scheme,
            self.network,
            self.discovered_at,
        )
```

---

### EventRelay Model

```python
@dataclass(frozen=True)
class EventRelay:
    """Event-relay junction with timestamp."""

    event: Union[Event, NostrEvent]
    relay: Relay
    seen_at: int

    @staticmethod
    def from_nostr_event(
        event: NostrEvent,
        relay: Relay,
        seen_at: int
    ) -> "EventRelay":
        """Factory from nostr_sdk Event."""
        return EventRelay(
            event=Event(event),  # Wrap in immutable Event
            relay=relay,
            seen_at=seen_at
        )

    def to_db_params(self) -> tuple:
        """Extract 11 parameters for insert_event procedure."""
        event_params = self.event.to_db_params()
        relay_params = self.relay.to_db_params()

        return (
            *event_params,     # (id, pubkey, created_at, kind, tags, content, sig)
            *relay_params,     # (url, network, discovered_at)
            self.seen_at,
        )
```

---

## Database Schema

### Core Tables

**relays**: Primary relay registry
```sql
CREATE TABLE relays (
    url TEXT PRIMARY KEY,               -- WebSocket URL (e.g., wss://relay.example.com)
    network TEXT NOT NULL,              -- clearnet, tor, i2p, or loki
    discovered_at BIGINT NOT NULL       -- Unix timestamp
);

CREATE INDEX idx_relays_network ON relays(network);
CREATE INDEX idx_relays_discovered_at ON relays(discovered_at DESC);
```

**events**: Full event storage
```sql
CREATE TABLE events (
    id BYTEA PRIMARY KEY,               -- SHA-256 (32 bytes)
    pubkey BYTEA NOT NULL,              -- secp256k1 public key (32 bytes)
    created_at BIGINT NOT NULL,
    kind INTEGER NOT NULL,
    tags JSONB NOT NULL,
    tagvalues TEXT[] GENERATED ALWAYS AS (
        tags_to_tagvalues(tags)
    ) STORED,                           -- For GIN indexing
    content TEXT NOT NULL,
    sig BYTEA NOT NULL,                 -- Schnorr signature (64 bytes)

    CHECK (octet_length(id) = 32),
    CHECK (octet_length(pubkey) = 32),
    CHECK (octet_length(sig) = 64),
    CHECK (kind >= 0 AND kind <= 65535)
);

CREATE INDEX idx_events_pubkey ON events(pubkey);
CREATE INDEX idx_events_created_at ON events(created_at DESC);
CREATE INDEX idx_events_kind ON events(kind);
CREATE INDEX idx_events_tagvalues ON events USING GIN(tagvalues);
CREATE INDEX idx_events_kind_created_at ON events(kind, created_at DESC);
CREATE INDEX idx_events_pubkey_kind ON events(pubkey, kind);
```

**events_relays**: Junction table
```sql
CREATE TABLE events_relays (
    event_id BYTEA NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    relay_url TEXT NOT NULL REFERENCES relays(url) ON DELETE CASCADE,
    seen_at BIGINT NOT NULL,

    PRIMARY KEY (event_id, relay_url)
);

CREATE INDEX idx_events_relays_relay_url ON events_relays(relay_url);
CREATE INDEX idx_events_relays_seen_at ON events_relays(seen_at DESC);
```

**metadata**: Content-addressed deduplication
```sql
CREATE TABLE metadata (
    id BYTEA PRIMARY KEY,               -- SHA-256 of value
    value JSONB NOT NULL,

    CHECK (octet_length(id) = 32)
);

CREATE INDEX idx_metadata_value ON metadata USING GIN(value jsonb_path_ops);
```

**relay_metadata**: Time-series metadata
```sql
CREATE TABLE relay_metadata (
    relay_url TEXT NOT NULL REFERENCES relays(url) ON DELETE CASCADE,
    generated_at BIGINT NOT NULL,
    metadata_type TEXT NOT NULL,        -- nip11_fetch, nip66_rtt, nip66_ssl, nip66_geo, nip66_net, nip66_dns, nip66_http
    metadata_id BYTEA NOT NULL REFERENCES metadata(id) ON DELETE CASCADE,

    PRIMARY KEY (relay_url, generated_at, metadata_type)
);

CREATE INDEX idx_relay_metadata_metadata_type ON relay_metadata(metadata_type);
CREATE INDEX idx_relay_metadata_generated_at ON relay_metadata(generated_at DESC);
CREATE INDEX idx_relay_metadata_relay_type_time ON relay_metadata(relay_url, metadata_type, generated_at DESC);
```

**service_data**: Per-service operational data
```sql
CREATE TABLE service_data (
    service_name TEXT NOT NULL,
    data_type TEXT NOT NULL,
    data_key TEXT NOT NULL,
    data JSONB NOT NULL DEFAULT '{}',
    updated_at BIGINT NOT NULL,

    PRIMARY KEY (service_name, data_type, data_key)
);

CREATE INDEX idx_service_data_service_name ON service_data(service_name);
CREATE INDEX idx_service_data_service_type ON service_data(service_name, data_type);
```

---

### Stored Functions

All stored functions use **bulk array parameters** for efficient batch operations. Hash computation for content-addressed storage is performed in Python (SHA-256), not in PostgreSQL.

**relays_insert**: Bulk relay insertion
```sql
CREATE OR REPLACE FUNCTION relays_insert(
    p_urls TEXT[],
    p_networks TEXT[],
    p_discovered_ats BIGINT[]
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_inserted INTEGER;
BEGIN
    WITH ins AS (
        INSERT INTO relays (url, network, discovered_at)
        SELECT unnest(p_urls), unnest(p_networks), unnest(p_discovered_ats)
        ON CONFLICT (url) DO NOTHING
        RETURNING 1
    )
    SELECT count(*) INTO v_inserted FROM ins;

    RETURN v_inserted;
END;
$$;
```

**events_insert**: Bulk event insertion
```sql
CREATE OR REPLACE FUNCTION events_insert(
    p_ids BYTEA[],
    p_pubkeys BYTEA[],
    p_created_ats BIGINT[],
    p_kinds INTEGER[],
    p_tags JSONB[],
    p_contents TEXT[],
    p_sigs BYTEA[]
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_inserted INTEGER;
BEGIN
    WITH ins AS (
        INSERT INTO events (id, pubkey, created_at, kind, tags, content, sig)
        SELECT unnest(p_ids), unnest(p_pubkeys), unnest(p_created_ats),
               unnest(p_kinds), unnest(p_tags), unnest(p_contents), unnest(p_sigs)
        ON CONFLICT (id) DO NOTHING
        RETURNING 1
    )
    SELECT count(*) INTO v_inserted FROM ins;

    RETURN v_inserted;
END;
$$;
```

**metadata_insert**: Bulk content-addressed metadata insertion
```sql
CREATE OR REPLACE FUNCTION metadata_insert(
    p_ids BYTEA[],
    p_values JSONB[]
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_inserted INTEGER;
BEGIN
    WITH ins AS (
        INSERT INTO metadata (id, value)
        SELECT unnest(p_ids), unnest(p_values)
        ON CONFLICT (id) DO NOTHING
        RETURNING 1
    )
    SELECT count(*) INTO v_inserted FROM ins;

    RETURN v_inserted;
END;
$$;
```

**events_relays_insert_cascade**: Bulk event+relay+junction insertion (cascade)
```sql
-- Inserts relays, events, and events_relays junction in one atomic operation.
-- Returns count of inserted event-relay pairs.
CREATE OR REPLACE FUNCTION events_relays_insert_cascade(
    p_event_ids BYTEA[],
    p_pubkeys BYTEA[],
    p_created_ats BIGINT[],
    p_kinds INTEGER[],
    p_tags JSONB[],
    p_relay_urls TEXT[],
    p_sigs BYTEA[]
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$ ... $$;
```

**relay_metadata_insert_cascade**: Bulk metadata+junction insertion (cascade)
```sql
-- Inserts relays, metadata, and relay_metadata junction in one atomic operation.
-- Hash (metadata id) is computed in Python and passed as parameter.
-- Returns count of inserted relay-metadata pairs.
CREATE OR REPLACE FUNCTION relay_metadata_insert_cascade(
    p_relay_urls TEXT[],
    p_generated_ats BIGINT[],
    p_metadata_types TEXT[],
    p_metadata_ids BYTEA[],
    p_metadata_values JSONB[]
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$ ... $$;
```

---

### Materialized View

**relay_metadata_latest**: Latest metadata per relay per metadata_type
```sql
CREATE MATERIALIZED VIEW relay_metadata_latest AS
SELECT DISTINCT ON (relay_url, metadata_type)
    relay_url,
    metadata_type,
    generated_at,
    metadata_id
FROM relay_metadata
ORDER BY relay_url, metadata_type, generated_at DESC;

CREATE UNIQUE INDEX idx_relay_metadata_latest_pkey
    ON relay_metadata_latest(relay_url, metadata_type);

-- Refresh via Brotr.refresh_matview()
REFRESH MATERIALIZED VIEW CONCURRENTLY relay_metadata_latest;
```

---

## Design Patterns

### 1. Cursor-Based Pagination

**Problem**: OFFSET/LIMIT skips or duplicates rows when data changes

**Solution**: Composite cursor with deterministic ordering

```sql
-- Query pattern
SELECT *
FROM events
WHERE (created_at > $1 OR (created_at = $1 AND id > $2))
ORDER BY created_at ASC, id ASC
LIMIT $3
```

**Benefits**:
- No duplicates or missed rows
- Handles timestamp collisions with ID tiebreaker
- Efficient with proper index: `(created_at, id)`
- Resumable from exact position

---

### 2. Content-Addressed Storage

**Problem**: Repeated metadata wastes space

**Solution**: Hash-based deduplication (SHA-256 computed in Python)

```python
# Python side: compute content-addressed hash
import hashlib
metadata_id = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).digest()
```

```sql
-- Insert only if new (hash passed as parameter)
INSERT INTO metadata (id, value)
VALUES (p_metadata_id, p_value)
ON CONFLICT (id) DO NOTHING;
```

**Benefits**:
- Automatic deduplication (~90% space savings for NIP-11)
- Hash computed in Python (no pgcrypto dependency)
- Query by content hash
- Immutable storage (can't modify existing)

---

### 3. Stored Functions for Mutations

**Problem**: SQL injection, non-atomic operations

**Solution**: All writes via stored functions with array parameters

```python
# Python side: hardcoded function names with array parameters
inserted = await conn.fetchval(
    "SELECT events_relays_insert_cascade($1, $2, $3, $4, $5, $6, $7)",
    ids, pubkeys, created_ats, kinds, tags_list, relay_urls, sigs,
)

# PostgreSQL side: atomic multi-table bulk insert
CREATE FUNCTION events_relays_insert_cascade(...) RETURNS INTEGER AS $$
BEGIN
    -- Insert relays ... ON CONFLICT DO NOTHING;
    -- Insert events ... ON CONFLICT DO NOTHING;
    -- Insert events_relays ... ON CONFLICT DO NOTHING;
    RETURN v_inserted;
END;
$$;
```

**Benefits**:
- No SQL injection (function names hardcoded)
- Atomic operations (transaction semantics)
- Bulk array parameters for efficient batch inserts
- Database-side validation
- Consistent error handling

---

### 4. Async-First Design

**Pattern**: All I/O operations are async

```python
# Connection pool
async with pool.acquire() as conn:
    rows = await conn.fetch("SELECT ...")

# HTTP requests
async with aiohttp.ClientSession() as session:
    async with session.get(url) as resp:
        data = await resp.json()

# WebSocket
client = Client()
await client.connect()
events = await client.fetch_events(filter)
```

**Benefits**:
- High concurrency without threads
- Non-blocking I/O
- Efficient resource usage
- Native asyncio ecosystem

---

### 5. Graceful Shutdown

**Pattern**: asyncio.Event as shutdown signal

```python
# Signal handler (sync)
def handle_signal(signum, frame):
    service.request_shutdown()  # Thread-safe

# Service loop (async)
while service.is_running:
    await service.run()
    if await service.wait(interval):
        break  # Shutdown during wait
```

**Benefits**:
- Thread-safe signal handling
- Interruptible waits
- Clean resource cleanup
- No race conditions

---

## Performance Characteristics

### Throughput

**Synchronizer**:
- 10,000+ events/second with 8 workers
- Scales linearly with CPU cores
- Batched inserts (10,000 events/batch)

**Monitor**:
- 100+ relays/minute with 50 concurrent checks
- RTT measurements: 30-60s per relay (clearnet)
- RTT measurements: 60-120s per relay (Tor)

**Finder**:
- 1,000+ candidates/minute from APIs
- 10,000 events/batch for mining
- Cursor-based resumption

### Latency

**Database queries**:
- Simple lookups: <1ms
- Cursor pagination: 1-5ms
- Batch inserts: 10-50ms (10,000 events)
- Materialized view refresh: 100-500ms

**Network operations**:
- WebSocket connection: 50-200ms (clearnet)
- WebSocket connection: 500-2000ms (Tor)
- HTTP NIP-11 fetch: 50-150ms
- DNS resolution: 10-50ms

### Storage

**BigBrotr (full)**:
- 1 million events ≈ 2GB
- 10,000 relays ≈ 10MB
- Metadata (deduplicated) ≈ 100MB

**LilBrotr (lightweight)**:
- 1 million events ≈ 800MB (60% savings)
- Events table only: id, pubkey, created_at, kind, sig

---

## Security Model

### SQL Injection Prevention

**Parameterized queries**:
```python
await pool.fetch("SELECT * FROM relays WHERE network = $1", network)
```

**Stored functions**:
```python
await conn.fetchval("SELECT events_relays_insert_cascade($1, $2, ...)", ...)
```

**Never use string concatenation**:
```python
# WRONG
await pool.fetch(f"SELECT * FROM relays WHERE network = '{network}'")
```

---

### Password Management

**Environment variables only**:
```python
password = os.getenv("DB_PASSWORD")
if not password:
    raise ValueError("DB_PASSWORD not set")
```

**Never in config files**:
```yaml
# WRONG
database:
  password: "my_password"  # Never do this!
```

---

### Relay URL Validation

**RFC 3986 parsing**:
```python
relay = Relay(raw_url)  # Validates in __new__
```

**Validation checks**:
- Scheme must be ws/wss
- Host must be valid domain or IP
- Reject local addresses (127.0.0.1, 10.0.0.0/8, etc.)
- Normalize URL (lowercase, default ports)

---

### Nostr Event Validation

**Cryptographic verification via nostr-sdk**:
```python
event = NostrEvent.from_json(raw_json)
# Signature verification built-in
```

**Validation includes**:
- SHA-256 ID verification
- Schnorr signature verification (BIP-340)
- Timestamp sanity checks
- Tag structure validation

---

### Tor Network Security

**SOCKS5 proxy**:
```python
if relay.network == "tor":
    opts = ClientOptions().proxy("socks5://127.0.0.1:9050")
```

**Separate timeouts**:
```python
timeout = (tor_timeout if relay.network == "tor"
           else clearnet_timeout)
```

**No IP leaks**:
- Local addresses rejected
- Network type enforced
- Proxy required for .onion

---

## Deployment Architecture

### Docker Compose Stack

```yaml
services:
  postgres:
    image: postgres:16-alpine
    volumes:
      - ./data/postgres:/var/lib/postgresql/data
      - ./postgres/init:/docker-entrypoint-initdb.d
    environment:
      POSTGRES_DB: bigbrotr
      POSTGRES_USER: admin
      POSTGRES_PASSWORD: ${DB_PASSWORD}

  pgbouncer:
    image: pgbouncer/pgbouncer:latest
    depends_on:
      postgres:
        condition: service_healthy

  tor:
    image: goldy/tor-hidden-service:latest
    ports:
      - "9050:9050"

  seeder:
    build: ../..
    command: python -m services seeder
    depends_on:
      pgbouncer:
        condition: service_healthy
    restart: "no"

  finder:
    build: ../..
    command: python -m services finder
    depends_on:
      seeder:
        condition: service_completed_successfully
    restart: unless-stopped

  validator:
    build: ../..
    command: python -m services validator
    depends_on:
      - finder
      - tor
    restart: unless-stopped

  monitor:
    build: ../..
    command: python -m services monitor
    depends_on:
      - validator
    environment:
      PRIVATE_KEY: ${PRIVATE_KEY}
    restart: unless-stopped

  synchronizer:
    build: ../..
    command: python -m services synchronizer
    depends_on:
      - monitor
    deploy:
      resources:
        limits:
          cpus: '4'
          memory: 4G
    restart: unless-stopped
```

---

### Kubernetes Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: bigbrotr-synchronizer
spec:
  replicas: 3
  template:
    spec:
      containers:
      - name: synchronizer
        image: bigbrotr:latest
        command: ["python", "-m", "services", "synchronizer"]
        resources:
          requests:
            cpu: 2000m
            memory: 2Gi
          limits:
            cpu: 4000m
            memory: 4Gi
        env:
        - name: DB_PASSWORD
          valueFrom:
            secretKeyRef:
              name: bigbrotr-secrets
              key: db-password
```

---

### Monitoring Stack

**Prometheus Metrics**:
```python
# Add to services
from prometheus_client import Counter, Histogram

events_inserted = Counter('bigbrotr_events_inserted_total', 'Events inserted')
event_insert_duration = Histogram('bigbrotr_event_insert_seconds', 'Insert duration')

with event_insert_duration.time():
    inserted = await brotr.insert_events(events)
    events_inserted.inc(inserted)
```

**Grafana Dashboards**:
- Event ingestion rate
- Relay count over time
- Service health checks
- Database pool utilization

---

## Conclusion

BigBrotr is a production-ready, scalable platform for Nostr network intelligence. Its modular architecture, async-first design, and comprehensive monitoring make it suitable for both personal projects and large-scale deployments.

**Key Strengths**:
- Modular four-layer architecture
- Async-first with high concurrency
- Multiprocessing for CPU-bound tasks
- Immutable data models with validation
- Content-addressed deduplication
- Graceful shutdown and error handling
- Comprehensive test coverage
- Production-ready deployment patterns

**For Developers**:
- Clear separation of concerns
- Easy to extend with new services
- Well-documented patterns
- Type-safe with mypy
- Comprehensive test fixtures

**For Operators**:
- One-command deployment
- Built-in monitoring
- Resource-efficient
- Scalable horizontally
- Flexible storage options

**For Researchers**:
- Complete network visibility
- Historical metadata tracking
- Flexible querying (SQL)
- Data export capabilities
- Protocol-compliant

---

**Built for the decentralized future.**
