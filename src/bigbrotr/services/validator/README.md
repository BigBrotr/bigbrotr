# validator

Candidate-relay validation and promotion service.

## Main Files

- `service.py`, `runtime.py`: validation loop and concurrency flow.
- `queries.py`: candidate fetch, failure accounting, and promotion helpers.
- `configs.py`, `utils.py`: configuration and helper logic.

## Rules

- This package decides whether a candidate becomes part of the canonical relay
  pool.
- Discovery and promotion should stay separate: Finder discovers, Validator
  promotes.
