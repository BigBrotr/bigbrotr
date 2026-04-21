# sql/testbrotr

Internal SQL overrides for the `testbrotr` fixture namespace.

## What Lives Here

- `02_tables_core.sql.j2`: lightweight event-table override with nullable
  `tags`, `content`, and `sig` while keeping computed `tagvalues`.
- `05_functions_crud.sql.j2`: fixture CRUD override that stores only the
  essential event fields and derives `tagvalues` at insert time.
- `99_verify.sql.j2`: fixture-specific verification summary for the reduced
  schema contract.

## Rules

- Keep overrides minimal and explicit relative to `sql/base/`.
- Preserve the lightweight event-storage assumptions that the fixture data and
  tooling expect: payload fields stay unpopulated, `tagvalues` stays computed.
- This namespace is for internal tooling/tests only; it is not part of the
  built-in deployment generation path driven by `GENERATED_DEPLOYMENTS`.
