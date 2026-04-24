# `tests/system/resilience/restart`

Runtime certification for repeated service restarts and interrupted work.

## What Lives Here

- repeated container restarts while a service is stuck on a real external boundary;
- proof that partial state stays honest across those restarts;
- and recovery proof once the interrupted boundary becomes healthy again.
