# System Test And Observability Certification Ledger

## Purpose

This ledger is the operational companion for:

- [33_system_test_and_observability_certification_program.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/33_system_test_and_observability_certification_program.md)

It exists so the broader test certification work does not depend on:

- memory;
- scattered shell history;
- implicit assumptions about what “system tested” means;
- or ambiguous claims that observability was “checked”.

Every closed subsection in the certification program must update this ledger.

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

- Current `tests/system/` tracked file count:
  `0`
- Current `tests/live_smoke/` tracked file count:
  `0`
- Frozen date:
  `2026-04-21`
- Frozen branch:
  `refactor/definitive-redesign-execution`
- Notes:
  The broader certification baseline starts from commit `601fb0b2` on branch
  `refactor/definitive-redesign-execution`. The frozen non-unit tracked surface
  now lives in
  [35_system_test_and_observability_manifest.txt](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/35_system_test_and_observability_manifest.txt)
  and currently contains `102` tracked files:
  `45` under `tests/integration/`, `25` under
  `deployments/bigbrotr/monitoring/`, `25` under
  `deployments/lilbrotr/monitoring/`, `2` deployment compose files, `4`
  operator-facing monitoring docs, and `1` metrics-specific unit suite.
  `tests/system/` and `tests/live_smoke/` are still empty tracked surfaces at
  this freeze point.

---

## Program Summary

| Wave | Status | Notes |
|------|--------|-------|
| 0. Freeze the expanded test problem | in progress | The non-unit tracked baseline and the live deployment/monitoring inventory are now frozen explicitly; the coverage matrix and target taxonomy still need their own closing slices |
| 1. Higher-band harness foundation | not started | Compose lifecycle, artifact capture, network fault control, and observability API helpers |
| 2. Real relay infrastructure | not started | Baseline relay, capture relay, fault-injected relay path, and optional secondary relay matrix |
| 3. Deployment stack baseline | not started | Clean `bigbrotr` and `lilbrotr` startup, health, dependency ordering, and restart baseline |
| 4. Service system certification | not started | Real runtime certification for all ten services |
| 5. Cross-service system pipelines | not started | Discovery, archive, derivation, public-read, and restart pipelines |
| 6. Observability certification | not started | Metrics, Prometheus, alerts, Grafana, exporter, and operator-doc parity |
| 7. Failure, recovery, and resilience | not started | Relay, DB, observability, restart, and concurrency hardening |
| 8. Profile parity and deployment hardening | not started | `bigbrotr` vs `lilbrotr` runtime and monitoring parity |
| 9. Final audit, cutover, and closeout | not started | Structural cleanup, repeated matrix reruns, and formal closure |

---

## Work-Package Checklist

### Wave 0 — Freeze The Expanded Test Problem

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 0.1 Freeze current non-unit test inventory | done | `docs: freeze system test certification baseline` | The broader certification baseline is now frozen in `35_system_test_and_observability_manifest.txt` with `102` tracked files spanning `tests/integration/`, both deployment monitoring trees, both deployment compose files, operator-facing monitoring docs, and the metrics-specific unit suite; `tests/system/` and `tests/live_smoke/` are explicitly frozen at `0` tracked files |
| 0.2 Freeze live deployment and monitoring inventory | done | `docs: freeze system deployment inventory` | Added `36_system_test_and_observability_deployment_inventory.md` to freeze the live built-in deployment shape: both profiles currently ship `17` compose services, `25` tracked monitoring files each, identical monitoring subtree shape, distinct DB/metrics/monitoring host-port ranges, and profile-root Grafana dashboards `bigbrotr.json` vs `lilbrotr.json`; the inventory also records that postgres-exporter stays internal-only on `9187` and that `seeder` remains outside the continuous metrics port range |
| 0.3 Freeze current-vs-required coverage matrix | not started |  | Record current proof vs required proof for services, pipelines, relays, and observability surfaces |
| 0.4 Freeze target taxonomy | not started |  | Freeze the target tree for `tests/system/`, `tests/live_smoke/`, overlays, artifacts, and helper modules |
| 0.5 Bootstrap execution ledger | done | `docs: add system test certification program` | This ledger now exists as the operational memory for the broader certification work |

### Wave 1 — Higher-Band Harness Foundation

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 1.1 Compose lifecycle harness | not started |  | Deterministic compose up/down, env generation, readiness polling, cleanup |
| 1.2 Artifact capture harness | not started |  | Container logs, Prometheus targets, Grafana provisioning responses, relay captures, DB snapshots |
| 1.3 Stable runtime addressing | not started |  | Port, host, volume, and project-name discipline for repeatable runs |
| 1.4 Network fault-control harness | not started |  | Deterministic TCP/WebSocket failure shaping for relay and selected service paths |
| 1.5 Observability API harness | not started |  | Prometheus/Grafana/Alertmanager inspection and query helpers |
| 1.6 Harness self-audit | not started |  | Repeated reruns proving harness stability before dependent slices close |

### Wave 2 — Real Relay Infrastructure

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 2.1 Baseline relay selection and contract | not started |  | Select first relay implementation and prove baseline local contract |
| 2.2 Capture relay | not started |  | Exact publication-capture path for `Assertor` and `DVM` |
| 2.3 Fault-injected relay path | not started |  | Controlled latency/disconnect/reset path through the selected proxy mechanism |
| 2.4 Secondary relay matrix | not started |  | Add a second relay implementation only after baseline proof is green |
| 2.5 Relay harness self-audit | not started |  | Repeat relay drills until deterministic and artifact-rich |

### Wave 3 — Deployment Stack Baseline

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 3.1 `bigbrotr` stack baseline | not started |  | Clean startup and readiness for the baseline deployment stack |
| 3.2 `lilbrotr` stack baseline | not started |  | Equivalent stack baseline for the lightweight profile |
| 3.3 Health-check and dependency ordering audit | not started |  | Certify that health and ordering edges are honest and sufficient |
| 3.4 Teardown and restart baseline | not started |  | Clean teardown, clean restart, and absence of hidden harness drift |

### Wave 4 — Service System Certification

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 4.1 `Seeder` | not started |  | Real seed ingestion, persistence, invalid-source, and once-run exit semantics |
| 4.2 `Finder` | not started |  | Real source fetch path, cooldown, dedup, persistence, and restart semantics |
| 4.3 `Validator` | not started |  | Real relay validation, invalid-relay rejection, and retry/failure semantics |
| 4.4 `Monitor` | not started |  | Real probe storage, degraded-relay behavior, checkpoints, and restart semantics |
| 4.5 `Synchronizer` | not started |  | Real archive ingestion, checkpoints, dedup, restart/resume, and disconnect recovery |
| 4.6 `Refresher` | not started |  | Real runtime orchestration, state touch points, stale-state recovery, and restart behavior |
| 4.7 `Ranker` | not started |  | Real score outputs, private store behavior, profile differences, and restart semantics |
| 4.8 `Assertor` | not started |  | Real publication capture, event correctness, publish failure handling, and restart behavior |
| 4.9 `API` | not started |  | Real HTTP boundary certification, payload correctness, pagination/filter/sort, and error mapping |
| 4.10 `DVM` | not started |  | Real relay/event boundary certification, response event correctness, and reconnect behavior |

### Wave 5 — Cross-Service System Pipelines

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 5.1 Discovery pipeline | not started |  | `Seeder` -> `Finder` -> `Validator` -> `Monitor` under the composed stack |
| 5.2 Archive pipeline | not started |  | Validated relays flowing into `Synchronizer` with honest persistence and checkpoints |
| 5.3 Derivation pipeline | not started |  | `Refresher` -> `Ranker` -> `Assertor` with real publication capture |
| 5.4 Public read pipeline | not started |  | Shared state flowing into `API` and `DVM` through their true boundaries |
| 5.5 Restart and partial-completion pipeline | not started |  | Resume, idempotency, and honest failure under interrupted composed flows |

### Wave 6 — Observability Certification

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 6.1 Emitted metrics schema contract | not started |  | Metric names, labels, semantics, and lifecycle behavior |
| 6.2 Deployment metrics wiring contract | not started |  | Real deployment config enabling/exposing intended metrics surfaces |
| 6.3 `bigbrotr` Prometheus scrape contract | not started |  | Target health, target correctness, and required series presence |
| 6.4 `lilbrotr` Prometheus scrape contract | not started |  | Equivalent scrape certification for the lightweight profile |
| 6.5 `bigbrotr` alert-rule contract | not started |  | Positive and negative alert semantics |
| 6.6 `lilbrotr` alert-rule contract | not started |  | Profile-specific alert semantics and parity checks |
| 6.7 Grafana datasource provisioning contract | not started |  | Datasource presence, UID stability, and connectivity |
| 6.8 Alertmanager routing contract | not started |  | Routing config load, alert acceptance, and documented semantics |
| 6.9 Dashboard provisioning integrity contract | not started |  | Dashboard load, UID stability, and provisioning completeness |
| 6.10 Dashboard query semantics contract | not started |  | Panel queries resolve against live metrics and current labels |
| 6.11 Postgres-exporter contract | not started |  | Exporter startup, custom query correctness, and schema parity |
| 6.12 Operator-document parity contract | not started |  | Monitoring docs align with the certified live stack |

### Wave 7 — Failure, Recovery, And Resilience

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 7.1 Relay-network failures | not started |  | Latency, disconnect, reset, timeout, degraded subsets, and recovery |
| 7.2 Database and pool failures | not started |  | Startup failure, transient DB loss, and rollback honesty |
| 7.3 Observability-stack failures | not started |  | Prometheus/Grafana/Alertmanager/exporter degradation and resulting semantics |
| 7.4 Service restart and mid-flight interruption | not started |  | Container restart, repeated restarts, and interrupted work recovery |
| 7.5 Flake and concurrency hardening | not started |  | Repeat high-risk runs until unexplained drift disappears |

### Wave 8 — Profile Parity And Deployment Hardening

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 8.1 `bigbrotr` vs `lilbrotr` service/runtime parity | not started |  | Shared contracts plus intentional profile differences only |
| 8.2 Monitoring parity | not started |  | Datasources, dashboards, alerts, and exporter semantics across both profiles |
| 8.3 SQL and deployment asset parity | not started |  | Generated SQL, deployed SQL, and certified stack remain aligned |
| 8.4 Operator-experience audit | not started |  | Final operator-facing coherence review for the deployment stack |

### Wave 9 — Final Audit, Cutover, And Closeout

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 9.1 Structural audit | not started |  | Every surviving file and helper must justify its place |
| 9.2 Remove obsolete or weak surfaces | not started |  | Delete or migrate superseded tests, helpers, and monitoring drift surfaces |
| 9.3 Full repeated matrix audit | not started |  | Repeat full higher-band reruns until residual unexplained weakness is gone |
| 9.4 Final closeout | not started |  | Close the ledger honestly and leave a clean worktree |

---

## Section-Level Audit Record Template

Use this structure whenever one work package closes:

- Contract proved:
- Real boundaries exercised:
- Allowed doubles used:
- Production/deployment drift exposed:
- Fixes applied before closure:
- Targeted tests:
- Repeat reruns:
- Band rerun:
- Repository gates:
- PTY rerun needed:
- Commit:
- Negative audit notes remaining:
- Follow-ups:

If `Negative audit notes remaining` is not empty, the work package is not
closed.

---

## Update Rule

Whenever a work package closes:

1. update its row in this ledger;
2. record the exact commit hash;
3. record the real drift found;
4. record the targeted tests and repeated reruns actually run;
5. record whether PTY reruns were required for observability;
6. record the full repository gates actually run;
7. leave no unresolved negative audit note.
