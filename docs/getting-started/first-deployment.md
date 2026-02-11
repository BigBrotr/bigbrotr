# First Deployment

A complete walkthrough for deploying BigBrotr with Docker Compose, including monitoring with Prometheus and Grafana.

---

## Prerequisites

- [x] Docker 20.10+ and Docker Compose 2.0+
- [x] Git
- [x] Repository cloned: `git clone https://github.com/BigBrotr/bigbrotr.git`

## Step 1: Create the Environment File

Navigate to the BigBrotr deployment directory and create your `.env` file from the template:

```bash
cd bigbrotr/deployments/bigbrotr
cp .env.example .env
```

Generate secure values for each required secret:

```bash
# Generate and set all secrets at once
DB_PASSWORD=$(openssl rand -base64 32)
PRIVATE_KEY=$(openssl rand -hex 32)
GRAFANA_PASSWORD=$(openssl rand -base64 16)

cat > .env << EOF
DB_PASSWORD=${DB_PASSWORD}
PRIVATE_KEY=${PRIVATE_KEY}
GRAFANA_PASSWORD=${GRAFANA_PASSWORD}
EOF
```

!!! warning
    Protect your `.env` file -- it contains database credentials and your Nostr
    private key. Set restrictive permissions:
    ```bash
    chmod 600 .env
    ```

## Step 2: Start the Stack

Launch all containers in the background:

```bash
docker compose up -d
```

Docker Compose will:

1. Pull required images (PostgreSQL, PGBouncer, Tor, Prometheus, Grafana)
2. Build the BigBrotr application image from `deployments/Dockerfile`
3. Initialize the PostgreSQL schema from `postgres/init/*.sql`
4. Start all services with health checks and restart policies

!!! note
    The first build takes a few minutes to compile dependencies. Subsequent starts
    use cached layers and are much faster.

## Step 3: Verify Services Are Running

Check the status of all containers:

```bash
docker compose ps
```

All services should show as `Up` with `(healthy)` status. The Seeder will show
`Exited (0)` after completing its one-shot run -- this is expected.

Watch the pipeline progress in real time:

```bash
# Follow the seeder (completes quickly)
docker compose logs -f seeder

# Follow the finder as it discovers relays
docker compose logs -f finder

# View all service logs
docker compose logs -f
```

## Step 4: Access Grafana Dashboard

Open your browser and navigate to the Grafana dashboard:

| Service | URL |
|---------|-----|
| Grafana | [http://localhost:3000](http://localhost:3000) |

Log in with:

- **Username**: `admin`
- **Password**: the `GRAFANA_PASSWORD` value from your `.env` file

The BigBrotr dashboard is auto-provisioned and displays per-service panels including
last cycle time, cycle duration, error counts, and consecutive failures.

## Step 5: Check Prometheus Targets

Verify that Prometheus is scraping metrics from all services:

| Service | URL |
|---------|-----|
| Prometheus | [http://localhost:9090](http://localhost:9090) |

Navigate to **Status > Targets** (`http://localhost:9090/targets`). All service
endpoints should show a green `UP` state:

| Target | Endpoint |
|--------|----------|
| Finder | `finder:8001/metrics` |
| Validator | `validator:8002/metrics` |
| Monitor | `monitor:8003/metrics` |
| Synchronizer | `synchronizer:8004/metrics` |

!!! tip
    If a target shows as `DOWN`, check the service logs:
    ```bash
    docker compose logs finder
    ```

## Step 6: Basic Operations

### View Service Logs

```bash
# All services
docker compose logs -f

# Single service with timestamps
docker compose logs -f --timestamps monitor

# Last 100 lines
docker compose logs --tail=100 synchronizer
```

### Restart a Service

```bash
# Restart a single service
docker compose restart validator

# Restart with a fresh image (after code changes)
docker compose up -d --build validator
```

### Check Database Health

```bash
# Connect to PostgreSQL
docker compose exec postgres psql -U admin -d bigbrotr

# Quick relay count
docker compose exec postgres psql -U admin -d bigbrotr -c "SELECT count(*) FROM relay;"

# Check PGBouncer stats
docker compose exec pgbouncer psql -U admin -p 6432 -d pgbouncer -c "SHOW pools;"
```

### Stop and Start

```bash
# Stop all services (preserves data)
docker compose stop

# Start again
docker compose start

# Full teardown (preserves volumes)
docker compose down

# Full teardown including data volumes
docker compose down -v
```

!!! warning
    `docker compose down -v` **deletes all data** including the PostgreSQL database,
    Prometheus metrics, and Grafana configuration. Use with caution.

## Port Reference

All ports bind to `127.0.0.1` (localhost only) by default:

| Service | Port |
|---------|------|
| PostgreSQL | 5432 |
| PGBouncer | 6432 |
| Tor SOCKS5 | 9050 |
| Grafana | 3000 |
| Prometheus | 9090 |
| Finder Metrics | 8001 |
| Validator Metrics | 8002 |
| Monitor Metrics | 8003 |
| Synchronizer Metrics | 8004 |

## Next Steps

Your BigBrotr instance is now running and discovering relays. From here:

- [Configuration Reference](../user-guide/configuration.md) -- Tune service intervals, timeouts, and network settings
- [Deployment Guide](../how-to/docker-deploy.md) -- Production hardening, backups, and scaling
- [Architecture](../user-guide/architecture.md) -- Understand the system design and module structure

---

## Related Documentation

- [Installation](installation.md) -- Install paths and system requirements
- [Quick Start](quickstart.md) -- Run services manually step by step
- [Deployment Guide](../how-to/docker-deploy.md) -- Production deployment, backup, and troubleshooting
- [Configuration Reference](../user-guide/configuration.md) -- YAML configuration for all services
