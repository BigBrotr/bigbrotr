# Creating a Custom Deployment

Create a new deployment from one of the built-in reference deployments with
custom configuration, schema, and Docker settings.

---

## Overview

BigBrotr ships with two reference deployments:

- `bigbrotr` for the full archive profile
- `lilbrotr` for the lightweight archive profile

To create your own, copy the reference deployment that is closest to the shape
you want and customize it. Each deployment is a self-contained directory with
configuration, generated PostgreSQL init files, Docker Compose, and local
operator assets.

## Step 1: Copy the Template

```bash
cp -r deployments/bigbrotr deployments/myproject
cd deployments/myproject
```

If you want the lightweight storage profile instead, start from
`deployments/lilbrotr`.

The copied reference deployment already includes local `README.md` files at the
deployment root and in the config folders. Keep those files honest as you make
the new deployment diverge from the reference shape.

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
    database: myproject   # Your database name
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
- `refresher.yaml` -- current-state, analytics, periodic refresh targets, and cycle budgets
- `api.yaml` -- REST API host, port, and protocol exposure policy for public readable resources
- `dvm.yaml` -- Nostr relays, protocol exposure policy with pricing, and NIP-90 kind

!!! tip
    See the [Configuration](../user-guide/configuration.md) reference for all available fields and their defaults.

!!! note
    The built-in CLI `--profile` flag only knows the shipped `bigbrotr` and
    `lilbrotr` deployments. For a custom deployment like `myproject`, run
    services with explicit config paths:

    ```bash
    python -m bigbrotr finder \
      --brotr-config deployments/myproject/config/brotr.yaml \
      --config deployments/myproject/config/services/finder.yaml
    ```

## Step 5: Choose and Maintain the SQL Package

The files in `postgres/init/` are generated deployment artifacts. Do **not**
hand-edit `02_tables_core.sql` or the other generated `.sql` files and expect
those changes to survive regeneration.

For most custom deployments, the right move is simply:

- start from `deployments/bigbrotr` if you want the full archive profile;
- start from `deployments/lilbrotr` if you want the lightweight archive profile;
- keep the copied `postgres/init/` package as your deployment's SQL package.

If you need to customize the schema itself, make the change in the SQL template
system:

1. add or update deployment-specific templates under
   `tools/templates/sql/<deployment>/`;
2. register that deployment name in `tools/generate_sql.py`;
3. regenerate the SQL package with:

```bash
python tools/generate_sql.py
```

The generator renders the deployment-local files in:

- `deployments/<deployment>/postgres/init/*.sql`

This keeps the checked-in SQL package aligned with the actual template source
of truth.

!!! note
    The built-in SQL generator currently knows the shipped deployment names
    `bigbrotr` and `lilbrotr`. A custom deployment that needs its own SQL
    generation path must be added explicitly to `tools/generate_sql.py`.

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
# Edit .env: set DB_ADMIN_PASSWORD, DB_WRITER_PASSWORD, DB_REFRESHER_PASSWORD,
# DB_READER_PASSWORD, GRAFANA_PASSWORD, and optionally the per-service
# Nostr keys NOSTR_PRIVATE_KEY_MONITOR, NOSTR_PRIVATE_KEY_SYNCHRONIZER,
# NOSTR_PRIVATE_KEY_DVM, NOSTR_PRIVATE_KEY_ASSERTOR
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

## Step 10: Add Local Operator Notes

Keep the copied local `README.md` files accurate. At minimum, the
deployment-local `README.md` should explain:

- what this deployment is for;
- which reference deployment it started from;
- whether it uses the full or lightweight storage profile;
- any custom SQL-template overrides, protocol-exposure limits, or operational
  differences.

If the copied `config/README.md` or `config/services/README.md` files stop being
true after your changes, update them too. Those local docs are the fastest way
to keep a deployment self-explanatory for future operators.

---

## Related Documentation

- [Docker Compose Deployment](docker-deploy.md) -- deploy the standard BigBrotr stack
- [Adding a New Service](new-service.md) -- add a custom service to your deployment
- [Monitoring Setup](monitoring-setup.md) -- configure Prometheus and Grafana
- [Troubleshooting](troubleshooting.md) -- resolve common deployment issues
