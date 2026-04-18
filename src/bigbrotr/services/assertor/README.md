# assertor

NIP-85 provider-package publisher.

## Main Files

- `service.py`, `runtime.py`: cycle orchestration and publication flow.
- `publishing.py`: event construction and publication helpers.
- `queries.py`: reads of shared facts and public score outputs.
- `configs.py`, `utils.py`: configuration and supporting helpers.

## Rules

- This package owns the published NIP-85 provider package: assertions,
  provider profile, and trusted-provider list.
- It should consume shared facts and public scores, not private Ranker state.
