# tests/system/services/dvm

Real runtime certification for the relay-backed `DVM` service.

## What Lives Here

- composed-stack execution of the shipped `dvm` container for `bigbrotr` and `lilbrotr`;
- live PostgreSQL seeding of the public read-surface data consumed by NIP-90 jobs;
- real relay assertions for NIP-89 announcement, NIP-90 request/result feedback, and restart-safe cursor restore;
- and profile proof that the shipped DVM exposure policy stays observable at the real relay boundary.

## Rules

- publish requests through a real relay and inspect reply events from the relay store, never mocked builders;
- assert result and error semantics from the published Nostr payloads, not internal helper calls;
- keep restart proof focused on persisted cursor behavior and duplicate suppression across container restarts;
- and capture relay/container/database artifacts for every certified run.
