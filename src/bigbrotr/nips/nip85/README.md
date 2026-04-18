# nip85

NIP-85 typed data helpers for public scores and provider-package publication.

## Main Files

- `data.py`: typed score/assertion payload models used by Ranker and Assertor.
- `__init__.py`: public package surface for NIP-85 data helpers.

## Rules

- Keep NIP-85 payload modeling here rather than duplicating shape logic in the
  services that publish or consume it.
