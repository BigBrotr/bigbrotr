# tests/system/services/synchronizer

Real runtime certification for the continuous `Synchronizer` service.

## What Lives Here

- real archive ingestion against a live relay stream behind deterministic TLS termination;
- persisted `event`, `event_observation`, and synchronizer cursor assertions from live PostgreSQL;
- stale-cursor cleanup, restart/resume, and dedup proof at the authored service boundary;
- and relay, proxy, websocket-session, and container artifacts for post-run audit.

## Rules

- use the shipped `synchronizer` container and config wiring;
- keep the relay stream real and keep network faults on the real transport path;
- assert archive rows and cursor state directly from the live DB;
- and capture relay/proxy/container evidence for every closed contract.
