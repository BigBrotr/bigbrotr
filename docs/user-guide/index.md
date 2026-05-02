# User Guide

Core concepts and runtime reference for the final BigBrotr architecture.

---

<div class="grid cards" markdown>

-   :material-graph:{ .lg .middle } **[Architecture](architecture.md)**

    ---

    Diamond DAG layering, shared runtime shape, and the main system contracts.

-   :material-cogs:{ .lg .middle } **[Services](services.md)**

    ---

    Service ownership model for discovery, monitoring, refresh, ranking,
    assertion, and public read adapters.

-   :material-database:{ .lg .middle } **[Database](database.md)**

    ---

    Shared storage-first schema, derived tables, and public score outputs.

-   :material-seal-variant:{ .lg .middle } **[NIP-85 Pipeline](nip85-pipeline.md)**

    ---

    Refresher facts, Ranker DuckDB compute state, public score exports, and
    Assertor publication ownership.

-   :material-eye-outline:{ .lg .middle } **[Read Side](read-side.md)**

    ---

    `ReadCore`, readable resources, transport compatibility, and bounded
    public queries.

-   :material-folder-cog-outline:{ .lg .middle } **[Deployments](deployments.md)**

    ---

    Deployment folder contract, storage profiles, and adapter exposure policy.

-   :material-file-cog:{ .lg .middle } **[Configuration](configuration.md)**

    ---

    Complete YAML configuration reference with Pydantic validation and
    examples.

-   :material-chart-line:{ .lg .middle } **[Monitoring](monitoring.md)**

    ---

    Prometheus metrics, alerting rules, Grafana dashboards, and structured logging.

</div>

!!! tip "Where to start"
    New to the final architecture? Start with [Architecture](architecture.md),
    then read [Services](services.md), [Database](database.md), and
    [NIP-85 Pipeline](nip85-pipeline.md) in that order.
