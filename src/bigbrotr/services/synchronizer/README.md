# synchronizer

Event-archive ingestion service for validated relays.

## Main Files

- `service.py`, `runtime.py`: relay loop and event-stream orchestration.
- `queries.py`: relay fetches, cursor cleanup, and event-observation inserts.
- `configs.py`: sync windows, batching, and network policy.

## Rules

- This package owns event archive ingestion and relay cursors.
- Shared derived facts from archived events belong downstream in Refresher.
