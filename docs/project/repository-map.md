# Repository Map

This page maps the live repository to the system responsibilities described in
the [architecture](../user-guide/architecture.md), [services](../user-guide/services.md),
and [database reference](../user-guide/database.md).

## Top-Level Layout

| Path | Responsibility | Related docs |
| --- | --- | --- |
| `src/bigbrotr/models/` | Frozen domain models, enums, validation, and cached database parameters. | [Architecture](../user-guide/architecture.md), [Python API Reference](../reference/models/index.md) |
| `src/bigbrotr/core/` | Pool, Brotr DB facade, BaseService lifecycle, deployments, logging, metrics, YAML loading. | [Architecture](../user-guide/architecture.md), [Configuration](../user-guide/configuration.md) |
| `src/bigbrotr/nips/` | NIP-11, NIP-66, NIP-85, event builders, and protocol capability helpers. | [NIP-85 Pipeline](../user-guide/nip85-pipeline.md), [Nostr NIPs Analysis](../appendices/nostr-nips-analysis.md) |
| `src/bigbrotr/utils/` | DNS, HTTP, transport, protocol sessions, streaming, key handling. | [Services](../user-guide/services.md), [Testing](../development/testing.md) |
| `src/bigbrotr/services/` | Ten independent service implementations plus shared service-side utilities. | [Services](../user-guide/services.md) |
| `tools/templates/sql/` | Jinja2 source of truth for deployment SQL packages. | [SQL Templates](../development/sql-templates.md), [Database](../user-guide/database.md) |
| `deployments/` | Built-in deployment profiles, generated SQL, service YAML, Compose, monitoring assets. | [Deployments](../user-guide/deployments.md), [Docker Deploy](../how-to/docker-deploy.md) |
| `tests/unit/` | Fast tests for models, core, NIPs, services, utilities, tooling, and local harness helpers. | [Testing](../development/testing.md) |
| `tests/integration/` | PostgreSQL-backed integration tests against generated deployment schemas. | [Testing](../development/testing.md), [Database](../user-guide/database.md) |
| `tests/system/` | Docker/system tests for deployment, observability, resilience, and pipelines. | [Testing](../development/testing.md), [Monitoring](../user-guide/monitoring.md) |
| `tests/live_smoke/` | Quarantined live-network smoke tests. | [Testing](../development/testing.md) |
| `.github/` | CI, release, security, issue, and PR automation. | [Contributing](../development/contributing.md) |
| `docs/` | Canonical documentation site. | [Documentation Maintenance](../development/documentation.md) |

## Package Boundaries

Imports follow the Diamond DAG:

```text
              services         src/bigbrotr/services/
             /   |   \
          core  nips  utils    src/bigbrotr/{core,nips,utils}/
             \   |   /
              models           src/bigbrotr/models/
```

Rules:

- `models` does not depend on project runtime modules.
- `core`, `nips`, and `utils` may depend on `models`.
- `services` may depend on all lower layers.
- Service modules must not import each other directly for runtime behavior.
- Service-to-service coordination happens through PostgreSQL state.

See [Architecture](../user-guide/architecture.md) for the rationale and
[Coding Standards](../development/coding-standards.md) for import conventions.

## Service Packages

| Package | Runtime role | Main implementation |
| --- | --- | --- |
| `services/seeder` | Seed relay URLs. | `service.py`, `configs.py`, `utils.py` |
| `services/finder` | Discover candidate relay URLs. | `service.py`, `queries.py`, `configs.py` |
| `services/validator` | Validate and promote candidates. | `service.py`, `runtime.py`, `queries.py` |
| `services/monitor` | NIP-11/NIP-66 monitoring and publication. | `service.py`, `processing.py`, `publishing.py`, `queries.py` |
| `services/synchronizer` | Event fetch/archive pipeline. | `service.py`, `runtime.py`, `queries.py` |
| `services/refresher` | Derived-table refresh orchestration. | `service.py`, `runtime.py`, `queries.py` |
| `services/ranker` | DuckDB graph and score export. | `service.py`, `store_graph.py`, `store_runtime.py`, `queries.py` |
| `services/assertor` | NIP-85 publication. | `service.py`, `publishing.py`, `queries.py` |
| `services/api` | HTTP read adapter. | `service.py`, `app.py`, `routes.py` |
| `services/dvm` | NIP-90 read adapter. | `service.py`, `jobs.py`, `publishing.py` |
| `services/common` | Shared service-side helpers. | `catalog.py`, `read_core.py`, mixins |

Each service has a generated Python reference under
[Python API Reference](../reference/index.md).

## Generated And Derived Files

The SQL files in `deployments/*/postgres/init/` are generated from
`tools/templates/sql/`. Do not edit generated SQL directly. Change the template,
run `uv run python tools/generate_sql.py`, and verify with:

```bash
uv run python tools/generate_sql.py --check
```

Reference deployment folders also contain runtime-state directories. Directory
tracking is handled with non-documentation keepers where the repository needs to
preserve an empty path.

## Removed Local Documentation Surfaces

The repository no longer treats folder README files, the temporary root wiki, or
historical planning notes as living documentation. Their useful current content
has been consolidated into this site. Historical material remains available in
Git history and in the current [Decision Record](../appendices/decision-record.md).

Related pages:

- [Project Orientation](index.md)
- [Data Flow](data-flow.md)
- [SQL Templates](../development/sql-templates.md)
- [Documentation Maintenance](../development/documentation.md)
