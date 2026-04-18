# Manual Deployment

Install and run BigBrotr directly on a Linux host without Docker, while still
reusing the built-in deployment contract and generated SQL package.

---

## Overview

The manual path is best when:

- Docker is unavailable or undesirable;
- you want direct systemd control over the services;
- you still want to stay close to a built-in deployment profile.

The cleanest mental model is:

- start from the built-in `deployments/bigbrotr/` or `deployments/lilbrotr/`
  folder;
- reuse its `config/` tree and generated `postgres/init/` package;
- recreate the database roles, grants, and service runtime outside Docker.

This guide assumes the `bigbrotr` reference deployment. For `lilbrotr`, swap
the deployment name, database name, and port defaults accordingly.

---

## Prerequisites

- Ubuntu 22.04+ or Debian 12+ (other Linux distributions work with equivalent
  packages)
- Python 3.11+
- PostgreSQL 18+
- PgBouncer (strongly recommended)
- Git

---

## 1. Prepare the Checkout and Deployment Root

```bash
git clone https://github.com/BigBrotr/bigbrotr.git
cd bigbrotr
```

Use the built-in deployment folder as the operator source of truth:

- `deployments/bigbrotr/config/`
- `deployments/bigbrotr/postgres/init/`
- `deployments/bigbrotr/static/`

If you are building a custom manual deployment, copy a built-in deployment
first and keep its local `README.md` files accurate as the deployment diverges.

---

## 2. Set Up PostgreSQL

### Install and start PostgreSQL

```bash
sudo apt update
sudo apt install postgresql-18 postgresql-contrib-18
sudo systemctl enable --now postgresql
```

### Create the admin role and database

```bash
sudo -u postgres psql -c "CREATE USER admin WITH PASSWORD 'your_admin_password';"
sudo -u postgres psql -c "CREATE DATABASE bigbrotr OWNER admin;"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE bigbrotr TO admin;"
```

### Apply the generated SQL package

The built-in deployment already ships a generated SQL package under
`deployments/bigbrotr/postgres/init/`.

Apply the `.sql` files in numeric order:

```bash
cd deployments/bigbrotr

for f in postgres/init/*.sql; do
    psql -U admin -d bigbrotr -f "$f"
done
```

!!! note
    The generated `.sql` files are derived artifacts. If the schema itself
    must change, change the SQL templates and regenerate the package rather
    than hand-maintaining `postgres/init/`.

### Create the application roles

The runtime uses four PostgreSQL roles:

- `writer`
- `reader`
- `refresher`
- `ranker`

Create them explicitly:

```bash
sudo -u postgres psql -d bigbrotr -c "CREATE ROLE writer LOGIN PASSWORD 'writer_password';"
sudo -u postgres psql -d bigbrotr -c "CREATE ROLE reader LOGIN PASSWORD 'reader_password';"
sudo -u postgres psql -d bigbrotr -c "CREATE ROLE refresher LOGIN PASSWORD 'refresher_password';"
sudo -u postgres psql -d bigbrotr -c "CREATE ROLE ranker LOGIN PASSWORD 'ranker_password';"
```

### Apply grants

The Docker deployment normally executes `01_roles.sh` and `98_grants.sh` for
you. In a manual deployment, mirror that contract by granting:

- `writer`: DML + function execution on shared archive and writer-owned facts
- `reader`: read-only access for Api, Dvm, and monitoring
- `refresher`: read access to sources plus DML/EXECUTE on derived tables and
  refresh functions
- `ranker`: read access to ranking inputs plus DML on public score tables

The authoritative grant logic lives in:

- `deployments/bigbrotr/postgres/init/01_roles.sh`
- `deployments/bigbrotr/postgres/init/98_grants.sh`

For a serious manual deployment, transcribe that logic into your DBA-managed
bootstrap procedure rather than inventing a smaller local permission model.

---

## 3. Configure PgBouncer

PgBouncer is strongly recommended even outside Docker.

### Install PgBouncer

```bash
sudo apt install pgbouncer
```

### Configure `/etc/pgbouncer/pgbouncer.ini`

```ini
[databases]
bigbrotr          = host=127.0.0.1 port=5432 dbname=bigbrotr pool_size=10
bigbrotr_readonly = host=127.0.0.1 port=5432 dbname=bigbrotr pool_size=8

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

Start and enable the service:

```bash
sudo systemctl enable --now pgbouncer
```

---

## 4. Install BigBrotr and Create the Runtime Environment

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync --frozen
```

Store runtime secrets in an environment file such as
`/etc/bigbrotr/bigbrotr.env`:

```bash
sudo install -d -m 700 /etc/bigbrotr
sudo tee /etc/bigbrotr/bigbrotr.env >/dev/null <<'EOF'
DB_WRITER_PASSWORD=writer_password
DB_READER_PASSWORD=reader_password
DB_REFRESHER_PASSWORD=refresher_password
DB_RANKER_PASSWORD=ranker_password
NOSTR_PRIVATE_KEY_MONITOR=
NOSTR_PRIVATE_KEY_SYNCHRONIZER=
NOSTR_PRIVATE_KEY_DVM=
NOSTR_PRIVATE_KEY_ASSERTOR=
EOF
sudo chmod 600 /etc/bigbrotr/bigbrotr.env
```

### Update the built-in config for host paths

The built-in configs assume the Docker deployment layout.
For manual deployment, review these files at minimum:

- `deployments/bigbrotr/config/brotr.yaml`
- `deployments/bigbrotr/config/services/*.yaml`

Common manual changes include:

- `pool.database.host: 127.0.0.1` (or your PgBouncer host)
- ranker writable paths under `storage.path` and `storage.checkpoint_path`
- host-level paths for static assets if your working directory differs from the
  deployment root

For the Ranker specifically, choose a writable private-store location such as:

```yaml
storage:
  path: /var/lib/bigbrotr/ranker/ranker.duckdb
  checkpoint_path: /var/lib/bigbrotr/ranker/ranker.checkpoint.json
```

---

## 5. Run Services Manually

From the repository root, you can reuse the built-in profile directly:

```bash
# One-shot bootstrap
python -m bigbrotr seeder --profile bigbrotr --once

# Long-lived services
python -m bigbrotr finder --profile bigbrotr
python -m bigbrotr validator --profile bigbrotr
python -m bigbrotr monitor --profile bigbrotr
python -m bigbrotr synchronizer --profile bigbrotr
python -m bigbrotr refresher --profile bigbrotr
python -m bigbrotr ranker --profile bigbrotr
python -m bigbrotr assertor --profile bigbrotr
python -m bigbrotr api --profile bigbrotr
python -m bigbrotr dvm --profile bigbrotr
```

For a copied custom deployment, use explicit config paths:

```bash
python -m bigbrotr finder \
  --brotr-config deployments/myproject/config/brotr.yaml \
  --config deployments/myproject/config/services/finder.yaml
```

---

## 6. Create systemd Units

Use systemd for production-grade manual deployment.

Create a reusable environment file reference and run each service from the repo
checkout:

```ini
[Unit]
Description=BigBrotr Finder
After=network.target postgresql.service pgbouncer.service

[Service]
Type=simple
User=bigbrotr
Group=bigbrotr
WorkingDirectory=/opt/bigbrotr
EnvironmentFile=/etc/bigbrotr/bigbrotr.env
ExecStart=/opt/bigbrotr/.venv/bin/python -m bigbrotr finder --profile bigbrotr
Restart=always
RestartSec=10

ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
NoNewPrivileges=yes
PrivateDevices=yes

[Install]
WantedBy=multi-user.target
```

Create equivalent units for:

- `validator`
- `monitor`
- `synchronizer`
- `refresher`
- `ranker`
- `assertor`
- `api`
- `dvm`

Seeder is normally one-shot and can be run manually when bootstrapping or when
you explicitly want to reseed candidates.

Enable and start the services:

```bash
sudo systemctl daemon-reload
sudo systemctl enable bigbrotr-finder bigbrotr-validator bigbrotr-monitor \
    bigbrotr-synchronizer bigbrotr-refresher bigbrotr-ranker \
    bigbrotr-assertor bigbrotr-api bigbrotr-dvm
sudo systemctl start bigbrotr-finder bigbrotr-validator bigbrotr-monitor \
    bigbrotr-synchronizer bigbrotr-refresher bigbrotr-ranker \
    bigbrotr-assertor bigbrotr-api bigbrotr-dvm
```

!!! warning
    Prefer `EnvironmentFile=` or systemd credentials over inline `Environment=`
    secrets for production deployments.

---

## 7. Verify the Deployment

```bash
# Service health
sudo systemctl status bigbrotr-finder
sudo journalctl -u bigbrotr-refresher -f

# Database connectivity
psql -h 127.0.0.1 -p 6432 -U reader -d bigbrotr -c "SELECT COUNT(*) FROM relay;"

# CLI sanity
python -m bigbrotr --help
```

For operator-facing metrics and dashboards, continue with
[Monitoring Setup](monitoring-setup.md).

---

## Related Documentation

- [Docker Compose Deployment](docker-deploy.md) -- use the bundled container deployment instead
- [Monitoring Setup](monitoring-setup.md) -- connect Prometheus, Alertmanager, and Grafana
- [Backup and Restore](backup-restore.md) -- protect and recover your PostgreSQL data
- [Troubleshooting](troubleshooting.md) -- diagnose common startup and runtime issues
