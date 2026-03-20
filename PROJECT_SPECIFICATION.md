# BigBrotr Project Specification

## Executive Summary

BigBrotr is a modular Nostr network observatory — a production-grade, fully asynchronous Python system that discovers, validates, monitors, and archives data from the Nostr relay network, materializes analytics views, and exposes everything through a REST API and a NIP-90 Data Vending Machine. It answers three fundamental questions:

1. **What relays exist on the Nostr network?**
2. **How healthy are they?**
3. **What events are they publishing?**

Eight independent async services share a PostgreSQL 16 backend, each deployable and scalable on its own. The system supports clearnet (TLS), Tor (.onion), I2P (.i2p), and Lokinet (.loki) relay networks with per-network concurrency control and proxy routing. Built on Python 3.11+ with strict typing, asyncio, and full Prometheus/Grafana observability.

---

## Table of Contents

1. [Purpose and Scope](#1-purpose-and-scope)
2. [Architecture Overview](#2-architecture-overview)
3. [Domain Model](#3-domain-model)
4. [Services](#4-services)
5. [NIP Protocol Implementations](#5-nip-protocol-implementations)
6. [Utilities](#6-utilities)
7. [Database Design](#7-database-design)
8. [Infrastructure and Deployment](#8-infrastructure-and-deployment)
9. [Observability](#9-observability)
10. [Quality Assurance](#10-quality-assurance)
11. [Technology Stack](#11-technology-stack)
12. [Configuration System](#12-configuration-system)
13. [Security Model](#13-security-model)
14. [Extensibility](#14-extensibility)
15. [Deployment Variants](#15-deployment-variants)
16. [CLI](#16-cli)

---

## 1. Purpose and Scope

### What Is Nostr?

Nostr (Notes and Other Stuff Transmitted by Relays) is a decentralized, censorship-resistant social protocol. Users publish cryptographically signed events to relays (WebSocket servers), which store and distribute them. There is no central directory of relays; they are independently operated and discovered organically.

### What BigBrotr Does

BigBrotr is a **relay observatory** that maps the Nostr relay ecosystem. It operates three pillars:

| Pillar | Description | Output |
|--------|-------------|--------|
| **Discovery** | Finds relay URLs from seed lists, API sources (nostr.watch), and Nostr events (kinds 2, 3, 10002). Validates candidates via WebSocket protocol handshake. | Validated relay registry |
| **Health Monitoring** | Runs 7 health check types per relay: NIP-11 info, round-trip time, SSL certificates, DNS records, geolocation, ASN/network info, HTTP headers. Publishes findings as NIP-66 events. | Content-addressed metadata archive + signed Nostr events |
| **Event Archiving** | Collects and stores Nostr events from all validated relays with binary-split windowed pagination for completeness guarantees. | Time-series event database with relay attribution |

Additionally, BigBrotr maintains 6 summary tables and 6 materialized views for analytics from accumulated data and exposes everything through a FastAPI REST API and a NIP-90 Data Vending Machine.

### What BigBrotr Publishes

BigBrotr is also a **NIP-66 relay monitor**. It publishes its findings back to the Nostr network as signed events:

- **Kind 10166** (Monitor Announcement): Declares itself as a relay monitor with capabilities, check frequencies, and supported networks.
- **Kind 30166** (Relay Discovery): Per-relay health reports with RTT, SSL, geo, net, DNS tags. Addressable replaceable event keyed by relay URL.
- **Kind 0** (Profile): Optional monitor identity profile.

---

## 2. Architecture Overview

### Diamond DAG

The codebase follows a strict **diamond-shaped Directed Acyclic Graph** for imports:

```
                 services          (Business logic and orchestration)
                /   |   \
             core  nips  utils     (Infrastructure, protocol I/O, network primitives)
                \   |   /
                 models            (Pure domain foundations, zero I/O)
```

**Rules**:
- `models` has zero imports from any other BigBrotr package. Uses only stdlib plus two external libraries (`nostr_sdk`, `rfc3986`).
- `core`, `nips`, and `utils` depend only on `models` (and on each other where justified: `protocol.py` imports from `transport.py`).
- `services` may import from all lower layers but never from each other.
- No circular dependencies exist.

### Package Responsibilities

| Package | Responsibility | I/O | LOC |
|---------|---------------|------|-----|
| `models` | Frozen dataclasses (Relay, Event, Metadata, ServiceState) with fail-fast validation and cached DB params | None | ~1,622 |
| `core` | Connection pool with retry, DB facade (Brotr), service base class, structured logging, Prometheus metrics, YAML loading | Database | ~2,746 |
| `nips` | NIP-11 relay info fetch/parse, NIP-66 health checks (6 types), declarative field parsing, event builders | HTTP, DNS, SSL, WebSocket, GeoIP | ~4,311 |
| `utils` | WebSocket transport, DNS resolution, Nostr key management, bounded HTTP reads, event streaming with binary-split windowing | Network | ~1,410 |
| `services` | 9 services + shared queries/mixins/configs/catalog | Orchestration | ~7,774 |

**Total source**: 17,863 lines across the `src/bigbrotr/` package.

### Independent Services, Shared Database

All 9 services are **independent processes** with no direct service-to-service dependencies. They communicate exclusively through the shared PostgreSQL database. Stopping one service does not affect the others.

```
                    ┌───────────────────────────────────────────────┐
                    │              PostgreSQL Database               │
                    │                                               │
                    │  relay ─── event_relay ─── event              │
                    │  metadata ─── relay_metadata                  │
                    │  service_state   6 summary tables + 6 matviews│
                    └──┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬───┘
                       │      │      │      │      │      │      │      │
                       ▼      ▼      ▼      ▼      ▼      ▼      ▼      ▼
                    Seeder Finder Valid. Monitor Sync. Refresh. Api    Dvm
                       │      │      │      │      │      │      │      │
                       ▼      ▼      ▼      ▼      ▼      │      ▼      ▼
                    seed   HTTP   Relays Relays  Relays (no I/O) HTTP  Nostr
                    file   APIs   (WS)  (NIP-11, (fetch         clients
                                         NIP-66)  events)          │
                                           │                       ▼
                                           ▼                  Nostr Network
                                      Nostr Network           (kind 5050/
                                    (kind 10166/30166)          6050)
```

### Service-Database Interaction Map

```
                 relay   event  event_  meta-  relay_    service_  summary tables
                                relay   data   metadata  state     + matviews
─────────────┬────────┬──────┬───────┬──────┬─────────┬─────────┬────────────
Seeder       │  W(1)  │      │       │      │         │    W    │
Finder       │   R    │      │   R   │      │         │   R/W   │
Validator    │   W    │      │       │      │         │   R/W   │
Monitor      │   R    │      │       │  W   │    W    │   R/W   │
Synchronizer │   R    │  W   │   W   │      │         │   R/W   │
Refresher    │        │      │       │      │         │         │     W
Api          │   R    │  R   │   R   │  R   │    R    │         │     R
Dvm          │   R    │  R   │   R   │  R   │    R    │         │     R
─────────────┴────────┴──────┴───────┴──────┴─────────┴─────────┴────────────

R = reads    W = writes    (1) = only when to_validate=False
```

---

## 3. Domain Model

All domain models are **frozen, immutable dataclasses** with `slots=True` for memory efficiency. Validation is fail-fast in `__post_init__` — invalid instances never escape constructors. Every model caches a `_db_params` NamedTuple in `__post_init__` via `object.__setattr__` (frozen workaround), returned by `to_db_params()`.

### Validation Infrastructure (`_validation.py`)

Shared private module consumed by every model's `__post_init__`:

| Function | Purpose |
|----------|---------|
| `validate_instance(value, expected, name)` | Type check with article-aware error messages |
| `validate_timestamp(value, name)` | Non-negative `int` (explicitly excludes `bool`) |
| `validate_str_no_null(value, name)` | `str` without `\x00` bytes |
| `validate_str_not_empty(value, name)` | Non-empty `str` without `\x00` bytes |
| `validate_mapping(value, name)` | Ensures value is a `Mapping` |
| `sanitize_data(obj, name, max_depth=50)` | Recursive JSON sanitization: removes `None`, empty containers, sorts keys, rejects null bytes, replaces non-serializable types |
| `deep_freeze(obj)` | Recursively wraps dicts with `MappingProxyType`, lists to tuples |

### Relay

A validated WebSocket endpoint on the Nostr network.

| Field | Type | Init | Description |
|-------|------|------|-------------|
| `raw_url` | `str` | Yes | User-provided input (not in repr/compare) |
| `discovered_at` | `int` | Yes | Unix timestamp, defaults to `int(time())` |
| `url` | `str` | No | Computed: normalized URL with scheme |
| `network` | `NetworkType` | No | Computed: detected from hostname/IP |
| `scheme` | `str` | No | Computed: `"wss"` (clearnet) or `"ws"` (overlays) |
| `host` | `str` | No | Computed: hostname (IPv6 brackets stripped) |
| `port` | `int \| None` | No | Computed: explicit port only, `None` for defaults |
| `path` | `str \| None` | No | Computed: URL path component |

**Validation rules**:
1. URL must be valid RFC 3986 with `ws://` or `wss://` scheme (parsed via `rfc3986` library).
2. Query strings and fragments are rejected.
3. Host classified via TLD (`.onion` → TOR, `.i2p` → I2P, `.loki` → LOKI) or IP range.
4. 28 IANA private/reserved IP ranges rejected (16 IPv4 + 12 IPv6: loopback, link-local, private, multicast, documentation, benchmarking, 6to4, Teredo, ULA, etc.).
5. Clearnet relays enforced to `wss://` (TLS required); overlay networks use `ws://`.
6. Default ports (80 for ws, 443 for wss) omitted from final URL.

**`RelayDbParams`**: `(url, network, discovered_at)`.

### Event

Immutable wrapper around `nostr_sdk.Event` with transparent SDK delegation.

| Field | Type | Init | Description |
|-------|------|------|-------------|
| `_nostr_event` | `nostr_sdk.Event` | Yes | The wrapped SDK event |

- `__getattr__()` delegates all attribute access to `_nostr_event` — enables `event.id()`, `event.kind()`, `event.content()`, etc. without explicit wrappers.
- Validates no null bytes in content or tag values (PostgreSQL TEXT incompatibility).
- `_compute_db_params()` converts hex IDs/pubkey/sig to `bytes`, JSON-encodes tags.

**`EventDbParams`**: `(id: bytes, pubkey: bytes, created_at, kind, tags: str, content, sig: bytes)`.

### EventRelay

Junction model linking Event to the Relay where it was observed.

| Field | Type | Description |
|-------|------|-------------|
| `event` | `Event` | The Nostr event |
| `relay` | `Relay` | The relay where it was seen |
| `seen_at` | `int` | Unix timestamp of observation |

Flattens `EventDbParams` + `RelayDbParams` + `seen_at` into a single `EventRelayDbParams` NamedTuple (11 fields) for the `event_relay_insert_cascade` stored procedure — enabling atomic multi-table insert (relay + event + junction) in a single SQL call.

### Metadata

Content-addressed metadata with SHA-256 hashing for deduplication.

| Field | Type | Init | Description |
|-------|------|------|-------------|
| `type` | `MetadataType` | Yes | One of 7 types |
| `data` | `Mapping[str, Any]` | Yes | JSON-compatible dict, sanitized and deep-frozen |

**7 MetadataType values**:

| Type | Value | Source |
|------|-------|--------|
| `NIP11_INFO` | `"nip11_info"` | NIP-11 relay info document |
| `NIP66_RTT` | `"nip66_rtt"` | Round-trip time measurements |
| `NIP66_SSL` | `"nip66_ssl"` | SSL/TLS certificate info |
| `NIP66_GEO` | `"nip66_geo"` | Geolocation data |
| `NIP66_NET` | `"nip66_net"` | Network/ASN info |
| `NIP66_DNS` | `"nip66_dns"` | DNS resolution data |
| `NIP66_HTTP` | `"nip66_http"` | HTTP header info |

**Content addressing algorithm**:
1. Sanitize input dict (remove `None`, empty containers, sort keys, validate strings).
2. Serialize to canonical JSON: `json.dumps(sanitized, sort_keys=True, ensure_ascii=False, separators=(",", ":"))`.
3. Hash with SHA-256: `hashlib.sha256(canonical.encode("utf-8")).digest()`.

Hash is computed from `data` only (not `type`). Composite PK in database: `(id, type)`. This enables deduplication within each metadata type independently.

**Computed/cached**: `_canonical_json` (deterministic JSON string), `_content_hash` (SHA-256 bytes, 32 bytes). Read-only properties expose both.

**`MetadataDbParams`**: `(id: bytes, type: MetadataType, data: str)`.

### RelayMetadata

Junction model linking Relay to Metadata (time-series snapshot).

| Field | Type | Description |
|-------|------|-------------|
| `relay` | `Relay` | The relay |
| `metadata` | `Metadata` | The metadata record |
| `generated_at` | `int` | Unix timestamp of collection |

Flattens into `RelayMetadataDbParams` (7 fields) for `relay_metadata_insert_cascade`. The metadata type is stored as `type` on the `metadata` table and as `metadata_type` on the `relay_metadata` table (compound FK), enabling type-filtered queries without joining metadata.

### ServiceState

Generic key-value persistence for operational state between service restarts.

| Field | Type | Description |
|-------|------|-------------|
| `service_name` | `ServiceName` | Service identifier (coerced from string) |
| `state_type` | `ServiceStateType` | Discriminator (coerced from string) |
| `state_key` | `str` | Application-defined key (e.g., relay URL) |
| `state_value` | `Mapping[str, Any]` | Deep-frozen JSON dict (sanitized) |

**`ServiceStateType`** — `StrEnum` with 2 members:

| Type | Purpose |
|------|---------|
| `CHECKPOINT` | Timestamp marker recording when an action was last performed (API fetch, relay check, candidate validation attempt, event publication) |
| `CURSOR` | Processing cursor marking the last-processed position in an ordered data source (event timestamp + ID, relay index) |

**Use cases by service**:
- **Seeder**: Inserts CHECKPOINT records for candidates (when `to_validate=True`).
- **Finder**: CHECKPOINT for API source polling timestamps; CURSOR for per-relay event scan position.
- **Validator**: Reads/deletes CHECKPOINT candidates; increments failure counters.
- **Monitor**: CHECKPOINT for per-relay last-monitored timestamp and publication timestamps (profile, announcement).
- **Synchronizer**: CURSOR for per-relay sync position (timestamp + event ID).

**`ServiceStateDbParams`**: `(service_name, state_type, state_key, state_value: str)`.

### Enumerations

| Enum | Type | Members | Purpose |
|------|------|---------|---------|
| `NetworkType` | `StrEnum` | `CLEARNET`, `TOR`, `I2P`, `LOKI`, `LOCAL`, `UNKNOWN` | Relay network classification. LOCAL/UNKNOWN rejected during validation. |
| `ServiceName` | `StrEnum` | `SEEDER`, `FINDER`, `VALIDATOR`, `MONITOR`, `SYNCHRONIZER`, `REFRESHER`, `API`, `DVM` | Service identifiers |
| `EventKind` | `IntEnum` | `SET_METADATA=0`, `RECOMMEND_RELAY=2`, `CONTACTS=3`, `RELAY_LIST=10002`, `NIP66_TEST=22456`, `MONITOR_ANNOUNCEMENT=10166`, `RELAY_DISCOVERY=30166` | Well-known Nostr event kinds |
| `MetadataType` | `StrEnum` | 7 members (see above) | Health check result types |
| `ServiceStateType` | `StrEnum` | `CHECKPOINT`, `CURSOR` | Service state discriminator |

**Constant**: `EVENT_KIND_MAX = 65_535` — maximum valid event kind value.

### External Dependencies (models layer)

Only Python stdlib plus two external libraries:
- `rfc3986` — URL parsing and validation (Relay)
- `nostr_sdk` — Nostr event wrapper (Event)

Plus stdlib: `dataclasses`, `enum`, `hashlib`, `ipaddress`, `json`, `time`, `types.MappingProxyType`, `collections.abc.Mapping`, `math.isfinite`.

---

## 4. Services

### Core Infrastructure

#### Pool (`core/pool.py`, 738 LOC)

Async PostgreSQL connection pool with retry, exponential backoff, JSON codec registration, and health checks.

**Configuration** (all Pydantic `BaseModel`, frozen):

| Config | Key Fields | Defaults |
|--------|-----------|----------|
| `DatabaseConfig` | host, port, database, user, password_env | localhost:5432/bigbrotr, admin, DB_ADMIN_PASSWORD |
| `LimitsConfig` | min_size, max_size, max_queries, max_inactive_connection_lifetime | 1, 5, 50000, 300s |
| `TimeoutsConfig` | acquisition | 10.0s |
| `RetryConfig` | max_attempts, initial_delay, max_delay, exponential_backoff | 3, 1.0s, 10.0s, True |
| `ServerSettingsConfig` | application_name, timezone, statement_timeout | bigbrotr, UTC, 0ms |

**Key behaviors**:
- Thread-safe pool creation via `asyncio.Lock`.
- JSON/JSONB codecs registered per connection via `_init_connection()` callback.
- `connect()` retries on `PostgresError`, `OSError`, `ConnectionError` with exponential or linear backoff.
- Query methods (`fetch`, `fetchrow`, `fetchval`, `execute`) retry only on transient connection errors (`InterfaceError`, `ConnectionDoesNotExistError`), acquiring a fresh connection per retry.
- Query-level errors (`PostgresError`) propagate immediately without retry.
- Context manager support: `async with pool:` for auto-connect/close.

#### Brotr (`core/brotr.py`, 964 LOC)

High-level database facade wrapping all stored procedures. All inserts return count of new records.

**Configuration**:

| Config | Key Fields | Defaults |
|--------|-----------|----------|
| `BatchConfig` | max_size | 1000 |
| `TimeoutsConfig` | query, batch, cleanup, refresh | 60s, 120s, 90s, None (infinite) |

**Methods by category**:

| Category | Methods |
|----------|---------|
| **Lifecycle** | `connect()`, `close()`, context manager, `from_yaml()`, `from_dict()` |
| **Generic queries** | `fetch()`, `fetchrow()`, `fetchval()`, `execute()`, `transaction()` |
| **Relay** | `insert_relay(list[Relay]) → int` |
| **Event** | `insert_event(list[Event]) → int` |
| **Event-Relay** | `insert_event_relay(list[EventRelay], cascade=True) → int` |
| **Metadata** | `insert_metadata(list[Metadata]) → int` |
| **Relay-Metadata** | `insert_relay_metadata(list[RelayMetadata], cascade=True) → int` |
| **Service State** | `upsert_service_state()`, `get_service_state()`, `delete_service_state()` |
| **Cleanup** | `delete_orphan_event() → int`, `delete_orphan_metadata() → int` |
| **Views** | `refresh_materialized_view(view_name) → None` |

**Key internals**:
- `_call_procedure()` validates procedure names against regex `^[a-z_][a-z0-9_]*$` (SQL injection prevention), builds parameterized SQL.
- `_transpose_to_columns()` converts row-oriented NamedTuples to column-oriented arrays for PostgreSQL `UNNEST`.
- `_validate_batch_size()` enforces `config.batch.max_size`.
- Cascade inserts atomically write parent + junction in one stored procedure call.

#### BaseService (`core/base_service.py`, 418 LOC)

Abstract base class for all 9 services. Provides lifecycle management, metrics, and graceful shutdown.

**`BaseServiceConfig`** (Pydantic):
- `interval: float` — 60-604800s, default=300 (5 min). Target seconds between cycle starts.
- `max_consecutive_failures: int` — 0-100, default=5. Stop after N consecutive errors (0=unlimited).
- `metrics: MetricsConfig` — Prometheus configuration.

**`BaseService[ConfigT]`** (ABC, Generic):

| Member | Purpose |
|--------|---------|
| `SERVICE_NAME` (ClassVar) | Service identifier enum |
| `CONFIG_CLASS` (ClassVar) | Pydantic config class for deserialization |
| `_brotr` | Injected Brotr instance |
| `_config` | Typed service configuration |
| `_logger` | Structured logger named after service |
| `_shutdown_event` | asyncio.Event for graceful shutdown |

**Abstract methods**: `run()` (one cycle of business logic), `cleanup()` (pre-cycle cleanup, returns items removed).

**`run_forever()` lifecycle per cycle**:
1. `cleanup()` → log removed count.
2. `run()` → main logic.
3. On success: increment `cycles_success`, record `cycle_duration_seconds`, reset `consecutive_failures` to 0.
4. On exception (except `CancelledError`/`KeyboardInterrupt`/`SystemExit`): increment `consecutive_failures`, `cycles_failed`, `errors_{ExceptionType}`. If threshold reached: break.
5. Compute `remaining = max(0, interval - elapsed)`.
6. `wait(remaining)` → break on shutdown signal.

#### Logger (`core/logger.py`, 249 LOC)

Structured logging with key=value and JSON output modes.

**Output formats**:
- **key=value** (default): `info finder cycle_completed cycle=1 duration=2.5 relays_found=42`
- **JSON** (`json_output=True`): `{"timestamp": "2026-03-09T12:00:00Z", "level": "info", "service": "finder", "message": "cycle_completed", "cycle": 1}`

Values containing spaces, `=`, or `"` are auto-quoted. Long values truncated (configurable `max_value_length`). No `__slots__` — required for `unittest.mock.patch.object()`.

#### Metrics (`core/metrics.py`, 209 LOC)

Prometheus metrics collection and HTTP exposition via aiohttp.

**Module-level singletons** (shared across services):

| Object | Type | Labels | Buckets |
|--------|------|--------|---------|
| `SERVICE_INFO` | Info | — | — |
| `CYCLE_DURATION_SECONDS` | Histogram | `service` | 1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600 |
| `SERVICE_GAUGE` | Gauge | `service`, `name` | — |
| `SERVICE_COUNTER` | Counter | `service`, `name` | — |

Services add custom metrics via `set_gauge(name, value)` and `inc_counter(name, value)`. MetricsServer binds to configurable host:port (default `127.0.0.1:8000`, use `0.0.0.0` in containers).

### Service Details

#### 1. Seeder

**Purpose**: Bootstrap relay URLs from a static seed file.

| Property | Value |
|----------|-------|
| Execution | One-shot (`--once` flag) |
| Input | `static/seed_relays.txt` (one URL per line, comments with `#`) |
| Output | Candidates (CHECKPOINT) or direct relay inserts |
| Config | `SeedConfig.to_validate: bool = True` controls output mode |

**Process**:
1. Parse seed file via `asyncio.to_thread(parse_seed_file(path))`.
2. Validate each URL via `Relay()` constructor (fail-open: invalid URLs silently skipped).
3. If `to_validate=True` (default): insert as CHECKPOINT records for Validator.
4. If `to_validate=False`: insert directly to relay table.

#### 2. Finder

**Purpose**: Discover new relay URLs from two sources: external APIs and stored Nostr events.

| Property | Value |
|----------|-------|
| Execution | Continuous (default 5-min interval) |
| Input | nostr.watch APIs, database events (kinds 2, 3, 10002) |
| Output | Candidates (CHECKPOINT) |
| Mixins | `ConcurrentStreamMixin` |

**API Discovery** (`find_from_api`):
1. Load per-source CHECKPOINT timestamps (cooldown-gated, default 24h).
2. For each source: HTTP GET → bounded JSON → JMESPath extraction → `Relay()` validation.
3. Deduplicate across sources. Apply `request_delay` between calls.
4. Save timestamps, insert candidates (filtering out known relays).

**Event Scanning** (`find_from_events`):
1. LEFT JOIN relay with service_state to build per-relay CURSOR records.
2. For each relay (concurrent, `parallel_relays` semaphore, default 50):
   - Cursor-paginated query: `(seen_at, event_id)` tie-breaking.
   - Extract relay URLs from tag values.
   - Insert discovered URLs as candidates.
3. Time limits: per-relay (`max_relay_time`) and overall (`max_duration`, default 24h).
4. Stream results via `_iter_concurrent()`.

**Cleanup**: delete stale cursors (relays deleted) + delete stale API checkpoints (sources removed from config).

#### 3. Validator

**Purpose**: Validate candidate URLs by attempting Nostr WebSocket protocol handshake.

| Property | Value |
|----------|-------|
| Execution | Continuous (default 5-min interval) |
| Input | CHECKPOINT candidates from `service_state` |
| Output | Promoted relays in `relay` table |
| Mixins | `ConcurrentStreamMixin`, `NetworkSemaphoresMixin` |
| Concurrency | Per-network semaphores: clearnet 50, Tor 10, I2P 5, Loki 5 |

**Process**:
1. Fetch candidate chunk (prioritized: fewest failures, then oldest timestamp). Retry cooldown: `processing.interval` (default 3600s = 1h).
2. For each candidate (concurrent, network-semaphore-bounded):
   - `is_nostr_relay()` WebSocket check: connect, send REQ for kind 1 with limit 1.
   - **Success criteria**: EOSE response, AUTH challenge (NIP-42), or `auth-required` CLOSED.
3. **Valid relays**: atomic promote (insert relay + delete CHECKPOINT in transaction).
4. **Invalid candidates**: increment failure counter, update timestamp for retry.
5. Paginate until all candidates processed or `max_candidates` budget exhausted.

**SSL fallback**: clearnet relays try verified SSL first. If SSL fails and `allow_insecure=True`, retry with `CERT_NONE`.

**Cleanup**: always delete promoted candidates (safety net); optionally delete exhausted candidates exceeding `max_failures` (default 720 = ~30 days at hourly checks).

#### 4. Monitor

**Purpose**: Run comprehensive health checks on validated relays and publish results as NIP-66 events.

| Property | Value |
|----------|-------|
| Execution | Continuous (default 5-min interval) |
| Input | Relays from `relay` table (due for check based on CHECKPOINT interval) |
| Output | Metadata records, Kind 10166/30166/0 Nostr events |
| Mixins | `ConcurrentStreamMixin`, `NetworkSemaphoresMixin`, `GeoReaderMixin`, `ClientsMixin` |
| Concurrency | Per-network semaphores + per-check retry with exponential backoff and jitter |

**Health checks** (7 types, all individually configurable for compute, store, and retry):

| Check | Networks | Method | Output |
|-------|----------|--------|--------|
| NIP-11 Info | All | HTTP GET to relay info URL | name, description, supported NIPs, software, version, fees, limitations, retention, localization |
| NIP-66 RTT | All | 3-phase WebSocket (open + read + write) | Round-trip times in milliseconds |
| NIP-66 SSL | Clearnet only | Two-context extraction + validation | Subject, issuer, expiry, SANs, fingerprint, protocol, cipher |
| NIP-66 DNS | Clearnet only | A/AAAA/CNAME/NS/PTR resolution | IPs, nameservers, CNAME, reverse DNS, TTL |
| NIP-66 Geo | Clearnet only | GeoLite2 City database lookup | Country, city, coordinates, geohash, timezone, continent |
| NIP-66 Net | Clearnet only | GeoLite2 ASN database lookup | IP, ASN, organization, network ranges |
| NIP-66 HTTP | All | WebSocket handshake header capture | Server, X-Powered-By headers |

**Process per cycle**:
1. `update_geo_databases()` — download/refresh GeoLite2 databases if stale (configurable max age, default 30 days).
2. `publish_profile()` — Kind 0 if interval elapsed (default 24h).
3. `publish_announcement()` — Kind 10166 if interval elapsed (default 24h).
4. `monitor()` — main loop:
   - Count relays due, iterate in chunks.
   - For each relay: NIP-11 fetch (first, sequential), then NIP-66 checks (RTT sequential, SSL/DNS/Geo/Net/HTTP parallel via `asyncio.gather()`).
   - Each check wrapped in `retry_fetch()` (exponential backoff + jitter, configurable per-check).
   - Store metadata, publish Kind 30166 per relay, update CHECKPOINT.

**GeoIP management**: auto-downloads GeoLite2 City and ASN databases if missing or stale. Configurable max age, download URLs, size limits.

#### 5. Synchronizer

**Purpose**: Collect Nostr events from all validated relays and store them with completeness guarantees.

| Property | Value |
|----------|-------|
| Execution | Continuous (default 5-min interval) |
| Input | All relays from `relay` table |
| Output | Events in `event` + `event_relay` tables |
| Mixins | `ConcurrentStreamMixin`, `NetworkSemaphoresMixin` |
| Concurrency | Per-network semaphores, shuffled relay order |

**Process per cycle**:
1. Delete stale cursors (relays no longer in database).
2. Fetch all relays, filter by enabled networks.
3. `random.shuffle(relays)` — prevent thundering herd.
4. For each relay (concurrent, network-semaphore-bounded, per-relay timeout):
   - Compute sync window: `[cursor + 1, now - end_lag]`.
   - Connect via `connect_relay()` (NIP-42 auth support, SSL fallback).
   - Stream events via `stream_events()` with binary-split windowing.
   - Validate 4 guarantees: filtered (matches filter), verified (signature), deduplicated (unique EventId), limited.
   - Insert valid events via `event_relay_insert_cascade` (atomic multi-table).
   - Update per-relay CURSOR (timestamp + event ID, batched writes).
5. Final cursor flush.

**Binary-split windowing algorithm** (`utils/streaming.py`):
- Stack-based window management: `until_stack` with boundaries.
- For each window: fetch events, attempt completeness verification.
- `_try_verify_completeness()`: data-driven check — re-fetches boundary window, verifies all events captured.
- On verification failure: binary-split at midpoint, push onto stack. Guarantees no events missed.
- Single-second windows yield directly (indivisible).
- Events yielded in ascending `(created_at, id)` order.

**Cursor persistence**: `SyncCursor(key, timestamp, id)` with sentinel ID (`b"\xff" * 32`) for completed windows. Batched writes (default every 50 relays).

**Feedback loop**: events collected by Synchronizer are later scanned by Finder to discover new relay URLs from tag values.

#### 6. Refresher

**Purpose**: Periodically refresh materialized views in dependency order.

| Property | Value |
|----------|-------|
| Execution | Continuous (default 60-min interval) |
| Input | Configured summary tables (6) and materialized views (6) |
| Output | Fresh summary table and materialized view data |

**Refresh order** (dependency levels):
1. Summary tables refreshed incrementally via range-based refresh functions: `pubkey_kind_stats`, `pubkey_relay_stats`, `relay_kind_stats`, `pubkey_stats`, `kind_stats`, `relay_stats`
2. `relay_metadata_latest` (base dependency for level 3)
3. `relay_software_counts`, `supported_nip_counts`, `daily_counts`, `events_replaceable_latest`, `events_addressable_latest` (bounded, full refresh)
4. Periodic functions: `rolling_windows_refresh()`, `relay_stats_metadata_refresh()`

Individual view failures do not block subsequent views (error isolation). Serial execution (CONCURRENTLY handles read isolation). No timeout (`refresh=None`). View names regex-validated (SQL injection prevention).

#### 7. Api

**Purpose**: Provide read-only HTTP access to all tables, views, and materialized views.

| Property | Value |
|----------|-------|
| Execution | Continuous (HTTP server via uvicorn) |
| Framework | FastAPI |
| Mixins | `CatalogAccessMixin` |

**Lifecycle**:
- `__aenter__`: discover schema via Catalog → `_build_app()` → spawn uvicorn as background Task.
- `run()`: log cycle stats, update Prometheus counters, detect server crashes.
- `__aexit__`: cancel server task.

**Auto-generated endpoints**:
- `/health` — `{"status": "ok"}`
- `{prefix}/schema` — list enabled tables
- `{prefix}/schema/{table}` — table detail (columns, types, PK)
- `{prefix}/{table}` — list with filter/sort/pagination
- `{prefix}/{table}/{pk}` — single row by primary key

**Query params**: `limit`, `offset`, `sort=col[:asc|desc]`, column filters (`col=value` or `col=op:value`). Operators: `=`, `>`, `<`, `>=`, `<=`, `ILIKE`. Max offset: 100,000.

**Safety**: whitelist-by-construction column/table validation via Catalog, type-safe casting, CatalogError → 400 (client-safe messages, no DB internals leaked), `asyncio.wait_for(request_timeout)` → 504.

#### 8. Dvm

**Purpose**: NIP-90 Data Vending Machine service for on-demand data queries via Nostr.

| Property | Value |
|----------|-------|
| Execution | Continuous (WebSocket listener) |
| Input | Kind 5050 job request events from Nostr relays |
| Output | Kind 6050 result events published to Nostr relays |
| Mixins | `CatalogAccessMixin` |

**Lifecycle**:
- `__aenter__`: discover schema → create Nostr client → connect to relays → publish NIP-89 handler announcement (Kind 31990).
- `run()`: fetch job requests since `_last_fetch_ts`, process, publish results.
- `__aexit__`: disconnect client.

**Job handling**:
1. Validate table exists and enabled.
2. Check pricing: if `price > 0` and `bid < price` → Kind 7000 payment-required error.
3. Parse params: `table`, `limit`, `offset`, `filter`, `sort`.
4. Execute `catalog.query()` with filters/sort.
5. Publish Kind 6050 (request kind + 1000) with query results.
6. Dedup via in-memory set (capped 10,000 entries).

### Shared Service Infrastructure (`services/common/`)

#### Configs

**Network configs** (per-network concurrency and proxy settings):
- `ClearnetConfig`: `enabled=True`, `max_tasks=50`, `timeout=10.0s`, `proxy_url=None`
- `TorConfig`: `enabled=False`, `proxy_url='socks5://tor:9050'`, `max_tasks=10`, `timeout=30.0s`
- `I2pConfig`: `enabled=False`, `proxy_url='socks5://i2p:4447'`, `max_tasks=5`, `timeout=45.0s`
- `LokiConfig`: `enabled=False`, `proxy_url='socks5://lokinet:1080'`, `max_tasks=5`, `timeout=30.0s`

**`NetworksConfig`**: unified container with `get(network)`, `get_proxy_url(network)`, `is_enabled(network)`, `get_enabled_networks()`.

**`TableConfig`**: `enabled: bool = False`, `price: int = 0` (millisats). Used by Api and Dvm for per-table access control and pricing.

#### Types

Frozen dataclass hierarchy for typed service state persistence:

**Checkpoints**: `Checkpoint(key, timestamp)` with subclasses `ApiCheckpoint`, `MonitorCheckpoint`, `PublishCheckpoint`, `CandidateCheckpoint(+network, failures)`.

**Cursors**: `Cursor(key, timestamp|None, id|None)` with subclasses `SyncCursor`, `FinderCursor`. Validation: both `timestamp` and `id` must be None or both set.

#### Mixins (5 cooperative inheritance mixins)

| Mixin | Provides | Used By |
|-------|----------|---------|
| `NetworkSemaphoresMixin` | Per-network `asyncio.Semaphore` from NetworksConfig | Validator, Monitor, Synchronizer |
| `ConcurrentStreamMixin` | `_iter_concurrent(items, worker)` — TaskGroup with Queue streaming | Finder, Monitor, Synchronizer, Validator |
| `GeoReaderMixin` | GeoLite2 City + ASN database reader lifecycle | Monitor |
| `ClientsMixin` | Managed Nostr client pool (`get(relay)`, `get_many(relays)`, `disconnect()`) | Monitor |
| `CatalogAccessMixin` | Schema introspection via Catalog on `__aenter__` | Api, Dvm |

#### Catalog (`catalog.py`)

Schema introspection and safe query builder.

- **Discovery**: 4 SQL queries (tables/views, matviews, columns, PKs).
- **`query()`**: safe paginated queries with whitelist-by-construction validation, typed operators, type casting.
- **`get_by_pk()`**: single row by composite primary key.
- **`CatalogError`**: client-safe exception with `client_message` field — prevents leaking database internals.

---

## 5. NIP Protocol Implementations

### Design Principles

All NIP fetch methods follow a **never-raise contract**. Only `CancelledError`, `KeyboardInterrupt`, and `SystemExit` propagate. All transport errors are captured in structured log objects:

```python
logs.success = False
logs.reason = "descriptive error message"
```

Data models use **declarative field parsing** via `FieldSpec` — a frozen dataclass declaring expected types per field name across 6 frozenset categories (`int_fields`, `bool_fields`, `str_fields`, `float_fields`, `str_list_fields`, `int_list_fields`). The `parse_fields()` function applies specs to raw dicts, silently dropping invalid values from untrusted relay responses.

All NIP data models extend `BaseData` (Pydantic frozen model with `_FIELD_SPEC`), logs extend `BaseLogs` (semantic validation: success=True requires reason=None and vice versa), and metadata pairs extend `BaseNipMetadata` (data + logs).

### NIP-11: Relay Information Document

Fetches the relay's self-declared information via HTTP GET to the relay's info URL (WebSocket URL converted to HTTPS).

**Data model** (`Nip11InfoData`) — complete relay info with nested sub-objects:
- **Identity**: name, description, banner, icon, pubkey, contact, software, version
- **Capabilities**: supported_nips (auto-sorted, deduplicated)
- **Policies**: privacy_policy, terms_of_service, posting_policy, payments_url
- **Limitations** (`Nip11InfoDataLimitation`): max_message_length, max_subscriptions, max_limit, max_subid_length, max_event_tags, max_content_length, min_pow_difficulty, auth_required, payment_required, restricted_writes, created_at_lower_limit, created_at_upper_limit, default_limit
- **Fees** (`Nip11InfoDataFees`): admission, subscription, publication (each list of `Nip11InfoDataFeeEntry` with amount, unit, period, kinds)
- **Retention**: list of `Nip11InfoDataRetentionEntry` with kinds (int or [int,int] range pairs), time, count
- **Localization**: relay_countries, language_tags, tags

**Fetch behavior**:
- Request header: `Accept: application/nostr+json` (per NIP-11 spec).
- Content-Type validated: must be `application/nostr+json` or `application/json`.
- Max response size: 64 KB (configurable).
- **SSL fallback**: clearnet tries verified HTTPS first, falls back to `CERT_NONE` if `allow_insecure=True`. Overlay networks always use SOCKS5 proxy with no SSL verification.
- Supports reusable aiohttp session (caller retains ownership).

### NIP-66: Relay Monitoring and Discovery

Six independent health checks, all run concurrently via `asyncio.gather(return_exceptions=True)`.

#### RTT (Round-Trip Time)

Three sequential phases with cascading failure:

1. **Open**: WebSocket connection establishment time (ms) via `connect_relay()`.
2. **Read**: Time to first event arrival after REQ subscription (ms).
3. **Write**: Time to publish event (Kind 22456, ephemeral) + verify retrieval (ms).

**Multi-phase log model** (`Nip66RttMultiPhaseLogs`): independent `success`/`reason` per phase. Cascading failure validation: if open fails, read and write must also fail. Timing via `time.perf_counter()`, converted to integer milliseconds.

Overlay networks without proxy → immediate cascading failure (all phases).

#### SSL Certificate

Two-context strategy (both synchronous, delegated via `asyncio.to_thread()`):

1. **Extract** with `CERT_NONE` — reads certificate data regardless of chain validity.
2. **Validate** with default SSL context — verifies chain against system trust store.

**Extracted fields**: subject CN, issuer (org + CN), validity dates (not_before, expires), SANs, serial, version, fingerprint (SHA-256, colon-separated hex), TLS protocol, cipher suite name, cipher bits.

**Clearnet only**: overlay networks rejected.

#### DNS Resolution

Comprehensive queries with per-record-type error isolation:

| Record | Resolver | Notes |
|--------|----------|-------|
| A (IPv4) | `dnspython` | Direct hostname |
| AAAA (IPv6) | `dnspython` | Direct hostname |
| CNAME | `dnspython` | Single target |
| NS | `dnspython` | Against registered domain (via `tldextract`) |
| PTR | `dnspython` | Reverse DNS on first IPv4 |

Each record type wrapped in `contextlib.suppress()`. TTL captured from first A record.

**Clearnet only**.

#### Geolocation

GeoLite2 City database lookup with geohash encoding:

1. Resolve hostname → IP via `resolve_host()` (prefers IPv4, falls back to IPv6).
2. GeoIP City lookup (thread pool).
3. Geohash encoding at precision 9 (~5m accuracy) via `geohash2`.

**Extracted**: country (physical preferred over registered), city, coordinates, geohash, timezone, continent, EU membership, postal code, accuracy radius, geoname ID.

**Clearnet only**.

#### Network/ASN

GeoLite2 ASN database lookup:

1. Resolve IPv4 and IPv6 via `resolve_host()`.
2. ASN lookup for each IP (thread pool).

**Priority**: IPv4 ASN/org takes precedence; IPv6 used as fallback. IPv6-specific CIDR always recorded in `net_network_v6`.

**Clearnet only**.

#### HTTP Headers

Captures `Server` and `X-Powered-By` headers from WebSocket upgrade handshake via aiohttp `TraceConfig` hooks (`on_request_end`). Not a separate HTTP request.

**All networks**: overlay via SOCKS5 proxy.

### Event Builders

Standalone functions for constructing Nostr events from typed NIP data:

| Function | Kind | Purpose |
|----------|------|---------|
| `build_profile_event()` | 0 | Profile metadata (name, about, picture, nip05, website, banner, lud16) |
| `build_monitor_announcement()` | 10166 | Enabled checks, networks (`n` tags), timeouts, capabilities (`c` tags) |
| `build_relay_discovery()` | 30166 | Relay health tags aggregated from all tests |

**Tag builders** for Kind 30166:
- RTT: `rtt-open`, `rtt-read`, `rtt-write` (ms)
- SSL: `ssl` (valid/!valid), `ssl-expires`, `ssl-issuer`
- Net: `net-ip`, `net-ipv6`, `net-asn`, `net-asn-org`
- Geo: `g` (geohash), `geo-country`, `geo-city`, `geo-lat`, `geo-lon`, `geo-tz`
- Language: ISO 639-1 codes from NIP-11's `language_tags`
- Requirements (`R` tags): auth, payment, writes, pow
- Type (`T` tags): Search, Community, Blob, Paid, PrivateStorage, PrivateInbox, PublicOutbox, PublicInbox

**Ground truth hierarchy for requirement tags**: RTT write probe result > RTT read probe result > NIP-11 self-report. If write succeeds → relay is fully open (auth=False, payment=False).

### Network Awareness Matrix

| Test | Clearnet | Overlay (with proxy) | Overlay (no proxy) |
|------|----------|---------------------|-------------------|
| NIP-11 Info | HTTPS (verified, insecure fallback) | HTTP via proxy | HTTP via proxy |
| RTT | WebSocket | WebSocket via proxy | Immediate failure |
| SSL | Two-context extraction + validation | Rejected (N/A) | Rejected (N/A) |
| Geo | GeoIP lookup on resolved IP | Rejected | Rejected |
| Net | ASN lookup on resolved IPs | Rejected | Rejected |
| DNS | Full resolution (A/AAAA/CNAME/NS/PTR) | Rejected | Rejected |
| HTTP | WebSocket upgrade headers | Via proxy (insecure SSL) | Immediate failure |

---

## 6. Utilities

### DNS (`utils/dns.py`, 99 LOC)

Async hostname resolution with independent A/AAAA lookups.

`resolve_host(host, timeout=5.0) → ResolvedHost(ipv4, ipv6)`. Each lookup in separate thread via `asyncio.to_thread()`. Failure suppressed — returns `ResolvedHost(None, None)` (never raises).

### HTTP (`utils/http.py`, 116 LOC)

Bounded HTTP reads preventing memory exhaustion:

- `read_bounded_json(response, max_size) → Any` — size check before JSON parse.
- `download_bounded_file(url, dest, max_size, timeout=60.0)` — size check before disk write. Creates parent directories.
- Correctly handles chunked transfer-encoding with loop-based reading.

### Keys (`utils/keys.py`, 137 LOC)

Nostr cryptographic key management:

- `load_keys_from_env(env_var) → Keys` — parses nsec1 (bech32) or 64-char hex private key from environment.
- `KeysConfig` (Pydantic) — eager validation at config load time via `@model_validator`. `__repr__`/`__str__` redact private key, show only pubkey hex.

### Parsing (`utils/parsing.py`, 56 LOC)

- `safe_parse(items, factory) → list` — tolerant sequence parsing. Catches `ValueError`/`TypeError`/`KeyError`, logs at WARNING, returns only successful results.

### Protocol (`utils/protocol.py`, 443 LOC)

High-level Nostr client operations with SSL fallback strategy:

- **`create_client(keys, proxy_url, allow_insecure)`**: configures nostr-sdk Client with optional SOCKS5 proxy and InsecureWebSocketTransport.
- **`connect_relay(relay, keys, proxy_url, timeout, allow_insecure)`**: connects to relay with automatic SSL fallback for clearnet. Overlay networks require proxy (ValueError if missing). Clearnet: try verified first → on SSL error + allow_insecure → retry with InsecureWebSocketTransport.
- **`broadcast_events(builders, clients)`**: sign and broadcast events to pre-connected clients. Returns count of successful clients.
- **`is_nostr_relay(relay, proxy_url, timeout, overall_timeout, allow_insecure)`**: validates relay via protocol handshake. Success: EOSE, AUTH, or `auth-required` CLOSED. Cleanup: always disconnects in finally block.

**SSL error detection**: 15 multi-word patterns matched case-insensitively (ssl certificate, certificate verify, self signed, tls handshake failed, etc.).

**Stderr suppression**: reference-counted `_StderrSuppressor` redirects stderr during nostr-sdk operations to suppress UniFFI tracebacks. Ref-counting avoids deadlock across `await` boundaries.

### Transport (`utils/transport.py`, 291 LOC)

WebSocket transport primitives with SSL bypass for nostr-sdk Rust FFI:

- **`InsecureWebSocketTransport`**: implements `nostr_sdk.CustomWebSocketTransport`. Creates SSL context with `check_hostname=False`, `verify_mode=CERT_NONE`. Returns `WebSocketAdapterWrapper(InsecureWebSocketAdapter(...))`.
- **`InsecureWebSocketAdapter`**: implements `nostr_sdk.WebSocketAdapter`. Handles TEXT/BINARY/PING/PONG messages. 60s receive timeout, 5s close timeout.
- **`_NostrSdkStderrFilter`**: global stderr wrapper installed at module load. Intercepts UniFFI tracebacks (up to 50 lines per burst). Combined with logger-level suppression for complete nostr-sdk silencing.

**Constants**: `DEFAULT_TIMEOUT = 10.0`, `_WS_RECV_TIMEOUT = 60.0`, `_WS_CLOSE_TIMEOUT = 5.0`.

### Streaming (`utils/streaming.py`, 229 LOC)

Event streaming with binary-split windowing for completeness guarantees:

- **`stream_events(client, filters, start, end, limit, timeout) → AsyncIterator[Event]`**: core windowing orchestrator. Stack-based window management. Data-driven completeness verification with binary-split fallback.
- **`_fetch_validated(ctx, since, until, limit)`**: single source of truth for event validation — 4 guarantees: Filtered, Verified, Deduplicated, Limited. Uses `client.stream_events()` (not `fetch_events`) to prevent relay flooding.
- **`_try_verify_completeness(ctx, events, since)`**: re-fetches boundary window, probes for events before min timestamp. Returns combined events on success, `None` on inconsistency (triggers binary split).

---

## 7. Database Design

### Schema

6 tables, 6 summary tables, 24 stored functions, 6 materialized views, 27 indexes.

#### Tables

```
relay                    (url TEXT PK, network TEXT, discovered_at BIGINT)
    │
    ├── event_relay      (event_id BYTEA FK, relay_url TEXT FK, seen_at BIGINT)
    │       │                                                   PK(event_id, relay_url)
    │       └── event    (id BYTEA PK, pubkey BYTEA, created_at BIGINT, kind INT,
    │                     tags JSONB, tagvalues TEXT[] NOT NULL, content TEXT, sig BYTEA)
    │
    ├── relay_metadata   (relay_url TEXT FK, metadata_id BYTEA FK, metadata_type TEXT FK,
    │       │             generated_at BIGINT)
    │       │             PK(relay_url, generated_at, metadata_type)
    │       │             compound FK (metadata_id, metadata_type) → metadata(id, type)
    │       │
    │       └── metadata (id BYTEA, type TEXT, data JSONB)
    │                     PK(id, type)
    │
    └── service_state    (service_name TEXT, state_type TEXT, state_key TEXT, state_value JSONB)
                          PK(service_name, state_type, state_key)
```

#### Key Design Decisions

- **Computed column**: `event.tagvalues` is a `TEXT[] NOT NULL` column computed at insert time by `event_insert()` via `tags_to_tagvalues(tags)`. Extracts key-prefixed values from single-character tag keys (e.g., `ARRAY['e:abc123', 'p:def456']`). Indexed with GIN for efficient containment queries that discriminate between tag types.
- **Content addressing**: Metadata uses SHA-256 hash + type as composite PK. Hash computed in Python for deterministic cross-platform behavior.
- **Cascade functions**: `event_relay_insert_cascade` and `relay_metadata_insert_cascade` atomically insert across 3 tables in a single stored procedure call.
- **Bulk array parameters**: All insert functions accept parallel arrays and use `UNNEST` for single-roundtrip bulk inserts.
- **No CHECK constraints**: Validation enforced in Python enum layer.
- **All functions SECURITY INVOKER**: PostgreSQL default, ensuring functions run with caller's permissions.

#### Stored Functions (24)

| Category | Functions |
|----------|-----------|
| **Utility** (1) | `tags_to_tagvalues(JSONB) → TEXT[]` |
| **CRUD** (8) | `relay_insert`, `event_insert`, `metadata_insert`, `event_relay_insert`, `relay_metadata_insert`, `service_state_upsert`, `service_state_get`, `service_state_delete` |
| **Cascade** (2) | `event_relay_insert_cascade` (relay+event+junction), `relay_metadata_insert_cascade` (relay+metadata+junction) |
| **Cleanup** (2) | `orphan_event_delete(batch_size=10000)`, `orphan_metadata_delete(batch_size=10000)` |
| **Summary refresh** (8) | `pubkey_kind_stats_refresh`, `pubkey_relay_stats_refresh`, `relay_kind_stats_refresh`, `pubkey_stats_refresh`, `kind_stats_refresh`, `relay_stats_refresh`, `rolling_windows_refresh`, `relay_stats_metadata_refresh` |
| **Matview refresh** (6) | `relay_metadata_latest_refresh`, `relay_software_counts_refresh`, `supported_nip_counts_refresh`, `daily_counts_refresh`, `events_replaceable_latest_refresh`, `events_addressable_latest_refresh` |

#### Summary Tables (6)

| Table | Granularity | Key Metrics |
|-------|-------------|-------------|
| `pubkey_kind_stats` | Per author + kind | Event count per author per kind |
| `pubkey_relay_stats` | Per author + relay | Per-relay author activity |
| `relay_kind_stats` | Per relay + kind | Per-relay kind distribution |
| `pubkey_stats` | Per author | Event count, unique kinds, first/last timestamps |
| `kind_stats` | Per event kind | Event count, unique pubkeys, NIP-01 category |
| `relay_stats` | Per relay | Event count, unique pubkeys, avg RTT (last 10), NIP-11 info |

#### Materialized Views (6)

| View | Granularity | Key Metrics |
|------|-------------|-------------|
| `relay_metadata_latest` | Per relay + type | Most recent metadata snapshot (DISTINCT ON) |
| `relay_software_counts` | Per software + version | Relay count by software distribution |
| `supported_nip_counts` | Per NIP number | Relay count supporting each NIP |
| `daily_counts` | Per UTC day | Daily event volume, unique pubkeys/kinds |
| `events_replaceable_latest` | Per author + kind | Latest replaceable event per pubkey+kind |
| `events_addressable_latest` | Per author + kind + d-tag | Latest addressable event per pubkey+kind+identifier |

All views have unique indexes (required for `REFRESH MATERIALIZED VIEW CONCURRENTLY`) and are refreshed by the Refresher service in dependency order.

#### Indexes (27)

**Event table** (7):
- `created_at DESC` — timeline queries
- `kind` — kind filtering
- `(kind, created_at DESC)` — kind + timeline
- `(pubkey, created_at DESC)` — author timeline
- `(pubkey, kind, created_at DESC)` — author + kind + timeline
- `tagvalues` GIN — tag value containment
- `(created_at ASC, id ASC)` — cursor-based pagination

**Event_relay table** (3 + PK):
- `relay_url` — events from relay
- `seen_at DESC` — recent events
- `(relay_url, seen_at DESC)` — latest events per relay

**Relay_metadata table** (3):
- `generated_at DESC` — recent metadata
- `(metadata_id, metadata_type)` — metadata lookup
- `(relay_url, metadata_type, generated_at DESC)` — per-relay type history

**Service_state table** (3 + PK):
- `service_name` — all data for service
- `(service_name, state_type)` — state type within service
- Partial expression index on `state_value->>'network'` WHERE state_type='checkpoint' — candidate filtering by network

**Summary table indexes** (3 secondary):
- Additional secondary indexes on summary tables for common query patterns

**Materialized view indexes** (10):
- 6 unique indexes (one per view, required for CONCURRENTLY)
- 4 secondary indexes (relay_metadata_latest type, relay_stats network, and others)

#### Database Roles (4)

| Role | Used By | Privileges |
|------|---------|-----------|
| `admin` | Docker setup, PGBouncer | SUPERUSER |
| `writer` | seeder, finder, validator, monitor, synchronizer | SELECT, INSERT, UPDATE, DELETE on all tables + EXECUTE on all functions |
| `refresher` | refresher | SELECT on all tables + EXECUTE on all functions + ownership of materialized views |
| `reader` | api, dvm, postgres-exporter | SELECT on all tables + EXECUTE on all functions + `pg_monitor` |

#### SQL Generation System

SQL schema generated from Jinja2 templates via `tools/generate_sql.py`:
- **Templates**: `tools/templates/sql/base/` (10 shared) + `tools/templates/sql/lilbrotr/` (3 overrides)
- **Output**: `deployments/{bigbrotr,lilbrotr}/postgres/init/` (10 files each)
- **Drift detection**: CI runs `generate_sql.py --check` to verify committed SQL matches templates

---

## 8. Infrastructure and Deployment

### Docker Compose Stack

15 containers on 2 bridge networks:

| Container | Image | Purpose |
|-----------|-------|---------|
| PostgreSQL 16 | postgres:16-alpine | Primary database, persistent volume |
| PGBouncer | edoburu/pgbouncer:v1.25.1-p0 | Connection pooler (transaction mode, scram-sha-256) |
| Tor | osminogin/tor-simple:0.4.8.10 | SOCKS5 proxy for .onion relays |
| Seeder | bigbrotr (custom) | One-shot relay bootstrapping |
| Finder | bigbrotr (custom) | Continuous relay discovery |
| Validator | bigbrotr (custom) | WebSocket protocol validation |
| Monitor | bigbrotr (custom) | Health checks + event publishing |
| Synchronizer | bigbrotr (custom) | Event collection |
| Refresher | bigbrotr (custom) | Materialized view refresh |
| Api | bigbrotr (custom) | REST API (read-only) |
| Dvm | bigbrotr (custom) | NIP-90 Data Vending Machine |
| postgres-exporter | prometheuscommunity/postgres-exporter:v0.16.0 | PostgreSQL metrics for Prometheus |
| Prometheus | prom/prometheus:v2.51.0 | Time-series metrics database (30-day retention) |
| Alertmanager | prom/alertmanager:v0.27.0 | Alert routing and grouping |
| Grafana | grafana/grafana:10.4.1 | Dashboards and visualization |

**Networks**:
- `bigbrotr-data-network`: PostgreSQL, PGBouncer, Tor, all services, postgres-exporter
- `bigbrotr-monitoring-network`: Prometheus, Alertmanager, Grafana, all services, postgres-exporter

**Optional containers** (disabled by default): I2P proxy, Lokinet proxy.

### Dockerfile

Multi-stage parametric build via `ARG DEPLOYMENT` (bigbrotr|lilbrotr):

**Builder** (python:3.11-slim): `uv` for dependency installation, gcc + libpq-dev + libsecp256k1-dev for native extensions. Two cache layers: dependencies first, then source.

**Production** (python:3.11-slim): runtime deps only (libpq5, libsecp256k1-dev), tini for PID 1 signal handling, non-root user (uid 1000). Stripped pip/setuptools/ensurepip.

### Port Mapping

| Resource | BigBrotr | LilBrotr |
|----------|----------|----------|
| PostgreSQL | 5432 | 5433 |
| PGBouncer | 6432 | 6433 |
| Tor | 9050 | 9051 |
| API | 8080 | 8081 |
| Prometheus | 9090 | 9091 |
| Alertmanager | 9093 | 9094 |
| Grafana | 3000 | 3001 |
| Service metrics | 8001–8007 | 9001–9007 |

Service containers expose metrics on port 8000 internally; Docker maps to host ports 8001–8007 via environment variable overrides.

### PostgreSQL Tuning

Optimized for ~4 GB RAM, SSD storage, write-heavy workload:

| Setting | Value | Rationale |
|---------|-------|-----------|
| shared_buffers | 1 GB | 25% RAM |
| effective_cache_size | 3 GB | 75% RAM |
| work_mem | 8 MB | Per-operation |
| maintenance_work_mem | 256 MB | VACUUM, CREATE INDEX |
| synchronous_commit | off | Async commits (~10ms data risk, acceptable for Nostr — events can be re-fetched) |
| random_page_cost | 1.1 | SSD-optimized |
| max_parallel_workers | 4 | Query parallelization |
| autovacuum_naptime | 30s | Frequent autovacuum checks |
| idle_in_transaction_session_timeout | 60s | Kill idle transactions |

**Extensions**: `btree_gin` (GIN index support for TEXT[]), `pg_stat_statements` (query execution statistics).

### PGBouncer Configuration

| Setting | Value |
|---------|-------|
| pool_mode | transaction |
| max_client_conn | 200 |
| default_pool_size | 5 |
| reserve_pool_size | 2 |
| query_timeout | 300s |
| query_wait_timeout | 120s |
| auth_type | scram-sha-256 |

Generates `userlist.txt` dynamically from environment variables via `entrypoint.sh`.

### Startup Sequence

1. PostgreSQL starts → executes 10 init SQL files in order (00–99).
2. PGBouncer starts (depends on PostgreSQL healthy).
3. Tor/proxy starts.
4. Seeder runs `--once` (depends on PGBouncer healthy) → seeds initial relays → exits.
5. All continuous services start (depend on PGBouncer healthy).
6. Monitoring stack starts independently.

---

## 9. Observability

### Prometheus Metrics

Each service automatically records:

| Metric | Type | Description |
|--------|------|-------------|
| `service_info` | Info | Static service metadata (set once at startup) |
| `service_counter_total{service, name}` | Counter | Cumulative totals: `cycles_success`, `cycles_failed`, `errors_{ExceptionType}` |
| `service_gauge{service, name}` | Gauge | Point-in-time values: `consecutive_failures`, `last_cycle_timestamp`, custom per-service |
| `cycle_duration_seconds{service}` | Histogram | Cycle latency with buckets: 1s, 5s, 10s, 30s, 60s, 120s, 300s, 600s, 1800s, 3600s |

Services add custom metrics via `set_gauge(name, value)` and `inc_counter(name, value)`.

### Alerting Rules (7)

| Alert | Severity | Condition |
|-------|----------|-----------|
| ServiceDown | Critical | Target unreachable for 5+ minutes |
| HighFailureRate | Warning | >0.1 errors/second over 5 minutes |
| ConsecutiveFailures | Critical | 5+ consecutive cycle failures for 2+ minutes |
| SlowCycles | Warning | p99 cycle duration exceeds 5 minutes |
| DatabaseConnectionsHigh | Warning | >80 active PostgreSQL connections for 5+ minutes |
| CacheHitRatioLow | Warning | Buffer cache hit ratio below 95% for 10+ minutes |
| RefresherViewsFailing | Warning | views_failed > 0 for 10+ minutes |

### PostgreSQL Exporter

Custom queries expose application-level metrics:
- `bigbrotr_overview`: relay_count, event_count_approx, metadata_count, service_state_count
- `bigbrotr_relay_by_network`: relay count per network type
- `bigbrotr_table_sizes`: per-table disk usage including indexes

### Structured Logging

All services use structured key=value logging:
```
info finder cycle_completed cycle=1 duration=2.5 relays_found=42
```

JSON output mode available for machine parsing:
```json
{"timestamp": "2026-03-09T10:30:45.123456+00:00", "level": "info", "service": "finder", "message": "cycle_completed", "cycle": 1}
```

---

## 10. Quality Assurance

### Test Suite

| Category | Count | Description |
|----------|-------|-------------|
| Unit tests | 2,737 | Isolated logic tests with mocked I/O |
| Integration tests | 216 | Real PostgreSQL via testcontainers |
| **Total** | **2,953** | Full suite |

**Test LOC**: 38,569 lines across 62 test files (53 unit + 9 integration).

**Coverage threshold**: 80% branch coverage (enforced, `fail_under = 80`).

**Test organization**: mirrors source tree. Class-per-unit naming (`TestPoolConnect`, `TestPoolRetry`). Method naming: `test_<method>_<scenario>`.

**Key patterns**:
- `asyncio_mode = "auto"` — no explicit `@pytest.mark.asyncio` markers needed.
- Global 120s timeout per test (`--timeout=120` in addopts).
- Mocks target consumer namespace, not source: `@patch("bigbrotr.services.validator.is_nostr_relay")` not `@patch("bigbrotr.utils.transport.is_nostr_relay")`.
- Shared fixtures in `tests/conftest.py` and `tests/fixtures/relays.py`.
- Integration tests use fresh PostgreSQL schema per test class via testcontainers.
- Integration fixtures use `TRUNCATE ... CASCADE` between tests for speed.

### CI Pipeline

**Trigger**: push to main/develop, PRs.

```
pre-commit ──┬──> unit-test (matrix: Python 3.11–3.14)
             ├──> integration-test
             ├──> docs
             └──> build (matrix: bigbrotr/lilbrotr, main/develop only)
                   │
                   └──> ci-success (branch protection gate)
```

| Job | Timeout | Description |
|-----|---------|-------------|
| pre-commit | 10 min | All 23 hooks via pre-commit/action |
| unit-test | 15 min | `uv sync`, `uv-secure` audit, SQL drift check, pytest with coverage (Codecov on 3.11 only) |
| integration-test | 10 min | testcontainers PostgreSQL |
| docs | 5 min | `mkdocs build --strict` |
| build | 20 min | Docker Buildx (2 deployments) + Trivy scan (CRITICAL/HIGH gate) + SARIF upload |
| ci-success | 5 min | Gate: all jobs must pass (build allowed to be skipped for PRs) |

### Code Quality Tools

| Tool | Mode | Configuration |
|------|------|---------------|
| Ruff | Lint + Format | 58 rule categories, line-length 100, target py311 |
| MyPy | Strict | On `src/bigbrotr` only |
| SQLFluff | PostgreSQL dialect | Uppercase keywords, lowercase identifiers |
| yamllint | Strict | 120 char lines, 2-space indent |
| detect-secrets | Baseline | Prevents accidental credential commits |
| hadolint | Docker linting | Ignores DL3008/DL3013 |
| codespell | Spell check | Custom word list for domain terms |
| markdownlint | Markdown linting | Fix mode (auto-corrects) |
| Trivy | Security scan | CRITICAL/HIGH severity gate on Docker images |
| CodeQL | SAST | Weekly + on PR, Python language |

### Pre-commit Hooks (23)

From 10 repositories:

| Category | Hooks |
|----------|-------|
| File hygiene (12) | trailing-whitespace, end-of-file-fixer, check-yaml, check-json, check-toml, check-added-large-files, check-merge-conflict, check-case-conflict, check-symlinks, detect-private-key, debug-statements, check-docstring-first, mixed-line-ending |
| Lock sync (1) | uv-lock |
| Format (4) | ruff (lint+fix), ruff-format, sqlfluff-fix, markdownlint (fix) |
| Type checking (1) | mypy (strict) |
| YAML (1) | yamllint |
| Secrets (1) | detect-secrets |
| Docker (1) | hadolint-docker |
| Spell check (1) | codespell |

---

## 11. Technology Stack

### Runtime

| Component | Version | Purpose |
|-----------|---------|---------|
| Python | 3.11+ (tested through 3.14) | Core language |
| PostgreSQL | 16+ | Primary database |
| asyncpg | >=0.29.0 | Async PostgreSQL driver |
| nostr-sdk | >=0.37.0 | Nostr protocol (Rust FFI via UniFFI) |
| aiohttp | >=3.9.0 | HTTP client + WebSocket |
| aiohttp-socks | >=0.9.0 | SOCKS5 proxy support |
| Pydantic | >=2.5.0 | Configuration validation |
| FastAPI | >=0.115.0 | REST API framework |
| uvicorn | >=0.34.0 | ASGI server |
| dnspython | >=2.5.0 | DNS resolution |
| geoip2 | >=4.8.0 | GeoLite2 database reader |
| geohash2 | >=1.1 | Geohash encoding |
| jmespath | >=1.0.0 | JSON data extraction |
| cryptography | >=46.0.5 | X.509 certificate parsing |
| rfc3986 | >=2.0.0 | URI parsing and validation |
| tldextract | >=5.1.0 | Domain/TLD extraction |
| prometheus-client | >=0.20.0 | Metrics exposition |
| PyYAML | >=6.0.1 | Configuration loading |

**16 runtime dependencies**.

### Development (20 packages)

Jinja2, pytest, pytest-asyncio, pytest-cov, pytest-mock, pytest-timeout, pytest-xdist, ruff, mypy, yamllint, sqlfluff, pre-commit, detect-secrets, uv-secure, types-PyYAML, types-jmespath, asyncpg-stubs, testcontainers[postgres], alembic, sqlalchemy[asyncio].

### Documentation (6 packages)

mkdocs, mkdocs-material, mkdocstrings[python], mkdocs-gen-files, mkdocs-literate-nav, mike.

### Infrastructure

| Component | Version | Purpose |
|-----------|---------|---------|
| Docker | Latest | Container runtime |
| uv | >=0.10.2 | Dependency management and build |
| PGBouncer | v1.25.1-p0 | Connection pooling |
| Tor | 0.4.8.10 | Overlay network proxy |
| Prometheus | v2.51.0 | Metrics collection |
| Grafana | 10.4.1 | Visualization |
| Alertmanager | v0.27.0 | Alert routing |
| tini | Latest | Container init process |

---

## 12. Configuration System

### Hierarchy

Configuration flows through three layers:

1. **Shared Brotr config** (`config/brotr.yaml`): database connection, pool settings, batch limits, timeouts.
2. **Per-service config** (`config/services/<service>.yaml`): service-specific settings with per-service pool overrides (user, password_env, min_size, max_size, application_name).
3. **Environment variables**: secrets (passwords, private keys) loaded at runtime.

The CLI merges these at startup: service config `pool` overrides are extracted and applied on top of shared brotr config. `application_name` auto-set to service name unless explicitly overridden.

### Configuration Models

All configuration uses Pydantic v2 models with:
- Type validation and coercion
- Range constraints (min/max values)
- Cross-field validators (e.g., `max_size >= min_size`, `default_page_size <= max_page_size`)
- Fail-fast at config load time (never at first use)
- Sensible defaults for all optional fields

### Key Configuration Knobs

| Setting | Default | Description |
|---------|---------|-------------|
| Service interval | 300s (5 min) | BaseService cycle interval (Refresher overrides to 3600s) |
| Max consecutive failures | 5 | Shutdown after N consecutive errors (0=unlimited) |
| Batch max size | 1000 | Max records per bulk insert |
| Query timeout | 60s | Single query timeout |
| Batch timeout | 120s | Bulk insert timeout |
| Cleanup timeout | 90s | Orphan deletion timeout |
| Refresh timeout | None (infinite) | Materialized view refresh timeout |
| Pool acquisition timeout | 10s | Connection pool checkout timeout |
| Pool min/max size | 1/5 | Connection pool bounds |
| Clearnet max tasks | 50 | Concurrent clearnet operations |
| Tor max tasks | 10 | Concurrent Tor operations |
| I2P max tasks | 5 | Concurrent I2P operations |
| Loki max tasks | 5 | Concurrent Lokinet operations |
| Clearnet timeout | 10s | Per-relay operation timeout |
| Tor timeout | 30s | Per-relay operation timeout |
| I2P timeout | 45s | Per-relay operation timeout |
| Loki timeout | 30s | Per-relay operation timeout |
| Validator retry cooldown | 3600s | Don't retry candidates within this window |
| Validator max failures | 720 | Delete exhausted candidates (if cleanup enabled) |
| Monitor geo max age | 30 days | GeoLite2 database freshness |
| Monitor discovery interval | 3600s | Kind 30166 publication cooldown per relay |
| Finder API cooldown | 86400s | Minimum time between re-polling an API source |
| Finder max duration | 86400s | Event scanning time budget per cycle |
| Sync end lag | 86400s | end_time = now - end_lag (avoid incomplete recent events) |
| Sync flush interval | 50 | Cursor persistence every N relays |
| API max page size | 1000 | Maximum rows per request |
| DVM max page size | 1000 | Maximum rows per job result |

---

## 13. Security Model

### Credential Management

- Database passwords loaded from environment variables (never in config files).
- Nostr private keys loaded from `NOSTR_PRIVATE_KEY` environment variable.
- PGBouncer userlist generated dynamically from environment at container start via `entrypoint.sh`.
- `detect-secrets` pre-commit hook prevents accidental credential commits.
- Key material redacted in `__repr__`/`__str__` of `KeysConfig`.

### Database Access Control

- **4 database roles**: admin (SUPERUSER), writer (full DML), refresher (REFRESH + SELECT), reader (SELECT + pg_monitor).
- **All functions SECURITY INVOKER**: run with caller's permissions.
- **PGBouncer**: transaction-mode pooling with scram-sha-256 authentication.
- **Stored procedure name validation**: regex `^[a-z_][a-z0-9_]*$` prevents SQL injection.
- **Parameterized queries**: all domain queries use `$1`/`$2` placeholders (never f-strings for values).

### Network Security

- Clearnet relays require TLS (`wss://`).
- SSL certificate validation with optional insecure fallback (configurable per service).
- Overlay networks (Tor/I2P/Loki) use dedicated SOCKS5 proxies.
- Prometheus metrics bound to `127.0.0.1` by default (configurable to `0.0.0.0` in containers).
- PostgreSQL bound to container network only.
- API whitelist-by-construction: only discovered tables/columns queryable. `CatalogError` prevents DB internal leaks.

### Input Validation

- All relay URLs validated against RFC 3986 with strict scheme/host requirements.
- 28 IANA local/private IP ranges rejected.
- Null bytes rejected in all string fields (PostgreSQL TEXT incompatibility).
- JSON response sizes bounded before parsing (prevents parse bombs).
- HTTP file downloads bounded before disk write.
- All database queries use parameterized placeholders.

### Supply Chain Security

- Docker images scanned with Trivy (CRITICAL/HIGH severity gate).
- CodeQL static analysis on every PR and weekly.
- Dependabot weekly updates with grouped PRs.
- CycloneDX SBOM generated for every release.
- OIDC trusted publisher for PyPI releases (no stored API tokens).
- `uv-secure` audit in CI (dependency vulnerability scanning).

---

## 14. Extensibility

### Adding a New Service

1. Create `src/bigbrotr/services/<name>/` with `__init__.py`, `configs.py`, `service.py`.
2. Subclass `BaseService[YourConfig]` and implement `async def run()` and `async def cleanup()`.
3. Set `SERVICE_NAME` and `CONFIG_CLASS` class variables.
4. Register in `__main__.py` `SERVICE_REGISTRY`.
5. Add deployment config `config/services/<name>.yaml`.
6. Add Docker Compose service entry.
7. Write unit tests mirroring service structure.

### Adding a New NIP

1. Create `src/bigbrotr/nips/nip<N>/` with `data.py` (Pydantic models with `_FIELD_SPEC`), `logs.py` (extends `BaseLogs`), metadata module (extends `BaseNipMetadata`), and top-level factory (extends `BaseNip`).
2. Follow the never-raise contract (errors in logs, not exceptions).
3. Add `MetadataType` variant to `models/metadata.py`.
4. Integrate into Monitor service's check flow.
5. Add materialized views and refresh functions if analytics needed.

### Adding a New Deployment

1. Create `deployments/<name>/` mirroring existing structure.
2. Customize SQL templates in `tools/templates/sql/<name>/` (Jinja2 block overrides).
3. Generate SQL from templates via `tools/generate_sql.py`.
4. Add Docker Compose configuration.
5. Update CI matrix for build and integration tests.

---

## 15. Deployment Variants

### bigbrotr (Full Archive)

The primary deployment with complete event storage.

- **Event storage**: full NIP-01 schema — `tags`, `content`, `sig` are `NOT NULL`.
- **`event_insert()`**: stores all 8 columns (id, pubkey, created_at, kind, tags, tagvalues, content, sig).
- **Use case**: complete relay observatory with rich analytics and full event reconstruction.

### lilbrotr (Lightweight)

A deployment optimized for reduced disk usage (~60% savings).

- **Event storage**: all 8 columns present but `tags`, `content`, `sig` are nullable and always `NULL`.
- **`event_insert()`**: stores only `(id, pubkey, created_at, kind, tagvalues)`.
- **Use case**: relay monitoring with lightweight event archiving (statistics only, no content).

Both share the same Dockerfile, service codebase, CLI, service configurations, materialized views, indexes, monitoring, and infrastructure. The only functional difference is the event table schema and corresponding stored procedure.

---

## 16. CLI

Entry point: `bigbrotr.__main__:cli` (registered as `bigbrotr` console script).

```
python -m bigbrotr <service> [--config PATH] [--brotr-config PATH] [--log-level LEVEL] [--once]
```

| Argument | Default | Description |
|----------|---------|-------------|
| `service` | (required) | One of: seeder, finder, validator, monitor, synchronizer, refresher, api, dvm |
| `--config` | `config/services/<service>.yaml` | Service configuration file |
| `--brotr-config` | `config/brotr.yaml` | Shared Brotr configuration file |
| `--log-level` | INFO | DEBUG, INFO, WARNING, ERROR |
| `--once` | False | Run single cycle and exit (no metrics server) |

**Lifecycle**:
1. Parse arguments, setup structured logging.
2. Load YAML configs, extract pool overrides, merge into brotr config.
3. `async with brotr:` — connect to database.
4. **One-shot** (`--once`): `async with service:` → `service.run()` → exit.
5. **Continuous**: start metrics server → register SIGINT/SIGTERM handlers → `async with service:` → `service.run_forever()`.
6. Graceful shutdown: signal handler calls `service.request_shutdown()` → current cycle completes → metrics server stops → exit.

---

## Appendix: Project Statistics

| Metric | Value |
|--------|-------|
| Python source LOC | 17,863 |
| Test LOC | 38,569 |
| SQL LOC (init scripts) | 1,766 |
| Version | 5.8.0 |
| Runtime dependencies | 16 |
| Dev dependencies | 20 |
| Docs dependencies | 6 |
| Docker containers | 15 |
| Database tables | 6 |
| Stored functions | 24 |
| Summary tables | 6 |
| Materialized views | 6 |
| Indexes | 27 |
| Unit tests | 2,737 |
| Integration tests | 216 |
| CI/CD pipelines | 4 |
| Pre-commit hooks | 23 |
| Alert rules | 7 |
| CLAUDE.md files | 20 |
| Supporting guides | 6 |
| Slash commands | 11 |
| Supported Python versions | 3.11, 3.12, 3.13, 3.14 |
