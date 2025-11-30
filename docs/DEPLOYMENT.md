# Deployment Guide

This document provides comprehensive guidance for deploying BigBrotr in various environments.

## Table of Contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Docker Compose Deployment](#docker-compose-deployment)
- [Manual Deployment](#manual-deployment)
- [Production Considerations](#production-considerations)
- [Monitoring and Maintenance](#monitoring-and-maintenance)
- [Troubleshooting](#troubleshooting)
- [Backup and Recovery](#backup-and-recovery)

---

## Overview

BigBrotr can be deployed using:

1. **Docker Compose** (recommended) - Full stack deployment with all services
2. **Manual Deployment** - Individual service execution on bare metal/VMs
3. **Kubernetes** - Container orchestration for high availability (advanced)

### Deployment Components

| Component | Purpose | Required |
|-----------|---------|----------|
| PostgreSQL 16+ | Primary data store | Yes |
| PGBouncer | Connection pooling | Recommended |
| Tor Proxy | .onion relay support | Optional |
| Initializer | Database bootstrap | Yes (once) |
| Finder | Relay discovery | Yes |
| Monitor | Health monitoring | Yes |
| Synchronizer | Event collection | Yes |

---

## Prerequisites

### Hardware Requirements

**Minimum (Development/Testing)**:
- CPU: 2 cores
- RAM: 4 GB
- Storage: 20 GB SSD

**Recommended (Production)**:
- CPU: 4+ cores
- RAM: 8+ GB
- Storage: 100+ GB SSD (depends on data retention)

### Software Requirements

- Docker 20.10+ and Docker Compose 2.0+
- OR Python 3.9+ for manual deployment
- Git

### Network Requirements

- Outbound HTTPS (443) for API calls
- Outbound WSS (443) for relay connections
- Outbound Tor (9050) if using .onion relays
- Inbound PostgreSQL (5432) only for admin access

---

## Docker Compose Deployment

Two implementations are available:

| Implementation | Use Case | Ports |
|----------------|----------|-------|
| **bigbrotr** | Full archiving with tags/content | PostgreSQL: 5432, PGBouncer: 6432, Tor: 9050 |
| **lilbrotr** | Lightweight (no tags/content) | PostgreSQL: 5433, PGBouncer: 6433, Tor: 9051 |

### Quick Start (BigBrotr - Full-Featured)

```bash
# Clone repository
git clone https://github.com/bigbrotr/bigbrotr.git
cd bigbrotr/implementations/bigbrotr

# Configure environment
cp .env.example .env
nano .env  # Set DB_PASSWORD

# Deploy
docker-compose up -d

# Check status
docker-compose ps
docker-compose logs -f
```

### Quick Start (LilBrotr - Lightweight)

```bash
# Clone repository
git clone https://github.com/bigbrotr/bigbrotr.git
cd bigbrotr/implementations/lilbrotr

# Configure environment
cp .env.example .env
nano .env  # Set DB_PASSWORD

# Deploy
docker-compose up -d

# Check status
docker-compose ps
docker-compose logs -f
```

**Note**: Both implementations can run simultaneously on the same host due to different port mappings.

### Environment Configuration

Edit `.env` file:

```bash
# Required
DB_PASSWORD=your_secure_password_here

# Optional - for NIP-66 write tests
MONITOR_PRIVATE_KEY=your_hex_private_key
```

### Docker Compose Services

```yaml
services:
  # PostgreSQL Database
  postgres:
    image: postgres:16
    container_name: bigbrotr-postgres
    restart: unless-stopped
    environment:
      POSTGRES_DB: bigbrotr
      POSTGRES_USER: admin
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - ./postgres/init:/docker-entrypoint-initdb.d:ro
      - ./data/postgres:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "admin", "-d", "bigbrotr"]
      interval: 10s
      timeout: 5s
      retries: 5

  # PGBouncer Connection Pooler
  pgbouncer:
    image: bitnami/pgbouncer:latest
    container_name: bigbrotr-pgbouncer
    restart: unless-stopped
    environment:
      PGBOUNCER_DATABASE: bigbrotr
      POSTGRESQL_HOST: postgres
      POSTGRESQL_USERNAME: admin
      POSTGRESQL_PASSWORD: ${DB_PASSWORD}
    depends_on:
      postgres:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "pg_isready", "-h", "localhost", "-p", "5432"]

  # Tor SOCKS5 Proxy
  tor:
    image: dperson/torproxy:latest
    container_name: bigbrotr-tor
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "nc", "-z", "localhost", "9050"]

  # Application Services
  initializer:
    build:
      context: ../../
      dockerfile: implementations/bigbrotr/Dockerfile
    container_name: bigbrotr-initializer
    environment:
      DB_PASSWORD: ${DB_PASSWORD}
    volumes:
      - ./yaml:/app/yaml:ro
      - ./data:/app/data:ro
    depends_on:
      pgbouncer:
        condition: service_healthy
    command: ["python", "-m", "services", "initializer"]

  finder:
    # ... similar configuration

  monitor:
    # ... similar configuration

  synchronizer:
    # ... similar configuration
```

### Deployment Commands

```bash
# Start all services
docker-compose up -d

# Start specific services
docker-compose up -d postgres pgbouncer finder

# View logs
docker-compose logs -f
docker-compose logs -f synchronizer

# Stop services
docker-compose stop

# Stop and remove
docker-compose down

# Rebuild images
docker-compose build --no-cache

# Scale services (if configured)
docker-compose up -d --scale synchronizer=3
```

### Data Persistence

Data is persisted in `./data/postgres/`:

```bash
# Backup location
implementations/bigbrotr/data/postgres/

# View size
du -sh data/postgres/

# Reset data (WARNING: deletes everything)
docker-compose down
rm -rf data/postgres
docker-compose up -d
```

---

## Manual Deployment

### 1. Database Setup

**PostgreSQL Installation**:

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install postgresql-16 postgresql-contrib-16

# Start service
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

**Database Creation**:

```bash
# Switch to postgres user
sudo -u postgres psql

# Create user and database
CREATE USER admin WITH PASSWORD 'your_secure_password';
CREATE DATABASE bigbrotr OWNER admin;
GRANT ALL PRIVILEGES ON DATABASE bigbrotr TO admin;
\q
```

**Schema Initialization**:

```bash
# Apply schema files
cd implementations/bigbrotr
for f in postgres/init/*.sql; do
    psql -U admin -d bigbrotr -f "$f"
done
```

### 2. PGBouncer Setup (Recommended)

```bash
# Install
sudo apt install pgbouncer

# Configure /etc/pgbouncer/pgbouncer.ini
[databases]
bigbrotr = host=localhost port=5432 dbname=bigbrotr

[pgbouncer]
listen_addr = 127.0.0.1
listen_port = 6432
auth_type = md5
auth_file = /etc/pgbouncer/userlist.txt
pool_mode = transaction
max_client_conn = 100
default_pool_size = 25

# Configure /etc/pgbouncer/userlist.txt
"admin" "md5_hash_of_password"

# Start
sudo systemctl start pgbouncer
sudo systemctl enable pgbouncer
```

### 3. Python Environment

```bash
# Create virtual environment
python3 -m venv /opt/bigbrotr/venv
source /opt/bigbrotr/venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set environment
export DB_PASSWORD=your_secure_password
export PYTHONPATH=/opt/bigbrotr/src
```

### 4. Running Services

```bash
# Change to implementation directory
cd /opt/bigbrotr/implementations/bigbrotr

# Run initializer (once)
python -m services initializer

# Run services (in separate terminals or with process manager)
python -m services finder &
python -m services monitor &
python -m services synchronizer &
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
WorkingDirectory=/opt/bigbrotr/implementations/bigbrotr
Environment="PATH=/opt/bigbrotr/venv/bin"
Environment="PYTHONPATH=/opt/bigbrotr/src"
Environment="DB_PASSWORD=your_secure_password"
ExecStart=/opt/bigbrotr/venv/bin/python -m services finder
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Create similar files for `monitor` and `synchronizer`.

```bash
# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable bigbrotr-finder bigbrotr-monitor bigbrotr-synchronizer
sudo systemctl start bigbrotr-finder bigbrotr-monitor bigbrotr-synchronizer

# Check status
sudo systemctl status bigbrotr-*
```

---

## Production Considerations

### Security

**Database**:
```bash
# Use strong password
openssl rand -base64 32

# Restrict connections (pg_hba.conf)
# Only allow local connections and application hosts

# Enable SSL
ssl = on
ssl_cert_file = '/path/to/server.crt'
ssl_key_file = '/path/to/server.key'
```

**Environment**:
```bash
# Protect .env file
chmod 600 .env

# Use secrets management for production
# - Docker secrets
# - HashiCorp Vault
# - AWS Secrets Manager
```

**Network**:
```bash
# Firewall rules
sudo ufw allow from app_server_ip to any port 5432
sudo ufw deny 5432  # Block public access

# Use internal networks in Docker
networks:
  internal:
    internal: true
```

### Performance Tuning

**PostgreSQL** (`postgresql.conf`):
```ini
# Memory
shared_buffers = 2GB              # 25% of RAM
effective_cache_size = 6GB        # 75% of RAM
work_mem = 64MB
maintenance_work_mem = 512MB

# Connections
max_connections = 200

# Write Ahead Log
wal_level = replica
max_wal_size = 4GB
min_wal_size = 1GB

# Checkpoints
checkpoint_completion_target = 0.9
checkpoint_timeout = 15min

# Statistics
default_statistics_target = 100
random_page_cost = 1.1  # For SSD
```

**PGBouncer**:
```ini
pool_mode = transaction
max_client_conn = 500
default_pool_size = 50
reserve_pool_size = 10
reserve_pool_timeout = 3
```

**Application**:
```yaml
# yaml/core/brotr.yaml
pool:
  limits:
    min_size: 10
    max_size: 50

# yaml/services/synchronizer.yaml
concurrency:
  max_parallel: 50
  max_processes: 16
```

### High Availability

**PostgreSQL Replication**:
```ini
# Primary (postgresql.conf)
wal_level = replica
max_wal_senders = 3
wal_keep_size = 1GB

# Replica
primary_conninfo = 'host=primary_host port=5432 user=replicator password=xxx'
```

**Service Redundancy**:
```yaml
# Run multiple instances
docker-compose up -d --scale finder=2 --scale monitor=2
```

**Load Balancing**:
- Use PGBouncer for database connections
- Use HAProxy/nginx for API load balancing (when implemented)

---

## Monitoring and Maintenance

### Health Checks

**Service Health**:
```bash
# Docker
docker-compose ps
docker-compose logs --tail=100 finder

# Systemd
sudo systemctl status bigbrotr-*
sudo journalctl -u bigbrotr-finder -f
```

**Database Health**:
```sql
-- Connection count
SELECT count(*) FROM pg_stat_activity WHERE datname = 'bigbrotr';

-- Table sizes
SELECT relname, pg_size_pretty(pg_total_relation_size(relid))
FROM pg_stat_user_tables ORDER BY pg_total_relation_size(relid) DESC;

-- Slow queries
SELECT query, calls, total_time, mean_time
FROM pg_stat_statements ORDER BY mean_time DESC LIMIT 10;
```

### Log Management

**Docker**:
```yaml
services:
  finder:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "5"
```

**Systemd**:
```bash
# View logs
journalctl -u bigbrotr-finder --since "1 hour ago"

# Configure log rotation
sudo nano /etc/logrotate.d/bigbrotr
```

### Routine Maintenance

**Daily**:
```bash
# Check service status
docker-compose ps

# Check logs for errors
docker-compose logs --since 24h | grep -i error
```

**Weekly**:
```sql
-- Analyze statistics
ANALYZE;

-- Cleanup orphans
SELECT delete_orphan_events();
SELECT delete_orphan_nip11();
SELECT delete_orphan_nip66();
```

**Monthly**:
```sql
-- Vacuum tables
VACUUM ANALYZE events;
VACUUM ANALYZE events_relays;
VACUUM ANALYZE relay_metadata;

-- Check index health
REINDEX INDEX CONCURRENTLY idx_events_created_at;
```

---

## Troubleshooting

### Common Issues

**"Connection refused"**:
```bash
# Check database is running
docker-compose ps postgres
docker-compose logs postgres

# Check connectivity
docker-compose exec pgbouncer pg_isready -h localhost
```

**"Pool exhausted"**:
```yaml
# Increase pool size
pool:
  limits:
    max_size: 50
```

**"Timeout connecting to relay"**:
```yaml
# Increase timeouts
timeouts:
  clearnet: 60.0
  tor: 120.0
```

**"Out of disk space"**:
```bash
# Check disk usage
df -h
du -sh data/postgres

# Vacuum to reclaim space
docker-compose exec postgres psql -U admin -d bigbrotr -c "VACUUM FULL events"
```

**"Memory issues"**:
```yaml
# Docker memory limits
services:
  postgres:
    deploy:
      resources:
        limits:
          memory: 4G

  synchronizer:
    deploy:
      resources:
        limits:
          memory: 2G
```

### Debug Mode

```bash
# Run with debug logging
docker-compose run --rm finder python -m services finder --log-level DEBUG

# Or set in docker-compose.yaml
environment:
  LOG_LEVEL: DEBUG
```

### Restart Strategies

```yaml
# docker-compose.yaml
services:
  finder:
    restart: unless-stopped
    # or: restart: always
    # or: restart: on-failure

# With health checks
healthcheck:
  test: ["CMD", "python", "-c", "import socket; socket.create_connection(('localhost', 5432))"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 40s
```

---

## Backup and Recovery

### Database Backup

**pg_dump (Recommended for smaller databases)**:
```bash
# Full backup
docker-compose exec postgres pg_dump -U admin -d bigbrotr > backup.sql

# Compressed
docker-compose exec postgres pg_dump -U admin -d bigbrotr | gzip > backup.sql.gz

# Specific tables
docker-compose exec postgres pg_dump -U admin -d bigbrotr -t relays -t events > partial.sql
```

**Automated Backup Script**:
```bash
#!/bin/bash
# /opt/bigbrotr/backup.sh

BACKUP_DIR=/opt/bigbrotr/backups
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS=7

# Create backup
docker-compose -f /opt/bigbrotr/implementations/bigbrotr/docker-compose.yaml \
    exec -T postgres pg_dump -U admin -d bigbrotr | gzip > "${BACKUP_DIR}/backup_${TIMESTAMP}.sql.gz"

# Remove old backups
find "${BACKUP_DIR}" -name "backup_*.sql.gz" -mtime +${RETENTION_DAYS} -delete

# crontab -e
# 0 2 * * * /opt/bigbrotr/backup.sh
```

### Recovery

**From pg_dump**:
```bash
# Stop services
docker-compose stop finder monitor synchronizer

# Restore
gunzip -c backup.sql.gz | docker-compose exec -T postgres psql -U admin -d bigbrotr

# Start services
docker-compose start finder monitor synchronizer
```

### Point-in-Time Recovery

For production, configure WAL archiving:

```ini
# postgresql.conf
archive_mode = on
archive_command = 'cp %p /path/to/archive/%f'
```

---

## Deployment Checklist

### Pre-Deployment

- [ ] Hardware requirements met
- [ ] Docker and Docker Compose installed
- [ ] Repository cloned
- [ ] `.env` file configured with secure password
- [ ] Firewall rules configured
- [ ] Backup strategy defined

### Deployment

- [ ] `docker-compose up -d`
- [ ] All services show as "healthy"
- [ ] Initializer completed successfully
- [ ] Database schema verified
- [ ] Finder discovering relays
- [ ] Monitor checking relay health
- [ ] Synchronizer collecting events

### Post-Deployment

- [ ] Monitoring configured
- [ ] Log rotation configured
- [ ] Backup automation configured
- [ ] Documentation updated
- [ ] Alerts configured (optional)

---

## Related Documentation

| Document | Description |
|----------|-------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System architecture overview |
| [CONFIGURATION.md](CONFIGURATION.md) | Complete configuration reference |
| [DATABASE.md](DATABASE.md) | Database schema documentation |
| [DEVELOPMENT.md](DEVELOPMENT.md) | Development setup and guidelines |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | Contribution guidelines |
| [CHANGELOG.md](../CHANGELOG.md) | Version history |
