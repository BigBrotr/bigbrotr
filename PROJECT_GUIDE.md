# BigBrotr Project Guide

This guide is the root-level, implementation-aligned overview of BigBrotr for
the current `feat/nip85-incremental-matviews-assertor` branch.

It replaces the older root-level codebase and project specification documents.
If this guide ever disagrees with the code, the code is the source of truth.
The most reliable implementation entry points are:

- `src/bigbrotr/__main__.py`
- `src/bigbrotr/models/constants.py`
- `src/bigbrotr/services/`
- `tools/templates/sql/`
- `deployments/bigbrotr/`
- `deployments/lilbrotr/`
- `tests/`

---

## 1. What BigBrotr Is

BigBrotr is a modular Nostr network observatory.

It discovers relays, validates them, monitors their health, archives events,
derives analytics facts, computes NIP-85 rank snapshots, publishes NIP-85
trusted assertions, and exposes the collected data through REST and Nostr.

The system is built around these principles:

- independent async services
- PostgreSQL as the canonical shared store
- generated SQL init scripts from Jinja templates
- typed Pydantic configuration
- frozen validated domain models
- explicit per-service metrics
- Docker Compose deployments for BigBrotr and LilBrotr
- extensive unit and integration test coverage

BigBrotr answers four operational questions:

| Question | Main Services | Main Output |
|----------|---------------|-------------|
| What relays exist? | Seeder, Finder, Validator | Validated relay registry |
| How healthy are relays? | Monitor | NIP-11/NIP-66 metadata and signed NIP-66 events |
| What events are relays publishing? | Synchronizer | Event archive with relay attribution |
| What NIP-85 facts and ranks can be published? | Refresher, Ranker, Assertor | NIP-85 facts, ranks, and trusted assertions |

---

## 2. Runtime Topology

The runtime currently exposes 10 built-in services through the registry in
`src/bigbrotr/services/registry.py`:

| Service | Purpose | External I/O |
|---------|---------|--------------|
| `seeder` | Bootstrap relay URLs from seed files | local seed file |
| `finder` | Discover relay URLs from APIs and archived events | HTTP APIs, PostgreSQL |
| `validator` | Validate relay candidates via Nostr WebSocket handshake | WebSocket |
| `monitor` | Run NIP-11 and NIP-66 health checks, publish monitor events | HTTP, WebSocket, DNS, SSL, GeoIP |
| `synchronizer` | Archive events from validated relays with cursor resumption | WebSocket |
| `refresher` | Maintain current-state tables, analytics tables, and NIP-85 facts | PostgreSQL |
| `ranker` | Compute NIP-85 rank snapshots in private DuckDB and export them | PostgreSQL, DuckDB |
| `api` | Expose registered read-only read models over HTTP | FastAPI/HTTP |
| `dvm` | Serve registered read-only read models through NIP-90 | WebSocket/Nostr |
| `assertor` | Publish NIP-85 trusted assertion events | WebSocket/Nostr |

All services communicate through PostgreSQL. There is no direct service-to-
service RPC. A service can be stopped without crashing the others; downstream
services simply observe stale or missing data until upstream producers resume.

The high-level flow is:

```text
seed file -> Seeder -> service_state candidates
external APIs/events -> Finder -> service_state candidates
service_state candidates -> Validator -> relay
relay -> Monitor -> metadata + relay_metadata + NIP-66 events
relay -> Synchronizer -> event + event_relay
event/metadata/relay state -> Refresher -> current + analytics + NIP-85 fact tables
current + NIP-85 facts -> Ranker -> NIP-85 rank tables
NIP-85 facts + ranks -> Assertor -> NIP-85 assertion events
registered read models -> Api/Dvm -> user-facing query surfaces
```

---

## 3. Import Architecture

The codebase follows a diamond-shaped import DAG:

```text
              services
             /   |   \
          core  nips  utils
             \   |   /
              models
```

Package responsibilities:

| Package | Responsibility |
|---------|----------------|
| `models` | Pure domain models and enums: relay, event, metadata, service state, constants |
| `core` | Brotr DB facade, async pool, base service lifecycle, config loading, logging, metrics |
| `nips` | NIP-specific protocol models and event builders |
| `utils` | Transport, streaming, DNS, keys, protocol helpers, bounded HTTP |
| `services` | Business orchestration, service configs, service queries, service utilities |

Rules:

- `models` stays pure and does not import BigBrotr runtime layers.
- `services` can use lower layers but services do not import each other.
- protocol I/O stays in `nips` and `utils`.
- database orchestration stays in `core` and service query modules.
- each service folder uses only `configs.py`, `queries.py`, `service.py`, and `utils.py`
  when local helper code is needed.

---

## 4. Core Runtime

The CLI entry point is `src/bigbrotr/__main__.py`.

The default invocation shape is:

```bash
python -m bigbrotr <service> --profile <bigbrotr|lilbrotr>
python -m bigbrotr <service> --config <service-config.yaml> --brotr-config <brotr.yaml>
```

Important runtime components:

| Component | Location | Role |
|-----------|----------|------|
| `SERVICE_REGISTRY` | `src/bigbrotr/services/registry.py` | maps built-in service names to classes and default config paths |
| `Brotr` | `src/bigbrotr/core/brotr.py` | high-level database facade over stored functions and queries |
| `BaseService` | `src/bigbrotr/core/base_service.py` | async lifecycle, `run_forever`, metrics, shutdown handling |
| `Logger` | `src/bigbrotr/core/logger.py` | structured log formatting |
| `MetricsServer` | `src/bigbrotr/core/metrics.py` | Prometheus metrics endpoint |
| YAML config loader | `src/bigbrotr/core/yaml.py` | config loading and validation |

`BaseService` provides:

- `__aenter__` and `__aexit__` lifecycle hooks
- `run()` as the single-cycle service entrypoint
- `run_forever()` as the continuous loop
- `cleanup()` hook
- cycle duration metrics
- failure accounting
- graceful shutdown on signals

---

## 5. Domain Model

The model layer contains validated immutable data structures used at the
database and protocol boundaries.

Important model concepts:

| Concept | File | Notes |
|---------|------|-------|
| `Relay` | `src/bigbrotr/models/relay.py` | validates relay URL shape and network type |
| `Event` | `src/bigbrotr/models/event.py` | wraps Nostr event fields for DB persistence |
| `EventRelay` | `src/bigbrotr/models/event_relay.py` | junction row between event and relay |
| `Metadata` | `src/bigbrotr/models/metadata.py` | content-addressed metadata document |
| `RelayMetadata` | `src/bigbrotr/models/relay_metadata.py` | time-series relay metadata reference |
| `ServiceState` | `src/bigbrotr/models/service_state.py` | generic checkpoint/cursor state |
| `ServiceName` | `src/bigbrotr/models/constants.py` | canonical service identifiers |
| `EventKind` | `src/bigbrotr/models/constants.py` | NIP event kinds used by services |

Network classification:

| Network | Host shape | Scheme expectation |
|---------|------------|--------------------|
| `clearnet` | public DNS/IP | `wss://` |
| `tor` | `.onion` | `ws://` through Tor proxy |
| `i2p` | `.i2p` | `ws://` through I2P proxy |
| `loki` | `.loki` | `ws://` through Lokinet proxy |

Local/private and unknown addresses are rejected during `Relay` construction.

---

## 6. Database Architecture

PostgreSQL 18 is the canonical store.

The schema is generated from Jinja templates in `tools/templates/sql/` into
deployment-specific init scripts under:

- `deployments/bigbrotr/postgres/init/`
- `deployments/lilbrotr/postgres/init/`

Base SQL templates:

| File | Purpose |
|------|---------|
| `00_extensions.sql.j2` | PostgreSQL extensions |
| `01_functions_utility.sql.j2` | tag extraction, address utilities, Bolt11 amount helper |
| `02_tables_core.sql.j2` | core relay/event/metadata/service_state tables |
| `03_tables_current.sql.j2` | current-state tables |
| `04_tables_analytics.sql.j2` | analytics and NIP-85 fact/rank tables |
| `05_functions_crud.sql.j2` | CRUD, cascade, service_state functions |
| `06_functions_cleanup.sql.j2` | orphan cleanup functions |
| `07_views_reporting.sql.j2` | reporting views |
| `08_functions_refresh_current.sql.j2` | current-state refresh functions |
| `09_functions_refresh_analytics.sql.j2` | analytics and NIP-85 refresh functions |
| `10_indexes_core.sql.j2` | core table indexes |
| `11_indexes_current.sql.j2` | current-state indexes |
| `12_indexes_analytics.sql.j2` | analytics and rank indexes |
| `99_verify.sql.j2` | init-time verification output |

LilBrotr overrides:

- `tools/templates/sql/lilbrotr/02_tables_core.sql.j2`
- `tools/templates/sql/lilbrotr/05_functions_crud.sql.j2`
- `tools/templates/sql/lilbrotr/99_verify.sql.j2`

### Core Tables

| Table | Purpose |
|-------|---------|
| `relay` | validated relay registry |
| `event` | archived Nostr events |
| `event_relay` | first-seen relay attribution for events |
| `metadata` | content-addressed NIP-11/NIP-66 metadata |
| `relay_metadata` | time-series relay metadata snapshots |
| `service_state` | per-service cursors/checkpoints |

### Summary Tables

| Table | Purpose |
|-------|---------|
| `pubkey_kind_stats` | per-author, per-kind event counts |
| `pubkey_relay_stats` | per-author, per-relay activity |
| `relay_kind_stats` | per-relay, per-kind event counts |
| `pubkey_stats` | global author activity |
| `kind_stats` | global kind distribution |
| `relay_stats` | relay event and metadata-derived stats |

### Current-State Tables

| Table | Purpose |
|-------|---------|
| `relay_metadata_current` | latest metadata per relay and metadata type |
| `events_replaceable_current` | latest replaceable event per pubkey and kind |
| `events_addressable_current` | latest addressable event per pubkey, kind, and d tag |
| `contact_lists_current` | latest kind 3 contact list source per follower |
| `contact_list_edges_current` | canonical follow graph edges |

### NIP-85 Fact Tables

| Table | Purpose |
|-------|---------|
| `nip85_pubkey_stats` | user assertion facts |
| `nip85_event_stats` | event assertion facts |
| `nip85_addressable_stats` | addressable event assertion facts |
| `nip85_identifier_stats` | NIP-73 identifier assertion facts |

### NIP-85 Rank Tables

| Table | Purpose |
|-------|---------|
| `nip85_pubkey_ranks` | algorithm-scoped user ranks |
| `nip85_event_ranks` | algorithm-scoped event ranks |
| `nip85_addressable_ranks` | algorithm-scoped addressable ranks |
| `nip85_identifier_ranks` | algorithm-scoped identifier ranks |

The refreshed analytics path uses regular tables and checkpointed refresh
functions rather than `REFRESH MATERIALIZED VIEW CONCURRENTLY`.

### Roles

| Role | Used By | Access model |
|------|---------|--------------|
| `admin` | database bootstrap, PGBouncer setup | superuser/bootstrap |
| `writer` | seeder, finder, validator, monitor, synchronizer | core writes and function execution |
| `refresher` | refresher | derived table refreshes and function execution |
| `ranker` | ranker | reads facts/current graph, writes rank snapshots |
| `reader` | api, dvm, postgres-exporter | read-only plus monitoring |

---

## 7. Deployment Variants

BigBrotr and LilBrotr share almost all service code and deployment layout.

| Variant | Event storage | Use case |
|---------|---------------|----------|
| BigBrotr | stores full NIP-01 event payload: tags, content, sig | complete archive and rich analytics |
| LilBrotr | keeps the same columns but leaves tags/content/sig null; stores tagvalues | lighter relay/statistics archive |

The main functional difference is the `event` table definition and
`event_insert()` procedure. Shared analytics try to rely on `id`, `pubkey`,
`created_at`, `kind`, `event_relay.seen_at`, and `tagvalues` so both variants
can use the same service logic.

Each deployment includes:

- PostgreSQL
- PGBouncer
- Tor proxy
- the 10 BigBrotr application services
- postgres-exporter
- Prometheus
- Alertmanager
- Grafana

Optional I2P and Lokinet proxies can be enabled in the compose files and service
network configs.

---

## 8. Service Details

### Seeder

The Seeder bootstraps relay discovery from a static text file.

Mode:

- usually one-shot
- commonly run with `--once`

Reads:

- `static/seed_relays.txt`

Writes:

- `service_state` candidates when `to_validate = true`
- `relay` rows directly when `to_validate = false`

Key behavior:

- parses one relay URL per line
- ignores comments and invalid URLs
- stores candidates for the Validator by default
- can directly seed trusted relays when configured

### Finder

The Finder discovers relay URLs from external APIs and from already archived
Nostr event tag values.

Reads:

- external JSON APIs such as nostr.watch
- `event_relay` and event tag values
- `service_state` finder cursors/checkpoints

Writes:

- `service_state` candidate checkpoints

Key behavior:

- API sources are cooldown-gated
- event scanning is cursor-paginated per relay
- relay URLs are parsed through `Relay` validation
- discovered URLs become Validator candidates
- stale event cursors and API checkpoints are cleaned up

### Validator

The Validator promotes relay candidates into the canonical `relay` table.

Reads:

- `service_state` candidates

Writes:

- `relay`
- `service_state` failure counters/checkpoints

Key behavior:

- validates via WebSocket Nostr protocol handshake
- treats EOSE, AUTH challenge, or auth-required closure as valid protocol behavior
- applies per-network semaphores
- supports SSL fallback if `allow_insecure` is enabled
- deletes promoted candidates
- optionally deletes candidates that exceed `max_failures`

### Monitor

The Monitor observes relay health and publishes NIP-66 events.

Reads:

- `relay`
- `service_state` publish/check checkpoints

Writes:

- `metadata`
- `relay_metadata`
- `service_state`
- Nostr events kind `0`, `10166`, `30166`

Checks:

- NIP-11 info
- RTT open/read/write
- SSL certificate metadata
- DNS records
- GeoIP city metadata
- ASN/network metadata
- HTTP/WebSocket response headers

Key behavior:

- updates GeoLite2 databases when configured
- publishes profile and monitor announcement on their own cadence
- monitors relays in chunks with per-network concurrency
- stores metadata as content-addressed documents
- publishes relay discovery events through configured relays

### Synchronizer

The Synchronizer archives events from validated relays.

Reads:

- `relay`
- per-relay sync cursors in `service_state`

Writes:

- `event`
- `event_relay`
- `service_state` cursors

Key behavior:

- shuffles relays to avoid thundering-herd ordering
- computes `[cursor + 1, now - end_lag]` sync windows
- connects through the appropriate transport/proxy
- streams events with binary-split windowing
- enforces filtered, verified, deduplicated, and limited event guarantees
- inserts through cascade functions
- flushes cursors in batches

### Refresher

The Refresher is the facts layer for downstream analytics and NIP-85.

Reads:

- core event and metadata tables
- current-state dependencies
- service checkpoints

Writes:

- summary tables
- current-state tables
- NIP-85 fact tables
- service checkpoints

Target groups:

- `current.targets`
- `analytics.targets`
- `periodic` reconciliation tasks

Key behavior:

- normalizes configured targets into dependency-safe order
- runs checkpointed `(after, until)` refresh ranges
- isolates target failures when configured
- emits per-target and aggregate metrics
- performs periodic rolling window, relay metadata, and NIP-85 follower refreshes
- cleans stale checkpoints for removed targets

### Ranker

The Ranker computes deterministic rank snapshots for NIP-85.

Reads:

- `contact_lists_current`
- `contact_list_edges_current`
- `nip85_event_stats`
- `nip85_addressable_stats`
- `nip85_identifier_stats`

Writes:

- `nip85_pubkey_ranks`
- `nip85_event_ranks`
- `nip85_addressable_ranks`
- `nip85_identifier_ranks`
- private DuckDB state
- local checkpoint JSON

Key behavior:

- syncs canonical follow graph data from PostgreSQL into DuckDB
- computes PageRank for pubkeys under `algorithm_id`
- stages non-user fact rows for events, addressables, and identifiers
- computes deterministic normalized ranks
- exports rank snapshots back to PostgreSQL in bounded batches
- supports cycle duration and row budget controls

### Assertor

The Assertor publishes NIP-85 trusted assertion events.

Reads:

- NIP-85 fact tables
- NIP-85 rank tables
- `pubkey_stats`
- assertor checkpoints in `service_state`

Writes:

- Nostr assertion events: `30382`, `30383`, `30384`, `30385`
- optional provider profile kind `0`
- assertor checkpoints in `service_state`

Key behavior:

- signs with the configured assertor service key
- uses `algorithm_id` to join and namespace ranks/checkpoints
- builds assertion events with `d` tag pointing to the subject
- includes NIP-85 tags for users, events, addressables, and NIP-73 identifiers
- publishes only changed assertions using a tag hash checkpoint
- uses canonical checkpoint keys: `<algorithm_id>:<kind>:<subject_id>`
- removes stale or non-canonical checkpoints after a cycle

NIP-85 kind mapping:

| Subject | Kind | Subject field |
|---------|------|---------------|
| user | `30382` | pubkey |
| event | `30383` | event id |
| addressable event | `30384` | event address |
| NIP-73 identifier | `30385` | identifier |

NIP-85 kind `10040` provider declarations are modeled in the NIP helper layer,
but the Assertor does not publish them as part of its provider flow. They are
user/client authorization events.

### Api

The Api service exposes a read-only REST interface.

Reads:

- enabled catalog tables and views

Writes:

- no domain writes

Key behavior:

- discovers schema through `CatalogAccessMixin`
- builds FastAPI routes dynamically
- supports pagination, filters, sorting, and PK lookups
- validates all table and column names against the catalog
- maps catalog errors to client-safe HTTP responses

### Dvm

The Dvm service exposes read-only database queries over NIP-90.

Reads:

- enabled catalog tables and views
- Nostr job request events

Writes:

- Nostr result and status events
- local in-memory dedup state

Key behavior:

- publishes NIP-89 handler metadata
- listens for kind `5050` job requests
- validates table access through the catalog
- supports pricing/bid checks
- publishes kind `6050` results or kind `7000` status/error events

---

## 9. NIP Implementations

BigBrotr currently implements these NIP surfaces:

| NIP | Implementation |
|-----|----------------|
| NIP-01 | event model, signatures via nostr-sdk, kind ranges |
| NIP-02 | contact list facts and follow graph extraction |
| NIP-11 | relay info document fetch and parse |
| NIP-42 | AUTH challenge support in client connections |
| NIP-44 | supported as encrypted content input for trusted provider declarations, when caller supplies ciphertext |
| NIP-65 | relay list event builder |
| NIP-66 | monitor announcement and relay discovery events |
| NIP-73 | identifier assertion support via `i`/`k` tag facts |
| NIP-85 | trusted assertions and provider declaration helpers |
| NIP-89 | DVM handler announcement |
| NIP-90 | DVM request/result/status flow |

Important event kinds:

| Kind | Meaning |
|------|---------|
| `0` | profile metadata |
| `3` | contact list |
| `10002` | relay list metadata |
| `10040` | NIP-85 trusted service provider list |
| `10166` | NIP-66 monitor announcement |
| `22456` | NIP-66 test event |
| `30166` | NIP-66 relay discovery |
| `30382` | NIP-85 user assertion |
| `30383` | NIP-85 event assertion |
| `30384` | NIP-85 addressable event assertion |
| `30385` | NIP-85 NIP-73 identifier assertion |

---

## 10. Configuration And Keys

Configuration is Pydantic-based and loaded from YAML.

Deployment config layout:

```text
deployments/<name>/config/
  brotr.yaml
  services/
    seeder.yaml
    finder.yaml
    validator.yaml
    monitor.yaml
    synchronizer.yaml
    refresher.yaml
    ranker.yaml
    api.yaml
    dvm.yaml
    assertor.yaml
```

Key conventions:

- database passwords are always environment variables
- private Nostr keys are service-specific through `keys.keys_env`
- blank or unset private-key env vars generate one ephemeral key at config creation
- Assertor keys should be stable for production NIP-85 identity
- distinct algorithms or personalized viewpoints should use distinct NIP-85
  service keys

Common env vars:

| Env var | Used by |
|---------|---------|
| `DB_ADMIN_PASSWORD` | PostgreSQL bootstrap/admin |
| `DB_WRITER_PASSWORD` | writer services |
| `DB_READER_PASSWORD` | Api, Dvm, postgres-exporter |
| `DB_REFRESHER_PASSWORD` | Refresher |
| `DB_RANKER_PASSWORD` | Ranker |
| `GRAFANA_PASSWORD` | Grafana admin |
| `NOSTR_PRIVATE_KEY_MONITOR` | Monitor |
| `NOSTR_PRIVATE_KEY_SYNCHRONIZER` | Synchronizer |
| `NOSTR_PRIVATE_KEY_DVM` | Dvm |
| `NOSTR_PRIVATE_KEY_ASSERTOR` | Assertor |

---

## 11. Observability

Each long-running service exposes Prometheus metrics through the shared service
metrics server.

Common metrics include:

- `service_info`
- cycle duration
- cycle success/failure counters
- per-service gauges and counters

The branch includes dedicated Grafana dashboard JSON files for services in both
BigBrotr and LilBrotr deployments. It also includes Prometheus scrape targets
and alert rules for the expanded service set.

Dashboard locations:

```text
deployments/bigbrotr/monitoring/grafana/provisioning/dashboards/
deployments/lilbrotr/monitoring/grafana/provisioning/dashboards/
```

Prometheus locations:

```text
deployments/bigbrotr/monitoring/prometheus/
deployments/lilbrotr/monitoring/prometheus/
```

---

## 12. Testing

The test strategy is layered:

| Area | Purpose |
|------|---------|
| unit tests | service config, service orchestration, helper logic, NIP builders, models, tools |
| integration tests | PostgreSQL schema, derived tables, Refresher, Ranker, Assertor, NIP-85 pipeline |
| docs build | MkDocs strict build |
| pre-commit | formatting, linting, typing, secrets, spelling, SQL lint hooks |
| CI matrix | Python 3.11, 3.12, 3.13, 3.14 |

Important NIP-85 test files:

- `tests/unit/services/test_refresher.py`
- `tests/unit/services/test_ranker.py`
- `tests/unit/services/test_assertor.py`
- `tests/integration/base/test_refresher.py`
- `tests/integration/base/test_ranker.py`
- `tests/integration/base/test_assertor.py`
- `tests/integration/base/test_nip85_pipeline.py`
- `tests/unit/nips/nip85/test_builders.py`
- `tests/unit/nips/nip85/test_data.py`

---

## 13. Operational Order

A fresh deployment normally comes up in this order:

1. PostgreSQL initializes schema and roles.
2. PGBouncer starts after PostgreSQL is healthy.
3. Seeder runs once and exits.
4. Finder discovers relay candidates.
5. Validator promotes candidates to `relay`.
6. Monitor begins health checks and NIP-66 publishing.
7. Synchronizer archives relay events.
8. Refresher derives current-state and analytics facts.
9. Ranker computes and exports NIP-85 rank snapshots.
10. Assertor publishes NIP-85 trusted assertions when facts/ranks change.
11. Api and Dvm serve read-only data.

The services are still independent processes; this is the data-readiness order,
not an RPC dependency chain.

---

## 14. Extension Rules

When adding a service:

1. create `src/bigbrotr/services/<name>/`
2. keep service-local code in `configs.py`, `queries.py`, `service.py`, and
   `utils.py` where needed
3. subclass `BaseService[YourConfig]`
4. set `SERVICE_NAME` and `CONFIG_CLASS`
5. register the service in `src/bigbrotr/services/registry.py`
6. add deployment YAML for BigBrotr and LilBrotr if it runs in containers
7. add metrics and Grafana panels
8. add unit and integration tests

When changing SQL:

1. edit `tools/templates/sql/`
2. generate deployment SQL
3. verify BigBrotr and LilBrotr outputs
4. add or update integration tests
5. keep grants and verification scripts aligned

When changing NIP-85:

1. keep Refresher as the facts layer
2. keep Ranker as the rank snapshot layer
3. keep Assertor as the publish layer
4. keep algorithm identity explicit through `algorithm_id`
5. keep service keys distinct for distinct algorithms or viewpoints
6. publish assertions only when tag content changes

---

## 15. Current Branch Summary

The current branch adds and aligns the full NIP-85 pipeline:

- Refresher current-state and analytics refresh model
- NIP-85 facts for users, events, addressable events, and identifiers
- Ranker service with private DuckDB state
- Assertor service with canonical algorithm-scoped checkpoints
- NIP-85 event builders and data models
- kind `10040` trusted provider declaration helper surface
- service-specific Nostr key config behavior
- BigBrotr and LilBrotr deployment configs for `ranker` and `assertor`
- service dashboards and alerting coverage
- unit and integration tests for Refresher, Ranker, Assertor, and NIP-85

This guide is intentionally branch-aware. Re-check it after rebasing or merging
large changes from `develop`.
