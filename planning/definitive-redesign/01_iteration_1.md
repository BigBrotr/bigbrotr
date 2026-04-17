# Iteration 1

## Objective

Iteration 1 exists to do the first broad, systematic pass over the redesign
space.

This iteration should:

- inspect each major architectural area one by one;
- identify strengths, weaknesses, and hidden coupling;
- enumerate the main solution families;
- reject obviously bad directions;
- produce a first candidate architecture.

This is intentionally wide. Precision comes later.

## Method

The analysis in this iteration is organized by viewpoint:

1. product and system identity;
2. domain model;
3. database and storage;
4. service boundaries;
5. public read surfaces;
6. NIP layer and protocol fidelity;
7. runtime and infra foundations;
8. deployments and composition;
9. scalability and data access patterns;
10. testing and verification;
11. naming and maintainability.

For each viewpoint, this iteration records:

- current strengths;
- current problems;
- plausible solution families;
- initial preferred direction.

## 1. Product And System Identity

### Current strengths

- The project has a strong real-world identity: Nostr relay observatory.
- The service split already matches major functional concerns.
- The end-to-end pipeline is coherent.

### Current problems

- Some internal names and boundaries still reflect implementation history more
  than product language.
- Public read surfaces and internal schema concepts are not fully separated.

### Solution families considered

#### Option A — Keep current product shape and only clean internals

Pros:

- lower rewrite risk;
- easier incremental adoption.

Cons:

- likely preserves too many historical compromises;
- does not exploit the draft-phase freedom enough.

#### Option B — Keep product identity but redesign internal structure around
canonical facts and public products

Pros:

- preserves what the product is;
- still allows deep simplification;
- best fit for current freedoms.

Cons:

- requires hard decisions on schema and service boundaries.

#### Option C — Reframe the product more narrowly around one subsystem

Pros:

- maximum simplification.

Cons:

- loses too much value;
- not aligned with what BigBrotr is meant to be.

### Initial decision

Choose **Option B**.

BigBrotr should remain a full relay observatory platform, but its internals can
be reshaped more radically than a production system would allow.

## 2. Domain Model

### Current strengths

- Domain model is typed and validated.
- Relay, event, metadata, and service state concepts are explicit.
- Service independence via shared domain/storage is conceptually strong.

### Current problems

- Some “current state” concepts are domain-worthy, but others are really
  convenience indexes.
- Generic operational state risks becoming semantically overloaded if not kept
  disciplined.

### Solution families considered

#### Option A — Preserve the current domain shape and only rename

Pros:

- safer.

Cons:

- may preserve false equivalence between canonical facts and convenience
  snapshots.

#### Option B — Reclassify the domain into:

- canonical domain facts;
- operational shared state;
- private compute state

Pros:

- much cleaner mental model;
- directly useful for schema redesign.

Cons:

- forces decisions that have downstream migration cost.

### Initial decision

Choose **Option B**.

This classification should be one of the central structural moves of the final
plan.

## 3. Database And Storage

### Current strengths

- Canonical append-only storage for relays, events, and metadata exists.
- Refresh-based derivation is explicit and test-covered.
- Current-state and analytics tables already separate raw archive from
  downstream facts.

### Current problems

- Some current tables duplicate too much payload.
- The schema mixes:
  - canonical facts;
  - convenience current views;
  - analytics outputs;
  - publish-oriented structures.
- Without redesign, storage will likely remain more expensive than necessary.

### Current table observations

Most important observed distinction:

- likely canonical current facts:
  - `contact_lists_current`
  - `contact_list_edges_current`
- likely storage-heavy convenience snapshots:
  - `events_replaceable_current`
  - `events_addressable_current`
  - `relay_metadata_current`

### Solution families considered

#### Option A — Keep all current tables and only optimize indexes

Pros:

- minimal disruption.

Cons:

- does not address conceptual confusion;
- does not remove payload duplication.

#### Option B — Slim current tables into pointer/index tables and move rich
payload access to joins or views

Pros:

- strong storage wins;
- cleaner separation between canonical source and current winner mapping.

Cons:

- more joins in read paths unless hidden behind views/read models.

#### Option C — Replace many tables with views or materialized views

Pros:

- storage reduction;
- clearer “derived, not canonical” semantics.

Cons:

- may make incremental refresh and checkpointing harder for some high-value
  structures.

### Initial decision

Preferred direction is **hybrid B + C**:

- keep a small number of current tables where they represent meaningful
  canonical current facts or important operational checkpoints;
- redesign storage-heavy current tables into much slimmer winner maps or views;
- reserve materialization for structures that genuinely earn it.

## 4. Service Boundaries

### Current strengths

- The service set already reflects coherent business concerns.
- The `Synchronizer` / `Refresher` / `Ranker` split is conceptually close to
  correct.
- Shared database integration instead of service RPC is a major strength.

### Current problems

- Some services still do more orchestration and boundary management than their
  names suggest.
- The `Ranker` name undersells that it is really a private ranking pipeline.
- Service-local operational data and canonical facts are not always clearly
  distinguished in storage.

### Solution families considered

#### Option A — Keep the current service list and only refine boundaries

Pros:

- preserves operational familiarity;
- likely sufficient.

Cons:

- may preserve misleading service names unless explicitly fixed.

#### Option B — Merge or split services radically

Pros:

- might improve purity.

Cons:

- high disruption;
- little evidence that the current top-level service list is wrong.

### Initial decision

Choose **Option A**.

The top-level service list should probably stay mostly intact. The major work is
to clarify what data each service owns and what it should not own.

## 5. Public Read Surfaces

### Current strengths

- Deployment config is already `read_models`-driven.
- API and DVM are already product surfaces rather than direct table lists at
  the config level.

### Current problems

- Backend execution is still largely generic and catalog-backed.
- This leaves a conceptual mismatch:
  - public contract sounds product-shaped;
  - execution path still feels schema-shaped.

### Solution families considered

#### Option A — Keep catalog-backed execution and accept it

Pros:

- simpler to preserve.

Cons:

- may never fully detach product surface from storage structure.

#### Option B — Introduce explicit read-model handlers owned by domain concepts

Pros:

- better product contract integrity;
- easier future extension per read model.

Cons:

- more code if overdone.

#### Option C — Hybrid

- keep a small generic query substrate;
- layer explicit read-model handlers on top for externally significant models.

### Initial decision

Choose **Option C**.

Do not preserve a generic catalog as the conceptual center of the public read
surface, but also do not overbuild a handler forest where a thin shared query
substrate would do.

## 6. NIP Layer And Protocol Fidelity

### Current strengths

- BigBrotr already has first-class implementations for NIP-11, NIP-66,
  and NIP-85 data/event modeling.
- Public surfaces already acknowledge NIP-89 and NIP-90.
- Protocol analysis confirms that the product is aligned with the right subset
  of the NIP universe.

### Current problems

- Some analytics or current-state decisions could accidentally drift from NIP
  semantics if storage convenience dominates design.
- The NIP registry remains more descriptive than central.

### Solution families considered

#### Option A — Keep NIP handling mostly where it is

Pros:

- strong existing fit.

Cons:

- leaves open the question of whether the registry should exist.

#### Option B — Make the registry a stronger protocol capability source

Pros:

- can improve extensibility for future NIPs.

Cons:

- may become a mini-framework.

#### Option C — Reduce the registry and keep NIP modules explicit

Pros:

- simpler.

Cons:

- less centralized extensibility metadata.

### Initial decision

Undecided in iteration 1.

Carry forward:

- either the registry becomes truly useful for capability wiring, or it should
  be simplified;
- no purely decorative registry should survive into the final architecture.

## 7. Runtime And Infrastructure Foundations

### Current strengths

- Service runtime is centralized.
- Database facade exists.
- Protocol client/session boundary already exists.

### Current problems

- these foundations are strong enough that later production migration would be
  expensive;
- therefore they need deliberate stabilization before production.

### Initial decision

Treat these as high-stability foundations:

- core runtime contract;
- Brotr/database façade;
- Nostr client/protocol boundary;
- deployment/config composition model.

## 8. Deployments And Composition

### Current strengths

- BigBrotr and LilBrotr already show that deployments can share architecture
  while diverging in storage profile and public surface.
- Profile-based CLI/default config resolution already exists.

### Current problems

- deployment composition is still more implicit than ideal;
- storage profile differences and semantic fallbacks need a more principled
  place in the design.

### Solution families considered

#### Option A — Keep current deployments as curated config bundles

Pros:

- simple.

Cons:

- may remain too implicit.

#### Option B — Formalize deployments as explicit compositions of:

- schema/storage profile
- enabled services
- public read models
- network/proxy/runtime policies

Pros:

- best extensibility story.

Cons:

- requires clearer deployment model language.

### Initial decision

Choose **Option B**.

This should become one of the final plan’s central extensibility stories.

## 9. Scalability And Data Access Patterns

### Current strengths

- hot loops already use page iterators in Finder, Monitor, and Synchronizer.
- batching and chunking patterns already exist.

### Current problems

- full-fetch helper APIs still exist and imply that all-fetch remains an
  acceptable path for large operational datasets.
- current storage duplication increases long-term cost at scale.

### Initial decision

The final architecture should treat:

- page/stream/batch as the default for large operational sets;
- all-fetch for these sets as an anti-pattern that survives only in narrow
  test/support contexts if at all.

## 10. Testing And Verification

### Current strengths

- integration tests act as real system specification;
- current-state, refresh, ranker, and deployment semantics are all exercised.

### Current problems

- some tests still encode structural assumptions that may change under a
  radical redesign;
- however, their behavioral meaning is too valuable to discard.

### Initial decision

The final plan must preserve a strong distinction between:

- tests that specify behavior and protocol semantics;
- tests that specify temporary internal shape.

## 11. Naming And Maintainability

### Current strengths

- the project is already much better documented than before;
- core concepts are identifiable.

### Current problems

- some names still reflect implementation history more than conceptual truth;
- some abstractions remain slightly more generic than they should be.

### Initial decision

The redesign should be willing to rename aggressively where it improves:

- conceptual honesty;
- discoverability;
- future extension.

## Candidate Architecture V1

Iteration 1 candidate architecture:

1. Preserve the product identity and top-level service set.
2. Reclassify data into:
   - canonical domain facts;
   - operational/shared state;
   - derived current/analytics facts;
   - private compute state.
3. Redesign storage-heavy current tables aggressively.
4. Preserve graph-current tables if they continue to prove their canonical
   value.
5. Keep `Synchronizer`, `Refresher`, and `Ranker` distinct, but tighten what
   each owns.
6. Keep public read surfaces read-model-first, and gradually shift backend
   execution away from catalog-centrism.
7. Treat deployments as explicit compositions rather than loose bundles.
8. Eliminate or constrain full-fetch APIs on large operational datasets.

## Iteration 1 Findings

### Strong findings

- The draft status justifies a much more radical redesign than an ordinary
  production refactor.
- The biggest likely DB/storage win is slimming current winner tables that
  duplicate payload.
- The biggest architecture win is clarifying canonical facts vs private compute.
- The biggest extensibility win is formalizing service/NIP/deployment extension
  surfaces.

### Unresolved findings carried forward

- How far should the read-model layer move away from `Catalog`?
- Should the NIP registry become real or be reduced?
- Which exact current tables should remain materialized?
- How should deployment storage profiles be formalized?

## Audit Of Iteration 1

### What is good

- It correctly identifies the key axes of redesign.
- It does not collapse product identity.
- It is bold enough for a draft-phase project.

### What is weak

- It is still too abstract on the target schema shape.
- It is still too abstract on extension surfaces.
- It does not yet define a concrete execution order.
- It leaves too much room for a half-radical, half-generic read-layer.

### Corrections required in iteration 2

- Make the data classification concrete table by table.
- Make service, NIP, and deployment extension surfaces explicit.
- Decide more firmly what happens to `Catalog`.
- Add concrete design principles for naming, storage, and compatibility
  deletion.
