# DB Consolidation And Remaining Topics

## Purpose

This file records the point at which the DB discussion stopped being a moving
target and became a consolidated foundation for the redesign.

Its job is to make three things explicit:

1. what is now fixed enough to treat as the target DB direction;
2. what wider architecture decisions are now effectively fixed too;
3. what final focused design notes were still needed after the DB block closed.

---

## 1. The DB Block Is Now Consolidated

The schema and efficiency discussion is now considered closed enough that the
implementation plan should stop reopening its fundamentals every time.

The following points are treated as fixed planning direction.

### 1.1 Storage-first shared DB

The shared DB is shaped around canonical storage truths, not around current
service convenience.

That means:

- archive first;
- shared derivation second;
- private compute third;
- public convenience projections last.

### 1.2 Stable canonical concepts

The stable future concepts are:

- `relay`
- `event`
- `event_observation`
- `document`
- `relay_document`
- `service_state`

These are now the conceptual anchor points for future naming and schema work.

### 1.3 Minimal shared schema

Only semantically essential fields should live in the shared DB.

This means:

- no `ingest_id`;
- no generic `updated_at` in `service_state`;
- no casual payload duplication in current tables;
- no helper columns added just to simplify one service’s internal runtime.

### 1.4 Narrow current tables

The current-table direction is fixed:

- current tables are winner maps or narrow indexes;
- rich payload belongs in views, joins, or read-core resources.

### 1.5 Contact graph is not assumed materialized

The contact graph is no longer treated as automatically deserving stored-table
status.

The default future direction is:

- current kind-`3` winners are canonical;
- graph edges are views unless they later prove real shared hot-path value.

### 1.6 Incremental maintenance plus rebuild on destructive change

Derived tables are maintained:

- incrementally on append/update paths;
- from their own canonical upstream sources;
- with rebuild after storage delete/rewrite that breaks correctness.

### 1.7 Huge-DB discipline

The project must always behave as if the DB were already very large.

So the operational defaults are:

- chunking;
- paging;
- keyset/cursor traversal where appropriate;
- bounded scans;
- no full-fetch runtime shortcuts on large sets.

### 1.8 Heavy computation is allowed only if it is controlled

The target is not “no heavy work ever”.

The target is:

- no unnecessary heavy hot-path work;
- no monolithic mandatory recomputation in normal runtime flow;
- chunked, resumable, bounded expensive work where the problem itself requires
  it.

### 1.9 Score stays separate from interaction facts

Canonical interaction facts remain canonical facts.

Algorithmic outputs remain separate score outputs and do not get merged into
interaction-stat tables.

---

## 2. Wider Decisions Now Also Effectively Closed

By the end of the DB discussion, several non-DB architecture questions also
stopped being truly open.

These directions should now be treated as the working target unless later code
inspection exposes a concrete reason to change them.

### 2.1 `Monitor` stays unified

`Monitor` should remain one service.

The right fix is clearer internal sub-boundaries for:

- probing;
- persistence;
- publication.

The right fix is not a forced service split.

### 2.2 `Refresher` owns canonical shared derivation

`Refresher` should own canonical shared derived facts, including the shared
facts needed downstream for NIP-85 and scoring.

### 2.3 `Assertor` owns the full NIP-85 provider package

`Assertor` should publish:

- trusted assertions;
- provider profile;
- trusted-provider list.

This is no longer treated as a narrow “assertions only” service.

### 2.4 Static capability-oriented `NIP_REGISTRY`

The project should keep a formal static NIP registry that represents real
architectural capability bundles.

It should be:

- explicit;
- useful;
- non-magical;
- not a plugin framework.

### 2.5 One semantic read core under all protocol adapters

`api`, `dvm`, and future adapters such as `mcp` are now clearly treated as
protocol adapters over one shared semantic read core.

### 2.6 Deployment folders and YAML-first authoring remain the base model

The preferred deployment model remains:

- one deployment folder;
- YAML-first authoring;
- explicit config and assets per deployment;
- customization by cloning and editing the deployment package, not by forking
  the core codebase.

### 2.7 Hard anti-full-fetch runtime policy

The internal runtime should treat large-set full fetches as forbidden by
default.

### 2.8 Aggressive rename and compatibility-break policy

The redesign should favor:

- correct names;
- decisive cleanup;
- explicit breakage where needed;

over:

- compatibility layers that preserve weak design.

---

## 3. What Was Still Left After That

After all of the above consolidated, only two architecture-shaping design
questions were still worth focused final treatment:

- the exact shape of the protocol-agnostic core read layer;
- the exact deployment contract behind deployment folders and YAML.

Those are now captured directly in:

- [14_core_read_layer_proposal.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/14_core_read_layer_proposal.md)
- [15_deployment_contract_proposal.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/15_deployment_contract_proposal.md)

They were then followed by:

- [17_integral_codebase_validation.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/17_integral_codebase_validation.md)
- [18_code_excellence_standard.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/18_code_excellence_standard.md)
- [19_documentation_rewrite_program.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/19_documentation_rewrite_program.md)

So the planning set has since moved from:

- “close the last two architecture-shaping design questions”

to:

- validate the whole plan against the real codebase;
- elevate code excellence to a first-class redesign goal;
- and treat the documentation rewrite as an explicit redesign program.

So the redesign no longer has a broad cloud of equally-open architectural
questions.

It now has:

- one consolidated DB foundation;
- one mostly-fixed service-boundary model;
- one detailed proposal for the shared read core;
- one detailed proposal for the deployment contract.

---

## 4. Practical Consequence For The Plan

The practical planning consequence is simple:

- the DB philosophy should now be treated as frozen enough for implementation
  planning;
- the service-boundary direction is now stable enough for implementation
  planning;
- the read-layer and deployment questions are no longer vague open topics, but
  focused design proposals with concrete target shape.

This means future work should stop reopening:

- whether the DB is storage-first;
- whether current tables should be narrow;
- whether large-set full fetches are acceptable;
- whether `Monitor` should be split by default;
- whether `Assertor` should stay too narrow;
- whether the NIP registry should remain merely decorative.

Those questions are now effectively closed.

---

## 5. Final Planning Status

The redesign planning set should now be read as:

- `12_best_db_schema.md` for the shared DB target;
- this file for what is now genuinely consolidated;
- `14_core_read_layer_proposal.md` for the final read-core direction;
- `15_deployment_contract_proposal.md` for the final deployment-contract
  direction;
- `17_integral_codebase_validation.md` for the codebase-grounded validation
  record;
- `18_code_excellence_standard.md` for the repository-wide quality standard;
- `19_documentation_rewrite_program.md` for the full documentation rewrite
  scope;
- `16_operational_implementation_plan.md` for the execution protocol and
  tranche-by-tranche implementation discipline;
- `99_definitive_master_plan.md` for the distilled execution plan tying them
  all together.

That is the point where planning stops being architectural exploration and
starts becoming implementation design.
