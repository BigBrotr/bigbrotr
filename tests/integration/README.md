# tests/integration

Integration coverage for the shared database contract and deployment variants.

## Main Areas

- `harness/`: deterministic PostgreSQL, schema-bootstrap, and shared fixture support.
- `base/`: historical canonical shared-schema and service integration tests pending migration.
- `lilbrotr/`: historical lightweight-profile integration coverage pending migration.
- `conftest.py`: thin root fixture entrypoint that exposes the shared harness.

## Rules

- Use these tests to prove storage, refresh, and service contracts end to end.
- Variant-specific behavior belongs in the profile-specific subfolder, not in
  duplicated base tests.
- New integration support code belongs under `harness/`, not inside unrelated
  assertion files.
