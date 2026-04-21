# `lilbrotr/monitoring/grafana`

Grafana provisioning assets for the `lilbrotr` deployment.

## What Lives Here

- [`provisioning/`](provisioning/README.md): auto-loaded datasource and
  dashboard configuration consumed at Grafana startup.

## Rules

- Keep this tree declarative: provisioned assets should remain committed and
  reproducible, not manually edited inside a running Grafana container.
