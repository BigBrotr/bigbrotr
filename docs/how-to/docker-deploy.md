# Docker Compose Deployment

Deploy the full BigBrotr stack using Docker Compose, including PostgreSQL, PGBouncer, Tor proxy, all application services, and the monitoring stack.

---

## Prerequisites

- Docker 20.10+
- Docker Compose 2.0+
- Git
- Outbound HTTPS (port 443) for relay connections
- Outbound Tor (port 9050) if monitoring `.onion` relays

## Step-by-step Deployment

### 1. Clone the repository

```bash
git clone https://github.com/BigBrotr/bigbrotr.git
cd bigbrotr/deployments/bigbrotr
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and set the required secrets:

```bash
# Required -- database passwords
DB_ADMIN_PASSWORD=your_admin_password          # openssl rand -base64 32
DB_WRITER_PASSWORD=your_writer_password        # openssl rand -base64 32
DB_READER_PASSWORD=your_reader_password        # openssl rand -base64 32
DB_REFRESHER_PASSWORD=your_refresher_password  # openssl rand -base64 32

# Required -- application secrets
NOSTR_PRIVATE_KEY=your_hex_private_key           # openssl rand -hex 32
GRAFANA_PASSWORD=your_grafana_password     # openssl rand -base64 16

# Optional -- metrics port overrides (host ports, all map to container port 8000)
FINDER_METRICS_PORT=8001
VALIDATOR_METRICS_PORT=8002
MONITOR_METRICS_PORT=8003
SYNCHRONIZER_METRICS_PORT=8004
REFRESHER_METRICS_PORT=8005
API_METRICS_PORT=8006
DVM_METRICS_PORT=8007
```

!!! danger "Protect your `.env` file"
    Run `chmod 600 .env` to prevent other users from reading your secrets.

### 3. Start the stack

```bash
docker compose up -d
```

This starts all containers: PostgreSQL, PGBouncer, Tor, Seeder, Finder, Validator, Monitor, Synchronizer, Refresher, Api, Dvm, Prometheus, Alertmanager, and Grafana.

### 4. Verify deployment

```bash
# Check all containers are healthy
docker compose ps

# Watch the seeder complete its one-shot run
docker compose logs -f seeder

# Follow service logs
docker compose logs -f finder validator monitor synchronizer refresher api dvm
```

!!! tip
    The seeder runs once and exits (`restart: no`). All other services restart automatically.

## Architecture

```mermaid
graph TD
    Grafana["Grafana :3000"] --> Prometheus["Prometheus :9090"]
    Prometheus -->|scrapes /metrics| Finder["Finder :8001"]
    Prometheus -->|scrapes /metrics| Validator["Validator :8002"]
    Prometheus -->|scrapes /metrics| Monitor["Monitor :8003"]
    Prometheus -->|scrapes /metrics| Synchronizer["Synchronizer :8004"]
    Prometheus -->|scrapes /metrics| Refresher["Refresher :8005"]
    Prometheus -->|scrapes /metrics| Api["Api :8006"]
    Prometheus -->|scrapes /metrics| Dvm["Dvm :8007"]
    Prometheus -->|scrapes /metrics| PGExporter["PG Exporter :9187"]
    Finder --> PGBouncer["PGBouncer :6432"]
    Validator --> PGBouncer
    Monitor --> PGBouncer
    Synchronizer --> PGBouncer
    Refresher --> PGBouncer
    Api --> PGBouncer
    Dvm --> PGBouncer
    PGBouncer --> PostgreSQL["PostgreSQL :5432"]
    PGExporter --> PostgreSQL
    Validator --> Tor["Tor :9050"]
    Monitor --> Tor
    Synchronizer --> Tor
```

## Network Isolation

Each deployment creates two Docker bridge networks:

| Network | Members | Purpose |
|---------|---------|---------|
| **data-network** | PostgreSQL, PGBouncer, Tor, all services | Database and relay connectivity |
| **monitoring-network** | Prometheus, Grafana, all services | Metrics scraping and dashboards |

PostgreSQL is only on the data network. Grafana is only on the monitoring network. Application services bridge both networks.

## Docker Commands Quick Reference

```bash
# Start all services
docker compose up -d

# Start specific services only
docker compose up -d postgres pgbouncer finder

# View logs (all or specific service)
docker compose logs -f
docker compose logs -f synchronizer

# Stop services (keep containers)
docker compose stop

# Stop and remove containers
docker compose down

# Rebuild images after code changes
docker compose build --no-cache

# Check service health
docker compose ps
```

## Port Mappings

All ports bind to `127.0.0.1` (localhost only).

| Service | BigBrotr | LilBrotr |
|---------|----------|----------|
| PostgreSQL | 5432 | 5433 |
| PGBouncer | 6432 | 6433 |
| Tor SOCKS5 | 9050 | 9051 |
| Finder Metrics | 8001 | 9001 |
| Validator Metrics | 8002 | 9002 |
| Monitor Metrics | 8003 | 9003 |
| Synchronizer Metrics | 8004 | 9004 |
| Refresher Metrics | 8005 | 9005 |
| Api HTTP | 8080 | 8081 |
| Api Metrics | 8006 | 9006 |
| Dvm Metrics | 8007 | 9007 |
| Prometheus | 9090 | 9091 |
| Grafana | 3000 | 3001 |

!!! note
    BigBrotr and LilBrotr use different ports and can run simultaneously on the same host.

---

## Related Documentation

- [Manual Deployment](manual-deploy.md) -- deploy without Docker
- [Custom Deployment](custom-deployment.md) -- create a new deployment from the template
- [Monitoring Setup](monitoring-setup.md) -- configure Prometheus and Grafana
- [Troubleshooting](troubleshooting.md) -- resolve common deployment issues
