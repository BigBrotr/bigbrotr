# Iteration 2

## Objective

Iteration 2 takes the broad candidate from iteration 1 and forces it into a
more concrete target shape.

This iteration should:

- turn the data classification into a schema philosophy;
- define the desired extension surfaces;
- tighten service ownership;
- define how radical the redesign should be on legacy compatibility and
  duplicated paths;
- produce a stronger target architecture;
- audit that stronger architecture for missing details and hidden risks.

## Carry-Forward From Iteration 1

The most important weaknesses to correct are:

- excessive abstraction;
- insufficiently concrete DB target;
- unclear read-model strategy;
- insufficiently explicit extensibility model.

## 1. Concrete Data Classification

Iteration 2 promotes the abstract data classes into a concrete design rule.

### Category A — Canonical domain tables

These represent the durable, semantics-bearing core of the system.

Candidates:

- `relay`
- `event`
- `event_observation`
- `metadata`
- `relay_metadata`

Characteristics:

- append-only or semantically durable;
- protocol-faithful;
- directly grounded in real domain entities;
- expensive to rename or restructure later.

### Category B — Operational/shared state

These represent internal execution state needed for independent services.

Candidate:

- `service_state` or a redesigned but still shared equivalent

Characteristics:

- not public product data;
- not canonical domain facts;
- should remain small, explicit, and highly disciplined.

### Category C — Canonical current facts

These are not raw archive, but still represent meaningful stable “current”
facts, not merely convenience.

Strong candidates:

- `contact_lists_current`
- `contact_list_edges_current`

Characteristics:

- derived from archive, but meaningfully canonical for downstream consumers;
- shared by multiple components;
- support ranking and analytics with stable semantics.

### Category D — Winner indexes / convenience current projections

These represent the current winner for replaceable/addressable/metadata state
but do not necessarily deserve rich duplicated payload storage.

Strong candidates:

- `events_replaceable_current`
- `events_addressable_current`
- `relay_metadata_current`

Target redesign direction:

- make them much slimmer;
- let richer payload be recovered through joins or views;
- only denormalize where the storage cost is truly justified.

### Category E — Analytics and publish-oriented facts

These are canonical enough for the product, but not the same as raw archive.

Examples:

- summary tables;
- NIP-85 fact tables;
- rank snapshot tables.

Characteristics:

- justified by product value;
- may be refreshed or exported;
- should remain clearly downstream of core/current canonical facts.

### Category F — Private compute state

These do not belong in the canonical shared DB unless forced by strong reason.

Examples:

- ranker graph node ids;
- private rank staging tables;
- private DuckDB algorithm state.

Conclusion:

- the canonical PostgreSQL schema should stop pretending these are equivalent
  to regular shared product data.

## 2. Concrete Storage Philosophy

### Storage principle 1 — Every materialized table must earn its bytes

A table is justified if it does at least one of the following:

- represents a real canonical concept;
- enables major shared downstream use;
- enables incremental refresh that would otherwise become fragile or too slow;
- dramatically simplifies high-value read or compute paths.

### Storage principle 2 — Wide current tables are suspicious by default

Duplicating:

- `tags`
- `content`
- `sig`
- large JSON payloads

in current-state tables should be treated as a deliberate exception, not the
default.

### Storage principle 3 — Views and joins are acceptable if they clarify the
model

The redesign should be willing to:

- keep pointer-like current tables;
- expose wider convenience views;
- hide join complexity behind read models and query handlers.

### Storage principle 4 — Do not explode into per-service tables

The project should not replace one generic-ish operational table with:

- `finder_cursor`
- `monitor_checkpoint`
- `validator_candidates`
- `assertor_hashes`

unless those become stable domain concepts in their own right.

## 3. Service Boundary Tightening

### Synchronizer

Desired responsibility:

- fetch canonical Nostr events from relays;
- persist canonical event observations;
- maintain sync cursors.

Should not own:

- ranking-specific structures;
- canonical analytics refresh;
- NIP-85 fact derivation.

### Refresher

Desired responsibility:

- compute canonical current-state and shared analytics facts from the archive.

Should own:

- replaceable/addressable current winners;
- relay metadata current winners;
- contact graph current facts;
- summary tables;
- NIP-85 fact tables.

Should not own:

- private ranking algorithm state;
- public API/DVM contract logic.

### Ranker

Desired responsibility:

- import canonical graph and analytics facts;
- maintain private algorithm state;
- compute and export rank snapshots.

Should not own:

- event ingestion;
- canonical fact derivation;
- generic shared storage structures.

### Assertor

Desired responsibility:

- publish trusted assertions from facts and ranks;
- manage publication checkpoints and provider declarations.

### Api / Dvm

Desired responsibility:

- expose product-level read models;
- remain decoupled from the internal schema shape as much as practical.

## 4. Extension Surface Model

Iteration 2 makes the extensibility story explicit.

### Adding a new service should require

- a local service package;
- a service config model;
- local queries/runtime/helpers;
- registration in the service registry;
- opt-in in a deployment.

### Adding a new NIP should require

- a local NIP module or package;
- parse/build/data logic;
- an optional capability registration point;
- optional use by services or event builders.

### Adding a new deployment should require

- choosing a storage profile;
- selecting enabled services;
- selecting public read models;
- selecting runtime/network/publishing policies.

This leads to a design principle:

- deployments are compositions, not forks.

## 5. Read-Model Strategy

Iteration 2 decides more firmly what the read layer should become.

### Decision

The final architecture should use a **two-layer read model**:

1. a narrow internal query substrate;
2. explicit read-model definitions that own:
   - request validation;
   - handler binding;
   - pagination policy;
   - public naming and exposure.

This means:

- `Catalog` may survive only as a lower-level query facility or transition
  helper;
- it should not remain the conceptual center of the public read contract.

### What not to do

- do not keep “read models” as just pretty names for table names;
- do not create dozens of tiny handlers if they add no semantic value;
- do not preserve schema-driven public behavior merely because it already
  exists.

## 6. Legacy Compatibility Policy

Iteration 2 sets a hard policy appropriate for a draft project:

- once the new path exists and is validated, remove the old path;
- do not leave permanent dual semantics;
- do not keep full-fetch APIs for large operational sets as first-class public
  helpers;
- do not keep deprecated config shapes for comfort.

This is important because without an explicit deletion policy the project will
drift back toward layered historical complexity.

## 7. Naming Policy

Iteration 2 adds an explicit naming policy.

Names should be:

- concept-first;
- stable;
- short enough to be used often;
- explicit enough to be understood without oral tradition.

Likely rename candidates or at least rename-review candidates:

- `Catalog`
- some `current` table names if they mix winner-index and canonical-current
  semantics;
- `Ranker` if the team decides a more explicit name helps more than it hurts;
- any registry whose purpose is descriptive rather than operational.

## 8. Candidate Architecture V2

Iteration 2 target architecture:

1. Canonical archive remains in PostgreSQL.
2. Shared operational state remains centralized and disciplined.
3. Canonical current facts remain only where they are product-relevant and
   semantically meaningful.
4. Wide current winner tables are slimmed down aggressively.
5. Shared derived facts live in PostgreSQL.
6. Private algorithmic compute remains outside canonical storage.
7. Public read surfaces use explicit read models over a thin query substrate.
8. Deployments become explicit compositions of storage profile, service set,
   and public surface.
9. Legacy compatibility paths are actively removed, not tolerated.

## Iteration 2 Findings

### Strong findings

- The redesign should absolutely include a DB/schema phase.
- The storage redesign should center on current winner tables, not the contact
  graph facts.
- Extensibility depends more on shared foundations and composition than on
  plugin systems.
- Public read surfaces need a stronger separation from generic catalog logic.

### Remaining unresolved questions

- What exact final shape should replace wide current winner tables?
- Should `service_state` remain one table or become one table with stricter
  typing conventions?
- Should the NIP registry become foundational or be reduced to documentation?
- How should deployments describe storage profile differences explicitly?

## Audit Of Iteration 2

### What improved over iteration 1

- Stronger schema philosophy;
- clearer service ownership;
- explicit extension surfaces;
- explicit compatibility deletion policy.

### What is still weak

- the target architecture is still not phased;
- exact work ordering and dependencies are still fuzzy;
- the read-model transition still needs a practical migration strategy;
- there is no explicit standard yet for how to validate success after each
  redesign tranche.

### Corrections required in iteration 3

- convert the target architecture into a true phased execution plan;
- define success criteria and exit criteria per workstream;
- explicitly connect each redesign workstream to the stated goals;
- identify the highest-risk decisions and how to de-risk them early.
