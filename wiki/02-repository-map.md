# Repository Map

## Top Level

| Path | Purpose |
| --- | --- |
| `src/bigbrotr/` | Python package containing models, core runtime, NIP helpers, utilities, and services. |
| `tests/` | Unit, integration, system, profile, relay, and smoke coverage. |
| `tools/` | SQL generation tooling and SQL templates. |
| `deployments/` | BigBrotr, LilBrotr, and TestBrotr deployment profiles. |
| `docs/` | MkDocs Material public documentation site. |
| `planning/` | Planning and design artifacts. |
| `.github/` | CI/CD, issue, security, and automation configuration. |
| `wiki/` | Internal codebase orientation wiki. |

## Python Package

| Package | Responsibility |
| --- | --- |
| `models` | Frozen, validated domain models and enums. No I/O. |
| `core` | Pooling, Brotr database facade, service lifecycle, deployment profile resolution, logging, metrics, YAML loading. |
| `nips` | NIP-11 data, NIP-66 checks, NIP-85 data, event builders, capability registry. |
| `utils` | Network protocol helpers, client lifecycle, publishing, proxy/session handling, HTTP, DNS, streaming. |
| `services` | Ten independent runtime services plus shared service-side abstractions. |

## Service Packages

| Package | Notes |
| --- | --- |
| `services/seeder` | Seed file parsing and bootstrap writes. |
| `services/finder` | External API discovery and event-observation scanning. |
| `services/validator` | Candidate validation and promotion. |
| `services/monitor` | Relay health/document computation and monitor publishing. |
| `services/synchronizer` | Relay event streaming and event-observation persistence. |
| `services/refresher` | Current/analytics/NIP-85 fact refresh orchestration. |
| `services/ranker` | DuckDB-backed NIP-85 score computation and snapshot export. |
| `services/assertor` | NIP-85 provider-package publication. |
| `services/api` | FastAPI read adapter. |
| `services/dvm` | NIP-90 read adapter. |
| `services/common` | Catalog, read models, state store, shared config and helpers. |

## SQL Generation

SQL source lives in `tools/templates/sql/`. Generated SQL lives under
`deployments/*/postgres/init/`. The branch uses split SQL layers:

| File group | Responsibility |
| --- | --- |
| `00_extensions` | PostgreSQL extension setup. |
| `01_functions_utility` | Utility functions used by inserts and refreshes. |
| `02_tables_core` | Core archive and state tables. |
| `03_tables_current` | Narrow current-state winner maps. |
| `04_tables_analytics` | Analytics, NIP-85 fact, and public score tables. |
| `05_functions_crud` | Bulk inserts, cascades, and service-state functions. |
| `08_functions_refresh_current` | Current table refresh functions. |
| `09_functions_refresh_analytics` | Analytics, operational fact, NIP-85, and periodic refreshes. |
| `10-12_indexes_*` | Core, current, and analytics indexes. |

## Tests

| Test area | Purpose |
| --- | --- |
| `tests/unit` | Pure unit coverage for models, core, NIPs, utilities, service logic, configs, and tooling. |
| `tests/integration/base` | PostgreSQL integration tests for schema, functions, transactions, Ranker, Assertor, and NIP-85 pipeline. |
| `tests/integration/lilbrotr` | Lightweight deployment behavior. |
| `tests/system` | Compose, monitoring, runtime, profile, relay harness, and operator-experience contracts. |
| `tests/live_smoke` | Live smoke boundaries. |

The test tree is part of the behavioral spec; inspect adjacent tests before
changing service or schema behavior.
