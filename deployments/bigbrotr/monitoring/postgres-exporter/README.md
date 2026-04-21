# `bigbrotr/monitoring/postgres-exporter`

PostgreSQL exporter query pack for the `bigbrotr` deployment.

## What Lives Here

- [`queries.yaml`](queries.yaml): custom metrics that expose deployment-level
  database counts, sizes, index usage, dead tuples, and partition summaries.

## Rules

- Keep exporter queries aligned with the live schema and deployment database
  name.
- Prefer catalog-driven queries over hardcoded table lists unless the metric
  contract truly requires a fixed target.
