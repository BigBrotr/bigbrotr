# Definitive Redesign Planning Context

## Purpose

This document is the shared context for the definitive redesign planning
process.

It exists to prevent drift between iterations. Every later iteration should be
able to reread this file and re-anchor itself in:

- what BigBrotr is;
- what it must do;
- what freedoms are available;
- what constraints still matter;
- what quality bar the final plan must meet.

This file is not the plan. It is the common ground all iterations must keep in
view.

## Inputs Reviewed

The planning work is based on the current repository state plus the dedicated
analysis documents prepared during the prior design-review pass.

Primary repository references:

- `/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/README.md`
- `/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/PROJECT_GUIDE.md`
- `/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/PROJECT_VISION_AND_REDESIGN_PLAN.md`
- `/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/BIGBROTR_REPOSITORY_BIBLE.md`
- `/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/NOSTR_NIPS_DEEP_ANALYSIS.md`

Primary code and schema anchors:

- `/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/src/bigbrotr/core`
- `/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/src/bigbrotr/models`
- `/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/src/bigbrotr/nips`
- `/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/src/bigbrotr/services`
- `/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/tools/templates/sql`
- `/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/deployments`
- `/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/tests`

High-value behavioral specifications:

- `/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/tests/integration/base/test_derived_tables.py`
- `/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/tests/integration/base/test_refresher.py`
- `/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/tests/integration/base/test_ranker.py`
- `/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/tests/integration/base/test_nip85_pipeline.py`
- `/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/tests/integration/base/test_assertor.py`
- `/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/tests/integration/lilbrotr/test_derived_tables.py`

Protocol references:

- official NIP repository snapshot documented in
  `/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/NOSTR_NIPS_DEEP_ANALYSIS.md`

## What BigBrotr Is

BigBrotr is a modular Nostr network observatory.

It answers, continuously:

1. Which relays exist on the Nostr network?
2. Which relays are valid, reachable, and healthy?
3. Which events are those relays publishing?
4. Which derived facts, analytics, and NIP-85 outputs can be produced from
   those observations?

It is not just:

- a relay crawler;
- a relay monitor;
- an event archiver;
- a ranking engine;
- an HTTP API;
- a NIP-90 service.

It is the composition of all of them.

## Product Pipeline

The intended pipeline is:

1. `Seeder`
   Bootstraps seed relay candidates from files.
2. `Finder`
   Discovers more relay candidates from external APIs and archived event
   values.
3. `Validator`
   Promotes viable candidates into the canonical relay set.
4. `Monitor`
   Runs NIP-11 and NIP-66 checks and can publish monitoring events.
5. `Synchronizer`
   Connects to relays and archives canonical Nostr events.
6. `Refresher`
   Turns append-only canonical data into current-state and derived facts.
7. `Ranker`
   Maintains private compute structures, computes NIP-85 rank snapshots, and
   exports them back to PostgreSQL.
8. `Assertor`
   Publishes the full NIP-85 provider package.
9. `Api`
   Serves deployment-approved readable resources over HTTP.
10. `Dvm`
   Serves deployment-approved readable resources over NIP-90.

These are independent services. PostgreSQL is the canonical integration
boundary.

## What Makes The Project Valuable

The value of BigBrotr is not a single dataset. It is the combination of:

- network discovery;
- protocol-aware health inspection;
- canonical event archiving;
- derived current-state and analytics facts;
- publishable NIP-85 trust assertions;
- public query surfaces.

Any redesign must preserve that full product identity, even if it radically
changes internal structure.

## Vision Consolidated From The Planning Discussions

### The project is still draft

This is the most important strategic fact.

Because the project is still draft:

- compatibility is not a primary goal;
- migration pain can be accepted now to avoid worse pain later;
- old names, old boundaries, old schema choices, and old public contracts may
  all be reconsidered;
- the correct standard is not “smallest change”, but “best long-term shape”.

### Simplicity beats timid evolution

The redesign should optimize for:

- less conceptual duplication;
- fewer structural fallbacks;
- fewer “legacy paths”;
- fewer weak abstractions;
- fewer storage structures that exist only because they are convenient today.

The redesign should not optimize for:

- preserving old names for comfort;
- keeping multiple equivalent paths;
- keeping current tables or service boundaries just because they already exist;
- adding indirection unless it pays for itself.

### Stable center, extensible edges

The correct shape is:

- stable at the center;
- extensible at the edges.

The center includes:

- domain model;
- canonical database model;
- service runtime contract;
- Nostr/protocol boundary;
- public read contract;
- deployment composition model.

The edges include:

- new services;
- new NIPs;
- new deployments;
- new readable resources and protocol adapters;
- new ranking algorithms.

### Extension should be local and declarative

Adding a new service, NIP, or deployment should require touching a small,
predictable set of places and reusing common foundations.

The desired shape is:

- new service:
  - local package;
  - config model;
  - queries/runtime/helpers;
  - single registration point.
- new NIP:
  - local module/package;
  - parse/build/data logic;
  - single capability registration point.
- new deployment:
  - new composition of services, configs, public surfaces, and storage profile;
  - not a fork of the architecture.

### Storage should be explicit and economical

The redesign should not create a forest of feature-specific tables.

Instead, the schema should prefer:

- a small number of core canonical tables;
- a small number of operational/shared tables;
- a small number of derived/current/analytics tables that truly earn their
  storage cost.

Tables should be:

- semantically coherent;
- easy to explain;
- justified by domain meaning or major operational value.

## Freedoms Explicitly Available

These are allowed by design intent and should be considered real options:

- rename any internal module, class, function, service, or schema object;
- redesign the database schema;
- replace current tables with slimmer pointer tables, views, or matviews;
- remove weak abstractions;
- remove full-fetch paths for large operational datasets;
- redesign the shared read core, readable-resource layer, and protocol
  adapters;
- change service boundaries;
- change deployment composition model;
- delete compatibility layers;
- remove old config shapes;
- change naming aggressively if it improves clarity.

## Constraints That Still Matter

Even with high freedom, the redesign still has important constraints.

### Product constraints

- the project must still remain BigBrotr, not collapse into only one of its
  subsystems;
- the final architecture must still support relay discovery, monitoring,
  archiving, NIP-85 derivation, and public read surfaces.

### Architectural constraints

- services remain independent;
- PostgreSQL remains the canonical shared integration boundary;
- direct service-to-service RPC is not desired;
- private compute is allowed, but should be clearly separated from canonical
  storage.

### Protocol constraints

The redesign must stay faithful to the NIP rules that matter most for
BigBrotr:

- NIP-01 event identity, kinds, tags, filters, replaceable and addressable
  semantics;
- NIP-02 follow list overwrite semantics;
- NIP-11 relay information documents;
- NIP-42 relay authentication flow;
- NIP-65 relay list metadata;
- NIP-66 monitor/discovery publication semantics;
- NIP-73 identifier semantics for kind `30385`;
- NIP-85 provider declarations and assertion tag shapes;
- NIP-89 handler discoverability;
- NIP-90 request/result/feedback flow.

### Scale constraints

The system should be able to handle large relay populations.

The working assumption from discussion is at least on the order of:

- `20k` relays;
- corresponding large cursor sets;
- non-trivial event volume.

That means:

- full-fetch defaults are usually wrong for large operational datasets;
- paging, chunking, batching, and stream-shaped APIs should be the default;
- storage duplication must be justified carefully.

### Maintainability constraints

- the final shape must be easier to explain than the current one;
- naming should reduce ambiguity;
- the public and internal architectural story should line up;
- tests should remain a true specification and not be invalidated casually.

## Most Important Current Architectural Conclusions

### 1. Not all derived tables are equally disposable

Current understanding:

- `contact_lists_current` and `contact_list_edges_current` look like canonical
  current graph facts derived from NIP-02 semantics.
- `events_replaceable_current`, `events_addressable_current`, and
  `relay_metadata_current` look more like winner indexes or convenience
  snapshots and are stronger candidates for slimming or redesign.

### 2. The Ranker boundary is mostly correct

The correct split is:

- `Synchronizer`:
  canonical event ingestion only;
- `Refresher`:
  canonical current-state and derived facts;
- `Ranker`:
  private compute structures and rank export only.

This means the likely redesign question is not “move ranker work into
Synchronizer” but “what should remain canonical in PostgreSQL and what should
remain private to compute”.

### 3. Public read surfaces improved, but backend execution is still generic

Current public configs are already `read_models`-driven.

However, the backend is still heavily shaped by:

- `Catalog`;
- generic table/query dispatch;
- registry entries that still map mostly to `catalog_name`.

The plan must decide how far to push toward truly domain-shaped read handlers.

### 4. Chunking is already present in hot loops, but the design is not yet
strict enough

Main runtime loops in:

- Finder;
- Monitor;
- Synchronizer

already use paged iterators.

But legacy full-fetch helpers still exist and remain a conceptual risk in a
large-scale system.

### 5. BigBrotr and LilBrotr are architectural siblings, not separate products

The integration tests and deployment configs strongly suggest that:

- the intended architecture is shared;
- the storage profile and read surface can differ;
- the semantic divergence should stay narrow and explicit.

This is important for deployment extensibility.

## Design Questions That Drove The Final Plan

These were the major design questions at the start of the definitive-redesign
planning pass.

They are now answered across the final planning set, especially in:

- `12_best_db_schema.md`
- `13_db_consolidation_and_remaining_topics.md`
- `14_core_read_layer_proposal.md`
- `15_deployment_contract_proposal.md`
- `16_operational_implementation_plan.md`
- `99_definitive_master_plan.md`

### Database and storage

- Which current tables remain materialized?
- Which become slimmer pointer/index tables?
- Which become views or materialized views?
- Which tables are truly canonical domain facts?
- Which tables are operational state?
- Which tables are private algorithm working state and should stay out of
  PostgreSQL?

### Service boundaries

- What exactly belongs in `Refresher`?
- What exactly belongs in `Ranker`?
- How thin should `Monitor` publication boundaries be?
- How much should service-specific state remain in one shared operational
  table versus separate explicit domain tables?

### Public read surfaces

- How far should the project move away from `Catalog` as the conceptual center?
- How should the protocol-agnostic read core sit above `Catalog`?
- How much bounded generic filtering/pagination remains allowed?

### Extensibility

- What is the minimal but sufficient service registry?
- Should the NIP registry become a real capability registry?
- How should deployments declare selected services, readable-resource
  exposure, and storage profile?

### Naming and conceptual cleanup

- Which existing names are misleading enough to justify renaming?
- Which abstractions should be collapsed instead of expanded?

## Evaluation Criteria For The Final Plan

The final plan should only be accepted if it satisfies all of the following.

### Structural quality

- The target architecture is simpler overall, not just more modular.
- The plan clearly distinguishes canonical data, operational state, and
  private compute.
- The plan does not preserve duplicate paths without strong reason.

### Product fidelity

- The plan preserves BigBrotr’s full product identity.
- The plan keeps the project protocol-correct on the NIPs that matter.

### Extensibility

- The plan makes adding services, NIPs, and deployments easier and more
  localized.
- The plan identifies stable extension surfaces explicitly.

### Storage discipline

- The plan reduces unjustified storage duplication.
- The plan avoids an explosion of feature tables.

### Execution quality

- The plan is phased and actionable.
- Dependencies between phases are clear.
- Risky design choices are called out explicitly.

## Iteration Process Required For This Planning Work

This planning effort will use at least three full iterations.

Each iteration must include:

1. analysis;
2. candidate design decisions;
3. internal audit;
4. explicit corrections and carry-forward findings.

The final plan should only be written after iteration 3 and after iteration 3
audit feedback is incorporated.

## Standard For What Counts As “Good Enough”

The final plan should aim for:

- no obvious structural contradictions;
- no vague hand-waving on the big architectural choices;
- no silent tradeoffs;
- no incompatible goals hidden in the wording;
- no defaulting back to timid incrementalism just because that is easier to
  write.

The plan should be bold where the project context allows boldness, and
disciplined where protocol and foundations require discipline.
