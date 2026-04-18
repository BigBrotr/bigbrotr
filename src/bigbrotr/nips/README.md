# nips

Protocol-aware NIP helpers, builders, and the static capability registry.

## Main Areas

- `nip11/`: relay information document fetch and normalization.
- `nip66/`: relay health-check families and probe outputs.
- `nip85/`: public score/assertion models plus provider-package builders.
- `event_builders.py`, `parsing.py`, `registry.py`: shared event builders,
  parsing helpers, and static capability registry.

## Rules

- Keep protocol semantics explicit here rather than leaking them into unrelated
  layers.
- Builders and registry contracts should stay aligned with the public service
  boundaries that consume them.
