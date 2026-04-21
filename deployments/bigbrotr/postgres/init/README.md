# `bigbrotr/postgres/init`

Generated PostgreSQL bootstrap package for the `bigbrotr` full-archive
reference deployment.

## What Lives Here

- `00_*.sql` through `12_*.sql`: generated schema, function, refresh, and
  index files rendered from `tools/templates/sql/`.
- `99_verify.sql`: generated verification summary for the initialized schema.
- `01_roles.sh`, `98_grants.sh`: shell hooks that create the deployment roles
  and apply the expected grants around the generated SQL package.

## Rules

- Treat the `*.sql` files here as generated output, not as hand-edited source.
- When schema behavior changes, update the template source and rerun
  `python tools/generate_sql.py` instead of patching this folder directly.
- Keep the role/grant scripts consistent with the privileges assumed by the
  application and deployment docs.
