# tests/system/services/monitor

Real runtime certification for the continuous `Monitor` service.

## What Lives Here

- real relay probe coverage against a healthy baseline relay and a degraded relay path;
- persisted `nip11_info` and `nip66_rtt` document assertions from the live PostgreSQL instance;
- checkpoint persistence and restart semantics under the authored monitor cadence;
- and relay, proxy, and container artifacts for post-run audit.

## Rules

- use the shipped `monitor` container and config wiring;
- keep both the healthy and degraded relay paths real;
- assert stored document payloads and monitor checkpoints directly from the live DB;
- and capture relay/proxy/container evidence for every closed contract.
