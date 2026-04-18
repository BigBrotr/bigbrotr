# unit/services/common

Unit tests for shared service-layer infrastructure.

## What Lives Here

- catalog discovery and execution;
- shared configs, paging, read-core, mixins, state store, and helper coverage.

## Rules

- Read-side contract changes should usually be proven here before adapter tests
  are updated.
