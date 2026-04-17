# Project Vision And Redesign Plan

## Purpose

This document consolidates the architectural understanding, redesign intent,
and improvement criteria that emerged from the full audit and the planning work
around the NIP-85 branch and its hardening follow-up.

It exists to keep one stable, detailed reference for:

- what BigBrotr is
- what it is supposed to do
- how it is composed today
- which design principles should guide future work
- which kinds of changes are encouraged, tolerated, or discouraged
- what "better" means for this project before it reaches production

This is not a historical changelog. It is a current design memo and future
planning anchor.

Role and precedence:

- this file is a broad **vision memo and redesign precursor**;
- it captures the direction and values that led into the definitive redesign
  planning work;
- it is **not** the final execution contract for the redesign;
- the canonical redesign-target and execution documents now live under
  `planning/definitive-redesign/`, especially:
  - `13_db_consolidation_and_remaining_topics.md`
  - `14_core_read_layer_proposal.md`
  - `15_deployment_contract_proposal.md`
  - `16_operational_implementation_plan.md`
  - `99_definitive_master_plan.md`

## Current Product Identity

BigBrotr is a modular Nostr network observatory.

Its purpose is to answer, continuously and at scale:

1. Which relays exist on the Nostr network?
2. Which of them are valid, reachable, and healthy?
3. Which events are they publishing?
4. Which derived facts, analytics, and NIP-85 trust outputs can be built from
   those observations?

BigBrotr is therefore not just an event archiver and not just a monitoring
system. It is a composed pipeline with four distinct concerns:

- relay discovery
- relay validation and health monitoring
- event archiving
- derived analytics and trust publication

It also exposes query surfaces for external consumers through:

- an HTTP API
- a NIP-90 DVM

## Runtime Shape

The system is built as a set of independent async services sharing PostgreSQL
as the canonical data store.

There is intentionally no direct service-to-service RPC. Services communicate
only through persisted state and derived tables.

The built-in service set currently includes:

- `seeder`
- `finder`
- `validator`
- `monitor`
- `synchronizer`
- `refresher`
- `ranker`
- `assertor`
- `api`
- `dvm`

The intended service flow is:

1. `Seeder` seeds initial relay candidates from files.
2. `Finder` discovers additional relay candidates from external APIs and
   archived event tag values.
3. `Validator` validates candidate relays through WebSocket/Nostr behavior and
   promotes the valid ones into the canonical relay registry.
4. `Monitor` performs NIP-11 and NIP-66 health checks and stores relay
   metadata snapshots.
5. `Synchronizer` streams and archives events from validated relays.
6. `Refresher` maintains current-state and derived analytics facts from the
   append-only core data.
7. `Ranker` computes algorithm-specific rank snapshots from derived canonical
   facts in a private compute store.
8. `Assertor` publishes NIP-85 trusted assertions derived from those facts and
   snapshots.
9. `Api` and `Dvm` expose read-only query surfaces over selected public read
   models.

## Architectural Style

The intended style of the project is:

- async and service-oriented
- SQL-first and database-centric
- typed and fail-fast at the model/config boundary
- explicit rather than magical
- operationally observable
- modular but not plugin-framework-heavy

The import architecture follows the intended diamond DAG:

- `models` as pure domain
- `core`, `nips`, and `utils` above it
- `services` above those

The most important constraints behind this shape are:

- services must remain independent
- the database is the canonical integration boundary
- domain models must remain deterministic and validated
- protocol and transport complexity should not leak arbitrarily into services
- public read surfaces should not expose internal storage directly

## What Each Major Layer Is For

### `models`

This layer holds immutable validated domain structures:

- relay identities
- events
- metadata documents
- service state records
- constants and enum-like built-ins

This layer should remain small, deterministic, and strict.

### `core`

This layer defines the project foundations:

- DB access façade
- async pool
- service lifecycle and runtime loop
- config loading
- logging
- metrics

This is one of the most important stability layers in the entire project.
Changes here are cheap now and expensive later.

### `nips`

This layer models protocol-specific knowledge:

- NIP-11 info
- NIP-66 checks and metadata
- NIP-85 data structures and builders
- shared parsing and event-building helpers

This should be a domain/protocol layer, not a mini-framework.

### `utils`

This layer should contain support boundaries that are genuinely reusable:

- DNS
- HTTP
- transport
- key loading
- Nostr client/session helpers
- bounded streaming

It should not accumulate unrelated application policy just because many services
import it.

### `services`

This layer owns orchestration. A service should primarily decide:

- what to read
- what to compute
- what to persist
- what to publish
- when to stop

It should not reinvent runtime machinery or become the dumping ground for
generic framework logic.

## Service Responsibilities, As Intended

### `Seeder`

One-shot bootstrap of initial relay candidates from seed files.

### `Finder`

Discovery service for new relay candidates from:

- external relay-list APIs
- archived event tag values already present in the database

This is discovery logic, not validation logic.

### `Validator`

Validation service for candidate relays. It probes candidate endpoints and
promotes valid Nostr relays into the canonical relay set.

This is the "candidate -> relay" boundary.

### `Monitor`

Health and metadata service. It runs NIP-11 and NIP-66 checks and persists
current and historical relay metadata. It may also publish monitoring-related
Nostr events.

### `Synchronizer`

Archive service. It is responsible for connecting to validated relays,
streaming events, and storing canonical event observations.

It should not compute rankings or private algorithmic structures.

### `Refresher`

Derived-data maintainer. It should build and maintain current-state and
analytics facts that are canonical and shared across downstream consumers.

This is where append-only canonical data becomes usable derived facts.

### `Ranker`

Algorithm-specific compute service. Its job is not generic ingestion and not
primary canonical derivation. Its job is:

- import already-derived canonical facts
- maintain private compute-friendly data structures
- compute ranking snapshots
- export final snapshots back into PostgreSQL

This means the `Ranker` is more accurately a private ranking pipeline than a
single function that "just computes rank".

### `Assertor`

Publishing service for NIP-85 trusted assertions derived from canonical facts
and ranking snapshots.

### `Api` and `Dvm`

Public query surfaces. They should expose stable product-level read models,
not raw internal database tables.

## Project-Wide Design Goals

The future project shape should optimize for the following simultaneously:

### 1. Simplicity

The project should become easier to explain, not only better split across
files. "More files" is not a success metric.

### 2. Stable foundations

The most expensive things to migrate after production should become correct and
deliberate now:

- core runtime contract
- domain model
- database model
- public read contracts
- deployment composition model
- protocol client boundary

### 3. Local extensibility

Adding one new thing should touch very few places.

This must hold for:

- new services
- new NIPs
- new deployments
- new public read models

### 4. Shared reusable primitives

New services and deployments should mostly compose existing foundations instead
of copying behavior.

### 5. Space and runtime efficiency

The database and services should not carry storage and compute costs that do
not earn themselves.

### 6. Naming clarity

Names are first-class architecture. If a name requires a paragraph of
explanation, it is usually weak.

## Non-Negotiable Principles For Future Work

### Prefer one correct path over multiple convenience paths

If a dataset is large enough to require paging or chunking in production, then
the default public and internal runtime path should be paged/chunked. "Fetch
everything" helpers should not remain as first-class patterns in operational
code.

### Prefer deletion over compatibility

The project is still draft-stage. If a path, alias, wrapper, compatibility shim,
or generic helper no longer earns its place, it should usually be removed
instead of preserved.

### Prefer domain boundaries over framework-like boundaries

Terms like `manager`, `handler`, `runtime`, `catalog`, `common`, or `utils`
should only remain where they are genuinely the best names. Broad buckets are
acceptable only when they still describe coherent ownership.

### Prefer shared foundations over service-local reinvention

When a new service, NIP, or deployment can reuse an existing foundation
cleanly, it should do so. Shared code should exist to make extensions easier,
not to introduce abstract ceremony.

### Prefer storage that earns itself

Any derived table must justify its physical storage by at least one of:

- materially lower runtime cost
- incremental refresh semantics that a view would not provide well
- multi-consumer reuse
- substantially simpler downstream queries

If it does not, a view or a join should usually replace it.

## Extensibility Vision

The project should explicitly support three kinds of growth:

- more services
- more NIPs
- more deployments

### New service: target shape

Adding a new service should ideally require:

1. one new service package
2. one service config model
3. service-local query/runtime helpers
4. one central registration entry
5. optional deployment enablement

It should not require touching many unrelated files or re-implementing runtime
plumbing.

### New NIP: target shape

Adding a new NIP should ideally require:

1. one new protocol package or module
2. its parsing/data/building logic
3. one capability-oriented registration point
4. optional read-model or publishing integration where needed

It should not require scattered changes across unrelated runtime layers.

### New deployment: target shape

Adding a deployment should ideally require:

1. selecting services
2. selecting configuration
3. selecting read surfaces
4. selecting infrastructure/profile details

It should not require forking the core architecture or duplicating business
logic.

## Database Vision

The database is allowed to change radically if doing so simplifies the project.

However, the goal is not "more schema". The goal is:

- fewer clearer concepts
- fewer bytes wasted on duplicated derivations
- fewer tables that exist only because one service wanted a shortcut
- more self-explanatory relations

### Desired DB shape

The ideal database should be thought of in three families:

#### A. Canonical core data

This is the append-only or conceptually primary domain:

- relays
- events
- event observations
- metadata documents
- relay metadata observations

#### B. Operational shared state

This is shared runtime persistence:

- service checkpoints
- service cursors
- service-level operational markers

One shared state table can be acceptable if it remains disciplined and
semantically clear. The problem is not "one table"; the problem is opaque and
weakly structured usage.

#### C. Derived current/analytics data

This is current-state and analytics material:

- current winners
- fact tables
- rank snapshots
- reporting-oriented aggregates

### Desired DB naming style

Names should be:

- self-explanatory
- domain-centered
- not historical fossils
- not framework jargon
- not excessively generic

### Storage-efficiency principle

Wide duplicated current tables should be challenged aggressively.

For example, current-state tables that duplicate large payloads such as:

- full event content
- tags
- signatures
- denormalized JSON blobs

should be reconsidered if a narrow winner table plus join/view would be
clearer and materially smaller.

### Example: `contact_lists_current`

`contact_lists_current` is derivable from `events_replaceable_current` and could
in principle be turned into a view or a more minimal structure. The important
insight is broader:

- not every derivable table should be stored
- tables must justify themselves in storage, not only in query convenience

At the same time, the biggest waste is often not in small narrow tables like
`contact_lists_current`, but in "current" tables that duplicate large event or
metadata payloads.

## Performance Vision

The project should scale by design, not by accident.

The key performance principles are:

### 1. Large operational datasets should be paged or chunked by default

This includes:

- relay worksets
- synchronizer cursors
- finder cursors
- monitor relay scans
- validator candidate pages
- assertor publish batches
- ranker stage/export batches

### 2. Generic read surfaces should not force expensive default query models

Public read surfaces should prefer keyset/cursor pagination where applicable
and should not rely on unnecessary broad `COUNT + OFFSET` patterns.

### 3. Derived state should not create avoidable storage duplication

Storage bloat is a performance problem too:

- bigger tables
- bigger indexes
- slower cache behavior
- more refresh work

### 4. Private compute structures should stay private

Algorithm-specific compute structures, such as the `Ranker`'s DuckDB-local
follow graph and staged fact tables, are acceptable when they serve one compute
engine well and avoid polluting the canonical DB schema.

## What Has Been Learned From The Planning Discussions

Several strong conclusions emerged and should be treated as working truths:

### The project is not yet constrained by compatibility

It is still acceptable to:

- rename files
- rename modules
- rename services
- redesign the schema
- remove old helper shapes
- remove compatibility aliases
- rewrite public surfaces

The only requirement is that the result is truly simpler and stronger.

### The right question is not "how do we preserve what we already have?"

The right question is:

What shape should this project have before it becomes expensive to change?

### Not every refactor that splits code is a net win

Splitting is useful only when it reduces:

- mass
- confusion
- repeated explanation
- runtime/framework tax

If it merely distributes the same complexity into more files, it should be
reconsidered.

### Shared abstractions should be used or removed

Any registry, helper layer, or boundary that does not currently earn its place
in runtime or maintenance should either:

- become real and central
- or be removed

### Public read models are a good direction, but internal storage coupling still matters

Exposing read models instead of raw tables is a real improvement. But if the
internal implementation is still too tightly catalog/schema-shaped, further
refinement may still be warranted.

## Current Improvement Lenses

The project can be improved from several legitimate points of view. Future
planning should evaluate proposals across all of them, not just one.

### Architectural lens

- less framework tax
- thinner and clearer boundaries
- fewer generic layers

### Product lens

- public surfaces should reflect product queries, not storage layout
- service responsibilities should align with product meaning

### Foundation lens

- stabilize the deepest contracts now
- avoid future production-costly migrations

### Extensibility lens

- new services, NIPs, and deployments should be locally composable

### Database lens

- use few meaningful tables
- minimize pointless duplication
- prefer clear semantics over convenience sprawl

### Performance lens

- page large datasets
- stage or materialize only what pays for itself
- avoid waste in storage and query execution

### Maintenance lens

- fewer explanations needed
- fewer weak names
- fewer tests coupled to transient internals

## Things The Project Should Avoid Going Forward

- preserving helper APIs purely for legacy comfort
- keeping both full-fetch and paged-fetch runtime paths for the same large
  operational dataset
- maintaining registries or abstraction layers that are not actually used
- exploding the DB into service-specific micro-tables
- keeping large duplicated payloads in current-state tables when narrow winner
  tables would do
- introducing new abstractions that mainly rename old abstractions
- allowing deployments to drift into separate quasi-products

## Desired Long-Term Shape

The desired final shape can be summarized as:

- stable at the center
- extensible at the edges
- lean in the shared layers
- explicit in the contracts
- economical in storage
- opinionated in the foundations

More concretely:

- `core` should be a stable, small foundation
- `models` should be deterministic and compact
- `nips` should be protocol-specific, not framework-specific
- `utils` should contain genuinely reusable low-level boundaries
- `services/common` should remain only as large as the value it provides
- services should compose shared primitives instead of rebuilding them
- the DB should contain only canonical data, justified operational state, and
  justified derived state
- read surfaces should be clear product contracts
- deployments should be compositions, not forks

## Planning Implication

Future redesign planning should not start from "what is least disruptive?".

It should start from:

1. Which foundations will be hardest to migrate after production?
2. Which abstractions do not yet earn themselves?
3. Which tables do not yet earn their storage cost?
4. Which extension paths are still too expensive?
5. Which names still hide responsibility?

The next serious design phase should therefore focus on:

- stabilizing foundations
- simplifying shared abstractions
- making extension surfaces genuinely local
- redesigning the DB where it materially improves clarity, extensibility, and
  storage efficiency

## Summary

BigBrotr should become a project that is:

- easier to explain
- easier to extend
- cheaper to run
- cheaper to store
- harder to misuse
- and easier to stabilize before production

The project is still draft-stage. That is an opportunity, not a constraint.

The correct mindset is:

- do not preserve accidental structure
- do not preserve historical names automatically
- do not preserve storage duplication that can be designed away
- do preserve the few core ideas that are genuinely strong:
  - independent services
  - PostgreSQL as canonical shared store
  - typed domain and config boundaries
  - explicit service responsibilities
  - reusable shared foundations
