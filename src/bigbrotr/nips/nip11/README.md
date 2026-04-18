# nip11

NIP-11 relay information document support.

## Main Files

- `nip11.py`: main fetch orchestration and document serialization seam.
- `info.py`: typed relay-information model.
- `data.py`, `logs.py`: structured NIP-11 payload and log models.

## Rules

- Keep HTTP fetch behavior and result modeling explicit and testable.
- This package owns NIP-11-specific logic; generic helpers belong in parent
  packages instead.
