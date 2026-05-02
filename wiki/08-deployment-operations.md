# Deployment And Operations

## Built-In Deployments

| Deployment | Purpose |
| --- | --- |
| `deployments/bigbrotr` | Full archive profile. |
| `deployments/lilbrotr` | Lightweight profile with same service set and schema shape. |
| `deployments/testbrotr` | Test profile used by integration/system harnesses. |

BigBrotr and LilBrotr include:

- PostgreSQL 18;
- PgBouncer;
- Tor proxy;
- ten application services;
- Prometheus;
- Alertmanager;
- Grafana;
- PostgreSQL exporter;
- static seed/GeoLite assets.

## Secrets

Important environment variables:

| Variable | Used by |
| --- | --- |
| `DB_ADMIN_PASSWORD` | PostgreSQL bootstrap/admin. |
| `DB_WRITER_PASSWORD` | Writer services and Assertor when configured with writer role. |
| `DB_REFRESHER_PASSWORD` | Refresher. |
| `DB_RANKER_PASSWORD` | Ranker role. |
| `DB_READER_PASSWORD` | API, DVM, PostgreSQL exporter. |
| `NOSTR_PRIVATE_KEY_MONITOR` | Monitor publishing. |
| `NOSTR_PRIVATE_KEY_SYNCHRONIZER` | Synchronizer relay auth. |
| `NOSTR_PRIVATE_KEY_DVM` | DVM identity. |
| `NOSTR_PRIVATE_KEY_ASSERTOR` | NIP-85 provider identity. |
| `GRAFANA_PASSWORD` | Grafana admin. |

Some configs generate ephemeral keys when service-specific keys are unset.
That is acceptable for local experimentation but not stable public identity.

## Observability

Services expose Prometheus metrics. The monitoring docs and system tests cover
scrape targets, host ports, alert names, dashboard layout, and profile parity.

Operationally important signals:

- successful cycle timestamp per continuous service;
- consecutive failure count;
- cycle duration;
- Refresher watermarks and row counts;
- Ranker graph/score export freshness;
- Assertor publish failures and skipped/published counts;
- API/DVM request failures and latency;
- PostgreSQL connection and cache health.

## Backup And Restore

The PostgreSQL database is the authoritative data store. Ranker also has a
private DuckDB/checkpoint store that may need reset or resync if restored from
an older PostgreSQL snapshot.

Restore order should generally be:

1. stop continuous services;
2. restore PostgreSQL;
3. reset or verify Ranker private store if needed;
4. start Refresher/Ranker/Assertor after base ingestion services;
5. verify API/DVM resources.

## Common Operational Questions

| Question | Where to inspect |
| --- | --- |
| Are relays being discovered? | Finder logs, Validator candidate state, `relay` count. |
| Are events being archived? | Synchronizer logs, `event`, `event_observation`. |
| Are documents fresh? | Monitor logs, `relay_document`, `relay_document_current`. |
| Are facts current? | Refresher metrics and refresh watermarks. |
| Are scores current? | Ranker metrics and score table timestamps. |
| Are assertions public? | Assertor logs, publish metrics, configured relays. |
| Are clients querying correctly? | API/DVM logs, Catalog errors, request metrics. |
