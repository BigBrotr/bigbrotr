# tests/system/services/refresher

Real runtime certification for the continuous `Refresher` service.

## What Lives Here

- composed-stack execution of the shipped `refresher` container and config wiring;
- live PostgreSQL assertions for refreshed current/analytics outputs and persisted checkpoints;
- stale-checkpoint cleanup plus restart/resume proof with bounded incremental backlog;
- and container/database artifacts that keep every closed contract auditable.

## Rules

- seed source rows through the real `Brotr` database boundary, not ad-hoc table shortcuts;
- keep runtime assertions focused on authored service behavior, not on re-proving every SQL target in full;
- prove checkpoint touch points directly from the live DB;
- and capture refresher/container evidence for every certified run.
