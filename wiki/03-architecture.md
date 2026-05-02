# Architecture

## Architectural Style

BigBrotr is a database-coordinated distributed system. Services do not call
each other directly. Each service owns a runtime concern, reads from
PostgreSQL or the network, writes back to PostgreSQL or Nostr, and can be run
or restarted independently.

```text
services
  -> core / nips / utils
    -> models
```

Imports flow downward. Models remain pure and reusable; service packages own
I/O, orchestration, retries, and runtime metrics.

## Runtime Flow

```text
Seeder/Finder -> service_state candidates
Validator -> relay
Monitor -> document + relay_document + monitor events
Synchronizer -> event + event_observation
Refresher -> current tables + analytics facts + NIP-85 facts
Ranker -> public score tables
Assertor -> NIP-85 events + service_state checkpoints
API/DVM -> public readable resources
```

## Core Components

| Component | Role |
| --- | --- |
| `Pool` | asyncpg pool wrapper with retry/backoff behavior. |
| `Brotr` | Database facade for stored functions and bulk mutations. |
| `BaseService` | Shared service lifecycle, interval loop, cleanup hook, metrics, failures, shutdown. |
| `service_runtime` | Shared runtime helpers for service execution patterns. |
| `deployments` | Built-in profile resolution for `--profile` service execution. |
| `Logger` | Structured key/value and JSON logging support. |
| `Metrics` | Prometheus metrics server and service metric helpers. |

## Model Layer Principles

| Principle | Implementation |
| --- | --- |
| Immutability | Dataclasses use frozen/slots patterns. |
| Fail-fast validation | Constructors normalize and reject invalid state. |
| Cached DB params | Models compute database parameter tuples once. |
| Content addressing | `Document` computes SHA-256 IDs from canonical JSON. |
| URL normalization | Relay URL parsing/classification lives in model helpers. |

## Service Boundary Rules

- Services communicate through PostgreSQL and Nostr, not direct imports.
- Query code lives in service-specific `queries.py` modules or shared common
  query/catalog modules.
- Runtime state that is not durable domain data belongs in `service_state`.
- Durable shared facts belong in explicit tables or generated SQL functions.
- Public read behavior is mediated by read models and the catalog, not raw
  arbitrary SQL from clients.

## Failure Domains

| Failure | Expected containment |
| --- | --- |
| Finder outage | Existing relays continue to validate, monitor, sync, refresh, rank, and serve. |
| Validator outage | New candidates do not promote; existing relays continue. |
| Monitor outage | Health/document history becomes stale; sync and read paths continue. |
| Synchronizer outage | Event archive and derived facts become stale; monitor/read paths continue. |
| Refresher outage | Current, analytics, and NIP-85 fact surfaces become stale. |
| Ranker outage | Public score exports become stale; Assertor publishes latest available scores. |
| Assertor outage | Public NIP-85 publication pauses; internal facts and scores continue. |
| API/DVM outage | Data collection and publication services continue. |

## Interpretation

The architecture optimizes for operational independence, explicit data
surfaces, and recoverability over low-latency service-to-service workflows. The
main trade-off is that schema/function contracts must be maintained carefully
because PostgreSQL is the coordination boundary.
