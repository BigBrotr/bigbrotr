# Definitive Master Plan

## Executive Summary

BigBrotr should be redesigned as a draft-phase, storage-first, protocol-aware,
extension-friendly Nostr observability platform.

The right goal is not to preserve the current shape with minimal disturbance.
The right goal is to establish the best long-term shape while the project is
still early enough to make decisive corrections.

The final redesign direction is now clear:

- a canonical shared DB built around stable storage concepts;
- narrow current tables and disciplined shared derivation;
- private compute where specialization is justified;
- one protocol-agnostic read core under all read adapters;
- folder-based YAML-first deployments with explicit storage profiles and
  exposure policy;
- a static capability-oriented NIP registry;
- service boundaries aligned to real ownership instead of historical drift;
- library-grade `src/` APIs and documentation;
- a repository-wide documentation rewrite;
- and a codebase-wide push to uniformly excellent code quality.

The execution starting point is also now clear:

- implementation should begin from the `nip85-hardening` line of work,
  because that branch already contains a significant share of the preparatory
  structural refactors the redesign assumes.

This plan therefore aims to:

- stabilize foundations;
- remove low-value duplication;
- formalize extension surfaces;
- align services to clear ownership;
- keep the system faithful to relevant NIPs;
- make the project robust for very large datasets and future deployments;
- make `src/` cleaner and more usable as a Python library;
- rewrite repository and `docs/` documentation around the final system shape;
- raise the whole codebase to a consistently excellent professional standard.

The detailed execution companion for this master plan is:

- [21_canonical_rename_ledger.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/21_canonical_rename_ledger.md)
- [22_final_contract_freeze.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/22_final_contract_freeze.md)
- [17_integral_codebase_validation.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/17_integral_codebase_validation.md)
- [18_code_excellence_standard.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/18_code_excellence_standard.md)
- [19_documentation_rewrite_program.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/19_documentation_rewrite_program.md)
- [16_operational_implementation_plan.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/16_operational_implementation_plan.md)
- [20_redesign_execution_ledger.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/20_redesign_execution_ledger.md)

This master plan should be read together with the integral validation,
code-excellence, and documentation-rewrite companions, because the redesign
has now been checked against the real codebase and raised to explicit
repository-wide quality standards rather than remaining only a planning
abstraction.

The execution ledger is part of that discipline too:

- the redesign must always have an up-to-date human-readable record of what is
  complete;
- what audit findings were raised and resolved;
- what follow-ups remain;
- and what work packages are still ahead.

The canonical compact freeze of execution baseline and planning-file
precedence now lives in:

- [22_final_contract_freeze.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/22_final_contract_freeze.md)

---

## Non-Negotiable Design Principles

### 1. Stable center, extensible edges

The following must become deliberate and stable:

- canonical data model;
- shared operational-state model;
- shared derivation ownership;
- protocol-agnostic read core;
- deployment contract;
- NIP capability model.

The following must remain easy to extend:

- services;
- deployments;
- storage profiles;
- protocol adapters;
- NIP-aware capabilities;
- private scoring/ranking engines.

### 2. Storage first

The final system is built in this order:

1. canonical archive;
2. canonical shared derivation;
3. private compute where needed;
4. public read and publication surfaces.

### 3. Huge-DB discipline

The project must always be designed as if the DB were already very large.

This means:

- chunked runtime traversal;
- bounded scans;
- page-first and cursor-first reads;
- no large-set full-fetch helpers in normal runtime flow;
- heavy work only when bounded, resumable, and off the hot path.

### 4. Derived tables must earn their bytes

A stored derived structure is justified only when it represents:

- canonical shared meaning;
- strong shared downstream value;
- an important incremental refresh boundary;
- or a real performance win worth the storage cost.

### 5. Public surfaces are controlled resource exposure, not schema mirroring

The public read side must expose deployment-approved readable resources through
one shared read core, not act as a generic schema browser.

### 6. Draft-first means decisive cleanup

Because the project is still draft:

- naming should be corrected aggressively where wrong;
- compatibility layers should not linger;
- the better path should replace the weaker path cleanly and deliberately.

### 7. Code excellence is a first-class redesign goal

The redesign is not only about target architecture.
It is also about codebase quality.

That means the final state must deliver:

- semantically honest names and abstractions;
- slim and bounded implementations;
- consistent patterns across equivalent layers;
- library-grade API and documentation quality in `src/`;
- high-quality repository documentation and `docs/` information architecture;
- code that is easier to read, reason about, and trust;
- removal of weak historical shapes that survive only by inertia.

---

## Target Architecture

## 1. Canonical Shared Data Model

The final shared PostgreSQL model is organized into five bands.

### Band A — Canonical archive

The durable archive consists conceptually of:

- `relay`
- `event`
- `event_observation`
- `document`
- `relay_document`

These are the shared durable truths the rest of the system builds on.

### Band B — Shared operational state

Keep one disciplined shared operational-state subsystem centered on
`service_state`.

The rule is:

- shared operational persistence by default;
- bespoke service tables only if a concept becomes a real canonical shared
  concept.

### Band C — Shared current and derived facts

Materialize only the current and derived facts that clearly earn storage.

Strong candidates include:

- narrow current winner tables;
- shared summary tables;
- shared interaction facts.

Contact-graph projections should remain views by default unless proven to have
strong shared hot-path value.

### Band D — Public score outputs

Private scoring or ranking compute may export minimal public score outputs back
to PostgreSQL when the rest of the system needs them.

These remain separate from canonical interaction facts.

### Band E — Views and convenience projections

Convenience shape belongs in:

- views;
- materialized views where justified;
- read-core resources.

It does not belong in wide current tables by default.

---

## 2. Service Ownership Model

### Seeder

- bootstraps candidate relay inputs;
- remains intentionally small.

### Finder

- owns discovery of relay candidates;
- keeps large scans chunked and paged;
- does not promote relays into the canonical pool.

### Validator

- remains the single promotion boundary from candidate to canonical relay.

### Monitor

- owns relay probing;
- owns relay-document persistence;
- owns relay-oriented protocol publication;
- remains one service with clearer internal sub-boundaries.

### Synchronizer

- owns canonical event ingestion;
- remains archive-facing;
- does not absorb analytics or scoring logic.

### Refresher

- owns canonical shared derivation;
- maintains current tables, summary tables, and shared interaction facts;
- remains the authoritative producer of downstream shared facts.

### Ranker

- owns private score computation;
- reads canonical shared facts;
- writes back only minimal public score outputs where needed.

### Assertor

- owns publication of the full NIP-85 provider package:
  - trusted assertions;
  - provider profile;
  - trusted-provider list.

### Api / Dvm / future adapters

- own protocol delivery only;
- depend on one shared semantic read core;
- expose deployment-approved readable resources under adapter-specific policy.

---

## 3. Public Read Architecture

The final read side is built around a protocol-agnostic read core.

### Layer 1 — Relation engine

Keep `Catalog` as the relation-oriented execution engine for:

- safe relation discovery;
- safe list queries;
- safe identity lookups;
- generic pagination;
- generic filter and sort enforcement.

### Layer 2 — Readable-resource registry

Define stable readable resources above raw relation discovery.

Each readable resource should describe:

- stable resource ID;
- relation or handler backing;
- allowed filters and sorts;
- pagination capabilities;
- discovery metadata.

### Layer 3 — Shared read core

The read core should:

- resolve deployment-available resources;
- validate and execute resource reads;
- route relation-backed resources into `Catalog`;
- route special resources into handlers when needed;
- normalize errors and result envelopes.

### Layer 4 — Protocol adapters

Each adapter such as `api`, `dvm`, or future `mcp` should:

- parse protocol-native inputs;
- apply protocol-specific exposure policy;
- call the shared read core;
- format protocol-native outputs.

This is the final read-side direction.

---

## 4. NIP And Capability Strategy

BigBrotr should remain sharply focused on the NIPs that matter most to the
product.

The architectural rule is:

- keep a **static capability-oriented NIP registry**;
- let it describe real architectural facts such as event kinds, document
  families, capability bundles, and service/publication relevance;
- do not turn it into a plugin framework.

This gives the project a formal and future-proof NIP surface without runtime
magic.

---

## 5. Deployment Model

Deployments should remain folder-based, YAML-first compositions of:

- storage profile;
- enabled services;
- protocol exposure policy;
- runtime and publication policy;
- network/proxy policy;
- deployment-local infra and assets.

This means:

- keep deployment folders;
- keep local config and infra files;
- treat `bigbrotr` and `lilbrotr` as first-class reference deployments;
- formalize the contract instead of replacing the model.

---

## 6. Extension Surface Model

### New service

Requires:

- service package;
- config model;
- registry integration;
- deployment opt-in.

### New NIP capability

Requires:

- local parsing/building/data logic;
- capability registration if architecturally relevant;
- service or publication integration where needed.

### New protocol adapter

Requires:

- adapter package;
- mapping into the shared read-query contract;
- adapter-specific exposure policy and formatting.

### New deployment

Requires:

- one deployment folder built from the reference shape;
- storage-profile choice;
- service-set choice;
- protocol exposure choice;
- infra/runtime customization.

---

## 7. Naming Strategy

Naming is part of the redesign itself.

The rules are:

- prefer conceptual names over historical names;
- rename aggressively where the current name lies about the concept;
- avoid rename churn only where the existing name is already semantically good;
- do not preserve weak names just for comfort.

Examples of the desired direction include:

- `document` over `metadata`;
- `event_observation` over `event_relay`;
- `score` over `raw_score` or stored ordinal rank.

The canonical source for rename execution is:

- [21_canonical_rename_ledger.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/21_canonical_rename_ledger.md)

---

## 8. Efficiency Rules

The system-wide performance rules are:

- no large-set full-fetch runtime patterns;
- no mandatory hot-path full rebuilds;
- chunked and resumable maintenance for heavy derivations;
- partitioning only where archive scale justifies it;
- read/query contracts designed for bounded traversal;
- views preferred over stored duplication when cost is acceptable.

---

## 9. Implementation Program

For the operational execution discipline, package-level audit loop, and commit
gates, use:

- [16_operational_implementation_plan.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/16_operational_implementation_plan.md)

## Phase 1 — Freeze names, targets, and contracts

Deliver:

- final naming decisions;
- target shared DB schema;
- final read-core design;
- final deployment contract.

This phase is mostly planning and contract freezing.

## Phase 2 — Rebuild the storage and schema foundations

Deliver:

- canonical storage schema changes;
- narrow current-table shapes;
- shared operational-state alignment;
- derived-table and view policy cleanup.

## Phase 3 — Align Python domain models and DB interfaces

Deliver:

- Python model alignment to the target schema semantics;
- `Brotr` and stored-procedure interface alignment to the new contracts;
- test updates that enforce the new shared model shape.

## Phase 4 — Align derivation and maintenance pipelines

Deliver:

- incremental refresh boundaries aligned to the new schema;
- rebuild-on-delete semantics;
- chunked/heavy-work maintenance paths where needed;
- removal of large-set full-fetch operational helpers.

## Phase 5 — Align service boundaries

Deliver:

- unified `Monitor` internal structure;
- `Refresher` ownership of canonical shared derivation;
- `Assertor` ownership of the full NIP-85 provider package;
- cleanup of service responsibilities that no longer match the target model.

## Phase 6 — Build the protocol-agnostic read core

Deliver:

- readable-resource registry;
- shared read core over `Catalog`;
- API migration onto the shared read core;
- DVM migration onto the shared read core;
- adapter policy boundary ready for future `mcp`.

## Phase 7 — Formalize deployment folders and storage profiles

Deliver:

- explicit deployment contract documentation;
- deployment config cleanup and normalization;
- clearer storage-profile meaning;
- cleaner path for authoring new deployments from the reference folder shape.

## Phase 8 — Rewrite documentation around the final system

Deliver:

- rewritten in-code public documentation where needed;
- rewritten `docs/` information architecture and narrative;
- coherent folder-level `README.md` coverage across maintained project
  surfaces;
- rewritten operator, deployment, and contributor docs;
- coherent alignment between narrative docs and generated reference docs.

## Phase 9 — Remove compatibility cruft and finalize language

Deliver:

- removal of old naming and partial compatibility layers;
- final repository cleanup and consistency pass;
- final code-excellence and repository-surface closeout pass;
- final audit against the target architecture.

---

## 10. Main Risks And Mitigations

### Risk 1 — Read-core abstraction becomes too weak or too magical

Mitigation:

- keep `Catalog` as strong concrete infrastructure;
- build readable-resource descriptors above it;
- keep the core explicit and static.

### Risk 2 — Deployment contract remains implicit

Mitigation:

- document the folder contract clearly;
- formalize required and optional files;
- keep YAML central and concrete.

### Risk 3 — Schema work reopens basic philosophy repeatedly

Mitigation:

- treat the DB block as closed enough;
- use `12` and `13` as the canonical schema-planning references.

### Risk 4 — Heavy derivations leak into hot paths

Mitigation:

- hard no-full-fetch policy;
- chunking and resumability by design;
- rebuild only on destructive storage changes.

---

## 11. Definition Of Done

The redesign should be considered successful when:

- the shared DB matches the storage-first target model;
- derived tables and views follow the final maintenance philosophy;
- services own the right boundaries;
- `Monitor` remains unified but clearer;
- `Assertor` publishes the full NIP-85 provider package;
- the NIP registry is formal and useful;
- `api`, `dvm`, and future adapters sit over one shared read core;
- deployments are clearly defined as folder-based YAML-first compositions;
- `src/` is materially cleaner and easier to use as a Python library;
- the whole repository meets one uniformly high quality standard rather than
  splitting into “core” and “secondary” quality zones;
- repository documentation has been deliberately rewritten around the final
  system shape;
- meaningful maintained folders have coherent local `README.md` and guidance
  surfaces;
- the codebase no longer depends on weak historical naming or compatibility
  scaffolding.

That is the final architecture this master plan is intended to deliver.
