# `lilbrotr/monitoring/alertmanager`

Alertmanager routing configuration for the `lilbrotr` deployment.

## What Lives Here

- [`alertmanager.yml`](alertmanager.yml): alert grouping, repeat intervals, and
  receiver definitions for Prometheus alerts.

## Rules

- Replace placeholder receivers with real notification integrations before
  treating this deployment as production-ready.
- Keep route labels and severity handling aligned with the alert rules shipped
  under `monitoring/prometheus/rules/`.
