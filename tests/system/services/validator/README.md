# tests/system/services/validator

Real runtime certification for the continuous `Validator` service.

## What Lives Here

- real `wss://` relay validation against a baseline relay via deterministic TLS termination;
- invalid websocket endpoint rejection without replacing the network boundary with mocks;
- persisted failure and promotion consequences against live PostgreSQL;
- and restart/backoff proof from the authored validator retry window.

## Rules

- use the shipped `validator` container and config wiring;
- keep both the valid relay path and the invalid websocket path real;
- assert relay promotion and failed-candidate persistence in the live DB;
- and capture websocket session evidence plus container logs for every closed contract.
