# BigBrotr

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![PostgreSQL 16](https://img.shields.io/badge/PostgreSQL-16-blue.svg)](https://www.postgresql.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Documentation](https://img.shields.io/badge/docs-latest-brightgreen.svg)](https://bigbrotr.github.io/bigbrotr/)

**A modular Nostr relay discovery, monitoring, and event archiving system.**

BigBrotr continuously discovers Nostr relays across all network types, validates their connectivity, performs comprehensive health checks, and archives events from the relay network. Built on Python 3.11+ with strict typing, asyncio, and PostgreSQL 16.

---

## How It Works

Eight independent async services share a PostgreSQL database, each with a distinct role in the discovery-monitoring-archiving workflow:

--8<-- "docs/_snippets/pipeline.md"

--8<-- "docs/_snippets/service-table.md"

## Key Features

<div class="grid cards" markdown>

-   :material-earth:{ .lg .middle } **Multi-Network Support**

    ---

    Discover and monitor relays across clearnet, Tor (.onion), I2P (.i2p), and Lokinet (.loki) networks with per-network concurrency control.

-   :material-shield-check:{ .lg .middle } **NIP Compliance**

    ---

    Full NIP-11 relay information and NIP-66 relay monitoring (RTT, SSL, DNS, GeoIP, HTTP, network ASN) with kind 10166/30166 event publishing.

-   :material-database:{ .lg .middle } **PostgreSQL Backend**

    ---

    25 stored functions, 11 materialized views, 44 indexes. Content-addressed metadata with SHA-256 deduplication.

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

The codebase follows a strict Diamond DAG -- imports flow strictly downward:

--8<-- "docs/_snippets/dag-diagram.md"

| Layer | Responsibility | I/O |
|-------|---------------|-----|
| **models** | Pure frozen dataclasses, enums, type definitions | None |
| **core** | Pool, Brotr, BaseService, Logger, Metrics | Database |
| **nips** | NIP-11 info fetch, NIP-66 health checks | HTTP, DNS, SSL, WebSocket, GeoIP |
| **utils** | DNS resolution, key management, WebSocket transport | Network |
| **services** | Business logic: Seeder, Finder, Validator, Monitor, Synchronizer | All |

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

## Documentation Guide

| Looking for... | Go to... |
|---------------|----------|
| First-time setup and installation | [Getting Started](getting-started/index.md) |
| System design, architecture, configuration | [User Guide](user-guide/index.md) |
| Step-by-step deployment and operational procedures | [How-to Guides](how-to/index.md) |
| Development environment, testing, contributing | [Development](development/index.md) |
| Python API documentation (auto-generated) | [API Reference](reference/index.md) |
| Version history | [Changelog](changelog.md) |
