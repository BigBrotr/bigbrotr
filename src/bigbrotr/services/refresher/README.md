# refresher

Owner of canonical shared derived facts.

## Main Files

- `service.py`, `runtime.py`: refresh orchestration and target scheduling.
- `queries.py`: refresh entrypoints and shared-state interactions.
- `configs.py`: refresh-target configuration and cycle policy.

## Rules

- Canonical current tables, analytics facts, and operational shared facts are
  refreshed here.
- Do not spread shared-derivation ownership across unrelated services.
