# Evidence Map

This appendix maps major documentation claims to the source files that should
be inspected when verifying or changing them.

## Runtime Registry And CLI

- `src/bigbrotr/services/registry.py`
- `src/bigbrotr/__main__.py`
- `src/bigbrotr/models/constants.py`
- [Services](../user-guide/services.md)
- [Configuration](../user-guide/configuration.md)

## Core Runtime

- `src/bigbrotr/core/base_service.py`
- `src/bigbrotr/core/brotr.py`
- `src/bigbrotr/core/pool.py`
- `src/bigbrotr/core/deployments.py`
- `src/bigbrotr/core/metrics.py`
- [Architecture](../user-guide/architecture.md)
- [Deployments](../user-guide/deployments.md)

## Models

- `src/bigbrotr/models/relay.py`
- `src/bigbrotr/models/event.py`
- `src/bigbrotr/models/event_observation.py`
- `src/bigbrotr/models/document.py`
- `src/bigbrotr/models/relay_document.py`
- `src/bigbrotr/models/service_state.py`
- [Database](../user-guide/database.md)

## Services

- `src/bigbrotr/services/seeder/`
- `src/bigbrotr/services/finder/`
- `src/bigbrotr/services/validator/`
- `src/bigbrotr/services/monitor/`
- `src/bigbrotr/services/synchronizer/`
- `src/bigbrotr/services/refresher/`
- `src/bigbrotr/services/ranker/`
- `src/bigbrotr/services/assertor/`
- `src/bigbrotr/services/api/`
- `src/bigbrotr/services/dvm/`
- `src/bigbrotr/services/common/`
- [Services](../user-guide/services.md)
- [Read Side](../user-guide/read-side.md)

## NIP Surfaces

- `src/bigbrotr/nips/nip11/`
- `src/bigbrotr/nips/nip66/`
- `src/bigbrotr/nips/nip85/`
- `src/bigbrotr/nips/event_builders.py`
- `src/bigbrotr/nips/registry.py`
- [NIP-85 Pipeline](../user-guide/nip85-pipeline.md)
- [Nostr NIPs Analysis](nostr-nips-analysis.md)

## SQL And Database

- `tools/templates/sql/base/02_tables_core.sql.j2`
- `tools/templates/sql/base/03_tables_current.sql.j2`
- `tools/templates/sql/base/04_tables_analytics.sql.j2`
- `tools/templates/sql/base/05_functions_crud.sql.j2`
- `tools/templates/sql/base/08_functions_refresh_current.sql.j2`
- `tools/templates/sql/base/09_functions_refresh_analytics.sql.j2`
- `deployments/bigbrotr/postgres/init/99_verify.sql`
- [Database](../user-guide/database.md)
- [SQL Templates](../development/sql-templates.md)

## Deployment And Operations

- `deployments/bigbrotr/docker-compose.yaml`
- `deployments/lilbrotr/docker-compose.yaml`
- `deployments/*/config/brotr.yaml`
- `deployments/*/config/services/*.yaml`
- `deployments/*/monitoring/`
- [Deployments](../user-guide/deployments.md)
- [Docker Deploy](../how-to/docker-deploy.md)
- [Monitoring](../user-guide/monitoring.md)

## Tests

- `tests/unit/`
- `tests/integration/`
- `tests/system/`
- `tests/live_smoke/`
- [Testing](../development/testing.md)

## Documentation

- `mkdocs.yml`
- `docs/gen_ref_pages.py`
- `docs/`
- [Documentation Maintenance](../development/documentation.md)

Related pages:

- [Project Orientation](../project/index.md)
- [Repository Map](../project/repository-map.md)
- [Decision Record](decision-record.md)
