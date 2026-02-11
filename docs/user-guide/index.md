# User Guide

In-depth reference documentation for BigBrotr's architecture, services, configuration, database, and monitoring.

---

## Sections

| Page | Description |
|------|-------------|
| [Architecture](architecture.md) | Diamond DAG layer structure, design patterns, concurrency model, and testing architecture |
| [Service Pipeline](pipeline.md) | Deep dive into the five-service pipeline: Seeder, Finder, Validator, Monitor, Synchronizer |
| [Configuration](configuration.md) | Complete YAML configuration reference with Pydantic validation and examples |
| [Database](database.md) | PostgreSQL schema, stored functions, materialized views, and indexes |
| [Monitoring](monitoring.md) | Prometheus metrics, alerting rules, Grafana dashboards, and structured logging |

---

## Quick Navigation

- **New to BigBrotr?** Start with [Architecture](architecture.md) for the system overview, then [Service Pipeline](pipeline.md) to understand data flow.
- **Deploying?** See [Configuration](configuration.md) for YAML reference and [Monitoring](monitoring.md) for observability setup.
- **Working on the database?** See [Database](database.md) for schema details and stored function signatures.

---

## Related Documentation

- [Getting Started](../getting-started/index.md) -- Installation and quick start
- [How-to Guides](../how-to/index.md) -- Task-oriented guides
- [API Reference](../reference/index.md) -- Auto-generated API documentation
