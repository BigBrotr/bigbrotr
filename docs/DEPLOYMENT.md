# Deployment Guide

Complete guide for deploying BigBrotr using Docker Compose or manual installation.

---

## Overview

BigBrotr supports two deployment methods:

1. **Docker Compose** (recommended) -- Full stack with all services, monitoring, and networking
2. **Manual** -- Individual service execution on bare metal or VMs

Two implementations are available:

| Implementation | Purpose | Ports |
|----------------|---------|-------|
| **BigBrotr** | Full event archiving with tags, content, signatures | PostgreSQL: 5432, PGBouncer: 6432 |
| **LilBrotr** | Lightweight indexing (~60% disk savings, omits tags/content/sig) | PostgreSQL: 5433, PGBouncer: 6433 |

Both can run simultaneously on the same host.

### Deployment Components

| Component | Image | Required |
|-----------|-------|----------|
| PostgreSQL 16 | `postgres:16-alpine` | Yes |
| PGBouncer | `edoburu/pgbouncer:v1.25.1-p0` | Recommended |
| Tor Proxy | `osminogin/tor-simple:0.4.8.10` | Optional (.onion relay support) |
| Prometheus | `prom/prometheus:v2.51.0` | Optional (monitoring) |
| Grafana | `grafana/grafana:10.4.1` | Optional (dashboards) |
| Application Services | Built from `deployments/Dockerfile` | Yes |

---

## Prerequisites

### Hardware

| Environment | CPU | RAM | Storage |
|-------------|-----|-----|---------|
| Development/Testing | 2 cores | 4 GB | 20 GB SSD |
| Production | 4+ cores | 8+ GB | 100+ GB SSD |

### Software

- Docker 20.10+ and Docker Compose 2.0+
- OR Python 3.11+ for manual deployment
- Git

### Network

- Outbound HTTPS (443) for relay connections and API calls
- Outbound Tor (9050) if using .onion relays
- All ports bind to `127.0.0.1` by default (localhost only)

---

## Docker Compose Deployment

### Quick Start

```bash
# Clone repository
git clone https://github.com/bigbrotr/bigbrotr.git
cd bigbrotr/deployments/bigbrotr

# Configure environment
cp .env.example .env
# Edit .env: set DB_PASSWORD, PRIVATE_KEY, GRAFANA_PASSWORD

# Deploy
docker compose up -d

# Check status
docker compose ps
docker compose logs -f
```

### Environment Configuration

Edit `.env`:

```bash
# Required
DB_PASSWORD=your_secure_password        # openssl rand -base64 32
PRIVATE_KEY=your_hex_private_key        # openssl rand -hex 32
GRAFANA_PASSWORD=your_grafana_password  # openssl rand -base64 16

# Optional - metrics port overrides
FINDER_METRICS_PORT=8001
VALIDATOR_METRICS_PORT=8002
MONITOR_METRICS_PORT=8003
SYNCHRONIZER_METRICS_PORT=8004
```

### Architecture

```text
                     +------------------+
                     |    Grafana       |  :3000
                     +--------+---------+
                              |
                     +--------+---------+
                     |   Prometheus     |  :9090
                     +--------+---------+
                              | scrapes /metrics
          +---+---+---+-------+
          |   |   |   |
       +--+--+--+--+--+--+--+--+
       |finder|valid|monit|sync |  :8001-8004
       +--+---+--+-+--+--+--+--+
          |      |     |     |
       +--+------+-----+-----+--+
       |       PGBouncer         |  :6432
       +-----------+-------------+
                   |
       +-----------+-------------+
       |       PostgreSQL        |  :5432
       +-------------------------+
```

### Network Isolation

Each deployment creates two Docker bridge networks:

- **data-network**: PostgreSQL, PGBouncer, Tor, application services
- **monitoring-network**: Prometheus, Grafana, application services

PostgreSQL is only on the data network. Grafana is only on the monitoring network. Application services bridge both.

### Service Details

#### Infrastructure

**PostgreSQL** (`postgres:16-alpine`)

- Custom `postgresql.conf` mounted for production tuning
- SSD-optimized settings (`random_page_cost = 1.1`, `synchronous_commit = off`)
- Schema initialized from `postgres/init/*.sql` on first start
- Data persisted to named volume `postgres-data`
- Healthcheck: `pg_isready -U admin -d bigbrotr`

**PGBouncer** (`edoburu/pgbouncer:v1.25.1-p0`)

- Transaction-mode pooling (`pool_mode = transaction`)
- 1000 max client connections, 20 default pool size
- Auth: `scram-sha-256`
- Depends on PostgreSQL being healthy

**Tor** (`osminogin/tor-simple:0.4.8.10`)

- SOCKS5 proxy on port 9050 for .onion relay access
- Healthcheck: `nc -z 127.0.0.1 9050`
- Enabled by default in BigBrotr, disabled in LilBrotr

#### Application Services

All application services share:

- Single parametric Dockerfile (`deployments/Dockerfile`) with `ARG DEPLOYMENT`
- **tini** as PID 1 for proper signal handling and zombie reaping
- `STOPSIGNAL SIGTERM` with 60s `stop_grace_period` for graceful shutdown
- Real healthcheck via `http://localhost:8000/metrics` endpoint
- Read-only config volume mount
- Resource limits (CPU and memory)

| Service | Restart Policy | CPU | Memory | Log Max |
|---------|---------------|-----|--------|---------|
| Seeder | `no` (one-shot) | 0.5 | 256 MB | 10 MB |
| Finder | `unless-stopped` | 1 | 512 MB | 50 MB |
| Validator | `unless-stopped` | 1 | 512 MB | 50 MB |
| Monitor | `unless-stopped` | 1 | 512 MB | 50 MB |
| Synchronizer | `unless-stopped` | 1 | 512 MB | 100 MB |

#### Monitoring

**Prometheus** (`prom/prometheus:v2.51.0`)

- Scrapes all service `/metrics` endpoints every 30s
- 30-day data retention
- Alerting rules in `monitoring/prometheus/rules/alerts.yml` (BigBrotr only)
- Data persisted to named volume `prometheus-data`

**Grafana** (`grafana/grafana:10.4.1`)

- Provisioned datasource (Prometheus) and dashboard directory
- Dashboards are non-editable in BigBrotr deployment (prevents drift)
- Data persisted to named volume `grafana-data`

### Alerting Rules (BigBrotr)

| Alert | Condition | Severity |
|-------|-----------|----------|
| ServiceDown | Target unreachable > 5 min | critical |
| HighFailureRate | Error rate > 0.1/sec over 5 min | warning |
| PoolExhausted | Zero available connections > 2 min | critical |
| DatabaseSlow | p99 query duration > 5s over 5 min | warning |

### Port Mappings

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
| Prometheus | 9090 | 9091 |
| Grafana | 3000 | 3001 |

### Docker Commands

```bash
# Start all services
docker compose up -d

# Start specific services
docker compose up -d postgres pgbouncer finder

# View logs
docker compose logs -f
docker compose logs -f synchronizer

# Stop services
docker compose stop

# Stop and remove containers
docker compose down

# Rebuild images (after code changes)
docker compose build --no-cache

# Check service health
docker compose ps
```

---

## Manual Deployment

### 1. Database Setup

```bash
# Install PostgreSQL 16
sudo apt update && sudo apt install postgresql-16 postgresql-contrib-16
sudo systemctl start postgresql && sudo systemctl enable postgresql

# Create database
sudo -u postgres psql -c "CREATE USER admin WITH PASSWORD 'your_password';"
sudo -u postgres psql -c "CREATE DATABASE bigbrotr OWNER admin;"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE bigbrotr TO admin;"

# Apply schema
cd deployments/bigbrotr
for f in postgres/init/*.sql; do
    psql -U admin -d bigbrotr -f "$f"
done
```

### 2. PGBouncer Setup (Recommended)

```bash
sudo apt install pgbouncer
```

Configure `/etc/pgbouncer/pgbouncer.ini`:

```ini
[databases]
bigbrotr = host=localhost port=5432 dbname=bigbrotr

[pgbouncer]
listen_addr = 127.0.0.1
listen_port = 6432
auth_type = scram-sha-256
auth_file = /etc/pgbouncer/userlist.txt
pool_mode = transaction
max_client_conn = 1000
default_pool_size = 20
```

```bash
sudo systemctl start pgbouncer && sudo systemctl enable pgbouncer
```

### 3. Python Environment

```bash
python3 -m venv /opt/bigbrotr/venv
source /opt/bigbrotr/venv/bin/activate
pip install .
export DB_PASSWORD=your_password
export PRIVATE_KEY=your_hex_key
```

### 4. Running Services

```bash
cd /opt/bigbrotr/deployments/bigbrotr

# Run seeder (one-shot)
python -m bigbrotr seeder --once

# Run services
python -m bigbrotr finder &
python -m bigbrotr validator &
python -m bigbrotr monitor &
python -m bigbrotr synchronizer &
```

### 5. Systemd Service Files

Create `/etc/systemd/system/bigbrotr-finder.service`:

```ini
[Unit]
Description=BigBrotr Finder Service
After=network.target postgresql.service pgbouncer.service

[Service]
Type=simple
User=bigbrotr
Group=bigbrotr
WorkingDirectory=/opt/bigbrotr/deployments/bigbrotr
Environment="PATH=/opt/bigbrotr/venv/bin"
Environment="DB_PASSWORD=your_password"
Environment="PRIVATE_KEY=your_hex_key"
ExecStart=/opt/bigbrotr/venv/bin/python -m bigbrotr finder
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Create similar files for `validator`, `monitor`, and `synchronizer`.

```bash
sudo systemctl daemon-reload
sudo systemctl enable bigbrotr-finder bigbrotr-validator bigbrotr-monitor bigbrotr-synchronizer
sudo systemctl start bigbrotr-finder bigbrotr-validator bigbrotr-monitor bigbrotr-synchronizer
```

---

## Creating a New Deployment

Use the `_template` deployment as a starting point:

```bash
cp -r deployments/_template deployments/myproject
cd deployments/myproject

# Customize:
# 1. Edit docker-compose.yaml (container names, ports, database name)
# 2. Edit config/brotr.yaml (database connection)
# 3. Edit config/services/*.yaml (service behavior)
# 4. Edit postgres/init/02_tables.sql (choose BigBrotr or LilBrotr schema)
# 5. Edit static/seed_relays.txt (initial relay URLs)
# 6. Create .env from .env.example
```

---

## Production Considerations

### Security

```bash
# Strong passwords
openssl rand -base64 32 > /dev/null  # for DB_PASSWORD
openssl rand -hex 32 > /dev/null     # for PRIVATE_KEY

# Protect .env file
chmod 600 .env

# Firewall: restrict PostgreSQL access
sudo ufw allow from app_server_ip to any port 5432
sudo ufw deny 5432
```

### PostgreSQL Tuning

The included `postgresql.conf` is tuned for a 2 GB container. Key settings:

| Setting | Value | Purpose |
|---------|-------|---------|
| `shared_buffers` | 512 MB | Data cache (25% RAM) |
| `effective_cache_size` | 1536 MB | OS cache estimate (75% RAM) |
| `synchronous_commit` | off | Async commits for write throughput |
| `random_page_cost` | 1.1 | SSD-optimized query planner |
| `autovacuum_naptime` | 30s | Aggressive autovacuum for high writes |

For larger deployments, scale proportionally:

| RAM | shared_buffers | effective_cache_size | work_mem |
|-----|---------------|---------------------|----------|
| 2 GB | 512 MB | 1.5 GB | 4 MB |
| 4 GB | 1 GB | 3 GB | 8 MB |
| 8 GB | 2 GB | 6 GB | 16 MB |

### Backup and Recovery

**Automated backup script**:

```bash
#!/bin/bash
BACKUP_DIR=/opt/bigbrotr/backups
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

docker compose exec -T postgres pg_dump -U admin -d bigbrotr \
    | gzip > "${BACKUP_DIR}/backup_${TIMESTAMP}.sql.gz"

# Remove backups older than 7 days
find "${BACKUP_DIR}" -name "backup_*.sql.gz" -mtime +7 -delete
```

Add to crontab: `0 2 * * * /opt/bigbrotr/backup.sh`

**Restore from backup**:

```bash
docker compose stop finder validator monitor synchronizer
gunzip -c backup.sql.gz | docker compose exec -T postgres psql -U admin -d bigbrotr
docker compose start finder validator monitor synchronizer
```

---

## Troubleshooting

**"Connection refused"** -- Check that PostgreSQL and PGBouncer are healthy:

```bash
docker compose ps postgres pgbouncer
docker compose logs postgres
```

**"Pool exhausted"** -- Increase pool size in `config/brotr.yaml`:

```yaml
pool:
  limits:
    max_size: 50
```

**"Timeout connecting to relay"** -- Increase timeouts in the service config:

```yaml
networks:
  clearnet:
    timeout: 60.0
  tor:
    timeout: 120.0
```

**"Out of disk space"** -- Check usage and vacuum:

```bash
du -sh data/postgres
docker compose exec postgres psql -U admin -d bigbrotr -c "VACUUM FULL event"
```

**Service not starting** -- Check logs and healthcheck:

```bash
docker compose logs finder
docker inspect bigbrotr-finder --format='{{json .State.Health}}'
```

---

## Deployment Checklist

### Pre-Deployment

- [ ] Hardware requirements met
- [ ] Docker and Docker Compose installed
- [ ] Repository cloned
- [ ] `.env` configured with secure passwords
- [ ] Firewall rules set (localhost-only ports)

### Deployment

- [ ] `docker compose up -d` succeeds
- [ ] All services show as healthy (`docker compose ps`)
- [ ] Seeder completed (`docker compose logs seeder`)
- [ ] Finder discovering candidates
- [ ] Validator testing candidates
- [ ] Monitor performing health checks
- [ ] Synchronizer collecting events

### Post-Deployment

- [ ] Prometheus scraping metrics (`:9090/targets`)
- [ ] Grafana accessible (`:3000`)
- [ ] Backup automation configured
- [ ] Log rotation active (Docker json-file driver with limits)

---

## Related Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) -- System architecture and module reference
- [CONFIGURATION.md](CONFIGURATION.md) -- YAML configuration reference
- [DATABASE.md](DATABASE.md) -- Database schema and stored procedures
- [DEVELOPMENT.md](DEVELOPMENT.md) -- Development setup and testing
