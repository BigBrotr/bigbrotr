# `tests/system/resilience`

Cross-cutting failure and recovery drills for the higher-band system suite.

## What Lives Here

- relay-network degradation and recovery that spans more than one service;
- database, pool, and observability-stack failure drills;
- runtime interruption scenarios that belong above one service contract;
- and flake-sensitive reruns that prove the stack recovers honestly.
