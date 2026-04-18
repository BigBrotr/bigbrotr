# tools

Repository maintenance and operational helper scripts.

## Main Files

- `generate_sql.py`: generate or verify deployment init SQL from Jinja
  templates.
- `migrate_relay_urls.py`: relay-URL migration and normalization helper.
- `rebuild_refresher_state.py`: operational helper for rebuilding Refresher
  shared derivation state.

## Subfolders

- `templates/`: template source of truth used by `generate_sql.py`.

## Rules

- Tooling should stay explicit and safe for operators and contributors.
- Generated output should be committed only after regenerating from template
  source.
