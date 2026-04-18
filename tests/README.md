# tests

Repository test suite for unit, integration, and shared fixture coverage.

## Main Areas

- `unit/`: fast, isolated tests for library and service logic.
- `integration/`: PostgreSQL-backed integration coverage for shared contracts.
- `fixtures/`: reusable test data helpers.
- `conftest.py`: top-level shared pytest fixtures and configuration.

## Rules

- Keep tests explicit about the layer they validate.
- Cache folders are generated exceptions and do not need local README files.
