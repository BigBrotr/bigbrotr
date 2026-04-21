# tests/system/deployments

Deployment-stack baseline certification for higher-band system tests.

## What Lives Here

- profile-specific compose startup proof;
- health and dependency-ordering audits;
- teardown and restart certification;
- and deployment-owned runtime artifacts such as `compose ps` snapshots and
  container logs.

## Rules

- certify the shipped deployment stacks here, not ad hoc service fragments;
- keep one-shot services and continuous services explicit in the assertions;
- capture enough runtime evidence to audit failures after teardown;
- and keep observability-deep assertions in `tests/system/observability/`.
