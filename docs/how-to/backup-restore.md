# Backup and Restore

Automate PostgreSQL backups and restore BigBrotr from a snapshot.

---

## Overview

BigBrotr stores all persistent data in PostgreSQL. Regular backups protect against data loss from hardware failure, accidental deletion, or failed upgrades. This guide covers automated backups with `pg_dump` and restore procedures.

## 1. Create a Backup Script

Create `/opt/bigbrotr/backup.sh`:

```bash
#!/bin/bash
set -euo pipefail

BACKUP_DIR=/opt/bigbrotr/backups
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "${BACKUP_DIR}"

docker compose exec -T postgres pg_dump -U admin -d bigbrotr \
    | gzip > "${BACKUP_DIR}/backup_${TIMESTAMP}.sql.gz"

# Remove backups older than 7 days
find "${BACKUP_DIR}" -name "backup_*.sql.gz" -mtime +7 -delete

echo "Backup completed: backup_${TIMESTAMP}.sql.gz"
```

Make it executable:

```bash
chmod +x /opt/bigbrotr/backup.sh
```

!!! note "Manual deployment"
    If you are not using Docker, replace the `docker compose exec` line with a direct `pg_dump` call:

    ```bash
    pg_dump -U admin -d bigbrotr | gzip > "${BACKUP_DIR}/backup_${TIMESTAMP}.sql.gz"
    ```

## 2. Schedule Automated Backups

Add a crontab entry to run the backup daily at 2:00 AM:

```bash
crontab -e
```

Add this line:

```text
0 2 * * * cd /opt/bigbrotr/deployments/bigbrotr && /opt/bigbrotr/backup.sh >> /opt/bigbrotr/backups/backup.log 2>&1
```

!!! tip
    Adjust the retention period in the backup script (`-mtime +7`) based on your storage capacity. For large databases, consider keeping weekly backups for 30 days.

## 3. Verify Backups

After a backup runs, verify the file is valid:

```bash
# Check the file exists and has a reasonable size
ls -lh /opt/bigbrotr/backups/

# Test decompression (without writing output)
gunzip -t /opt/bigbrotr/backups/backup_20260101_020000.sql.gz

# Inspect the first few lines
gunzip -c /opt/bigbrotr/backups/backup_20260101_020000.sql.gz | head -20
```

!!! warning
    A zero-byte backup file indicates a connection failure. Check that PostgreSQL is running and the credentials are correct.

## 4. Restore from Backup

### Stop application services

Stop all services that write to the database before restoring:

=== "Docker"

    ```bash
    docker compose stop finder validator monitor synchronizer
    ```

=== "Systemd"

    ```bash
    sudo systemctl stop bigbrotr-finder bigbrotr-validator bigbrotr-monitor bigbrotr-synchronizer
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

### Refresh materialized views

After restoring, refresh all materialized views to ensure they reflect the restored data:

```sql
-- Connect to the database
-- Docker: docker compose exec postgres psql -U admin -d bigbrotr
-- Manual: psql -U admin -d bigbrotr

SELECT all_statistics_refresh();
```

This calls the stored function that refreshes all 11 materialized views concurrently.

### Restart services

=== "Docker"

    ```bash
    docker compose start finder validator monitor synchronizer
    ```

=== "Systemd"

    ```bash
    sudo systemctl start bigbrotr-finder bigbrotr-validator bigbrotr-monitor bigbrotr-synchronizer
    ```

## 5. Off-site Backup (Optional)

For disaster recovery, copy backups to a remote location:

```bash
# rsync to a remote server
rsync -az /opt/bigbrotr/backups/ user@backup-server:/backups/bigbrotr/

# Or upload to S3-compatible storage
aws s3 sync /opt/bigbrotr/backups/ s3://my-bucket/bigbrotr-backups/
```

---

## Related Documentation

- [Docker Compose Deployment](docker-deploy.md) -- the database runs inside Docker
- [Manual Deployment](manual-deploy.md) -- database setup for bare-metal installs
- [Troubleshooting](troubleshooting.md) -- diagnose backup and restore issues
