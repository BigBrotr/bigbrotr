# `bigbrotr/pgbouncer`

PgBouncer connection-pooler assets for the `bigbrotr` full-archive deployment.

## What Lives Here

- [`pgbouncer.ini`](pgbouncer.ini): transaction-pooling configuration for the
  deployment database and its readonly alias.
- [`entrypoint.sh`](entrypoint.sh): startup hook that renders the SCRAM userlist
  from deployment secrets before launching PgBouncer.

## Rules

- Keep the database names, role names, and auth expectations aligned with the
  deployment `.env`, PostgreSQL bootstrap, and service pool configuration.
- Preserve transaction-pooling compatibility assumptions such as the startup
  parameter pass-through expected by `asyncpg`.
- If pooler behavior changes, update this README with the operational contract.
