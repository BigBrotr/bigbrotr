# `testbrotr/data/ranker`

Committed Ranker fixture state for the internal `testbrotr` deployment.

## What Lives Here

- `ranker.checkpoint.json`: persisted Ranker checkpoint state for internal
  workflows.
- `ranker.duckdb`: committed DuckDB snapshot used by tests and tooling.

## Rules

- Keep these artifacts aligned with the fixture workflows that consume them.
- Refresh them intentionally as a matched snapshot instead of editing one file
  in isolation.
