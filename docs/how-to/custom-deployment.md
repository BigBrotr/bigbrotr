# Creating a Custom Deployment

Create a new BigBrotr deployment from the `_template` directory with custom configuration, schema, and Docker settings.

---

## Overview

BigBrotr ships with two ready-made deployments (`bigbrotr` and `lilbrotr`) and a `_template` directory for creating your own. Each deployment is a self-contained directory with configuration, SQL schema, Docker Compose, and monitoring files.

## Step 1: Copy the Template

```bash
cp -r deployments/_template deployments/myproject
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

Edit `config/brotr.yaml`:

```yaml
pool:
  database:
    host: pgbouncer       # Use 'localhost' for manual deployment
    port: 5432
    database: myproject    # Your database name
    user: admin
```

## Step 4: Customize Service Configs

Edit files in `config/services/`:

- `seeder.yaml` -- seed file path and insertion mode
- `finder.yaml` -- discovery interval, API sources, event kinds
- `validator.yaml` -- validation interval, network settings
- `monitor.yaml` -- health check settings, publishing relays
- `synchronizer.yaml` -- sync interval, concurrency, event filters

!!! tip
    The `_template` deployment contains every configuration field with comments. Start by reading the template files, then remove fields where you want the defaults.

## Step 5: Choose a Schema

Edit `postgres/init/02_tables.sql` to select which schema to use:

=== "BigBrotr (full archive)"

    Keep the full event table with all columns (`tags`, `content`, `sig`). This stores complete Nostr events and enables the 7 materialized views.

=== "LilBrotr (lightweight)"

    Use the lightweight event table that stores only `id`, `pubkey`, `created_at`, `kind`, and `tagvalues`. This omits tags JSON, content, and signatures for approximately 60% disk savings. Materialized views are not available.

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
# Edit .env: set DB_PASSWORD, PRIVATE_KEY, GRAFANA_PASSWORD
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
