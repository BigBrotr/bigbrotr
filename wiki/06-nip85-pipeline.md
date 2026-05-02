# NIP-85 Pipeline

The NIP-85 pipeline turns observed public data into ranked public assertion
events.

## Stages

```text
Synchronizer -> event + event_observation
Refresher -> contact graph + NIP-85 fact tables
Ranker -> public score tables
Assertor -> signed NIP-85 provider package
```

## Refresher Fact Surfaces

Refresher maintains:

- `contact_lists_current`;
- `contact_list_edges_current`;
- `nip85_pubkey_stats`;
- `nip85_event_stats`;
- `nip85_addressable_stats`;
- `nip85_identifier_stats`;
- periodic follower/following counts.

The lightweight deployment keeps parity where metrics can be reconstructed from
stored event IDs, pubkeys, kinds, observed timestamps, and tagvalues. Metrics
that need full tags use documented fallback behavior.

## Ranker

Ranker computes deterministic public scores for:

| Kind | Subject | Score table |
| --- | --- | --- |
| `30382` | pubkey | `pubkey_score` |
| `30383` | event id | `event_score` |
| `30384` | addressable event coordinate | `addressable_score` |
| `30385` | NIP-73 identifier | `identifier_score` |

Ranker uses a private DuckDB store for graph state and intermediate ranking
work. Public outputs are snapshot-exported to PostgreSQL with `algorithm_id` so
multiple algorithms can be represented without changing the subject tables.

## Assertor

Assertor reads NIP-85 fact tables joined with public score tables for a
configured algorithm. It publishes:

- kind `30382` user assertions;
- kind `30383` event assertions;
- kind `30384` addressable assertions;
- kind `30385` identifier assertions;
- optional kind `0` provider profile;
- optional kind `10040` trusted-provider list.

Content hashes are persisted in `service_state`, allowing Assertor to skip
unchanged subjects and republish only changed payloads.

## Operational Dependencies

| Symptom | Likely layer |
| --- | --- |
| No eligible subjects | Synchronizer or Refresher stale. |
| Facts exist but no scores | Ranker stale or failing. |
| Scores exist but no public events | Assertor relay/key/publish issue. |
| Published output tied to wrong algorithm | `algorithm_id` mismatch across Refresher/Ranker/Assertor config. |

## Key Design Decisions

- Public score tables are durable PostgreSQL surfaces.
- Private graph computation state is kept outside the primary database.
- Publication identity is separated from monitor/DVM identities through
  service-specific key configuration.
- Algorithm scope is explicit and should be treated as part of the public
  output contract.
