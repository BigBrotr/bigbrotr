# Current State

BigBrotr is a storage-first Nostr relay observatory. It discovers relays,
validates connectivity, stores relay documents and event observations, derives
shared facts, computes public NIP-85 scores, publishes provider output, and
exposes approved public data through HTTP and Nostr.

## Implemented Runtime Services

The CLI registry in `src/bigbrotr/services/registry.py` contains ten service
entries:

| Service | Runtime role |
| --- | --- |
| `seeder` | Bootstrap relay URLs from seed files. |
| `finder` | Discover candidate relay URLs from APIs and archived event observations. |
| `validator` | Validate relay candidates with Nostr WebSocket checks. |
| `monitor` | Fetch NIP-11 documents, run NIP-66 checks, persist documents, and publish monitor events. |
| `synchronizer` | Stream events from validated relays and persist event observations. |
| `refresher` | Refresh current tables, analytics facts, operational facts, and periodic reconciliations. |
| `ranker` | Compute deterministic NIP-85 public scores in a private DuckDB-backed store and export snapshots to PostgreSQL. |
| `api` | Serve approved public readable resources over HTTP. |
| `dvm` | Serve the same public readable resources through NIP-90 requests over Nostr. |
| `assertor` | Publish the NIP-85 provider package and assertion events. |

## Core Storage Shape

The base schema is not the older `metadata` / `relay_metadata` /
`event_relay` naming. The current branch uses:

| Area | Objects |
| --- | --- |
| Core archive | `relay`, `event`, `event_observation`, `document`, `relay_document`, `service_state` |
| Current tables | `relay_document_current`, `replaceable_event_current`, `addressable_event_current` |
| Operational contact facts | `contact_lists_current`, `contact_list_edges_current` |
| Analytics summaries | `daily_counts`, `relay_software_counts`, `supported_nip_counts`, `pubkey_kind_stats`, `pubkey_relay_stats`, `relay_kind_stats`, `pubkey_stats`, `kind_stats`, `relay_stats` |
| NIP-85 fact tables | `nip85_pubkey_stats`, `nip85_event_stats`, `nip85_addressable_stats`, `nip85_identifier_stats` |
| Public score tables | `pubkey_score`, `event_score`, `addressable_score`, `identifier_score` |

`service_state` uses `owner`, `state_type`, `state_key`, and `state_value`.
It is intentionally generic so new service checkpoints and cursors can be added
without database migrations.

## Function Inventory

The generated base deployment reports 38 stored functions:

| Class | Count | Examples |
| --- | ---: | --- |
| Utility | 5 | `tags_to_tagvalues`, `event_d_tag`, `normalize_event_address`, `event_address`, `bolt11_amount_msats` |
| CRUD and state | 10 | `relay_insert`, `event_insert`, `document_insert`, `event_observation_insert_cascade`, `relay_document_insert_cascade`, `service_state_*` |
| Current refresh | 3 | `relay_document_current_refresh`, `replaceable_event_current_refresh`, `addressable_event_current_refresh` |
| Analytics and operational-fact refresh | 13 | `contact_lists_current_refresh`, `relay_stats_refresh`, `daily_counts_refresh`, `supported_nip_counts_refresh` |
| NIP-85 incremental refresh | 4 | `nip85_*_stats_refresh` |
| Periodic refresh | 3 | `rolling_windows_refresh`, `relay_stats_document_refresh`, `nip85_follower_count_refresh` |

There are no base cleanup functions in the current generated schema.

## Deployment Profiles

| Profile | Purpose |
| --- | --- |
| `bigbrotr` | Full archive deployment that stores complete event payloads. |
| `lilbrotr` | Lightweight deployment with the same service and schema shape, but lighter event storage. |
| `testbrotr` | Test-oriented deployment assets. |

Both main deployments include all ten services and the monitoring stack.

## Important Corrections

- Ranker and Assertor are implemented runtime services on this branch.
- The Python API reference is generated from the Python package at build time.
- Generated SQL under deployment folders should not be manually edited; change
  templates and regenerate.
- The database design is table/function heavy, not service-to-service API heavy.
