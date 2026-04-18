# BigBrotr Project Guide

This file is the implementation-aligned root overview for BigBrotr.

It is meant to answer, quickly and honestly:

- what the project is today;
- how the runtime is composed;
- what the shared data model means;
- how the public read side works;
- how deployments are modeled;
- where a contributor should look first in the repository.

If this guide and the code ever disagree, the code is the source of truth.

Role and precedence:

- this file is a **current-state implementation guide**;
- it is not the final redesign execution contract;
- canonical redesign targets and sequencing live under
  `planning/definitive-redesign/`, especially:
  - `12_best_db_schema.md`
  - `14_core_read_layer_proposal.md`
  - `15_deployment_contract_proposal.md`
  - `16_operational_implementation_plan.md`
  - `99_definitive_master_plan.md`

---

## 1. Product Identity

BigBrotr is a storage-first Nostr relay observatory.

It continuously tries to answer four questions:

1. Which relays exist on the Nostr network?
2. Which of them are valid, reachable, and healthy?
3. Which events are they publishing?
4. Which shared facts and public NIP-85 outputs can be built from those
   observations?

That means BigBrotr is not just:

- a relay monitor;
- an event archiver;
- a generic Nostr client;
- or a schema browser over PostgreSQL.

It is a composed system with four main concerns:

- discovery;
- validation and monitoring;
- event archiving;
- shared derivation plus public score/assertion publication.

---

## 2. Runtime Shape

BigBrotr ships ten built-in services:

| Service | Responsibility | External I/O |
|---------|----------------|--------------|
| `seeder` | Bootstrap initial relay candidates from seed files | local files |
| `finder` | Discover additional relay candidates from APIs and archived event tagvalues | HTTP, PostgreSQL |
| `validator` | Validate candidate relays and promote valid ones into the canonical relay pool | WebSocket |
| `monitor` | Run NIP-11 and NIP-66 checks, persist relay documents, publish monitoring events | HTTP, WebSocket, DNS, SSL, GeoIP |
| `synchronizer` | Archive events from validated relays with resumable bounded streaming | WebSocket |
| `refresher` | Maintain narrow current tables, shared analytics facts, and NIP-85 fact tables | PostgreSQL |
| `ranker` | Maintain a private DuckDB compute store and export final public score tables | PostgreSQL, DuckDB |
| `assertor` | Publish the NIP-85 provider package from canonical facts and public scores | WebSocket (Nostr) |
| `api` | Expose deployment-approved public readable resources over HTTP | FastAPI/HTTP |
| `dvm` | Expose the same public readable resources over NIP-90 | WebSocket (Nostr) |

The services are intentionally independent:

- there is no service-to-service RPC;
- PostgreSQL is the canonical integration boundary;
- one service going down does not directly crash the others;
- downstream services see stale or missing data until upstream producers resume.

The broad flow is:

```text
seed file -> Seeder -> service_state candidate entries
APIs + archived event tagvalues -> Finder -> more candidates
candidates -> Validator -> relay
relay -> Monitor -> document + relay_document + monitor publication
relay -> Synchronizer -> event + event_observation
archive tables -> Refresher -> current tables + analytics facts + NIP-85 facts
shared facts -> Ranker -> public score tables
shared facts + public scores -> Assertor -> NIP-85 provider package
enabled readable resources -> Api/Dvm -> public query surfaces
```

---

## 3. Shared Data Model

### 3.1 Core archive tables

The canonical shared archive is built around:

| Table | Meaning |
|-------|---------|
| `relay` | canonical stored relay pool |
| `event` | canonical archived Nostr events |
| `event_observation` | which relay served which event, and when BigBrotr observed it |
| `document` | content-addressed stored documents |
| `relay_document` | time-series relay-to-document associations |
| `service_state` | shared operational state keyed by `(owner, state_type, state_key)` |

Two naming points matter a lot:

- `document` is the canonical content-addressed storage concept;
- `service_state` uses `owner`, not the old `service_name` vocabulary.

### 3.2 Derived shared tables

The archive feeds several classes of derived shared data:

| Class | Examples | Owner |
|-------|----------|-------|
| Narrow current tables | `relay_document_current`, `replaceable_event_current`, `addressable_event_current` | Refresher |
| Shared analytics facts | `pubkey_stats`, `kind_stats`, `relay_stats`, cross-tabs, `daily_counts` | Refresher |
| Operational contact facts | `contact_lists_current`, `contact_list_edges_current` | Refresher |
| NIP-85 fact tables | `nip85_pubkey_stats`, `nip85_event_stats`, `nip85_addressable_stats`, `nip85_identifier_stats` | Refresher |
| Public score tables | `pubkey_score`, `event_score`, `addressable_score`, `identifier_score` | Ranker |

The important boundary is:

- `Refresher` owns canonical shared derivations;
- `Ranker` owns private compute plus public score export;
- `Assertor` owns publication from those shared facts and scores.

### 3.3 Storage profiles

Built-in deployments currently use two storage profiles:

| Deployment | Storage profile | Meaning |
|------------|-----------------|---------|
| `bigbrotr` | `full_archive` | stores full event payloads |
| `lilbrotr` | `lightweight_archive` | stores identity + `tagvalues`, leaves tags/content/signature unpopulated |

This contract lives in `src/bigbrotr/core/deployments.py`, not only in folder
names.

---

## 4. Public Read Side

The public read side is no longer just "catalog plus transport handlers".

The current shape is:

- `Catalog`: discovered schema and safe read-only query execution;
- readable-resource registry: canonical internal descriptors of public
  resources;
- `ReadCore`: protocol-agnostic shared read engine;
- `api` and `dvm`: thin adapters above that core.

Important nuance:

- the internal contract is now **readable resources**;
- the public transport seam still uses the historical `read_model` identifier
  in URLs, config, and NIP-90 requests for compatibility.

So when reading the code:

- `src/bigbrotr/services/common/read_model_registry.py` is the readable-resource registry;
- `src/bigbrotr/services/common/read_models.py` contains `ReadCore` plus the
  compatibility wrapper `ReadModelSurface`;
- `src/bigbrotr/services/api/` and `src/bigbrotr/services/dvm/` are adapter
  layers, not the read-side core.

The guiding rule is:

- public adapters may preserve the historical `read_model` surface;
- the architectural center is the shared `ReadCore`.

---

## 5. Deployment Model

Deployments are first-class compositions, not just folders users happen to
copy.

The built-in deployment contract is folder-based and YAML-first:

- `deployments/bigbrotr/`
- `deployments/lilbrotr/`

Each built-in deployment has:

- `config/brotr.yaml`
- `config/services/*.yaml`
- `docker-compose.yaml`
- `.env.example`
- `postgres/init/` generated SQL package
- local operator `README.md` guidance

The deployment contract is normalized in:

- `src/bigbrotr/core/deployments.py`

That module is the right place to check:

- built-in deployment names;
- storage profile mapping;
- required deployment paths;
- default root resolution for `--profile bigbrotr` / `--profile lilbrotr`.

Deployment-level policy now has two distinct layers:

1. **what exists**
   - determined by deployment folder + storage profile + enabled services
2. **what is exposed**
   - determined by adapter-local protocol exposure policy (`api`, `dvm`, and
     future adapters)

---

## 6. Code Layout

### 6.1 Source DAG

The Python package follows the intended diamond DAG:

```text
              services
             /   |   \
          core  nips  utils
             \   |   /
              models
```

Layer intent:

| Layer | Purpose |
|-------|---------|
| `models` | immutable validated domain structures |
| `core` | DB/runtime/logging/metrics/config foundations |
| `nips` | NIP-aware protocol data and builders |
| `utils` | low-level protocol, transport, DNS, key, and streaming helpers |
| `services` | orchestration and service-local policy |

### 6.2 Top-level repository areas

| Path | Purpose |
|------|---------|
| `src/` | Python package |
| `deployments/` | built-in deployment folders, SQL packages, operator assets |
| `tools/` | SQL generation and operational tooling |
| `tests/` | unit and integration suites |
| `docs/` | MkDocs site and local documentation surfaces |
| `planning/definitive-redesign/` | redesign target and execution contract |

### 6.3 Practical entry points

If you need the most useful current-state files first, start here:

- `src/bigbrotr/__main__.py`
- `src/bigbrotr/services/registry.py`
- `src/bigbrotr/core/brotr.py`
- `src/bigbrotr/core/deployments.py`
- `src/bigbrotr/services/common/read_models.py`
- `src/bigbrotr/services/common/read_model_registry.py`
- `tools/templates/sql/`
- `deployments/bigbrotr/`
- `tests/`

---

## 7. Quality And Verification

BigBrotr expects repository-wide rigor, not just working code.

The minimum commit gate is:

```bash
make ci
uv lock --check
```

When schema or deployment SQL changes are involved, also verify:

```bash
python tools/generate_sql.py --check
```

When documentation or guidance changes are involved, also verify:

```bash
mkdocs build --strict
```

The repository also treats `src/` as a usable Python library surface, so
public package docs, import ergonomics, and discoverability matter alongside
service behavior.

---

## 8. Related Root References

These root files each serve a different role:

| File | Role |
|------|------|
| `README.md` | public-facing summary |
| `PROJECT_GUIDE.md` | current-state implementation overview |
| `PROJECT_VISION_AND_REDESIGN_PLAN.md` | architectural direction memo |
| `BIGBROTR_REPOSITORY_BIBLE.md` | deeper repository reference |
| `NOSTR_NIPS_DEEP_ANALYSIS.md` | protocol-analysis reference |
| `planning/definitive-redesign/` | canonical redesign target and execution program |

Use this guide when you need a current implementation map.
Use the redesign planning set when you need the final target shape or the
execution protocol.
