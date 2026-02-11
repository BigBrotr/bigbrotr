# Service Pipeline

Deep dive into BigBrotr's five-service pipeline: how relays are discovered, validated, monitored, and how events are archived.

---

## Overview

BigBrotr processes relay data through a sequential pipeline of five async services:

--8<-- "docs/_snippets/pipeline.md"

--8<-- "docs/_snippets/service-table.md"

Each service runs independently as its own process, communicating exclusively through the shared PostgreSQL database. Services can be started, stopped, and scaled independently.

---

## Pipeline Data Flow

The following diagram shows which database tables each service reads from and writes to:

```mermaid
flowchart TD
    subgraph Services
        SE["Seeder"]
        FI["Finder"]
        VA["Validator"]
        MO["Monitor"]
        SY["Synchronizer"]
    end

    subgraph Database
        SS["service_state<br/><small>candidates, cursors</small>"]
        RE["relay<br/><small>validated URLs</small>"]
        MD["metadata<br/><small>NIP-11/NIP-66 docs</small>"]
        RM["relay_metadata<br/><small>time-series snapshots</small>"]
        EV["event<br/><small>Nostr events</small>"]
        ER["event_relay<br/><small>event-relay junction</small>"]
    end

    SE -->|"write candidates"| SS
    FI -->|"read events"| EV
    FI -->|"write candidates"| SS
    VA -->|"read candidates"| SS
    VA -->|"promote valid"| RE
    VA -->|"update failures"| SS
    MO -->|"read relays"| RE
    MO -->|"write metadata"| MD
    MO -->|"write snapshots"| RM
    SY -->|"read relays"| RE
    SY -->|"read/write cursors"| SS
    SY -->|"write events"| EV
    SY -->|"write junctions"| ER

    style SE fill:#7B1FA2,color:#fff,stroke:#4A148C
    style FI fill:#7B1FA2,color:#fff,stroke:#4A148C
    style VA fill:#7B1FA2,color:#fff,stroke:#4A148C
    style MO fill:#7B1FA2,color:#fff,stroke:#4A148C
    style SY fill:#7B1FA2,color:#fff,stroke:#4A148C
    style SS fill:#311B92,color:#fff,stroke:#1A237E
    style RE fill:#311B92,color:#fff,stroke:#1A237E
    style MD fill:#311B92,color:#fff,stroke:#1A237E
    style RM fill:#311B92,color:#fff,stroke:#1A237E
    style EV fill:#311B92,color:#fff,stroke:#1A237E
    style ER fill:#311B92,color:#fff,stroke:#1A237E
```

---

## Seeder

**Purpose**: Bootstrap the pipeline by loading relay URLs from a static seed file.

**Mode**: One-shot (`--once` flag). Runs once and exits.

**Reads**: Seed file (`static/seed_relays.txt`)
**Writes**: `service_state` (candidates) or `relay` (direct insert)

### How It Works

1. Read the seed file (one URL per line, `#` comments skipped)
2. Parse each URL into a `Relay` object (validates URL format, detects network type)
3. Insert as candidates via `upsert_candidates()` (default) or directly to the `relay` table

!!! tip
    Set `to_validate: false` in the Seeder config to skip validation and insert relays directly. This is useful when seeding with a trusted, pre-validated relay list.

### Configuration

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `seed.file_path` | string | `static/seed_relays.txt` | Path to seed relay URLs file |
| `seed.to_validate` | bool | `true` | Insert as candidates (true) or directly as relays (false) |

!!! tip "API Reference"
    See [`bigbrotr.services.seeder`](../reference/services/seeder.md) for the complete Seeder API.

---

## Finder

**Purpose**: Discover new relay URLs from stored Nostr events and external HTTP APIs.

**Mode**: Continuous (`run_forever`, default interval 1 hour)

**Reads**: `event` (stored Nostr events), external HTTP APIs
**Writes**: `service_state` (candidates)

### How It Works

```mermaid
flowchart TD
    A["Finder.run()"] --> B["_find_from_events()"]
    A --> C["_find_from_api()"]

    B --> D["Scan kind 3<br/><small>contact lists</small>"]
    B --> E["Scan kind 10002<br/><small>NIP-65 relay lists</small>"]
    B --> F["Scan r tags<br/><small>relay references</small>"]

    C --> G["HTTP GET<br/><small>nostr.watch API</small>"]
    C --> H["HTTP GET<br/><small>custom sources</small>"]

    D --> I["Collect URLs"]
    E --> I
    F --> I
    G --> I
    H --> I

    I --> J["filter_new_relay_urls()"]
    J --> K["upsert_candidates()"]

    style A fill:#7B1FA2,color:#fff,stroke:#4A148C
    style K fill:#311B92,color:#fff,stroke:#1A237E
```

**Discovery sources:**

1. **Event scanning** -- extracts relay URLs from:
    - Kind 3 (contact list): content field contains JSON with relay URLs as keys
    - Kind 10002 (NIP-65 relay list): `r` tags contain relay URLs
    - Any event with `r` tags

2. **API fetching** -- HTTP requests to external sources:
    - Default: nostr.watch online/offline relay list endpoints
    - Configurable timeout, SSL verification, delay between requests

### Configuration

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `interval` | float | `3600.0` | Seconds between discovery cycles |
| `concurrency.max_parallel` | int | `5` | Concurrent API requests |
| `events.enabled` | bool | `true` | Enable event-based relay discovery |
| `events.batch_size` | int | `1000` | Events per scanning batch |
| `events.kinds` | list[int] | `[2, 3, 10002]` | Nostr event kinds to scan |
| `api.enabled` | bool | `true` | Enable API-based discovery |
| `api.sources[].url` | string | -- | API endpoint URL |
| `api.delay_between_requests` | float | `1.0` | Delay between API calls |

!!! tip "API Reference"
    See [`bigbrotr.services.finder`](../reference/services/finder.md) for the complete Finder API.

---

## Validator

**Purpose**: Test candidate relay URLs via WebSocket and promote valid ones to the relay table.

**Mode**: Continuous (`run_forever`, default interval 8 hours)

**Reads**: `service_state` (candidates)
**Writes**: `relay` (promoted valid relays), `service_state` (updated failure counts)

### How It Works

```mermaid
flowchart TD
    A["Validator.run()"] --> B["delete_stale_candidates()"]
    B --> C["delete_exhausted_candidates()"]
    C --> D["fetch_candidate_chunk()"]
    D --> E{Candidates?}
    E -->|No| F["Cycle complete"]
    E -->|Yes| G["Validate in parallel<br/><small>per-network semaphores</small>"]
    G --> H["is_nostr_relay()<br/><small>WebSocket test</small>"]
    H --> I{Valid?}
    I -->|Yes| J["promote_candidates()"]
    I -->|No| K["Increment failure count"]
    J --> D
    K --> D

    style A fill:#7B1FA2,color:#fff,stroke:#4A148C
    style J fill:#1B5E20,color:#fff,stroke:#0D3B0F
    style K fill:#B71C1C,color:#fff,stroke:#7F0000
```

1. Delete stale candidates (URLs already in the relay table)
2. Delete exhausted candidates (exceeded `max_failures` threshold)
3. Fetch a chunk of candidates ordered by failure count (ASC) then age (ASC)
4. Validate in parallel with per-network semaphores via `is_nostr_relay(relay, timeout, proxy_url)`
5. Promote valid candidates to the relay table; increment failure count for invalid ones
6. Repeat until all candidates are processed

!!! note
    The Validator uses `is_nostr_relay()` which performs a WebSocket handshake and checks for a valid Nostr protocol response. It does not verify event storage or relay policies.

### Configuration

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `interval` | float | `28800.0` | Seconds between validation cycles |
| `processing.chunk_size` | int | `100` | Candidates per fetch batch |
| `processing.max_candidates` | int or null | `null` | Max candidates per cycle |
| `cleanup.enabled` | bool | `false` | Enable stale candidate cleanup |
| `cleanup.max_failures` | int | `100` | Failure threshold for removal |
| `networks` | NetworkConfig | -- | Per-network timeouts and concurrency |

!!! tip "API Reference"
    See [`bigbrotr.services.validator`](../reference/services/validator.md) for the complete Validator API.

---

## Monitor

**Purpose**: Perform NIP-11 and NIP-66 health checks on all validated relays and publish results as Nostr events.

**Mode**: Continuous (`run_forever`, default interval 1 hour)

**Reads**: `relay` (validated relays)
**Writes**: `metadata`, `relay_metadata` (health check results); publishes Nostr kind 0, 10166, 30166 events

### How It Works

The Monitor is the most complex service, split across three modules:

| Module | Lines | Responsibility |
|--------|-------|---------------|
| `monitor.py` | ~600 | Config models, health check orchestration, GeoIP, DB persistence |
| `monitor_publisher.py` | ~230 | Nostr event broadcasting: kind 0, 10166, 30166 |
| `monitor_tags.py` | ~280 | NIP-66 tag building for kind 30166 events |

**Orchestration flow:**

1. `run()` -- fetch relays due for check, chunk them
2. `_check_chunk(relays)` -- parallel checks with semaphore
3. `_check_one(relay)` -- run NIP-11 + all NIP-66 checks, return `CheckResult`
4. `_persist_results(successful, failed)` -- insert metadata to DB
5. `_publish_relay_discoveries(successful)` -- build and broadcast kind 30166 events
6. `_publish_announcement()` -- kind 10166 (monitor capabilities)
7. `_publish_profile()` -- kind 0 (monitor profile metadata)

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

**Published Nostr events:**

| Kind | Type | Content |
|------|------|---------|
| 0 | Profile | Monitor name, about, picture (NIP-01) |
| 10166 | Announcement | Monitor capabilities, check frequency, supported checks (NIP-66) |
| 30166 | Discovery | Per-relay health data: RTT, SSL, DNS, Geo, Net, NIP-11 (addressable, `d` tag = relay URL) |

**NIP-66 tags produced by `monitor_tags.py`:**

| Method | Tags Produced |
|--------|--------------|
| `_add_rtt_tags()` | `rtt-open`, `rtt-read`, `rtt-write` |
| `_add_ssl_tags()` | `ssl`, `ssl-expires`, `ssl-issuer` |
| `_add_net_tags()` | `net-ip`, `net-ipv6`, `net-asn`, `net-asn-org` |
| `_add_geo_tags()` | `g` (geohash), `geo-country`, `geo-city`, `geo-lat`, `geo-lon`, `geo-tz` |
| `_add_nip11_tags()` | `N` (NIPs), `t` (topics), `l` (languages), `R` (requirements), `T` (types) |

### Configuration

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `interval` | float | `3600.0` | Seconds between check cycles |
| `processing.chunk_size` | int | `100` | Relays per batch |
| `processing.max_relays` | int or null | `null` | Max relays per cycle |
| `processing.compute.*` | bool | `true` | Enable computation per metadata type |
| `processing.store.*` | bool | `true` | Enable persistence per metadata type |
| `discovery.enabled` | bool | `true` | Publish kind 30166 events |
| `announcement.enabled` | bool | `true` | Publish kind 10166 events |
| `networks` | NetworkConfig | -- | Per-network timeouts and concurrency |

!!! warning
    The Monitor requires the `PRIVATE_KEY` environment variable for signing published Nostr events and performing NIP-66 write tests.

!!! tip "API Reference"
    See [`bigbrotr.services.monitor`](../reference/services/monitor.md) for the complete Monitor API.

---

## Synchronizer

**Purpose**: Connect to relays, subscribe to events, and archive them to PostgreSQL.

**Mode**: Continuous (`run_forever`, default interval 15 minutes)

**Reads**: `relay` (validated relays), `service_state` (cursors)
**Writes**: `event`, `event_relay` (archived events and junctions), `service_state` (updated cursors)

### How It Works

```mermaid
flowchart TD
    A["Synchronizer.run()"] --> B["Fetch relays from DB"]
    B --> C["Load cursors from service_state"]
    C --> D["_sync_all_relays(relays)<br/><small>TaskGroup + semaphore</small>"]
    D --> E["Per relay:"]
    E --> F["Connect via WebSocket"]
    F --> G["Subscribe with filter<br/><small>kinds, since, until, limit</small>"]
    G --> H["Collect events into EventBatch"]
    H --> I{Batch full?}
    I -->|Yes| J["insert_event_relay<br/>(cascade=True)"]
    I -->|No| K{EOSE received?}
    K -->|Yes| J
    K -->|No| H
    J --> L["Update cursor"]
    L --> M{More events?}
    M -->|Yes| G
    M -->|No| N["Next relay"]

    style A fill:#7B1FA2,color:#fff,stroke:#4A148C
    style J fill:#311B92,color:#fff,stroke:#1A237E
```

1. `run()` -- fetch relays from DB, load cursors, distribute work
2. `_sync_all_relays(relays)` -- `TaskGroup` with semaphore coordination
3. For each relay: connect via WebSocket, subscribe with filter, collect events
4. Per-relay cursor tracking via `ServiceState` with `StateType.CURSOR`
5. Batch insert events + relay junctions via `insert_event_relay(cascade=True)`
6. Flush cursor updates periodically

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

### Configuration

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `interval` | float | `900.0` | Seconds between sync cycles |
| `filter.kinds` | list[int] or null | `null` | Event kinds to sync (null = all) |
| `filter.limit` | int | `500` | Events per REQ request |
| `time_range.use_relay_state` | bool | `true` | Use per-relay incremental cursors |
| `time_range.lookback_seconds` | int | `86400` | Lookback window from cursor position |
| `concurrency.max_parallel` | int | `10` | Concurrent relays |
| `concurrency.stagger_delay` | list[int] | `[0, 60]` | Random delay range [min, max] seconds |
| `source.require_readable` | bool | `true` | Only sync relays with successful read test |
| `networks` | NetworkConfig | -- | Per-network timeouts and concurrency |

!!! tip "API Reference"
    See [`bigbrotr.services.synchronizer`](../reference/services/synchronizer.md) for the complete Synchronizer API.

---

## Service Lifecycle

All services share a common lifecycle managed by `BaseService`:

```mermaid
statediagram-v2
    [*] --> Created: __init__()
    Created --> Running: __aenter__()
    Running --> Cycling: run_forever()

    state Cycling {
        [*] --> RunCycle: run()
        RunCycle --> WaitInterval: wait(interval)
        WaitInterval --> RunCycle: interval elapsed
        WaitInterval --> [*]: shutdown requested
        RunCycle --> FailureTracking: exception
        FailureTracking --> WaitInterval: consecutive < max
        FailureTracking --> [*]: consecutive >= max
    }

    Cycling --> Cleanup: __aexit__()
    Cleanup --> [*]
```

### run() vs run_forever()

| Method | Behavior | Use Case |
|--------|----------|----------|
| `run()` | Execute a single cycle, return | Testing, one-shot (`--once` flag) |
| `run_forever()` | Loop: `run()` -> `wait(interval)` -> repeat | Production continuous operation |

### Failure Handling

- Each service tracks consecutive failures
- After `max_consecutive_failures` (default 5), the service stops
- Set `max_consecutive_failures: 0` to disable the limit (never auto-stop)
- A successful cycle resets the consecutive failure counter

### Graceful Shutdown

- `SIGTERM` or `SIGINT` triggers `request_shutdown()`
- The current cycle completes before exiting
- `wait()` is interruptible -- no waiting for the full interval
- `stop_grace_period: 60s` in Docker Compose ensures time for cleanup

---

## Configuration Reference

For complete configuration details including all fields, defaults, constraints, and YAML examples, see the [Configuration](configuration.md) reference. Key tuning parameters per service:

| Service | Key Config | Impact |
|---------|-----------|--------|
| Seeder | `seed.to_validate` | Skip validation for trusted seed lists |
| Finder | `events.kinds`, `api.sources` | Control discovery breadth |
| Validator | `processing.chunk_size`, `cleanup.max_failures` | Throughput vs resource usage |
| Monitor | `processing.compute.*`, `discovery.enabled` | Which checks to run and publish |
| Synchronizer | `concurrency.max_parallel`, `filter.kinds` | Archival throughput and scope |

---

## Related Documentation

- [Architecture](architecture.md) -- Diamond DAG layer structure and design patterns
- [Configuration](configuration.md) -- Complete YAML configuration reference
- [Database](database.md) -- PostgreSQL schema and stored functions
- [Monitoring](monitoring.md) -- Prometheus metrics, alerting, and dashboards
