# `lilbrotr/monitoring/grafana/provisioning/dashboards`

Provisioned Grafana dashboards for the `lilbrotr` deployment.

## What Lives Here

- `lilbrotr.json`: deployment overview dashboard.
- `finder.json`, `validator.json`, `monitor.json`, `synchronizer.json`,
  `refresher.json`, `ranker.json`, `api.json`, `dvm.json`, `assertor.json`:
  service-specific dashboards.
- [`dashboards.yaml`](dashboards.yaml): Grafana provider definition that loads
  the JSON dashboards in this folder.

## Rules

- Keep dashboard titles, panel labels, and Prometheus queries aligned with the
  live metric names and the current service set.
- Update the provider file if dashboard-loading behavior changes.
