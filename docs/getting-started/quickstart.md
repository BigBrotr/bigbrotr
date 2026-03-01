# Quick Start

A step-by-step tutorial that walks you through BigBrotr's core services, from seeding initial relay URLs to viewing data in the database.

---

## Prerequisites

Before starting, make sure you have:

- [x] Python 3.11+ installed
- [x] BigBrotr installed with `uv sync --group dev` (see [Installation](installation.md))
- [x] PostgreSQL and PGBouncer running (Docker or local)

!!! tip "Quickest infrastructure setup"
    ```bash
    docker compose -f deployments/bigbrotr/docker-compose.yaml up -d postgres pgbouncer
    ```

## Step 1: Clone and Install

If you have not already done so during installation:

```bash
git clone https://github.com/BigBrotr/bigbrotr.git
cd bigbrotr
curl -LsSf https://astral.sh/uv/install.sh | sh  # install uv (one-time)
uv sync --group dev
```

## Step 2: Start Infrastructure

Start only the database containers -- you will run the application services manually:

```bash
docker compose -f deployments/bigbrotr/docker-compose.yaml up -d postgres pgbouncer
```

Wait for PostgreSQL to become healthy:

```bash
docker compose -f deployments/bigbrotr/docker-compose.yaml ps
```

You should see both `postgres` and `pgbouncer` with status `healthy`.

!!! note
    The PostgreSQL init scripts in `deployments/bigbrotr/postgres/init/` run
    automatically on first start. They create all tables, stored functions,
    indexes, and materialized views.

## Step 3: Set Environment Variables

Services need the database password to connect. Each service uses its own role
(configured via pool overrides in the service YAML). Set the writer password:

```bash
export DB_WRITER_PASSWORD=your_writer_password
```

## Step 4: Run the Seeder

The Seeder is a one-shot service that loads initial relay URLs from a seed file
into the `service_state` table as candidates for the Finder:

```bash
cd deployments/bigbrotr
python -m bigbrotr seeder --once
```

You will see structured log output indicating how many seed URLs were loaded:

```text
info seeder cycle_started
info seeder cycle_completed relays_loaded=150 duration=0.3
```

!!! info
    The seed file is located at `deployments/bigbrotr/static/seed_relays.txt`.
    Each line is a `wss://` or `ws://` relay URL.

## Step 5: Run the Finder

The Finder discovers new relay URLs by scanning stored events (NIP-65 relay lists,
kind 2, kind 3) and querying external APIs. Run a single cycle:

```bash
python -m bigbrotr finder --once
```

Expected output:

```text
info finder cycle_started
info finder api_scan_completed source=api candidates=85
info finder event_scan_completed source=events candidates=210
info finder cycle_completed total_candidates=295 duration=12.4
```

The Finder writes discovered URLs as candidates in `service_state` for the Validator.

!!! tip
    Add `--log-level DEBUG` to any command for verbose output:
    ```bash
    python -m bigbrotr finder --once --log-level DEBUG
    ```

## Step 6: Run the Validator

The Validator tests each candidate URL by opening a WebSocket connection to confirm
it is a live Nostr relay. Valid relays are promoted to the `relay` table:

```bash
python -m bigbrotr validator --once
```

Expected output:

```text
info validator cycle_started candidates=295
info validator batch_completed tested=295 valid=180 invalid=115 duration=45.2
info validator cycle_completed promoted=180 duration=45.8
```

!!! note
    Validation is network-bound and may take a minute or more depending on the
    number of candidates and network conditions. The Validator uses per-network
    concurrency limits defined in its configuration file.

## Step 7: Check the Database

After running the first three services, your database now contains real data.
Connect with `psql` to inspect:

```bash
docker compose -f deployments/bigbrotr/docker-compose.yaml exec postgres \
    psql -U admin -d bigbrotr
```

Useful queries:

```sql
-- Count validated relays
SELECT count(*) FROM relay;

-- View relays by network type
SELECT network, count(*) FROM relay GROUP BY network ORDER BY count DESC;

-- Check service state entries
SELECT key, state_type, count(*) FROM service_state GROUP BY key, state_type;
```

## What Just Happened?

You ran three of BigBrotr's eight independent services:

--8<-- "docs/_snippets/pipeline.md"

1. **Seeder** loaded seed URLs from a text file into the database as candidates
2. **Finder** discovered additional relay URLs from events and external APIs
3. **Validator** tested every candidate via WebSocket and promoted live relays

The remaining five services handle monitoring, event archiving, analytics, and data access:

- **Monitor** performs NIP-11 and NIP-66 health checks on validated relays and
  publishes results as kind 10166/30166 Nostr events (requires `NOSTR_PRIVATE_KEY`)
- **Synchronizer** connects to validated relays, subscribes to events, and
  archives them with cursor-based pagination
- **Refresher** refreshes materialized views that power analytics queries
- **Api** exposes the database as a read-only REST API with paginated endpoints
- **Dvm** serves database queries over the Nostr protocol as a NIP-90 Data Vending Machine

## Running All Services

To run all services continuously (not just `--once`), each service enters an
infinite loop with configurable intervals between cycles:

```bash
# In separate terminals (from deployments/bigbrotr/):
python -m bigbrotr finder
python -m bigbrotr validator
python -m bigbrotr monitor       # requires NOSTR_PRIVATE_KEY env var
python -m bigbrotr synchronizer
python -m bigbrotr refresher
python -m bigbrotr api
python -m bigbrotr dvm           # requires NOSTR_PRIVATE_KEY env var
```

!!! warning
    The Monitor requires a `NOSTR_PRIVATE_KEY` environment variable (hex format, 64
    characters) to sign and publish Nostr events. Generate one with:
    ```bash
    export NOSTR_PRIVATE_KEY=$(openssl rand -hex 32)
    ```

## Next Steps

You have successfully run BigBrotr's core services manually. To deploy the full
stack with monitoring, Grafana dashboards, and automatic restarts:

- [First Deployment](first-deployment.md) -- Full Docker Compose deployment
- [Configuration Reference](../user-guide/configuration.md) -- Tune intervals, timeouts, and networks
- [Architecture](../user-guide/architecture.md) -- Understand the system design

---

## Related Documentation

- [Installation](installation.md) -- Install paths and system requirements
- [First Deployment](first-deployment.md) -- Full stack Docker deployment
- [Configuration Reference](../user-guide/configuration.md) -- YAML configuration for all services
- [Database](../user-guide/database.md) -- Schema, stored functions, and materialized views
