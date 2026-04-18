# tests/unit

Fast unit tests for package-local behavior.

## Main Areas

- `core/`, `models/`, `nips/`, `services/`, `utils/`: layer-specific unit
  suites.
- `tools/`: unit tests for repository tooling.
- top-level files: shared unit-level tests such as lazy-import coverage.

## Rules

- Unit tests should stay isolated from real infrastructure.
- Mock at the consumer boundary, not the original definition site.
