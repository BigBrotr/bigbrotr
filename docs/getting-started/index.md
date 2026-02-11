# Getting Started

Everything you need to go from zero to a running BigBrotr instance.

---

This section walks you through the complete setup process in three stages:

<div class="grid cards" markdown>

-   :material-download:{ .lg .middle } **[Installation](installation.md)**

    ---

    System requirements, dependency installation, and three install paths: Docker-only, hybrid, and full manual.

-   :material-rocket-launch:{ .lg .middle } **[Quick Start](quickstart.md)**

    ---

    Step-by-step tutorial running each service locally, from seeding the database to validating relays.

-   :material-server:{ .lg .middle } **[First Deployment](first-deployment.md)**

    ---

    Full Docker Compose deployment with monitoring, Grafana dashboards, and production secrets.

</div>

## Prerequisites at a Glance

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.11+ | Required for local development; not needed for Docker-only |
| PostgreSQL | 16+ | Provided by Docker Compose, or install locally |
| Docker | 20.10+ | Recommended for infrastructure and full deployments |
| Git | Any | To clone the repository |

!!! tip "Which path should I choose?"
    **Just want to run it?** Start with [First Deployment](first-deployment.md) -- Docker handles everything.
    **Want to develop?** Follow [Installation](installation.md) (hybrid path), then [Quick Start](quickstart.md).
