# tests/system/services/assertor

Real runtime certification for the relay-publishing `Assertor` service.

## What Lives Here

- composed-stack execution of the shipped `assertor` container;
- live PostgreSQL seeding of ranked NIP-85 inputs and checkpoint assertions;
- real relay capture of published provider-package events;
- restart/idempotence proof against persisted assertor checkpoints;
- and publish-boundary failure proof against a fault-injected relay proxy.

## Rules

- publish only through a real relay or a real proxy in front of one;
- assert event correctness from captured relay payloads, not mocked builders;
- keep failure drills focused on authored publish semantics and checkpoint persistence;
- and capture relay/container/database artifacts for every certified run.
