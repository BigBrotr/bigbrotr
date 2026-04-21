# tests/system/services/seeder

Real runtime certification for the one-shot `Seeder` service.

## What Lives Here

- once-run exit proof on the composed deployment stack;
- candidate-mode persistence and duplicate/idempotency checks;
- direct-relay insertion proof;
- and invalid-source handling with audit artifacts.

## Rules

- use the shipped `seeder` container and config wiring;
- keep the seed file runtime-owned under the copied `static/` tree;
- assert DB consequences directly from the live PostgreSQL instance;
- and capture logs plus DB snapshots for every closed contract.
