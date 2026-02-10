# BigBrotr

A modular Nostr data archiving and monitoring system.

BigBrotr discovers, monitors, and archives data from the Nostr relay network. Five async services form a processing pipeline:

```
Seeder -> Finder -> Validator -> Monitor -> Synchronizer
```

| Service | Role |
|---------|------|
| **Seeder** | Bootstraps initial relay URLs from a seed file (one-shot) |
| **Finder** | Discovers new relays from events and external APIs |
| **Validator** | Verifies URLs are live Nostr relays via WebSocket |
| **Monitor** | Runs NIP-11 + NIP-66 health checks, publishes kind 10166/30166 events |
| **Synchronizer** | Collects events from relays using cursor-based pagination |

## Key Features

- **Multi-network support**: clearnet, Tor (.onion), I2P (.i2p), Lokinet (.loki)
- **NIP compliance**: NIP-11 relay information, NIP-66 relay monitoring metadata
- **PostgreSQL 16**: 22 stored functions, 7 materialized views, 44 indexes
- **Fully async**: asyncpg, aiohttp, per-network semaphore concurrency control
- **Docker ready**: single parametric Dockerfile for all deployments
- **Type safe**: strict mypy, frozen dataclasses, Pydantic v2 configs

## Quick Start

```bash
# Clone and install
git clone https://github.com/BigBrotr/bigbrotr.git
cd bigbrotr
pip install -e ".[dev]"

# Start infrastructure
docker compose -f deployments/bigbrotr/docker-compose.yaml up -d postgres pgbouncer

# Run the seeder
python -m bigbrotr seeder --once
```

## Documentation

- [Architecture](ARCHITECTURE.md) -- system design, diamond DAG, module reference
- [Configuration](CONFIGURATION.md) -- YAML config reference for all services
- [Database](DATABASE.md) -- schema, stored functions, views, indexes
- [Deployment](DEPLOYMENT.md) -- Docker Compose and manual deployment
- [Development](DEVELOPMENT.md) -- setup, testing, code quality, CI/CD
- [API Reference](reference/index.md) -- auto-generated from source code
