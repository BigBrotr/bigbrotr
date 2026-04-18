# sql templates

Source of truth for generated PostgreSQL bootstrap SQL.

## Subfolders

- `base/`: shared templates used by all storage profiles.
- `lilbrotr/`: lightweight-profile overrides.
- `testbrotr/`: test fixture profile overrides.

## Workflow

1. edit templates here;
2. run `python tools/generate_sql.py`;
3. commit regenerated files under `deployments/*/postgres/init/`;
4. verify with `python tools/generate_sql.py --check`.
