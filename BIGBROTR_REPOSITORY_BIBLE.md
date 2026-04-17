# BigBrotr Repository Bible

This document is the most detailed repository-wide reference for BigBrotr.

Its job is to be the single long-form document that explains:

- what BigBrotr is trying to do
- what the repository contains
- how the codebase is organized
- how data moves through the system
- what each major package, service, and deployment is responsible for
- which parts of the project are foundational and expensive to change later
- where new services, NIPs, and deployments should plug in

This file is not a changelog and not a short onboarding note. It is a deep map
of the current repository and the current system shape.

If this file and the code ever disagree, the code is the source of truth.

Role and precedence:

- this file is a **current-state repository reference**;
- it is meant to explain the repository as it exists today;
- it is **not** the canonical redesign-target document;
- when redesign execution work needs the final target shape, the canonical
  source is `planning/definitive-redesign/`, especially:
  - `12_best_db_schema.md`
  - `14_core_read_layer_proposal.md`
  - `15_deployment_contract_proposal.md`
  - `16_operational_implementation_plan.md`
  - `99_definitive_master_plan.md`

---

## 1. Project Identity

### 1.1 What BigBrotr is

BigBrotr is a modular Nostr network observatory.

It is not only an event archiver, and it is not only a relay monitor. It is a
composed pipeline that continuously tries to answer four questions:

1. Which relays exist on the Nostr network?
2. Which of those relays are valid, reachable, and healthy?
3. What events are those relays publishing?
4. What derived analytics and NIP-85 trust outputs can be built from those
   observations?

The codebase is organized around those four concerns:

- relay discovery
- relay validation and health monitoring
- event archiving
- derived analytics and trust publication

### 1.2 What BigBrotr is not

BigBrotr is not:

- a generic Nostr client
- a monolithic web backend
- an ORM-driven CRUD app
- a plugin framework with runtime discovery
- a system where services call each other directly

The project is much closer to a service-oriented data platform: multiple async
services, one shared canonical PostgreSQL database, explicit protocol helpers,
and a public read-only surface exposed over HTTP and Nostr.

### 1.3 Core product stance

The project favors:

- explicit contracts
- typed boundaries
- SQL-first persistence
- service independence
- strong validation at model and config boundaries
- operational observability

The project deliberately avoids:

- hidden cross-service coupling
- runtime magic
- schema exposure as a product API
- storing the same concept in many separate service-specific tables unless
  there is a very strong reason

---

## 2. High-Level Mental Model

### 2.1 Runtime topology

BigBrotr runs as ten built-in services:

1. `seeder`
2. `finder`
3. `validator`
4. `monitor`
5. `synchronizer`
6. `refresher`
7. `ranker`
8. `assertor`
9. `api`
10. `dvm`

All ten services share PostgreSQL. They do not call each other directly.

The database is the canonical integration boundary.

### 2.2 The pipeline in one pass

The intended operational flow is:

1. `Seeder` loads an initial relay list from disk.
2. `Finder` expands the candidate set from APIs and archived events.
3. `Validator` tests candidate relays and promotes valid ones into `relay`.
4. `Monitor` runs NIP-11 and NIP-66 checks and stores relay metadata.
5. `Synchronizer` fetches and stores canonical Nostr events from relays.
6. `Refresher` turns append-only core data into current-state and analytics
   tables.
7. `Ranker` imports derived canonical facts into DuckDB, computes NIP-85 rank
   snapshots, and exports them back to PostgreSQL.
8. `Assertor` publishes NIP-85 assertions using those facts and snapshots.
9. `Api` exposes selected read models over HTTP.
10. `Dvm` exposes the same public read-model surface over NIP-90.

### 2.3 Why the pipeline is split this way

The service split reflects different kinds of work:

- discovery work
- validation work
- monitoring work
- ingestion work
- canonical derivation work
- private algorithmic compute work
- public query surface work

This separation keeps responsibilities local and avoids turning one service into
the operational bottleneck for all others.

---

## 3. Top-Level Repository Map

### 3.1 Root files

Important root files:

- `README.md`
  Public-facing summary of the project.
- `PROJECT_GUIDE.md`
  Implementation-aligned repository overview.
- `PROJECT_VISION_AND_REDESIGN_PLAN.md`
  Consolidated architectural vision and redesign intent.
- `pyproject.toml`
  Packaging metadata, dependencies, lint/type/test configuration.
- `uv.lock`
  Locked dependency graph.
- `Makefile`
  Common developer and CI commands.
- `mkdocs.yml`
  MkDocs site configuration.
- `LICENSE`
  Repository license.
- `AGENTS.md`
  Local engineering instructions loaded by the development environment.

### 3.2 Root directories

- `src/`
  Python application code.
- `deployments/`
  Deployment profiles, generated SQL, Docker Compose, monitoring, and runtime
  assets.
- `tools/`
  SQL generation and operational maintenance scripts.
- `tests/`
  Unit and integration verification suites.
- `docs/`
  MkDocs site content.
- `.github/`
  CI, CodeQL, release automation, and repository governance files.

---

## 4. Source Tree Architecture

### 4.1 The diamond DAG

The application code follows a diamond-shaped dependency graph:

```text
              services
             /   |   \
          core  nips  utils
             \   |   /
              models
```

This is the intended import direction:

- `models` is foundational
- `core`, `nips`, and `utils` sit above models
- `services` sits above all of them

### 4.2 Why this shape matters

This shape enforces several important design choices:

- domain types are not polluted by runtime concerns
- protocol parsing does not live inside business services
- transport and Nostr client lifecycle are reusable
- services stay orchestration-focused rather than infrastructural

### 4.3 Package-by-package intent

#### `src/bigbrotr/`

Package root:

- `__init__.py`
  Package export surface and version resolution.
- `__main__.py`
  CLI entrypoint used by `python -m bigbrotr`.
- `py.typed`
  Marks the package as typed.

This folder is thin on purpose. It mostly wires the package together and
delegates to subpackages.

#### `src/bigbrotr/models/`

This is the immutable domain vocabulary shared across the whole codebase.

Files:

- `constants.py`
  Network types, service names, event kinds, and similar shared constants.
- `relay_url.py`
  Relay URL parsing, normalization, and network classification.
- `relay.py`
  Canonical relay entity.
- `event.py`
  Canonical Nostr event wrapper for persistence.
- `event_observation.py`
  Event-observation junction row.
- `metadata.py`
  Content-addressed metadata document model.
- `relay_metadata.py`
  Relay-metadata time-series reference model.
- `service_state.py`
  Shared operational state model.
- `_validation.py`
  Shared validation and normalization helpers.

Design properties:

- all models are immutable dataclasses
- validation happens on construction
- DB parameter tuples are computed once and cached
- models remain free of service logic and I/O

#### `src/bigbrotr/core/`

This is the runtime and database infrastructure layer.

Files:

- `base_service.py`
  Base service contract, lifecycle, and configuration base.
- `service_runtime.py`
  Shared loop runners and CLI service hosting helpers.
- `brotr.py`
  High-level PostgreSQL facade.
- `pool.py`
  Async pool wrapper around asyncpg.
- `pool_config.py`
  Database/pool configuration models.
- `brotr_config.py`
  Batch size and timeout configuration.
- `logger.py`
  Structured logging.
- `metrics.py`
  Prometheus metrics server and helpers.
- `yaml.py`
  YAML loading and validation helpers.

This package is one of the most foundational in the repo. Changes here tend to
affect every service.

#### `src/bigbrotr/nips/`

This layer contains protocol-specific knowledge.

Files:

- `base.py`
  Shared Pydantic bases for NIP payloads and logs.
- `parsing.py`
  Strict parsing helpers.
- `event_builders.py`
  Shared event builder helpers for monitor/assertor-style publication.
- `registry.py`
  Static registry of built-in NIP capability bundles.

Subpackages:

- `nip11/`
  Relay information fetch and normalization.
- `nip66/`
  Health checks and metadata extraction.
- `nip85/`
  Typed rank and assertion payloads.

The `nips` package is a protocol/domain layer, not a plugin framework.

#### `src/bigbrotr/utils/`

This package contains lower-level reusable helpers.

Files:

- `dns.py`
  Async hostname resolution.
- `http.py`
  Bounded HTTP reads and download helpers.
- `keys.py`
  Environment-based Nostr key loading.
- `transport.py`
  Transport overrides and `nostr-sdk` stderr handling.
- `streaming.py`
  Event streaming algorithm.
- `protocol.py`
  Public facade for shared Nostr client lifecycle helpers.
- `protocol_factory.py`
  Nostr client construction.
- `protocol_connections.py`
  Relay connection logic and SSL fallback.
- `protocol_lifecycle.py`
  Client cleanup and shutdown helpers.
- `protocol_manager.py`
  Shared `NostrClientManager`.
- `protocol_publish.py`
  Relay publish result normalization and helpers.
- `protocol_sessions.py`
  Session types and helpers for multi-relay access.
- `protocol_validation.py`
  Relay validation workflow.

The `protocol*` cluster is especially important. It keeps `nostr-sdk` session
management and relay interaction patterns out of individual services.

#### `src/bigbrotr/services/`

This is the orchestration layer.

Top-level files:

- `registry.py`
  Built-in service registry used by the CLI and deployments.
- `__init__.py`
  Export surface.

Subpackages:

- `common/`
- `seeder/`
- `finder/`
- `validator/`
- `monitor/`
- `synchronizer/`
- `refresher/`
- `ranker/`
- `assertor/`
- `api/`
- `dvm/`

This is where business behavior lives.

---

## 5. Service Layer in Detail

### 5.1 `services/common/`

This is the shared service-layer foundation.

Files and responsibilities:

- `configs.py`
  Shared Pydantic models for network config, Nostr key config, public read-model
  policies, and common knobs reused across services.
- `mixins.py`
  Shared concurrency and network helpers, including bounded concurrent
  iteration.
- `types.py`
  Shared dataclasses for checkpoints, cursors, and service-layer state shapes.
- `state_store.py`
  Typed boundary over `service_state`.
- `utils.py`
  Small shared helpers, including insert batching and relay parsing.
- `paging.py`
  Shared keyset-pagination helpers.
- `discovery_queries.py`
  Shared candidate insertion and discovery-oriented query helpers.
- `read_model_registry.py`
  Canonical registry of built-in public read models.
- `read_model_requests.py`
  Request parsing and response metadata helpers for API and DVM.
- `read_models.py`
  Runtime wrapper that resolves enabled public read models against the catalog.
- `catalog.py`
  Safe read-only query surface.
- `catalog_types.py`
  Schema and query result types used by the catalog.
- `catalog_discovery.py`
  Introspection over tables, views, columns, and keys.
- `catalog_planner.py`
  Filter parsing, sort planning, cursor encoding, and read-model SQL planning.
- `catalog_execution.py`
  Query execution helpers.

This folder is one of the most strategic folders in the repository because it
defines:

- how services persist operational state
- how public read models are declared and exposed
- how query surfaces discover schema and run safe read-only queries
- how several services reuse the same pagination and insertion patterns

### 5.2 `services/seeder/`

Purpose:

- bootstrap a deployment from a seed relay file

Files:

- `configs.py`
  Seed file path and insert policy.
- `queries.py`
  Persistence helpers.
- `utils.py`
  Seed file parsing and relay normalization.
- `service.py`
  One-cycle orchestration.

Core behavior:

- reads relay URLs from a static text file
- normalizes and validates them
- either inserts them as candidates in `service_state`
- or, if configured, inserts them directly into `relay`

Seeder is intentionally simple. It exists to make a brand-new deployment
non-empty.

### 5.3 `services/finder/`

Purpose:

- discover new relay candidates from external APIs and archived events

Files:

- `configs.py`
  API and event-scan settings.
- `queries.py`
  Paged reads and cursor/checkpoint persistence.
- `api_runtime.py`
  API fetch planning, attempts, and persistence.
- `event_runtime.py`
  Archived-event scan planning and persistence.
- `utils.py`
  Relay URL extraction logic.
- `service.py`
  Top-level orchestration.

Core behavior:

- polls external relay-list style APIs
- extracts relay-like URLs from JSON payloads
- scans archived event tag values for relay URLs
- persists candidates into `service_state`

Finder does not insert canonical relays directly. It feeds the validator.

### 5.4 `services/validator/`

Purpose:

- validate candidates and promote good ones into the canonical relay table

Files:

- `configs.py`
  Processing limits, cleanup policy, and network validation settings.
- `queries.py`
  Candidate reads, promotion helpers, cleanup helpers.
- `runtime.py`
  Cycle planning and chunk classification.
- `utils.py`
  Validation wrapper around WebSocket/Nostr relay probing.
- `service.py`
  Main orchestration.

Core behavior:

- reads candidate rows from `service_state`
- validates them with Nostr/WebSocket probing
- promotes valid ones to `relay`
- increments or eventually cleans up invalid candidates

Validator is the boundary between “discovered candidate” and “trusted relay
enough to monitor and synchronize”.

### 5.5 `services/monitor/`

Purpose:

- run relay health and capability checks
- persist structured relay metadata
- optionally publish monitor-side events

Files:

- `configs.py`
  Health checks, geo config, publishing config, discovery config.
- `queries.py`
  Relay selection and metadata/publish persistence helpers.
- `checks.py`
  Check planning and dependency/context builders.
- `processing.py`
  Chunk planning, worker context, and persistence bookkeeping.
- `publishing.py`
  Announcement and discovery publishing helpers.
- `runtime.py`
  Cycle planning and shared resource lifecycle.
- `resources.py`
  Small shared resource holders.
- `geo.py`
  Geo-related helpers around NIP-66 data.
- `utils.py`
  Collection helpers, results, logging-oriented helpers.
- `service.py`
  Main orchestration.

Core behavior:

- selects relays from `relay`
- runs NIP-11 and NIP-66 checks
- produces structured metadata payloads
- inserts into `metadata` and `relay_metadata`
- may publish NIP-66-related events

Monitor is one of the largest services because it coordinates:

- HTTP probing
- DNS probing
- SSL probing
- network probing
- geo enrichment
- metadata persistence
- optional event publication

### 5.6 `services/synchronizer/`

Purpose:

- archive canonical Nostr events from validated relays

Files:

- `configs.py`
  Event filters, timeouts, batching, network settings.
- `queries.py`
  Paged relay selection, cursor persistence, event insert helpers.
- `runtime.py`
  Page planning, worker context, and batch bookkeeping.
- `service.py`
  Main orchestration.

Core behavior:

- selects relays from `relay`
- uses shared protocol/streaming helpers to fetch events
- inserts canonical events and event-observation junctions
- persists cursors for resume

Synchronizer is the append-only ingestion service. It should not own ranking or
private analytics state.

### 5.7 `services/refresher/`

Purpose:

- maintain current-state and analytics tables inside PostgreSQL

Files:

- `configs.py`
  Refresh target selection and cleanup settings.
- `queries.py`
  Refresh target specs and stored procedure helpers.
- `runtime.py`
  Cycle result types and metric emission helpers.
- `service.py`
  Target orchestration.

Core behavior:

- invokes refresh stored procedures
- updates current-state tables
- updates analytics tables
- runs cleanup and periodic refresh work

Refresher is the bridge between append-only canonical data and derived canonical
facts.

### 5.8 `services/ranker/`

Purpose:

- maintain a private compute store for ranking
- compute NIP-85 rank snapshots
- export those snapshots back to PostgreSQL

Files:

- `configs.py`
  DuckDB path, sync, staging, export, cleanup settings.
- `queries.py`
  PostgreSQL reads used to feed ranking.
- `types.py`
  Internal cycle dataclasses.
- `runtime.py`
  Cycle budgeting and metric emission.
- `store_runtime.py`
  DuckDB connection ownership and lifecycle.
- `store_graph.py`
  Follow graph sync, checkpoints, and PageRank.
- `store_non_user.py`
  Staging and ranking for non-user subjects.
- `utils.py`
  Store helpers and run bookkeeping.
- `service.py`
  Top-level orchestration.

Ranker is more than “compute rank”. It is a private ranking pipeline:

1. import canonical facts from PostgreSQL
2. maintain compute-friendly local structures in DuckDB
3. run ranking algorithms
4. export rank snapshots back into PostgreSQL

This is intentionally separate from `Synchronizer` and `Refresher` because the
DuckDB working set and ranking logic are algorithm-specific, not canonical.

### 5.9 `services/assertor/`

Purpose:

- publish NIP-85 trusted assertion events

Files:

- `configs.py`
  Provider profile, publishing, cleanup, and selection config.
- `queries.py`
  Reads for assertion inputs and publish-state tracking.
- `publishing.py`
  Publish planning and relay execution helpers.
- `runtime.py`
  Cycle metrics and result helpers.
- `utils.py`
  State-key logic and content hashing.
- `service.py`
  Main orchestration.

Core behavior:

- reads derived NIP-85 facts and rank snapshots
- builds NIP-85 assertion events
- publishes them to relays
- persists publish progress/state

Assertor is the publishing endpoint of the NIP-85 pipeline.

### 5.10 `services/api/`

Purpose:

- expose the public read-model surface over HTTP

Files:

- `configs.py`
  Host, port, route prefix, CORS, timeouts, read-model policy.
- `read_models.py`
  Per-read-model HTTP handlers.
- `routes.py`
  API route registration.
- `service.py`
  FastAPI application lifecycle and Uvicorn hosting.

Core behavior:

- resolves enabled read models through `services/common`
- registers discovery and data routes
- keeps the surface read-only

The API is a product surface, not a schema browser.

### 5.11 `services/dvm/`

Purpose:

- expose the same public read-model surface over Nostr using NIP-90

Files:

- `configs.py`
  Relay, key, request kind, announcement, pricing, read-model policy.
- `utils.py`
  Request parsing and event builder helpers.
- `jobs.py`
  Job preparation, validation, pricing checks, read-model execution.
- `subscriptions.py`
  Long-lived request subscription state and buffering.
- `publishing.py`
  Announcement publishing and send helpers.
- `service.py`
  Main lifecycle and orchestration.

Core behavior:

- subscribes for NIP-90 requests
- validates and executes jobs against read models
- publishes results or errors
- publishes announcements

The DVM is the Nostr-native twin of the HTTP API.

---

## 6. Public Read Surface

### 6.1 What a read model is

A read model is a named public query surface exposed by:

- the HTTP API
- the DVM

It is defined centrally in `services/common/read_model_registry.py`.

Each read model entry declares:

- `read_model_id`
- `catalog_name`
- allowed public surfaces
- schema resolution logic
- query handler
- primary-key lookup handler

### 6.2 Built-in public read models

Current built-in read models:

- `relays`
- `events`
- `event-observations`
- `metadata-documents`
- `relay-metadata-history`
- `relay-metadata-current`
- `pubkey-stats`
- `kind-stats`
- `relay-stats`
- `pubkey-relay-stats`
- `pubkey-kind-stats`
- `relay-kind-stats`
- `relay-software-counts`
- `supported-nip-counts`
- `daily-counts`
- `replaceable-events-current`
- `addressable-events-current`
- `nip85-pubkey-stats`
- `nip85-event-stats`
- `nip85-addressable-stats`
- `nip85-identifier-stats`

Important design point:

- internal tables exist in the schema
- public read models are the named product surface
- not every internal table is automatically public

### 6.3 Catalog relationship

Today the read-model surface is catalog-backed:

- the catalog discovers schema
- the planner builds safe read-only queries
- the registry maps public names to catalog-backed sources

This keeps public exposure controlled while still reusing a generic read-only
query engine.

---

## 7. Domain Model and Vocabulary

### 7.1 Core entities

The core domain revolves around these concepts:

- `Relay`
  A validated Nostr relay URL plus network classification.
- `Event`
  A canonical Nostr event persisted in PostgreSQL.
- `EventObservation`
  An observation that a given relay served a given event at a specific time.
- `Metadata`
  A content-addressed metadata document.
- `RelayMetadata`
  A time-series reference from relay to metadata snapshot.
- `ServiceState`
  Persisted operational state used by services for checkpoints and cursors.

### 7.2 Important enums and built-ins

`models/constants.py` defines key shared built-ins:

- `NetworkType`
  `clearnet`, `tor`, `i2p`, `loki`, `local`, `unknown`
- `ServiceName`
  `seeder`, `finder`, `validator`, `monitor`, `synchronizer`, `refresher`,
  `ranker`, `api`, `dvm`, `assertor`
- `EventKind`
  Includes kind `0`, `2`, `3`, `10002`, `10040`, `22456`, `10166`, `30166`,
  `30382`, `30383`, `30384`, `30385`

### 7.3 Relay network classification

Relays are classified by host shape:

- clearnet
- Tor (`.onion`)
- I2P (`.i2p`)
- Lokinet (`.loki`)

Local and unknown hosts are rejected during relay validation.

### 7.4 Model discipline

Models follow strict rules:

- immutable dataclasses
- validation in `__post_init__`
- cached DB parameter tuples
- no service or protocol behavior in the model layer

This keeps the domain layer deterministic and safe to reuse everywhere.

---

## 8. Database Architecture

### 8.1 The database as canonical substrate

PostgreSQL is the canonical shared store.

It is not only a place where rows are stored. It is:

- the coordination boundary between services
- the canonical history store
- the place where derived canonical tables are maintained
- the backing store for public read models

### 8.2 Schema layers

The schema can be understood in four conceptual layers.

#### Core archive tables

- `relay`
- `event`
- `event_observation`
- `metadata`
- `relay_metadata`
- `service_state`

These are the core persisted facts and operational state.

#### Current-state tables

- `relay_metadata_current`
- `events_replaceable_current`
- `events_addressable_current`
- `contact_lists_current`
- `contact_list_edges_current`

These tables collapse append-only history into “current winner” style views
maintained by refresh procedures.

#### Analytics tables

- `pubkey_kind_stats`
- `pubkey_relay_stats`
- `relay_kind_stats`
- `pubkey_stats`
- `kind_stats`
- `relay_stats`
- `daily_counts`
- `relay_software_counts`
- `supported_nip_counts`

These provide aggregate analytics over the canonical archive.

#### NIP-85 fact and rank tables

Fact tables:

- `nip85_pubkey_stats`
- `nip85_event_stats`
- `nip85_addressable_stats`
- `nip85_identifier_stats`

Rank tables:

- `nip85_pubkey_ranks`
- `nip85_event_ranks`
- `nip85_addressable_ranks`
- `nip85_identifier_ranks`

Facts are canonical derived inputs. Rank snapshots are exported outputs from
the ranker’s private compute pipeline.

### 8.3 Core table roles

#### `relay`

Canonical validated relay registry.

#### `event`

Canonical event archive.

In BigBrotr, full event content is stored.
In LilBrotr, `tags`, `content`, and `sig` exist but are always `NULL`; only the
lightweight shape is retained to save storage.

#### `event_observation`

Records which relay served which event and when it was first seen there.

#### `metadata`

Content-addressed metadata document store keyed by content hash plus metadata
type.

This allows multiple relays with identical metadata payloads to share one row.

#### `relay_metadata`

Time-series link between relays and generated metadata snapshots.

#### `service_state`

Shared operational persistence for services.

This table is used for:

- checkpoints
- cursors
- candidate state
- publish state
- incremental resume boundaries

The project has intentionally kept a shared state table instead of a forest of
small service-specific state tables.

### 8.4 Why `service_state` matters

`service_state` is an important design choice:

- it avoids schema explosion for operational state
- it allows shared typed patterns in code
- it makes service restart/resume behavior persistent

The `StateStore` in `services/common/state_store.py` provides the typed
application boundary around this table so that services do not directly juggle
raw JSON blobs and composite keys everywhere.

### 8.5 Data lifecycle

The data lifecycle looks like this:

1. services write canonical append-only facts
2. refresher builds current-state and analytics facts
3. ranker imports facts into DuckDB and exports rank snapshots
4. assertor publishes from facts plus ranks
5. API and DVM expose selected read models

### 8.6 Storage variants

Two deployment variants exist:

- `bigbrotr`
  Full event archive
- `lilbrotr`
  Lightweight archive with shared derived schema but much smaller event storage

They share the same general service model and mostly the same derived schema.

---

## 9. SQL Template System

### 9.1 Source of truth

Generated SQL lives under:

- `deployments/bigbrotr/postgres/init/`
- `deployments/lilbrotr/postgres/init/`

But the source of truth lives in:

- `tools/templates/sql/base/`
- `tools/templates/sql/lilbrotr/`
- `tools/templates/sql/testbrotr/`

Generated SQL should not be edited directly.

### 9.2 Base template sequence

The main base templates are:

- `00_extensions.sql.j2`
- `01_functions_utility.sql.j2`
- `02_tables_core.sql.j2`
- `03_tables_current.sql.j2`
- `04_tables_analytics.sql.j2`
- `05_functions_crud.sql.j2`
- `06_functions_cleanup.sql.j2`
- `07_views_reporting.sql.j2`
- `08_functions_refresh_current.sql.j2`
- `09_functions_refresh_analytics.sql.j2`
- `10_indexes_core.sql.j2`
- `11_indexes_current.sql.j2`
- `12_indexes_analytics.sql.j2`
- `99_verify.sql.j2`

### 9.3 Role of the template system

The template system lets the project:

- share one schema core across deployments
- override only deployment-specific differences
- keep generated init SQL reproducible
- validate that generated files match templates in CI

### 9.4 LilBrotr differences

LilBrotr overrides only the parts that need to differ:

- event table shape
- event insert behavior
- verification output

The rest of the current-state, analytics, and rank schema is inherited.

---

## 10. NIP Layer

### 10.1 Why the NIP layer exists

The NIP layer keeps protocol-specific concepts out of services.

Instead of scattering NIP-specific parsing and payload structures throughout
service code, BigBrotr localizes them in `src/bigbrotr/nips/`.

### 10.2 `nip11/`

NIP-11 support covers:

- fetching relay information documents
- normalizing them into structured metadata payloads
- logging outcomes in a protocol-aware way

Key files:

- `info.py`
- `data.py`
- `logs.py`
- `nip11.py`

### 10.3 `nip66/`

NIP-66 support covers relay health checks and the typed payloads derived from
them.

Subdomains include:

- RTT
- SSL
- DNS
- Geo
- Net
- HTTP

Key files:

- `rtt.py`
- `ssl.py`
- `dns.py`
- `geo.py`
- `net.py`
- `http.py`
- `data.py`
- `logs.py`
- `nip66.py`

### 10.4 `nip85/`

NIP-85 support covers rank and assertion payload types.

Key file:

- `data.py`

### 10.5 Shared NIP helpers

- `base.py`
  Common typed bases and shared data/log structures.
- `parsing.py`
  Strict parsing helpers.
- `event_builders.py`
  Shared event construction helpers.
- `registry.py`
  Static registry for built-in NIP capability bundles.

---

## 11. Nostr Protocol Boundary

### 11.1 Why the protocol cluster exists

Relay connection and client lifecycle logic is too important and too repetitive
to let each service reinvent it.

The `utils/protocol*` cluster centralizes:

- client creation
- read/write/probe session patterns
- relay connection behavior
- SSL fallback
- lifecycle cleanup
- publish result normalization
- shared validation paths

### 11.2 Key modules

- `protocol.py`
  Public facade for most service-level uses.
- `protocol_factory.py`
  Client construction.
- `protocol_connections.py`
  Relay connection helpers.
- `protocol_lifecycle.py`
  Cleanup and shutdown.
- `protocol_manager.py`
  Shared `NostrClientManager`.
- `protocol_publish.py`
  Publish and per-relay result handling.
- `protocol_sessions.py`
  Session types and multi-relay helpers.
- `protocol_validation.py`
  Validation-oriented protocol helpers.

### 11.3 Which services depend on this boundary

Most notably:

- `validator`
- `monitor`
- `synchronizer`
- `assertor`
- `dvm`

The more stable this boundary is, the easier it is to add future services and
future Nostr-facing capabilities without copy-pasting transport logic.

---

## 12. Runtime, Logging, and Metrics

### 12.1 CLI and service launching

The CLI entrypoint is `src/bigbrotr/__main__.py`.

It is responsible for:

- parsing service name and common flags
- resolving deployment profiles
- loading shared and service-specific YAML config
- merging per-service pool overrides
- instantiating `Brotr`
- instantiating the selected service from the service registry
- delegating execution to `ServiceCliRunner`

### 12.2 Service registry

`services/registry.py` maps service IDs to:

- import path
- class name
- default config path

This is the central registry for built-in services.

### 12.3 Base service contract

`BaseService` defines the common lifecycle:

- service construction from validated config
- `run()` for one cycle
- `run_forever()` for the main loop
- graceful shutdown
- cycle metrics
- failure tracking

Services focus on business logic rather than rebuilding lifecycle machinery.

### 12.4 Logging

Structured logging lives in `core/logger.py`.

The CLI installs a `StructuredFormatter` at startup so logs from different parts
of the system use a unified shape.

### 12.5 Metrics

Prometheus metric serving is handled by `core/metrics.py`.

Each service can expose metrics and emit:

- cycle duration
- counters
- gauges
- service-specific custom metrics

The deployment stack then scrapes those metrics via Prometheus and surfaces them
in Grafana/Alertmanager.

---

## 13. Deployment Model

### 13.1 Purpose of `deployments/`

The `deployments/` folder contains runnable deployment profiles.

Current profiles:

- `bigbrotr/`
- `lilbrotr/`
- `testbrotr/` for test fixture contexts

The deployment model is meant to let the same codebase be composed into
different storage/runtime profiles without forking the core application code.

### 13.2 What a deployment contains

A deployment directory contains:

- `config/`
  Shared `brotr.yaml` plus per-service YAML config.
- `docker-compose.yaml`
  Stack composition.
- `postgres/`
  PostgreSQL config and generated init SQL.
- `pgbouncer/`
  Connection pooler config.
- `monitoring/`
  Prometheus, Alertmanager, and postgres-exporter config.
- `static/`
  Seed relay lists and GeoIP databases.
- `data/`
  Persistent volumes.
- `dumps/`
  Backup placeholders.
- `.env.example`
  Environment template.
- `backup.sh`
  Backup helper script.

### 13.3 Infrastructure inside the stack

A deployment stack typically includes:

- PostgreSQL
- PGBouncer
- Tor SOCKS5 proxy
- optional disabled-by-default I2P and Lokinet proxy definitions
- all built-in application services
- Prometheus
- Alertmanager
- Grafana
- postgres-exporter

### 13.4 `bigbrotr` vs `lilbrotr`

`bigbrotr`:

- full event storage
- full archive profile

`lilbrotr`:

- lightweight event storage
- same general service architecture
- smaller disk footprint

### 13.5 Deployment composition principle

A new deployment should primarily vary by:

- config
- assets
- SQL overrides
- Compose/runtime choices

It should not require a fork of the core business logic.

---

## 14. Configuration System

### 14.1 Shape of config loading

At runtime, config comes from:

1. YAML files
2. environment variables for secrets
3. Pydantic validation

The CLI loads:

- one shared `brotr.yaml`
- one service-specific YAML file

### 14.2 Shared config

`brotr.yaml` holds:

- database host/port/database
- default pool settings
- retry settings
- batch settings
- timeout settings

### 14.3 Per-service config

Each service YAML provides:

- service-specific configuration
- pool override section with role and sizing

This lets the same deployment share common DB/runtime settings while still
right-sizing roles and pool sizes per service.

### 14.4 Secret model

Secrets are supplied through environment variables such as:

- `DB_ADMIN_PASSWORD`
- `DB_WRITER_PASSWORD`
- `DB_READER_PASSWORD`
- `DB_REFRESHER_PASSWORD`
- `DB_RANKER_PASSWORD`
- `NOSTR_PRIVATE_KEY_MONITOR`
- `NOSTR_PRIVATE_KEY_SYNCHRONIZER`
- `NOSTR_PRIVATE_KEY_DVM`
- `NOSTR_PRIVATE_KEY_ASSERTOR`

---

## 15. Tools and Maintenance Scripts

### 15.1 `tools/generate_sql.py`

This is the most important repo maintenance script.

It:

- renders Jinja SQL templates
- writes generated SQL into deployment init directories
- checks for drift in CI

### 15.2 `tools/rebuild_analytics.py`

Operational helper to rebuild derived analytics state.

### 15.3 `tools/migrate_relay_urls.py`

Operational helper for relay URL normalization/migration.

### 15.4 Why the tools folder matters

This folder exists to keep schema generation and operational maintenance
scriptable and repeatable, instead of relying on ad hoc manual steps.

---

## 16. Documentation Structure

### 16.1 `docs/`

The docs site is split into:

- `getting-started/`
  Installation, quickstart, first deployment.
- `user-guide/`
  Architecture, configuration, services, database, monitoring.
- `development/`
  Contributor-oriented engineering guides.
- `how-to/`
  Focused operational recipes.
- `_snippets/`
  Reusable markdown fragments.
- `overrides/`
  MkDocs theme overrides.

### 16.2 Relationship to this document

The docs site teaches users and contributors how to use the project.

This file is different:

- broader than a single guide
- more implementation-oriented than public docs
- closer to a repository map and architectural bible

### 16.3 Local folder guides

There are also local `CLAUDE.md` files across the repository. Their role is
smaller and more localized:

- explain the current folder
- list important files
- explain local responsibility

This document sits above them and ties them together.

---

## 17. Testing Strategy

### 17.1 Test split

The repo uses:

- `tests/unit/`
  Fast tests that mirror the source tree
- `tests/integration/`
  PostgreSQL-backed integration tests

### 17.2 Unit tests

Unit tests cover:

- models
- core runtime
- NIP parsing and payloads
- service logic
- common service-layer helpers
- utilities and protocol helpers
- tooling scripts

### 17.3 Integration tests

Integration tests verify:

- generated schema behavior
- stored procedures
- deployment-specific differences
- end-to-end database behavior

Integration suites are split into:

- `tests/integration/base/`
- `tests/integration/lilbrotr/`

### 17.4 Quality gates

The repo uses strict quality gates:

- `ruff`
- `mypy`
- `pytest`
- SQL generation drift checks
- dependency/security checks
- docs build in CI

### 17.5 Practical meaning

The project treats tests and checks as part of the product surface. A refactor
is not finished if it only “looks cleaner” but does not leave the repo green.

---

## 18. GitHub and CI Automation

### 18.1 `.github/`

Repository automation and policy live here.

Important files:

- `CODEOWNERS`
- `CODE_OF_CONDUCT.md`
- `PULL_REQUEST_TEMPLATE.md`
- `SECURITY.md`
- `dependabot.yml`
- `codeql-config.yml`

### 18.2 Workflows

Key workflows:

- `ci.yml`
  Main quality gate.
- `docs.yml`
  Documentation validation/build.
- `release.yml`
  Release-oriented automation.
- `codeql.yml`
  Static analysis and security scanning.

This means repository health is enforced both locally and in hosted automation.

---

## 19. End-to-End Data Flow

### 19.1 Discovery

Sources:

- static seed file
- external relay-list APIs
- archived event tag values

Flow:

- `Seeder` and `Finder` write candidate records into shared operational state
- `Validator` consumes those candidates and promotes valid relays

### 19.2 Monitoring

Input:

- canonical relay table

Flow:

- `Monitor` probes relays
- emits structured metadata
- stores metadata snapshots in content-addressed form

### 19.3 Archiving

Input:

- canonical relay table
- configured filters

Flow:

- `Synchronizer` fetches events from relays
- persists `event`
- persists `event_observation`
- updates relay cursors/checkpoints in `service_state`

### 19.4 Canonical derivation

Input:

- append-only core archive tables
- relay metadata history

Flow:

- `Refresher` maintains current-state tables
- `Refresher` maintains analytics tables
- `Refresher` computes NIP-85 fact tables

### 19.5 Ranking

Input:

- canonical current-state and fact tables

Flow:

- `Ranker` imports them into DuckDB
- computes graph-based and non-user rank snapshots
- exports rank tables back into PostgreSQL

### 19.6 Assertion publishing

Input:

- NIP-85 facts
- NIP-85 ranks
- publish state

Flow:

- `Assertor` builds NIP-85 events
- publishes to relays
- stores publish progress

### 19.7 Public consumption

Input:

- public read-model registry
- enabled read-model policies
- catalog-discovered schema

Flow:

- `Api` exposes over HTTP
- `Dvm` exposes over NIP-90

---

## 20. Extension Surfaces

### 20.1 Adding a new service

A new service should require:

- a new service package under `src/bigbrotr/services/`
- config models
- service-specific query/runtime helpers
- a registry entry in `services/registry.py`
- per-deployment config files
- tests

The rest of the repo should not need broad edits if the foundations are doing
their job.

### 20.2 Adding a new NIP

A new NIP capability should mostly require:

- a module or package under `src/bigbrotr/nips/`
- typed payloads/parsers/builders
- optional registry wiring if it is part of the built-in capability set
- service consumption only where needed

### 20.3 Adding a new deployment

A new deployment should require mostly:

- a new folder under `deployments/`
- config
- SQL overrides if needed
- Compose/runtime wiring

It should not require cloning or forking the core codebase.

### 20.4 Public read-model extension

A new public read model should primarily involve:

- registry entry in `read_model_registry.py`
- policy/config enabling
- tests

This keeps the public surface named and controlled.

---

## 21. Foundational Invariants

These are some of the most important invariants to preserve when evolving the
project.

### 21.1 Services remain independent

Services may share PostgreSQL, but they should not grow hidden direct coupling.

### 21.2 Models remain strict and deterministic

The model layer is not the place for operational shortcuts.

### 21.3 Protocol complexity stays out of service business logic

Nostr client/session/connection details belong in reusable protocol helpers.

### 21.4 The database remains the canonical integration boundary

Cross-service coordination belongs in persisted state and canonical tables.

### 21.5 Public query surfaces are named products, not raw schema dumps

API and DVM should expose read models intentionally.

### 21.6 Deployments compose the system, they do not redefine it

Profiles should vary by configuration and storage choices more than by code
forking.

### 21.7 Shared operational state should stay disciplined

Using one shared operational state table can be a strength if the typed boundary
stays strong and the semantics remain clear.

---

## 22. Practical Way to Read the Repository

For someone trying to understand the codebase in the right order, a good reading
sequence is:

1. `README.md`
2. `PROJECT_GUIDE.md`
3. this file
4. `src/bigbrotr/__main__.py`
5. `src/bigbrotr/models/`
6. `src/bigbrotr/core/`
7. `src/bigbrotr/services/common/`
8. `src/bigbrotr/utils/protocol*.py`
9. the individual service packages
10. `tools/templates/sql/`
11. `deployments/`
12. `tests/`

This order mirrors the real conceptual dependency chain of the project.

---

## 23. Final Summary

BigBrotr is a modular Nostr observatory built from independent async services
that share PostgreSQL as the canonical store.

The repository is organized to keep:

- domain models strict
- runtime foundations reusable
- protocol logic localized
- service orchestration separate
- public read surfaces intentional
- deployment composition explicit

The most important way to think about the project is this:

BigBrotr is not one daemon with many subcommands. It is a data platform for the
Nostr relay ecosystem, with:

- discovery services
- validation services
- health/metadata services
- archive services
- canonical derivation services
- private ranking compute
- public query surfaces

If those layers remain clear, the project stays understandable, extensible, and
operationally stable even as more services, more NIPs, and more deployments are
added later.
