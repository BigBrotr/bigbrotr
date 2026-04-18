# Getting Started

Everything you need to go from zero to a running BigBrotr instance.

---

This section gets you from zero to a real BigBrotr deployment path. It is
organized around three goals:

<div class="grid cards" markdown>

-   :material-download:{ .lg .middle } **[Installation](installation.md)**

    ---

    System requirements, dependency installation, and the supported setup
    paths.

-   :material-rocket-launch:{ .lg .middle } **[Quick Start](quickstart.md)**

    ---

    Step-by-step local run-through from initial relay seeding to the first
    validated relay archive state.

-   :material-server:{ .lg .middle } **[First Deployment](first-deployment.md)**

    ---

    First serious deployment path using the built-in reference deployment and
    monitoring stack.

</div>

## Prerequisites at a Glance

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.11+ | Required for local development; not needed for Docker-only |
| PostgreSQL | 18+ | Provided by Docker Compose, or install locally |
| Docker | 20.10+ | Recommended for infrastructure and full deployments |
| Git | Any | To clone the repository |

!!! tip "Which path should I choose?"
    **Just want to run a real deployment?** Start with
    [First Deployment](first-deployment.md).
    **Want to understand the runtime locally first?** Follow
    [Installation](installation.md), then [Quick Start](quickstart.md).
