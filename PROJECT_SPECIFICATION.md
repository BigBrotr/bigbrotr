# BigBrotr Project Specification

## Executive Summary

BigBrotr is a production-grade, fully asynchronous Python system that continuously discovers, validates, monitors, and archives data from the **Nostr relay network**. It answers three fundamental questions:

1. **What relays exist on the Nostr network?**
2. **How healthy are they?**
3. **What events are they publishing?**

The system runs 8 independent services deployed via Docker Compose, backed by PostgreSQL 16, with full Prometheus/Grafana observability. It supports clearnet (TLS), Tor (.onion), I2P (.i2p), and Lokinet (.loki) relay networks.

---

## Table of Contents

1. [Purpose and Scope](#1-purpose-and-scope)
2. [Architecture Overview](#2-architecture-overview)
3. [Domain Model](#3-domain-model)
4. [Services](#4-services)
5. [NIP Protocol Implementations](#5-nip-protocol-implementations)
6. [Database Design](#6-database-design)
7. [Infrastructure and Deployment](#7-infrastructure-and-deployment)
8. [Observability](#8-observability)
9. [Quality Assurance](#9-quality-assurance)
10. [Technology Stack](#10-technology-stack)
11. [Configuration System](#11-configuration-system)
12. [Security Model](#12-security-model)
13. [Extensibility](#13-extensibility)
14. [Deployment Variants](#14-deployment-variants)

---

## 1. Purpose and Scope

### What Is Nostr?

Nostr (Notes and Other Stuff Transmitted by Relays) is a decentralized, censorship-resistant social protocol. Users publish cryptographically signed events to relays (WebSocket servers), which store and distribute them. There is no central directory of relays; they are independently operated and discovered organically.

### What BigBrotr Does

BigBrotr is a **relay observatory** that maps the Nostr relay ecosystem. It operates three pillars:

| Pillar | Description | Output |
|--------|-------------|--------|
| **Discovery** | Finds relay URLs from seed lists, API sources (nostr.watch), and Nostr events (kinds 2, 3, 10002) | Validated relay registry |
| **Health Monitoring** | Runs 7 health checks per relay: NIP-11 info, round-trip time, SSL certificates, DNS records, geolocation, ASN/network info, HTTP headers | Content-addressed metadata archive |
| **Event Archiving** | Collects and stores Nostr events from all validated relays with cursor-based pagination | Time-series event database with relay attribution |

### What BigBrotr Publishes

BigBrotr is also a **NIP-66 relay monitor**. It publishes its findings back to the Nostr network as signed events:

- **Kind 10166** (Monitor Announcement): Declares itself as a relay monitor with capabilities and check frequencies.
- **Kind 30166** (Relay Discovery): Per-relay health reports with RTT, SSL, geo, network tags.
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
- `models` has zero imports from any other BigBrotr package. Uses only stdlib and two external libraries (`nostr_sdk`, `rfc3986`).
- `core`, `nips`, and `utils` depend only on `models` (and each other where justified).
- `services` may import from all lower layers but never from each other.
- No circular dependencies exist.

### Package Responsibilities

| Package | Responsibility | I/O | LOC |
|---------|---------------|------|-----|
| `models` | Frozen dataclasses (Relay, Event, Metadata, ServiceState) with fail-fast validation | None | ~1,400 |
| `core` | Connection pool, DB facade, service base class, structured logging, Prometheus metrics | Database | ~2,800 |
| `nips` | NIP-11 relay info fetch/parse, NIP-66 health checks (6 types) | HTTP, DNS, SSL, WebSocket | ~4,200 |
| `utils` | WebSocket transport, DNS resolution, Nostr key management, bounded HTTP reads | Network | ~1,300 |
| `services` | 8 services + shared queries/mixins/configs | Orchestration | ~6,900 |

### Independent Services, Shared Database

All 8 services are **independent processes** with no direct service-to-service dependencies. They communicate exclusively through the shared PostgreSQL database. Stopping one service does not break the others.

```
                  ┌──────────────────────────────────────────────────────┐
                  │               PostgreSQL Database                    │
                  │                                                      │
                  │  relay ─── event_relay ─── event                     │
                  │  service_state (candidates/cursors)                  │
                  │  metadata ─── relay_metadata                        │
                  │  11 materialized views                              │
                  └──┬───┬───┬───┬───┬───┬───┬───┬─────────────────────┘
                     │   │   │   │   │   │   │   │
  ┌──────────────────┘   │   │   │   │   │   │   └─────────────────────┐
  │        ┌─────────────┘   │   │   │   │   └──────────────┐         │
  │        │     ┌───────────┘   │   │   └──────────┐       │         │
  ▼        ▼     ▼               ▼   ▼              ▼       ▼         ▼
┌──────┐ ┌──────┐ ┌─────────┐ ┌───────┐ ┌────────────┐ ┌─────────┐ ┌───┐ ┌───┐
│Seeder│ │Finder│ │Validator│ │Monitor│ │Synchronizer│ │Refresher│ │Api│ │Dvm│
│      │ │      │ │         │ │       │ │            │ │         │ │   │ │   │
│ boot │ │disc. │ │ test ws │ │health │ │archive evts│ │ refresh │ │REST│ │NIP│
└──┬───┘ └──┬───┘ └───┬─────┘ └──┬────┘ └─────┬──────┘ └────┬────┘ └─┬─┘ └─┬─┘
   │        │         │          │             │             │        │     │
   ▼        ▼         ▼          ▼             ▼             │        ▼     ▼
seed file  APIs     Relays    Relays        Relays        (no I/O)  HTTP  Nostr
         (HTTP)   (WebSocket) (NIP-11,     (fetch                        Network
                               NIP-66)     events)                     (kind 5050
                                 │                                      /6050)
                                 ▼
                          Nostr Network
                       (kind 10166/30166)
```

### Service-Database Interaction Map

```
                 relay   event  event_  meta-  relay_    service_  materialized
                                relay   data   metadata  state     views (11)
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

All domain models are **frozen, immutable dataclasses** with `slots=True` for memory efficiency. Validation is fail-fast in `__post_init__` -- invalid instances never escape constructors.

### Relay

A validated WebSocket endpoint on the Nostr network.

| Field | Type | Description |
|-------|------|-------------|
| `url` | `str` | Fully normalized WebSocket URL (computed from `raw_url`) |
| `network` | `NetworkType` | Detected from hostname: CLEARNET, TOR, I2P, LOKI |
| `scheme` | `str` | `wss` for clearnet, `ws` for overlay networks |
| `host` | `str` | Hostname or IP address |
| `port` | `int \| None` | Explicit port or None for defaults (443/80) |
| `path` | `str \| None` | URL path component |
| `discovered_at` | `int` | Unix timestamp of first discovery |

**Validation rules**:
- URL must be valid RFC 3986 with `ws://` or `wss://` scheme.
- Clearnet relays are upgraded to `wss://` (TLS required).
- Overlay networks (Tor/I2P/Loki) use `ws://` (encryption handled by overlay).
- Local/private IPs (27 IANA ranges) and invalid hostnames are rejected.
- Query strings and fragments are rejected.

### Event

A cryptographically signed Nostr event, wrapping `nostr_sdk.Event`.

| Field | Type | Description |
|-------|------|-------------|
| `_nostr_event` | `nostr_sdk.Event` | Underlying SDK event (delegated via `__getattr__`) |
| `id` | `bytes` | 32-byte SHA-256 event hash |
| `pubkey` | `bytes` | 32-byte author public key |
| `created_at` | `int` | Unix timestamp |
| `kind` | `int` | Event kind (0-65535) |
| `tags` | `str` | JSON-encoded tag array |
| `content` | `str` | Event content |
| `sig` | `bytes` | 64-byte Schnorr signature |

**Validation**: Null bytes in content or tags are rejected (PostgreSQL TEXT incompatibility).

### Metadata

Content-addressed metadata with SHA-256 hashing for deduplication.

| Field | Type | Description |
|-------|------|-------------|
| `type` | `MetadataType` | One of 7 types (NIP11_INFO, NIP66_RTT, NIP66_SSL, NIP66_GEO, NIP66_NET, NIP66_DNS, NIP66_HTTP) |
| `data` | `Mapping[str, Any]` | Deep-frozen, sanitized JSON-compatible dict |
| `content_hash` | `bytes` | SHA-256 of canonical JSON (computed, not stored in constructor) |
| `canonical_json` | `str` | Deterministic JSON (sorted keys, no whitespace) |

**Content addressing**: Same data always produces the same hash, regardless of key order. The `type` is NOT included in the hash but is part of the database composite PK `(id, type)`, enabling deduplication within each metadata type.

**Integrity verification**: the constructor recomputes the content hash from the canonical JSON representation, enabling detection of silent data corruption when reconstructing from stored values.

### Junction Models

Two junction models support **cascade atomic inserts** across multiple tables:

| Model | Junction | Purpose |
|-------|----------|---------|
| `EventRelay` | event + relay | Tracks which events appear on which relays (with `seen_at` timestamp) |
| `RelayMetadata` | relay + metadata | Links health check results to relays (with `generated_at` timestamp) |

Both flatten their composite fields into a single `NamedTuple` for efficient bulk insertion via PostgreSQL stored procedures.

### ServiceState

Generic key-value persistence for operational state between service restarts.

| Field | Type | Description |
|-------|------|-------------|
| `service_name` | `ServiceName` | Service identifier (8 values) |
| `state_type` | `ServiceStateType` | CANDIDATE, CURSOR, MONITORING, or PUBLICATION |
| `state_key` | `str` | Application-defined key (e.g., relay URL) |
| `state_value` | `Mapping[str, Any]` | Deep-frozen JSON dict |
| `updated_at` | `int` | Unix timestamp |

**Use cases**:
- **Finder**: Cursors tracking last-seen event timestamp per relay.
- **Validator**: Candidate records with failure counters.
- **Synchronizer**: Per-relay sync cursors (`last_synced_at`).
- **Monitor**: Health check monitoring state and publication tracking.

### Enumerations

| Enum | Values | Purpose |
|------|--------|---------|
| `NetworkType` | CLEARNET, TOR, I2P, LOKI, LOCAL, UNKNOWN | Relay network classification |
| `ServiceName` | SEEDER, FINDER, VALIDATOR, MONITOR, SYNCHRONIZER, REFRESHER, API, DVM | Service identifiers |
| `EventKind` | SET_METADATA(0), RECOMMEND_RELAY(2), CONTACTS(3), RELAY_LIST(10002), NIP66_TEST(22456), MONITOR_ANNOUNCEMENT(10166), RELAY_DISCOVERY(30166) | Well-known Nostr event kinds |
| `MetadataType` | NIP11_INFO, NIP66_RTT, NIP66_SSL, NIP66_GEO, NIP66_NET, NIP66_DNS, NIP66_HTTP | Health check result types |
| `ServiceStateType` | CANDIDATE, CURSOR, MONITORING, PUBLICATION | Service state discriminator |

---

## 4. Services

### Overview

Eight **independent** services run on their own schedules. They share the PostgreSQL database but have no direct dependencies on each other. Stopping or restarting any service does not affect the others.

```
┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐  ┌──────────┐  ┌─────┐  ┌─────┐
│  Seeder  │  │  Finder  │  │Validator │  │ Monitor  │  │Synchronizer  │  │ Refresher│  │ Api │  │ Dvm │
│ (boot)   │  │ (5 min)  │  │ (5 min)  │  │ (5 min)  │  │  (5 min)     │  │ (60 min) │  │     │  │     │
│          │  │          │  │          │  │          │  │              │  │          │  │     │  │     │
│ W: cand. │  │ R: relay │  │ R: cand. │  │ R: relay │  │ R: relay     │  │ W: views │  │R: * │  │R: * │
│ W: relay │  │ R: evts  │  │ W: relay │  │ W: meta  │  │ W: events    │  │          │  │     │  │     │
│          │  │ W: cand. │  │ W: cand. │  │ W: mons. │  │ W: cursors   │  │          │  │     │  │     │
│          │  │ W: curs. │  │          │  │ W: pubs. │  │              │  │          │  │     │  │     │
└──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────────┘  └──────────┘  └─────┘  └─────┘
     │             │              │             │               │                          │        │
     ▼             ▼              ▼             ▼               ▼                          ▼        ▼
  seed file    HTTP APIs      WebSocket    HTTP/WS/DNS/     WebSocket                    HTTP    Nostr
                                           SSL/GeoIP +                                          Network
                                           Nostr publish
```

**Loose coupling via database**: Seeder and Finder populate candidates in `service_state`. Validator reads candidates and promotes valid ones to `relay`. Monitor and Synchronizer read `relay` to know which relays to check or sync. Refresher materializes views from all accumulated data. Api and Dvm provide read-only access to all accumulated data. But each service runs its own loop, on its own schedule, independently.

All services inherit from `BaseService[ConfigT]`, which provides:
- Configurable run cycle intervals
- Graceful shutdown via `asyncio.Event`
- Automatic Prometheus metrics (cycle counts, durations, failures)
- Consecutive failure tracking with configurable shutdown threshold
- YAML/dict factory methods for configuration

### Service Details

#### 1. Seeder

**Purpose**: Bootstrap relay URLs from a static seed file.

| Property | Value |
|----------|-------|
| Execution | One-shot (`--once` flag) |
| Input | `static/seed_relays.txt` (one URL per line) |
| Output | Candidates (for validation) or direct relay inserts |
| Config | `SeedConfig.to_validate: bool` controls output mode |

**Process**:
1. Read seed file (skip comments, blank lines).
2. Parse and validate each URL via `Relay()` constructor.
3. Insert as candidates (default) or directly as relays.

#### 2. Finder

**Purpose**: Discover new relay URLs from two sources: external APIs and stored Nostr events.

| Property | Value |
|----------|-------|
| Execution | Continuous (default 5-min interval) |
| Input | nostr.watch APIs, database events (kinds 2, 3, 10002) |
| Output | Candidates (for validation) |
| Concurrency | Configurable: `max_parallel_api` (5), `max_parallel_events` (10) |

**API Discovery**:
1. Fetch JSON from configured API sources (default: nostr.watch online/offline endpoints).
2. Apply JMESPath expression to extract URLs from response.
3. Validate each URL via `Relay()` constructor.
4. Insert new URLs as candidates (skip duplicates).

**Event Scanning**:
1. Fetch all relay URLs from database.
2. Load per-relay cursors (`last_seen_at`) for incremental scanning.
3. For each relay, fetch events after cursor position.
4. Extract relay URLs from event tag values.
5. Insert discovered URLs as candidates.
6. Update cursor to latest `seen_at`.

#### 3. Validator

**Purpose**: Validate candidate URLs by attempting Nostr WebSocket protocol handshake.

| Property | Value |
|----------|-------|
| Execution | Continuous (default 5-min interval) |
| Input | Candidates from `service_state` table |
| Output | Promoted relays in `relay` table |
| Concurrency | Per-network semaphores (clearnet: 50, Tor: 10, I2P: 5, Loki: 5) |

**Process**:
1. Clean up stale candidates (URLs already in relay table).
2. Optionally clean up exhausted candidates (too many failures).
3. Fetch candidate chunk (prioritized by fewest failures, then oldest).
4. For each candidate, attempt `is_nostr_relay()` WebSocket check:
   - Connect to relay with SSL (clearnet) or proxy (overlay).
   - Send REQ for kind 1 events with limit 1.
   - Success criteria: EOSE response, AUTH challenge, or auth-required CLOSED.
5. **Valid relays**: Atomically promote (insert relay + delete candidate in transaction).
6. **Invalid candidates**: Increment failure counter for retry in future cycles.

**SSL Fallback**: Clearnet relays try verified SSL first. If SSL fails and `allow_insecure=True`, retry with certificate verification disabled.

#### 4. Monitor

**Purpose**: Run comprehensive health checks on validated relays and publish results.

| Property | Value |
|----------|-------|
| Execution | Continuous (default 5-min interval) |
| Input | Relays from `relay` table (due for check based on interval) |
| Output | Metadata records, Kind 10166/30166 Nostr events |
| Concurrency | Per-network semaphores + per-check retry with exponential backoff |

**Health Checks** (7 types, all configurable):

| Check | Network | Method | Output |
|-------|---------|--------|--------|
| NIP-11 Info | All | HTTP GET to relay info URL | name, description, supported NIPs, software, version, fees, limitations, retention policies |
| NIP-66 RTT | All | 3-phase WebSocket test (open + read + write) | Round-trip times in milliseconds |
| NIP-66 SSL | Clearnet only | Two-context extraction + validation | Certificate subject, issuer, expiry, SANs, fingerprint, protocol, cipher |
| NIP-66 DNS | Clearnet only | A/AAAA/CNAME/NS/PTR resolution | IP addresses, nameservers, CNAME, reverse DNS, TTL |
| NIP-66 Geo | Clearnet only | GeoLite2 City database lookup | Country, city, coordinates, geohash, timezone, continent |
| NIP-66 Net | Clearnet only | GeoLite2 ASN database lookup | IP, ASN, organization, network ranges |
| NIP-66 HTTP | All | WebSocket handshake header capture | Server, X-Powered-By headers |

**RTT Test Phases**:
1. **Open**: Connect via WebSocket, measure connection time.
2. **Read**: Subscribe to events, measure time to first event (EOSE).
3. **Write**: Send a test event (Kind 22456, ephemeral), verify relay acceptance and retrievability.

**Publishing**:
- **Kind 30166** (Relay Discovery): Published per relay with health check tags (RTT, SSL, geo, net, DNS). Addressable replaceable event keyed by relay URL.
- **Kind 10166** (Monitor Announcement): Published periodically with check capabilities, frequency, supported networks.
- **Kind 0** (Profile): Optional monitor identity metadata.

**GeoIP Database Management**: Monitor auto-downloads GeoLite2 City and ASN databases if missing or stale (configurable max age, default 30 days).

#### 5. Synchronizer

**Purpose**: Collect Nostr events from all validated relays and store them.

| Property | Value |
|----------|-------|
| Execution | Continuous (default 5-min interval) |
| Input | All relays from `relay` table |
| Output | Events in `event` + `event_relay` tables |
| Concurrency | Per-network semaphores, shuffled relay order |

**Process**:
1. Delete stale cursors (relays no longer in database).
2. Fetch all relays, filter by enabled networks.
3. Merge per-relay configuration overrides.
4. Shuffle relay list (avoid thundering herd).
5. For each relay (bounded by network semaphore):
   - Compute sync window: `[cursor + 1, now - lookback]`.
   - Connect via WebSocket (with optional SOCKS5 proxy).
   - Build Nostr filter from config (kinds, authors, tags, limit).
   - Fetch events within time window.
   - Validate each event (signature verification + timestamp range).
   - Insert valid events via `event_relay_insert_cascade` (atomic multi-table insert).
   - Update per-relay cursor to latest `created_at`.
6. Flush remaining cursor updates.

**Feedback loop**: Events collected by Synchronizer are later scanned by Finder to discover new relay URLs from tag values.

#### 6. Refresher

**Purpose**: Periodically refresh materialized views in dependency order.

| Property | Value |
|----------|-------|
| Execution | Continuous (default 60-min interval) |
| Input | Configured view list (11 views) |
| Output | Fresh materialized view data |

**Refresh order** (3 dependency levels):
1. `relay_metadata_latest` (base dependency for level 3)
2. `event_stats`, `relay_stats`, `kind_counts`, `kind_counts_by_relay`, `pubkey_counts`, `pubkey_counts_by_relay`, `network_stats`, `event_daily_counts`
3. `relay_software_counts`, `supported_nip_counts` (depend on `relay_metadata_latest`)

Individual view failures do not block subsequent views.

#### 7. Api

**Purpose**: Provide read-only HTTP access to all tables, views, and materialized views.

| Property | Value |
|----------|-------|
| Execution | Continuous (HTTP server) |
| Input | HTTP requests |
| Output | JSON responses |
| Framework | FastAPI |

**Process**:
1. Auto-generates paginated endpoints via Catalog schema introspection.
2. Enforces per-table access control via `TablePolicy`.
3. All queries are read-only against the shared PostgreSQL database.

#### 8. Dvm

**Purpose**: NIP-90 Data Vending Machine service for on-demand data queries via Nostr.

| Property | Value |
|----------|-------|
| Execution | Continuous (WebSocket listener) |
| Input | Kind 5050 job request events from Nostr relays |
| Output | Kind 6050 result events published to Nostr relays |

**Process**:
1. Listens for kind 5050 job requests on configured Nostr relays.
2. Executes read-only queries via the shared Catalog.
3. Publishes kind 6050 result events back to the Nostr network.
4. Enforces per-table pricing via `DvmTablePolicy`.

---

## 5. NIP Protocol Implementations

### Design Principles

All NIP fetch methods follow a **never-raise contract**. Errors are captured in structured logs:
```python
logs.success = False
logs.reason = "descriptive error message"
```

Data models use **declarative field parsing** via `FieldSpec`, silently dropping invalid values from untrusted relay responses.

### NIP-11: Relay Information Document

Fetches the relay's self-declared information via HTTP GET to the relay's info URL (WebSocket URL converted to HTTPS).

**Data extracted** (`Nip11InfoData`):
- Identity: name, description, banner, icon, pubkey, contact
- Software: software name, version
- Capabilities: supported_nips (sorted, deduplicated)
- Policies: privacy_policy, terms_of_service, posting_policy
- Limitations: max_message_length, max_subscriptions, auth_required, payment_required, restricted_writes
- Fees: admission, subscription, publication (with amounts, units, periods)
- Retention: per-kind retention policies with time/count limits
- Localization: relay_countries, language_tags
- Payments: payments_url

**SSL handling**: Clearnet tries verified HTTPS first; falls back to unverified if `allow_insecure=True`. Overlay networks use SOCKS5 proxy with no SSL verification.

### NIP-66: Relay Monitoring and Discovery

Six independent health checks, all run concurrently via `asyncio.gather()`:

#### RTT (Round-Trip Time)
- **Open phase**: WebSocket connection establishment time (ms).
- **Read phase**: Time to first event arrival after REQ subscription (ms).
- **Write phase**: Time to send event + verify retrieval (ms).
- **Cascading failure**: If open fails, read and write automatically fail with same reason.
- **Supports**: All networks (overlay via SOCKS5 proxy).

#### SSL Certificate
- **Two-context strategy**: Extract certificate data with CERT_NONE (reads any cert), then validate with default context (verifies chain).
- **Data**: subject CN, issuer, expiry, SANs, serial, fingerprint (SHA-256), protocol, cipher, bits.
- **Clearnet only**: Overlay networks rejected (encryption handled by overlay).
- **Thread pool**: Synchronous SSL operations delegated via `asyncio.to_thread()`.

#### DNS Resolution
- **Records**: A (IPv4), AAAA (IPv6), CNAME, NS (against registered domain), PTR (reverse DNS from first IPv4).
- **Library**: dnspython with per-record-type error isolation.
- **Clearnet only**.

#### Geolocation
- **Database**: GeoLite2 City (MaxMind).
- **Data**: country (physical preferred over registered), city, coordinates, geohash (precision 9), timezone, continent, postal code.
- **IP selection**: IPv4 preferred; IPv6 as fallback.
- **Clearnet only**.

#### Network/ASN
- **Database**: GeoLite2 ASN (MaxMind).
- **Data**: IPv4 address, IPv6 address, ASN number, organization, network ranges.
- **Priority**: IPv4 ASN preferred; IPv6 used as fallback for ASN/org.
- **Clearnet only**.

#### HTTP Headers
- **Method**: Captures WebSocket handshake response headers via aiohttp trace hooks.
- **Data**: Server header, X-Powered-By header.
- **Supports**: All networks (overlay via SOCKS5 proxy).

### Event Builders

The `nips/event_builders.py` module constructs Nostr events for publishing:

- `build_profile_event()`: Kind 0 with profile metadata.
- `build_monitor_announcement()`: Kind 10166 with capability tags, network tags, frequency.
- `build_relay_discovery()`: Kind 30166 with relay URL identifier, health check tags, language/requirement/type tags.

**Relay type classification** (from RTT probe + NIP-11 data): Search, Community, Blob, Paid, PrivateStorage, PrivateInbox, PublicOutbox, PublicInbox.

---

## 6. Database Design

### Schema

6 tables, 25 stored procedures, 11 materialized views, 30+ indexes.

#### Tables

```
relay                    (url PK, network, discovered_at)
    │
    ├── event_relay      (event_id FK, relay_url FK, seen_at) ── PK(event_id, relay_url)
    │       │
    │       └── event    (id PK, pubkey, created_at, kind, tags, tagvalues GENERATED, content, sig)
    │
    ├── relay_metadata   (relay_url FK, metadata_id FK, metadata_type FK, generated_at) ── PK(relay_url, generated_at, metadata_type)
    │       │
    │       └── metadata (id, metadata_type) ── PK(id, metadata_type), data JSONB
    │
    └── service_state    (service_name, state_type, state_key) ── PK(service_name, state_type, state_key)
```

#### Key Design Decisions

- **Generated column**: `event.tagvalues` is a `TEXT[]` column generated from `tags_to_tagvalues(tags)`, extracting values from single-character tag keys. Indexed with GIN for efficient containment queries.
- **Content addressing**: Metadata uses SHA-256 hash + type as composite PK. Hash computed in Python for deterministic cross-platform behavior.
- **Cascade functions**: `event_relay_insert_cascade` and `relay_metadata_insert_cascade` atomically insert across 3 tables in a single stored procedure call.
- **Bulk array parameters**: All insert functions accept parallel arrays and use `UNNEST` for single-roundtrip bulk inserts.
- **No CHECK constraints**: Validation enforced in Python enum layer.
- **All functions SECURITY INVOKER**: PostgreSQL default, ensuring functions run with caller's permissions.

#### Materialized Views

| View | Granularity | Key Metrics |
|------|-------------|-------------|
| `relay_metadata_latest` | Per relay + type | Most recent metadata snapshot |
| `event_stats` | Global (singleton) | Total events, unique pubkeys/kinds, rolling windows (1h/24h/7d/30d), events/day |
| `relay_stats` | Per relay | Event count, unique pubkeys, avg RTT (last 10), NIP-11 info |
| `kind_counts` | Per event kind | Event count, unique pubkeys, NIP-01 category |
| `kind_counts_by_relay` | Per kind + relay | Per-relay kind distribution |
| `pubkey_counts` | Per author | Event count, unique kinds, first/last timestamps |
| `pubkey_counts_by_relay` | Per author + relay | Per-relay author activity (2+ events filter) |
| `network_stats` | Per network type | Relay count, event count, unique pubkeys/kinds |
| `relay_software_counts` | Per software + version | Relay count by software distribution |
| `supported_nip_counts` | Per NIP number | Relay count supporting each NIP |
| `event_daily_counts` | Per UTC day | Daily event volume, unique pubkeys/kinds |

All materialized views have unique indexes (required for `REFRESH MATERIALIZED VIEW CONCURRENTLY`) and are refreshed by the Refresher service in dependency order.

#### Indexes

**Event table** (7 indexes):
- `created_at DESC` (timeline queries)
- `kind` (kind filtering)
- `(kind, created_at DESC)` (kind + timeline)
- `(pubkey, created_at DESC)` (author timeline)
- `(pubkey, kind, created_at DESC)` (author + kind + timeline)
- `tagvalues` GIN (tag value containment)
- `(created_at ASC, id ASC)` (cursor-based pagination)

**Event_relay table** (3 indexes + PK):
- `relay_url` (events from relay)
- `seen_at DESC` (recent events)
- `(relay_url, seen_at DESC)` (latest events per relay)

**Service_state table** (3 indexes + PK):
- `service_name` (all data for service)
- `(service_name, state_type)` (state type within service)
- `(state_value->>'network') WHERE candidate` (candidate filtering by network)

#### Roles

| Role | Permissions |
|------|------------|
| `bigbrotr_writer` | SELECT, INSERT, UPDATE, DELETE on all tables + EXECUTE on all functions |
| `bigbrotr_reader` | SELECT on all tables + EXECUTE on all functions + `pg_monitor` |

---

## 7. Infrastructure and Deployment

### Docker Compose Stack

15 containers on 2 bridge networks:

| Container | Image | CPU | RAM | Purpose |
|-----------|-------|-----|-----|---------|
| PostgreSQL 16 | postgres:16-alpine | 2 | 2G | Primary database |
| PGBouncer | edoburu/pgbouncer:v1.25.1 | 0.5 | 256M | Connection pooler (transaction mode) |
| Tor | osminogin/tor-simple:0.4.8.10 | 0.5 | 256M | SOCKS5 proxy for .onion relays |
| Seeder | bigbrotr (custom) | 0.5 | 256M | One-shot relay bootstrapping |
| Finder | bigbrotr (custom) | 1 | 512M | Continuous relay discovery |
| Validator | bigbrotr (custom) | 1 | 512M | WebSocket protocol validation |
| Monitor | bigbrotr (custom) | 1 | 512M | Health checks + event publishing |
| Synchronizer | bigbrotr (custom) | 1 | 512M | Event collection |
| Refresher | bigbrotr (custom) | 0.25 | 256M | Materialized view refresh |
| Api | bigbrotr (custom) | 0.5 | 256M | REST API (read-only) |
| Dvm | bigbrotr (custom) | 0.5 | 256M | NIP-90 Data Vending Machine |
| postgres-exporter | prometheuscommunity | 0.25 | 128M | PostgreSQL metrics for Prometheus |
| Prometheus | prom/prometheus:v2.51.0 | 0.5 | 512M | Time-series metrics database (30-day retention) |
| Alertmanager | prom/alertmanager:v0.27.0 | 0.25 | 128M | Alert routing and grouping |
| Grafana | grafana/grafana:10.4.1 | 0.5 | 512M | Dashboards and visualization |

**Total resources**: ~9.75 CPUs, ~6.9 GB RAM

**Networks**:
- `bigbrotr-data-network`: PostgreSQL, PGBouncer, Tor, services
- `bigbrotr-monitoring-network`: Prometheus, Grafana, Alertmanager, postgres-exporter, all services

**Optional containers** (disabled by default): I2P proxy, Lokinet proxy.

### Dockerfile

Multi-stage parametric build:
- **Builder stage**: Python 3.11-slim + uv for dependency installation + gcc/libpq-dev for native extensions.
- **Production stage**: Python 3.11-slim + runtime deps only + tini (PID 1 init) + non-root user.
- **Parametric**: `ARG DEPLOYMENT` selects config directory (bigbrotr/lilbrotr).

### PostgreSQL Tuning

Optimized for 2GB container:
- `shared_buffers = 512MB` (25% RAM)
- `effective_cache_size = 1536MB` (75% RAM)
- `synchronous_commit = off` (async commits for write throughput)
- `random_page_cost = 1.1` (SSD-optimized)
- Aggressive autovacuum (30s naptime, 2ms cost delay)
- `pg_stat_statements` for query performance analysis

### PGBouncer Configuration

- **Mode**: Transaction pooling
- **Auth**: scram-sha-256
- **Pool sizes**: bigbrotr=10, bigbrotr_readonly=8
- **Timeouts**: query_timeout=300s, query_wait_timeout=120s

### Startup Sequence

1. PostgreSQL starts, executes 10 init SQL files in order.
2. PGBouncer starts (depends on PostgreSQL healthy).
3. Tor/proxy starts.
4. Seeder runs once (depends on PGBouncer healthy).
5. All continuous services start (depend on PGBouncer healthy).
6. Monitoring stack starts independently.

---

## 8. Observability

### Prometheus Metrics

Each service automatically records:

| Metric | Type | Description |
|--------|------|-------------|
| `service_info` | Info | Static service metadata (set once at startup) |
| `service_counter{service, name}` | Counter | Cumulative totals: `cycles_success`, `cycles_failed`, `errors_{ExceptionType}` |
| `service_gauge{service, name}` | Gauge | Point-in-time values: `consecutive_failures`, `last_cycle_timestamp`, custom per-service |
| `cycle_duration_seconds{service}` | Histogram | Cycle latency with buckets: 1s, 5s, 10s, 30s, 60s, 120s, 300s, 600s, 1800s, 3600s |

Services add custom metrics via `set_gauge(name, value)` and `inc_counter(name, value)`.

### Alerting Rules

| Alert | Severity | Condition |
|-------|----------|-----------|
| ServiceDown | Critical | Service unreachable for 5+ minutes |
| HighFailureRate | Warning | >0.1 errors/second over 5 minutes |
| ConsecutiveFailures | Critical | 5+ consecutive cycle failures |
| SlowCycles | Warning | p99 cycle duration exceeds 5 minutes |
| DatabaseConnectionsHigh | Warning | >80 active PostgreSQL connections |
| CacheHitRatioLow | Warning | Buffer cache hit ratio below 95% |

### PostgreSQL Exporter

Custom queries expose BigBrotr-specific metrics:
- `bigbrotr_overview`: relay_count, event_count_approx, metadata_count, service_state_count
- `bigbrotr_relay_by_network`: Relay count per network type
- `bigbrotr_table_sizes`: Per-table disk usage including indexes

### Structured Logging

All services use structured key=value logging:
```
info finder cycle_completed cycle=1 duration=2.5 relays_found=42
```

JSON output mode available for machine parsing:
```json
{"timestamp": "2024-02-26T10:30:45.123456+00:00", "level": "info", "service": "finder", "message": "cycle_completed", "cycle": 1}
```

---

## 9. Quality Assurance

### Test Suite

| Category | Count | Description |
|----------|-------|-------------|
| Unit tests | ~2,400 | Isolated logic tests with mocked I/O |
| Integration tests | ~90 | Real PostgreSQL via testcontainers |
| Total | ~2,490 | Full suite |

**Coverage threshold**: 80% branch coverage (enforced).

**Test organization**: Mirrors source tree. Class-per-unit naming (`TestPoolConnect`, `TestPoolRetry`). Method naming: `test_<method>_<scenario>`.

**Key patterns**:
- `asyncio_mode = "auto"` (no explicit markers needed).
- Global 120s timeout per test.
- Mocks target consumer namespace, not source.
- Shared fixtures in `tests/conftest.py` and `tests/fixtures/relays.py`.
- Integration tests use fresh PostgreSQL schema per test via testcontainers.

### CI Pipeline

**Trigger**: Push to main/develop, PRs.

| Job | Duration | Description |
|-----|----------|-------------|
| pre-commit | 10 min | All 15 pre-commit hooks |
| unit-test | 15 min | Python 3.11-3.14 matrix, coverage upload |
| integration-test | 10 min | testcontainers PostgreSQL |
| docs | 5 min | mkdocs build --strict |
| build | 20 min | Docker build + Trivy security scan |
| ci-success | 5 min | Gate: all jobs must pass |

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
| Trivy | Security scan | CRITICAL/HIGH severity gate on Docker images |
| CodeQL | SAST | Weekly + on PR, Python language |

### Pre-commit Hooks

15 hooks from 10 repositories run on every commit:
- File hygiene (trailing whitespace, end-of-file, mixed line endings)
- Format enforcement (ruff format, sqlfluff fix, markdownlint fix)
- Type checking (mypy strict)
- Secret detection (detect-secrets)
- Lock file sync (uv-lock)
- Docker linting (hadolint)
- Spell checking (codespell)

---

## 10. Technology Stack

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
| dnspython | >=2.5.0 | DNS resolution |
| geoip2 | >=4.8.0 | GeoLite2 database reader |
| geohash2 | >=1.1 | Geohash encoding |
| jmespath | >=1.0.0 | JSON data extraction |
| cryptography | >=46.0.5 | X.509 certificate parsing |
| rfc3986 | >=2.0.0 | URI parsing and validation |
| tldextract | >=5.1.0 | Domain/TLD extraction |
| prometheus-client | >=0.20.0 | Metrics exposition |
| PyYAML | >=6.0.1 | Configuration loading |

### Build and Quality

| Tool | Version | Purpose |
|------|---------|---------|
| uv | >=0.10.2 | Dependency management and build |
| Ruff | >=0.14.0 | Lint + format (unified) |
| MyPy | >=1.19.0 | Static type checking |
| pytest | >=8.0.0 | Test framework |
| testcontainers | >=4.0.0 | Integration test PostgreSQL |
| MkDocs Material | >=9.5.0 | Documentation |

### Infrastructure

| Component | Version | Purpose |
|-----------|---------|---------|
| Docker | Latest | Container runtime |
| PGBouncer | v1.25.1 | Connection pooling |
| Tor | 0.4.8.10 | Overlay network proxy |
| Prometheus | v2.51.0 | Metrics collection |
| Grafana | 10.4.1 | Visualization |
| Alertmanager | v0.27.0 | Alert routing |
| tini | Latest | Container init process |

---

## 11. Configuration System

### Hierarchy

Configuration flows through three layers:

1. **Shared Brotr config** (`config/brotr.yaml`): Database connection, pool settings, batch limits, timeouts.
2. **Per-service config** (`config/services/<service>.yaml`): Service-specific settings with per-service pool overrides.
3. **Environment variables**: Secrets (passwords, private keys) loaded at runtime.

The CLI merges these at startup: service config pool overrides are applied on top of shared brotr config.

### Configuration Models

All configuration uses Pydantic v2 models with:
- Type validation and coercion
- Range constraints (min/max values)
- Cross-field validators (e.g., max_size >= min_size)
- Fail-fast at config load time (never at first use)
- Sensible defaults for all optional fields

### Key Configuration Knobs

| Setting | Default | Description |
|---------|---------|-------------|
| Service interval | 300s (5 min) | Time between run cycles |
| Max consecutive failures | 5 | Shutdown after N consecutive errors |
| Batch max size | 1000 | Max records per bulk insert |
| Query timeout | 60s | Single-row query timeout |
| Batch timeout | 120s | Bulk insert timeout |
| Cleanup timeout | 90s | Orphan deletion timeout |
| Refresh timeout | None (infinite) | Materialized view refresh timeout |
| Pool acquisition timeout | 10s | Connection pool checkout timeout |
| Pool min/max size | 2/20 | Connection pool bounds |
| Clearnet max tasks | 50 | Concurrent clearnet operations |
| Tor max tasks | 10 | Concurrent Tor operations |
| Clearnet timeout | 10s | Per-relay operation timeout |
| Tor timeout | 30s | Per-relay operation timeout |

---

## 12. Security Model

### Credential Management

- Database passwords loaded from environment variables (never in config files).
- Nostr private keys loaded from `PRIVATE_KEY` environment variable.
- PGBouncer userlist generated dynamically from environment at container start.
- `detect-secrets` pre-commit hook prevents accidental credential commits.

### Database Access Control

- **Writer role**: Full DML on all tables, used by writer services.
- **Reader role**: SELECT only, used by API/monitoring.
- **All functions SECURITY INVOKER**: Run with caller's permissions, not definer's.
- **PGBouncer**: Transaction-mode pooling with scram-sha-256 authentication.

### Network Security

- Clearnet relays require TLS (`wss://`).
- SSL certificate validation with optional insecure fallback.
- Overlay networks (Tor/I2P/Loki) use dedicated SOCKS5 proxies.
- Prometheus metrics bound to `127.0.0.1` by default (configurable to `0.0.0.0` in containers).
- PostgreSQL bound to container network only.

### Supply Chain Security

- Docker images scanned with Trivy (CRITICAL/HIGH severity gate).
- CodeQL static analysis on every PR and weekly.
- Dependabot weekly updates with grouped PRs.
- CycloneDX SBOM generated for every release.
- OIDC trusted publisher for PyPI releases (no stored API tokens).

### Input Validation

- All relay URLs validated against RFC 3986 with strict scheme/host requirements.
- Local/private IPs rejected (27 IANA ranges).
- Null bytes rejected in all string fields (PostgreSQL TEXT incompatibility).
- JSON response sizes bounded before parsing (prevents parse bombs).
- Stored procedure names validated against regex (prevents SQL injection).
- All database queries use parameterized placeholders (`$1`, `$2`).

---

## 13. Extensibility

### Adding a New Service

1. Create `src/bigbrotr/services/<name>/` with `__init__.py`, `configs.py`, `service.py`.
2. Subclass `BaseService[YourConfig]` and implement `async def run()`.
3. Set `SERVICE_NAME` and `CONFIG_CLASS` class variables.
4. Register in `__main__.py` SERVICE_REGISTRY.
5. Add deployment config `config/services/<name>.yaml`.
6. Add Docker Compose service entry.
7. Write unit tests mirroring service structure.

### Adding a New NIP

1. Create `src/bigbrotr/nips/nip<N>/` with data models, logs, metadata, and top-level factory.
2. Follow the never-raise contract (errors in logs, not exceptions).
3. Add `MetadataType` variant to `models/metadata.py`.
4. Integrate into Monitor service's check flow.
5. Add materialized views if analytics needed.

### Adding a New Deployment

1. Create `deployments/<name>/` mirroring existing structure.
2. Customize SQL schema (table columns, views, indexes).
3. Generate SQL from Jinja2 templates via `tools/generate_sql.py`.
4. Add Docker Compose configuration.
5. Update CI matrix for build and integration tests.

---

## 14. Deployment Variants

### bigbrotr (Full Archive)

The primary deployment with complete event storage and 11 materialized views.

- **Event storage**: Full schema (id, pubkey, created_at, kind, tags, tagvalues, content, sig).
- **Materialized views**: All 11 analytics views.
- **Use case**: Complete relay observatory with rich analytics.

### lilbrotr (Lightweight)

A minimal deployment optimized for reduced disk usage (~60% savings).

- **Event storage**: Metadata-only (omits tags, content, sig).
- **Materialized views**: None (reduces refresh overhead).
- **Use case**: Relay health monitoring without event archiving.

Both share the same Dockerfile, service codebase, and CLI. The difference is entirely in SQL schema and configuration.

---

## Appendix: Project Statistics

| Metric | Value |
|--------|-------|
| Python source LOC | ~17,000 |
| Test LOC | ~35,000 |
| SQL LOC | ~1,500 |
| Total files | ~200 |
| Dependencies (runtime) | 17 |
| Dependencies (dev) | 18 |
| Docker containers | 15 |
| Database tables | 6 |
| Stored procedures | 25 |
| Materialized views | 11 |
| Unit tests | ~2,400 |
| Integration tests | ~90 |
| CI/CD pipelines | 4 |
| Pre-commit hooks | 15 |
| Supported Python versions | 3.11, 3.12, 3.13, 3.14 |
