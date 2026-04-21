# tests/system/services

Real per-service runtime certification for higher-band system tests.

## What Lives Here

- one service slice per package;
- real container/process proof against the composed stack;
- DB, relay, HTTP, or filesystem assertions at the true service boundary;
- and service-owned runtime artifacts for audit after teardown.

## Rules

- certify one service contract at a time;
- use the shipped deployment wiring, not ad hoc subprocess launches;
- keep shared support in `tests/system/harness/`;
- and leave cross-service flows to `tests/system/pipelines/`.
