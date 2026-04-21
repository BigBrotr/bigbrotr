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
  `git ls-files tests/integration | sort`
- Frozen integration-file count:
  `24`
- Frozen date:
  `2026-04-21`
- Notes:
  The rebuild starts from baseline commit `e0fb0e45` on branch
  `refactor/definitive-redesign-execution`. The current tracked integration
  surface is frozen in
  [30_integration_test_rebuild_manifest.txt](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/30_integration_test_rebuild_manifest.txt),
  the live current-vs-target contract matrix is frozen in
  [31_integration_test_rebuild_contract_matrix.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/31_integration_test_rebuild_contract_matrix.md),
  and the target suite topology is frozen in
  [32_integration_test_rebuild_taxonomy.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/32_integration_test_rebuild_taxonomy.md).
  The historical `base/` and `lilbrotr/` trees are preserved only as
  reference input until the new taxonomy absorbs their unique proof.

---

## Program Summary

| Wave | Status | Notes |
|------|--------|-------|
| 0. Baseline freeze and rebuild bootstrapping | done | Tracked inventory (`24` files), live contract matrix, and target taxonomy are now frozen explicitly; the rebuild starts from `base/` + `lilbrotr/` as reference-only historical subtrees and will move all new work into the new target topology |
| 1. Harness redesign | done | The harness now has an explicit bootstrap seam under `tests/integration/harness/`: container lifecycle, schema bootstrap, deployment-aware `Brotr` factory, canonical builders, deterministic support, named doubles, explicit failure injection seams, and a repeated self-audit bundle are in place; harness-only reruns (`3x`) and patch-boundary integration reruns (`2x`) stayed stable before closure |
| 2. Shared PostgreSQL contract rebuild | in progress | The first rebuilt storage contract now lives under `tests/integration/shared_db/` with its own local fixture and guidance; historical `base/` files remain only while unique proof is still being migrated slice by slice |
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
| 0.1 Freeze current integration inventory | done | `docs: freeze integration rebuild baseline` | Exact tracked baseline frozen in `30_integration_test_rebuild_manifest.txt`; current tracked integration surface is `24` files rooted in the historical `base/` and `lilbrotr/` subtrees plus root harness support files |
| 0.2 Freeze live contract matrix | done | `docs: freeze integration rebuild baseline` | Live current-vs-target matrix captured in `31_integration_test_rebuild_contract_matrix.md`, including service/runtime/profile/failure gaps and acceptable external-doubles policy |
| 0.3 Freeze target suite taxonomy | done | `docs: freeze integration rebuild baseline` | Final target topology frozen in `32_integration_test_rebuild_taxonomy.md`; all new integration work must now land under the new `harness/shared_db/core/services/pipelines/deployments/failures` structure |
| 0.4 Bootstrap execution ledger | done | `docs: add integration rebuild program` | This ledger and the paired normative program now exist as the canonical planning baseline |

### Wave 1 — Harness Redesign

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 1.1 Container lifecycle and schema bootstrap | done | `test: redesign integration harness bootstrap` | PostgreSQL lifecycle, Docker/testcontainers environment prep, deployment-aware schema reset/truncate logic, and the live `Brotr` factory were extracted from the monolithic root `conftest.py` into `tests/integration/harness/{postgres,schema,brotr,fixtures}.py`; `tests/integration/conftest.py` is now a thin fixture entrypoint, profile `conftest.py` files depend on the shared harness directly, and the new harness behavior is covered by `tests/unit/test_integration_harness.py` plus the full green integration rerun |
| 1.2 Canonical data builders | done | `test: add canonical integration record builders` | Added `tests/integration/harness/builders/records.py` plus local builder docs/exports for relays, events, event observations, relay documents, service state, and canonical event-address strings; builder semantics are now pinned by `tests/unit/test_integration_builders.py`, and the historical DB/refresher/lilbrotr integration files now consume the shared builders instead of carrying duplicate record-construction logic |
| 1.3 Named external doubles | done | `test: add named integration protocol doubles` | Added `tests/integration/harness/doubles/protocol.py` plus local exports/docs for the publish-client, publish-session, and broadcast-recorder doubles; `tests/integration/base/test_assertor.py` and `tests/integration/base/test_nip85_pipeline.py` now use the shared harness doubles instead of inline `AsyncMock` clouds, and the new boundary helpers are pinned by `tests/unit/test_integration_protocol_doubles.py` |
| 1.4 Deterministic support utilities | done | `test: add deterministic integration utilities` | Added `tests/integration/harness/deterministic.py` plus unit proof for fixed timestamps, synthetic identifiers, monotonic timestamp sequencing, and canonical ranker storage paths; shared builder and protocol-double support now consume the same deterministic constants, and the partitioning/ranker/assertor/NIP-85 integration files no longer rely on temp-path duplication or random event ids |
| 1.5 Failure-injection harness | done | `test: add integration failure injection seams` | Added `tests/integration/harness/failures.py` with observable async outcome plans, canonical timeout/cancellation/database failure builders, and a reusable `patched_assertor_publish_boundary()` seam; `tests/integration/base/test_assertor.py` and `tests/integration/base/test_nip85_pipeline.py` now consume the harness instead of inline patch clouds, and the seam is pinned by `tests/unit/test_integration_failures.py` |
| 1.6 Harness self-audit | done | `test: add integration harness self-audit` | Added `tests/unit/test_integration_harness_audit.py` and tightened `tests/integration/harness/README.md` so harness closure now depends on an explicit self-audit bundle; the audit surfaced and fixed a real seam drift in `patched_assertor_publish_boundary()` relay reuse, then stayed stable across repeated harness-only reruns (`3x`) and repeated `Assertor`/`NIP-85` integration reruns (`2x`) |

### Wave 2 — Shared PostgreSQL Contract Rebuild

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 2.1 Relay storage contract | done | `test: rebuild relay storage integration contract` | Added the first target-taxonomy shared DB subtree (`tests/integration/shared_db/`) with local `README.md`, package marker, and a `bigbrotr` fixture entrypoint; `test_relay_storage.py` now proves canonical clearnet insert, parse-to-storage canonicalization, idempotent duplicate handling, same-batch dedup, network classification, IPv6 round-trip, and concurrent convergence without adding new relay coverage to the historical `base/` tree |
| 2.2 Document and relay-document contract | done | `test: rebuild document storage integration contract` | Added `tests/integration/shared_db/test_document_storage.py` to the target taxonomy and rebuilt the document/relay-document contract around the shared harness builders: direct content-addressed insert, type-scoped dedup, nested JSON round-trip, cascade association creation, cross-relay document reuse, multi-timestamp associations, exact-junction idempotency, and non-cascade missing-parent failures are now proven under `shared_db/` instead of being extended inside the historical `base/` tree |
| 2.3 Event and event-observation contract | done | `test: rebuild event storage integration contract` | Added `tests/integration/shared_db/test_event_storage.py` and rebuilt the event/event-observation storage contract around shared builders: direct event row round-trip, duplicate idempotency, `tagvalues` derivation from persisted tags, cascade relay+event+junction creation, same-event multi-relay reuse, same-relay batch behavior, exact observation idempotency, and non-cascade missing-parent failures are now proven in the target `shared_db/` subtree |
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
