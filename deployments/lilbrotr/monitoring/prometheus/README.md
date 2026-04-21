# `lilbrotr/monitoring/prometheus`

Prometheus scrape and rule configuration for the `lilbrotr` deployment.

## What Lives Here

- [`prometheus.yaml`](prometheus.yaml): scrape targets and Alertmanager wiring.
- [`rules/`](rules/README.md): alerting rules evaluated by Prometheus.

## Rules

- Keep scrape targets aligned with the actual containers, ports, and exported
  metrics in this deployment.
- When alert semantics change, update the paired rules and local guidance
  together.
