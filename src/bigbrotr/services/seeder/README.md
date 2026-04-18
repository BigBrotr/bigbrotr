# seeder

One-shot bootstrap of initial relay candidates or stored relays.

## Main Files

- `service.py`: seed-file orchestration.
- `queries.py`: seed persistence helpers.
- `configs.py`, `utils.py`: configuration and parsing helpers.

## Rules

- Keep this package minimal and bootstrap-focused.
- Long-running discovery belongs to Finder, not Seeder.
