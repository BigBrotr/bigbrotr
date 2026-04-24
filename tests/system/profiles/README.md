# tests/system/profiles

Explicit certification of shipped deployment-profile differences.

## What Lives Here

- proof that `bigbrotr` and `lilbrotr` keep shared runtime contracts aligned;
- assertions that public-surface and provider-identity drift is intentional only;
- cross-profile snapshots that normalize profile-owned identities before comparison;
- and audit artifacts for each profile run under the composed stack.

## Rules

- certify only shipped `bigbrotr` vs `lilbrotr` differences here;
- reuse already-certified service and pipeline harnesses instead of cloning support code;
- normalize profile-owned keys, names, and event ids before parity comparisons;
- and fail if any unexpected divergence survives after allowed normalization.
