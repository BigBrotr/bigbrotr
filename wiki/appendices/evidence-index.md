# Evidence Index

This page lists the primary files used to build the internal wiki.

## Runtime Registry

- `src/bigbrotr/services/registry.py`
- `src/bigbrotr/__main__.py`
- `src/bigbrotr/models/constants.py`

## Core Runtime

- `src/bigbrotr/core/base_service.py`
- `src/bigbrotr/core/brotr.py`
- `src/bigbrotr/core/pool.py`
- `src/bigbrotr/core/deployments.py`
- `src/bigbrotr/core/metrics.py`

## Models

- `src/bigbrotr/models/relay.py`
- `src/bigbrotr/models/event.py`
- `src/bigbrotr/models/event_observation.py`
- `src/bigbrotr/models/document.py`
- `src/bigbrotr/models/relay_document.py`
- `src/bigbrotr/models/service_state.py`

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

## NIP Surfaces

- `src/bigbrotr/nips/nip11/`
- `src/bigbrotr/nips/nip66/`
- `src/bigbrotr/nips/nip85/`
- `src/bigbrotr/nips/event_builders.py`
- `src/bigbrotr/nips/registry.py`

## SQL

- `tools/templates/sql/base/02_tables_core.sql.j2`
- `tools/templates/sql/base/03_tables_current.sql.j2`
- `tools/templates/sql/base/04_tables_analytics.sql.j2`
- `tools/templates/sql/base/05_functions_crud.sql.j2`
- `tools/templates/sql/base/08_functions_refresh_current.sql.j2`
- `tools/templates/sql/base/09_functions_refresh_analytics.sql.j2`
- `deployments/bigbrotr/postgres/init/99_verify.sql`

## Deployment

- `deployments/bigbrotr/docker-compose.yaml`
- `deployments/lilbrotr/docker-compose.yaml`
- `deployments/*/config/brotr.yaml`
- `deployments/*/config/services/*.yaml`
- `deployments/*/monitoring/`

## Tests

- `tests/unit/`
- `tests/integration/base/test_ranker.py`
- `tests/integration/base/test_assertor.py`
- `tests/integration/base/test_nip85_pipeline.py`
- `tests/system/`

## Public Docs

- `README.md`
- `mkdocs.yml`
- `docs/user-guide/architecture.md`
- `docs/user-guide/services.md`
- `docs/user-guide/database.md`
- `docs/user-guide/configuration.md`
- `docs/user-guide/monitoring.md`
- `docs/how-to/troubleshooting.md`

## PR Readiness

- `wiki/11-pr-readiness.md`
- `deployments/bigbrotr/docker-compose.yaml`
- `deployments/lilbrotr/docker-compose.yaml`
- `deployments/*/config/services/ranker.yaml`
