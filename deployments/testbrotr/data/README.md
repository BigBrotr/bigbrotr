# `testbrotr/data`

Committed runtime snapshot data for the internal `testbrotr` fixture
deployment.

## What Lives Here

- [`postgres/README.md`](postgres/README.md): internal PostgreSQL cluster state
  used by fixture workflows.
- [`ranker/README.md`](ranker/README.md): committed Ranker checkpoint and
  DuckDB snapshot used by tests and tooling.

## Rules

- Treat this tree as deterministic fixture state, not as an operator-facing
  deployment volume contract.
- Refresh data here intentionally and keep workflow assumptions near the tests
  or tools that consume the snapshot.
