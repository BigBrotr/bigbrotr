# Troubleshooting

Solutions for common issues and frequently asked questions about BigBrotr.

---

## Common Issues

### "Connection refused"

**Symptom**: Services fail to start with a connection error to the database.

**Solution**:

1. Check that PostgreSQL and PGBouncer are healthy:

    ```bash
    docker compose ps postgres pgbouncer
    docker compose logs postgres
    ```

2. Verify `pool.database.host` in `config/brotr.yaml`:
    - In Docker: use the service name (`pgbouncer` or `postgres`)
    - Outside Docker: use `localhost`

3. Ensure the database port is correct and not blocked by a firewall.

### "DB_WRITER_PASSWORD environment variable not set"

**Symptom**: Service exits immediately on startup with a configuration error about a missing password environment variable.

**Solution**:

Pipeline services (seeder, finder, validator, monitor, synchronizer) use `DB_WRITER_PASSWORD`. Read-only services use `DB_READER_PASSWORD`. Set the appropriate variable:

1. Set the environment variable:

    === "Docker"

        Add `DB_WRITER_PASSWORD` and `DB_READER_PASSWORD` to your `.env` file and verify with:

        ```bash
        docker compose config | grep DB_WRITER_PASSWORD
        ```

    === "Shell"

        ```bash
        export DB_WRITER_PASSWORD=your_secure_password
        ```

    === "Systemd"

        Add to the service file or an `EnvironmentFile`:

        ```ini
        Environment="DB_WRITER_PASSWORD=your_secure_password"
        ```

### "Pool exhausted"

**Symptom**: Queries time out or services log "pool exhausted" warnings.

**Solution**:

1. Increase the pool size in `config/brotr.yaml`:

    ```yaml
    pool:
      limits:
        max_size: 50
    ```

2. Increase the acquisition timeout:

    ```yaml
    pool:
      timeouts:
        acquisition: 30.0
    ```

3. Check for long-running queries:

    ```sql
    SELECT pid, now() - query_start AS duration, query
    FROM pg_stat_activity
    WHERE state = 'active'
    ORDER BY duration DESC;
    ```

### "Timeout connecting to relay"

**Symptom**: Validator or Monitor logs show frequent relay timeout errors.

**Solution**:

1. Increase timeouts in the service config:

    ```yaml
    networks:
      clearnet:
        timeout: 30.0
      tor:
        timeout: 60.0
    ```

2. Reduce concurrency if the host is resource-constrained:

    ```yaml
    networks:
      clearnet:
        max_tasks: 25
      tor:
        max_tasks: 5
    ```

!!! tip
    Tor relays typically need 30--60 seconds for connections. I2P relays may need 45--60 seconds.

### "Out of disk space"

**Symptom**: PostgreSQL stops accepting writes or Docker containers fail to start.

**Solution**:

1. Check disk usage:

    ```bash
    du -sh data/postgres
    docker system df
    ```

2. Run a full vacuum on large tables:

    ```bash
    docker compose exec postgres psql -U admin -d bigbrotr -c "VACUUM FULL event"
    ```

3. Prune unused Docker resources:

    ```bash
    docker system prune -f
    ```

4. Consider switching to LilBrotr for approximately 60% disk savings.

### "Validation error for MonitorConfig"

**Symptom**: Monitor service fails to start with a Pydantic validation error about `store` flags.

**Solution**: The `store` flags must be a subset of the `compute` flags. You cannot store metadata that is not computed:

```yaml
processing:
  compute:
    nip66_geo: true
    nip66_dns: false
  store:
    nip66_geo: true
    nip66_dns: false    # Must be false because compute.nip66_dns is false
```

### Service not starting

**Symptom**: A service container shows as unhealthy or restarts repeatedly.

**Solution**:

1. Check the logs:

    ```bash
    docker compose logs finder
    ```

2. Inspect the health check status:

    ```bash
    docker inspect bigbrotr-finder --format='{{json .State.Health}}'
    ```

3. Try running the service in one-shot mode with debug logging:

    ```bash
    python -m bigbrotr finder --once --log-level DEBUG
    ```

---

## Frequently Asked Questions

### What is the difference between BigBrotr and LilBrotr?

**BigBrotr** stores complete Nostr events including `tags` (JSON), `content`, and `sig`. It provides 11 materialized views for analytics and uses more disk space.

**LilBrotr** stores only event metadata: `id`, `pubkey`, `created_at`, `kind`, and `tagvalues` (extracted single-char tag values). It omits tags JSON, content, and signatures, resulting in approximately 60% disk savings. Materialized views are not available.

Both use the same service pipeline and codebase. The only difference is the SQL schema.

### Do I need to run all five services?

No. The only required services are:

- **Seeder** (one-shot) -- populates the initial candidate list
- **Finder** -- discovers new relay URLs
- **Validator** -- tests connectivity and promotes candidates to the relay table

The remaining services are optional:

- **Monitor** -- performs NIP-11/NIP-66 health checks and publishes Nostr events. Required if you want relay metadata.
- **Synchronizer** -- archives events from validated relays. Required only if you want to store Nostr events.

### How much disk space does BigBrotr use?

Disk usage depends on the number of relays monitored and events archived:

| Component | Approximate size |
|-----------|-----------------|
| PostgreSQL base (schema + indexes) | ~50 MB |
| Relay metadata (1000 relays) | ~200 MB |
| Events (1M events, BigBrotr schema) | ~2--5 GB |
| Events (1M events, LilBrotr schema) | ~0.8--2 GB |

!!! tip
    Use the `synchronizer.yaml` `filter.kinds` setting to archive only specific event kinds, reducing storage significantly.

### What happens when a service crashes?

All long-running services (`finder`, `validator`, `monitor`, `synchronizer`) have `restart: unless-stopped` in Docker Compose. When a service crashes:

1. Docker restarts the container automatically after `RestartSec` (10s default).
2. The service picks up where it left off using cursor state stored in the `service_state` table.
3. After `max_consecutive_failures` (default: 5) consecutive failures, the service stops to avoid a crash loop.

For systemd deployments, the `Restart=always` directive provides the same behavior.

### How do I upgrade to a new version?

1. Pull the latest code:

    ```bash
    git pull origin main
    ```

2. Check the changelog for breaking changes or new migration steps.

3. Rebuild and restart:

    === "Docker"

        ```bash
        cd deployments/bigbrotr
        docker compose build --no-cache
        docker compose up -d
        ```

    === "Manual"

        ```bash
        uv sync --no-dev
        sudo systemctl restart bigbrotr-finder bigbrotr-validator bigbrotr-monitor bigbrotr-synchronizer
        ```

4. If the upgrade includes SQL migrations, apply them before restarting services:

    ```bash
    psql -U admin -d bigbrotr -f migrations/XXXX_description.sql
    ```

---

## Related Documentation

- [Docker Compose Deployment](docker-deploy.md) -- deployment reference
- [Manual Deployment](manual-deploy.md) -- systemd and bare-metal setup
- [Monitoring Setup](monitoring-setup.md) -- verify service health with Prometheus
- [Backup and Restore](backup-restore.md) -- protect against data loss
- [Tor and Overlay Networks](tor-relays.md) -- diagnose overlay network issues
