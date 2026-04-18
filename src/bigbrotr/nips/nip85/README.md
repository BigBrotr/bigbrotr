# nip85

NIP-85 typed data models and provider-package builder surface.

## Main Files

- `data.py`: typed score/assertion payload models used by Ranker and Assertor.
- `__init__.py`: public package surface exposing those models plus the
  provider-profile, trusted-provider-list, and assertion builders.

## Rules

- Keep NIP-85 payload modeling and provider-package builder exports here rather
  than duplicating shape logic in the services that publish or consume it.
