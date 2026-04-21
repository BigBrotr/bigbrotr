# `testbrotr/data/postgres/pgdata`

Raw PostgreSQL cluster data directory snapshot committed for internal fixture
workflows.

## What Lives Here

- PostgreSQL control and configuration files such as `PG_VERSION`,
  `postgresql.conf`, `postgresql.auto.conf`, `pg_hba.conf`, `pg_ident.conf`,
  and `postmaster.opts`.
- Engine-managed subdirectories such as `base/`, `pg_wal/`, `pg_logical/`, and
  `pg_multixact/`.

## Rules

- Do not treat subdirectories here as human-documented package surfaces; they
  are raw engine internals owned by PostgreSQL.
- Regenerate this snapshot through the fixture workflow when it drifts instead
  of editing storage internals by hand.
