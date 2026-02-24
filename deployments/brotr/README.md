# Brotr Reference Implementation

This is the **reference implementation** with the minimal base schema shared by all
BigBrotr deployments. Use it as a starting point for creating custom deployments.

## Quick Start

```bash
# 1. Copy the reference implementation
cp -r deployments/brotr deployments/myimpl
cd deployments/myimpl

# 2. Customize names (replace 'brotr' with your implementation name)
#    - Update docker-compose.yaml container names and networks
#    - Update config/brotr.yaml database name
#    - Update config/services/*.yaml pool user

# 3. Configure environment
cp .env.example .env
# Edit .env and set DB_ADMIN_PASSWORD, DB_WRITER_PASSWORD, DB_READER_PASSWORD (required)

# 4. Customize schema (optional)
#    - Create Jinja2 override templates in tools/templates/sql/myimpl/
#    - Add "myimpl": {} to OVERRIDES in tools/generate_sql.py
#    - Run: make sql-generate

# 5. Start services
docker compose up -d

# 6. Verify
docker compose exec postgres psql -U admin -d myimpl -c "\dt"
```

## Directory Structure

```
deployments/brotr/
+-- README.md                         # This file
+-- .env.example                      # Environment template
+-- docker-compose.yaml               # Container orchestration
+-- postgres/
|   +-- postgresql.conf               # PostgreSQL tuning
|   +-- init/                         # SQL initialization (run in order)
|       +-- 00_extensions.sql         # Required extensions
|       +-- 01_functions_utility.sql  # Utility functions
|       +-- 02_tables.sql             # Core tables (CUSTOMIZABLE)
|       +-- 03_functions_crud.sql     # CRUD functions (CUSTOMIZABLE)
|       +-- 04_functions_cleanup.sql  # Cleanup functions
|       +-- 05_views.sql              # Views (extension point)
|       +-- 06_materialized_views.sql # relay_metadata_latest
|       +-- 07_functions_refresh.sql  # relay_metadata_latest_refresh()
|       +-- 08_indexes.sql            # Performance indexes
|       +-- 99_verify.sql             # Verification script
+-- config/
|   +-- brotr.yaml                    # Database connection config
|   +-- services/
|       +-- seeder.yaml
|       +-- finder.yaml
|       +-- validator.yaml
|       +-- monitor.yaml
|       +-- synchronizer.yaml
+-- pgbouncer/                        # Connection pooler config
+-- monitoring/
|   +-- prometheus/                   # Metrics scrape config + alert rules
|   +-- postgres-exporter/            # Database metrics queries
|   +-- grafana/                      # Dashboards and datasources
|   +-- alertmanager/                 # Alert routing
+-- static/
    +-- seed_relays.txt               # Initial relay URLs
```

## Base Schema

All deployments share this minimal schema:

| Component | Details |
|-----------|---------|
| Extensions | `btree_gin`, `pg_stat_statements` |
| Tables | `relay`, `event`, `event_relay`, `metadata`, `relay_metadata`, `service_state` |
| CRUD Functions | `relay_insert`, `event_insert`, `metadata_insert`, `event_relay_insert`, `relay_metadata_insert`, `event_relay_insert_cascade`, `relay_metadata_insert_cascade`, `service_state_upsert`, `service_state_get`, `service_state_delete` |
| Cleanup Functions | `orphan_metadata_delete`, `orphan_event_delete` |
| Materialized Views | `relay_metadata_latest` |
| Refresh Functions | `relay_metadata_latest_refresh` |
| Indexes | Table indexes + `relay_metadata_latest` unique index |

## Extending with Jinja2

Deployments extend the base by overriding Jinja2 blocks in `tools/templates/sql/`:

| Extension Point | Purpose |
|----------------|---------|
| `events_table` | Customize event table columns |
| `events_insert_body` | Match event_insert() to your schema |
| `extra_cleanup_functions` | Add cleanup functions (e.g., retention) |
| `views` | Add regular SQL views |
| `extra_materialized_views` | Add materialized views |
| `extra_refresh_functions` | Add refresh functions for matviews |
| `extra_matview_indexes` | Add indexes for matviews |
| `verify_body` | Customize verification output |

See `tools/templates/sql/bigbrotr/` for a complete example of extending the base.

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

Avoid port conflicts with other deployments:

| Deployment | PostgreSQL | PGBouncer | Metrics | Prometheus | Grafana |
|------------|------------|-----------|---------|------------|---------|
| bigbrotr   | 5432       | 6432      | 8001-04 | 9090       | 3000    |
| lilbrotr   | 5433       | 6433      | 9001-04 | 9091       | 3001    |
| myimpl     | 5434       | 6434      | 7001-04 | 9092       | 3002    |

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
| `DB_ADMIN_PASSWORD` | Yes | PostgreSQL admin password |
| `DB_WRITER_PASSWORD` | Yes | Writer role password (pipeline services) |
| `DB_READER_PASSWORD` | Yes | Reader role password (read-only services) |
| `PRIVATE_KEY` | No | Nostr private key (hex, 64 chars) |
| `GRAFANA_PASSWORD` | No | Grafana admin password (default: admin) |

## Troubleshooting

```bash
# Check logs
docker compose logs -f

# Connect to database
docker compose exec postgres psql -U admin -d brotr

# Reset database
docker compose down && rm -rf data/postgres && docker compose up -d
```
