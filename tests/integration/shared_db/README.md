# integration/shared_db

Direct shared PostgreSQL contract tests for the rebuilt integration suite.

## What Lives Here

- relay, event, document, and service-state storage contracts;
- shared SQL function behavior and persisted-state invariants;
- cross-table integrity, partitioning, retention, and refresh contracts that
  belong to the shared schema rather than one service.

## Rules

- prove persisted-state and SQL semantics, not service orchestration;
- use `tests/integration/harness/` support surfaces instead of ad hoc builders;
- migrate historical `base/` storage proof here before removing old files.
