# tests/system

Higher-band runtime certification for BigBrotr.

## What Lives Here

- deployment-fidelity stack startup and teardown;
- service runtime certification against real boundaries;
- cross-service pipeline proof;
- observability-stack certification;
- resilience and restart drills;
- and reusable higher-band harness support.

## Rules

- keep full composed-runtime proof here, not under `tests/integration/`;
- use real boundaries where the product contract is external;
- keep public-network probes out of this tree and under `tests/live_smoke/`;
- keep test-owned stack assets under `tests/system/assets/`;
- and keep support code under `tests/system/harness/`, not inside assertion
  files.
