# tests/system/services/finder

Real runtime certification for the continuous `Finder` service.

## What Lives Here

- real API-source fetches through a controlled HTTP fixture service;
- candidate and checkpoint persistence proof against live PostgreSQL;
- duplicate/cooldown behavior under repeated service cycles;
- and restart semantics with persisted finder state.

## Rules

- use the shipped `finder` container and config wiring;
- keep the HTTP fixture service real and deterministic;
- assert both `finder` and downstream candidate persistence in the live DB;
- and capture request evidence plus container logs for every closed contract.
