# unit/services

Unit tests for service packages and public adapters.

## What Lives Here

- one-file suites for each service package;
- `common/` tests for shared service infrastructure;
- CLI and registry coverage for the service runtime surface.

## Rules

- Service unit tests should mock external dependencies at the consumer
  boundary and keep behavior slices small and explicit.
