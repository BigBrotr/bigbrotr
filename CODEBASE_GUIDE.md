# BigBrotr Codebase Guide

This document is intentionally code-first.

It is meant to help someone orient themselves in the real project as it exists in the repository today, even if older docs, plans, handoffs, or chats have drifted.

If this guide ever disagrees with the code, the code wins.

## 1. What This Repository Is

BigBrotr is a modular Nostr network observatory built around:

- Python async services
- PostgreSQL as the canonical shared data store
- generated SQL init scripts from Jinja templates
- strict typed models and config models
- a service-oriented runtime launched through a single CLI entrypoint

At code level, the project currently exposes **9 services** through the runtime registry in `src/bigbrotr/__main__.py`:

- `seeder`
- `finder`
- `validator`
- `monitor`
- `refresher`
- `synchronizer`
- `api`
- `dvm`
- `assertor`

There is **no `ranker` service yet in code**.

## 2. The Most Important Mental Model

The easiest correct mental model for the codebase is:

1. `__main__.py` wires config + DB + service lifecycle.
2. `core/` provides shared runtime primitives.
3. `models/` defines validated domain objects used at the DB boundary.
4. `services/` contains orchestration logic, one service per concern.
5. `tools/templates/sql/` defines the real database contract.
6. `deployments/` is how the code actually gets run in containers.
7. `tests/` mirrors the same architecture: unit tests around Python logic, integration tests around generated PostgreSQL behavior.

Another way to say it:

- Python services orchestrate work.
- PostgreSQL procedures and summary tables do the heavy persistent analytics work.
- generated SQL is not secondary: it is part of the application logic.

## 3. Repository Map

Top-level directories that matter most:

- `src/bigbrotr/`
  - application code
- `tools/templates/sql/`
  - source of truth for generated database init SQL
- `deployments/`
  - runnable BigBrotr and LilBrotr deployments
- `tests/`
  - unit and integration tests
- `docs/`
  - user/developer docs
- `site/`
  - built documentation output

Practical note:

- `docs/` can drift
- `site/` is generated/published output
- `tools/templates/sql/` and `src/` are the safest sources when you need truth

## 4. Runtime Entry Point

The runtime starts in `src/bigbrotr/__main__.py`.

That file is the operational gateway to the whole system:

- defines the `SERVICE_REGISTRY`
- loads the shared DB config from `config/brotr.yaml`
- loads one service YAML from `config/services/<name>.yaml`
- builds `Brotr`
- instantiates exactly one service class
- starts metrics if configured
- runs the service once or forever
- applies signal-based shutdown

Important consequence:

- all services are designed to be standalone processes
- each service should be runnable with `bigbrotr <service>`
- each service must behave well under `--once` and `run_forever()`

If you want to understand "what can run", start here.

## 5. Core Layer

### `src/bigbrotr/core/base_service.py`

This is the common service lifecycle contract.

Every real service inherits from `BaseService[ConfigT]`.

Responsibilities:

- async context manager lifecycle
- `run()` contract for one cycle
- `cleanup()` hook
- `run_forever()` loop
- failure counting via `max_consecutive_failures`
- cooperative shutdown
- Prometheus metric helpers through the base class

If a new service does not fit naturally into `BaseService`, it likely does not fit the project style.

### `src/bigbrotr/core/brotr.py`

`Brotr` is the high-level DB facade.

This is one of the most important architectural rules in the codebase:

- services should use `Brotr`
- services should not reach into the raw asyncpg pool directly

`Brotr` wraps:

- typed bulk inserts for domain models
- generic `fetch`, `fetchrow`, `fetchval`, `execute`
- service state persistence
- refresh/materialized-view operations
- transaction access
- YAML-based construction

Why this matters:

- timeout policy stays centralized
- logging stays consistent
- batch limits stay enforced
- the rest of the code gets a stable DB interface

### `src/bigbrotr/core/pool.py`

`Pool` is the low-level asyncpg wrapper.

Responsibilities:

- connection pool management
- env-aware password lookup
- JSON/JSONB codec registration
- retries and server settings

Think of the layering as:

- `Pool` = transport/mechanics
- `Brotr` = domain-aware DB API

### `src/bigbrotr/core/metrics.py`

Global metrics registry and metrics server.

This is shared infrastructure, not service-specific logic.

### `src/bigbrotr/core/logger.py`

Structured logger wrapper used across services.

The codebase strongly prefers structured event-style logs instead of ad-hoc string dumps.

### `src/bigbrotr/core/yaml.py`

Safe YAML loading used by config constructors.

## 6. Domain Models

The models in `src/bigbrotr/models/` are not decorative dataclasses. They are the typed boundary between external data and the DB API.

Key models:

- `Relay`
  - canonicalizes URLs
  - detects network type
  - validates relay identity
- `Event`
  - wraps `nostr_sdk.Event`
  - validates and extracts all persisted fields
  - prepares DB parameters
- `EventRelay`
  - junction between an event and the relay where it was seen
- `Metadata`
  - content-addressed metadata records with canonical JSON hashing
- `RelayMetadata`
  - junction between relay and metadata
- `ServiceState`
  - generic persistent service checkpoint/state record

Enums in `models/constants.py` matter a lot:

- `NetworkType`
- `ServiceName`
- `EventKind`

Current NIP-85 constants exist for:

- `30382`
- `30383`
- `30384`
- `30385`

But current implemented publish/data-model support in Python exists only for:

- `30382` user assertions
- `30383` event assertions

## 7. Service Architecture

Services live in `src/bigbrotr/services/<name>/`.

A normal service package usually has:

- `configs.py`
- `queries.py`
- `service.py`
- sometimes `utils.py`

The pattern is consistent:

- `configs.py` defines Pydantic config models
- `queries.py` holds DB reads/writes specific to the service
- `service.py` orchestrates lifecycle and business flow
- `utils.py` holds parsing/transform logic that does not belong in the orchestrator

This separation is one of the codebase's strongest design decisions.

### 7.1 Seeder

Path:

- `src/bigbrotr/services/seeder/`

Role:

- bootstrap relay URLs from a static file

Typical usage:

- one-shot initialization with `--once`

What it does:

- reads configured seed relay list
- inserts URLs as candidates or relays depending on mode

Use this when:

- bringing up a fresh deployment
- seeding an empty database

### 7.2 Finder

Path:

- `src/bigbrotr/services/finder/`

Role:

- discover new relay URLs

Sources:

- external APIs
- stored `tagvalues` extracted from collected events

Important design details:

- API fetches happen first
- event scanning uses cursor-based pagination
- cursors are stored in `service_state`
- discovered URLs are inserted as relay candidates for the validator

This service is downstream of ingestion and upstream of validation.

### 7.3 Validator

Path:

- `src/bigbrotr/services/validator/`

Role:

- validate relay candidates by checking whether they actually behave like Nostr relays

Important design details:

- uses per-network semaphores
- processes candidates in chunks
- retries failures
- promotes valid relays
- increments failure counts for invalid ones
- can delete exhausted candidates

This is the gate between "discovered URL" and "real relay in the system".

### 7.4 Monitor

Path:

- `src/bigbrotr/services/monitor/`

Role:

- health-check relays
- collect NIP-11 and NIP-66 style metadata
- optionally publish monitor/discovery/profile events

What it checks:

- NIP-11 relay info
- RTT
- SSL
- DNS
- geo
- ASN/network info
- HTTP metadata

Important design details:

- uses lazy publish clients
- uses GeoLite databases
- stores results as content-addressed metadata
- publishes only when intervals say it is due

This is the service that turns "relay exists" into "relay is measured".

### 7.5 Synchronizer

Path:

- `src/bigbrotr/services/synchronizer/`

Role:

- collect Nostr events from validated relays

Important design details:

- fetches per-relay sync cursors
- orders relays by sync lag
- streams events concurrently
- buffers `EventRelay` batches
- updates per-relay cursors after flushes
- bounds memory by flushing at batch size

This is the main ingestion service for Nostr events.

If you want to understand how events enter the database, this is the Python side to read.

### 7.6 Refresher

Path:

- `src/bigbrotr/services/refresher/`

Role:

- maintain analytics structures

It is currently the analytics orchestration layer.

The refresher does not implement the analytics formulas itself in Python.
Instead, it:

- refreshes materialized views
- calls stored procedures for summary tables
- manages `(after, until]` checkpoints via `service_state`
- runs periodic refresh tasks such as rolling windows and metadata enrichments

Current periodic tasks in code:

- `rolling_windows`
- `relay_stats_metadata`
- `nip85_followers`

Important mental model:

- Python decides when to refresh and what range to process
- PostgreSQL functions do the actual summary updates

### 7.7 API

Path:

- `src/bigbrotr/services/api/`

Role:

- expose read-only HTTP access to discovered tables/views/materialized views

Important design details:

- FastAPI
- routes are auto-generated from the DB catalog
- only GET endpoints
- safe query construction through `Catalog`
- no application-side rate limiting

This is not a handcrafted business API.
It is a safe read-only data exposure layer over the schema.

### 7.8 DVM

Path:

- `src/bigbrotr/services/dvm/`

Role:

- expose the same read-only data via NIP-90 job processing

Important design details:

- uses the same `Catalog` used by the API
- polls relays for incoming jobs
- deduplicates processed event IDs in memory
- supports payment-required flows
- publishes result/error/payment-required events back to relays

This is essentially the Nostr-native sibling of the HTTP API.

### 7.9 Assertor

Path:

- `src/bigbrotr/services/assertor/`

Role:

- publish NIP-85 trusted assertion events from already prepared summary tables

What exists today:

- reads `nip85_pubkey_stats`
- reads `nip85_event_stats`
- publishes:
  - `30382` user assertions
  - `30383` event assertions
- stores a hash of assertion tags in `service_state`
- only republishes when tags changed

What does not exist yet in code:

- `30384` addressable assertions
- `30385` identifier assertions
- any rank computation
- any `ranker` service

This means the current assertor is a publisher over already-computed metrics, not a scorer.

## 8. Shared Service Infrastructure

### `src/bigbrotr/services/common/configs.py`

This is where network config policy lives.

It defines:

- per-network configs for clearnet/Tor/I2P/Lokinet
- default proxy URLs
- max concurrency per network
- timeout policy
- table exposure/pricing config for API/DVM

This file matters because several services share the same network model rather than reinventing it.

### `src/bigbrotr/services/common/mixins.py`

This file is a major architectural hub.

Key mixins:

- `NetworkSemaphoresMixin`
  - per-network bounded concurrency
- `ConcurrentStreamMixin`
  - concurrent async workers with streamed results
- `GeoReaderMixin`
  - lifecycle around GeoLite readers
- `ClientsMixin`
  - lazy relay client pooling for publishers
- `CatalogAccessMixin`
  - shared schema discovery/access for API and DVM

When adding a new service, check this file before inventing a new runtime helper.

### `src/bigbrotr/services/common/catalog.py`

This is the safe read-only query engine for API and DVM.

It:

- introspects public schema objects at runtime
- discovers columns and PKs
- includes materialized views
- validates tables, columns, operators, and sort keys
- builds parameterized queries

This is why the API and DVM can expose the database without being a SQL injection mess.

## 9. Nostr Protocol Layer

### `src/bigbrotr/utils/protocol.py`

This file is another core architectural piece.

It handles:

- Nostr client creation
- relay connection
- SSL fallback for clearnet
- overlay network proxy routing
- event broadcasting
- relay validation helpers
- safe client shutdown

Important nuance:

- clearnet may try SSL first, then insecure fallback if configured
- overlay networks always use proxy mode
- client shutdown is careful because the Rust/FFI side can otherwise leak resources

If relay connectivity behaves strangely, read this file early.

## 10. NIP Layer

The `src/bigbrotr/nips/` package contains protocol-specific models/builders/parsers.

Key areas:

- `nip11/`
- `nip66/`
- `nip85/`
- `event_builders.py`
- `parsing.py`

### `event_builders.py`

This file is where Python turns internal data models into Nostr events/builders.

It is important because multiple services depend on it:

- monitor
- dvm
- assertor

Pattern to preserve:

- services decide *when* to publish
- event builders decide *what the event looks like*

### `nip85/data.py`

Current assertion data models:

- `UserAssertion`
- `EventAssertion`

These encode the current implemented NIP-85 publish surface.

Not present yet:

- `AddressableAssertion`
- `IdentifierAssertion`

## 11. Database Architecture

The database contract lives in generated SQL, not hand-written init SQL.

Source templates:

- `tools/templates/sql/base/`
- `tools/templates/sql/lilbrotr/`

Generated output:

- `deployments/bigbrotr/postgres/init/*.sql`
- `deployments/lilbrotr/postgres/init/*.sql`

### 11.1 SQL Generation Model

`tools/generate_sql.py` renders a fixed ordered list of templates:

- `00_extensions`
- `01_functions_utility`
- `02_tables`
- `03_functions_crud`
- `04_functions_cleanup`
- `05_views`
- `06_materialized_views`
- `07_functions_refresh`
- `08_indexes`
- `99_verify`

Key architectural rule:

- `base/` defines the shared schema/logic
- implementation-specific folders override only what they must

### 11.2 BigBrotr vs LilBrotr

As implemented in code today, the intended contract is:

- BigBrotr and LilBrotr share the same generated SQL unless LilBrotr explicitly overrides a file

Current LilBrotr override templates are:

- `tools/templates/sql/lilbrotr/02_tables.sql.j2`
- `tools/templates/sql/lilbrotr/03_functions_crud.sql.j2`
- `tools/templates/sql/lilbrotr/99_verify.sql.j2`

Everything else comes from the shared base.

In practice this means:

- same analytics logic whenever possible
- same refresh procedures whenever possible
- different persistence only where LilBrotr intentionally does not store:
  - `tags`
  - `content`
  - `sig`

Important nuance from the code:

- LilBrotr still computes and stores `tagvalues`
- ordered `tagvalues` are now used as the main fallback path when full `tags` are absent

### 11.3 Core Tables

Defined in `02_tables.sql.j2`.

Primary core tables:

- `relay`
- `event`
- `event_relay`
- `metadata`
- `relay_metadata`
- `service_state`

Important roles:

- `relay`
  - canonical relay registry
- `event`
  - partitioned event storage
- `event_relay`
  - one row per event/relay observation
- `metadata`
  - deduplicated metadata payload store
- `relay_metadata`
  - mapping between relays and metadata snapshots
- `service_state`
  - generic checkpoint/state store used by services

### 11.4 Utility Functions

Defined in `01_functions_utility.sql.j2`.

Most important function:

- `tags_to_tagvalues(jsonb)`

This function is central to BigBrotr/LilBrotr parity.

Current effective behavior:

- keeps only single-character tag keys
- stores `key:first_value`
- preserves sequence order

That means:

- LilBrotr can recover a lot of semantics from ordered `tagvalues`
- but it still cannot recover data from non-single-char tags or extra tag fields

### 11.5 CRUD Stored Procedures

Defined in `03_functions_crud.sql.j2`.

Important procedures:

- `relay_insert`
- `event_insert`
- `metadata_insert`
- `event_relay_insert`
- `relay_metadata_insert`
- `event_relay_insert_cascade`
- `relay_metadata_insert_cascade`
- `service_state_upsert`
- `service_state_get`
- `service_state_delete`

This is the procedural API that `Brotr` speaks.

### 11.6 Cleanup Functions

Defined in `04_functions_cleanup.sql.j2`.

These are bulk cleanup helpers for orphan metadata and orphan events.

### 11.7 Views and Materialized Views

Key objects from `06_materialized_views.sql.j2`:

- `relay_metadata_latest`
- `relay_software_counts`
- `supported_nip_counts`
- `daily_counts`
- `events_replaceable_latest`
- `events_addressable_latest`

There are also summary tables defined in the same file, because they are maintained by refresh procedures rather than by standard view refresh alone:

- `pubkey_kind_stats`
- `pubkey_relay_stats`
- `relay_kind_stats`
- `pubkey_stats`
- `kind_stats`
- `relay_stats`
- `nip85_pubkey_stats`
- `nip85_event_stats`

Important nuance:

- not every analytics structure is a materialized view
- several "analytics tables" are incremental summary tables refreshed by procedures

### 11.8 Refresh Procedures

Defined in `07_functions_refresh.sql.j2`.

This file is one of the single most important pieces in the entire repository.

It contains:

- matview refresh procedures
- rolling windows refresh
- relay stats metadata refresh
- incremental summary refresh procedures
- NIP-85 refresh logic
- follower count recomputation
- helper logic like `bolt11_amount_msats`

If analytics results look wrong, this file is the first SQL file to inspect.

Important procedures:

- `pubkey_kind_stats_refresh`
- `pubkey_relay_stats_refresh`
- `relay_kind_stats_refresh`
- `pubkey_stats_refresh`
- `kind_stats_refresh`
- `relay_stats_refresh`
- `rolling_windows_refresh`
- `relay_stats_metadata_refresh`
- `relay_software_counts_refresh`
- `supported_nip_counts_refresh`
- `daily_counts_refresh`
- `events_replaceable_latest_refresh`
- `events_addressable_latest_refresh`
- `nip85_pubkey_stats_refresh`
- `nip85_event_stats_refresh`
- `nip85_follower_count_refresh`

## 12. Current NIP-85 State From Code

Trust the code, not old handoffs.

### What exists

- constants for all four NIP-85 kinds
- DB summary tables for:
  - `nip85_pubkey_stats`
  - `nip85_event_stats`
- refresh procedures for:
  - `nip85_pubkey_stats_refresh`
  - `nip85_event_stats_refresh`
  - `nip85_follower_count_refresh`
- Python models for:
  - `UserAssertion`
  - `EventAssertion`
- event builders for:
  - user assertions
  - event assertions
- assertor service publish support for:
  - `30382`
  - `30383`

### What does not exist

- rank computation
- rank persistence
- `30384` data model + builder + assertor support
- `30385` data model + builder + assertor support
- a `ranker` service

### Practical implication

Today the NIP-85 implementation is "metrics and publish for two kinds", not "full trusted assertions platform".

## 13. BigBrotr / LilBrotr Parity Rules in Code

The project is structured so that BigBrotr and LilBrotr should be as similar as possible.

Current code-backed rule set:

- share the same Python runtime
- share the same services
- share the same refresh logic
- share the same analytics logic
- differ primarily in what gets persisted at ingestion time

Current intended LilBrotr trade-off:

- do not persist full `tags`, `content`, `sig`
- still compute as much as possible from `tagvalues`

Current best-effort boundary from code:

- ordered `tagvalues` can emulate some semantics like `first e`, `last e`, `first p`
- they cannot reconstruct:
  - non-single-char tags like `amount` and `bolt11`
  - extra fields inside tags, such as reply markers and hints

That is why LilBrotr can approach parity, but not always exact parity, without storing more.

## 14. Deployments

Deployment files live under:

- `deployments/bigbrotr/`
- `deployments/lilbrotr/`

Each implementation has:

- `config/brotr.yaml`
- `config/services/*.yaml`
- `docker-compose.yaml`
- PostgreSQL init SQL
- PGBouncer config
- static assets like seed relays and GeoLite DBs

### Important deployment pattern

Each service is a separate container/process, even though they all use the same codebase and CLI entrypoint.

Typical compose services include:

- postgres
- pgbouncer
- tor
- seeder
- finder
- validator
- monitor
- synchronizer
- refresher
- api
- dvm
- assertor

BigBrotr and LilBrotr differ at deploy time mainly by:

- DB name
- init SQL
- deployment-specific config values

## 15. Tests

Test layout:

- `tests/unit/`
  - Python logic, models, services, tools, utils
- `tests/integration/base/`
  - integration tests against base generated SQL behavior
- `tests/integration/lilbrotr/`
  - LilBrotr-specific integration expectations
- `tests/fixtures/`
  - shared data fixtures

Important testing truth:

- many of the most important behaviors are integration-tested at the SQL level
- Python-only tests are not enough to validate analytics correctness

If a change touches:

- refresh procedures
- summary tables
- materialized views
- BigBrotr/LilBrotr parity

you should expect integration tests to be part of the real validation story.

## 16. How Data Flows Through the System

The most useful end-to-end path is:

1. `Seeder`
   - initial relay bootstrap
2. `Finder`
   - discovers more relay URLs
3. `Validator`
   - checks whether candidates are real Nostr relays
4. `Monitor`
   - measures relay health and metadata
5. `Synchronizer`
   - ingests events from validated relays
6. `Refresher`
   - materializes analytics structures from raw data
7. `API`
   - exposes read-only data over HTTP
8. `DVM`
   - exposes read-only data over NIP-90
9. `Assertor`
   - publishes NIP-85 assertions from prepared analytics tables

Persistent coordination between services happens mainly through:

- database tables
- materialized views / summary tables
- `service_state`

The services are not tightly calling each other in memory.
They are coordinated through persisted state and scheduling.

## 17. How To Read This Codebase Efficiently

If you are new and want the fastest path to competence:

1. `src/bigbrotr/__main__.py`
2. `src/bigbrotr/core/base_service.py`
3. `src/bigbrotr/core/brotr.py`
4. `src/bigbrotr/models/`
5. one representative service:
   - `validator/service.py` for concurrency
   - `synchronizer/service.py` for ingestion
   - `refresher/service.py` for analytics orchestration
6. `tools/templates/sql/base/02_tables.sql.j2`
7. `tools/templates/sql/base/06_materialized_views.sql.j2`
8. `tools/templates/sql/base/07_functions_refresh.sql.j2`
9. `tests/integration/base/test_materialized_views.py`

That order gives the best return on time.

## 18. How To Extend The Project In The Existing Style

### Add a new service

Follow the pattern:

1. create `services/<name>/configs.py`
2. create `services/<name>/queries.py`
3. create `services/<name>/service.py`
4. register it in `SERVICE_REGISTRY`
5. add deployment config YAML
6. add compose service
7. add tests

The service should:

- inherit `BaseService`
- receive a `Brotr`
- keep orchestration in `service.py`
- keep SQL in `queries.py`
- prefer mixins over bespoke concurrency helpers

### Add a new analytics table or matview

Follow the pattern:

1. define schema in `06_materialized_views.sql.j2`
2. define refresh procedure in `07_functions_refresh.sql.j2`
3. wire it through `refresher/configs.py` defaults if appropriate
4. wire it through `refresher/queries.py` and `refresher/service.py`
5. regenerate SQL
6. add integration tests

### Add a new publishable Nostr event type

Follow the pattern:

1. define the internal data model
2. add an event builder in `nips/event_builders.py`
3. add service query support
4. keep publish orchestration inside the relevant service

Do not put wire-format event construction directly inside service loops.

## 19. Where Bugs Usually Actually Live

In this project, the real bug hotspots are usually:

- refresh procedures in `07_functions_refresh.sql.j2`
- edge-case parsing in `tagvalues` handling
- service-state checkpoint boundaries
- network timeout / concurrency behavior
- generated SQL drift
- incomplete BigBrotr/LilBrotr parity assumptions

Less often, the bug is in the high-level service skeleton itself.

This means debugging strategy should usually be:

1. confirm which persisted object is wrong
2. identify which refresh procedure or ingestion step owns it
3. confirm generated SQL matches templates
4. only then assume the service loop itself is wrong

## 20. Things That Are Easy To Misread

### "View" does not always mean PostgreSQL view

Several analytics objects are real tables refreshed incrementally, not actual SQL views.

### The refresher is orchestration, not analytics math in Python

The heavy logic is mostly in PostgreSQL procedures.

### The API is schema-driven, not handcrafted domain-specific REST

It exposes discovered tables safely.

### The DVM is not a separate analytics engine

It is another read-only access surface over the same catalog.

### LilBrotr is not a forked app

It is the same app with a thinner persistence model.

### NIP-85 is present, but not complete

Current code implements a meaningful subset, not the full future architecture discussed in plans.

## 21. Current Missing Piece Relative To Future Plans

If you compare the codebase to future architecture discussions, the biggest missing capability is:

- a dedicated ranking/scoring layer

Today:

- the refresher computes observable metrics
- the assertor publishes metrics as NIP-85 events
- there is no dedicated rank computation pipeline

So if future work introduces a `ranker`, it should be treated as a genuinely new service and not something "already half-present".

## 22. Practical File Reading Guide By Task

### "I need to understand service boot and shutdown"

Read:

- `src/bigbrotr/__main__.py`
- `src/bigbrotr/core/base_service.py`

### "I need to understand DB access policy"

Read:

- `src/bigbrotr/core/brotr.py`
- `src/bigbrotr/core/pool.py`

### "I need to understand how relays are discovered and validated"

Read:

- `src/bigbrotr/services/seeder/service.py`
- `src/bigbrotr/services/finder/service.py`
- `src/bigbrotr/services/validator/service.py`

### "I need to understand how events enter the DB"

Read:

- `src/bigbrotr/services/synchronizer/service.py`
- `src/bigbrotr/models/event.py`
- `tools/templates/sql/base/03_functions_crud.sql.j2`

### "I need to understand analytics and counts"

Read:

- `src/bigbrotr/services/refresher/service.py`
- `src/bigbrotr/services/refresher/queries.py`
- `tools/templates/sql/base/06_materialized_views.sql.j2`
- `tools/templates/sql/base/07_functions_refresh.sql.j2`

### "I need to understand BigBrotr/LilBrotr parity"

Read:

- `tools/templates/sql/base/01_functions_utility.sql.j2`
- `tools/templates/sql/lilbrotr/02_tables.sql.j2`
- `tools/templates/sql/lilbrotr/03_functions_crud.sql.j2`
- `tools/templates/sql/lilbrotr/99_verify.sql.j2`
- `tests/integration/lilbrotr/`

### "I need to understand NIP-85"

Read:

- `src/bigbrotr/nips/nip85/data.py`
- `src/bigbrotr/nips/event_builders.py`
- `src/bigbrotr/services/assertor/queries.py`
- `src/bigbrotr/services/assertor/service.py`
- `tools/templates/sql/base/06_materialized_views.sql.j2`
- `tools/templates/sql/base/07_functions_refresh.sql.j2`

### "I need to understand read-only data exposure"

Read:

- `src/bigbrotr/services/common/catalog.py`
- `src/bigbrotr/services/api/service.py`
- `src/bigbrotr/services/dvm/service.py`

## 23. Current Ground Truth Summary

As of the current code:

- the project is service-oriented and DB-centric
- PostgreSQL procedures are part of the application core, not an implementation detail
- `Brotr` is the stable DB boundary
- `service_state` is the common checkpoint/state mechanism
- BigBrotr and LilBrotr are intended to stay as close as possible
- NIP-85 support exists but is partial
- there is no ranker yet
- any future implementation plan should be judged against these facts, not against stale design notes

## 24. How To Use This Guide

Use this document when:

- onboarding onto the project
- checking whether a handoff is stale
- deciding where a new feature belongs
- deciding whether logic belongs in Python or SQL
- understanding whether a behavior is shared between BigBrotr and LilBrotr

Do not use this document as a substitute for reading the code when making non-trivial changes.

Its job is to shorten the path to the right files, not to replace them.
