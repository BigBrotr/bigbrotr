# System Test And Observability Certification Program

## Purpose

The integration rebuild program is necessary, but not sufficient, to certify the
BigBrotr product professionally.

The repository still needs a broader and stricter test program that proves:

- deployment-fidelity service execution under Docker Compose;
- real relay-facing protocol behavior where the network boundary is the
  contract;
- public adapter behavior for `API` and `DVM` at their true runtime boundaries;
- restart, recovery, and partial-failure behavior across the composed system;
- and the full observability chain from emitted metrics to Prometheus, alert
  rules, Grafana provisioning, and operator-facing dashboards.

This program defines that broader test architecture.

It complements, but does not replace:

- [28_integration_test_rebuild_program.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/28_integration_test_rebuild_program.md)
- [29_integration_test_rebuild_ledger.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/29_integration_test_rebuild_ledger.md)
- [31_integration_test_rebuild_contract_matrix.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/31_integration_test_rebuild_contract_matrix.md)
- [32_integration_test_rebuild_taxonomy.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/32_integration_test_rebuild_taxonomy.md)

The integration rebuild remains the professional source of truth for:

- shared PostgreSQL contracts;
- lower-band service integration contracts;
- deterministic harness support;
- and bounded doubles where a higher-band test would become impractical.

This program adds the next band:

- full system execution;
- deployment-shape fidelity;
- relay realism;
- operator-surface certification;
- and observability correctness.

---

## Why A Separate Program Is Justified

The current repository already has:

- a live deployment shape under `deployments/bigbrotr/` and
  `deployments/lilbrotr/`;
- a real metrics subsystem in `src/bigbrotr/core/metrics.py`;
- Prometheus, Grafana, Alertmanager, and postgres-exporter configuration under
  `deployments/*/monitoring/`;
- and partial service/integration proof in `tests/integration/`.

But none of those facts by themselves prove that:

- the full stack starts cleanly and remains internally coherent;
- the services behave honestly when composed instead of invoked in isolation;
- the relay-facing services work against a real relay server rather than only
  against doubles;
- Prometheus truly scrapes the right targets and surfaces the right series;
- alert rules still match the emitted metrics and fire for the right reasons;
- Grafana provisioning is intact and its dashboards query valid metrics;
- or `bigbrotr` and `lilbrotr` preserve intended parity and intended
  differences across the operator-facing stack.

That is a different contract band from the integration rebuild.

It deserves its own:

- program;
- ledger;
- taxonomy;
- audit loop;
- and commit discipline.

---

## Scope

This program covers all test work needed to certify BigBrotr above the current
integration layer, specifically:

### 1. System-runtime certification

- service startup and shutdown under Docker Compose;
- health checks and dependency ordering;
- persisted side effects across the real deployment stack;
- restart, resume, and recovery behavior;
- and cross-service composition at the actual runtime boundary.

### 2. Real relay certification

- relay-facing behavior for `Validator`, `Monitor`, `Synchronizer`, `Assertor`,
  and `DVM`;
- real event flow through WebSocket relay servers;
- publish, read, subscribe, reconnect, and disconnect behavior;
- and relay failure injection through explicit network control.

### 3. Public-surface certification

- HTTP behavior of `API`;
- event/job behavior of `DVM`;
- pagination, filtering, error mapping, and payload correctness;
- and end-to-end read-surface correctness from shared DB state to exposed
  public result.

### 4. Observability certification

- emitted metrics contract;
- Prometheus scrape correctness;
- alert rule correctness;
- Grafana datasource provisioning;
- Grafana dashboard provisioning and query integrity;
- postgres-exporter correctness;
- and operator-facing deployment documentation parity with the live system.

### 5. Deployment/profile certification

- `bigbrotr` baseline deployment contract;
- `lilbrotr` profile contract;
- shared-vs-profile-specific monitoring behavior;
- generated-SQL vs deployed-SQL parity where it affects the certified test
  stack;
- and final operator confidence that the shipped deployments are not only
  runnable, but auditable.

---

## Non-Negotiable Principles

### 1. Test bands must stay explicit

The repository should not pretend that every serious test is “just another
integration test”.

The target test bands are:

- `tests/integration/` for the integration rebuild band;
- `tests/system/` for deployment-fidelity and composed-runtime testing;
- `tests/live_smoke/` for rare, quarantined, non-blocking public-network proof
  when a truly public dependency cannot be avoided.

If a test band has a different runtime cost, determinism profile, external
dependency model, or operator value, it should not be hidden inside a generic
folder.

### 2. Real boundaries where the product contract is external

The following boundaries should be real in the `tests/system/` band unless a
documented blocker proves otherwise:

- PostgreSQL;
- PgBouncer;
- service containers or service processes;
- real HTTP exposure for `API`;
- real WebSocket relay servers for relay-facing services;
- Prometheus;
- Grafana;
- Alertmanager;
- postgres-exporter;
- Docker health checks;
- and deployment-level config mounts and environment wiring.

### 3. Doubles are allowed only where realism would be dishonest or unstable

Acceptable uses of doubles in higher-band tests are narrow:

- deterministic fixture sources for seeded HTTP/API payloads;
- explicit fault-control seams when the real dependency cannot be manipulated
  deterministically;
- time-sequencing helpers;
- and artifact capture utilities.

Unacceptable uses of doubles in the `tests/system/` band include:

- faking a relay while claiming to certify relay behavior;
- bypassing Prometheus while claiming to certify scrape or alert behavior;
- bypassing Grafana provisioning while claiming to certify dashboards;
- bypassing the actual HTTP boundary while claiming to certify `API`;
- or bypassing the actual Nostr event boundary while claiming to certify `DVM`
  or `Assertor` publication behavior.

### 4. No screenshot or pixel-certification as a primary gate

Prometheus and Grafana should be certified by:

- emitted series;
- scrape targets;
- rule evaluation;
- datasource provisioning;
- dashboard provisioning;
- panel query integrity;
- and end-to-end operator semantics.

Pixel or screenshot testing is not a primary certification tool here.

It is only acceptable if a later slice proves that a specific rendered panel has
genuine contract value that cannot be expressed through API-level assertions.

That should be rare, exceptional, and explicitly justified.

### 5. Public relays must not be part of the merge gate

The main gating stack must remain deterministic and CI-safe.

Public relays may be touched only in:

- a quarantined `tests/live_smoke/` band;
- scheduled or manual runs;
- clearly documented host lists;
- and explicitly non-blocking job configuration.

No branch gate should rely on public relay uptime, public relay policy, or the
uncontrolled behavior of the open network.

### 6. Observability is part of the product contract

The monitoring stack is not decorative.

Prometheus rules, Grafana dashboards, and exporter queries should be treated as
runtime product surfaces.

They deserve the same seriousness as:

- service logic;
- deployment wiring;
- and adapter correctness.

### 7. Every subsection closes only after a clean audit

A subsection is not complete because:

- code exists;
- tests were written;
- or one green run happened.

A subsection is complete only if:

- its contract is explicit;
- the real boundaries are named;
- its negative space is explicit;
- targeted tests are green;
- repeat reruns remain green;
- band-level reruns remain green;
- repo-level gates remain green;
- no negative audit note survives;
- the ledger records the closure honestly;
- and the closure lands in its own commit.

### 8. Drift found by tests must be fixed, not normalized away

If this program exposes:

- runtime drift;
- deployment drift;
- relay drift;
- metrics drift;
- alert drift;
- dashboard drift;
- or operator-doc drift;

the answer is to:

- tighten the contract;
- fix the product or deployment surface;
- rerun the audit loop;
- and close honestly.

It is not to:

- soften the test silently;
- weaken the meaning of the surface;
- or demote a real system contract into a mock-only proof.

---

## Relationship To The Integration Rebuild

The integration rebuild remains the lower-band dependency for this program.

Execution should proceed with these rules:

### 1. Do not duplicate lower-band proof unnecessarily

If `tests/integration/` already proves:

- a shared DB contract;
- a direct service-storage contract;
- or a deterministic failure seam;

`tests/system/` should consume that fact and prove the next boundary upward,
not rewrite the same proof at the wrong level.

### 2. Do not skip the higher band because the lower band is green

If `tests/integration/` is green for:

- `Assertor`;
- `Synchronizer`;
- `API`;
- or `DVM`;

that still does not certify:

- relay interoperability;
- compose wiring;
- public endpoint behavior;
- or monitoring stack correctness.

### 3. Use the integration harness as the staging ground

Where possible, support utilities should be shared or mirrored intentionally:

- deterministic IDs and timestamps;
- named fault controls;
- deployment bootstrap helpers;
- and DB reset or artifact-capture seams.

But the higher band must not collapse back into lower-band fakes just because
the lower-band harness exists.

### 4. Service system closure depends on the lower band being honest first

A service-level `tests/system/` subsection should not close before the
corresponding lower-band contract is already honest in `tests/integration/` or
explicitly absorbed into the same closing slice.

That rule exists so the higher band does not become a dumping ground for:

- lower-band contract holes;
- harness shortcuts;
- or unexplained failures that should have been resolved one layer down first.

---

## Target Test Architecture

## Top-Level Tree

```text
tests/
  integration/
    ...
  system/
    harness/
      compose/
      relays/
      artifacts/
      observability/
      failures/
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
      public_read/
      restart/
    observability/
      metrics/
      prometheus/
      alerts/
      grafana/
      postgres_exporter/
    profiles/
      bigbrotr/
      lilbrotr/
    failures/
    README.md
  live_smoke/
    README.md
```

This is the target architecture for the new higher-band tests.

The important constraint is not exact folder count.
It is intentional separation of concerns:

- harness support;
- service-runtime contracts;
- multi-service pipelines;
- observability surfaces;
- profile parity;
- and public-network smoke proof.

## Area Intent

### `tests/system/harness/`

Owns reusable higher-band support:

- compose lifecycle;
- container readiness and teardown;
- relay bootstrapping;
- artifact collection;
- Prometheus and Grafana API helpers;
- and network fault control.

### `tests/system/services/`

Owns per-service system-runtime contracts:

- real config;
- real startup;
- real outputs;
- real failures;
- and real restart/resume behavior.

### `tests/system/pipelines/`

Owns multi-service flow proof:

- discovery;
- archive;
- derivation/publication;
- read-surface composition;
- and restart/idempotency across composed services.

### `tests/system/observability/`

Owns the operator-surface contracts:

- emitted metrics;
- scrape integrity;
- alert semantics;
- Grafana provisioning;
- Grafana query integrity;
- postgres-exporter correctness.

### `tests/system/profiles/`

Owns explicit deployment/profile differences:

- `bigbrotr`;
- `lilbrotr`;
- and any retained internal fixture profile if it survives later audit.

### `tests/live_smoke/`

Owns rare and quarantined public-network proof.

These tests are:

- non-blocking;
- sparse;
- manually or scheduled triggered;
- and never confused with the deterministic merge gate.

---

## Real Relay Strategy

The relay-facing services need a real relay plan, not vague “network-ish”
testing.

The system test program should converge on four relay roles:

### 1. Baseline relay

One simple, container-friendly relay implementation selected as the default
system-test relay.

Selection criteria:

- easy Docker lifecycle;
- stable local operation;
- clear startup and readiness behavior;
- basic Nostr protocol support sufficient for BigBrotr flows;
- and reasonable artifact inspectability.

Recommended first candidate:

- `nostr-rs-relay`

because it already presents itself as a Docker-runnable relay server with a
simple local container story.

### 2. Capture relay

A relay dedicated to recording exactly what `Assertor` and `DVM` publish.

Its job is not merely to accept events.
It must support audit of:

- event ids;
- kinds;
- authors;
- tags;
- content;
- replaceable/addressable behavior where relevant;
- duplicates;
- and publication timing or ordering constraints where relevant.

### 3. Fault-injected relay path

A relay reachable only through a controllable network proxy so the suite can
apply deterministic failures:

- latency;
- disconnects;
- resets;
- bandwidth reduction;
- timeout-like stalls;
- and partial availability.

Recommended first fault-control mechanism:

- `Toxiproxy`

because it provides deterministic TCP-level failure shaping suitable for CI and
test environments.

### 4. Secondary relay matrix candidate

After the baseline relay path is green, a second relay implementation may be
added to reduce implementation-specific blind spots.

Recommended first secondary candidate:

- `strfry`

because it is a real standalone relay with a different storage and runtime
shape from the baseline candidate.

This secondary matrix should not block the first executable slices.
It is a hardening layer, not the first dependency.

### 5. What should not be the primary relay strategy

The program should not use an SDK client library as the main relay under test.

For example:

- `nostr-sdk`

may be useful as a client-side or helper dependency, but it is not the right
primary system-test relay strategy for certifying production-like relay
behavior.

---

## Observability Certification Strategy

Observability certification must be treated as a first-class workstream rather
than as a handful of smoke checks.

The required bands are:

### 1. Emitted metrics contract

For each service:

- `/metrics` endpoint behavior;
- required metric families;
- required label sets;
- monotonic counter behavior;
- gauge reset and update behavior;
- histogram presence and bucket semantics where required;
- and correctness under success, failure, retry, and restart.

### 2. Docker health-check contract

For each deployment:

- service health checks match the real metrics endpoint;
- unhealthy behavior is honest when the endpoint is unavailable;
- and startup ordering does not rely on fake or PID-only checks.

### 3. Prometheus scrape contract

For each profile:

- all intended targets are configured;
- all configured targets become `UP`;
- scrape labels and job names remain coherent;
- required series appear after workload execution;
- and no configured target points at the wrong port, wrong path, or wrong
  container.

### 4. Alert rule contract

For each profile:

- rules load successfully;
- rules reference real metric names;
- rules do not depend on stale labels;
- positive drill: expected alert fires under induced failure;
- negative drill: alert does not fire under healthy behavior;
- and alert descriptions match the real system meaning.

### 5. Grafana provisioning contract

For each profile:

- Grafana starts successfully;
- the Prometheus datasource is provisioned;
- dashboard provisioning succeeds;
- dashboard UIDs remain stable and unique;
- no dashboard references a missing datasource UID;
- and no dashboard file is present but ignored due to provisioning drift.

### 6. Alertmanager routing contract

For each profile:

- Alertmanager starts successfully;
- routing config loads cleanly;
- the alert pipeline accepts the intended alerts from Prometheus;
- and the deployment’s documented notification semantics match the live config.

### 7. Grafana query integrity contract

For each dashboard:

- every panel query resolves against the live Prometheus datasource;
- no panel references missing metric families;
- no panel depends on labels that the application no longer emits;
- and dashboard meaning matches the current deployment/runtime surface.

### 8. Postgres-exporter contract

For each profile:

- exporter boots with the intended query set;
- custom query results appear in Prometheus;
- custom queries still match the real schema;
- and deployment-level DB metrics remain aligned with the current tables and
  functions.

### 9. Operator-document parity contract

Monitoring docs must not describe a stack different from the one actually
certified.

Documentation should be audited against:

- compose files;
- metrics endpoints;
- Prometheus config;
- alert rules;
- dashboard provisioning;
- and profile differences.

---

## Definition Of Done

This program is complete only when all of the following are true:

- `tests/system/` exists with an intentional, documented taxonomy;
- the higher-band harness is stable and repeatable;
- relay-facing services have real relay proof, not only doubled proof;
- `API` and `DVM` have real runtime-boundary certification;
- cross-service pipelines are proven under the composed deployment stack;
- `bigbrotr` and `lilbrotr` both have explicit system/profile certification;
- Prometheus, Alertmanager, Grafana, and postgres-exporter are certified as
  real runtime surfaces;
- no primary certification depends on screenshot or pixel tests;
- no merge gate depends on public relays;
- repeated full-matrix reruns remain green;
- and the final audit leaves no structural or operator-facing weakness
  unresolved.

---

## Section Audit Loop

Every subsection in this program must close using the same severe loop.

### Required closure checklist

1. Write the exact contract being proved.
2. Name the real boundaries being exercised.
3. Name the allowed doubles, if any, and justify them.
4. Implement or adjust the test and any required production/deployment fixes.
5. Run targeted tests for the subsection.
6. Run a focused failure or restart drill if the subsection claims failure or
   recovery coverage.
7. Rerun the targeted subsection repeatedly until the run is stable.
   Minimum expectation:
   `3x` for the local subsection unless a stricter band-specific rule is
   declared.
8. Run the enclosing band suite.
9. Run repository gates.
10. Record the real drift found and the exact fixes applied.
11. Update the ledger.
12. Commit the subsection closure alone.

### No-negative-note rule

If the audit leaves any negative note such as:

- flaky once but “probably fine”;
- alert semantics look suspicious;
- dashboard query seems stale;
- relay timing looked odd but was not explained;
- Prometheus target was intermittently down;
- or docs still appear slightly inaccurate;

the subsection is not closed.

It stays open until:

- the issue is explained and fixed;
- or it is escalated honestly as a blocker.

### Required gate stack for subsection closure

At minimum, a closing subsection should run:

- targeted subsection tests;
- enclosing-band tests;
- `make ci`;
- `uv lock --check`;
- and any band-specific deployment validation needed by the subsection.

If a run is teardown-opaque, the final gate should be rerun in PTY or another
observable form before closure.

---

## Execution Waves

### Wave 0 — Freeze The Expanded Test Problem

#### 0.1 Freeze current non-unit test inventory

Capture the current tracked surfaces for:

- `tests/integration/`;
- deployment monitoring assets;
- compose files;
- operator-facing monitoring docs;
- and any existing metrics-specific unit tests.

#### 0.2 Freeze live deployment and monitoring inventory

Record the current:

- service containers;
- metrics ports;
- monitoring containers;
- datasource files;
- dashboard files;
- alert files;
- exporter query files;
- and profile-specific differences.

#### 0.3 Freeze current-vs-required coverage matrix

Produce an auditable matrix that says, for each service and operator surface:

- what is currently proven;
- what still lacks proof;
- what boundary must be real;
- what doubles remain acceptable;
- and what band owns the proof.

#### 0.4 Freeze target taxonomy

Freeze the intended final layout for:

- `tests/system/`;
- `tests/live_smoke/`;
- compose overlays;
- relay support assets;
- and observability helpers.

#### 0.5 Bootstrap execution ledger

Create the operational ledger that every closing subsection must update.

### Wave 1 — Higher-Band Harness Foundation

#### 1.1 Compose lifecycle harness

Build reusable helpers for:

- compose up/down;
- isolated project naming;
- deterministic env file generation;
- log capture;
- readiness polling;
- and final cleanup.

#### 1.2 Artifact capture harness

Capture:

- container logs;
- Prometheus target snapshots;
- Grafana health and provisioning responses;
- relay-published event captures;
- and DB-side final snapshots where needed.

#### 1.3 Stable runtime addressing

Standardize:

- internal service names;
- exposed host ports where needed;
- temporary volumes;
- and collision-free parallel-run behavior.

#### 1.4 Network fault-control harness

Integrate deterministic failure shaping for:

- relay traffic;
- optionally service-to-service traffic where justified;
- and partial outage drills.

#### 1.5 Observability API harness

Add helpers for:

- Prometheus HTTP API queries;
- target inspection;
- alert inspection;
- Grafana health checks;
- datasource inspection;
- dashboard inventory inspection;
- and panel-query validation.

#### 1.6 Harness self-audit

Prove that the higher-band harness itself is:

- deterministic;
- leak-free on teardown;
- artifact-producing;
- and stable across repeated reruns.

### Wave 2 — Real Relay Infrastructure

#### 2.1 Baseline relay selection and contract

Choose the first relay implementation and prove:

- startup;
- readiness;
- local publish;
- local subscribe;
- local query;
- and inspectability.

#### 2.2 Capture relay

Provide a relay path that supports exact publication audit for:

- `Assertor`;
- `DVM`;
- and any future publication surface.

#### 2.3 Fault-injected relay path

Wire one relay through the failure-control layer and prove:

- latency injection;
- disconnect;
- reset;
- timeout-like stalling;
- and recovery.

#### 2.4 Secondary relay matrix

Introduce a second relay implementation only after the baseline path is green,
then prove that the system does not accidentally rely on one relay server’s
quirks.

#### 2.5 Relay harness self-audit

Repeat the relay-specific harness drills until:

- repeated publish/read cycles stay deterministic;
- artifacts are inspectable;
- and no relay-role drift remains.

### Wave 3 — Deployment Stack Baseline

#### 3.1 `bigbrotr` stack baseline

Prove the baseline deployment can start with:

- DB;
- PgBouncer;
- target services;
- monitoring stack;
- and correct readiness sequencing.

#### 3.2 `lilbrotr` stack baseline

Repeat the same baseline certification for `lilbrotr`.

#### 3.3 Health-check and dependency ordering audit

Prove that health and dependency edges are:

- real;
- sufficient;
- and not accidentally masking broken service surfaces.

#### 3.4 Teardown and restart baseline

Prove that the stack:

- tears down cleanly;
- can restart cleanly;
- and does not leave hidden state drift in its test harness.

### Wave 4 — Service System Certification

#### 4.1 `Seeder`

Prove:

- real seed ingestion;
- persistence consequences;
- duplicate behavior;
- invalid-source behavior;
- and startup/once-run exit semantics.

#### 4.2 `Finder`

Prove:

- real source fetch path through a controlled HTTP fixture service;
- cooldown handling;
- deduplication;
- persistence outcomes;
- and restart behavior.

#### 4.3 `Validator`

Prove:

- real relay validation against the baseline relay;
- invalid relay rejection;
- retry and backoff behavior where exposed;
- persistence consequences;
- and failure isolation.

#### 4.4 `Monitor`

Prove:

- real probe paths;
- stored NIP-11/NIP-66 effects;
- timeout and degraded-relay behavior;
- checkpoint/state effects;
- and restart semantics.

#### 4.5 `Synchronizer`

Prove:

- real archive ingestion from a relay;
- checkpoint advancement;
- deduplication;
- restart/resume;
- retention interaction;
- and failure or disconnect recovery.

#### 4.6 `Refresher`

Prove:

- real runtime orchestration under the composed stack;
- service-state touch points;
- stale-state recovery;
- refresh outputs;
- and restart behavior.

#### 4.7 `Ranker`

Prove:

- real score computation over live refreshed data;
- private store outputs;
- restart semantics;
- profile differences;
- and failure handling for storage or input drift.

#### 4.8 `Assertor`

Prove:

- score hydration;
- real event publication to the capture relay;
- event correctness;
- duplicate or idempotent behavior;
- publish failure handling;
- and restart behavior.

#### 4.9 `API`

Prove through real HTTP requests:

- startup and routing;
- response payload correctness;
- pagination/filter/sort behavior;
- error mapping;
- and profile-aware read-surface behavior.

#### 4.10 `DVM`

Prove through real relay/event behavior:

- request intake;
- response event creation;
- failure mapping;
- resource exposure policy;
- and reconnect behavior.

### Wave 5 — Cross-Service System Pipelines

#### 5.1 Discovery pipeline

Prove:

- `Seeder` -> `Finder` -> `Validator` -> `Monitor`

at the composed system boundary.

#### 5.2 Archive pipeline

Prove:

- validated relays feed `Synchronizer`;
- events persist correctly;
- and restart/resume semantics remain honest.

#### 5.3 Derivation pipeline

Prove:

- `Refresher` -> `Ranker` -> `Assertor`

with real publication capture and restart/idempotency checks.

#### 5.4 Public read pipeline

Prove:

- refreshed and ranked state reaches `API` and `DVM`

through their actual runtime boundaries.

#### 5.5 Restart and partial-completion pipeline

Prove that interrupted multi-service flows can:

- resume;
- remain idempotent where required;
- and fail honestly where idempotency does not apply.

### Wave 6 — Observability Certification

#### 6.1 Emitted metrics schema contract

Audit the service-emitted metrics against:

- metric names;
- label names;
- label cardinality;
- documented semantics;
- and service lifecycle behavior.

#### 6.2 Deployment metrics wiring contract

Audit that deployment config actually enables and exposes the intended metrics
endpoints and ports.

#### 6.3 `bigbrotr` Prometheus scrape contract

Certify target list, target health, series presence, and target semantics for
`bigbrotr`.

#### 6.4 `lilbrotr` Prometheus scrape contract

Repeat the same certification for `lilbrotr`.

#### 6.5 `bigbrotr` alert-rule contract

Certify positive and negative alert semantics for `bigbrotr`.

#### 6.6 `lilbrotr` alert-rule contract

Repeat the same for `lilbrotr`.

#### 6.7 Grafana datasource provisioning contract

Certify datasource presence, UID stability, and connectivity for both profiles.

#### 6.8 Alertmanager routing contract

Certify routing config load, alert acceptance, and honest documented semantics
for both profiles.

#### 6.9 Dashboard provisioning integrity contract

Certify that all intended dashboards are loaded and none drift silently out of
provisioning.

#### 6.10 Dashboard query semantics contract

Certify that the dashboards query live, correct metrics and do not depend on
stale labels or removed series.

#### 6.11 Postgres-exporter contract

Certify exporter startup, custom query correctness, and schema alignment for
both profiles.

#### 6.12 Operator-document parity contract

Re-read the operator-facing monitoring docs against the certified stack and
close only when the prose is honest.

### Wave 7 — Failure, Recovery, And Resilience

#### 7.1 Relay-network failures

Latency, disconnect, reset, timeout, degraded relay subsets, and recovery.

#### 7.2 Database and pool failures

DB unavailability, pool exhaustion or startup failure, and rollback honesty
where observable.

#### 7.3 Observability-stack failures

Prometheus unavailable, Grafana unavailable, exporter unavailable, alerting path
degraded, and honest resulting behavior.

#### 7.4 Service restart and mid-flight interruption

Container restart, repeated restarts, and partial completion or shutdown.

#### 7.5 Flake and concurrency hardening

Repeat the highest-risk subsections until unexplained drift disappears.

### Wave 8 — Profile Parity And Deployment Hardening

#### 8.1 `bigbrotr` vs `lilbrotr` service/runtime parity

Prove that shared services preserve shared contracts and intended profile
differences only.

#### 8.2 Monitoring parity

Prove that dashboards, datasource wiring, rules, and exporter semantics remain
coherent across both profiles.

#### 8.3 SQL and deployment asset parity

Prove that generated SQL, deployed SQL, and certified runtime stack do not
diverge silently.

#### 8.4 Operator-experience audit

Audit whether the stack is now clean, navigable, and professionally coherent
from an operator’s point of view.

### Wave 9 — Final Audit, Cutover, And Closeout

#### 9.1 Structural audit

Every surviving higher-band file and helper must justify its existence.

#### 9.2 Remove obsolete or weak surfaces

Delete or migrate historical tests and weak support surfaces that the new stack
has superseded.

#### 9.3 Full repeated matrix audit

Run the full matrix repeatedly until the last unexplained weakness is gone.

#### 9.4 Final closeout

Close the ledger, document the final suite shape, and leave a clean worktree.

---

## Plan Self-Audit Questions

This program should not be accepted unless the answer to all of these is yes:

- Does it distinguish integration, system, and live-smoke bands clearly?
- Does it require real relay proof where relay behavior is the contract?
- Does it keep public relays out of the merge gate?
- Does it reject screenshot/pixel testing as the primary observability proof?
- Does it treat Prometheus, Alertmanager, Grafana, and exporter surfaces as
  real product contracts?
- Does it require both `bigbrotr` and `lilbrotr` to be certified explicitly?
- Does it force repeated audit loops and forbid “green enough” closure?
- Does it enforce commit-per-subsection discipline?
- Does it leave room to fix production or deployment drift inside the relevant
  subsection rather than deferring it silently?

If any answer is no, the program itself should be revised before execution
starts.
