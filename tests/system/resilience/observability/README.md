# `tests/system/resilience/observability`

Failure and recovery certification for the monitoring stack.

## What Lives Here

- Prometheus outages and the resulting Grafana datasource degradation;
- Grafana outages that must not take down Prometheus or Alertmanager;
- postgres-exporter outages that must surface honestly in Prometheus target state;
- Alertmanager outages where alerts still fire locally in Prometheus and route again
  after recovery.
