# BigBrotr Implementation Template

This template provides the **mandatory** components needed to create a custom BigBrotr implementation.
Use it as a starting point and customize according to your requirements.

## Quick Start

```bash
# 1. Copy the template
cp -r deployments/_template deployments/myimpl
cd deployments/myimpl

# 2. Customize names (replace 'myimpl' with your implementation name)
#    - Update docker-compose.yaml container names and network
#    - Update config/brotr.yaml database name

# 3. Configure environment
cp .env.example .env
# Edit .env and set DB_PASSWORD (required)

# 4. Customize schema (optional)
#    - Edit postgres/init/02_tables.sql to adjust event table columns
#    - Edit postgres/init/03_functions_crud.sql to match event_insert()

# 5. Start services
docker compose up -d

# 6. Verify
docker compose exec postgres psql -U admin -d myimpl -c "\dt"
```

## Directory Structure

```
deployments/myimpl/
├── README.md                         # This file
├── .env.example                      # Environment template
├── docker-compose.yaml               # Container orchestration
├── postgres/
│   ├── postgresql.conf               # PostgreSQL tuning
│   └── init/                         # SQL initialization (run in order)
│       ├── 00_extensions.sql         # Required extensions
│       ├── 01_functions_utility.sql  # Utility functions
│       ├── 02_tables.sql             # Core tables (CUSTOMIZABLE)
│       ├── 03_functions_crud.sql     # CRUD functions (CUSTOMIZABLE)
│       ├── 04_functions_cleanup.sql  # Cleanup functions
│       ├── 05_indexes.sql            # Performance indexes
│       └── 99_verify.sql             # Verification script
├── config/
│   ├── brotr.yaml                    # Database connection config
│   ├── seeder.yaml
│   ├── finder.yaml
│   ├── validator.yaml
│   ├── monitor.yaml
│   └── synchronizer.yaml
├── monitoring/
│   ├── prometheus/
│   │   └── prometheus.yaml           # Metrics scrape config
│   └── grafana/
│       └── provisioning/             # Dashboards and datasources
└── static/
    └── seed_relays.txt               # Initial relay URLs
```

## What's Mandatory vs Optional

### Mandatory (included in template)

| Component | Details |
|-----------|---------|
| Extensions | `btree_gin` |
| Tables | `relay`, `event`, `event_relay`, `metadata`, `relay_metadata`, `service_state` |
| CRUD Functions | `relay_insert`, `event_insert`, `metadata_insert`, `event_relay_insert`, `relay_metadata_insert`, `event_relay_insert_cascade`, `relay_metadata_insert_cascade`, `service_state_upsert`, `service_state_get`, `service_state_delete` |
| Cleanup Functions | `orphan_metadata_delete`, `orphan_event_delete` |
| Indexes | Basic table indexes for performance |

### Optional (NOT included -- add from bigbrotr if needed)

| Component | Files in bigbrotr |
|-----------|-------------------|
| Views | `05_views.sql` |
| Materialized Views | `06_materialized_views.sql` |
| Refresh Functions | `07_functions_refresh.sql` |
| Materialized View Indexes | Additional indexes in `08_indexes.sql` |

## Customization Guide

### Event Table

The `event` table only requires `id BYTEA PRIMARY KEY`. All other columns are optional.

```sql
-- Minimal (just tracking event IDs per relay):
CREATE TABLE event (id BYTEA PRIMARY KEY);

-- Lightweight (metadata + tag filtering, ~60% disk savings):
CREATE TABLE event (
    id BYTEA PRIMARY KEY,
    pubkey BYTEA NOT NULL,
    created_at BIGINT NOT NULL,
    kind INTEGER NOT NULL,
    tagvalues TEXT[]
);

-- Full storage (complete events, used by default):
CREATE TABLE event (
    id BYTEA PRIMARY KEY,
    pubkey BYTEA NOT NULL,
    created_at BIGINT NOT NULL,
    kind INTEGER NOT NULL,
    tags JSONB NOT NULL,
    tagvalues TEXT[] GENERATED ALWAYS AS (tags_to_tagvalues(tags)) STORED,
    content TEXT NOT NULL,
    sig BYTEA NOT NULL
);
```

When customizing, update `03_functions_crud.sql`:

- Function signatures are **FIXED** (`src/bigbrotr/core/brotr.py` calls with all parameters)
- Only modify the INSERT statement inside `event_insert()`
- All parameters must be accepted even if not stored

### Port Configuration

Avoid port conflicts with other implementations:

```yaml
# For a second implementation, use different ports:
ports:
  - "127.0.0.1:5433:5432"  # PostgreSQL
  - "127.0.0.1:6433:5432"  # PGBouncer
  - "127.0.0.1:9051:9050"  # Tor
  - "127.0.0.1:9091:9090"  # Prometheus
  - "127.0.0.1:3001:3000"  # Grafana
```

Metrics ports can be configured via environment variables in `.env`:

```bash
# Service metrics ports (Prometheus scrape targets)
FINDER_METRICS_PORT=9001       # Default: 8001
VALIDATOR_METRICS_PORT=9002    # Default: 8002
MONITOR_METRICS_PORT=9003      # Default: 8003
SYNCHRONIZER_METRICS_PORT=9004 # Default: 8004
```

**Port allocation by implementation:**

| Implementation | PostgreSQL | PGBouncer | Metrics | Prometheus | Grafana |
|---------------|------------|-----------|---------|------------|---------|
| bigbrotr      | 5432       | 6432      | 8001-04 | 9090       | 3000    |
| lilbrotr      | 5433       | 6433      | 9001-04 | 9091       | 3001    |
| myimpl        | 5434       | 6434      | 7001-04 | 9092       | 3002    |

## Required SQL Functions

These functions are called by `src/bigbrotr/core/brotr.py` and MUST exist:

### Base Functions

| Function | Purpose |
|----------|---------|
| `relay_insert(TEXT[], TEXT[], BIGINT[])` | Bulk insert relays |
| `event_insert(BYTEA[], BYTEA[], BIGINT[], INTEGER[], JSONB[], TEXT[], BYTEA[])` | Bulk insert events |
| `metadata_insert(BYTEA[], JSONB[])` | Bulk insert metadata |
| `event_relay_insert(BYTEA[], TEXT[], BIGINT[])` | Insert event-relay junctions |
| `relay_metadata_insert(TEXT[], BYTEA[], TEXT[], BIGINT[])` | Insert relay-metadata junctions |
| `service_state_upsert(TEXT[], TEXT[], TEXT[], JSONB[], BIGINT[])` | Upsert service state |
| `service_state_get(TEXT, TEXT, TEXT)` | Get service state (3rd param optional) |
| `service_state_delete(TEXT[], TEXT[], TEXT[])` | Delete service state |

### Cascade Functions

| Function | Purpose |
|----------|---------|
| `event_relay_insert_cascade(...)` | Atomic: relay + event + event_relay |
| `relay_metadata_insert_cascade(...)` | Atomic: relay + metadata + relay_metadata |

### Cleanup Functions

| Function | Purpose |
|----------|---------|
| `orphan_metadata_delete(INTEGER)` | Remove unreferenced metadata (batched) |
| `orphan_event_delete(INTEGER)` | Remove events without relay associations (batched) |
| `relay_metadata_delete_expired(INTEGER, INTEGER)` | Remove old metadata snapshots (batched) |

## Services

| Service | Type | Purpose |
|---------|------|---------|
| Seeder | One-shot | Load initial relay URLs |
| Finder | Continuous | Discover new relays |
| Validator | Continuous | Validate relay candidates |
| Monitor | Continuous | Check relay health, publish NIP-66 events |
| Synchronizer | Continuous | Fetch and archive events |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DB_PASSWORD` | Yes | PostgreSQL password |
| `PRIVATE_KEY` | No | Nostr private key (hex, 64 chars) |
| `GRAFANA_PASSWORD` | No | Grafana admin password (default: admin) |
| `FINDER_METRICS_PORT` | No | Finder Prometheus port (default: 8001) |
| `VALIDATOR_METRICS_PORT` | No | Validator Prometheus port (default: 8002) |
| `MONITOR_METRICS_PORT` | No | Monitor Prometheus port (default: 8003) |
| `SYNCHRONIZER_METRICS_PORT` | No | Synchronizer Prometheus port (default: 8004) |

## Troubleshooting

```bash
# Check logs
docker compose logs -f

# Connect to database
docker compose exec postgres psql -U admin -d myimpl

# Reset database
docker compose down && rm -rf data/postgres && docker compose up -d
```
