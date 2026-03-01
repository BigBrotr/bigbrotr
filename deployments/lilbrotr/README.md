# LilBrotr - Lightweight BigBrotr Implementation

LilBrotr is a **lightweight** BigBrotr implementation optimized for reduced disk usage and resource consumption.
It has all 8 event columns but keeps `tags`, `content`, and `sig` as nullable columns that are always NULL (~60% disk savings).

## Key Differences from BigBrotr

| Feature | BigBrotr | LilBrotr |
|---------|----------|----------|
| Event storage | Full (all columns NOT NULL) | All 8 columns (tags/content/sig nullable, always NULL) |
| Disk usage | ~100% | ~40% |
| Tor support | Enabled by default | Disabled by default |
| I2P/Lokinet | Available | Disabled |
| Concurrency | High | Reduced |
| Event scanning | Enabled | Disabled (tags/content/sig are NULL) |

## Quick Start

```bash
cd deployments/lilbrotr

# 1. Configure environment
cp .env.example .env
nano .env  # Set DB_ADMIN_PASSWORD, DB_WRITER_PASSWORD, DB_READER_PASSWORD and PRIVATE_KEY

# 2. Start services
docker-compose up -d

# 3. Verify
docker-compose ps
docker-compose exec postgres psql -U admin -d lilbrotr -c "\dt"

# 4. Check logs
docker-compose logs -f
```

## Directory Structure

```
deployments/lilbrotr/
├── README.md                         # This file
├── .env.example                      # Environment template
├── docker-compose.yaml               # Container orchestration
├── Dockerfile                        # Application image build
├── postgres/
│   ├── postgresql.conf               # PostgreSQL tuning
│   └── init/                         # SQL initialization (10 files)
│       ├── 00_extensions.sql
│       ├── 01_functions_utility.sql
│       ├── 02_tables.sql             # Lightweight events table
│       ├── 03_functions_crud.sql     # Adapted CRUD functions
│       ├── 04_functions_cleanup.sql
│       ├── 05_views.sql
│       ├── 06_materialized_views.sql # relay_metadata_latest
│       ├── 07_functions_refresh.sql
│       ├── 08_indexes.sql
│       └── 99_verify.sql
├── config/
│   ├── brotr.yaml                    # Database connection config
│   ├── seeder.yaml                   # Seed relay URLs
│   ├── finder.yaml                   # Discover relays (API only)
│   ├── validator.yaml                # Validate candidates
│   ├── monitor.yaml                  # Health checks
│   └── synchronizer.yaml             # Sync events
├── monitoring/
│   ├── prometheus/
│   │   └── prometheus.yaml           # Metrics scrape config
│   └── grafana/
│       └── provisioning/             # Dashboards and datasources
└── static/
    ├── seed_relays.txt               # Initial relay URLs
    └── GeoLite2-City.mmdb            # Geolocation database (optional)
```

## Port Configuration

LilBrotr uses different ports from BigBrotr to allow running both simultaneously:

| Service | BigBrotr | LilBrotr |
|---------|----------|----------|
| PostgreSQL | 5432 | 5433 |
| PGBouncer | 6432 | 6433 |
| Finder metrics | 8001 | 9001 |
| Validator metrics | 8002 | 9002 |
| Monitor metrics | 8003 | 9003 |
| Synchronizer metrics | 8004 | 9004 |
| Refresher metrics | 8005 | 9005 |
| Api HTTP | 8080 | 8081 |
| Api metrics | 8006 | 9006 |
| Dvm metrics | 8007 | 9007 |
| Prometheus | 9090 | 9091 |
| Grafana | 3000 | 3001 |

Metrics ports can be overridden in `.env`:

```bash
FINDER_METRICS_PORT=9001
VALIDATOR_METRICS_PORT=9002
MONITOR_METRICS_PORT=9003
SYNCHRONIZER_METRICS_PORT=9004
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DB_ADMIN_PASSWORD` | Yes | PostgreSQL admin password |
| `DB_WRITER_PASSWORD` | Yes | Writer role password (services) |
| `DB_READER_PASSWORD` | Yes | Reader role password (read-only services) |
| `PRIVATE_KEY` | Yes | Nostr private key (hex, 64 chars) |
| `GRAFANA_PASSWORD` | No | Grafana admin password (default: admin) |
| `FINDER_METRICS_PORT` | No | Finder Prometheus port (default: 9001) |
| `VALIDATOR_METRICS_PORT` | No | Validator Prometheus port (default: 9002) |
| `MONITOR_METRICS_PORT` | No | Monitor Prometheus port (default: 9003) |
| `SYNCHRONIZER_METRICS_PORT` | No | Synchronizer Prometheus port (default: 9004) |

## Services Configuration

### Seeder
- One-shot service that loads initial relays from `static/seed_relays.txt`
- Runs once at startup, then exits

### Finder
- Discovers relay URLs from external APIs (nostr.watch)
- Event scanning **disabled** (tags/content are NULL in database)
- Runs every hour

### Validator
- Validates candidate relay URLs (clearnet only by default)
- Tor/I2P/Lokinet disabled by default
- Runs every 8 hours

### Monitor
- Performs health checks on validated relays
- Publishes NIP-66 events
- Runs every hour

### Synchronizer
- Fetches events from readable relays
- Stores lightweight event data (tags/content/sig are NULL)
- Runs every 15 minutes

## Enabling Tor Support

To enable Tor relay support:

1. **Uncomment Tor service** in `docker-compose.yaml`:
   ```yaml
   tor:
     image: osminogin/tor-simple:0.4.8.10
     container_name: lilbrotr-tor
     # ... rest of config
   ```

2. **Uncomment Tor dependencies** in validator/monitor/synchronizer services:
   ```yaml
   depends_on:
     tor:
       condition: service_healthy
   ```

3. **Enable Tor in service configs** (`config/*.yaml`):
   ```yaml
   networks:
     tor:
       enabled: true
   ```

4. **Restart services**:
   ```bash
   docker-compose down && docker-compose up -d
   ```

## Database Schema

LilBrotr uses a lightweight event table with all 8 columns where tags, content, and sig are nullable and always NULL:

```sql
CREATE TABLE event (
    id BYTEA PRIMARY KEY,
    pubkey BYTEA NOT NULL,
    created_at BIGINT NOT NULL,
    kind INTEGER NOT NULL,
    tags JSONB,
    tagvalues TEXT[] NOT NULL,
    content TEXT,
    sig BYTEA
);
-- Note: tags, content, sig are nullable and always NULL
-- tagvalues is computed at insert time by event_insert()
```

This reduces disk usage by ~60% compared to full event storage since NULL values do not occupy storage.

## Monitoring

Access monitoring dashboards:

- **Prometheus**: http://localhost:9091
- **Grafana**: http://localhost:3001 (admin/admin)

Pre-configured dashboards show:
- Service health and cycle times
- Relay discovery and validation rates
- Event sync progress
- Database statistics

## Troubleshooting

```bash
# Check service status
docker-compose ps

# View logs
docker-compose logs -f                    # All services
docker-compose logs -f synchronizer       # Single service

# Connect to database
docker-compose exec postgres psql -U admin -d lilbrotr

# Check relay count
docker-compose exec postgres psql -U admin -d lilbrotr -c "SELECT COUNT(*) FROM relay"

# Check event count
docker-compose exec postgres psql -U admin -d lilbrotr -c "SELECT COUNT(*) FROM event"

# Reset database (WARNING: deletes all data)
docker-compose down && rm -rf data/postgres && docker-compose up -d
```

## Common Issues

### Services fail to connect to database
- Ensure `DB_ADMIN_PASSWORD`, `DB_WRITER_PASSWORD`, `DB_READER_PASSWORD` are set in `.env`
- Wait for postgres/pgbouncer health checks to pass

### No relays being discovered
- Check Finder logs: `docker-compose logs -f finder`
- Verify API endpoints are reachable

### Monitor fails to publish NIP-66 events
- Ensure `PRIVATE_KEY` is set in `.env`
- Check Monitor logs for connection errors

### Synchronizer not fetching events
- Ensure relays have been validated (check `relays` table)
- Ensure Monitor has marked relays as readable
