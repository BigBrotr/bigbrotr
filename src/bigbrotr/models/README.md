# models

Pure frozen dataclasses and enums for the shared BigBrotr data model.

## Main Files

- `relay.py`, `event.py`, `event_observation.py`: archive entities and
  observation history.
- `document.py`, `relay_document.py`: content-addressed document storage and
  relay-document history.
- `service_state.py`: resumable shared service state.
- `constants.py`, `relay_url.py`, `_validation.py`: shared enums, URL helpers,
  and validation primitives.

## Rules

- No I/O and no upward package dependencies.
- Fail-fast validation and cached DB-parameter conversion stay part of the
  model contract.
