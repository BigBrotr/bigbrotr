# tests/integration

Integration coverage for the shared database contract and deployment variants.

## Main Areas

- `base/`: canonical shared-schema and service integration tests.
- `lilbrotr/`: lightweight-profile integration coverage.
- `conftest.py`: containerized PostgreSQL fixtures and shared setup.

## Rules

- Use these tests to prove storage, refresh, and service contracts end to end.
- Variant-specific behavior belongs in the profile-specific subfolder, not in
  duplicated base tests.
