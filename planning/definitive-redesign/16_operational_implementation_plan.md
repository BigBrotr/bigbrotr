# Operational Implementation Plan

## Purpose

This file turns the redesign from an architectural decision set into an
**execution program**.

It is intentionally operational and strict.

The goal is not merely to list phases.
The goal is to define:

- the exact execution discipline;
- the order of work;
- the audit loop that must happen after every work package;
- the test and commit gates that block progression;
- the progress-ledger discipline that keeps execution state explicit;
- the concrete tranche structure that should be followed to implement the
  redesign with professional rigor.

This document should be treated as the working execution companion to:

- [21_canonical_rename_ledger.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/21_canonical_rename_ledger.md)
- [12_best_db_schema.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/12_best_db_schema.md)
- [14_core_read_layer_proposal.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/14_core_read_layer_proposal.md)
- [15_deployment_contract_proposal.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/15_deployment_contract_proposal.md)
- [17_integral_codebase_validation.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/17_integral_codebase_validation.md)
- [18_code_excellence_standard.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/18_code_excellence_standard.md)
- [19_documentation_rewrite_program.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/19_documentation_rewrite_program.md)
- [20_redesign_execution_ledger.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/20_redesign_execution_ledger.md)
- [99_definitive_master_plan.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/99_definitive_master_plan.md)

---

## 1. Execution Standard

The implementation standard is intentionally very high.

That means:

- no casual refactors;
- no mixed-scope commits that blur multiple architectural moves;
- no “good enough” review;
- no moving forward with unresolved audit findings just because tests happen to
  pass;
- no slices that reach target behavior while leaving obviously weak code
  quality behind;
- no weak compatibility layers left in place merely for comfort.

The execution standard is:

1. understand deeply;
2. change narrowly and deliberately;
3. audit critically;
4. fix findings;
5. re-audit;
6. run full verification;
7. commit only when the slice is genuinely solid.

This standard applies to **every work package**, not only to the end of a
tranche.

---

## 2. Non-Negotiable Working Rules

## 2.1 One closed work package at a time

Each work package must be:

- narrow enough to reason about clearly;
- broad enough to be architecturally meaningful;
- finished completely before the next one starts.

No half-finished slices should be left behind.

## 2.2 No progression past red flags

If audit reveals:

- architectural mismatch;
- naming dishonesty;
- broken boundedness assumptions;
- test weakness;
- questionable performance behavior;
- suspicious service-boundary leakage;

the work package is **not done**.

It must be fixed and re-audited before progressing.

## 2.3 Every change is reviewed as if it were a PR

Even when working locally, every work package must end with a critical review
pass equivalent to a serious PR review:

- correctness;
- regressions;
- performance;
- maintainability;
- naming quality;
- test adequacy;
- boundary compliance.

## 2.4 Full quality gate before every commit

No work package is committed before:

- targeted tests are green;
- full repository verification is green;
- audit findings are resolved;
- the resulting diff is coherent and intentional.

The minimum final gate for each commit is:

```bash
make ci
uv lock --check
```

If the work package touches schema generation or deployment SQL, also verify:

```bash
python tools/generate_sql.py --check
```

If `make ci` already covers this, still treat the SQL check as an explicit
audit concern in the review.

## 2.5 Descriptive commits only after clean closure

Every work package ends with a descriptive conventional commit only after it is
fully closed.

Commit messages should explain **why** the slice exists, not merely what files
changed.

## 2.6 Branch and integration discipline

Execution should follow the project git workflow strictly:

- all work happens on feature branches from `develop`;
- no direct work lands on `main`;
- no direct work lands on `develop`;
- commit messages remain conventional and descriptive;
- each work package should normally map to one coherent commit after it is
  fully green and audited.

If a branch starts accumulating too many semantically different packages, stop
and split the work before the audit quality degrades.

## 2.7 Execution ledger and checklist discipline

The redesign must never rely on memory alone to know what has been completed,
what changed in a given slice, and what still remains.

That means execution must maintain one explicit progress ledger/checklist that
is updated continuously during the program.

The ledger must record, at minimum:

- tranche status;
- work-package status;
- the commit(s) that closed each work package;
- the main files and surfaces touched by each work package;
- audit findings that were raised and how they were resolved;
- follow-up items that remain intentionally open;
- remaining risks or watch points for later tranches.

The purpose is not bureaucratic ceremony.
The purpose is:

- always knowing exactly what is done;
- always knowing exactly what is in progress;
- always knowing exactly what remains;
- never losing critical migration context between slices.

No work package should be considered truly closed until the ledger/checklist
has been updated to reflect the final reality of the slice.

---

## 3. Standard Work-Package Loop

This loop must be followed for every numbered package in this plan.

## 3.1 Study first

Before editing:

- read the relevant code;
- read the relevant package documentation;
- identify current invariants;
- identify all directly affected tests and configs;
- identify likely indirect break points.

No code should be changed before the current behavior is understood.

## 3.2 Freeze the intended delta

Before editing:

- define the exact architectural purpose of the slice;
- define what is in scope;
- define what is deliberately out of scope;
- define the expected user-visible or system-visible behavior after the change.

If the intended delta is still fuzzy, stop and tighten it before coding.

## 3.3 Implement the minimal closed slice

Change only what is needed to complete that slice end-to-end.

Avoid:

- speculative cleanup;
- unrelated renames;
- opportunistic abstractions;
- “while I’m here” architectural drift.

## 3.4 Run targeted validation immediately

After the slice compiles, run targeted checks first:

- the most relevant unit tests;
- service-local tests;
- SQL generator checks if applicable;
- focused command runs for any touched surface.

This catches obvious regressions before the deeper audit.

## 3.5 Perform a first severe audit

Review the diff critically against the audit checklist in section 4.

The review must ask:

- is the change actually correct;
- is the boundary cleaner or dirtier;
- is the design more honest or merely different;
- did any hidden convenience logic creep into the wrong layer;
- did any unbounded behavior slip in;
- are naming and config now better than before.

## 3.6 Fix findings, then re-audit

If the audit reveals issues:

- fix them;
- rerun the targeted checks;
- re-audit the updated diff.

This loop repeats until the slice looks solid under critical review.

## 3.7 Run the full verification gate

Only after targeted validation and local audit are clean:

- run `make ci`;
- run `uv lock --check`;
- confirm the repo remains green.

## 3.8 Update the execution ledger

Before committing, update the redesign execution ledger/checklist to reflect:

- what was completed;
- what files and contracts actually changed;
- what audit findings were discovered;
- what was fixed before closure;
- what deliberate follow-up remains, if any;
- what the next intended work package is.

This update is part of the closure protocol, not optional aftercare.

## 3.9 Final diff review

Before committing:

- inspect the final diff once more;
- ensure the scope still matches the intended slice;
- ensure no temporary crutches or stray churn remain;
- ensure the commit is still easy to explain in one sentence.

## 3.10 Commit and stop

Commit only when the slice is closed and green.

Do not begin the next work package before the current one has fully landed in a
clean state.

---

## 4. Mandatory Audit Checklist

Every work package must be audited across all of these dimensions.

## 4.1 Correctness audit

Check:

- logic correctness;
- data-shape correctness;
- state transitions;
- behavior under empty and edge cases;
- failure behavior;
- invariants preserved or improved.

## 4.2 Architecture audit

Check:

- responsibility stays in the right layer;
- no new service-to-service leakage;
- no service-private convenience structures forced into shared architecture;
- no read-layer logic drifting into protocol adapters;
- no protocol concerns drifting into core layers.

## 4.3 Performance and boundedness audit

Check:

- no new full-fetch paths on large operational sets;
- traversal is chunked or paginated where required;
- queries are indexable and bounded;
- derivations are incremental or consciously rebuild-based;
- heavy work is resumable or isolated from the hot path.

## 4.4 Schema and SQL audit

When SQL is touched, check:

- column semantics are honest;
- names match the target architecture;
- current tables stay narrow where intended;
- views and tables are chosen for the right reasons;
- indexes match the access pattern;
- profile-specific templates remain coherent;
- cleanup logic does not encode false domain assumptions.

## 4.5 Async/runtime audit

When service code is touched, check:

- cancellation safety;
- checkpoint correctness;
- retry and failure boundaries;
- no broad exception swallowing;
- no hidden concurrency hazards;
- no unbounded in-memory accumulation.

## 4.6 Naming audit

Check:

- names are more truthful than before;
- no historical lie survives just because it already existed;
- no rename was made only for aesthetics;
- terminology is consistent across code, config, tests, and docs.

## 4.7 Test audit

Check:

- changed behavior is actually covered;
- tests verify the intended architectural boundary, not only happy-path output;
- newly added tests would have failed before the change;
- test naming and fixtures remain readable and intentional.

## 4.8 Code quality and design-hygiene audit

Check:

- the touched code is slimmer, clearer, or more honest than before;
- complexity is proportionate to the real problem, not inflated by inertia;
- duplicated logic was reduced where reasonable;
- helpers and abstractions still earn their existence;
- no dead branches, temporary scaffolding, or awkward transitional code remain;
- the slice improves the local code quality baseline instead of merely moving
  behavior around.

## 4.9 Public API and library-ergonomics audit

When `src/` package surfaces are touched, check:

- public APIs are more coherent and easier to use than before;
- import surfaces remain intentional and unsurprising;
- factory/config entry points stay understandable;
- no awkward transitional API shape is left behind merely to avoid cleanup;
- the slice improves library-grade usability rather than only internal
  behavior.

## 4.10 Documentation and config audit

Check:

- public-facing modules and APIs are documented enough for serious use;
- config shape still matches code semantics;
- local folder `README.md` files and guidance files remain honest where the
  slice changes local meaning;
- docs or planning notes stay consistent if the slice changes surface behavior;
- no stale references remain in deployment or service configs.

## 4.11 Repository-surface audit

When a slice touches any non-`src` repository surface, check:

- the touched files are now cleaner and more coherent than before;
- `tests`, `tools`, `deployments`, `docs`, workflow/config files, and
  repository notes are treated as first-class project surfaces;
- `AGENTS.md` files, repository guides, and other contributor/operator
  guidance are updated when their slice semantics change;
- no “secondary quality zone” mentality is tolerated outside `src/`;
- repository-level consistency improves rather than fragments.

---

## 5. Repository-Wide Gates

These gates apply repeatedly throughout execution.

## 5.1 After every work package

Required:

- targeted tests for the touched slice;
- local audit;
- fix loop if findings exist;
- `make ci`;
- `uv lock --check`;
- clean final diff review;
- commit.

Additionally, the work package is not considered closed unless the touched
code also satisfies the local code-excellence standard from
`18_code_excellence_standard.md`.

If the slice touches public-library surfaces in `src/`, it is also not closed
unless the corresponding API/documentation usability audit is clean.

If the slice touches non-`src` repository surfaces, it is also not closed
unless the repository-surface audit is clean.

## 5.2 After every tranche

Required:

- one tranche-level audit over all commits in the tranche;
- explicit search for hidden inconsistencies across modules and configs;
- explicit review for naming drift and partial migrations;
- one more full green run.

## 5.3 Before moving to the next tranche

Required:

- the previous tranche must be conceptually closed;
- no known red flags should be deliberately deferred unless they are explicitly
  documented and accepted as a later-scope dependency.

## 5.4 Redesign-level definition of done

The redesign is not complete when the new architecture merely exists.

It is complete only when:

- the target architecture exists end-to-end;
- old conceptual lies have been removed;
- the codebase is uniformly professional and coherent;
- touched areas have been cleaned to a consistently excellent standard;
- `src/` is easier to use and understand as a Python library surface;
- repository and `docs/` documentation have been deliberately rewritten around
  the final system shape;
- the repository is easier to trust, understand, and extend than before.

---

## 6. Tranche Map Overview

The implementation should proceed in this order:

0. integral codebase validation and assumption audit
1. contract freeze and rename ledger
2. SQL and shared-schema foundation
3. Python domain-model and `Brotr` alignment
4. shared derivation and maintenance pipeline alignment
5. service-boundary alignment
6. score/output and NIP capability alignment
7. protocol-agnostic read-core implementation
8. deployment-contract normalization
9. repository-wide documentation rewrite
10. final cleanup, rename sweep, and closeout audit

This order is deliberate:

- the real execution baseline is the `nip85-hardening` line of work, because
  it already contains preparatory refactors across many seams the redesign
  depends on;
- the real code seams must be validated before the first invasive refactor;
- schema and domain semantics must settle before service rewiring;
- service boundaries should settle before the read side is rebuilt around them;
- deployment formalization should happen after the real runtime and read
  surfaces are stable enough to describe accurately;
- the full documentation rewrite should happen once the final system shape is
  materially stable, not while architecture is still moving under it.

---

## 7. Detailed Execution Plan

### Tranche 0 — Integral Codebase Validation And Assumption Audit

#### Objective

Validate the redesign plan against the real codebase before starting invasive
refactor work.

#### Why this is now explicit

The redesign is not being applied to a toy project.
The current codebase already contains:

- a real read-model stack above `Catalog`;
- deployment-folder conventions that are already operationally meaningful;
- tests that encode current schema and public-surface contracts;
- private/public score boundaries that already partially match the target.

It also already contains a substantial preparatory branch line:

- `refactor/nip85-hardening-cleanup-performance`

That line is not accidental background noise.
It is part of the real execution baseline for the redesign and must be treated
as such when work begins.

So the implementation must begin with a serious assumption audit, not with
abstract confidence.

#### Main touch areas

- service registries and entrypoints;
- shared read-layer code;
- service boundaries in real code;
- SQL templates and refresh functions;
- deployment folders and service YAML;
- integration and unit tests that encode current behavior.

#### Work Package 0.1 — Integral architecture validation

Read and validate the codebase across the architectural seams that the
redesign will touch most heavily.

Expected outputs:

- a confirmed list of decisions that still hold;
- a list of sharpened migration constraints;
- a record of current seams that future tranches must respect.

Audit focus:

- whether the architectural plan survives contact with the real code;
- whether any supposedly “closed” decisions are actually contradicted in code;
- whether any tranche descriptions are too abstract for the real migration.

Exit condition:

- one explicit validation record exists and the implementation plan is updated
  to reflect it.

#### Work Package 0.2 — Migration-risk ledger

Freeze the most important execution warnings discovered during the validation
pass.

At minimum this should record:

- that the read-core migration must pass through the current
  `ReadModelSurface` / registry / adapter-config seam;
- that the DB redesign is a coordinated SQL + Python + tests + deployment
  migration;
- that deployment normalization formalizes the current folder model rather
  than replacing it.

Audit focus:

- no hidden optimism remains in later tranche descriptions;
- the rest of the plan is now grounded in the real codebase.

Commit gate:

- `make ci`
- `uv lock --check`

#### Work Package 0.3 — Redesign execution ledger bootstrap

Create and initialize the explicit execution ledger/checklist that will track
the redesign from the first committed slice to the final closeout.

At minimum it should contain:

- tranche-by-tranche status;
- work-package checklist rows;
- room for commit references;
- room for audit findings and resolutions;
- room for deferred follow-ups and remaining risks.

Audit focus:

- the ledger is detailed enough to serve as the operational memory of the
  redesign;
- the ledger structure is simple enough to keep updated for every slice;
- later tranches can be tracked without ambiguity.

Exit condition:

- one committed execution ledger exists and later work packages can update it
  instead of reconstructing progress from git history alone.

### Tranche 1 — Contract Freeze And Rename Ledger

#### Objective

Freeze the exact target language and map current names to future names before
code refactoring begins.

#### Why this comes first

If the rename and contract layer is fuzzy, every later tranche will leak
historical naming and partial semantics.

This tranche is intentionally **after** Tranche 0 because the contracts must
now be frozen against the real current seams, not against planning language
alone.

#### Main touch areas

- planning docs;
- architecture docs;
- rename mapping notes;
- selected code comments or package docs where they directly affect later work.

#### Work Package 1.1 — Canonical rename ledger

Define and freeze the canonical mapping for at least:

- `metadata` -> `document`
- `event_relay` -> `event_observation`
- `relay_metadata` -> `relay_document`
- `d_tag` -> `d_value`
- `*_rank` / `raw_score` -> `*_score` / `score`
- `read model` center -> `readable resource` / `read core` center

Audit focus:

- semantic honesty;
- cross-doc consistency;
- no unresolved competing vocabularies.

Exit condition:

- one canonical rename ledger exists and later tranches can follow it without
  guessing;
- later schema, Python, tests, and documentation work now have one explicit
  target vocabulary source.

#### Work Package 1.2 — Final contract freeze

Freeze the final contracts for:

- shared DB concepts;
- read-core shape;
- deployment-folder contract;
- `Monitor`, `Refresher`, `Ranker`, and `Assertor` boundaries.

Audit focus:

- no remaining large architectural ambiguity;
- no contradiction between planning files.

Commit gate:

- `make ci`
- `uv lock --check`

---

### Tranche 2 — SQL And Shared-Schema Foundation

#### Objective

Implement the shared schema target in the SQL/template system.

#### Why this comes second

The entire codebase depends on the DB contract.
This must be made concrete before service runtime changes.

#### Main touch areas

- `tools/templates/sql/base/*`
- `tools/templates/sql/lilbrotr/*`
- `tools/templates/sql/testbrotr/*`
- generated deployment SQL under `deployments/*/postgres/init/*`
- SQL-oriented tests and checks

#### Work Package 2.1 — Core storage relation alignment

Implement the core storage contract around:

- `relay`
- `event`
- `event_observation`
- `document`
- `relay_document`
- `service_state`

This includes:

- final table names or the migration strategy toward them;
- final column semantics;
- removal of non-essential helper columns;
- storage-profile coherence across base and profile overrides.

Audit focus:

- semantic correctness;
- data minimality;
- profile coherence;
- generated SQL consistency.

#### Work Package 2.2 — Current-table slimming

Implement narrow current tables and remove unjustified payload duplication.

This includes:

- replaceable current;
- addressable current;
- relay-document current;
- explicit decision about view-first contact graph exposure.

Audit focus:

- narrowness;
- correct winner semantics;
- no hidden denormalized payload sprawl.

#### Work Package 2.3 — Shared analytics and interaction tables

Align shared summary, interaction, and score-output tables with the final
schema target.

This includes:

- count-column naming cleanup;
- event-centric timestamp semantics;
- separation between shared facts and public score outputs.

Audit focus:

- table-worthiness;
- incremental maintainability;
- no algorithmic leakage into canonical fact tables.

#### Work Package 2.4 — Functions, refreshes, cleanup, indexes, verify scripts

Bring procedures, refresh functions, cleanup logic, indexes, and verify scripts
into alignment with the new schema.

This includes:

- removing false orphan assumptions;
- aligning refresh procedures to new tables/views;
- verifying index strategy for large-set bounded traversal;
- keeping SQL generation green for all deployment profiles.

Audit focus:

- cleanup correctness;
- no hidden domain lies;
- performance support;
- template/profile consistency.

Commit rule for every package in this tranche:

- no commit without full SQL generation check and full `make ci`.

---

### Tranche 3 — Python Domain-Model And `Brotr` Alignment

#### Objective

Align Python models and the DB interface layer to the new schema contract.

#### Main touch areas

- `src/bigbrotr/models/*`
- `src/bigbrotr/core/brotr.py`
- model-related tests;
- `Brotr` operation tests;
- any shared constants or DB parameter contracts.

#### Work Package 3.1 — Domain model rename and shape alignment

Align models to the future concepts and semantics:

- document-oriented naming;
- observation-oriented relation naming;
- service-state minimality;
- timestamp semantics.

Audit focus:

- constructor validation integrity;
- DB-param caching integrity;
- no drift between model semantics and SQL semantics.

#### Work Package 3.2 — `Brotr` procedure and query interface alignment

Update `Brotr` methods and stored-procedure integration to the new schema and
procedure surface.

Audit focus:

- method naming honesty;
- batch safety;
- no leaking of obsolete schema terms;
- no mismatch between SQL and Python call contracts.

#### Work Package 3.3 — Test matrix alignment

Update model, core, and integration-facing tests to enforce the new contract.

Audit focus:

- changed behavior is asserted clearly;
- tests fail on old semantics;
- no stale references to obsolete names survive.

---

### Tranche 4 — Shared Derivation And Maintenance Pipeline Alignment

#### Objective

Bring derivation logic and maintenance loops into alignment with the new schema
and maintenance philosophy.

#### Main touch areas

- `src/bigbrotr/services/refresher/*`
- `src/bigbrotr/services/common/state_store.py`
- refresh/query helpers across services;
- SQL refresh procedures and related tests.

#### Work Package 4.1 — Current derivation alignment

Align current-table maintenance to:

- narrow current structures;
- correct winner logic;
- rebuild-on-delete semantics;
- no hidden dependence on wide cached payloads.

Audit focus:

- correctness of winner replacement;
- no hidden denormalization expectations downstream.

#### Work Package 4.2 — Shared analytics maintenance alignment

Align incremental shared analytics maintenance to the new schema and naming.

Audit focus:

- event-centric semantics;
- correct upstream cursoring;
- no false “one cursor fits all” assumptions.

#### Work Package 4.3 — Heavy-derivation boundedness

Review and align heavier derivations so they are explicitly:

- chunked;
- resumable;
- bounded;
- not hot-path monoliths.

Audit focus:

- memory boundedness;
- progress resumption;
- key-range or window-range scoping;
- explicit rebuild path when needed.

---

### Tranche 5 — Service-Boundary Alignment

#### Objective

Bring service internals and responsibilities into full alignment with the
final architecture.

#### Main touch areas

- `src/bigbrotr/services/monitor/*`
- `src/bigbrotr/services/refresher/*`
- `src/bigbrotr/services/assertor/*`
- `src/bigbrotr/services/ranker/*`
- service configs and service tests

#### Work Package 5.1 — `Monitor` internal restructuring

Keep `Monitor` as one service while clarifying the internal boundary between:

- probing;
- persistence;
- publication.

Audit focus:

- clear internal ownership;
- failure isolation;
- checkpoint clarity;
- no accidental service split through code structure.

#### Work Package 5.2 — `Refresher` authoritative ownership

Ensure `Refresher` truly owns canonical shared derivation and downstream shared
facts.

Audit focus:

- no competing derivation ownership in other services;
- clear upstream/downstream data flow.

#### Work Package 5.3 — `Assertor` full provider-package publication

Complete `Assertor` as owner of:

- trusted assertions;
- provider profile;
- trusted-provider list.

Audit focus:

- full NIP-85 package completeness;
- publication cadence and change detection coherence;
- no publication responsibility leaking elsewhere.

#### Work Package 5.4 — `Ranker` boundary hardening

Keep private compute private and shared output minimal.

Audit focus:

- no schema deformation for ranker convenience;
- clean import of shared facts;
- minimal shared score-output contract.

---

### Tranche 6 — Score, NIP Capability, And Publication Alignment

#### Objective

Align protocol capability declarations and score/publication surfaces to the
final model.

#### Main touch areas

- `src/bigbrotr/nips/registry.py`
- `src/bigbrotr/nips/event_builders.py`
- `src/bigbrotr/nips/nip85/*`
- `src/bigbrotr/services/assertor/*`
- `src/bigbrotr/services/monitor/publishing.py`
- related tests

#### Work Package 6.1 — Formalize the static capability registry

Make `NIP_REGISTRY` clearly represent real capability bundles used by the
system.

Audit focus:

- registry usefulness;
- no ornamental entries;
- no plugin-magic direction.

#### Work Package 6.2 — Align NIP-85 event builders and publication paths

Ensure event builders, publication logic, and data contracts fully match the
final `Assertor` boundary.

Audit focus:

- event-kind correctness;
- provider-package completeness;
- no mismatched semantics between builders and service usage.

#### Work Package 6.3 — Align score-output naming and usage

Ensure score-output semantics are consistent across:

- schema;
- queries;
- services;
- publication logic;
- tests.

Audit focus:

- `score` vocabulary consistency;
- no stale `rank`/`raw_score` semantics where they no longer belong.

---

### Tranche 7 — Protocol-Agnostic Read-Core Implementation

#### Objective

Implement the new shared read core above `Catalog` and migrate adapters onto
it.

#### Main touch areas

- `src/bigbrotr/services/common/catalog*.py`
- `src/bigbrotr/services/common/read_model_registry.py`
- `src/bigbrotr/services/common/read_models.py`
- `src/bigbrotr/services/common/read_model_requests.py`
- `src/bigbrotr/services/api/*`
- `src/bigbrotr/services/dvm/*`
- relevant configs and tests

#### Work Package 7.1 — Resource-registry evolution

Evolve the current read-model registry toward a readable-resource registry with
resource-level policy and capability descriptors.

Audit focus:

- conceptual center shifts from relation aliases to readable resources;
- no loss of strong generic machinery already present today;
- explicit preservation of the current adapter-config exposure seam;
- no casual breakage of canonical public resource IDs without an intentional
  migration decision.

#### Work Package 7.2 — Shared read-core object/service

Introduce the shared read-core layer that resolves resources and executes them
through `Catalog` or handlers.

Audit focus:

- protocol agnosticism;
- bounded query enforcement;
- deployment-aware resource resolution;
- explicit error normalization;
- a real migration path from `ReadModelSurface`, not an abstract rewrite that
  bypasses the current seam.

#### Work Package 7.3 — API migration

Migrate HTTP reading fully onto the new shared read core.

Audit focus:

- no adapter-owned data semantics;
- no regression in discovery or pagination behavior;
- no unbounded public query path.

#### Work Package 7.4 — DVM migration

Migrate DVM reading fully onto the same shared read core.

Audit focus:

- semantic parity where it should exist;
- deliberate protocol-specific difference only at adapter level;
- no duplication of core read logic.

#### Work Package 7.5 — Future-adapter readiness

Without implementing a full new adapter yet, ensure the core shape is ready for
future adapters such as `mcp`.

Audit focus:

- no API-specific assumptions in the read core;
- no DVM-specific assumptions in the read core.

---

### Tranche 8 — Deployment-Contract Normalization

#### Objective

Formalize the deployment contract around the existing folder-based, YAML-first
model.

#### Main touch areas

- `deployments/*`
- deployment docs;
- config models;
- service config parsing/validation;
- any scaffolding or helper logic needed for new deployments

#### Work Package 8.1 — Formalize required and optional deployment pieces

Make explicit which files and subtrees are:

- required;
- conditional;
- optional-but-recommended.

Audit focus:

- no hidden conventions;
- one deployment folder remains self-explanatory;
- the formalization reflects the current real folder pattern instead of an
  invented clean-room model.

#### Work Package 8.2 — Storage-profile contract

Formalize how storage profile is represented and how it affects:

- SQL package;
- config;
- runtime expectations;
- downstream readable data.

Audit focus:

- `bigbrotr` / `lilbrotr` coherence;
- future deployability without forking.

#### Work Package 8.3 — Per-protocol exposure policy

Normalize how deployments express what `api`, `dvm`, and future adapters may
expose.

Audit focus:

- clean interaction with the new read core;
- deployment decides what exists;
- adapter config decides what is exposed.

#### Work Package 8.4 — Reference-deployment cleanup

Make `bigbrotr` and `lilbrotr` clean reference deployments after the previous
changes.

Audit focus:

- config clarity;
- profile clarity;
- no stale pre-redesign semantics left in deployment files.

---

### Tranche 9 — Repository-Wide Documentation Rewrite

#### Objective

Rewrite and realign repository documentation around the final system shape.

#### Main touch areas

- `docs/*`
- `mkdocs.yml`
- public package/module documentation in `src/*`
- folder-level `README.md` files and local guidance files
- repository-level guidance and explanatory files
- deployment and operations docs

#### Work Package 9.1 — In-code documentation rewrite

Rewrite public in-code documentation where needed so that module and API docs
match the final architecture and public-library expectations.

Audit focus:

- semantic honesty;
- public API usability;
- coherence between code reality and documented usage.

#### Work Package 9.2 — MkDocs information architecture rewrite

Rethink and rewrite the `docs/` site structure and content so it explains the
final project rather than the pre-redesign one.

Audit focus:

- easier navigation;
- cleaner final project narrative;
- coherence across getting-started, user-guide, how-to, and development docs.

#### Work Package 9.3 — Folder-level README and guidance rewrite

Establish a coherent local documentation layer across the repository.

This includes:

- folder-level `README.md` coverage for meaningful maintained project folders;
- explicit treatment of allowed exceptions for trivial or generated folders;
- alignment between local `README.md` files and local `AGENTS.md` or guidance
  files where both exist.

Audit focus:

- local orientation quality;
- no important folder left undocumented without an explicit reason;
- no split-brain between local README and local workflow guidance.

#### Work Package 9.4 — Deployment, operator, and contributor docs rewrite

Rewrite deployment and operational guidance so it reflects the final
deployment contract, service ownership model, and engineering standards.

Audit focus:

- operational realism;
- contributor clarity;
- removal of stale or conflicting guidance.

#### Work Package 9.5 — Reference alignment pass

Ensure generated API reference, in-code documentation, and narrative docs all
tell the same story.

Audit focus:

- no split-brain between reference docs and narrative docs;
- public package surfaces are discoverable and understandable.

---

### Tranche 10 — Final Cleanup, Rename Sweep, And Closeout Audit

#### Objective

Finish the redesign by removing residual drift and proving the system is
coherent end-to-end.

#### Main touch areas

- cross-cutting residual names;
- docs;
- configs;
- tests;
- deployment examples;
- planning follow-through where needed

#### Work Package 10.1 — Residual-name sweep

Remove stale legacy terms that survived intermediate tranches.

Audit focus:

- no split vocabulary;
- no hidden old-schema language in live code paths.

#### Work Package 10.2 — Compatibility-cruft removal

Remove temporary compatibility shims that were justified only during migration.

Audit focus:

- no dead branches;
- no lingering dual paths;
- no code kept only to avoid touching callers.

#### Work Package 10.3 — Final architecture audit

Perform one cross-cutting audit over the whole redesign result.

This audit should explicitly re-check:

- DB shape;
- derivation model;
- service boundaries;
- read-core boundaries;
- deployment contract;
- naming quality;
- large-DB discipline.

#### Work Package 10.4 — Final verification and release-readiness gate

Run:

- full `make ci`;
- `uv lock --check`;
- final SQL generation verification;
- final targeted runtime sanity checks for the touched services and deployments.

Only after this should the redesign be considered complete.

---

## 8. Commit And Audit Discipline By Tranche

The rule for all tranches is:

- one work package;
- one closed audit loop;
- one full green gate;
- one updated execution-ledger entry;
- one descriptive commit.

If a tranche contains four work packages, it should normally produce four clean
commits, not one giant one.

Exception:

- if two tiny packages are inseparable and the resulting diff is still easy to
  audit as one unit, they may be merged deliberately.

That exception should be rare.

---

## 9. Stop Conditions

Work must pause and re-evaluate immediately if:

- a package starts needing broad speculative changes outside its intended
  slice;
- the target contract appears internally inconsistent with the real code;
- a rename causes uncontrolled churn beyond the planned boundary;
- a supposedly incremental path reveals an unbounded runtime assumption;
- adapter code starts reintroducing read semantics that should belong to the
  read core;
- deployment config starts accumulating hidden conventions instead of becoming
  clearer.

These are not reasons to “push through”.
These are reasons to stop, think, and tighten the slice.

---

## 10. Definition Of Execution Success

This execution plan succeeds only if the redesign is implemented with all of
the following true:

- every major tranche lands through audited, bounded, descriptive commits;
- the execution ledger/checklist always reflects the real state of the
  redesign, including completed work, open follow-ups, and remaining work;
- no major architectural decision is undermined during implementation;
- the repo stays green after every committed work package;
- final code, config, SQL, and tests speak one coherent language;
- documentation, guides, and operator/contributor surfaces speak that same
  coherent language too;
- `src/` ends in a materially better state as a Python library surface;
- the system is cleaner, more honest, and more future-proof than the starting
  point.

That is the standard this plan is designed to enforce.
