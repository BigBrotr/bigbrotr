# LilBrotr - Lightweight BigBrotr Implementation

LilBrotr is a **lightweight** BigBrotr implementation optimized for reduced disk usage and resource consumption.
It stores essential event metadata while omitting heavy fields like `tags`, `content`, and `sig` (~60% disk savings).

## Key Differences from BigBrotr

| Feature | BigBrotr | LilBrotr |
|---------|----------|----------|
| Event storage | Full (tags, content, sig) | Lightweight (id, pubkey, created_at, kind) |
| Disk usage | ~100% | ~40% |
| Tor support | Enabled by default | Disabled by default |
| I2P/Lokinet | Available | Disabled |
| Concurrency | High | Reduced |
| Event scanning | Enabled | Disabled (no tags/content) |

## Quick Start

```bash
cd implementations/lilbrotr

# 1. Configure environment
cp .env.example .env
nano .env  # Set DB_PASSWORD and PRIVATE_KEY

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
implementations/lilbrotr/
├── README.md                         # This file
├── .env.example                      # Environment template
├── docker-compose.yaml               # Container orchestration
├── Dockerfile                        # Application image build
├── postgres/
│   ├── postgresql.conf               # PostgreSQL tuning
│   └── init/                         # SQL initialization
│       ├── 00_extensions.sql
│       ├── 01_functions_utility.sql
│       ├── 02_tables.sql             # Lightweight events table
│       ├── 03_functions_crud.sql     # Adapted CRUD functions
│       ├── 04_functions_cleanup.sql
│       ├── 05_indexes.sql
│       └── 99_verify.sql
├── yaml/
│   ├── core/
│   │   └── brotr.yaml                # Database connection config
│   └── services/
│       ├── seeder.yaml               # Seed relay URLs
│       ├── finder.yaml               # Discover relays (API only)
│       ├── validator.yaml            # Validate candidates
│       ├── monitor.yaml              # Health checks
│       └── synchronizer.yaml         # Sync events
├── prometheus/
│   └── prometheus.yaml               # Metrics scrape config
├── grafana/
│   └── provisioning/                 # Dashboards and datasources
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
| `DB_PASSWORD` | Yes | PostgreSQL password |
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
- Event scanning **disabled** (no tags/content in database)
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
- Stores lightweight event data (no tags/content/sig)
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

3. **Enable Tor in service configs** (`yaml/services/*.yaml`):
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

LilBrotr uses a lightweight events table:

```sql
CREATE TABLE events (
    id BYTEA PRIMARY KEY,
    pubkey BYTEA NOT NULL,
    created_at BIGINT NOT NULL,
    kind INTEGER NOT NULL
);
-- Note: tags, tagvalues, content, sig columns are OMITTED
```

This reduces disk usage by ~60% compared to full event storage.

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
docker-compose exec postgres psql -U admin -d lilbrotr -c "SELECT COUNT(*) FROM relays"

# Check event count
docker-compose exec postgres psql -U admin -d lilbrotr -c "SELECT COUNT(*) FROM events"

# Reset database (WARNING: deletes all data)
docker-compose down && rm -rf data/postgres && docker-compose up -d
```

## Common Issues

### Services fail to connect to database
- Ensure `DB_PASSWORD` is set in `.env`
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
