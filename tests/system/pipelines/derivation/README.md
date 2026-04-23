# tests/system/pipelines/derivation

Runtime certification for the derivation-side service chain:

- `Refresher`
- `Ranker`
- `Assertor`

The tests here prove that raw archived events become shared NIP-85 facts,
ranker score outputs, and a real published provider package on a live relay,
with restart-time idempotency across the composed stack.
