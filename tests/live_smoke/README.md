# tests/live_smoke

Quarantined live-network smoke tests.

## What Lives Here

- rare public-relay probes that cannot belong to the main gate;
- manual or scheduled checks against uncontrolled network dependencies;
- and the smallest possible helper layer needed to run those probes honestly.

## Rules

- keep this tree non-blocking by policy;
- never move public-network tests into `tests/system/`;
- and keep coverage here intentionally small and explicit.
