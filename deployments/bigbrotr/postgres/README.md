# `bigbrotr/postgres`

PostgreSQL runtime settings and bootstrap package for the `bigbrotr`
reference deployment.

## What Lives Here

- [`postgresql.conf`](postgresql.conf): deployment-local PostgreSQL tuning for
  the full-archive reference stack.
- [`init/`](init/README.md): generated SQL bootstrap package plus the role and
  grant shell hooks executed during database initialization.

## Rules

- Tune PostgreSQL runtime behavior here only when the deployment-level database
  contract changes.
- Do not hand-maintain the generated SQL under `init/`; regenerate it from the
  template source when the schema changes.
- Keep the initialization hooks aligned with the shared role/grant contract
  expected by the services and connection-pooler layer.
