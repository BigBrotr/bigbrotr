# User Guide

In-depth reference documentation for BigBrotr's architecture, services, configuration, database, and monitoring.

---

<div class="grid cards" markdown>

-   :material-graph:{ .lg .middle } **[Architecture](architecture.md)**

    ---

    Diamond DAG layer structure, design patterns, concurrency model, and testing architecture.

-   :material-cogs:{ .lg .middle } **[Services](services.md)**

    ---

    Deep dive into the nine independent services: Seeder, Finder, Validator, Monitor, Synchronizer, Refresher, Assertor, Api, Dvm.

-   :material-file-cog:{ .lg .middle } **[Configuration](configuration.md)**

    ---

    Complete YAML configuration reference with Pydantic validation and examples.

-   :material-database:{ .lg .middle } **[Database](database.md)**

    ---

    PostgreSQL schema, stored functions, materialized views, and indexes.

-   :material-chart-line:{ .lg .middle } **[Monitoring](monitoring.md)**

    ---

    Prometheus metrics, alerting rules, Grafana dashboards, and structured logging.

</div>

!!! tip "Where to start"
    New to BigBrotr? Start with [Architecture](architecture.md) for the system overview, then [Services](services.md) to understand what each service does.
