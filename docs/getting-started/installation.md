# Installation

System requirements and three installation paths depending on how you plan to use BigBrotr.

---

## System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU | 2 cores | 4+ cores |
| RAM | 4 GB | 8+ GB |
| Disk | 20 GB SSD | 100+ GB SSD |
| OS | Linux, macOS, WSL2 | Linux (Debian/Ubuntu) |

## Install Paths

Choose the path that matches your use case:

=== "Docker Only (recommended for running)"

    The simplest path -- Docker handles Python, PostgreSQL, PGBouncer, and all services.
    You only need Docker and Docker Compose installed.

    ```bash
    # Clone the repository
    git clone https://github.com/BigBrotr/bigbrotr.git
    cd bigbrotr/deployments/bigbrotr

    # Configure secrets
    cp .env.example .env
    # Edit .env: set DB_ADMIN_PASSWORD, DB_WRITER_PASSWORD, DB_REFRESHER_PASSWORD, DB_READER_PASSWORD, NOSTR_PRIVATE_KEY, GRAFANA_PASSWORD

    # Start the full stack
    docker compose up -d
    ```

    !!! note
        This is all you need for a production deployment. See [First Deployment](first-deployment.md)
        for a detailed walkthrough including secret generation and verification.

=== "Hybrid (recommended for development)"

    Install Python dependencies locally for development and testing, while running
    PostgreSQL and PGBouncer in Docker containers.

    ```bash
    # Clone and install Python package
    git clone https://github.com/BigBrotr/bigbrotr.git
    cd bigbrotr
    curl -LsSf https://astral.sh/uv/install.sh | sh  # install uv (one-time)
    uv sync --group dev

    # Start infrastructure only
    docker compose -f deployments/bigbrotr/docker-compose.yaml up -d postgres pgbouncer
    ```

    !!! tip
        The `dev` dependency group installs pytest, ruff, mypy, and all other development
        tools. See [Quick Start](quickstart.md) to run your first service.

=== "Full Manual"

    Install everything natively -- no Docker required. Suitable for environments
    where Docker is unavailable.

    ```bash
    # 1. Install PostgreSQL 16
    sudo apt update && sudo apt install postgresql-16 postgresql-contrib-16
    sudo systemctl start postgresql && sudo systemctl enable postgresql

    # 2. Create database and user
    sudo -u postgres psql -c "CREATE USER admin WITH PASSWORD 'your_password';"
    sudo -u postgres psql -c "CREATE DATABASE bigbrotr OWNER admin;"
    sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE bigbrotr TO admin;"

    # 3. Apply schema
    cd deployments/bigbrotr
    for f in postgres/init/*.sql; do
        psql -U admin -d bigbrotr -f "$f"
    done

    # 4. (Optional) Install PGBouncer for connection pooling
    sudo apt install pgbouncer

    # 5. Install BigBrotr
    cd ../..
    curl -LsSf https://astral.sh/uv/install.sh | sh  # install uv (one-time)
    uv sync --group dev
    ```

    !!! warning
        Without PGBouncer, services connect directly to PostgreSQL. This works for
        development but is not recommended for production workloads. See the
        [Deployment Guide](../how-to/docker-deploy.md) for PGBouncer configuration details.

## Verify Installation

After any install path, confirm the CLI is available:

```bash
python -m bigbrotr --help
```

Expected output:

```text
usage: python -m bigbrotr [-h] {seeder,finder,validator,monitor,synchronizer,refresher,api,dvm} ...

BigBrotr - Nostr relay discovery, monitoring, and event archiving
```

## Next Steps

- [Quick Start](quickstart.md) -- Run services locally step by step
- [First Deployment](first-deployment.md) -- Full Docker Compose deployment with monitoring

---

## Related Documentation

- [Quick Start](quickstart.md) -- Run each service step by step
- [First Deployment](first-deployment.md) -- Full stack Docker deployment
- [Development Setup](../development/setup.md) -- Testing, linting, and contributing
- [Configuration Reference](../user-guide/configuration.md) -- YAML configuration details
