# Architecture

Comprehensive architecture reference for BigBrotr.

---

## Overview

BigBrotr uses a **Diamond DAG** architecture. Five layers with strict top-to-bottom import flow:

```text
              services         src/bigbrotr/services/
             /   |   \
          core  nips  utils    src/bigbrotr/{core,nips,utils}/
             \   |   /
              models           src/bigbrotr/models/
```

| Tier | Layer | Purpose | Changes When |
|------|-------|---------|--------------|
| **Top** | Services | Business logic, orchestration | New features, protocol updates |
| **Mid** | Core | Pool, Brotr, BaseService, Exceptions, Logger, Metrics | Rarely |
| **Mid** | NIPs | NIP-11 info fetch/parse, NIP-66 health checks (I/O) | Protocol spec updates |
| **Mid** | Utils | DNS, keys, transport, SOCKS5 proxy | Cross-cutting needs |
| **Foundation** | Models | Frozen dataclasses, validation, DB mapping | Schema changes |

Deployments (`deployments/{bigbrotr,lilbrotr,_template}/`) sit outside the package and configure behavior through YAML, SQL schemas, and Docker Compose.

---

## Models Layer

`src/bigbrotr/models/` -- Pure frozen dataclasses. Zero I/O, zero `bigbrotr` imports. Uses only `import logging` + `logging.getLogger()`.

### Data Models

| Model | File | Purpose |
|-------|------|---------|
| `Relay` | `relay.py` | URL validation (rfc3986), network detection (clearnet/tor/i2p/loki/local), local IP rejection |
| `Event` | `event.py` | Wraps nostr-sdk Event, extracts hex fields, tag parsing |
| `EventRelay` | `event_relay.py` | Event-relay junction with `seen_at` timestamp |
| `Metadata` | `metadata.py` | Content-addressed metadata: SHA-256 hash over canonical JSON |
| `RelayMetadata` | `relay_metadata.py` | Relay-metadata junction with `metadata_type` and `generated_at` |
| `ServiceState` | `service_state.py` | Per-service operational state (candidates, cursors, checkpoints) |

### Enumerations

| Type | File | Values |
|------|------|--------|
| `NetworkType` | `constants.py` | `clearnet`, `tor`, `i2p`, `loki`, `local`, `unknown` |
| `MetadataType` | `metadata.py` | `nip11_info`, `nip66_rtt`, `nip66_ssl`, `nip66_geo`, `nip66_net`, `nip66_dns`, `nip66_http` |
| `StateType` | `service_state.py` | `candidate`, `cursor`, `checkpoint` |
| `EventKind` | `service_state.py` | `RECOMMEND_RELAY=2`, `CONTACTS=3`, `RELAY_LIST=10002`, `NIP66_TEST=22456`, `MONITOR_ANNOUNCEMENT=10166`, `RELAY_DISCOVERY=30166` |

### Model Patterns

All models follow the same frozen dataclass pattern:

```python
@dataclass(frozen=True, slots=True)
class Relay:
    url: str
    discovered_at: int
    _db_params: RelayDbParams = field(init=False, repr=False)

    def __post_init__(self) -> None:
        # Validate and compute derived fields
        parsed = rfc3986.uri_reference(self.url)
        network = _detect_network(parsed.host)
        object.__setattr__(self, "network", network)
        object.__setattr__(self, "_db_params", self._compute_db_params())

    def _compute_db_params(self) -> RelayDbParams: ...
    def to_db_params(self) -> RelayDbParams:
        return self._db_params  # cached, no recomputation

    @classmethod
    def from_db_params(cls, url: str, ...) -> Relay: ...
```

Key characteristics:

- `frozen=True` + `slots=True` on all models
- `_compute_db_params()` runs once in `__post_init__`, cached in `_db_params`
- `object.__setattr__` for setting fields in frozen `__post_init__`
- `from_db_params()` classmethod for reconstruction from database rows
- `to_db_params()` returns a typed NamedTuple matching stored procedure parameter order

### ServiceState and ServiceStateKey

`ServiceState` was extracted from `services/common/constants.py` to `models/service_state.py` to fix a DAG violation (core was importing from services via `TYPE_CHECKING`).

```python
@dataclass(frozen=True, slots=True)
class ServiceState:
    service_name: str
    state_type: str
    state_key: str
    payload: dict[str, Any]
    updated_at: int

class ServiceStateKey(NamedTuple):
    service_name: str
    state_type: str
    state_key: str
```

---

## Core Layer

`src/bigbrotr/core/` -- Reusable infrastructure with zero business logic. Depends only on models.

### Pool (`pool.py`)

Async PostgreSQL connection pool via asyncpg with retry/backoff, health-checked acquisition.

**Configuration:**

```python
class PoolConfig(BaseModel):
    database: DatabaseConfig       # host, port, database, user (password from DB_PASSWORD env)
    limits: LimitsConfig           # min_size, max_size, max_queries, max_inactive_connection_lifetime
    timeouts: PoolTimeoutsConfig   # acquisition, health_check
    retry: PoolRetryConfig         # max_attempts, initial_delay, max_delay, exponential_backoff
    server_settings: ServerSettingsConfig  # application_name, timezone, statement_timeout
```

**Key methods:**

| Method | Purpose |
|--------|---------|
| `connect()` | Create asyncpg pool with retry backoff |
| `close()` | Idempotent pool teardown |
| `acquire()` | Get connection from pool |
| `acquire_healthy()` | Get connection with health check retry |
| `transaction()` | Async context manager for ACID transactions |
| `fetch()`, `fetchrow()`, `fetchval()` | Query methods with automatic retry on transient errors |
| `execute()`, `executemany()` | Mutation methods |
| `metrics` (property) | Pool statistics: size, utilization, is_connected |

In Docker deployments, services connect to **PGBouncer** (port 6432/6433) which provides infrastructure-level connection pooling in transaction mode. Pool provides application-level retry, health checking, and query methods.

### Brotr (`brotr.py`)

High-level database facade. Wraps stored procedures via `_call_procedure()`. Provides generic query methods that services use.

**Configuration:**

```python
class BrotrConfig(BaseModel):
    batch: BatchConfig              # max_size (default 1000)
    timeouts: BrotrTimeoutsConfig   # query (60s), batch (120s), cleanup (90s), refresh (None)
```

**Insert operations** (all accept lists, auto-batch by `batch.max_size`):

| Method | Stored Function Called | Cascade |
|--------|----------------------|---------|
| `insert_relay(relays)` | `relay_insert` | -- |
| `insert_event(events)` | `event_insert` | -- |
| `insert_metadata(metadata)` | `metadata_insert` | -- |
| `insert_event_relay(records, cascade=True)` | `event_relay_insert_cascade` | Relay + Event + Junction |
| `insert_relay_metadata(records, cascade=True)` | `relay_metadata_insert_cascade` | Relay + Metadata + Junction |

**Service state:**

| Method | Stored Function Called |
|--------|----------------------|
| `upsert_service_state(records)` | `service_state_upsert` |
| `get_service_state(service, type, key?)` | `service_state_get` |
| `delete_service_state(keys)` | `service_state_delete` |

**Cleanup and maintenance:**

| Method | Stored Function Called |
|--------|----------------------|
| `delete_orphan_event()` | `orphan_event_delete` |
| `delete_orphan_metadata()` | `orphan_metadata_delete` |
| `refresh_materialized_view(name)` | `{name}_refresh` |

**Generic query facade** (used by services for ad-hoc queries):

- `fetch(query, *args, timeout)` -> `list[Record]`
- `fetchrow(query, *args, timeout)` -> `Record | None`
- `fetchval(query, *args, timeout)` -> `Any`
- `execute(query, *args, timeout)` -> `str`
- `transaction()` -> async context manager yielding a connection

`Brotr._pool` is **private** -- services use Brotr methods, never pool directly.

### BaseService (`base_service.py`)

Abstract base class for all five services. Generic over configuration type.

```python
class BaseService(ABC, Generic[ConfigT]):
    SERVICE_NAME: ClassVar[str]
    CONFIG_CLASS: ClassVar[type[BaseModel]]

    _brotr: Brotr
    _config: ConfigT
```

**Lifecycle:**

| Method | Purpose |
|--------|---------|
| `run()` | Abstract -- single cycle logic |
| `run_forever()` | Loop: `run()` -> `wait(interval)` -> repeat. Tracks consecutive failures. |
| `request_shutdown()` | Sync-safe flag for signal handlers |
| `wait(timeout)` -> `bool` | Interruptible sleep. Returns `True` if shutdown was requested. |
| `is_running` (property) | `True` until shutdown requested |

**Factory methods:**

- `from_yaml(config_path, brotr, **kwargs)` -> configured service instance
- `from_dict(data, brotr, **kwargs)` -> configured service instance

**Metrics integration:**

- `set_gauge(name, value)` -- custom Prometheus gauge
- `inc_counter(name, value=1)` -- custom Prometheus counter
- Automatic cycle duration tracking via `CYCLE_DURATION_SECONDS` histogram

**Context manager** (`async with service:`) handles lifecycle setup/teardown.

### Exceptions (`exceptions.py`)

Structured exception hierarchy replacing bare `except Exception`:

```text
BigBrotrError (base)
├── ConfigurationError          # YAML, env vars, CLI args
├── DatabaseError
│   ├── ConnectionPoolError     # Transient: pool exhausted, network blip -> retry
│   └── QueryError              # Permanent: bad SQL, constraint violation -> don't retry
├── ConnectivityError
│   ├── RelayTimeoutError       # Connection or response timed out
│   └── RelaySSLError           # TLS/SSL certificate failures
├── ProtocolError               # NIP parsing/validation failures
└── PublishingError             # Nostr event broadcast failures
```

Services catch specific exceptions for appropriate handling: retry on `ConnectionPoolError`, skip relay on `RelayTimeoutError`, log and continue on `ProtocolError`.

### Logger (`logger.py`)

Structured key=value logging with optional JSON output mode.

```python
logger = Logger("synchronizer")
logger.info("sync_completed", events=1500, duration=45.2)
# Output: 2026-02-09 12:00:00 INFO synchronizer: sync_completed events=1500 duration=45.2
```

JSON mode output for cloud aggregation:

```json
{"timestamp": "2026-02-09T12:34:56+00:00", "level": "info", "service": "synchronizer", "message": "sync_completed", "events": 1500}
```

### Metrics (`metrics.py`)

Prometheus metrics served on `/metrics` (port 8000).

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `service_info` | Info | service | Static service metadata |
| `service_gauge` | Gauge | service, name | Point-in-time state (consecutive_failures, progress, last_cycle_timestamp) |
| `service_counter` | Counter | service, name | Cumulative totals (cycles_success, cycles_failed, errors) |
| `cycle_duration_seconds` | Histogram | service | Cycle latency, 10 buckets (1s to 1h) |

**MetricsConfig:**

- `enabled: bool` (default `False`)
- `port: int` (default `8000`)
- `host: str` (default `"127.0.0.1"`, use `"0.0.0.0"` in containers)
- `path: str` (default `"/metrics"`)

### YAML Loader (`yaml.py`)

YAML configuration loading with environment variable interpolation.

---

## NIPs Layer

`src/bigbrotr/nips/` -- NIP-11 and NIP-66 protocol implementations. Has I/O (HTTP, DNS, SSL, WebSocket, GeoIP). Depends on models, utils, core.

### NIP-11 (`nip11/`)

Relay Information Document (NIP-11) fetch and parse.

| Module | Purpose |
|--------|---------|
| `fetch.py` | HTTP GET to relay URL with `Accept: application/nostr+json` |
| `data.py` | Parsed NIP-11 document fields (name, description, pubkey, contact, supported_nips, etc.) |
| `logs.py` | Structured logging for NIP-11 operations |
| `nip11.py` | `Nip11` orchestrator class |

### NIP-66 (`nip66/`)

Relay Monitoring and Discovery (NIP-66) health check implementations.

| Module | What It Measures |
|--------|-----------------|
| `rtt.py` | WebSocket round-trip times: open, read, write latency (ms) |
| `ssl.py` | Certificate validity, expiry date, issuer, cipher suite |
| `dns.py` | A/AAAA/CNAME/NS/PTR records, query time |
| `geo.py` | Country, city, coordinates, timezone, geohash (via GeoLite2) |
| `net.py` | IP address, ASN number, ASN organization (via GeoLite2 ASN) |
| `http.py` | Server header, X-Powered-By header |
| `nip66.py` | `Nip66` orchestrator class |

Each module produces a `RelayMetadata` object with the corresponding `MetadataType`. The Monitor service calls these and persists results.

---

## Utils Layer

`src/bigbrotr/utils/` -- Shared utilities. Depends only on models.

| Module | Key Exports | Purpose |
|--------|-------------|---------|
| `transport.py` | `connect_relay()`, `is_nostr_relay()`, `create_client()`, `create_insecure_client()` | WebSocket/HTTP transport with SOCKS5 proxy and SSL fallback |
| `keys.py` | `load_keys_from_env()`, `KeysConfig` | Nostr key management (hex/nsec loading from env) |
| `dns.py` | DNS resolution utilities | dnspython wrapper |

### Transport SSL Fallback

`connect_relay()` implements a two-phase connection strategy:

1. **Clearnet**: try standard SSL first; fall back to insecure (disabled SSL verification) if `allow_insecure=True`
2. **Overlay** (Tor/I2P/Loki): require `proxy_url`, no SSL fallback

`InsecureWebSocketAdapter` and `InsecureWebSocketTransport` handle relays with invalid certificates.

---

## Service Layer

`src/bigbrotr/services/` -- Business logic. Depends on core, nips, utils, models.

### Service Architecture Pattern

All five services follow the same pattern:

```python
class MyService(BaseService[MyServiceConfig]):
    SERVICE_NAME = "myservice"
    CONFIG_CLASS = MyServiceConfig

    def __init__(self, brotr: Brotr, config: MyServiceConfig | None = None):
        super().__init__(brotr=brotr, config=config or MyServiceConfig())

    async def run(self) -> None:
        """Single cycle -- called repeatedly by run_forever()."""
        ...
```

Configuration classes inherit from `BaseServiceConfig` which provides:

- `interval: float` (default 300s, minimum 60s)
- `max_consecutive_failures: int` (default 5, 0=unlimited)
- `metrics: MetricsConfig`

### Shared Infrastructure (`services/common/`)

| Module | Purpose |
|--------|---------|
| `constants.py` | `ServiceName` and `DataType` StrEnum enumerations |
| `queries.py` | 13 domain SQL query functions |
| `mixins.py` | `BatchProgress` dataclass, `BatchProgressMixin`, `NetworkSemaphoreMixin` |
| `configs.py` | Per-network Pydantic config models |

**Domain Query Functions** (13 total in `queries.py`):

| Function | Purpose |
|----------|---------|
| `get_all_relay_urls(brotr)` | All relay URLs |
| `get_all_relays(brotr)` | All relays with network + discovered_at |
| `filter_new_relay_urls(brotr, urls)` | URLs not yet in relay table |
| `count_relays_due_for_check(brotr, ...)` | Count relays needing health check |
| `fetch_relays_due_for_check(brotr, ...)` | Fetch relays needing health check |
| `get_events_with_relay_urls(brotr, ...)` | Events containing relay URLs |
| `upsert_candidates(brotr, relays)` | Insert/update validation candidates |
| `count_candidates(brotr, networks)` | Count pending candidates |
| `fetch_candidate_chunk(brotr, ...)` | Fetch candidate batch for validation |
| `delete_stale_candidates(brotr)` | Remove candidates already in relay table |
| `delete_exhausted_candidates(brotr, ...)` | Remove candidates exceeding max_failures |
| `promote_candidates(brotr, relays)` | Move validated candidates to relay table |
| `get_all_service_cursors(brotr, ...)` | Get sync cursors for all relays |

**Network Configuration** (`configs.py`):

| Config | Default Enabled | Proxy | Max Tasks | Timeout |
|--------|----------------|-------|-----------|---------|
| `ClearnetConfig` | Yes | None | 50 | 10s |
| `TorConfig` | No | `socks5://tor:9050` | 10 | 30s |
| `I2pConfig` | No | `socks5://i2p:4447` | 5 | 45s |
| `LokiConfig` | No | `socks5://lokinet:1080` | 5 | 30s |

`NetworkConfig` wraps all four and provides `get(network)`, `is_enabled(network)`, `get_proxy_url(network)`, `get_enabled_networks()`.

**BatchProgress** (`mixins.py`):

Mutable tracker for batch operations (not frozen -- has `reset()` method):

```python
@dataclass(slots=True)
class BatchProgress:
    started_at: float      # wall-clock
    total: int
    processed: int
    success: int
    failure: int
    chunks: int
```

**NetworkSemaphoreMixin**: creates one `asyncio.Semaphore` per enabled network, limiting concurrency to `max_tasks`.

### Seeder Service (`seeder.py`)

**Purpose**: Load relay URLs from a seed file and insert as candidates for validation.

**Lifecycle**: One-shot (`--once` flag)

**Configuration:**

- `file_path: str` (default `"static/seed_relays.txt"`)
- `to_validate: bool` (default `True`) -- if True, inserts as candidates; if False, directly to relay table

**Flow:**

1. Read seed file (one URL per line, `#` comments skipped)
2. Parse each URL into a `Relay` object (validates URL, detects network type)
3. Insert as candidates via `upsert_candidates()` or directly via `insert_relay()`

### Finder Service (`finder.py`)

**Purpose**: Discover new relay URLs from stored events and external APIs.

**Lifecycle**: Continuous (`run_forever`, default interval 1h)

**Discovery sources:**

1. **Event scanning** -- extracts relay URLs from:
   - Kind 3 (contact list): content field contains JSON with relay URLs as keys
   - Kind 10002 (NIP-65 relay list): `r` tags contain relay URLs
   - Any event with `r` tags

2. **API fetching** -- HTTP requests to external sources:
   - Default: nostr.watch online/offline relay list endpoints
   - Configurable timeout, SSL verification, delay between requests

**Flow:**

1. Scan stored events for relay URLs (`_find_from_events()`)
2. Fetch external API sources (`_find_from_api()`)
3. Filter out URLs already in the relay table
4. Insert new URLs as candidates via `upsert_candidates()`

### Validator Service (`validator.py`)

**Purpose**: Test candidate relay URLs and promote valid ones.

**Lifecycle**: Continuous (`run_forever`, default interval 8h)

**Candidate dataclass:**

```python
@dataclass(frozen=True, slots=True)
class Candidate:
    relay: Relay
    data: dict[str, Any]  # from service_state payload

    @property
    def failed_attempts(self) -> int:
        return self.data.get("failed_attempts", 0)
```

**Flow:**

1. Delete stale candidates (URLs already in relay table)
2. Delete exhausted candidates (exceeded `max_failures`)
3. Fetch chunk of candidates ordered by failure count (ASC) then age (ASC)
4. Validate in parallel with per-network semaphores via `is_nostr_relay(relay, timeout, proxy_url)`
5. Promote valid candidates to relay table; increment failure count for invalid ones
6. Repeat until all candidates processed

**Configuration:**

- `networks: NetworkConfig` -- per-network timeouts and concurrency
- `processing: ValidatorProcessingConfig` -- chunk_size, max_candidates
- `cleanup: CleanupConfig` -- enabled, max_failures

### Monitor Service (`monitor.py` + `monitor_publisher.py` + `monitor_tags.py`)

**Purpose**: Health check all relays and publish results as Nostr events.

**Lifecycle**: Continuous (`run_forever`, default interval 1h)

The Monitor service is split across three modules:

| Module | Lines | Responsibility |
|--------|-------|---------------|
| `monitor.py` | ~600 | Config models, health check orchestration, GeoIP, DB persistence |
| `monitor_publisher.py` | ~230 | Nostr event broadcasting: kind 0, 10166, 30166 |
| `monitor_tags.py` | ~280 | NIP-66 tag building for kind 30166 events |

**Class hierarchy using mixins:**

```python
class Monitor(
    MonitorTagsMixin,        # from monitor_tags.py
    MonitorPublisherMixin,   # from monitor_publisher.py
    BatchProgressMixin,      # from services/common/mixins.py
    NetworkSemaphoreMixin,   # from services/common/mixins.py
    BaseService[MonitorConfig],
): ...
```

**CheckResult** (what each relay check produces):

```python
class CheckResult(NamedTuple):
    nip11: RelayMetadata | None
    nip66_rtt: RelayMetadata | None
    nip66_ssl: RelayMetadata | None
    nip66_geo: RelayMetadata | None
    nip66_net: RelayMetadata | None
    nip66_dns: RelayMetadata | None
    nip66_http: RelayMetadata | None
```

**Orchestration flow:**

1. `run()` -- fetch relays due for check, chunk them
2. `_check_chunk(relays)` -- parallel checks with semaphore
3. `_check_one(relay)` -- run NIP-11 + all NIP-66 checks, return `CheckResult`
4. `_persist_results(successful, failed)` -- insert metadata to DB
5. `_publish_relay_discoveries(successful)` -- build and broadcast kind 30166 events
6. `_publish_announcement()` -- kind 10166 (monitor capabilities)
7. `_publish_profile()` -- kind 0 (monitor profile metadata)

**Published Nostr events:**

| Kind | Type | Content |
|------|------|---------|
| 0 | Profile | Monitor name, about, picture (NIP-01) |
| 10166 | Announcement | Monitor capabilities, check frequency, supported checks (NIP-66) |
| 30166 | Discovery | Per-relay health data: RTT, SSL, DNS, Geo, Net, NIP-11 (addressable, `d` tag = relay URL) |

**Tag building** (`monitor_tags.py`):

| Method | Tags Produced |
|--------|--------------|
| `_add_rtt_tags()` | `rtt-open`, `rtt-read`, `rtt-write` |
| `_add_ssl_tags()` | `ssl`, `ssl-expires`, `ssl-issuer` |
| `_add_net_tags()` | `net-ip`, `net-ipv6`, `net-asn`, `net-asn-org` |
| `_add_geo_tags()` | `g` (geohash), `geo-country`, `geo-city`, `geo-lat`, `geo-lon`, `geo-tz` |
| `_add_nip11_tags()` | `N` (NIPs), `t` (topics), `l` (languages), `R` (requirements), `T` (types) |

### Synchronizer Service (`synchronizer.py`)

**Purpose**: Connect to relays, subscribe to events, archive to PostgreSQL.

**Lifecycle**: Continuous (`run_forever`, default interval 15m)

**EventBatch** -- bounded event buffer:

```python
class EventBatch:
    since: int           # filter start timestamp
    until: int           # filter end timestamp
    limit: int           # max events
    events: list[Event]  # collected events

    def append(event) -> None   # raises OverflowError if full
    def is_full() -> bool
    def is_empty() -> bool
```

**SyncContext** -- immutable per-sync configuration:

```python
@dataclass(frozen=True, slots=True)
class SyncContext:
    filter_config: FilterConfig
    network_config: NetworkConfig
    request_timeout: float
    brotr: Brotr
    keys: Keys
```

**Flow:**

1. `run()` -- fetch relays from DB, load cursors, distribute work
2. `_sync_all_relays(relays)` -- `TaskGroup` with semaphore coordination
3. For each relay: connect via WebSocket, subscribe with filter, collect events
4. Per-relay cursor tracking via `ServiceState` with `StateType.CURSOR`
5. Batch insert events + relay junctions via `insert_event_relay(cascade=True)`
6. Flush cursor updates periodically

**Configuration highlights:**

- `filter: FilterConfig` -- event kinds, authors, tags, limit
- `time_range: TimeRangeConfig` -- default_start, use_relay_state, lookback_seconds
- `concurrency: SyncConcurrencyConfig` -- max_parallel, cursor_flush_interval, stagger_delay
- `overrides: list[RelayOverride]` -- per-relay timeout/URL overrides

---

## Database Architecture

PostgreSQL 16 with PGBouncer (transaction-mode pooling) and asyncpg async driver.

### Tables (6)

| Table | Primary Key | Purpose |
|-------|-------------|---------|
| `relay` | `url` | Validated relay URLs with `network` and `discovered_at` |
| `event` | `id` (BYTEA) | Nostr events. BYTEA for id/pubkey/sig (space efficiency). `tags` JSONB, `tagvalues` generated column, `content` TEXT. |
| `event_relay` | `(event_id, relay_url)` | Junction: which events seen at which relays, with `seen_at` |
| `metadata` | `id` (BYTEA) | Content-addressed NIP-11/NIP-66 documents. SHA-256 hash as ID, `payload` JSONB. |
| `relay_metadata` | `(relay_url, generated_at, metadata_type)` | Time-series snapshots linking relays to metadata records |
| `service_state` | `(service_name, state_type, state_key)` | Service operational data: candidates, cursors, checkpoints |

**Column naming:**

- Metadata content: `payload` (NOT `value`)
- Metadata type: `metadata_type` (NOT `type`)
- No CHECK constraints -- validation in Python enum layer

### Stored Functions (22)

All functions use `SECURITY INVOKER`, bulk array parameters, and `ON CONFLICT DO NOTHING`.

| Category | Functions | Count |
|----------|-----------|-------|
| **Utility** | `tags_to_tagvalues` (extracts single-char tag values for GIN indexing) | 1 |
| **CRUD** | `relay_insert`, `event_insert`, `metadata_insert`, `event_relay_insert`, `relay_metadata_insert`, `event_relay_insert_cascade`, `relay_metadata_insert_cascade`, `service_state_upsert`, `service_state_get`, `service_state_delete` | 10 |
| **Cleanup** | `orphan_event_delete`, `orphan_metadata_delete`, `relay_metadata_delete_expired` (all batched with LIMIT loops) | 3 |
| **Refresh** | One per materialized view + `all_statistics_refresh` | 8 |

### Materialized Views (7)

| View | Purpose |
|------|---------|
| `relay_metadata_latest` | Most recent metadata per relay per type |
| `event_stats` | Global event statistics |
| `relay_stats` | Per-relay event counts |
| `kind_counts` | Event counts by kind |
| `kind_counts_by_relay` | Event counts by kind per relay |
| `pubkey_counts` | Event counts by pubkey |
| `pubkey_counts_by_relay` | Event counts by pubkey per relay |

All support `REFRESH CONCURRENTLY` via unique indexes.

### Schema Initialization

SQL files in `deployments/*/postgres/init/` are numbered `00-99` and run in order by PostgreSQL's entrypoint:

| File | Content |
|------|---------|
| `00_extensions.sql` | Extensions (none currently, pgcrypto removed) |
| `01_functions_utility.sql` | `tags_to_tagvalues` |
| `02_tables.sql` | 6 tables |
| `03_functions_crud.sql` | 10 CRUD functions |
| `04_functions_cleanup.sql` | 3 cleanup functions |
| `05_materialized_views.sql` | 7 materialized views |
| `06_functions_refresh.sql` | 8 refresh functions |
| `07_triggers.sql` | Triggers |
| `08_indexes.sql` | Indexes (GIN on tagvalues, B-tree on timestamps, etc.) |
| `09_permissions.sql` | Role grants |

### Deployment-Specific Schemas

**BigBrotr** (full archive): stores tags JSONB, generated tagvalues, content TEXT.

```sql
CREATE TABLE event (
    id BYTEA PRIMARY KEY,
    pubkey BYTEA NOT NULL,
    created_at BIGINT NOT NULL,
    kind INTEGER NOT NULL,
    tags JSONB NOT NULL,
    tagvalues TEXT[] GENERATED ALWAYS AS (tags_to_tagvalues(tags)) STORED,
    content TEXT NOT NULL,
    sig BYTEA NOT NULL
);
```

**LilBrotr** (lightweight): omits tags, tagvalues, content for ~60% disk savings.

```sql
CREATE TABLE event (
    id BYTEA PRIMARY KEY,
    pubkey BYTEA NOT NULL,
    created_at BIGINT NOT NULL,
    kind INTEGER NOT NULL,
    sig BYTEA NOT NULL
);
```

---

## Data Flow

### Service Pipeline

```text
┌──────────┐    ┌──────────┐    ┌───────────┐    ┌──────────┐    ┌──────────────┐
│  Seeder  │───>│  Finder  │───>│ Validator │───>│ Monitor  │    │ Synchronizer │
│(one-shot)│    │(discover)│    │  (test)   │    │ (health) │    │  (archive)   │
└──────────┘    └──────────┘    └───────────┘    └──────────┘    └──────────────┘
     │               │               │                │                │
     v               v               v                v                v
┌────────────────────────────────────────────────────────────────────────────────┐
│                              PostgreSQL                                       │
│  service_state ──> relay ──> event_relay <── event                            │
│  (candidates)                relay_metadata <── metadata                      │
└────────────────────────────────────────────────────────────────────────────────┘
```

1. **Seeder** loads seed URLs -> inserts as candidates in `service_state`
2. **Finder** discovers URLs from events (kind 3, 10002) and APIs -> inserts as candidates
3. **Validator** tests candidates via WebSocket -> promotes valid ones to `relay` table
4. **Monitor** health-checks relays (NIP-11 + NIP-66) -> inserts `metadata` + `relay_metadata`, publishes kind 10166/30166
5. **Synchronizer** connects to relays, subscribes to events -> inserts `event` + `event_relay`

### Metadata Deduplication

Metadata is content-addressed: SHA-256 hash over canonical JSON. When the Monitor produces identical metadata for a relay, only a new `relay_metadata` row is inserted (linking the relay to the existing `metadata` record). The cascade function handles this:

```text
Monitor._check_one(relay) -> CheckResult (7 metadata types)
    |
    v
insert_relay_metadata(records, cascade=True)
    |
    v
relay_metadata_insert_cascade(arrays...):
    1. INSERT INTO relay ON CONFLICT DO NOTHING
    2. INSERT INTO metadata ON CONFLICT DO NOTHING  (dedup by hash)
    3. INSERT INTO relay_metadata                    (time-series link)
```

---

## Concurrency Model

### Async I/O

All I/O is async:

- `asyncpg` for database
- `aiohttp` for HTTP
- `aiohttp-socks` for SOCKS5 proxy
- `nostr-sdk` for WebSocket (via Rust FFI/PyO3)

### Connection Pooling

```text
Application                 PGBouncer                PostgreSQL
    │                           │                        │
    ├── asyncpg pool ──────────>├── connection pool ────>│
    │   (configurable)          │   (transaction mode)   │ (max_connections)
    │                           │                        │
    ├── finder ────────────────>│                        │
    ├── validator ─────────────>│                        │
    ├── monitor ───────────────>│                        │
    └── synchronizer ──────────>│                        │
```

### Per-Network Semaphores

Services that contact relays (Validator, Monitor, Synchronizer) use `NetworkSemaphoreMixin` to limit concurrent connections per network type:

| Network | Default Max Tasks | Default Timeout |
|---------|-------------------|-----------------|
| Clearnet | 50 | 10s |
| Tor | 10 | 30s |
| I2P | 5 | 45s |
| Lokinet | 5 | 30s |

### Graceful Shutdown

```python
# Signal handler (sync context, safe to call from signal)
def handle_signal(signum, frame):
    service.request_shutdown()  # Sets asyncio.Event, no await

# run_forever loop
while not self._shutdown_requested:
    await self.run()            # Single cycle
    if await self.wait(interval):  # Interruptible sleep
        break                      # Shutdown requested during wait

# Cleanup via async context manager __aexit__
```

---

## Deployment Architecture

### Container Stack

All deployments use a single parametric Dockerfile (`deployments/Dockerfile` with `ARG DEPLOYMENT`).

| Container | Image | Networks | Purpose |
|-----------|-------|----------|---------|
| postgres | postgres:16-alpine | data | Primary storage |
| pgbouncer | edoburu/pgbouncer | data | Transaction-mode connection pooling |
| tor | osminogin/tor-simple | data | SOCKS5 proxy for .onion relays |
| finder | bigbrotr (parametric) | data, monitoring | Relay discovery |
| validator | bigbrotr (parametric) | data, monitoring | Candidate validation |
| monitor | bigbrotr (parametric) | data, monitoring | Health monitoring |
| synchronizer | bigbrotr (parametric) | data, monitoring | Event archiving |
| prometheus | prom/prometheus | monitoring | Metrics collection |
| grafana | grafana/grafana | monitoring | Dashboards |

### Network Segmentation

- **data-network**: postgres, pgbouncer, tor, all Python services
- **monitoring-network**: prometheus, grafana, all Python services (for `/metrics` scraping)

Postgres is only on the data network. Grafana is only on the monitoring network.

### Container Security

- All ports bound to `127.0.0.1` (no external exposure)
- Non-root container execution (UID 1000)
- `tini` as PID 1 for proper signal handling and zombie reaping
- SCRAM-SHA-256 authentication for PostgreSQL and PGBouncer
- Real healthchecks via `curl -sf http://localhost:8000/metrics` (not fake PID checks)
- Resource limits on all containers (`deploy.resources.limits`)

### Deployments

| Deployment | Schema | Networks | Use Case |
|------------|--------|----------|----------|
| **bigbrotr** | Full (tags, content, 7 mat views) | Clearnet + Tor | Production archiving |
| **lilbrotr** | Minimal (no tags/content, 5 mat views) | Clearnet only | Lightweight indexing, ~60% disk savings |
| **_template** | Customizable | Configurable | Starting point for custom deployments |

---

## Design Patterns

### Dependency Injection

Services receive `Brotr` via constructor, enabling mock injection for testing:

```python
service = Monitor(brotr=brotr, config=config)

# Testing
mock_brotr = MagicMock(spec=Brotr)
service = Monitor(brotr=mock_brotr)
```

### Composition over Inheritance

`Brotr` HAS-A `Pool` (not IS-A). Services HAS-A `Brotr`. This enables independent testing and lifecycle management.

### Template Method

`BaseService.run_forever()` calls the abstract `run()` method in a loop with interval, failure tracking, and shutdown checks. Subclasses implement only `run()`.

### Mixins for Cross-Cutting Concerns

Monitor uses multiple mixins to compose behavior:

- `MonitorTagsMixin` -- tag building (from `monitor_tags.py`)
- `MonitorPublisherMixin` -- Nostr broadcasting (from `monitor_publisher.py`)
- `BatchProgressMixin` -- batch tracking (from `services/common/mixins.py`)
- `NetworkSemaphoreMixin` -- per-network concurrency (from `services/common/mixins.py`)

### Content-Addressed Deduplication

Metadata uses SHA-256 hash as primary key. Identical NIP-11/NIP-66 results across time or relays produce the same hash, deduplicating storage. Time-series tracking is via the `relay_metadata` junction table.

### Factory Methods

All services support three construction paths:

```python
service = Monitor.from_yaml("config.yaml", brotr=brotr)     # from YAML file
service = Monitor.from_dict(config_dict, brotr=brotr)        # from dict
service = Monitor(brotr=brotr, config=MonitorConfig(...))     # direct
```

### Context Managers

Resources are automatically managed:

```python
async with brotr:           # connect pool on enter, close on exit
    async with service:     # lifecycle setup/teardown
        await service.run_forever()
```

---

## Configuration System

### Configuration Hierarchy

```text
deployments/bigbrotr/config/
├── brotr.yaml                  # Pool, batch size, timeouts
└── services/
    ├── seeder.yaml             # file_path, to_validate
    ├── finder.yaml             # API sources, event scan, interval
    ├── validator.yaml          # Networks, chunk_size, max_failures, interval
    ├── monitor.yaml            # Networks, GeoIP, publishing, checks, interval
    └── synchronizer.yaml       # Networks, filter, concurrency, overrides, interval
```

### Pydantic Validation

All configuration uses Pydantic v2 models with:

- Typed fields with defaults and constraints (`Field(ge=1, le=65535)`)
- Nested models (e.g., `MonitorConfig.networks.clearnet.timeout`)
- `model_validator` for cross-field validation (e.g., Monitor keys at config load time)
- Environment variable injection for secrets (`DB_PASSWORD`, `PRIVATE_KEY`)

### Environment Variables

| Variable | Required | Used By |
|----------|----------|---------|
| `DB_PASSWORD` | Yes | Pool (database password) |
| `PRIVATE_KEY` | For Monitor | Monitor (Nostr event signing, RTT write tests) |
| `GRAFANA_PASSWORD` | No | Grafana (admin password) |

---

## Monitoring Stack

### Prometheus

Scrape configuration in `deployments/*/monitoring/prometheus/prometheus.yaml`:

- 4 service targets (finder, validator, monitor, synchronizer) on port 8000
- 1 self-monitoring target (localhost:9090)
- 15s global scrape interval, 30s per service

### Alerting Rules

4 rules in `deployments/*/monitoring/prometheus/rules/alerts.yml`:

| Alert | Condition | Severity |
|-------|-----------|----------|
| ServiceDown | `up == 0` for 5m | critical |
| HighFailureRate | error rate > 0.1/s for 5m | warning |
| PoolExhausted | zero available connections for 2m | critical |
| DatabaseSlow | p99 query latency > 5s for 5m | warning |

### Grafana

Auto-provisioned dashboards and datasources. Per-service panels: last cycle time, cycle duration histogram, error counts (24h), consecutive failures.

---

## Testing Architecture

### Test Structure

```text
tests/
├── conftest.py                  # Root: mock_pool, mock_brotr, mock_connection, sample_*
├── fixtures/
│   └── relays.py                # Shared relay fixtures (registered as pytest plugin)
├── unit/                        # 2049 tests, mirrors src/ structure
│   ├── core/                    # test_pool.py, test_brotr.py, test_base_service.py, ...
│   ├── models/                  # test_relay.py, test_event.py, test_metadata.py, ...
│   ├── nips/                    # nip11/, nip66/
│   ├── services/                # test_monitor.py, test_synchronizer.py, ...
│   └── utils/                   # test_transport.py, test_keys.py, ...
└── integration/                 # 8 tests (testcontainers PostgreSQL)
```

### Test Configuration

- `asyncio_mode = "auto"` -- no `@pytest.mark.asyncio` needed
- Global timeout: `--timeout=120` per test
- Coverage threshold: `fail_under = 80` (branch coverage enabled)
- Fixtures registered via `pytest_plugins = ["tests.fixtures.relays"]`
- Custom markers: `integration`, `unit`, `slow`

### Mock Patterns

- Mock targets use `bigbrotr.` prefix: `@patch("bigbrotr.services.validator.is_nostr_relay")`
- Service tests mock query functions at the **service module namespace** (not `bigbrotr.core.queries.*`)
- Root conftest provides: `mock_pool`, `mock_brotr`, `mock_connection`, `mock_asyncpg_pool`, `sample_event`, `sample_relay`, `sample_metadata`, `sample_events_batch`, `sample_relays_batch`
