# Services

## Service Contract

Continuous services inherit `BaseService` behavior:

- configuration through Pydantic models;
- optional per-service pool override;
- async context lifecycle;
- `run()` for one cycle;
- `run_forever()` for interval execution;
- cleanup hook;
- structured logging;
- Prometheus metrics;
- consecutive-failure handling.

Seeder is intentionally one-shot oriented but still follows the shared service
shape.

## Service Summary

| Service | Reads | Writes | External I/O |
| --- | --- | --- | --- |
| Seeder | seed file | `service_state` candidates or `relay` | file |
| Finder | external APIs, `event_observation`, `event`, `service_state` | `service_state` | HTTP |
| Validator | `service_state` candidates | `relay`, `service_state` | WebSocket |
| Monitor | `relay`, checkpoints | `document`, `relay_document`, `service_state`, Nostr events | HTTP, DNS, SSL, GeoIP, WebSocket |
| Synchronizer | `relay`, cursors, relay streams | `event`, `event_observation`, `service_state` | WebSocket |
| Refresher | core/current/fact tables | current tables, analytics, NIP-85 facts | PostgreSQL |
| Ranker | contact graph and NIP-85 facts | public score tables, private DuckDB state | PostgreSQL, DuckDB |
| Assertor | NIP-85 facts/scores, checkpoints | `service_state`, Nostr events | WebSocket |
| API | read models/catalog resources | HTTP responses | HTTP |
| DVM | read models/catalog resources, Nostr requests | Nostr responses/feedback | WebSocket |

## Discovery Services

Seeder imports seed relay URLs. Finder expands the candidate set from API
responses and archived event data. Validator controls promotion into the
canonical `relay` table. This keeps untrusted candidates out of the durable
relay set until protocol validation succeeds.

## Observation Services

Monitor and Synchronizer are independent consumers of validated relays:

- Monitor checks relay health and documents advertised relay state.
- Synchronizer archives Nostr events and records relay observations.

Both are bounded by network config, timeouts, batching, and service-state
checkpoints.

## Derivation Services

Refresher is PostgreSQL-first: it calls stored refresh functions in configured
groups. Ranker is compute-first: it keeps a private DuckDB store for graph and
ranking work, then exports public score snapshots to PostgreSQL.

## Publication Services

Monitor publishes NIP-66-related events. Assertor publishes the NIP-85 provider
package. DVM publishes NIP-90 job feedback and results. These services need
careful key management because their public identities matter.

## Read Services

API and DVM are adapters over the shared public read core. They should expose
resource IDs and read-model contracts, not arbitrary internal table behavior.
