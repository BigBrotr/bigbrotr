# BigBrotr

**Modular Nostr network observatory.**

BigBrotr discovers relays across clearnet, Tor, I2P, and Lokinet, validates their connectivity, runs NIP-11 and NIP-66 health checks, archives events, materializes analytics views, and exposes everything through a REST API and a NIP-90 Data Vending Machine. Eight independent async services share a PostgreSQL 18 backend, each deployable and scalable on its own. Built on Python 3.11+ with strict typing and asyncio.

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![PostgreSQL 18](https://img.shields.io/badge/PostgreSQL-18-blue.svg)](https://www.postgresql.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Documentation](https://img.shields.io/badge/docs-latest-brightgreen.svg)](https://bigbrotr.github.io/bigbrotr/)

---

## How It Works

Eight independent async services share a PostgreSQL database, each with a distinct role in the discovery-monitoring-archiving pipeline:

--8<-- "docs/_snippets/pipeline.md"

--8<-- "docs/_snippets/service-table.md"

## Key Features

<div class="grid cards" markdown>

-   :material-earth:{ .lg .middle } **Multi-Network Discovery**

    ---

    Discover and monitor relays across clearnet, Tor, I2P, and Lokinet with per-network concurrency control and proxy routing.

-   :material-shield-check:{ .lg .middle } **NIP-11 & NIP-66 Compliance**

    ---

    Full relay information documents and six health check types with kind 10166/30166 event publishing.

-   :material-database:{ .lg .middle } **PostgreSQL Backend**

    ---

    25 stored functions, 11 materialized views, content-addressed metadata with SHA-256 deduplication.

-   :material-lightning-bolt:{ .lg .middle } **Fully Async**

    ---

    asyncpg connection pooling, aiohttp HTTP client, per-network semaphore concurrency, graceful shutdown.

-   :material-docker:{ .lg .middle } **Docker Ready**

    ---

    Single parametric Dockerfile for all deployments. Full monitoring stack with Prometheus and Grafana.

-   :material-language-python:{ .lg .middle } **Type Safe**

    ---

    Strict mypy, frozen dataclasses with `slots=True`, Pydantic v2 configuration models.

</div>

## Architecture

The codebase follows a strict Diamond DAG — imports flow strictly downward:

--8<-- "docs/_snippets/dag-diagram.md"

| Layer | Responsibility | I/O |
|-------|---------------|-----|
| **models** | Pure frozen dataclasses, enums, type definitions | None |
| **core** | Pool, Brotr, BaseService, Logger, Metrics | Database |
| **nips** | NIP-11 info fetch, NIP-66 health checks | HTTP, DNS, SSL, WebSocket, GeoIP |
| **utils** | DNS resolution, key management, WebSocket transport | Network |
| **services** | Business logic: discovery, validation, monitoring, archiving | All |

## Quick Start

```bash
git clone https://github.com/BigBrotr/bigbrotr.git
cd bigbrotr
curl -LsSf https://astral.sh/uv/install.sh | sh  # install uv (one-time)
uv sync --group dev
docker compose -f deployments/bigbrotr/docker-compose.yaml up -d postgres pgbouncer
python -m bigbrotr seeder --once
```

For a complete walkthrough, see the [Getting Started](getting-started/index.md) guide.

## Documentation

| Section | Description |
|---------|-------------|
| [Getting Started](getting-started/index.md) | Installation, quick start tutorial, and first deployment |
| [User Guide](user-guide/index.md) | Architecture, services, configuration, database, and monitoring |
| [How-to Guides](how-to/index.md) | Docker deployment, Tor support, backups, and troubleshooting |
| [Development](development/index.md) | Dev setup, testing, coding standards, and contributing |
| [API Reference](reference/index.md) | Auto-generated Python API documentation |
| [Changelog](changelog.md) | Version history and release notes |
