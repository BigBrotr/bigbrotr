# Review Objects And Open Questions

## Purpose

This file turns the redesign into a set of small review objects that can be
discussed one by one.

Each object includes:

- why it matters;
- the current planning opinion;
- the preferred resolution;
- the specific clarification still needed.

The goal is to review the plan in manageable conceptual groups instead of
trying to approve or reject the whole architecture at once.

## Status Update

The DB and efficiency discussion has since advanced beyond many of the original
open questions in section A.

In particular, the following areas are now substantially consolidated in:

- [12_best_db_schema.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/12_best_db_schema.md)
- [13_db_consolidation_and_remaining_topics.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/13_db_consolidation_and_remaining_topics.md)

This means that objects `1` through `27` should now be read mostly as
historical review prompts, not as equally-open unresolved questions.

The architecture is no longer “wide open” in the way this file originally
assumed. In particular, the following directions are now treated as
substantially fixed:

- storage-first shared DB design;
- narrow current tables and view-first convenience projections;
- hard anti-full-fetch policy for large operational sets;
- one `Monitor` service with clearer internal boundaries;
- full NIP-85 provider-package ownership inside `Assertor`;
- static capability-oriented `NIP_REGISTRY`;
- protocol adapters over one common read core;
- deployment folders and YAML-first deployment authoring.

At this point, the last two architecture-shaping design-closure topics were
concentrated in two reframed areas:

- the final shape of the protocol-agnostic core read layer;
- the final deployment contract and composition model.

Those two topics are captured more directly in:

- [14_core_read_layer_proposal.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/14_core_read_layer_proposal.md)
- [15_deployment_contract_proposal.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/15_deployment_contract_proposal.md)

Their operational execution discipline is then captured in:

- [16_operational_implementation_plan.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/16_operational_implementation_plan.md)

Later files then further closed the loop by:

- validating the plan against the real codebase in
  [17_integral_codebase_validation.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/17_integral_codebase_validation.md)
- making code excellence explicit in
  [18_code_excellence_standard.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/18_code_excellence_standard.md)
- and making the documentation rewrite explicit in
  [19_documentation_rewrite_program.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/19_documentation_rewrite_program.md)

## How To Use This File

The objects are grouped from most foundational to most peripheral:

1. data and schema
2. service boundaries
3. public read surfaces
4. future extensibility
5. simplification and deletion policy
6. execution strategy

The most leverage-heavy objects are:

- `2`
- `4`
- `12`
- `14`
- `17`
- `23`

These are the best first discussion points if the review needs to start with
the highest-impact decisions.

For the current state of the redesign, however, this file should now be read
mainly as:

- historical review context;
- a record of the decision surface that was explored;
- a complement to the more final proposals in `12`, `13`, `14`, `15`, and `99`.

## A. Data Foundations And Schema

### 1. System Data Classes

#### Why this matters

If the system does not clearly distinguish its different data categories, then
schema design, service ownership, read models, and naming all become blurred.

The project currently contains very different kinds of data:

- canonical archive data;
- operational state;
- current facts;
- convenience winner tables;
- analytics facts;
- private compute state.

Treating them as if they were structurally equivalent creates bad decisions
downstream.

#### Current planning opinion

The system should be explicitly divided into:

- canonical archive;
- shared operational state;
- canonical current facts;
- winner/projection tables;
- analytics and product facts;
- private compute state.

This should become an architectural rule, not just an informal explanation.

#### Preferred resolution

Make this taxonomy an explicit part of the redesign and use it to drive:

- schema structure;
- service ownership;
- read surface design;
- naming;
- documentation.

#### Clarification still needed

Should this taxonomy remain mostly an internal design rule, or should it become
highly visible in naming and official documentation too?

### 2. Shared Operational State

#### Why this matters

The project needs shared execution state for independent services, but this can
either stay disciplined or turn into a junk drawer.

The main design choice is whether to keep one shared structure like
`service_state` or split into several operational tables.

#### Current planning opinion

Keeping one shared operational structure is still the best direction if it
stays disciplined.

It avoids an explosion of service-specific tables and supports the project's
goal of keeping the DB small and conceptually clear.

#### Preferred resolution

Keep a single operational state subsystem unless a concept becomes so stable
and semantically distinct that it deserves its own real table.

The default should be one shared operational structure, not a family of
micro-tables.

#### Clarification still needed

Do you want to preserve the principle of one shared operational table
explicitly, or are you open to a very small family of operational tables if
2-3 truly distinct concepts emerge?

### 3. Shape Of The Operational State Table

#### Why this matters

Even if there is one shared state structure, it can be either:

- too generic and opaque;
- or disciplined and legible.

The question is whether the current `type/key/value_json` style should remain
roughly the same or become much more explicit.

#### Current planning opinion

The current direction is useful but too easy to abuse.

One shared table is fine, but it should become more semantically strict and
more self-explanatory.

#### Preferred resolution

Preserve a shared operational store, but make it less opaque through:

- stronger naming;
- stricter type conventions;
- more explicit state codecs;
- less arbitrary JSON where not needed.

#### Clarification still needed

Would you rather keep a fairly generic but highly disciplined structure, or do
you want a more column-explicit and less JSON-shaped operational table?

### 4. Wide Current Winner Tables

#### Why this matters

Some current tables currently do two jobs:

- identify the current winner;
- duplicate a lot of payload.

This increases storage cost and blurs the distinction between canonical source
data and current-state indexing.

The main candidates are:

- `events_replaceable_current`
- `events_addressable_current`
- `relay_metadata_current`

#### Current planning opinion

These are among the strongest DB redesign targets.

They look much more like winner maps or current indexes than true independent
canonical facts.

#### Preferred resolution

Redesign them as narrow pointer-style or winner-index tables, and reconstruct
rich shape through:

- joins;
- views;
- read-model handlers.

#### Clarification still needed

Are you comfortable with a `narrow current table + richer view/read-model`
pattern, even if it makes direct SQL reads less immediately convenient?

### 5. Current Contact Graph

#### Why this matters

The current contact graph is not just a convenience cache. It represents the
current social graph derived from NIP-02 overwrite semantics.

This makes it much closer to a canonical current fact than to a disposable
projection.

#### Current planning opinion

`contact_lists_current` and `contact_list_edges_current` likely deserve to stay
materialized, or at least one of them does.

They seem to provide genuine shared current facts for:

- follower/following counts;
- graph derivation;
- downstream ranking.

#### Preferred resolution

Treat the current contact graph as a canonical current-state concept, not as an
arbitrary convenience snapshot.

#### Clarification still needed

For the contact graph current layer, do you want to optimize more for minimum
storage or for simpler refresh and downstream consumption?

### 6. Current Relay Metadata

#### Why this matters

`relay_metadata_current` appears to carry more denormalized payload than is
architecturally healthy if the goal is a small and explainable schema.

#### Current planning opinion

This is a strong candidate for slimming.

It should probably keep only the information needed to identify the current
winner and the minimum operational fields required for downstream use.

#### Preferred resolution

Make `relay_metadata_current` much narrower and recover richer state through
joins or views.

#### Clarification still needed

Are you willing to give up the convenience of a self-contained current table if
it produces a cleaner and much smaller schema?

### 7. Analytics And Summary Tables

#### Why this matters

If every derived concept becomes a table, the DB will grow in both bytes and
conceptual weight.

The project needs a policy for deciding what deserves physical storage.

#### Current planning opinion

The correct bias is:

- view by default;
- table only if it earns its bytes.

#### Preferred resolution

Materialize only what clearly provides:

- shared downstream value;
- strong performance gain;
- or incremental refresh boundaries that would otherwise become too awkward.

#### Clarification still needed

Do you want an aggressive `view by default` policy, or a somewhat more
pragmatic and conservative one?

### 8. NIP-85 Facts Versus Rank Snapshots

#### Why this matters

Facts and ranks are not the same kind of thing.

Facts are shared product knowledge. Ranks are outputs of a specific algorithm.
Blurring them weakens both the schema and service boundaries.

#### Current planning opinion

Facts belong in canonical shared PostgreSQL. Rank computation belongs in
private compute. Final rank snapshots can be exported back into PostgreSQL.

#### Preferred resolution

Use a strict split:

- facts as canonical shared downstream data;
- private algorithm state outside the canonical DB;
- exported rank snapshots in PostgreSQL only as outputs.

#### Clarification still needed

Should PostgreSQL hold only publishable rank snapshots, or do you also want
some extra algorithm inspection/debugging visibility there?

### 9. BigBrotr Versus LilBrotr

#### Why this matters

These deployments should not drift into separate architectures by accident.

They should represent different compositions or storage profiles of the same
system.

#### Current planning opinion

The architecture should stay shared, with divergence mostly in storage profile,
data fidelity, and exposed surface.

#### Preferred resolution

Preserve architectural siblinghood and make any divergence:

- explicit;
- narrow;
- justified.

#### Clarification still needed

Do you want to maximize schema parity between the two deployments, or are you
comfortable with stronger differences if the storage savings are substantial?

## B. Service Boundaries

### 10. Finder

#### Why this matters

Finder is the producer of relay discovery information. If it becomes too smart,
it starts to overlap with validation or canonicalization.

#### Current planning opinion

Finder should remain discovery-oriented and not absorb validation or canonical
promotion logic.

#### Preferred resolution

Keep Finder focused on discovering candidates and normalizing discovery inputs,
but do not let it become the promotion or validation boundary.

#### Clarification still needed

Should Finder also own stronger source classification and discovery quality
semantics, or should it stay mostly a producer of raw candidates?

### 11. Validator

#### Why this matters

The candidate-to-relay transition should happen in one place only.

Otherwise relay validity becomes ambiguous and upstream/downstream ownership
breaks down.

#### Current planning opinion

Validator should remain the sole promotion boundary from candidate to canonical
relay.

#### Preferred resolution

Preserve this as an explicit architectural invariant.

#### Clarification still needed

Do you want to lock this down as a hard rule: no other service may promote a
relay into the canonical set?

### 12. Monitor

#### Why this matters

Monitor is one of the densest services. It mixes:

- probing;
- persistence;
- protocol shaping;
- publication.

The question is whether it should stay one service or split.

#### Current planning opinion

It can remain one service, but only if its internal boundaries become very
clear.

#### Preferred resolution

Keep one Monitor service but make it a thin orchestrator over clearly separated
subsystems for:

- checks;
- persistence;
- publication.

#### Clarification still needed

Do you want monitor publication to stay inside the Monitor, or would you prefer
publication to become its own service using already-produced monitoring
artifacts?

### 13. Synchronizer

#### Why this matters

Synchronizer should be the canonical archive ingest service. If it gains
analytics or ranking responsibilities, the architecture becomes muddled.

#### Current planning opinion

Synchronizer should stay strictly archive-oriented.

#### Preferred resolution

Keep Synchronizer responsible only for:

- event fetch/streaming;
- archive persistence;
- sync cursors and completeness strategies.

#### Clarification still needed

Do you agree that Synchronizer should be rigorously archive-first and should
not own derived analytics logic?

### 14. Refresher

#### Why this matters

Refresher is the natural owner of canonical current-state and shared analytics
facts.

This decision strongly affects schema, ranker inputs, and downstream semantics.

#### Current planning opinion

Everything that counts as canonical shared derivation should live here,
including NIP-85 facts.

#### Preferred resolution

Make Refresher the sole owner of canonical current-state and shared derived
facts.

#### Clarification still needed

Do you want all canonical NIP-85 facts to live in Refresher without exception,
even where some of them currently feel closer to other services?

### 15. Ranker

#### Why this matters

Ranker is one of the key architectural boundaries in the project.

It should not do ingestion or canonical fact derivation. It should do private
compute.

#### Current planning opinion

The boundary is largely right today. The main question is whether the name
still reflects the real responsibility clearly enough.

#### Preferred resolution

Keep it as a private compute pipeline that imports canonical facts and exports
rank snapshots.

#### Clarification still needed

Do you want to preserve the name `Ranker`, or are you open to renaming it if a
more explicit name improves conceptual clarity?

### 16. Assertor

#### Why this matters

Assertor should stay publication-oriented. If it starts owning too much
provider-identity or metadata logic, its boundary gets muddy.

#### Current planning opinion

Its core job should remain publishing trusted assertions from canonical facts
and rank snapshots.

#### Preferred resolution

Keep Assertor tightly focused on NIP-85 publication, with provider metadata
handled only if it is clearly part of that product story.

#### Clarification still needed

Should Assertor also own official provider profile and `10040` declaration
publication, or should it stay as narrow as possible around assertion
publishing only?

## C. Public Surface And Query Layer

### 17. Catalog

#### Why this matters

Catalog is currently too close to being the conceptual center of the read side.

That makes the public read surface feel more schema-driven than product-driven.

#### Current planning opinion

Catalog should not remain the conceptual center of public reading.

#### Preferred resolution

Reduce Catalog to a lower-level query substrate or support layer. The public
contract should be read-model-first, not catalog-first.

#### Clarification still needed

Do you want a strong conceptual break from Catalog, or are you happy for it to
remain under the hood as long as it disappears from the public architectural
story?

### 18. Explicit Read Models

#### Why this matters

If a read model is only a pretty alias for a table, then the public surface is
still schema-shaped.

#### Current planning opinion

At least the major public read models should become explicit product
definitions.

#### Preferred resolution

Use a read-model layer where important public models own:

- naming;
- request shape;
- handler binding;
- pagination policy;
- API/DVM exposure policy.

#### Clarification still needed

Do you prefer a small number of strong product-shaped read models, or broader
explicit coverage across nearly the whole public surface?

### 19. API Versus DVM

#### Why this matters

API and DVM represent two different channels over what is partly the same data.

The question is how strictly they should align.

#### Current planning opinion

They should share the same semantic read-model core, while keeping different
bindings and protocol behavior where needed.

#### Preferred resolution

One shared read-model domain, with separate HTTP and Nostr delivery layers.

#### Clarification still needed

Do you want near-perfect parity between API and DVM surfaces, or are you happy
with deliberate differences when one channel benefits from them?

### 20. Generic Query Power

#### Why this matters

Too much public genericity turns the product into a schema browser. Too little
genericity can make the surface rigid.

#### Current planning opinion

Internal genericity is useful. Public genericity should remain constrained.

#### Preferred resolution

Keep a thin generic query substrate internally, but expose only a controlled
amount of filtering, sorting, and pagination publicly.

#### Clarification still needed

How much consumer freedom do you want to give up in order to keep the public
surface stable, simpler, and more product-shaped?

## D. Future Extensibility

### 21. Service Registry

#### Why this matters

Adding a new service should be local, obvious, and not magical.

#### Current planning opinion

An explicit simple registry is better than runtime discovery or plugin magic.

#### Preferred resolution

Keep a declarative, explicit service registry and treat registration as a
single intentional step.

#### Clarification still needed

Is one explicit central registration point enough, or do you want service
declaration to become even more manifest-driven?

### 22. NIP Registry

#### Why this matters

The current NIP registry is only worth keeping if it becomes structurally
useful.

#### Current planning opinion

It should either become a real capability registry or be reduced.

#### Preferred resolution

Avoid keeping a decorative registry. Decide between:

- operational capability registry;
- or strong simplification.

#### Clarification still needed

Do you want a real registry for NIP capabilities and future extension, or do
you prefer to keep NIPs explicit and less registry-driven?

### 23. Deployment Model

#### Why this matters

This is one of the most important future-facing decisions.

If deployments are not modeled explicitly, future growth will tend toward forks
and duplicated logic.

#### Current planning opinion

A deployment should be defined as a composition of:

- storage profile;
- service set;
- public read surface;
- runtime/network/publishing policy.

#### Preferred resolution

Make deployment composition an official first-class architectural concept.

#### Clarification still needed

Do you want deployments to remain mostly YAML/config-driven, or are you open to
slightly stronger Python-side structure if it makes the model more explicit and
robust?

### 24. Storage Profiles

#### Why this matters

BigBrotr and LilBrotr already imply that storage profile is a first-class axis
of the architecture.

#### Current planning opinion

Storage profile should become an explicit concept, not just an accidental
deployment difference.

#### Preferred resolution

Support the idea that the system may have multiple official storage profiles,
while still sharing the same overall architecture.

#### Clarification still needed

Do you want future profiles such as `tiny`, `archive-heavy`, or
`analytics-heavy` to be a supported idea, or do you expect the project to stay
with just a very small fixed set?

## E. Simplification And Deletion Policy

### 25. Full-Fetch APIs

#### Why this matters

On datasets like relay sets and cursor sets, all-fetch APIs are a structural
risk at BigBrotr scale.

#### Current planning opinion

They should not survive as normal runtime-facing patterns for large operational
sets.

#### Preferred resolution

Make page/stream/batch the default and constrain all-fetch to narrow support or
test-only contexts, if it survives at all.

#### Clarification still needed

Do you want a strict rule like “forbidden in runtime, tolerated only in
test/support contexts”, or a softer policy?

### 26. Compatibility Layers

#### Why this matters

Draft projects often rot by keeping dual semantics for too long.

#### Current planning opinion

Compatibility layers should be short-lived and aggressively deleted once the
better path is validated.

#### Preferred resolution

Break early and cleanly rather than carrying two models for long periods.

#### Clarification still needed

Are you comfortable with a strong break policy on config, naming, and public
paths if it leads to a much better final architecture?

### 27. Renaming Large Concepts

#### Why this matters

Misleading names impose a constant mental tax on the whole project.

#### Current planning opinion

Rename when the current name truly lies or strongly misleads.

#### Preferred resolution

Use renames selectively but decisively where they improve conceptual honesty.

#### Clarification still needed

When continuity and semantic correctness conflict, which do you want to prefer
more strongly?

## F. Execution Strategy

### 28. Schema-First Versus Services-First

#### Why this matters

If service refactors happen before the target data model is fixed, they risk
being locally clean but globally wrong.

#### Current planning opinion

The redesign should start with foundations and target data shape, then align
services to that model, then finalize public surfaces.

#### Preferred resolution

Use a schema-aware and foundation-first execution order.

#### Clarification still needed

Would you rather review the target database vision first, or the target
service-architecture vision first?

### 29. Tranche Size

#### Why this matters

Too many tiny steps lose the big picture. One giant opaque phase is hard to
review.

#### Current planning opinion

The best balance is a small number of large, sharply defined workstreams.

#### Preferred resolution

Use a handful of big tranches or workstreams with clear scope and strong review
points.

#### Clarification still needed

Do you prefer a more compact decisive plan, or one split into many smaller
reviewable pieces?

### 30. Technical Spikes

#### Why this matters

Some architectural decisions may benefit from a narrow prototype or validation
step before implementation freezes.

#### Current planning opinion

Spikes should be used only for a few truly risky areas, not as a substitute for
planning.

#### Preferred resolution

Allow small focused spikes only where they reduce real uncertainty, such as
current winner table redesign or read-layer execution shape.

#### Clarification still needed

Do you want to reserve space for a few technical spikes before implementation,
or would you rather freeze the architecture and go straight into execution?
