# integration/harness/doubles

Named doubles for integration-only external boundaries.

## What Lives Here

- protocol publish-session doubles;
- broadcast capture doubles;
- future API-source, relay-stream, network, and storage doubles.

## Rules

- prefer explicit named doubles here over inline `AsyncMock` clouds;
- keep each double narrow and observable;
- model only the boundary contract the integration tests actually need.
