# Project Orientation

This section is the canonical orientation surface for the live repository. It
explains what BigBrotr is, where each responsibility lives, how the services
interact, and which source files are authoritative when the documentation and
implementation need to be checked together.

## Source Of Truth

Use this order when investigating behavior:

1. executable code under `src/bigbrotr/`;
2. tests under `tests/`;
3. SQL templates under `tools/templates/sql/`;
4. generated deployment SQL under `deployments/*/postgres/init/`;
5. deployment YAML, Docker Compose, Prometheus, Grafana, and shell assets;
6. this documentation site.

The documentation is the maintained explanation layer. It should point to the
code and tests that prove each claim, but it does not replace source review for
behavioral changes.

## Reading Path

For a complete first pass through the project:

1. Read this page.
2. Read the [repository map](repository-map.md) to learn where each subsystem
   lives.
3. Read the [system architecture](../user-guide/architecture.md) for runtime
   boundaries and service contracts.
4. Read the [data flow](data-flow.md) to understand how observations become
   public outputs.
5. Read [services](../user-guide/services.md), [database](../user-guide/database.md),
   [read side](../user-guide/read-side.md), and the
   [NIP-85 pipeline](../user-guide/nip85-pipeline.md) for operational detail.
6. Read [testing](../development/testing.md) and
   [documentation maintenance](../development/documentation.md) before changing
   the repository.

## Project Shape

BigBrotr is a storage-first Nostr relay observatory. It discovers relays,
validates connectivity, monitors relay metadata and health, archives events,
refreshes derived facts, computes public NIP-85 scores, publishes trusted
assertions, and exposes public read surfaces over HTTP and Nostr.

The runtime shape is intentionally service-oriented but database-mediated:

- services are independent processes;
- services communicate through PostgreSQL, not direct service calls;
- Ranker uses a private DuckDB store for analytical graph computation;
- API and DVM share the read-side catalog and differ only by transport.

## Canonical Runtime Services

| Service | Primary responsibility | Primary state |
| --- | --- | --- |
| Seeder | Load initial relay URLs from the seed file. | `relay` or candidate rows in `service_state` |
| Finder | Discover relay candidates from archived events and external APIs. | candidate/cursor rows in `service_state` |
| Validator | Promote validated WebSocket relays into the canonical relay pool. | `relay`, candidate failure state |
| Monitor | Fetch NIP-11 data, run NIP-66 checks, store documents, publish monitor events. | `document`, `relay_document`, monitor checkpoints |
| Synchronizer | Fetch events from validated relays and persist observations. | `event`, `event_observation`, synchronizer cursors |
| Refresher | Refresh current tables, analytics facts, and NIP-85 fact tables. | derived PostgreSQL tables |
| Ranker | Build local graph state in DuckDB and export public score snapshots. | DuckDB graph + PostgreSQL score tables |
| Assertor | Publish NIP-85 provider package and assertion events. | assertor checkpoints + Nostr events |
| API | Expose readable resources over HTTP. | read-only PostgreSQL access |
| DVM | Expose readable resources over NIP-90. | read-only PostgreSQL access + Nostr sessions |

See [services](../user-guide/services.md) for full service behavior and
[configuration](../user-guide/configuration.md) for the YAML contract.

## Current Documentation Contract

`docs/` is the only living documentation tree. Repository-local README files,
the temporary root wiki, and historical planning notes are intentionally not
part of the maintained documentation surface. If a behavior changes, update the
page in `docs/` that owns that behavior and add cross references to adjacent
pages.

Related pages:

- [Repository Map](repository-map.md)
- [Data Flow](data-flow.md)
- [Glossary](glossary.md)
- [Architecture](../user-guide/architecture.md)
- [Documentation Maintenance](../development/documentation.md)
