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
| 4. Service system certification | done | All ten services are now certified against their real authored boundaries on the composed stack: file-owned seed ingestion, controlled HTTP discovery, real `wss` relay validation/probing/archive, derived-table refresh, private rank-store behavior, real provider-package publication capture, real HTTP API surface, and real DVM relay request/response semantics |
| 5. Cross-service system pipelines | done | Discovery, archive, derivation, public-read, and restart/resume pipelines are now certified end-to-end under the composed stack with live PostgreSQL, live relay/runtime boundaries, and restart/idempotency assertions instead of service-local proofs only |
| 6. Observability certification | done | Emitted metric schema, deployment metrics wiring, Prometheus scrape semantics, alert rules, Grafana datasource/provisioning/query contracts, Alertmanager routing, postgres-exporter correctness, and operator-doc parity are now all certified on the live monitoring stack for both built-in profiles |
| 7. Failure, recovery, and resilience | done | Relay, database/pool, observability-stack, service-restart, and concurrency resilience bands are now certified with real fault injection, repeated reruns, and cleanup hardening until unexplained drift disappeared |
| 8. Profile parity and deployment hardening | done | `bigbrotr` vs `lilbrotr` runtime parity, monitoring parity, SQL/deployment asset parity, and operator-surface coherence are now all certified with only intentional profile differences left alive |
| 9. Final audit, cutover, and closeout | done | Structural audit, weak-surface removal, repeated no-change matrix reruns, and formal ledger closeout are complete; the final higher-band tracked surface is `136` files under `tests/system/` plus `2` under `tests/live_smoke/`, and the closing rerun is green with `95` system tests, `5410` unit/non-system tests, and `293` integration tests |

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
| 4.2 `Finder` | done | `test: certify finder system contract` | Added `tests/system/services/finder/` plus a host-side HTTP fixture runtime wired into the composed stack through runtime-only `extra_hosts`, then proved real API-source discovery against the authored Finder service: one-shot fetch persistence, duplicate relay deduplication, invalid-source filtering, checkpoint persistence, and restart-time cooldown skipping with live PostgreSQL assertions and captured HTTP request artifacts. The real drift closed here was slice-local but genuine: the first green path exposed that closeout assertions were reconstructing the Docker-facing source URL after the local HTTP fixture had already been stopped, so the contract now freezes and reuses the exact runtime source URL instead of deriving it from post-shutdown state. Closing the slice also extended runtime overrides with deterministic host-gateway injection and added a first-class local HTTP fixture harness plus unit coverage so later service/system slices can exercise real HTTP boundaries without falling back to mocks. Audit loop executed with `3x` green reruns of `tests/system/services/finder/test_service.py -q`, then a green band rerun of `tests/system/test_band_contract.py tests/system/services/finder/test_service.py -q`; repository gates for closure are `make test-system`, `pre-commit --files ...`, `uv lock --check`, `make ci`, and `./.venv/bin/pytest tests/integration/ -q` |
| 4.3 `Validator` | done | `test: certify validator system contract` | Added `tests/system/services/validator/` plus a real `wss` validator contract around the shipped container: one baseline relay behind a deterministic TLS boundary is promoted into `relay`, while a separate invalid `wss` candidate backed by a plain HTTP endpoint is rejected and persisted as a failed validator checkpoint with restart-time backoff. The slice closed two real drifts. First, `allow_insecure=True` was not actually honoring rust-side certificate failures such as `invalid peer certificate: UnknownIssuer`, so `src/bigbrotr/utils/protocol.py` now recognizes those SSL strings and the validator can fall back to insecure transport exactly when promised. Second, a websocket endpoint that simply accepted a REQ and closed cleanly was still treated as “valid enough” by the runtime, so the invalid side of the contract was tightened to a non-websocket HTTP boundary that fails during connect/fetch rather than accidentally completing an empty fetch. Audit loop executed with green targeted unit coverage for `tests/unit/test_system_database_harness.py tests/unit/test_system_websocket_harness.py tests/unit/utils/test_protocol.py`, `3x` green reruns of `tests/system/services/validator/test_service.py -q`, then a green band rerun of `tests/system/test_band_contract.py tests/system/services/validator/test_service.py -q`; repository gates for closure are `make test-system`, `pre-commit --files ...`, `uv lock --check`, `make ci`, and `./.venv/bin/pytest tests/integration/ -q` |
| 4.4 `Monitor` | done | `test: certify monitor system contract` | Added `tests/system/services/monitor/` plus the first real monitor-runtime contract around the shipped container: a healthy relay path now runs through a deterministic host-side TLS relay proxy that serves both `https` NIP-11 fetches and `wss` RTT probes against `nostr-rs-relay`, while a second TLS relay proxy fronts a blackholed Toxiproxy path to prove degraded-check checkpoint persistence without inventing fake boundaries. The slice closed several real harness drifts that only appeared once Monitor was exercised at the authored system boundary: raw Docker IPs were reclassified as `local` and short Docker aliases were rejected as invalid clearnet hosts, while canonical `wss://` relay rows also required a same-origin `https://` path for NIP-11 rather than a websocket-only TLS shim. Closing the slice therefore extended the TLS websocket harness so proxy mode can serve proxied HTTP responses on the same certified TLS origin, added Toxiproxy network-alias support for later service bands, and codified the live Monitor semantics that healthy relays persist `nip11_info` + `nip66_rtt`, degraded relays still advance monitor checkpoints, and restart within the authored discovery window does not re-probe already-checked relays. Audit loop executed with green targeted unit coverage for `tests/unit/test_system_websocket_harness.py tests/unit/test_system_fault_harness.py`, `3x` green reruns of `tests/system/services/monitor/test_service.py -q`, then a green band rerun of `tests/system/test_band_contract.py tests/system/services/monitor/test_service.py -q`; repository gates for closure are `make test-system`, `pre-commit --files ...`, `uv lock --check`, `make ci`, and `./.venv/bin/pytest tests/integration/ -q` |
| 4.5 `Synchronizer` | done | `test: certify synchronizer system contract` | Added `tests/system/services/synchronizer/` and certified the authored continuous service against a real relay stream: one live `nostr-rs-relay` now feeds archive ingestion through a deterministic host-side TLS boundary, while a second restart path keeps the relay stream behind real `Toxiproxy` fault injection to prove no cursor drift during blackout and honest recovery on the next restart without duplicate `event_observation` rows. The slice closed two real drifts before the contract went green. First, `src/bigbrotr/services/synchronizer/queries.py` built `SyncCursor(timestamp=None)` for relays without persisted cursor rows because the join mapper treated `NULL` columns as present values instead of falling back to sentinel defaults; that was fixed in production code and locked with a new unit test in `tests/unit/services/test_synchronizer.py`. Second, the TLS websocket harness readiness probe had become a raw TLS socket check that triggered noisy invalid-HTTP server errors, so `tests/system/harness/websocket.py` now uses an explicit `/ready` websocket path that bypasses mode-specific handlers and keeps startup deterministic without startup-log drift. The certified contract now proves stale-cursor cleanup, event/archive persistence, cursor advancement, restart/resume dedup, and blackout recovery with live DB assertions plus relay/proxy/container artifacts. Audit loop executed with green targeted unit coverage for `tests/unit/services/test_synchronizer.py tests/unit/test_system_websocket_harness.py`, `3x` green reruns of `tests/system/services/synchronizer/test_service.py -q`, then a green band rerun of `tests/system/test_band_contract.py tests/system/services/synchronizer/test_service.py -q`; repository gates for closure are `make test-system`, `pre-commit --files ...`, `uv lock --check`, `make ci`, and `./.venv/bin/pytest tests/integration/ -q` |
| 4.6 `Refresher` | done | `test: certify refresher system contract` | Added `tests/system/services/refresher/` and certified the authored continuous service on the composed `bigbrotr` stack with live PostgreSQL seeding through the real `Brotr` boundary. The first contract proves incremental plus periodic orchestration, refreshed `relay_document_current` and `pubkey_kind_stats` outputs, persisted checkpoint touch points, and stale-checkpoint cleanup against the shipped container/config wiring. The second contract proves restart/resume behavior with `max_source_window` enabled, showing that a partial first cycle persists a bounded checkpoint and that the next container restart resumes from that checkpoint without duplicate drift in the refreshed analytics rows. No product drift surfaced in the service itself; the audit loop instead exposed two test-boundary defects that were fixed before closure: the current-document snapshot compared a hex-encoded DB projection against the model's raw binary content hash, and the restart wait conditions compared tuple snapshots from the runtime DB helper against list literals, which could never converge. Audit loop executed with green targeted runtime probes for each contract, `3x` green reruns of `tests/system/services/refresher/test_service.py -q`, then a green band rerun of `tests/system/test_band_contract.py tests/system/services/refresher/test_service.py -q`; repository gates for closure are `make test-system`, `pre-commit --files ...`, `uv lock --check`, `make ci`, and `./.venv/bin/pytest tests/integration/ -q` |
| 4.7 `Ranker` | done | `12448c51` | Real rank exports, private DuckDB store ownership, restart incrementality, and `lilbrotr` profile store isolation are now certified on the composed stack |
| 4.8 `Assertor` | done | `db7526d2` | Real relay publication capture now proves provider-package event correctness, duplicate-skip restart behavior, and honest failure handling without partial checkpoint persistence |
| 4.9 `API` | done | `19dee93c` | The real HTTP boundary is now certified for health/read-model surfaces, payload correctness, pagination/filter/sort semantics, and restart continuity |
| 4.10 `DVM` | done | `bba5d1ca` | The real relay/event boundary is now certified for provider announcement, request handling, response-event correctness, cursor recovery, and `lilbrotr` read-model exposure over relay |

### Wave 5 — Cross-Service System Pipelines

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 5.1 Discovery pipeline | done | `b11bbf9f` | `Seeder` -> `Finder` -> `Validator` -> `Monitor` is now certified under the composed stack with controlled source ownership, live relay validation, and persisted relay-health state |
| 5.2 Archive pipeline | done | `2d8de41a` | Validated relays now flow into `Synchronizer` with live relay ingestion, honest `event` / `event_observation` persistence, cursor resume, and restart deduplication |
| 5.3 Derivation pipeline | done | `7e3bd73d` | `Refresher` -> `Ranker` -> `Assertor` is now certified with live derived outputs, private ranking store usage, and real publication capture instead of mocked publication semantics |
| 5.4 Public read pipeline | done | `bf4009a6` | Shared state now flows through the real `API` and `DVM` boundaries with live HTTP and relay request/response certification over the composed stack |
| 5.5 Restart and partial-completion pipeline | done | `3dadd5a7` | Interrupted composed flows are now certified for resume, idempotency, and honest failure semantics across restart and partial-completion boundaries |

### Wave 6 — Observability Certification

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 6.1 Emitted metrics schema contract | done | `e00c29e5` | Metric family names, labels, lifecycle behavior, and restart continuity are now certified across the live service metrics surface |
| 6.2 Deployment metrics wiring contract | done | `acae1079` | The live deployment config now certifies intended metrics enablement/exposure, including the corrected `assertor` metrics port wiring and host reachability |
| 6.3 `bigbrotr` Prometheus scrape contract | done | `594fa6a9` | `bigbrotr` now proves target health, target correctness, and required `up` / `service_info` / exporter series via the live Prometheus API |
| 6.4 `lilbrotr` Prometheus scrape contract | done | `bfba0f0f` | The lightweight profile now carries the same Prometheus scrape proof with the intended profile-specific target addresses only |
| 6.5 `bigbrotr` alert-rule contract | done | `79ba9b18` | `ServiceDown` and related positive/negative alert semantics are now certified on the live `bigbrotr` monitoring stack |
| 6.6 `lilbrotr` alert-rule contract | done | `ccc9130b` | The lightweight profile now proves the same alert semantics plus parity of monitoring behavior across the two built-in deployments |
| 6.7 Grafana datasource provisioning contract | done | `c6b37f4c` | Datasource presence, UID stability, connectivity, and provisioning correctness are now certified via the live Grafana API |
| 6.8 Alertmanager routing contract | done | `d7949eb3` | Routing config load, alert receipt, and documented routing semantics are now certified against the live Alertmanager boundary |
| 6.9 Dashboard provisioning integrity contract | done | `bb08f43a` | Dashboard load, UID stability, expected inventory, and provisioning completeness are now certified for both profiles |
| 6.10 Dashboard query semantics contract | done | `fc8053bc` | Panel queries are now proven against live metrics and current label sets, with no stale metric-name or label-shape assumptions left |
| 6.11 Postgres-exporter contract | done | `21fadc63` | Exporter startup, custom query correctness, live sample payloads, and schema/query parity are now certified against the running stack |
| 6.12 Operator-document parity contract | done | `0627dcf7` | Monitoring/operator docs now align with the certified live stack instead of historical or provisioning-only assumptions |

### Wave 7 — Failure, Recovery, And Resilience

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 7.1 Relay-network failures | done | `9425c766` | Latency, disconnect, reset, timeout, degraded-subset, and recovery behavior are now certified under real relay-network fault injection |
| 7.2 Database and pool failures | done | `2aa4a116` | Startup failure, transient DB/pool loss, rollback honesty, and service recovery are now certified against the live data path |
| 7.3 Observability-stack failures | done | `df910274` | Prometheus, Grafana, Alertmanager, and postgres-exporter degradation semantics are now certified with recovery drills on the live monitoring stack |
| 7.4 Service restart and mid-flight interruption | done | `4d8aab13` | Repeated restarts and interrupted work recovery are now certified on real service boundaries, including `Assertor` partial publish state |
| 7.5 Flake and concurrency hardening | done | `1984c2e5` | Repeated high-risk coexistence reruns are now stable, teardown is auditable, and unexplained concurrency drift has been driven out of the band |

### Wave 8 — Profile Parity And Deployment Hardening

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 8.1 `bigbrotr` vs `lilbrotr` service/runtime parity | done | `a139d6ca` | Shared service/runtime contracts now differ only on intentional profile boundaries; the closeout also absorbed companion recovery fix `5cbe5868` for synchronizer behavior after failed relay cycles |
| 8.2 Monitoring parity | done | `17c194a1` | Datasources, dashboards, alerts, exporter semantics, and live monitoring behavior are now certified as profile-parity surfaces with only intentional profile tokens differing |
| 8.3 SQL and deployment asset parity | done | `9a88a1cb` | Generated SQL, shipped deployment SQL/init assets, and the certified runtime schema now remain aligned across both built-in profiles |
| 8.4 Operator-experience audit | done | `d194c275` | Final operator-facing coherence review now proves README links, host-port surfaces, and asset inventory match the real shipped deployment stack |

### Wave 9 — Final Audit, Cutover, And Closeout

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 9.1 Structural audit | done | `b4af3e60` | The final higher-band topology is now locked and every surviving leaf package/helper surface must justify its place against the structural audit contract |
| 9.2 Remove obsolete or weak surfaces | done | `a9b7bbe6` | Weak higher-band band-contract placeholders were removed, relay cleanup was hardened, and the remaining topology now reflects only justified live surfaces |
| 9.3 Full repeated matrix audit | done | `12041346` | A no-change repeated rerun is now green end-to-end: observability/profile bands no longer depend on unnecessary rebuilds during audit, teardown now still runs when artifact capture fails, transient unlabeled `service_info` rows no longer explode readiness polling, and TLS websocket readiness treats `InvalidMessage` as transient startup noise; closing reruns are `make test-system` (`95 passed in 4588.29s`), `make ci` (`5410 passed in 25.41s`), and `./.venv/bin/pytest tests/integration/ -q` (`293 passed in 32.69s`) |
| 9.4 Final closeout | done | `docs: close system test certification ledger` | The ledger is now aligned with the real branch state, no wave remains open, the final tracked higher-band surface is `136` files under `tests/system/` plus `2` under `tests/live_smoke/`, and no negative audit note remains open |

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
