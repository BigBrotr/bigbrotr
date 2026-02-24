# Creating a Custom Deployment

Create a new deployment from the `bigbrotr` base with custom configuration, schema, and Docker settings.

---

## Overview

BigBrotr ships with two deployments: `bigbrotr` (full event archive) and `lilbrotr` (lightweight, omits tags/content/sig). To create your own, copy `bigbrotr` and customize. Each deployment is a self-contained directory with configuration, SQL schema, Docker Compose, and monitoring files.

## Step 1: Copy the Template

```bash
cp -r deployments/bigbrotr deployments/myproject
cd deployments/myproject
```

## Step 2: Configure Docker Compose

Edit `docker-compose.yaml`:

1. Update container name prefixes (e.g., `myproject-postgres`)
2. Set unique port mappings to avoid conflicts with existing deployments
3. Update the database name in service environment variables
4. Set the `DEPLOYMENT` build argument:

```yaml
services:
  finder:
    build:
      context: ../..
      dockerfile: deployments/Dockerfile
      args:
        DEPLOYMENT: myproject
```

## Step 3: Configure the Database Connection

Edit `config/brotr.yaml` with shared connection settings:

```yaml
pool:
  database:
    host: pgbouncer       # Use 'localhost' for manual deployment
    database: myproject    # Your database name
```

Per-service pool settings (user, password, pool sizing) are configured in each service's YAML file. See Step 4.

## Step 4: Customize Service Configs

Edit files in `config/services/`. Each service config includes a `pool:` section for per-service database role and pool sizing:

```yaml
# config/services/finder.yaml
pool:
  user: myproject_writer           # Database role for this service
  password_env: DB_WRITER_PASSWORD # Env var with the role's password
  min_size: 1
  max_size: 3

# ... service-specific config below
```

Service files to customize:

- `seeder.yaml` -- seed file path and insertion mode
- `finder.yaml` -- discovery interval, API sources, event kinds
- `validator.yaml` -- validation interval, network settings
- `monitor.yaml` -- health check settings, publishing relays
- `synchronizer.yaml` -- sync interval, concurrency, event filters

!!! tip
    See the [Configuration](configuration.md) reference for all available fields and their defaults.

## Step 5: Choose a Schema

Edit `postgres/init/02_tables.sql` to select which schema to use:

=== "BigBrotr (full archive)"

    Keep the full event table with all columns (`tags`, `content`, `sig`). This stores complete Nostr events and enables the 11 materialized views.

=== "LilBrotr (lightweight)"

    Use the lightweight event table that stores only `id`, `pubkey`, `created_at`, `kind`, and `tagvalues`. This omits tags JSON, content, and signatures for approximately 60% disk savings. All 11 materialized views are still available.

## Step 6: Set Up the Seed File

Edit `static/seed_relays.txt` with your initial relay URLs (one per line):

```text
wss://relay.damus.io
wss://relay.nostr.band
wss://nos.lol
```

## Step 7: Create the Environment File

```bash
cp .env.example .env
# Edit .env: set DB_ADMIN_PASSWORD, DB_WRITER_PASSWORD, DB_READER_PASSWORD, PRIVATE_KEY, GRAFANA_PASSWORD
chmod 600 .env
```

## Step 8: Build and Start

```bash
# Build the Docker image with your deployment name
docker compose build

# Start the stack
docker compose up -d

# Verify
docker compose ps
docker compose logs -f seeder
```

## Step 9: Test the Deployment

```bash
# Check that the database schema was applied
docker compose exec postgres psql -U admin -d myproject -c "\dt"

# Verify roles were created
docker compose exec postgres psql -U admin -d myproject -c \
    "SELECT rolname FROM pg_roles WHERE rolname LIKE 'myproject_%'"

# Check that the seeder populated candidates
docker compose logs seeder

# Verify services are healthy
docker compose ps
```

!!! note
    If you need to reset and start fresh, run `docker compose down -v` to remove all containers and volumes, then `docker compose up -d` again.

---

## Related Documentation

- [Docker Compose Deployment](docker-deploy.md) -- deploy the standard BigBrotr stack
- [Adding a New Service](new-service.md) -- add a custom service to your deployment
- [Monitoring Setup](monitoring-setup.md) -- configure Prometheus and Grafana
- [Troubleshooting](troubleshooting.md) -- resolve common deployment issues
