# System Test And Observability Contract Matrix

## Purpose

This file freezes the current-versus-required proof matrix for the broader
system-test and observability certification program.

It is not a vague statement that “more end-to-end coverage would be nice”.
It is the auditable map of:

- what the repository already proves today;
- what still lacks proof at the correct runtime band;
- what boundary must be real;
- what doubles remain acceptable;
- and what target test band owns the missing proof.

This matrix is the execution companion for:

- [33_system_test_and_observability_certification_program.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/33_system_test_and_observability_certification_program.md)
- [34_system_test_and_observability_certification_ledger.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/34_system_test_and_observability_certification_ledger.md)
- [35_system_test_and_observability_manifest.txt](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/35_system_test_and_observability_manifest.txt)
- [36_system_test_and_observability_deployment_inventory.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/36_system_test_and_observability_deployment_inventory.md)

---

## Frozen Start State

- Matrix freeze date:
  `2026-04-21`
- Frozen branch:
  `refactor/definitive-redesign-execution`
- Frozen baseline commit:
  `0bf4afc2`
- Current tracked proof surface relevant to this matrix:
  `45` files under `tests/integration/`,
  `25` monitoring files under `deployments/bigbrotr/monitoring/`,
  `25` monitoring files under `deployments/lilbrotr/monitoring/`,
  `2` built-in deployment compose files,
  `4` operator-facing monitoring docs,
  and `1` metrics-specific unit suite.

The current repository therefore already has a serious proof baseline.
It does not yet have the higher-band runtime certification this program is
supposed to deliver.

---

## Current Proof Bands

| Band | Current State | What It Already Proves | What It Does Not Yet Prove |
|------|---------------|------------------------|----------------------------|
| `tests/unit/` | Strong in isolated areas | Metrics objects/server lifecycle, many service internals, harness helpers | Compose behavior, real relay behavior, Prometheus/Grafana/Alertmanager runtime |
| `tests/integration/` | Rebuilt and growing | Real PostgreSQL/shared-schema contracts plus selected `Refresher`/`Ranker`/`Assertor` behavior | Deployment-fidelity runtime, real relay protocol, full service matrix, observability stack |
| `tests/system/` | Not started | Nothing yet | All higher-band runtime certification |
| `tests/live_smoke/` | Not started | Nothing yet | Optional public-network proof outside the merge gate |
| Deployment assets under `deployments/*/monitoring/` | Present but not certified | Intended operator surface exists in version control | That the live stack loads, scrapes, alerts, and renders honestly |

---

## Service Runtime Matrix

| Service | Current Proof | Required Higher-Band Outcome | Real Boundary That Must Be Exercised | Acceptable Doubles | Target Band | Gap Type |
|---------|---------------|------------------------------|--------------------------------------|--------------------|-------------|----------|
| `Seeder` | None at non-unit bands | Compose-run `--once` ingestion, persistence, exit semantics, invalid-source handling | Service process/container + live DB + real deployment wiring | Deterministic fixture source only | `tests/system/services/seeder/` | Missing |
| `Finder` | None at non-unit bands | Real fetch/cooldown/dedup/persistence/restart proof | Service process/container + live DB + real config/env wiring | Deterministic HTTP source only | `tests/system/services/finder/` | Missing |
| `Validator` | None at non-unit bands | Real relay validation, invalid-relay rejection, retry/failure semantics | Service process/container + real relay + live DB | None for relay protocol; optional DNS fault harness only | `tests/system/services/validator/` | Missing |
| `Monitor` | None at non-unit bands | Real probe storage, degraded-relay behavior, checkpoint/restart semantics | Service process/container + real relay and HTTP/NIP surfaces + live DB | Deterministic probe-fault harness only where relay realism is preserved | `tests/system/services/monitor/` | Missing |
| `Synchronizer` | None at non-unit bands | Real archive ingestion, checkpointing, dedup, disconnect recovery, restart/resume | Service process/container + real relay event stream + live DB | None for relay stream; fault harness allowed only around the network path | `tests/system/services/synchronizer/` | Missing |
| `Refresher` | Strong integration proof in `tests/integration/base/test_refresher.py` | Deployment-fidelity runtime, service process lifecycle, restart, health wiring | Service process/container + live DB + real deployment wiring | None beyond deterministic time helpers if strictly needed | `tests/system/services/refresher/` | Structural |
| `Ranker` | Strong integration proof in `tests/integration/base/test_ranker.py` | Deployment-fidelity run, file-store contract, restart, profile-difference proof | Service process/container + live DB + real storage mounts | Temporary local storage only | `tests/system/services/ranker/` | Structural |
| `Assertor` | Strong integration proof plus pipeline proof in `tests/integration/base/test_assertor.py` and `test_nip85_pipeline.py` | Real relay publication capture, publish-failure semantics, restart proof | Service process/container + real relay publish path + live DB | None for relay publication; capture relay is real, not a fake publish client | `tests/system/services/assertor/` | Structural |
| `API` | None at non-unit bands | HTTP runtime contract: payloads, filters, sort, pagination, error mapping | Service process/container + live DB + real HTTP boundary | No DB fake; thin HTTP client helper only | `tests/system/services/api/` | Missing |
| `DVM` | None at non-unit bands | Nostr event/job runtime contract: request/response semantics, reconnect, payload correctness | Service process/container + real relay + live DB | No fake relay; capture helpers only | `tests/system/services/dvm/` | Missing |

---

## Cross-Service Pipeline Matrix

| Pipeline | Current Proof | Required Higher-Band Outcome | Real Boundary That Must Be Exercised | Acceptable Doubles | Target Band | Gap Type |
|----------|---------------|------------------------------|--------------------------------------|--------------------|-------------|----------|
| Discovery (`Seeder` -> `Finder` -> `Validator` -> `Monitor`) | None | Real composed discovery flow from seed source to monitored relay state | Multiple live service containers + real relay for validation/monitoring + live DB | Deterministic seed/source fixture only | `tests/system/pipelines/discovery/` | Missing |
| Archive (`Validator`/`Monitor` -> `Synchronizer`) | None | Real validated relay feeds archive ingestion with honest checkpoints and dedup | Live relay + live service containers + live DB | None for relay path | `tests/system/pipelines/archive/` | Missing |
| Derivation (`Refresher` -> `Ranker` -> `Assertor`) | Narrow integration smoke only | Composed runtime plus restart/idempotency and relay publication capture | Live services + live DB + real relay capture | None for publish path | `tests/system/pipelines/derivation/` | Structural |
| Public read (`DB` -> `API` and `DVM`) | None | End-to-end read surface correctness via HTTP and event boundaries | Live API/DVM containers + live DB + real relay for DVM | None for public boundaries | `tests/system/pipelines/read_surfaces/` | Missing |
| Restart/partial completion | None | Interrupted flows resume honestly without duplicate or hidden loss | Live containers, live DB, real relay where relevant | Fault harness around orchestration only | `tests/system/pipelines/restart/` | Missing |

---

## Real Relay And Public Boundary Matrix

| Boundary Surface | Current Proof | Required Outcome | Real Boundary Requirement | Acceptable Doubles | Target Band | Gap Type |
|------------------|---------------|------------------|---------------------------|--------------------|-------------|----------|
| Baseline local relay | None | One first-class local relay implementation with explicit contract and artifacts | Real relay server/container | None | `tests/system/relay/` via Wave 2 | Missing |
| Capture relay for publication | None | Exact capture of `Assertor` and `DVM` publications | Real relay server/container dedicated to capture | None | `tests/system/relay/` | Missing |
| Fault-injected relay path | None | Controlled latency/disconnect/reset semantics | Real relay behind deterministic proxy/fault layer | Proxy harness only; not a fake relay | `tests/system/relay/` | Missing |
| `API` HTTP boundary | None beyond unit/integration internals | Response correctness over real HTTP | Real service container/process and real port | Thin client helper only | `tests/system/services/api/` | Missing |
| `DVM` request/reply boundary | None | Response-event correctness over real relay traffic | Real service container/process and real relay | None | `tests/system/services/dvm/` | Missing |
| Public relay smoke | None | Optional non-gating public-network proof | Real public relay hosts | No doubles in live smoke | `tests/live_smoke/` | Missing but intentionally deferred |

---

## Deployment And Operator Surface Matrix

| Surface | Current Proof | Required Outcome | Real Boundary That Must Be Exercised | Acceptable Doubles | Target Band | Gap Type |
|---------|---------------|------------------|--------------------------------------|--------------------|-------------|----------|
| `bigbrotr` compose startup | None | All intended containers reach ready/healthy state with clean logs and honest dependency ordering | Real Docker Compose stack | None | `tests/system/deployments/bigbrotr/` | Missing |
| `lilbrotr` compose startup | None | Equivalent startup proof for lightweight profile | Real Docker Compose stack | None | `tests/system/deployments/lilbrotr/` | Missing |
| Health checks and dependency edges | Only declared in YAML | Runtime audit that the checks are sufficient and truthful | Real Docker Compose health checks | None | `tests/system/deployments/` | Missing |
| Clean teardown/restart | None | Clean stop, clean restart, no hidden drift across reruns | Real Docker Compose lifecycle | None | `tests/system/deployments/` | Missing |
| Metrics endpoint emission | Strong unit proof in `tests/unit/core/test_metrics.py`; no deployment proof | Real service endpoints expose intended series under deployment config | Live service containers/processes | None for emitted endpoint itself | `tests/system/observability/metrics/` | Partial |
| Prometheus scrape configuration | Config files only | Targets `UP`, correct jobs, required series present | Real Prometheus container scraping live targets | None | `tests/system/observability/prometheus/` | Missing |
| Alert rules | YAML only | Positive and negative rule semantics against live series | Real Prometheus + real Alertmanager path | None | `tests/system/observability/alerts/` | Missing |
| Alertmanager routing | YAML only | Routing config loads and accepts intended alerts | Real Alertmanager container/API | None | `tests/system/observability/alertmanager/` | Missing |
| Grafana datasource provisioning | YAML only | Datasource loads, is reachable, and stays stable | Real Grafana container/API | None | `tests/system/observability/grafana/` | Missing |
| Grafana dashboard provisioning | JSON/YAML only | All dashboards load with stable UID and no missing refs | Real Grafana container/API | None | `tests/system/observability/grafana/` | Missing |
| Grafana dashboard query semantics | None | Panels resolve against live metrics and current labels | Real Grafana + real Prometheus + live services | None | `tests/system/observability/grafana/` | Missing |
| postgres-exporter query surface | YAML only | Exporter starts, loads custom queries, and exposes expected series | Real postgres-exporter container + live Postgres | None | `tests/system/observability/postgres_exporter/` | Missing |
| Monitoring/operator docs parity | Documentation only | Docs match the certified live stack and its expected operator actions | Real certified stack plus docs audit | None | `tests/system/observability/docs/` and planning closeout | Missing |

---

## Realism Rules By External Dependency

| External Dependency | Current State | Rule For This Program |
|---------------------|---------------|-----------------------|
| PostgreSQL | Already real in integration | Keep real in every higher band |
| PgBouncer | Present only in deployment assets | Must become real in deployment-fidelity system tests |
| Docker Compose lifecycle | Present only as operator surface | Must be exercised directly in `tests/system/` |
| Relay/WebSocket protocol | Mostly absent from non-unit proof | Must be real for `Validator`, `Monitor`, `Synchronizer`, `Assertor`, and `DVM` |
| Seed/input HTTP sources | Not yet proven at higher bands | May use deterministic fixture service if the product contract is the consumer behavior |
| Prometheus | Config-only today | Must be real for scrape and alert certification |
| Grafana | Config-only today | Must be real for datasource and dashboard certification |
| Alertmanager | Config-only today | Must be real for routing/config-load certification |
| postgres-exporter | Config-only today | Must be real for exporter certification |
| Public relays on the open network | Not used today | Allowed only in quarantined `tests/live_smoke/`, never in the main gate |

---

## Frozen Execution Priorities

Execution priority for the higher-band certification remains:

1. freeze the current problem honestly;
2. build the reusable `tests/system/` harness first;
3. stand up the real relay layer before relay-facing service proofs;
4. certify deployment startup and restart before deep cross-service pipelines;
5. certify each service at its true runtime boundary;
6. certify cross-service pipelines only after the service baselines are green;
7. certify observability with real Prometheus/Grafana/Alertmanager/exporter;
8. quarantine any truly public-network proof under `tests/live_smoke/`;
9. remove or retire weaker historical surfaces only after the higher band is
   clearly stronger.

This order is mandatory.
It prevents the program from:

- calling config files “certified” before the live stack is running;
- faking relay behavior while claiming system proof;
- or declaring observability done before emitted metrics and downstream queries
  are proven together.
