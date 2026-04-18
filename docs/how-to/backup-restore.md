# Backup and Restore

Automate PostgreSQL backups and restore BigBrotr from a snapshot.

---

## Overview

BigBrotr stores all persistent data in PostgreSQL. Regular backups protect against data loss from hardware failure, accidental deletion, or failed upgrades. This guide covers automated backups with `pg_dump` and restore procedures.

## 1. Use the Deployment-Local Backup Script

The built-in deployments already ship a backup helper:

- `deployments/bigbrotr/backup.sh`
- `deployments/lilbrotr/backup.sh`

From the deployment root:

```bash
cd deployments/bigbrotr
chmod +x backup.sh
./backup.sh
```

The script:

- reads deployment-local secrets from `.env`;
- dumps PostgreSQL through the deployment-local container name;
- writes compressed dumps into `dumps/`;
- keeps the newest seven dumps by default.

!!! note "Manual deployment"
    If you are not using Docker, replace the `docker compose exec` line with a direct `pg_dump` call:

    ```bash
    pg_dump -U admin -d bigbrotr | gzip > "${BACKUP_DIR}/backup_${TIMESTAMP}.sql.gz"
    ```

## 2. Schedule Automated Backups

Add a crontab entry to run the deployment-local script daily at 2:00 AM:

```bash
crontab -e
```

Add this line:

```text
0 2 * * * cd /opt/bigbrotr/deployments/bigbrotr && ./backup.sh >> ./dumps/backup.log 2>&1
```

!!! tip
    Adjust the retention period in the backup script (`-mtime +7`) based on your storage capacity. For large databases, consider keeping weekly backups for 30 days.

## 3. Verify Backups

After a backup runs, verify the file is valid:

```bash
# Check the file exists and has a reasonable size
ls -lh deployments/bigbrotr/dumps/

# Test decompression (without writing output)
gunzip -t deployments/bigbrotr/dumps/bigbrotr_20260101_020000.sql.gz

# Inspect the first few lines
gunzip -c deployments/bigbrotr/dumps/bigbrotr_20260101_020000.sql.gz | head -20
```

!!! warning
    A zero-byte backup file indicates a connection failure. Check that PostgreSQL is running and the credentials are correct.

## 4. Restore from Backup

### Stop application services

Stop all services that read from or write to the deployment before restoring:

=== "Docker"

    ```bash
    docker compose stop finder validator monitor synchronizer refresher ranker assertor api dvm
    ```

=== "Systemd"

    ```bash
    sudo systemctl stop bigbrotr-finder bigbrotr-validator bigbrotr-monitor bigbrotr-synchronizer bigbrotr-refresher bigbrotr-ranker bigbrotr-assertor bigbrotr-api bigbrotr-dvm
    ```

### Restore the database

=== "Docker"

    ```bash
    gunzip -c backup.sql.gz | docker compose exec -T postgres psql -U admin -d bigbrotr
    ```

=== "Manual"

    ```bash
    gunzip -c backup.sql.gz | psql -U admin -d bigbrotr
    ```

### Reset the ranker's private store if the snapshot is older

The Ranker keeps a private DuckDB working store and checkpoint outside
PostgreSQL. If you restore PostgreSQL to an earlier point in time, remove that
private store before restarting the Ranker so it can resync cleanly from the
restored canonical facts.

=== "Docker"

    ```bash
    rm -rf deployments/bigbrotr/data/ranker/*
    ```

=== "Manual"

    Remove the files pointed to by `ranker.yaml`:

    - `storage.path`
    - `storage.checkpoint_path`

    and any surrounding writable directory you use for the Ranker's private
    state.

### Refresh derived analytics state

After restoring, refresh narrow current winner tables, shared analytics facts,
operational contact-graph facts, and periodic reconciliation targets to ensure
they reflect the restored data. The simplest approach is to run the Refresher
service once before bringing the rest of the stack back:

```bash
# Docker
docker compose up -d refresher

# Manual
python -m bigbrotr refresher --profile bigbrotr --once
```

Alternatively, connect to the database and call the individual refresh
functions manually. Incremental current-state and analytics refresh functions
require `(after, until)` range parameters; periodic reconciliation functions
take no arguments.

### Restart services

=== "Docker"

    ```bash
    docker compose start finder validator monitor synchronizer refresher ranker assertor api dvm
    ```

=== "Systemd"

    ```bash
    sudo systemctl start bigbrotr-finder bigbrotr-validator bigbrotr-monitor bigbrotr-synchronizer bigbrotr-refresher bigbrotr-ranker bigbrotr-assertor bigbrotr-api bigbrotr-dvm
    ```

## 5. Off-site Backup (Optional)

For disaster recovery, copy backups to a remote location:

```bash
# rsync to a remote server
rsync -az deployments/bigbrotr/dumps/ user@backup-server:/backups/bigbrotr/

# Or upload to S3-compatible storage
aws s3 sync deployments/bigbrotr/dumps/ s3://my-bucket/bigbrotr-backups/
```

---

## Related Documentation

- [Docker Compose Deployment](docker-deploy.md) -- the database runs inside Docker
- [Manual Deployment](manual-deploy.md) -- database setup for bare-metal installs
- [Troubleshooting](troubleshooting.md) -- diagnose backup and restore issues
