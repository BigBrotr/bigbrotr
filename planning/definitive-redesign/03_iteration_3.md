# Iteration 3

## Objective

Iteration 3 turns the revised target architecture into a plan that is actually
executable and reviewable.

This iteration must:

- sequence the redesign;
- define workstreams;
- define success criteria;
- identify high-risk decisions;
- perform a final internal audit of completeness, consistency, and ambition.

## Carry-Forward From Iteration 2

Iteration 2 left four big needs:

- a true phase order;
- explicit acceptance criteria;
- de-risking strategy;
- a final consistency audit.

Iteration 3 resolves those.

## 1. Workstream Structure

The redesign should be executed as explicit workstreams rather than a vague
single “rewrite”.

### Workstream A — Foundations

Purpose:

- stabilize and clarify the foundations that will become expensive to migrate
  in production.

Includes:

- runtime contract;
- Brotr/query boundary;
- protocol boundary;
- naming principles;
- extension-surface policy.

### Workstream B — Canonical data model and schema redesign

Purpose:

- redesign the PostgreSQL schema around:
  - canonical archive;
  - operational/shared state;
  - canonical current facts;
  - analytics facts;
  - lean winner indexes.

Includes:

- current/winner table redesign;
- classification of derived tables;
- storage-profile strategy for BigBrotr vs LilBrotr.

### Workstream C — Service boundary convergence

Purpose:

- align services to their intended ownership model.

Includes:

- Synchronizer boundary tightening;
- Refresher ownership of canonical current/facts;
- Ranker ownership of private compute;
- Assertor consumption and publication boundary cleanup;
- Monitor and Finder cleanup where needed.

### Workstream D — Public read surfaces

Purpose:

- make API and DVM product-shaped and clearly detached from schema-first
  thinking.

Includes:

- explicit read-model handler ownership;
- reduced catalog centrality;
- handler/discoverability contracts.

### Workstream E — Deployment composition

Purpose:

- make deployments explicit architectural compositions instead of implicit
  bundles.

Includes:

- storage profile selection;
- enabled services;
- enabled public read models;
- runtime/policy choices;
- deployment authoring guidance.

### Workstream F — Convergence and deletion

Purpose:

- remove old paths, aliases, duplicate helpers, and stale abstractions.

Includes:

- deletion of full-fetch APIs on large operational sets where not justified;
- deletion of old config shapes;
- deletion of obsolete read paths;
- renaming cleanups;
- documentation convergence.

## 2. Phase Order

Iteration 3 defines the preferred phase order.

### Phase 1 — Design foundations and invariants

Must define first:

- canonical data categories;
- service ownership rules;
- extension surface rules;
- naming and deletion policy.

Why first:

- every later workstream depends on these decisions.

### Phase 2 — Schema redesign and storage profile redesign

Must define second:

- what the final PostgreSQL model is;
- what remains in PostgreSQL;
- what moves to views or slimmer winner indexes;
- how BigBrotr and LilBrotr differ in storage profile.

Why second:

- every service and read model sits on top of the data model.

### Phase 3 — Refresher / Ranker / analytics convergence

Must define third:

- canonical current and fact production;
- private compute inputs and outputs;
- NIP-85 production pipeline shape.

Why third:

- this is the deepest downstream data contract.

### Phase 4 — Synchronizer / Monitor / Finder convergence

Must define fourth:

- final event ingestion responsibilities;
- final discovery responsibilities;
- final monitoring/publication responsibilities;
- final batching/pagination API rules.

Why fourth:

- depends on the schema and fact model being known.

### Phase 5 — Public read surface redesign

Must define fifth:

- read-model handler structure;
- API and DVM contract;
- deployable public surface composition.

Why fifth:

- this should reflect the now-stable internal facts, not drive them.

### Phase 6 — Deployment model, deletion pass, docs, and test convergence

Must define last:

- deployment authoring shape;
- dead-path deletion;
- final docs;
- final behavior-vs-structure test cleanup.

Why last:

- it converges the architecture after the deeper substrate is in place.

## 3. High-Risk Decisions And How To De-Risk Them

### Risk 1 — Oversimplifying current-state storage and breaking useful
incremental refresh

Mitigation:

- treat each current table separately;
- preserve materialization where it clearly supports canonical current facts or
  expensive shared use;
- prototype the pointer-table + view pattern mentally and against the current
  test spec before adopting it broadly.

### Risk 2 — Overbuilding the read-model layer

Mitigation:

- keep a thin query substrate;
- demand that any explicit handler earn its abstraction cost;
- do not create a handler just to wrap a table one-to-one.

### Risk 3 — Under-specifying deployment composition

Mitigation:

- define deployment composition explicitly as:
  - storage profile
  - service set
  - public surface
  - runtime policy

### Risk 4 — Letting `service_state` become a junk drawer again

Mitigation:

- keep one shared operational state model only if it stays disciplined;
- define strict semantic conventions for state types and keys;
- move any truly canonical concept out of it.

### Risk 5 — Accidental protocol drift in analytics

Mitigation:

- keep NIP fidelity as a design review gate;
- continue using integration tests as behavioral specification;
- treat NIP-01, NIP-02, NIP-11, NIP-42, NIP-65, NIP-66, NIP-73, NIP-85,
  NIP-89, and NIP-90 as non-negotiable protocol anchors.

## 4. Success Criteria For Each Workstream

### Foundations success criteria

- the project can clearly answer which concepts are canonical, operational, or
  private;
- new service/NIP/deployment extension points are explicit.

### Schema success criteria

- wide duplicated current tables are either justified or removed;
- the schema becomes more explainable and less storage-wasteful;
- no explosion of feature-specific tables.

### Service convergence success criteria

- each service owns a clearer, narrower responsibility band;
- `Ranker` is fully downstream of canonical shared facts;
- large-dataset operational paths default to batching/paging.

### Public surface success criteria

- API and DVM are explainable without starting from table names;
- read models are stable product concepts.

### Deployment success criteria

- a new deployment can be described as a composition rather than a fork;
- BigBrotr and LilBrotr differences are principled and explicit.

### Convergence success criteria

- old duplicate paths are removed;
- docs tell the same story as the architecture;
- tests primarily guard behavior and protocol semantics.

## 5. Candidate Architecture V3

Iteration 3 target:

- a leaner canonical PostgreSQL schema;
- explicit distinction between canonical facts and private compute;
- services aligned to data ownership;
- read models as true product surfaces;
- deployments as explicit compositions;
- no permanent legacy paths.

## Final Audit Of Iteration 3

### Consistency check

The architecture is internally consistent if:

- the DB is not expected to be both canonical truth and arbitrary convenience
  cache at the same time;
- services do not compete for the same ownership responsibility;
- read surfaces do not expose storage accidents as product concepts;
- deployment variability does not require architectural forks.

Result:

- passes.

### Ambition check

The redesign is radical enough if:

- it includes schema redesign;
- it includes naming redesign;
- it includes deletion of duplicate paths;
- it does not preserve legacy behavior purely for comfort.

Result:

- passes.

### Practicality check

The redesign is still practical if:

- it preserves the top-level service list;
- it uses existing strong ideas where they are already correct;
- it does not invent a plugin framework or a totally new runtime model.

Result:

- passes.

### Extensibility check

The redesign supports future growth if:

- service, NIP, and deployment addition are localized;
- foundations are shared and stable;
- public surfaces are explicit;
- data ownership is clear.

Result:

- passes.

### Remaining reservations

- the final plan will still need explicit decisions on exact table-by-table
  redesign;
- a future implementation pass will need to turn naming review into actual
  rename choices.

These are execution details, not blockers to the architecture direction.

## Changes To Carry Into The Final Plan

The final plan should therefore:

- be unapologetically schema-aware;
- be explicit about phase order;
- be explicit about deletion policy;
- be explicit about extensibility surfaces;
- be explicit about storage philosophy and table classification;
- be explicit about success criteria.
