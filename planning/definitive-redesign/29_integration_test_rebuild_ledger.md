# Integration Test Rebuild Ledger

## Purpose

This file is the operational memory for the integration test rebuild defined
in:

- [28_integration_test_rebuild_program.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/28_integration_test_rebuild_program.md)

It exists so the rebuild never depends on:

- memory;
- scattered terminal notes;
- vague impressions of coverage;
- or reconstructing progress from git history after the fact.

Every closed section in the rebuild must update this ledger.

The ledger is mandatory because the rebuild is not only about adding tests.
It is also about:

- exposing real production drift;
- deciding what old integration surfaces should survive;
- recording what was fixed;
- recording what was removed;
- and proving that every closed section really passed an audit loop.

---

## Status Vocabulary

Use these statuses consistently:

- `not started`
- `in progress`
- `auditing`
- `blocked`
- `done`

---

## Baseline Freeze

Fill this section when execution starts for real.

- Integration manifest command:
  `find tests/integration -type f | sort`
- Frozen integration-file count:
  `TBD`
- Frozen date:
  `TBD`
- Notes:
  Record the current suite shape, the chosen target taxonomy, and whether any
  historical files are explicitly preserved only as reference input.

---

## Program Summary

| Wave | Status | Notes |
|------|--------|-------|
| 0. Baseline freeze and rebuild bootstrapping | not started | Freeze current integration inventory, live contract matrix, target taxonomy, and ledger bootstrap |
| 1. Harness redesign | not started | Rebuild container lifecycle, schema bootstrap, builders, named doubles, deterministic support utilities, and failure injection |
| 2. Shared PostgreSQL contract rebuild | not started | Rebuild shared storage and SQL-contract coverage from scratch |
| 3. Core runtime integration rebuild | not started | Rebuild `Pool`, `Brotr`, and shared runtime boundary coverage |
| 4. Service runtime rebuild | not started | Rebuild intentional integration coverage for all ten services |
| 5. Cross-service pipeline rebuild | not started | Rebuild end-to-end system flows across service boundaries |
| 6. Deployment and profile matrix rebuild | not started | Rebuild coverage for `bigbrotr`, `lilbrotr`, and internal test profile/deployment seams |
| 7. Failure, recovery, and resilience rebuild | not started | Rebuild timeout, retry, failure, cancellation, cleanup, and flake-sensitive coverage |
| 8. Final audit, cutover, and closeout | not started | Remove obsolete surfaces, repeat full-matrix audits, and close the rebuild honestly |

---

## Work-Package Checklist

### Wave 0 — Baseline Freeze And Rebuild Bootstrapping

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 0.1 Freeze current integration inventory | not started |  | Record exact manifest, file count, deployment split, and legacy-reference-only surfaces |
| 0.2 Freeze live contract matrix | not started |  | Map tables/functions, services, deployments, and external boundaries to test bands |
| 0.3 Freeze target suite taxonomy | not started |  | Decide top-level layout, fixture ownership, and file naming rules |
| 0.4 Bootstrap execution ledger | done | `docs: add integration rebuild program` | This ledger and the paired normative program now exist as the canonical planning baseline |

### Wave 1 — Harness Redesign

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 1.1 Container lifecycle and schema bootstrap | not started |  | Rebuild deterministic PostgreSQL setup/reset behavior and deployment selection |
| 1.2 Canonical data builders | not started |  | Centralize relay/event/document/service-state/score fixtures and prove their semantics |
| 1.3 Named external doubles | not started |  | Replace opaque patch clouds with explicit protocol/network/storage doubles |
| 1.4 Deterministic support utilities | not started |  | Normalize timestamps, temp paths, identifiers, and sequencing helpers |
| 1.5 Failure-injection harness | not started |  | Create explicit timeout/retry/cancellation/DB-failure injection seams |
| 1.6 Harness self-audit | not started |  | Repeated reruns until setup/teardown stability is observable |

### Wave 2 — Shared PostgreSQL Contract Rebuild

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 2.1 Relay storage contract | not started |  | Insert/dedup/update/concurrency/idempotency semantics |
| 2.2 Document and relay-document contract | not started |  | Content-addressed dedup, association semantics, missing-parent failures |
| 2.3 Event and event-observation contract | not started |  | Event persistence, cascade behavior, tag storage, cross-relay observations |
| 2.4 Service-state contract | not started |  | Owner isolation, CRUD semantics, JSON round-trip, restart continuity |
| 2.5 Schema integrity contract | not started |  | Foreign keys, partitioning, transactions, batching, concurrency |
| 2.6 Retention and cleanup contract | not started |  | Retention and cleanup behavior against live rows and safety invariants |
| 2.7 Derived/current/fact/score contract | not started |  | Refresh semantics for current tables, facts, and score outputs |

### Wave 3 — Core Runtime Integration Rebuild

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 3.1 `Pool` lifecycle | not started |  | Config-to-live connection behavior, startup failure, cleanup guarantees |
| 3.2 `Brotr` boundary | not started |  | Real method-to-SQL behavior, transaction boundaries, lifecycle guarantees |
| 3.3 Shared service runtime seam | not started |  | Once/run loop behavior, runtime cleanup, service-state touch points |

### Wave 4 — Service Runtime Rebuild

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 4.1 `Seeder` | not started |  | Source ingestion, deduplication, persistence, seed-source failures |
| 4.2 `Finder` | not started |  | Discovery behavior, filtering, cooldown, persistence consequences |
| 4.3 `Validator` | not started |  | Validation, normalization, invalid-relay rejection, retry/failure effects |
| 4.4 `Monitor` | not started |  | Probe/doc ingestion, timeout behavior, current-state effects |
| 4.5 `Synchronizer` | not started |  | Archive, checkpoint, restart, cascade integrity, retention interactions |
| 4.6 `Refresher` | not started |  | Rolling windows, fact/current refresh correctness, stale-state recovery |
| 4.7 `Ranker` | not started |  | Score computation, store outputs, restart semantics, profile differences |
| 4.8 `Assertor` | not started |  | Score hydration, publication package creation, publish failure behavior |
| 4.9 `API` | not started |  | Read-surface exposure, bounded pagination/filter/sort, protocol error mapping |
| 4.10 `DVM` | not started |  | Request handling, output event creation, protocol failure mapping |

### Wave 5 — Cross-Service Pipeline Rebuild

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 5.1 Discovery pipeline | not started |  | `Seeder` -> `Finder` -> `Validator` -> `Monitor` |
| 5.2 Archive pipeline | not started |  | Discovery/validation inputs flowing into `Synchronizer` |
| 5.3 Derivation pipeline | not started |  | `Refresher` -> `Ranker` -> `Assertor` |
| 5.4 Public read pipeline | not started |  | Shared facts and outputs flowing into `API` and `DVM` |
| 5.5 Restart and idempotency pipeline | not started |  | Repeated runs, stale state, partial completion, resume semantics |

### Wave 6 — Deployment And Profile Matrix Rebuild

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 6.1 `bigbrotr` baseline profile | not started |  | Default deployment contract as first-class integration target |
| 6.2 `lilbrotr` profile | not started |  | Lightweight-profile compromises proved explicitly |
| 6.3 Internal fixture/deployment support | not started |  | Decide and test or retire `testbrotr` honestly |
| 6.4 Generated-SQL and deployed-SQL parity | not started |  | Keep generated SQL, deployed SQL, and integration schema setup aligned |

### Wave 7 — Failure, Recovery, And Resilience Rebuild

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 7.1 Timeout and retry contracts | not started |  | Single-budget timeout semantics, retry exhaustion, honest failure boundaries |
| 7.2 Database-failure contracts | not started |  | Transient DB errors, integrity violations, rollback guarantees |
| 7.3 External-boundary failure contracts | not started |  | Publish/connect/fetch failures, invalid payloads, degraded sources |
| 7.4 Cancellation, shutdown, and cleanup | not started |  | Mid-flight failure cleanup and partial-resource release guarantees |
| 7.5 Flake and concurrency hardening | not started |  | Repeated reruns, teardown observability, race elimination |

### Wave 8 — Final Audit, Cutover, And Closeout

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 8.1 Structural audit of the new suite | not started |  | Ensure every surviving file earns its place |
| 8.2 Remove or migrate obsolete surfaces | not started |  | Delete or migrate historical leftovers honestly |
| 8.3 Full-matrix repeated audit | not started |  | Repeat full reruns until unexplained drift disappears |
| 8.4 Final closeout | not started |  | Close ledger, document final suite shape, leave clean worktree |

---

## Section-Level Audit Record Template

Use this structure inside section notes when a work package closes:

- Contract proved:
- Real boundaries exercised:
- Intentional doubles used:
- Production drift exposed:
- Fixes applied before closure:
- Targeted tests:
- Full integration rerun:
- Full repository gates:
- PTY rerun needed:
- Commit:
- Follow-ups:

If one of these fields is empty because “it did not seem necessary”, the
section is probably underspecified and should not be closed yet.

---

## Open Follow-Ups And Watch Points

Use this section only for explicitly deferred items that survive a closed work
package.

Each entry must record:

- originating work package;
- what was deferred;
- why it was deferred;
- what later work package must absorb it;
- and whether it is a blocker, risk, or improvement.

No deferred item should survive silently.

---

## Update Rule

Whenever a work package closes:

1. update its row in this ledger;
2. record the commit hash and the real drift found;
3. record the gate stack actually run;
4. record whether a rerun was needed for opacity or flakiness;
5. ensure the closure happened in its own commit.

If a section required code fixes outside `tests/integration/`, record that
explicitly.
