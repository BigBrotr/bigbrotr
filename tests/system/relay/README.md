# tests/system/relay

Real relay infrastructure proof for higher-band system tests.

## What Lives Here

- baseline relay selection and local protocol contract;
- publication-capture relay proof for producer services;
- fault-injected relay-path drills;
- and relay-role self-audit over repeated real publish/read cycles.

## Rules

- use real relay servers here, not protocol doubles;
- capture logs, inspect payloads, and relay event evidence for every closed
  slice;
- keep public-relay probes out of this tree and under `tests/live_smoke/`;
- and treat relay startup, readiness, publish, query, subscribe, and recovery
  semantics as first-class contracts.
