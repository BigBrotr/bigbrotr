# `lilbrotr/monitoring/prometheus/rules`

Prometheus alert rules for the `lilbrotr` deployment.

## What Lives Here

- [`alerts.yml`](alerts.yml): service, database, and refresher health alerts.

## Rules

- Keep alert expressions, database names, and metric references aligned with
  the deployed Prometheus metric families.
- Avoid placeholder alert text that drifts from the actual operational signal.
