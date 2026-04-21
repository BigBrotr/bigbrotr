# System Test And Observability Target Taxonomy

## Purpose

This file freezes the intended final tree for the broader system-test and
observability certification band.

The repository currently has:

- `tests/integration/` for the rebuilt integration layer;
- `deployments/*/` for operator/runtime assets;
- and no committed `tests/system/` or `tests/live_smoke/` tree yet.

That is acceptable at the freeze point.
It is not acceptable as the long-term execution shape of the higher-band
certification work.

The taxonomy below is therefore the target structure the system/observability
program should converge to.

It exists so execution stays auditable instead of drifting into:

- ad hoc compose helpers in unrelated test modules;
- relay assets hidden inside deployment folders;
- observability assertions mixed into service smoke files;
- or live-network probes accidentally promoted into the main gate.

---

## Frozen Context

- Taxonomy freeze date:
  `2026-04-21`
- Frozen branch:
  `refactor/definitive-redesign-execution`
- Frozen baseline commit:
  `5bf3b112`

---

## Target Top-Level Tree

```text
tests/system/
  harness/
    artifacts/
    compose/
    fixtures/
    observability/
    relay/
    runtime/
  assets/
    compose/
      base/
      bigbrotr/
      lilbrotr/
      relay/
      observability/
    relay/
      configs/
      seeds/
  deployments/
    bigbrotr/
    lilbrotr/
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
  observability/
    metrics/
    prometheus/
    alertmanager/
    grafana/
    postgres_exporter/
    docs/
  resilience/
    relay/
    database/
    observability/
    runtime/
  README.md

tests/live_smoke/
  harness/
  relay/
  api/
  dvm/
  README.md
```

This is the target execution shape.
It does not require every directory to appear immediately.

It does require that every new higher-band slice move the repository closer to
this tree rather than inventing a parallel layout.

---

## Area Intent

### `tests/system/harness/`

Owns reusable support for the deterministic higher band:

- compose lifecycle helpers;
- project-name and port discipline;
- artifact capture;
- runtime polling and teardown checks;
- observability API helpers;
- relay control helpers;
- and deployment-aware fixture builders.

`harness/` owns support code only.
It must not become a hiding place for domain assertions.

### `tests/system/assets/`

Owns committed static assets required by the higher-band suite:

- compose overlays and override fragments;
- relay configs or seed payloads;
- and observability-side test assets that belong to the test stack rather than
  the shipped deployments.

These assets are test-owned.
They must not be mixed into `deployments/*/` unless the asset is truly part of
  the shipped operator contract.

### `tests/system/deployments/`

Owns stack-baseline certification by profile:

- clean startup;
- clean teardown;
- health checks;
- dependency ordering;
- port wiring;
- and repeated restart proof.

This area proves the stack as deployed, not one service in isolation.

### `tests/system/services/`

Owns service-specific runtime certification.

Each service gets its own subtree because the runtime boundary must remain
legible:

- `seeder/`
- `finder/`
- `validator/`
- `monitor/`
- `synchronizer/`
- `refresher/`
- `ranker/`
- `assertor/`
- `api/`
- `dvm/`

Each service subtree should converge on small contract files such as:

- `test_runtime.py`
- `test_happy_path.py`
- `test_failures.py`
- `test_restart.py`

Not every service needs every filename immediately.
The rule is contract clarity, not symmetry for its own sake.

### `tests/system/pipelines/`

Owns multi-service composition proof:

- discovery flow;
- archive flow;
- derivation/publication flow;
- public read-surface flow;
- and interrupted/restart flow.

Pipeline files should prove composition only.
They should not duplicate the detailed contract of a service-specific file.

### `tests/system/observability/`

Owns runtime certification of the operator stack:

- emitted metrics behavior;
- Prometheus scrape correctness;
- alert semantics;
- Alertmanager routing semantics;
- Grafana provisioning and query integrity;
- postgres-exporter correctness;
- and final operator-doc parity.

No observability contract should be hidden inside an arbitrary service smoke
test once this subtree exists.

### `tests/system/resilience/`

Owns failures that cut across services or the whole stack:

- relay-network degradation;
- database or pool failures;
- observability-stack degradation;
- runtime interruption and repeated restart;
- and flake-sensitive concurrency drills.

### `tests/live_smoke/`

Owns rare, quarantined, non-blocking proof against real public-network
dependencies.

This tree exists so:

- public relay experiments stay explicit;
- the branch gate remains deterministic;
- and live-network uncertainty never contaminates the main system band.

`tests/live_smoke/` is allowed to be very small.
Its role is quarantine, not bulk coverage.

---

## Asset Placement Rules

### 1. Compose overlays live under `tests/system/assets/compose/`

The system band should not edit the shipped deployment compose files just to
make the tests runnable.

Instead, test-owned overlay fragments should live under:

- `tests/system/assets/compose/base/`
- `tests/system/assets/compose/bigbrotr/`
- `tests/system/assets/compose/lilbrotr/`
- `tests/system/assets/compose/relay/`
- `tests/system/assets/compose/observability/`

These overlays may:

- redirect ports;
- add relay containers;
- inject temporary volumes;
- or add test-only helper containers.

They must not silently redefine the operator contract of the real deployments.

### 2. Relay support assets live under `tests/system/assets/relay/`

Relay-specific support such as:

- config files;
- static fixtures;
- captured-event schema samples;
- or deterministic seed events

belongs under:

- `tests/system/assets/relay/configs/`
- `tests/system/assets/relay/seeds/`

Relay assets should not be buried inside service folders.

### 3. Runtime artifacts are never tracked

Captured logs, snapshots, relay captures, and observability dumps are runtime
artifacts.

They should be written to temporary directories managed by the harness, not
committed into the repository tree.

### 4. Test-owned observability assets stay test-owned

If the higher-band suite needs:

- synthetic alert targets;
- test dashboards;
- or helper scrape configs

they belong under `tests/system/assets/compose/observability/` or another
clearly test-owned subtree, not inside the shipped deployment monitoring tree.

---

## Naming Rules

### 1. Files must name the runtime contract

Prefer:

- `test_compose_startup.py`
- `test_relay_disconnect_recovery.py`
- `test_dashboard_query_integrity.py`
- `test_publication_capture.py`

Avoid:

- `test_misc.py`
- `test_stack_more.py`
- `test_e2e_2.py`

### 2. One file, one contract band

Service runtime, observability, deployment baseline, and live-smoke concerns
should stay in their own directories and files.

If a file would need a paragraph to explain why it mixes unrelated contracts,
the file is scoped badly.

### 3. Support helpers must read like components

Prefer helper names such as:

- `ComposeStack`
- `RelayCaptureClient`
- `PrometheusApi`
- `GrafanaApi`
- `AlertmanagerApi`
- `RuntimeArtifactBundle`

Avoid anonymous helpers that conceal their runtime role.

### 4. Overlay fragments should name the contract they alter

Prefer filenames such as:

- `docker-compose.relay-capture.yaml`
- `docker-compose.monitoring-audit.yaml`
- `docker-compose.bigbrotr-test.yaml`

over generic names that hide the purpose of the override.

---

## Migration Rules

### 1. New higher-band work goes into the target taxonomy

No new deployment-fidelity or observability certification should be added to:

- `tests/integration/`
- `deployments/*/monitoring/`

unless the slice is explicitly migrating legacy proof or fixing a shipped
operator asset.

### 2. `tests/integration/` remains the lower band

The new system band must complement `tests/integration/`, not erase the
distinction between:

- real shared-schema/component contracts;
- and full composed runtime proof.

### 3. Live-smoke never becomes the gate by accident

Any test that touches public relays or uncontrolled public hosts must live
under `tests/live_smoke/` and remain non-blocking by policy.

### 4. Local guidance appears as subtrees become nontrivial

When a new subtree gains multiple helpers or contracts, it should gain a local
`README.md` explaining:

- what belongs there;
- what does not belong there;
- and what other subtree it depends on.

---

## Audit Questions For Taxonomy Compliance

Before closing any higher-band slice, ask:

1. Did the new file land in the correct subtree for its contract band?
2. Is any support code hiding inside a domain assertion file?
3. Did a test-owned asset accidentally land inside `deployments/*/`?
4. Did any public-network proof stay quarantined under `tests/live_smoke/`?
5. Does the new name describe the real runtime contract?
6. Did the slice move the repository closer to the frozen target tree?

If any answer is `no`, the slice is not taxonomy-clean yet.
