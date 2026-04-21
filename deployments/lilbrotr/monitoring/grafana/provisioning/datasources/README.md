# `lilbrotr/monitoring/grafana/provisioning/datasources`

Provisioned Grafana datasources for the `lilbrotr` deployment.

## What Lives Here

- [`prometheus.yaml`](prometheus.yaml): default Prometheus datasource used by
  the shipped dashboards.

## Rules

- Keep datasource names, UIDs, and target URLs stable unless you also update
  the dashboards that depend on them.
