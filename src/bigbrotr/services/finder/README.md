# finder

Relay discovery service for stored events and external API sources.

## Main Files

- `service.py`: orchestration of event and API discovery phases.
- `event_runtime.py`, `api_runtime.py`: source-specific runtime logic.
- `queries.py`, `utils.py`, `configs.py`: database access, helpers, and config.

## Rules

- Event discovery and API discovery are separate subflows but one service
  boundary.
- Persist only candidate discovery state here; relay promotion belongs to the
  Validator.
