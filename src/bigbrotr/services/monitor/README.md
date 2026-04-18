# monitor

Relay monitoring service for NIP-11/NIP-66 document collection and publication.

## Main Files

- `service.py`, `runtime.py`, `processing.py`: main orchestration and cycle
  flow.
- `checks.py`, `geo.py`, `resources.py`: probe execution and resource handling.
- `publishing.py`, `queries.py`, `utils.py`, `configs.py`: publication,
  persistence, helpers, and configuration.

## Rules

- This package owns relay-document collection and monitor-side publication.
- Keep the monitoring and publication boundary here unless the service contract
  changes deliberately.
