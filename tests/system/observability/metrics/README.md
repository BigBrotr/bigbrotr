# `tests/system/observability/metrics`

Contracts for service-emitted metrics and deployment metrics wiring.

## Focus

- metric family names and label schemas;
- lifecycle semantics across startup, successful cycles, and restart;
- and deployment config that is supposed to expose those metrics to operators
  and the monitoring stack.
