# BigBrotr WoTathon Demo

This file is the reproducible demo walkthrough for the WoTathon submission.
It complements the demo video and shows how to run the submitted
`hackathon/wotathon-submission` branch with the bundled TestBrotr deployment.

Demo video folder:
<https://drive.google.com/drive/folders/1apKN1P-el4wMJMZLDylt6EC8EAwNVjRV?usp=sharing>

## Demo Goal

BigBrotr is a Nostr Web of Trust observatory. The demo shows the full
NIP-85-oriented pipeline:

```text
relay discovery and validation
-> bounded event archival
-> current-state and NIP-85 fact refresh
-> PageRank-style rank snapshots
-> NIP-85 trusted assertion publishing
-> REST/API, DVM, Prometheus, and Grafana access
```

The demo uses `deployments/testbrotr`, a small full-stack Docker Compose
deployment created for hackathon evaluation and local smoke testing.

## What To Say

Use this as the narration if presenting the walkthrough live:

```text
BigBrotr is an open-source Nostr network observatory and Web of Trust data
foundation. It discovers relays, validates relay health, archives Web of Trust
signals from Nostr events, derives trust facts, computes rank snapshots, and
publishes NIP-85 trusted assertions.

The important part is that trust computation on Nostr is not only an algorithm
problem. The hard prerequisite is a durable, queryable, cross-relay data
substrate. BigBrotr provides that substrate and keeps the ranking and assertion
layers reproducible.

This demo uses TestBrotr. It is intentionally bounded: the synchronizer does not
try to archive all of Nostr. It archives only the event kinds needed to exercise
the trust pipeline. API, DVM, refresher, ranker, and assertor then operate on the
database state produced by that archive.
```

## Quick Start

Clone the submitted branch:

```bash
git clone -b hackathon/wotathon-submission https://github.com/BigBrotr/bigbrotr.git
cd bigbrotr/deployments/testbrotr
```

Create the local environment file:

```bash
cp .env.example .env
```

Fill every required password in `.env`. For local testing, these commands are a
quick way to generate values:

```bash
openssl rand -base64 32
openssl rand -hex 32
```

Required fields:

```text
DB_ADMIN_PASSWORD
DB_WRITER_PASSWORD
DB_REFRESHER_PASSWORD
DB_READER_PASSWORD
DB_RANKER_PASSWORD
GRAFANA_PASSWORD
```

Optional, but recommended for stable Nostr identities:

```text
NOSTR_PRIVATE_KEY_MONITOR
NOSTR_PRIVATE_KEY_SYNCHRONIZER
NOSTR_PRIVATE_KEY_DVM
NOSTR_PRIVATE_KEY_ASSERTOR
```

Start the stack:

```bash
docker compose --env-file .env up -d --build
```

Check that services are up:

```bash
docker compose --env-file .env ps
```

The main local endpoints are:

```text
REST API:     http://127.0.0.1:8082
Grafana:      http://127.0.0.1:3002
Prometheus:   http://127.0.0.1:9092
Alertmanager: http://127.0.0.1:9095
PostgreSQL:   127.0.0.1:5434
PGBouncer:    127.0.0.1:6434
```

## Demo Step 1: Show The Full Stack

Run:

```bash
docker compose --env-file .env ps
```

What to point out:

- `seeder`, `finder`, `validator`, `monitor`, and `synchronizer` cover relay
  discovery, validation, monitoring, and archival ingestion.
- `refresher` derives current-state, analytics, and NIP-85 fact tables.
- `ranker` computes rank snapshots with a private DuckDB working store.
- `assertor` publishes signed NIP-85 trusted assertions.
- `api` and `dvm` expose the resulting data.
- `postgres`, `pgbouncer`, `prometheus`, `grafana`, and `alertmanager` provide
  storage, pooling, and observability.

## Demo Step 2: Show The Bounded Archive Filter

Open:

```text
deployments/testbrotr/config/services/synchronizer.yaml
```

Point to the `processing.filters` section. The TestBrotr filter archives a
small WoT-relevant slice:

```text
0, 1, 3, 6, 7, 1984, 1985, 9735, 10000, 10002, 30023
```

What to say:

```text
This filter controls only what the synchronizer archives. It is not an assertor
filter. API and DVM expose what is present in PostgreSQL. Refresher and ranker
derive facts and ranks from the archive. Assertor publishes its own NIP-85
30382-30385 outputs, so those output kinds do not need to be archived as inputs
for this bounded demo.
```

## Demo Step 3: Run A Deterministic One-Shot Pipeline

The services also run periodically, but one-shot commands make the demo easier
to follow.

Run the relay monitor:

```bash
docker compose --env-file .env run -T --rm --no-deps monitor bigbrotr --once monitor
```

Run the bounded synchronizer:

```bash
docker compose --env-file .env run -T --rm --no-deps synchronizer bigbrotr --once synchronizer
```

Run the derived-table refresher:

```bash
docker compose --env-file .env run -T --rm --no-deps refresher bigbrotr --once refresher
```

Run the ranker:

```bash
docker compose --env-file .env run -T --rm --no-deps ranker bigbrotr --once ranker
```

Run the assertor:

```bash
docker compose --env-file .env run -T --rm --no-deps assertor bigbrotr --once assertor
```

Expected shape of the logs:

```text
monitor:      relays_available total > 0
synchronizer: sync_completed events_synced > 0
refresher:    refresh_completed refreshed=21 failed=0
ranker:       ranker_cycle_completed ... pubkey_ranks_written > 0
assertor:     cycle_completed ... failed=0
```

The exact row counts depend on relay availability and current network data.
In a local TestBrotr run during submission preparation, the bounded sync
archived thousands of events, the refresher completed all 21 targets, the ranker
exported pubkey and event ranks, and the assertor published bounded 30382 user
assertions plus the provider profile.

## Demo Step 4: Show The API

Health check:

```bash
curl -fsS http://127.0.0.1:8082/health
```

Schema introspection:

```bash
curl -fsS http://127.0.0.1:8082/v1/schema | head -c 1200
```

Relay data:

```bash
curl -fsS 'http://127.0.0.1:8082/v1/relay?limit=3'
```

What to say:

```text
The REST API provides read-only query access to the archive and derived tables.
Applications do not need to rebuild relay crawling and archival infrastructure
just to consume trust facts.
```

## Demo Step 5: Show Database Evidence

Event kinds archived:

```bash
docker compose --env-file .env exec -T postgres psql -U admin -d testbrotr -c "
SELECT kind, count(*)
FROM event
GROUP BY kind
ORDER BY kind;
"
```

Core pipeline counts:

```bash
docker compose --env-file .env exec -T postgres psql -U admin -d testbrotr -c "
SELECT 'relay' AS table_name, count(*) FROM relay
UNION ALL SELECT 'event', count(*) FROM event
UNION ALL SELECT 'event_relay', count(*) FROM event_relay
UNION ALL SELECT 'events_replaceable_current', count(*) FROM events_replaceable_current
UNION ALL SELECT 'events_addressable_current', count(*) FROM events_addressable_current
UNION ALL SELECT 'contact_lists_current', count(*) FROM contact_lists_current
UNION ALL SELECT 'contact_list_edges_current', count(*) FROM contact_list_edges_current
UNION ALL SELECT 'nip85_pubkey_stats', count(*) FROM nip85_pubkey_stats
UNION ALL SELECT 'nip85_event_stats', count(*) FROM nip85_event_stats
UNION ALL SELECT 'nip85_addressable_stats', count(*) FROM nip85_addressable_stats
UNION ALL SELECT 'nip85_identifier_stats', count(*) FROM nip85_identifier_stats
UNION ALL SELECT 'nip85_pubkey_ranks', count(*) FROM nip85_pubkey_ranks
UNION ALL SELECT 'nip85_event_ranks', count(*) FROM nip85_event_ranks
UNION ALL SELECT 'nip85_addressable_ranks', count(*) FROM nip85_addressable_ranks
UNION ALL SELECT 'nip85_identifier_ranks', count(*) FROM nip85_identifier_ranks;
"
```

Assertor publication checkpoints:

```bash
docker compose --env-file .env exec -T postgres psql -U admin -d testbrotr -c "
SELECT split_part(state_key, ':', 2) AS kind, count(*)
FROM service_state
WHERE service_name = 'assertor'
GROUP BY 1
ORDER BY 1;
"
```

What to say:

```text
These tables show the transition from raw archived events into current-state
facts, then NIP-85 facts, then rank snapshots, then assertor checkpoints for
published signed assertions.
```

## Demo Step 6: Show Pipeline Logs

Run:

```bash
docker compose --env-file .env logs --tail=120 refresher ranker assertor
```

Look for:

```text
refresher refresh_completed refreshed=21 failed=0
ranker ranker_cycle_completed
assertor cycle_completed
```

What to say:

```text
This is the end-to-end trust pipeline. Refresher derives facts, ranker computes
rank snapshots, and assertor publishes NIP-85 assertions from those ranks.
```

## Demo Step 7: Show Grafana And Prometheus

Open Grafana:

```text
http://127.0.0.1:3002
```

Use the credentials from `.env`:

```text
user: admin
password: GRAFANA_PASSWORD
```

Useful dashboards:

```text
TestBrotr Services
Refresher
Ranker
Assertor
Synchronizer
API
DVM
```

Open Prometheus:

```text
http://127.0.0.1:9092
```

Example Prometheus checks:

```text
up
service_info
service_gauge
```

What to say:

```text
BigBrotr is not just a script. It is operational infrastructure: each service
has metrics, dashboards, logs, resource limits, and restart behavior.
```

## Demo Step 8: Show DVM Surface

The DVM is a NIP-90 read-only query surface for the same database-backed data.
For a short demo, show that it is running and exposing metrics:

```bash
curl -fsS http://127.0.0.1:9107/metrics | head -n 20
```

What to say:

```text
The same data can be consumed through REST or over Nostr through a DVM. This is
useful for clients and agents that prefer Nostr-native query workflows.
```

## Troubleshooting

If the stack is already running and you changed resource limits:

```bash
docker compose --env-file .env up -d postgres grafana
```

If a one-shot command seems stuck on a terminal allocation, use `-T` as shown in
this file.

If `finder` logs a `nostr.watch` HTTP error, that is an external source issue;
it does not mean the internal pipeline failed.

If the first `synchronizer` run sees zero relays, run `validator` and `monitor`
once, then run `synchronizer` again:

```bash
docker compose --env-file .env run -T --rm --no-deps validator bigbrotr --once validator
docker compose --env-file .env run -T --rm --no-deps monitor bigbrotr --once monitor
docker compose --env-file .env run -T --rm --no-deps synchronizer bigbrotr --once synchronizer
```

To reset only the local TestBrotr sandbox:

```bash
docker compose --env-file .env down -v --remove-orphans
rm -rf data/postgres data/ranker
```

The reset command above deletes local TestBrotr runtime data only. It does not
touch source files.

## Submission Summary

The submitted branch is:

```text
hackathon/wotathon-submission
```

The demo deployment is:

```text
deployments/testbrotr
```

The branch intentionally includes `deployments/testbrotr` but excludes local
runtime artifacts:

```text
.env
data/postgres/
data/ranker/
```

This keeps the demo reproducible without committing local secrets, PostgreSQL
data, or DuckDB ranker state.
