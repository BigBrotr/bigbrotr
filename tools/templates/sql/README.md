# sql templates

Source of truth for generated PostgreSQL bootstrap SQL.

## Subfolders

- `base/`: shared templates used by all built-in storage profiles.
- `lilbrotr/`: lightweight-archive storage-profile overrides used by the
  built-in `lilbrotr` deployment.
- `testbrotr/`: test-fixture SQL overrides used by tooling/tests, not by the
  built-in deployment generator.

## Workflow

1. edit templates here;
2. run `python tools/generate_sql.py`;
3. commit regenerated built-in deployment files under
   `deployments/*/postgres/init/`;
4. verify with `python tools/generate_sql.py --check`.
