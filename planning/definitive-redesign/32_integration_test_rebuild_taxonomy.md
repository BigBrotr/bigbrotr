# Integration Test Rebuild Target Taxonomy

## Purpose

This file freezes the intended top-level shape of the rebuilt integration
suite.

The current suite shape:

- `tests/integration/base`
- `tests/integration/lilbrotr`

is historically understandable, but no longer the best executable map of the
system.

The target taxonomy below is the structure the rebuild should converge to.

It exists so execution decisions remain deliberate and audit-friendly instead
of becoming opportunistic file churn.

---

## Target Top-Level Tree

```text
tests/integration/
  harness/
    builders/
    doubles/
    fixtures/
  shared_db/
  core/
  services/
    seeder/
    finder/
    validator/
    monitor/
    synchronizer/
    refresher/
    ranker/
    assertor/
    api/
    dvm/
  pipelines/
    discovery/
    archive/
    derivation/
    read_surfaces/
    restart/
  deployments/
    bigbrotr/
    lilbrotr/
    testbrotr/
  failures/
  README.md
```

This tree is the target execution shape.
It does not require every directory to appear immediately.

It does require that every new integration slice move the repository closer to
this shape rather than sideways.

---

## Area Intent

### `harness/`

Owns deterministic integration support:

- PostgreSQL container lifecycle;
- deployment/schema bootstrap;
- canonical test data builders;
- named external doubles;
- deterministic temp-path, timestamp, and ID helpers;
- failure-injection helpers.

`harness/` should contain support code, not domain assertions disguised as
fixtures.

### `shared_db/`

Owns the direct shared-storage contract:

- CRUD;
- cascade semantics;
- deduplication;
- foreign keys;
- partitioning;
- transactions;
- retention;
- refresh-derived tables.

These files should prove SQL and persisted-state contracts without coupling
themselves to one service unless that service behavior is the contract under
test.

### `core/`

Owns the integration seams that sit below service-specific behavior:

- `Pool`;
- `Brotr`;
- service runtime primitives where live integration proof matters.

### `services/`

Owns service-specific integration contracts.

Each service gets its own directory so the boundary remains legible.

Each service subtree should converge on a consistent internal split:

- `test_config_and_runtime.py`
- `test_happy_path.py`
- `test_failures.py`
- `test_restart.py`

Not every service needs every filename immediately.
The point is contract clarity, not forced symmetry.

### `pipelines/`

Owns multi-service execution contracts:

- discovery;
- archive;
- derivation/publication;
- read-surface exposure;
- restart/idempotency across service boundaries.

No pipeline file should duplicate the full internals of a service-specific
file.
Pipeline tests should prove composition.

### `deployments/`

Owns profile-specific guarantees.

This is where the suite proves:

- `bigbrotr` baseline expectations;
- `lilbrotr` documented compromises;
- `testbrotr` support status if retained.

### `failures/`

Owns failure/recovery seams that cut across service or profile boundaries:

- timeout budgets;
- retries;
- transient DB failure;
- partial external failure;
- cancellation and cleanup;
- flake-sensitive concurrency surfaces.

---

## Naming Rules

### 1. Files name the contract, not the implementation detail

Prefer:

- `test_archive_checkpoint_restart.py`
- `test_publication_retry_budget.py`
- `test_relay_document_refresh.py`

Avoid:

- `test_more_ranker.py`
- `test_misc.py`
- `test_pipeline_2.py`

### 2. One file, one contract band

If a file needs a long README comment to explain why unrelated assertions live
there together, the file is scoped badly.

### 3. Named doubles must read like components

Prefer:

- `FakePublishSession`
- `FakeApiSource`
- `FakeRelayStream`
- `FailingDnsLookup`

Avoid anonymous mocks embedded in many unrelated tests.

### 4. Builders should encode domain nouns

Prefer:

- `build_relay()`
- `build_event_observation()`
- `build_relay_document()`
- `build_user_score_row()`

Avoid generic factories that conceal contract semantics.

---

## Migration Rules

### 1. New work goes into the target taxonomy

No new integration coverage should be added under:

- `tests/integration/base`
- `tests/integration/lilbrotr`

unless a short-lived compatibility move is required inside the same slice.

### 2. Historical files survive only while still carrying unique proof

An old file may remain temporarily if the new taxonomy has not yet absorbed
its unique coverage.

Once parity or stronger proof exists in the new tree, the old file should be
removed in the same or next closing slice.

### 3. Support code should migrate before assertions depend on it

If a new service or pipeline slice needs builders or doubles, those support
surfaces should be created under `harness/` first.

### 4. Local guidance must stay honest

Whenever a new subtree becomes nontrivial, it should gain a local `README.md`
that explains:

- what contracts live there;
- what does not belong there;
- and what support surfaces it depends on.

---

## Audit Questions For Taxonomy Compliance

Use these questions whenever a slice closes:

- Did the slice move the suite toward the target topology?
- Did it introduce any new historical-looking junk drawer files?
- Are doubles centralized when reused?
- Does the file placement help a future reader predict where similar tests
  belong?
- Could a new contributor understand the contract boundary from the path
  alone?

If the answer is no, the taxonomy drift should be fixed before closure.
