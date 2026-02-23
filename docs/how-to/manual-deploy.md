# Manual Deployment

Install and run BigBrotr services directly on a Linux host without Docker.

---

## Prerequisites

- Ubuntu 22.04+ or Debian 12+ (other Linux distributions work with equivalent packages)
- Python 3.11+
- PostgreSQL 16+
- PGBouncer (recommended)

## 1. Set Up PostgreSQL

### Install and start PostgreSQL

```bash
sudo apt update && sudo apt install postgresql-16 postgresql-contrib-16
sudo systemctl start postgresql && sudo systemctl enable postgresql
```

### Create the database

```bash
sudo -u postgres psql -c "CREATE USER admin WITH PASSWORD 'your_admin_password';"
sudo -u postgres psql -c "CREATE DATABASE bigbrotr OWNER admin;"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE bigbrotr TO admin;"
```

### Create application roles

```bash
sudo -u postgres psql -d bigbrotr -c "CREATE ROLE bigbrotr_writer LOGIN PASSWORD 'your_writer_password';"
sudo -u postgres psql -d bigbrotr -c "CREATE ROLE bigbrotr_reader LOGIN PASSWORD 'your_reader_password';"
```

### Apply the schema

The init directory contains SQL files and shell scripts (for roles and grants). Apply SQL files first, then run the shell scripts:

```bash
cd deployments/bigbrotr

# Apply SQL schema files
for f in postgres/init/*.sql; do
    psql -U admin -d bigbrotr -f "$f"
done

# Apply grants (run the shell script manually or apply the SQL equivalent)
psql -U admin -d bigbrotr -c "
    GRANT USAGE ON SCHEMA public TO bigbrotr_writer;
    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO bigbrotr_writer;
    GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO bigbrotr_writer;
    GRANT USAGE ON SCHEMA public TO bigbrotr_reader;
    GRANT SELECT ON ALL TABLES IN SCHEMA public TO bigbrotr_reader;
"
```

!!! tip
    The SQL files in `postgres/init/` are numbered and must be applied in order. The `for` loop handles this automatically. Shell scripts (`01_roles.sh`, `98_grants.sh`) are designed for Docker init and can be adapted for manual deployment as shown above.

## 2. Configure PGBouncer (Recommended)

### Install PGBouncer

```bash
sudo apt install pgbouncer
```

### Configure `/etc/pgbouncer/pgbouncer.ini`

```ini
[databases]
bigbrotr          = host=localhost port=5432 dbname=bigbrotr pool_size=10
bigbrotr_readonly = host=localhost port=5432 dbname=bigbrotr pool_size=8

[pgbouncer]
listen_addr = 127.0.0.1
listen_port = 6432
auth_type = scram-sha-256
auth_user = admin
auth_query = SELECT usename, passwd FROM pg_shadow WHERE usename=$1
pool_mode = transaction
max_client_conn = 200
default_pool_size = 5
reserve_pool_size = 2
```

### Start PGBouncer

```bash
sudo systemctl start pgbouncer && sudo systemctl enable pgbouncer
```

## 3. Set Up the Python Environment

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh  # install uv (one-time)
uv sync --no-dev
```

### Set environment variables

```bash
export DB_WRITER_PASSWORD=your_writer_password
export PRIVATE_KEY=your_hex_key
```

## 4. Run Services

```bash
cd /opt/bigbrotr/deployments/bigbrotr

# Run seeder (one-shot)
python -m bigbrotr seeder --once

# Run long-lived services
python -m bigbrotr finder &
python -m bigbrotr validator &
python -m bigbrotr monitor &
python -m bigbrotr synchronizer &
```

!!! note
    For production use, run services via systemd instead of background shell processes. See the next section.

## 5. Create Systemd Service Files

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
Environment="DB_WRITER_PASSWORD=your_writer_password"
Environment="PRIVATE_KEY=your_hex_key"
ExecStart=/opt/bigbrotr/venv/bin/python -m bigbrotr finder
Restart=always
RestartSec=10

# Security hardening
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
NoNewPrivileges=yes
PrivateDevices=yes

[Install]
WantedBy=multi-user.target
```

Create similar files for `validator`, `monitor`, and `synchronizer`, changing the `Description` and the service name in the `ExecStart` line.

### Enable and start all services

```bash
sudo systemctl daemon-reload
sudo systemctl enable bigbrotr-finder bigbrotr-validator bigbrotr-monitor bigbrotr-synchronizer
sudo systemctl start bigbrotr-finder bigbrotr-validator bigbrotr-monitor bigbrotr-synchronizer
```

### Check service status

```bash
sudo systemctl status bigbrotr-finder
sudo journalctl -u bigbrotr-finder -f
```

!!! warning
    Store secrets in a systemd credential file or environment file (`EnvironmentFile=`) rather than inline `Environment=` directives for production deployments.

---

## Related Documentation

- [Docker Compose Deployment](docker-deploy.md) -- deploy with Docker instead
- [Monitoring Setup](monitoring-setup.md) -- add Prometheus and Grafana
- [Backup and Restore](backup-restore.md) -- automate database backups
- [Troubleshooting](troubleshooting.md) -- resolve common deployment issues
