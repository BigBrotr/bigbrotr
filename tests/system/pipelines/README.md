# tests/system/pipelines

Cross-service runtime proof for higher-band system tests.

## What Lives Here

- one pipeline slice per multi-service flow;
- composed-stack proof across real runtime boundaries;
- persisted snapshots for each intermediate handoff;
- and teardown-safe artifacts for post-run audit.

## Rules

- certify only flows that involve multiple shipped services;
- reuse the service-certified harnesses rather than re-implementing them;
- keep boundary ownership honest at each handoff;
- and leave service-local assertions to `tests/system/services/`.
