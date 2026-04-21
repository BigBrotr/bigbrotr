# Integration Test Rebuild Program

## Purpose

The current integration suite is useful, but it is not yet a complete
executable specification of the BigBrotr system.

It is strongest where the repository already has:

- shared PostgreSQL contract coverage;
- shared-table refresh coverage;
- a meaningful `Refresher` / `Ranker` / `Assertor` pipeline seam.

It is materially weaker where the system still needs:

- first-class service-runtime integration for all ten services;
- realistic boundary testing for external protocols and adapters;
- deployment-profile parity as an explicit contract;
- restart, recovery, and failure-mode coverage as a first-class integration
  concern;
- and a suite shape that was designed deliberately instead of accumulated
  historically.

This program therefore does **not** treat the current `tests/integration/`
tree as the target shape.

It treats it as:

- evidence;
- reference material;
- a source of already-proved contracts;
- and a source of already-exposed drift.

The integration layer should now be rebuilt **from scratch** as a professional,
high-signal, audit-driven test specification for the actual product.

The goal is not merely “more integration tests”.

The goal is:

- a deliberate integration architecture;
- an explicit coverage matrix across all product concerns;
- closure-auditable work packages;
- and a repeatable fix loop that can harden production code while the suite is
  rebuilt.

This program complements, but does not replace:

- [16_operational_implementation_plan.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/16_operational_implementation_plan.md)
- [18_code_excellence_standard.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/18_code_excellence_standard.md)
- [20_redesign_execution_ledger.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/20_redesign_execution_ledger.md)
- [23_repository_content_audit_program.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/23_repository_content_audit_program.md)
- [24_repository_content_audit_ledger.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/24_repository_content_audit_ledger.md)

---

## Why A Full Rebuild Is Justified

The current integration layer proves real value already.

But it also shows structural limits:

- service coverage is uneven;
- deployment/profile coverage is partial;
- external-boundary realism is inconsistent;
- file boundaries are historical rather than intentionally designed;
- and the suite does not yet function as a complete system-level contract for
  discovery, monitoring, archiving, derivation, and publication.

That means the current layer is strong enough to preserve, but not strong
enough to trust as the final professional integration standard.

The rebuild is justified because:

- BigBrotr is a ten-service system sharing one PostgreSQL database;
- integration failure often appears at boundaries that unit tests do not
  expose;
- the repository now has a much cleaner architecture than the historical test
  layout reflects;
- and the same rebuild can surface real production drift while the system is
  exercised more honestly.

This program explicitly assumes that some production fixes will emerge during
the rebuild.

That is expected.
It is not accidental scope creep.

---

## Non-Negotiable Principles

### 1. From-scratch design, not incremental patching

Each integration area should be redesigned from the live contract outward.

The existing integration files may be read for:

- contract hints;
- useful fixtures;
- historical edge cases;
- and already-known regressions.

They must **not** be treated as the default target structure to preserve.

### 2. The suite is an executable system contract

Each integration test file must prove a meaningful contract, not merely assert
that code paths can run.

Every file should answer one of these questions clearly:

- does the shared storage contract hold?
- does a service behave correctly against the real database contract?
- does a multi-service pipeline produce the right persisted or published
  outcome?
- does a deployment/profile preserve the intended system guarantees?
- does a failure mode recover or fail honestly?

### 3. Minimal fake boundaries, maximal honest boundaries

The database boundary should be real.

Protocol, filesystem, time, and network boundaries should be made as real as
possible while remaining deterministic and auditable.

Mocks are acceptable only when the true external dependency would make the
suite:

- nondeterministic;
- prohibitively slow;
- or impossible to run in CI.

When a fake is required, it should behave like a named test double with an
explicit contract, not as an opaque patch cloud.

### 4. Determinism is a first-class quality requirement

Integration tests must avoid:

- hidden wall-clock races;
- sleep-based stabilization;
- test-order coupling;
- accidental cross-test state;
- and non-observable teardown opacity.

Where timing matters, the suite should use:

- fixed timestamps;
- explicit monotonic sequencing;
- deterministic temporary storage;
- and bounded observability on teardown failures.

### 5. Every section must be closure-auditable

No section is complete because code was written.

A section is complete only if:

- its scope is bounded;
- its contract is explicit;
- its tests and any required production fixes are implemented;
- its audit loop is green;
- its ledger entry is updated;
- and its closure lands in its own commit.

### 6. The rebuild may fix production drift, but not lower the bar

If the new integration suite reveals production bugs, design dishonesty, or
fixture drift, those issues should be fixed inside the relevant section.

The answer to exposed drift is:

- tighten the test;
- fix the product;
- rerun the audit loop;
- and close the section only after the contract is honest.

It is **not**:

- weakening assertions;
- broadening tolerance silently;
- or converting real integration tests back into unit-style mocks.

---

## Definition Of Done

The integration rebuild is complete only when all of the following are true:

- all ten services have intentional integration coverage;
- the shared PostgreSQL contract is covered directly and not only indirectly;
- the built-in deployment profiles are covered explicitly as contracts, not as
  incidental fixture variants;
- cross-service pipelines are proven end to end at the level BigBrotr actually
  composes them;
- major failure/recovery contracts are tested intentionally;
- the suite structure is documented, navigable, and locally honest;
- the full integration matrix is stable under repeated audit reruns;
- and the final audit finds no remaining structural weakness that requires
  more slice work.

“Some integration tests pass” is not sufficient.

---

## Target Coverage Matrix

The rebuilt suite must cover all of these bands explicitly.

### 1. Shared data contract

- schema bootstrap and deployment SQL initialization;
- relay/event/document/service-state CRUD semantics;
- cascade semantics and deduplication;
- foreign-key integrity;
- partitioning and placement invariants;
- transactional guarantees;
- retention and cleanup behavior;
- derived/current/fact/score refresh semantics.

### 2. Core runtime boundary

- `Pool` / `Brotr` lifecycle against the real database;
- config-driven timeout, batch, retry, and cleanup behavior where integration
  proof is warranted;
- service runtime enter/exit behavior that affects real integration contracts.

### 3. Service-runtime contract

- `Seeder`
- `Finder`
- `Validator`
- `Monitor`
- `Synchronizer`
- `Refresher`
- `Ranker`
- `Assertor`
- `API`
- `DVM`

Each service needs intentional integration proof for:

- construction/config contract;
- happy-path behavior;
- persisted outputs or published outputs;
- failure path;
- restart or resume semantics where applicable;
- and deployment/profile differences where they matter.

### 4. Cross-service pipelines

- discovery pipeline;
- archive pipeline;
- refresh-to-score pipeline;
- score-to-publication pipeline;
- read-surface pipeline for `API` and `DVM`;
- restart/idempotency seams that cross service boundaries.

### 5. Deployment/profile contract

- `bigbrotr`
- `lilbrotr`
- internal `testbrotr` fixture/deployment surfaces where they remain part of
  the supported test system;
- generated SQL parity with deployed SQL initialization;
- profile-specific compromises proved explicitly instead of hidden behind
  weakened shared assertions.

### 6. Failure and resilience contract

- timeout and retry budget behavior;
- partial external failure handling;
- database error boundaries;
- checkpoint/resume correctness;
- cleanup and shutdown guarantees;
- invalid data rejection at real boundaries;
- flake-sensitive concurrency seams.

---

## Target Suite Shape

The final test tree does not need to match this layout mechanically, but the
rebuild should aim for this level of explicitness:

```text
tests/integration/
  harness/
  shared_db/
  core/
  services/
  pipelines/
  deployments/
  failures/
  README.md
```

Expected intent by area:

- `harness/`: container lifecycle, fixture factories, named doubles,
  deterministic support helpers.
- `shared_db/`: direct proof of shared schema and SQL-function contracts.
- `core/`: `Pool`, `Brotr`, and runtime seams that are not tied to one
  service.
- `services/`: one sub-area per service, shaped around that service's real
  integration contract.
- `pipelines/`: multi-service end-to-end bands that matter operationally.
- `deployments/`: profile-specific integration proof.
- `failures/`: resilience and recovery contracts that cut across services.

The exact file map should be frozen during execution.

The rule is clarity, not bureaucracy:

- narrow file purpose;
- obvious fixture ownership;
- low surprise;
- and easy auditability.

---

## Anti-Goals

The rebuild must not degrade into:

- a monolithic mega-suite where every file tests everything;
- porting old assertions blindly into new filenames;
- over-mocked pseudo-integration tests;
- brittle sleeps and retries used as synchronization;
- hidden fixture magic that nobody can reason about;
- or coverage theater that counts files without proving contracts.

The rebuild is not successful if it merely becomes larger.

It must become sharper.

---

## Section Closure Protocol

Every work package in this program must follow the same closure loop.

### 1. Contract read

Before writing tests, read the live contract:

- implementation code;
- config models;
- queries and SQL templates;
- adjacent unit tests;
- deployment files;
- and any local README / AGENTS guidance.

### 2. Section design pass

Write down the section’s intent in the ledger before implementation:

- target contract;
- included boundaries;
- intentionally excluded boundaries;
- expected production artifacts;
- expected failure classes;
- and target test files.

### 3. Build the section from scratch

Implement the harness pieces and the tests for that section without using the
old file layout as a binding constraint.

Reuse only what still earns its place.

### 4. Run the targeted audit loop

At minimum:

- targeted integration tests for the section;
- targeted unit tests for any touched production code;
- static/type gates if source code moved or changed;
- and reruns until the section is observable and green.

### 5. Fix exposed product drift

If the section reveals production issues:

- fix them in the same section;
- add or tighten the integration assertions;
- and rerun the section until the revealed drift is truly closed.

### 6. Run the closure gate

A section closes only after:

- its targeted suite is green;
- dependent pipeline suites are green;
- the full integration suite is green;
- and the standard repository gates required by the touched files are green.

### 7. Update the ledger

Record:

- commit hash;
- drift found;
- fixes applied;
- audits run;
- reruns needed;
- and any explicit deferred watch points.

### 8. Commit the section

Every closed section lands in its own conventional commit.

No multi-section catch-all commits.

---

## Mandatory Gate Stack

Unless a section proves that a smaller gate is sufficient and records why in
the ledger, the default closure stack is:

- targeted integration tests for the section;
- targeted unit tests for touched production code;
- `./.venv/bin/ruff check src/ tests/`;
- `./.venv/bin/ruff format --check src/ tests/`;
- `./.venv/bin/mypy src/bigbrotr`;
- `./.venv/bin/python tools/generate_sql.py --check`;
- `uv lock --check`;
- `./.venv/bin/uv-secure uv.lock`;
- `./.venv/bin/pre-commit run --files <touched files>`;
- `./.venv/bin/pytest tests/integration/ -q`;
- `./.venv/bin/pytest tests/ --ignore=tests/integration/ -q`.

If the full integration suite ends opaquely, the final green run must be
repeated in PTY or another equally observable mode before the section is
closed.

---

## Work Packages

### Wave 0 — Baseline Freeze And Rebuild Bootstrapping

#### 0.1 Freeze the current integration inventory

- freeze the current `tests/integration/` manifest;
- record file count, deployment/profile split, and current runtime shape;
- record which current files are to be preserved only as reference input, not
  as target structure.

#### 0.2 Freeze the live contract matrix

- map the ten services to their real integration boundaries;
- map shared tables/functions/current/fact/score surfaces;
- map deployment profiles and runtime-only seams;
- map external dependencies that require named test doubles.

#### 0.3 Freeze the target suite taxonomy

- decide the final top-level integration test layout;
- decide fixture ownership boundaries;
- decide naming rules for files, builders, and named doubles;
- decide what belongs in `services/`, `pipelines/`, `deployments/`, and
  `failures/`.

#### 0.4 Bootstrap the execution ledger

- initialize the rebuild ledger;
- record statuses, commit slots, and audit notes fields;
- and explicitly encode the “one commit per closed section” rule.

### Wave 1 — Harness Redesign

#### 1.1 Container lifecycle and schema bootstrap

- redesign PostgreSQL container lifecycle for speed and isolation;
- redesign schema/bootstrap reset semantics;
- make deployment selection explicit and auditable;
- prove deterministic cleanup behavior.

#### 1.2 Canonical data builders

- build shared factories for relays, events, documents, service state, and
  score/fact rows;
- remove duplicated ad hoc builders hidden inside unrelated test files;
- prove builder semantics directly.

#### 1.3 Named external doubles

- define explicit doubles for Nostr publishing, relay sessions, HTTP fetches,
  DNS/network lookups, storage files, and time-sensitive seams where needed;
- ensure each double has an intentionally small contract and observability.

#### 1.4 Deterministic support utilities

- centralize temporary storage, fixed timestamps, synthetic identifiers, and
  monotonic sequencing helpers;
- eliminate hidden wall-clock and temp-path randomness.

#### 1.5 Failure-injection harness

- create reusable seams for timeout, retry, cancellation, database-failure,
  and partial-result scenarios;
- make failure injection readable and local, not patch soup.

#### 1.6 Harness self-audit

- run harness-only proof tests;
- stress isolation and repeated setup/teardown;
- and close the harness only when repeated reruns remain stable.

### Wave 2 — Shared PostgreSQL Contract Rebuild

#### 2.1 Relay storage contract

- insert, deduplicate, update semantics;
- network variants and canonicalization;
- concurrency and idempotency behavior.

#### 2.2 Document and relay-document contract

- content-addressed deduplication;
- cross-relay reuse;
- association semantics;
- missing-parent failure semantics.

#### 2.3 Event and event-observation contract

- event insert semantics;
- cascade/non-cascade behavior;
- event tag persistence and retrieval shape;
- cross-relay observation behavior.

#### 2.4 Service-state contract

- owner isolation;
- upsert/get/delete semantics;
- JSON round-trip guarantees;
- restart continuity assumptions.

#### 2.5 Schema integrity contract

- foreign keys;
- partition structure and placement;
- transactional atomicity;
- batch validation;
- concurrency seams.

#### 2.6 Retention and cleanup contract

- shared storage-retention semantics;
- orphan cleanup behavior where applicable;
- cleanup safety against live rows that must survive.

#### 2.7 Derived/current/fact/score contract

- current tables;
- analytics/fact refresh tables;
- contact/follower/severity-derived surfaces;
- score-table semantics;
- publication-ready derived state.

### Wave 3 — Core Runtime Integration Rebuild

#### 3.1 `Pool` lifecycle

- configuration to live connection behavior;
- startup failure semantics;
- cleanup guarantees;
- connection reuse assumptions that matter to services.

#### 3.2 `Brotr` boundary

- real method-to-SQL behavior against live schema;
- transaction boundaries;
- lifecycle enter/exit guarantees;
- guardrails around direct pool access assumptions.

#### 3.3 Shared service runtime seam

- once/run loop behavior where integration proof matters;
- service-state interactions at the runtime boundary;
- metrics/log/cleanup effects that materially affect system behavior.

### Wave 4 — Service Runtime Rebuild

For every service work package below, the minimum required subsections are:

- config/construction contract;
- happy path;
- failure path;
- restart/resume path where applicable;
- output verification;
- deployment/profile difference where applicable.

#### 4.1 `Seeder`

- seeded source ingestion;
- deduplication and persistence;
- seed-source failure handling.

#### 4.2 `Finder`

- relay discovery from active sources;
- source filtering, deduplication, and cooldown behavior;
- persistence and source-state consequences.

#### 4.3 `Validator`

- relay validation and normalization against live persistence;
- invalid relay rejection;
- retry and failure consequences.

#### 4.4 `Monitor`

- NIP-11/NIP-66/health-check document ingestion and storage;
- timeout and probe failure behavior;
- relay/document current-state consequences.

#### 4.5 `Synchronizer`

- event archive behavior against real storage;
- checkpoint and restart semantics;
- cascade integrity and retention interactions.

#### 4.6 `Refresher`

- rolling-window refresh behavior;
- current/fact refresh correctness;
- recovery after partial or stale state.

#### 4.7 `Ranker`

- score computation inputs and store outputs;
- checkpoint/store semantics;
- failure/restart behavior;
- profile-specific differences.

#### 4.8 `Assertor`

- score hydration and publication package construction;
- DB-to-NIP boundary correctness;
- publish failure/retry consequences.

#### 4.9 `API`

- read-surface exposure against the real database;
- pagination/filter/sort capability proof at the protocol boundary;
- error mapping and catalog/read-core safety guarantees.

#### 4.10 `DVM`

- request handling against the real read core;
- output/event construction;
- protocol-level failure mapping and safety guarantees.

### Wave 5 — Cross-Service Pipeline Rebuild

#### 5.1 Discovery pipeline

- `Seeder` -> `Finder` -> `Validator` -> `Monitor` system-level flow;
- prove that discovered relay data becomes meaningful monitored state.

#### 5.2 Archive pipeline

- relay discovery/validation inputs flowing into `Synchronizer`;
- prove event archive and checkpoint behavior at system level.

#### 5.3 Derivation pipeline

- `Refresher` -> `Ranker` -> `Assertor`;
- prove the full derivation chain, not only local service seams.

#### 5.4 Public read pipeline

- persisted shared facts and outputs flowing into `API` and `DVM`;
- prove that publication/read surfaces expose the intended system state.

#### 5.5 Restart and idempotency pipeline

- repeated runs;
- stale state carry-over;
- partial completion and resume semantics across service boundaries.

### Wave 6 — Deployment And Profile Matrix Rebuild

#### 6.1 `bigbrotr` baseline profile

- prove the default deployment contract as a first-class integration target.

#### 6.2 `lilbrotr` profile

- prove lightweight compromises explicitly;
- ensure the shared contract is preserved where intended and narrowed where
  documented.

#### 6.3 Internal fixture/deployment support

- decide whether `testbrotr` remains a supported integration profile;
- if yes, test it intentionally;
- if no, remove or isolate the leftover contract honestly.

#### 6.4 Generated-SQL and deployed-SQL parity

- prove that generated SQL, checked-in deployment SQL, and integration schema
  setup remain aligned.

### Wave 7 — Failure, Recovery, And Resilience Rebuild

#### 7.1 Timeout and retry contracts

- timeout budgets;
- retry budgets;
- partial retry exhaustion;
- no dishonest “double budget” behavior.

#### 7.2 Database-failure contracts

- transient DB errors;
- integrity violations;
- rollback guarantees;
- no half-committed state.

#### 7.3 External-boundary failure contracts

- publish failures;
- relay-connect failures;
- HTTP/document fetch failures;
- invalid payloads;
- degraded source behavior.

#### 7.4 Cancellation, shutdown, and cleanup

- service shutdown;
- cleanup after mid-flight failure;
- release guarantees for partial resources.

#### 7.5 Flake and concurrency hardening

- repeated reruns of the suite;
- concurrency-sensitive seams under repetition;
- teardown observability;
- elimination of hidden race windows.

### Wave 8 — Final Audit, Cutover, And Closeout

#### 8.1 Structural audit of the new suite

- every file earns its place;
- no historical leftovers survive by inertia;
- local docs and guidance are honest.

#### 8.2 Removal or migration of obsolete integration surfaces

- remove superseded files;
- keep only what still contributes to the final suite shape;
- preserve useful historical reference only where explicitly justified.

#### 8.3 Full-matrix repeated audit

- repeat full integration reruns until the suite stops producing unexplained
  drift;
- if reruns expose drift, open new sections and close them honestly.

#### 8.4 Final closeout

- ledger closed;
- final matrix green;
- open follow-ups either eliminated or explicitly justified;
- suite shape documented for future contributors.

---

## Audit Questions For Every Closed Section

Before a section can be marked `done`, answer all of these:

- What exact contract did this section prove?
- Which boundaries were real, and which were faked intentionally?
- What production drift did the section expose?
- Was any assertion weakened to make the section pass?
- Do the file boundaries remain clear and audit-friendly?
- What reruns were needed before the section became stable?
- Why does this section deserve to exist in the final suite shape?

If any answer is vague, the section is not closed yet.

---

## Commit Discipline

Each closed section must produce:

- one conventional commit;
- one ledger update;
- one explicit closure note with drift and gates;
- and one clean worktree before the next section starts.

If a section grows too large to close honestly in one commit, it was scoped
badly and must be split.

---

## Expected Outcome

If executed seriously, this program should produce:

- a new integration architecture that mirrors the final BigBrotr system more
  honestly;
- materially stronger confidence in service boundaries and cross-service
  behavior;
- production fixes discovered under real integration pressure;
- and a suite whose failures are high-signal enough to guide future work
  instead of merely alarming CI.

The rebuild is therefore both:

- a test program;
- and a final system-hardening program.
