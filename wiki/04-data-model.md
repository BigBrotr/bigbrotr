# Data Model

## Core Archive

| Entity | Source model | Purpose |
| --- | --- | --- |
| `relay` | `Relay` | Validated relay URL, network type, and storage timestamp. |
| `event` | `Event` | Nostr event payload or lightweight event shape depending on deployment. |
| `event_observation` | `EventObservation` | Junction recording which relay served which event and when. |
| `document` | `Document` | Content-addressed NIP-11/NIP-66 document data. |
| `relay_document` | `RelayDocument` | Time-series link between a relay and a document role. |
| `service_state` | `ServiceState` | Generic per-service checkpoints, cursors, candidates, and publish state. |

`event` and `event_observation` are hash-partitioned in the generated
deployment schema. Document deduplication is application-computed, not
dependent on database extensions.

## Current Tables

| Table | Purpose |
| --- | --- |
| `relay_document_current` | Latest document per relay and document role. |
| `replaceable_event_current` | Current replaceable event winner per `(pubkey, kind)`. |
| `addressable_event_current` | Current addressable event winner per `(pubkey, kind, d_tag)`. |

These are narrow winner maps. Rich payloads remain in the core archive tables.

## Analytics And Operational Facts

| Category | Tables |
| --- | --- |
| Contact graph | `contact_lists_current`, `contact_list_edges_current` |
| Event/relay summaries | `pubkey_kind_stats`, `pubkey_relay_stats`, `relay_kind_stats`, `pubkey_stats`, `kind_stats`, `relay_stats`, `daily_counts` |
| Relay document summaries | `relay_software_counts`, `supported_nip_counts` |

These tables are maintained by Refresher functions and are read by public
adapters, Ranker, and operators.

## NIP-85 Facts And Scores

| Layer | Tables | Owner |
| --- | --- | --- |
| Facts | `nip85_pubkey_stats`, `nip85_event_stats`, `nip85_addressable_stats`, `nip85_identifier_stats` | Refresher |
| Public scores | `pubkey_score`, `event_score`, `addressable_score`, `identifier_score` | Ranker |
| Published state | `service_state` checkpoint rows | Assertor |

The facts tables provide eligible subjects and engagement metrics. Ranker adds
algorithm-scoped scores. Assertor publishes signed NIP-85 events from the
joined fact/score surfaces.

## Service State

`service_state` is keyed by:

```text
(owner, state_type, state_key)
```

State types are `checkpoint` and `cursor`.

Typical owners:

| Owner | State use |
| --- | --- |
| `finder` | API checkpoints and event-observation scan cursors. |
| `validator` | Candidate relay retry/failure state. |
| `monitor` | Check and publication checkpoints. |
| `synchronizer` | Per-relay event stream cursors. |
| `assertor` | NIP-85 content hashes and publish checkpoints. |

Ranker keeps private DuckDB/checkpoint state and exports durable score
snapshots into PostgreSQL.

## Migration Rule

Schema changes should be made in `tools/templates/sql/`, generated into
deployment SQL, and backed by integration tests. Do not patch generated
deployment SQL directly.
