# tests/system/harness

Deterministic support layer for the higher-band system-test suite.

## What Lives Here

- Docker Compose lifecycle helpers;
- runtime PostgreSQL query helpers;
- local HTTP fixture helpers for service-boundary tests;
- deterministic env generation for built-in deployments;
- readiness polling and teardown helpers;
- artifact-capture support;
- observability API helpers;
- relay/runtime control helpers;
- and other reusable test-only runtime utilities.

## Rules

- keep support code here, not domain assertions;
- prefer named helpers over ad hoc subprocess logic in tests;
- make compose state, readiness, and teardown behavior observable;
- and keep the harness directly unit-tested before higher-band assertions build
  on top of it.
