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
#    - Edit postgres/init/02_tables.sql to remove columns
#    - Edit postgres/init/03_functions_crud.sql to match

# 5. Start services
docker-compose up -d

# 6. Verify
docker-compose exec postgres psql -U admin -d myimpl -c "\dt"
```

## Directory Structure

```
deployments/myimpl/
├── README.md                         # This file
├── .env.example                      # Environment template
├── docker-compose.yaml               # Container orchestration
├── Dockerfile                        # Application image build
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

| Component | Files |
|-----------|-------|
| Extensions | `btree_gin` |
| Tables | `relays`, `events`, `events_relays`, `metadata`, `relay_metadata`, `service_data` |
| CRUD Functions | `*_insert`, `*_insert_cascade`, `service_data_*` |
| Cleanup Functions | `orphan_*_delete` |
| Indexes | Basic table indexes for performance |

### Optional (NOT included - add from bigbrotr if needed)

| Component | Files in bigbrotr |
|-----------|-------------------|
| Materialized Views | `06_materialized_views.sql` |
| Refresh Functions | `07_functions_refresh.sql` |
| Materialized View Indexes | Additional indexes in `08_indexes.sql` |

## Customization Guide

### Events Table

The `events` table only requires `id BYTEA PRIMARY KEY`. All other columns are optional.

```sql
-- Minimal (just tracking event IDs per relay):
CREATE TABLE events (id BYTEA PRIMARY KEY);

-- Lightweight (metadata + tag filtering):
CREATE TABLE events (
    id BYTEA PRIMARY KEY,
    pubkey BYTEA NOT NULL,
    created_at BIGINT NOT NULL,
    kind INTEGER NOT NULL,
    tagvalues TEXT[]
);

-- Full storage (complete events):
CREATE TABLE events (
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
- Function signatures are **FIXED** (brotr.py calls with all parameters)
- Only modify the INSERT statements inside the function body

### Port Configuration

Avoid port conflicts with other implementations:

```yaml
# For second implementation, use different ports:
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

These functions are called by `src/core/brotr.py` and MUST exist:

### Base Functions
| Function | Purpose |
|----------|---------|
| `relays_insert(TEXT[], TEXT[], BIGINT[])` | Bulk insert relays |
| `events_insert(...)` | Bulk insert events |
| `metadata_insert(JSONB[])` | Bulk insert metadata |
| `events_relays_insert(BYTEA[], TEXT[], BIGINT[])` | Insert junctions |
| `relay_metadata_insert(TEXT[], JSONB[], TEXT[], BIGINT[])` | Insert junctions |
| `service_data_upsert(...)` | Upsert service data |
| `service_data_get(...)` | Get service data |
| `service_data_delete(...)` | Delete service data |

### Cascade Functions
| Function | Purpose |
|----------|---------|
| `events_relays_insert_cascade(...)` | Atomic: relays + events + junctions |
| `relay_metadata_insert_cascade(...)` | Atomic: relays + metadata + junctions |

### Cleanup Functions
| Function | Purpose |
|----------|---------|
| `orphan_metadata_delete()` | Remove unreferenced metadata |
| `orphan_events_delete()` | Remove events without relays |

## Services

| Service | Type | Purpose |
|---------|------|---------|
| Seeder | One-shot | Load initial relay URLs |
| Finder | Continuous | Discover new relays |
| Validator | Continuous | Validate candidates |
| Monitor | Continuous | Check relay health |
| Synchronizer | Continuous | Fetch events |

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
docker-compose logs -f

# Connect to database
docker-compose exec postgres psql -U admin -d myimpl

# Reset database
docker-compose down && rm -rf data/postgres && docker-compose up -d
```
