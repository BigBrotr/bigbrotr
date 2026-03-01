# User Guide

In-depth reference documentation for BigBrotr's architecture, services, configuration, database, and monitoring.

---

## Sections

| Page | Description |
|------|-------------|
| [Architecture](architecture.md) | Diamond DAG layer structure, design patterns, concurrency model, and testing architecture |
| [Services](services.md) | Deep dive into the eight independent services: Seeder, Finder, Validator, Monitor, Synchronizer, Refresher, Api, Dvm |
| [Configuration](configuration.md) | Complete YAML configuration reference with Pydantic validation and examples |
| [Database](database.md) | PostgreSQL schema, stored functions, materialized views, and indexes |
| [Monitoring](monitoring.md) | Prometheus metrics, alerting rules, Grafana dashboards, and structured logging |

---

## Quick Navigation

- **New to BigBrotr?** Start with [Architecture](architecture.md) for the system overview, then [Services](services.md) to understand what each service does.
- **Deploying?** See [Configuration](configuration.md) for YAML reference and [Monitoring](monitoring.md) for observability setup.
- **Working on the database?** See [Database](database.md) for schema details and stored function signatures.

---

## Related Documentation

- [Getting Started](../getting-started/index.md) -- Installation and quick start
- [How-to Guides](../how-to/index.md) -- Task-oriented guides
- [API Reference](../reference/index.md) -- Auto-generated API documentation
