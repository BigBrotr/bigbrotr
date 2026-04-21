# `testbrotr/data/postgres`

Reserved PostgreSQL fixture state for the internal `testbrotr` deployment.

## What Lives Here

- [`pgdata/README.md`](pgdata/README.md): raw PostgreSQL data directory snapshot
  committed for internal fixture workflows.

## Rules

- Treat this folder as internal database state, not as editable deployment
  configuration.
- If the snapshot needs regeneration, update the full fixture coherently rather
  than hand-editing individual PostgreSQL internals.
