# services

Independent runtime services plus service-layer shared infrastructure.

## Main Areas

- `common/`: shared read core, catalog execution, config, paging, mixins, and
  state helpers.
- `seeder/`, `finder/`, `validator/`, `monitor/`, `synchronizer/`: archive and
  relay-observability pipeline.
- `refresher/`, `ranker/`, `assertor/`: derived facts, score export, and
  provider-package publication.
- `api/`, `dvm/`: public protocol adapters over the shared read core.
- `registry.py`: CLI-visible service registry.

## Rules

- Services communicate through the shared database, not direct imports between
  service packages.
- Keep service boundaries semantically honest: archive ownership, read-side
  exposure, ranking, and provider publication each have distinct homes.
