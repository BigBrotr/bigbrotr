# Decision Record

This appendix records current architectural decisions that matter for operating
and extending the project. Historical planning notes are intentionally not kept
as live documentation; the repository history preserves them.

## Documentation Is Centralized In `docs/`

Decision: `docs/` is the single living documentation tree. Root and folder-level
documentation fragments are not maintained as parallel sources of truth.

Why:

- current behavior needs one obvious update target;
- duplicate wiki/planning/README surfaces drift quickly;
- MkDocs strict builds give one validation path for public documentation;
- cross references are easier to maintain in one information architecture.

Trade-off: local folders lose embedded prose. The replacement is the
[repository map](../project/repository-map.md), [evidence map](evidence-map.md),
and generated [Python API Reference](../reference/index.md).

## Services Communicate Through PostgreSQL

Decision: services do not directly call each other for runtime behavior.
Coordination happens through PostgreSQL tables, service state, and derived
facts.

Why:

- services can run, fail, and recover independently;
- operators can scale services by responsibility;
- state transitions are observable and testable through database contracts;
- API and DVM can expose stable read surfaces without coupling to service
  internals.

Related pages:

- [Architecture](../user-guide/architecture.md)
- [Data Flow](../project/data-flow.md)
- [Services](../user-guide/services.md)

## Ranker Uses DuckDB For Private Analytical State

Decision: Ranker's local graph and compute state live in DuckDB, while public
score snapshots live in PostgreSQL.

Why:

- the graph is large and analytical;
- the graph belongs to Ranker's compute lifecycle;
- PostgreSQL remains the shared canonical store for facts and public outputs;
- `service_state` is intentionally limited to small operational state.

If DuckDB state is lost, rebuild it from PostgreSQL facts rather than treating
`service_state` as a graph backup.

Related pages:

- [NIP-85 Pipeline](../user-guide/nip85-pipeline.md)
- [Ranker](../user-guide/services.md#ranker)
- [Backup And Restore](../how-to/backup-restore.md)

## API And DVM Share The Read Core

Decision: HTTP API and NIP-90 DVM expose the same readable-resource catalog
through different transport adapters.

Why:

- read semantics remain protocol-agnostic;
- resource enablement and bounds stay consistent;
- adapter-specific behavior is isolated at the transport edge;
- the old public `read_model` transport vocabulary can remain compatible
  without controlling internal architecture.

Related pages:

- [Read Side](../user-guide/read-side.md)
- [Services](../user-guide/services.md#api)

## SQL Is Template-Owned

Decision: generated deployment SQL is not edited directly. SQL changes start in
`tools/templates/sql/`, then regenerate deployment packages.

Why:

- BigBrotr and LilBrotr share most SQL while differing in storage profile;
- generated deployment packages stay reproducible;
- drift is caught by `tools/generate_sql.py --check`;
- tests can validate templates and generated output together.

Related pages:

- [SQL Templates](../development/sql-templates.md)
- [Database](../user-guide/database.md)

## System And Live-Smoke Tests Are Separate From The Unit Matrix

Decision: the CI unit matrix excludes `tests/integration/`, `tests/system/`,
and `tests/live_smoke/`. Integration tests run in a dedicated job. System and
live-smoke tests are separate higher-band suites.

Why:

- unit tests should be fast and deterministic across the Python matrix;
- system tests require Docker/runtime orchestration;
- live-smoke tests depend on external network behavior;
- mixing suites under one job name hides the real failing contract.

Related pages:

- [Testing](../development/testing.md)
- [Contributing](../development/contributing.md)
