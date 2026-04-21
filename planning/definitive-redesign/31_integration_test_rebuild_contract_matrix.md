# Integration Test Rebuild Contract Matrix

## Purpose

This file freezes the live integration-contract matrix at the real rebuild
start.

It is not a prose summary of “what the tests kind of do”.
It is the auditable map of:

- what the current integration suite really covers;
- what the product actually needs from a professional integration layer;
- what boundaries must be exercised honestly;
- what doubles are still acceptable;
- and where the execution program must add or replace coverage.

This matrix is the execution companion for:

- [28_integration_test_rebuild_program.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/28_integration_test_rebuild_program.md)
- [29_integration_test_rebuild_ledger.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/29_integration_test_rebuild_ledger.md)
- [30_integration_test_rebuild_manifest.txt](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/30_integration_test_rebuild_manifest.txt)

---

## Frozen Start State

- Rebuild start date:
  `2026-04-21`
- Frozen branch:
  `refactor/definitive-redesign-execution`
- Frozen baseline commit:
  `e0fb0e45`
- Tracked integration file count:
  `24`
- Current tracked suite shape:
  root support files plus two historical subtrees:
  `tests/integration/base` and `tests/integration/lilbrotr`

The current suite is therefore a useful baseline, but not the target suite
shape.

---

## Product-Level Contract Bands

BigBrotr needs integration proof across five product concerns:

1. Discovery
2. Health monitoring
3. Event archiving
4. Shared derivation and public publication
5. Public read/query exposure

The current suite proves the fourth concern well enough to be trusted as
reference input.
It proves the first, second, third, and fifth only partially or not at all.

---

## Current Coverage Versus Required Coverage

| Contract Band | Current Coverage | Required Rebuild Outcome | Gap Type |
|---------------|------------------|--------------------------|----------|
| Shared PostgreSQL schema contract | Strong | Preserve and restructure as first-class `shared_db/` contract tests | Structural |
| Shared SQL function / refresh contract | Strong | Preserve and restructure with clearer file boundaries and builder reuse | Structural |
| `Pool` / `Brotr` live runtime | Weak | Dedicated integration coverage for lifecycle, transaction, and failure seams | Missing |
| `Seeder` service runtime | None | Dedicated service integration coverage | Missing |
| `Finder` service runtime | None | Dedicated service integration coverage | Missing |
| `Validator` service runtime | None | Dedicated service integration coverage | Missing |
| `Monitor` service runtime | None | Dedicated service integration coverage | Missing |
| `Synchronizer` service runtime | None | Dedicated service integration coverage | Missing |
| `Refresher` service runtime | Present | Rebuild into explicit service-contract tests plus pipeline ownership | Structural |
| `Ranker` service runtime | Present | Rebuild into explicit service-contract tests plus failure/restart proof | Structural |
| `Assertor` service runtime | Present | Rebuild into explicit service-contract tests plus publish-failure proof | Structural |
| `API` service runtime | None | Dedicated integration coverage at protocol boundary | Missing |
| `DVM` service runtime | None | Dedicated integration coverage at protocol boundary | Missing |
| Cross-service discovery pipeline | None | End-to-end discovery pipeline proof | Missing |
| Cross-service archive pipeline | None | End-to-end archive pipeline proof | Missing |
| Cross-service derivation pipeline | Present in narrow form | Rebuild as explicit pipeline band with restart/idempotency coverage | Structural |
| Public read pipeline | None | End-to-end API/DVM read-surface proof | Missing |
| `bigbrotr` deployment contract | Implicit | Explicit profile tests and SQL parity proof | Missing |
| `lilbrotr` deployment contract | Partial | Preserve profile-specific proof with sharper boundaries | Structural |
| `testbrotr` test-deployment contract | None | Decide and either test intentionally or retire honestly | Missing |
| Failure/recovery/resilience matrix | Partial and scattered | Dedicated failure band with named injection seams | Missing |

---

## Current Tracked File Matrix

### Root integration harness surfaces

| File | Current Role | Keep As Reference | Rebuild Action |
|------|--------------|-------------------|----------------|
| `tests/integration/conftest.py` | Shared PostgreSQL container plus deployment-aware `make_brotr()` | Yes | Split into explicit harness modules and thinner fixture entry surface |
| `tests/integration/README.md` | High-level scope note | Yes | Rewrite to match final suite taxonomy |
| `tests/integration/__init__.py` | Package marker | No strong opinion | Keep or remove based on final import needs |

### `base/` subtree

| File | Current Contract | Coverage Value | Rebuild Action |
|------|------------------|----------------|----------------|
| `base/conftest.py` | `bigbrotr` fixture alias | Medium | Replace with deployment fixtures under the new harness/profile layer |
| `base/test_relay_crud.py` | Relay storage contract | High | Preserve semantics, move to `shared_db/` |
| `base/test_document_crud.py` | Document and relay-document contract | High | Preserve semantics, move to `shared_db/` |
| `base/test_event_crud.py` | Event and event-observation contract | High | Preserve semantics, move to `shared_db/` |
| `base/test_service_state.py` | Service-state contract | High | Preserve semantics, move to `shared_db/` or `core/` |
| `base/test_foreign_keys.py` | FK and retention boundary checks | High | Preserve semantics, split by sharper contract boundary |
| `base/test_partitioning.py` | Partitioning structure and colocation | High | Preserve semantics, move to `shared_db/` |
| `base/test_transactions.py` | Transaction and concurrency contract | High | Preserve semantics, move to `shared_db/` or `core/` |
| `base/test_storage_retention.py` | Retention contract | High | Preserve semantics, move to `shared_db/` |
| `base/test_derived_tables.py` | Refresh/fact/current/score contract | High | Preserve semantics, split into narrower contract files |
| `base/test_refresher.py` | `Refresher` service integration | High | Rebuild under `services/refresher/` plus pipeline tests |
| `base/test_ranker.py` | `Ranker` service integration | High | Rebuild under `services/ranker/` plus restart/failure tests |
| `base/test_assertor.py` | `Assertor` service integration | High | Rebuild under `services/assertor/` plus failure/publish tests |
| `base/test_nip85_pipeline.py` | `Refresher` -> `Ranker` -> `Assertor` smoke | High | Rebuild under `pipelines/derivation/` with stronger restart/idempotency proof |
| `base/README.md` | Local subtree guide | Medium | Replace or rewrite to reflect final taxonomy |

### `lilbrotr/` subtree

| File | Current Contract | Coverage Value | Rebuild Action |
|------|------------------|----------------|----------------|
| `lilbrotr/conftest.py` | `lilbrotr` fixture alias | Medium | Replace with profile fixture layer |
| `lilbrotr/test_event_crud.py` | Lightweight event-storage differences | High | Preserve semantics, move to `deployments/lilbrotr/` or `shared_db/profiles/` |
| `lilbrotr/test_derived_tables.py` | Lightweight derived-table differences | High | Preserve semantics, move to `deployments/lilbrotr/` |
| `lilbrotr/README.md` | Local subtree guide | Medium | Replace or rewrite to reflect final taxonomy |

---

## Service Boundary Matrix

| Service | Current Integration File | Real Boundary That Must Be Proven | External Doubles Allowed |
|---------|--------------------------|-----------------------------------|--------------------------|
| `Seeder` | None | Seed-source ingestion into live shared storage | Seed source payload provider |
| `Finder` | None | API-source discovery, cooldown, dedup, relay persistence | HTTP/API source client |
| `Validator` | None | Relay validation and persistence against live DB state | Relay connectivity / protocol client |
| `Monitor` | None | NIP-11/NIP-66/health probes storing real documents | HTTP fetch, DNS, network probe seams |
| `Synchronizer` | None | Live archive inserts, checkpointing, retention interaction | Relay session / event stream client |
| `Refresher` | `base/test_refresher.py` | Refresh orchestration over live schema and service state | None or minimal clock helpers |
| `Ranker` | `base/test_ranker.py` | Score export and private-store interaction over live shared DB | Local filesystem/store seams only where necessary |
| `Assertor` | `base/test_assertor.py` | NIP-85 hydration and publish package generation over live DB | Publish session and broadcast boundary |
| `API` | None | Read-core exposure at HTTP-facing adapter boundary | Minimal ASGI/transport harness, no DB fake |
| `DVM` | None | Read-core exposure at DVM job/event boundary | Protocol publish/session boundary only |

---

## External Boundary Matrix

| Boundary | Reality Requirement | Current State | Rebuild Rule |
|----------|---------------------|---------------|--------------|
| PostgreSQL | Real via testcontainers | Real | Keep real |
| Deployment SQL init | Real | Real for `bigbrotr` / `lilbrotr` fixture setup | Keep real and prove parity |
| Nostr publish session | Named double acceptable | Scattered inline mocks | Replace with named harness double |
| Relay connection/session | Named double acceptable | Not covered at integration level for most services | Introduce explicit harness doubles |
| HTTP fetch | Named double acceptable | Not covered at integration level except indirectly | Introduce explicit harness doubles |
| DNS / network lookup | Named double acceptable | Not covered at integration level except indirectly | Introduce explicit harness doubles |
| Filesystem ranker store | Real temp storage preferred | Partially real inside current ranker tests | Standardize through deterministic temp helpers |
| Time / clock sequencing | Deterministic helper required | Ad hoc fixed timestamps | Centralize deterministic helpers |

---

## Frozen Rebuild Priorities

Execution priority is:

1. freeze and document the target suite architecture;
2. rebuild harness first;
3. preserve and restructure the strongest existing DB and derivation coverage;
4. fill the totally missing service/runtime gaps;
5. close deployment/failure/recovery gaps;
6. remove historical subtree leftovers only after the new suite proves parity
   or better.

This priority order is mandatory.
It prevents the rebuild from:

- deleting strong historical coverage too early;
- adding new service tests on top of an unstable harness;
- or calling the rebuild “done” while key product concerns remain untested.
