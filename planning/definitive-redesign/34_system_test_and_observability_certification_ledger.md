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
| 0. Freeze the expanded test problem | done | The non-unit tracked baseline, the live deployment/monitoring inventory, the current-vs-required contract matrix, and the target taxonomy are now frozen explicitly; Wave 1 can start on a stable execution map instead of inventing structure on the fly |
| 1. Higher-band harness foundation | done | The higher-band harness foundation is now closed: `tests/system/`/`tests/live_smoke/` exist physically, compose lifecycle, artifact capture, runtime addressing, fault control, and observability API helpers are all in place, and the self-audit now proves deterministic repeated cycles without mutating the shipped compose assets |
| 2. Real relay infrastructure | done | The baseline relay is now pinned and proven against a real containerized `nostr-rs-relay` contract with startup/readiness, publish, query, live-subscribe, SQLite inspectability, and per-run artifacts; the capture relay path also proves exact live publication audit for ids/kinds/authors/tags/content/order plus duplicate-send semantics, the fault-injected path is live through digest-pinned `Toxiproxy` with latency, blackhole, reset, disable, and recovery drills, the secondary matrix adds digest-pinned `rnostr` under the same common contract, and the closing self-audit now proves repeated relay publish/read cycles, artifact manifests, and teardown cleanup across baseline/capture/fault/secondary roles without residual drift |
| 3. Deployment stack baseline | done | Both built-in profiles now reach deterministic baseline readiness with the same runtime-owned local relay path, honest one-shot compose snapshots, corrected shipped health checks, an explicit compose contract audit for dependency ordering and health probes, and a verified teardown/restart baseline that leaves no hidden Docker resource drift between cycles |
| 4. Service system certification | in progress | `Seeder` is now certified on the composed `bigbrotr` stack with real seed-file ownership, DB-side consequences, duplicate/idempotency proof, invalid-source handling, and clean once-run exits; the remaining nine service slices stay open |
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
| 0.3 Freeze current-vs-required coverage matrix | done | `docs: freeze system certification contract matrix` | Added `37_system_test_and_observability_contract_matrix.md` to freeze the higher-band proof map across service runtime, cross-service pipelines, real relay/public boundaries, and deployment/operator surfaces; the matrix records the current partial proof baseline, names the real boundaries that must become live, limits acceptable doubles explicitly, and assigns the missing proof to `tests/system/` or `tests/live_smoke/` instead of leaving it implicit |
| 0.4 Freeze target taxonomy | done | `docs: freeze system certification taxonomy` | Added `38_system_test_and_observability_taxonomy.md` to freeze the intended higher-band tree for `tests/system/`, `tests/live_smoke/`, compose overlays, relay assets, observability helpers, deployment/service/pipeline/observability/resilience subtrees, and the placement rules that keep public-network probes quarantined and test-owned assets out of shipped deployment folders |
| 0.5 Bootstrap execution ledger | done | `docs: add system test certification program` | This ledger now exists as the operational memory for the broader certification work |

### Wave 1 — Higher-Band Harness Foundation

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 1.1 Compose lifecycle harness | done | `test: add system compose lifecycle harness` | Added the first higher-band runtime scaffold under `tests/system/` plus `tests/live_smoke/`, introduced explicit `system` and `live_smoke` markers/targets so the unit gate keeps excluding those bands, and added `tests/system/harness/compose.py` with deterministic env rendering from built-in `.env.example`, normalized `docker compose ps` parsing, compose command execution, and readiness polling covered by `tests/unit/test_system_compose_harness.py` |
| 1.2 Artifact capture harness | done | `test: add system artifact capture harness` | Added `tests/system/harness/artifacts.py` with a canonical artifact bundle rooted in per-run directories plus manifest tracking for container logs, Prometheus target snapshots, Grafana and Alertmanager responses, relay captures, and DB-side snapshots; the new capture API is covered by `tests/unit/test_system_artifact_harness.py` so later system slices can persist teardown evidence instead of losing it in shell output |
| 1.3 Stable runtime addressing | done | `test: add system runtime addressing plan` | Added `tests/system/harness/addressing.py` with deterministic project-name generation, profile/slot-based host-port planning, runtime env overrides for service metrics, and runtime compose rewrites that replace fixed container names, remap fixed host ports, move mutable `postgres`/`ranker` bind mounts into per-run directories, and rename monitoring volumes/networks away from the shipped deployment names; coverage lives in `tests/unit/test_system_addressing_harness.py` |
| 1.4 Network fault-control harness | done | `test: add system fault control harness` | Added `tests/system/harness/faults.py` with a deterministic Toxiproxy-style admin client, slot-based admin/proxy port planning, explicit proxy/toxic payload models, and error surfacing for reset/create/list/delete operations; coverage in `tests/unit/test_system_fault_harness.py` now freezes the API shape for later relay-network latency/disconnect/reset drills |
| 1.5 Observability API harness | done | `test: add system observability API harness` | Added `tests/system/harness/observability.py` with validated HTTP clients for Prometheus, Grafana, and Alertmanager, including health endpoints, target/alert listing, PromQL query support, Grafana datasource/dashboard inventory, and structured error surfacing; coverage in `tests/unit/test_system_observability_harness.py` locks the endpoint map and query encoding before the higher-band observability slices arrive |
| 1.6 Harness self-audit | done | `test: audit system harness stability` | Added `tests/unit/test_system_harness_audit.py` to exercise repeated cycles across runtime addressing, compose command assembly, harness isolation, and shared stdlib-backed HTTP clients; the audit explicitly checks idempotent addressing, isolation of per-run roots, unchanged shipped compose files, and absence of hidden state across repeated Prometheus/Grafana/Toxiproxy calls |

### Wave 2 — Real Relay Infrastructure

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 2.1 Baseline relay selection and contract | done | `test: add relay baseline contract` | Selected digest-pinned `nostr-rs-relay` as the baseline relay and added `tests/system/harness/relay.py` plus unit coverage and real `tests/system/relay/test_nostr_rs_relay.py` proof for startup, REQ/EOSE readiness, publish `OK`, query replay, live subscribe after initial `EOSE`, container log capture, `docker inspect` evidence, and mounted SQLite file inspectability; the local audit loop reran `tests/unit/test_system_relay_harness.py tests/system/relay/test_nostr_rs_relay.py -q` `3x` green before the enclosing `tests/system/` rerun |
| 2.2 Capture relay | done | `test: add relay capture contract` | Extended the relay harness with generic signed-event builders and ordered live EVENT collection, then added `tests/system/relay/test_capture_relay.py` to prove a real capture subscription can audit exact publication ids, kinds, pubkeys, tags, contents, and arrival order across two distinct events while a duplicate resend remains observable only through the relay `OK` payload (`duplicate:`) and does not emit a second live EVENT; the local audit loop reran `tests/unit/test_system_relay_harness.py tests/system/relay/test_nostr_rs_relay.py tests/system/relay/test_capture_relay.py -q` `3x` green before the enclosing `tests/system/` rerun |
| 2.3 Fault-injected relay path | done | `test: add relay fault path contract` | Added deterministic Docker-network and local `Toxiproxy` runtimes plus proxy enable/disable control, then proved a real proxied relay path under latency, timeout-style blackhole, reset-peer, disconnect, and recovery semantics in `tests/system/relay/test_fault_injected_relay.py`; the slice also fixed a real harness drift exposed by the blackhole probe by making relay session close best-effort under broken sockets and by adding explicit WebSocket connect time budgets so disabled proxies fail deterministically instead of hanging teardown; the local audit loop reran `tests/unit/test_system_relay_harness.py tests/unit/test_system_fault_harness.py tests/system/relay/test_nostr_rs_relay.py tests/system/relay/test_capture_relay.py tests/system/relay/test_fault_injected_relay.py -q` `3x` green before the enclosing `tests/system/` rerun |
| 2.4 Secondary relay matrix | done | `test: add secondary relay matrix` | Added digest-pinned `rnostr` as the second real relay implementation through `LocalRnostrRuntime`, then proved the same common startup/readiness/publish/query/live-subscribe/duplicate semantics against both `nostr-rs-relay` and `rnostr` in `tests/system/relay/test_relay_matrix.py`; the real drift was supply-path related rather than protocol-level: the recommended `strfry` bootstrap could not be made executable in this environment because its official-source build path depended on GitHub submodule fetches plus in-container `apt` egress that failed during the probe, so the matrix was closed with `rnostr`, whose official README already ships a Docker-run path and whose `linux/amd64` image is now pinned by digest; the local audit loop reran `tests/unit/test_system_relay_harness.py tests/system/relay/test_nostr_rs_relay.py tests/system/relay/test_capture_relay.py tests/system/relay/test_fault_injected_relay.py tests/system/relay/test_relay_matrix.py -q` `3x` green before the enclosing `tests/system/` rerun |
| 2.5 Relay harness self-audit | done | `test: audit relay harness stability` | Added explicit relay/container and fault-network existence probes plus `tests/system/relay/test_relay_harness_audit.py`, which repeats baseline and secondary publish/query cycles with artifact-manifest checks and then audits capture plus proxied fault roles for duplicate semantics, recovery, and real Docker teardown; the real drift closed here was structural rather than product-level: the relay band still relied on per-slice green runs, but did not yet have a first-class self-audit proving that all relay roles remain leak-free and artifact-rich together, so this slice codified that contract directly; the local audit loop reran `tests/unit/test_system_relay_harness.py tests/unit/test_system_fault_harness.py tests/system/relay/test_nostr_rs_relay.py tests/system/relay/test_capture_relay.py tests/system/relay/test_fault_injected_relay.py tests/system/relay/test_relay_matrix.py tests/system/relay/test_relay_harness_audit.py -q` `3x` green before the enclosing `tests/system/` rerun |

### Wave 3 — Deployment Stack Baseline

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 3.1 `bigbrotr` stack baseline | done | `test: certify bigbrotr deployment baseline` | Added `tests/system/deployments/` plus the real `bigbrotr` baseline contract, then proved the shipped compose stack reaches honest readiness with artifact capture, `docker compose ps --all` snapshots for one-shot services, and repeated `3x` targeted reruns green; the real drift exposed and closed here was multi-layered: service containers were still using historical CLI paths instead of `/app/config` mounts, the `reader` role needed explicit `service_state` DML for `Dvm` cursor persistence, `handle_notifications()` had to run against the rebuilt async subscription handler instead of stale Docker images, `assertor` health checks were probing the wrong internal metrics port, and the baseline snapshot had to include exited `seeder`; repository gates run before closure: `make test-system`, `pre-commit --files ...`, `uv lock --check`, `make ci`, and `./.venv/bin/pytest tests/integration/ -q` |
| 3.2 `lilbrotr` stack baseline | done | `test: certify lilbrotr deployment baseline` | Added the real `lilbrotr` baseline contract plus shared runtime override helpers so both deployment profiles boot against a deterministic local relay instead of public relay availability; the real drift closed here was multi-step: the first runtime override attempt exposed that authored relay config rejected non-canonical internal hostnames, then a private-IP relay route exposed that shared multi-relay sessions were still hard-coded to `clearnet` only even though `local` direct relays do not need proxy policy. The slice now resolves the started relay to its private compose-network IP, allows canonical local relay URLs and local trusted-provider relay hints at the authored config boundary, widens shared session support from `clearnet` to direct relays (`clearnet` + `local`), and defends the harness with new unit coverage. Audit loop executed with one observed green baseline run, then `3x` repeated green reruns of `tests/system/deployments/bigbrotr/test_stack_baseline.py tests/system/deployments/lilbrotr/test_stack_baseline.py`, followed by green `make test-system`, before repository gates (`pre-commit --files ...`, `uv lock --check`, `make ci`, and `./.venv/bin/pytest tests/integration/ -q`) |
| 3.3 Health-check and dependency ordering audit | done | `test: audit deployment health and ordering contracts` | Added `tests/system/deployments/test_compose_contracts.py` to freeze the full `depends_on` and `healthcheck` matrix for all `17` services in both built-in profiles, including one-shot `seeder`, infra services, monitoring services, and the intentionally different profile-specific probes (`postgres` DB name and `assertor` metrics port). The new contract also proves profile parity by asserting that, after normalizing those two intentional deltas, the compose health/dependency surfaces are identical. Audit loop executed with `3x` green reruns of `tests/system/deployments/test_compose_contracts.py`, followed by green `make test-system`; repository gates for closure are `pre-commit --files ...`, `uv lock --check`, `make ci`, and `./.venv/bin/pytest tests/integration/ -q` |
| 3.4 Teardown and restart baseline | done | `test: certify deployment restart baseline` | Added shared deployment baseline helpers plus `tests/system/deployments/test_restart_baseline.py`, which runs two full start->ready->down cycles per profile on the same runtime plan and asserts that compose networks, compose containers, and the runtime relay container are all gone before the second cycle begins. The real drift exposed here was not product teardown but harness observability: `docker_container_exists()` used generic `docker inspect`, which falsely matched build-time images named like `<project>-finder:latest`; closing the slice required narrowing that helper to `docker container inspect` and defending it in `tests/unit/test_system_relay_harness.py`. Targeted proof is green with `./.venv/bin/pytest tests/system/deployments/test_restart_baseline.py -q`; band rerun is green with `make test-system` (`19 passed in 402.41s`); repository gates for closure are `pre-commit --files ...`, `uv lock --check`, `make ci`, and `./.venv/bin/pytest tests/integration/ -q` |

### Wave 4 — Service System Certification

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 4.1 `Seeder` | done | `test: certify seeder system contract` | Added `tests/system/services/` plus the first real service-runtime contract under `tests/system/services/seeder/`, proving candidate-mode insertion, direct relay insertion, duplicate/idempotency behavior across repeated one-shot runs, invalid-source handling, and clean `exited/0` once-run semantics against the composed `bigbrotr` stack with live PostgreSQL assertions. The real drift closed here was harness-level but only exposed at band scope: the service slice needed a runtime-owned `/app/static` seed tree plus first-class one-shot state polling and live DB query helpers, and the first `make test-system` run then exposed a deeper inter-slice issue where relay/fault tests left `DOCKER_CONFIG` pointing at the testcontainers-only empty config, which hides the Docker CLI compose plugin and makes later `docker compose` calls fail with exit `125`. Closing the slice required adding runtime static-mount rewrites, `ComposeStack.wait_until_state()`, runtime DB helpers, service-band scaffolding, and sanitizing `docker compose` subprocess env so compose plugin discovery no longer inherits the testcontainers override. Audit loop executed with `3x` green reruns of `tests/system/services/seeder/test_service.py -q`, a green relay-to-seeder minimal reproduction rerun, then green `make test-system` (`22 passed in 465.31s`); repository gates for closure are `pre-commit --files ...`, `uv lock --check`, `make ci`, and `./.venv/bin/pytest tests/integration/ -q` |
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
