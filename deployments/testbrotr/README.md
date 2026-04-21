# `testbrotr` Fixture Deployment

`testbrotr` is an internal deployment fixture used by tests and tooling.

Unlike `bigbrotr` and `lilbrotr`, this folder is not a human-facing reference
deployment and it is not expected to contain the full operator packaging
surface. It exists to hold deterministic fixture assets for internal workflows.

## What Lives Here

- [`.env`](.env): committed fixture credentials and service keys used by
  internal test/tool runs.
- [`data/postgres/`](data/postgres/): reserved PostgreSQL fixture state for the
  internal deployment snapshot.
- [`data/ranker/`](data/ranker/): Ranker fixture state, including the committed
  checkpoint JSON and DuckDB snapshot.

## Rules

- Treat this folder as internal fixture state, not as a starting point for
  operator deployments.
- If you need a real deployment template, copy `deployments/bigbrotr/` or
  `deployments/lilbrotr/` instead.
- Refresh committed fixture data intentionally and keep any workflow
  expectations near the tests or tools that depend on it.
