# `bigbrotr/monitoring`

Observability stack assets for the `bigbrotr` full-archive deployment.

## What Lives Here

- [`prometheus/`](prometheus/README.md): scrape configuration and alert rules.
- [`alertmanager/`](alertmanager/README.md): notification routing config.
- [`grafana/`](grafana/README.md): provisioned datasource and dashboard assets.
- [`postgres-exporter/`](postgres-exporter/README.md): custom SQL metrics for
  the PostgreSQL exporter.

## Rules

- Keep the monitoring stack aligned with the actual service set, port map, and
  metric names emitted by the application.
- Treat deployment-local dashboards and alert rules as operator surfaces, not
  as ad-hoc scratch files.
- When observability behavior changes, update the nearest local README with the
  operational contract.
