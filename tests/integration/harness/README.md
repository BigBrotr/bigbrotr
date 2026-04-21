# integration/harness

Deterministic support layer for the rebuilt integration suite.

## What Lives Here

- PostgreSQL container lifecycle helpers;
- deployment-aware schema bootstrap helpers;
- shared `Brotr` factory fixtures;
- canonical record builders;
- named external doubles;
- deterministic timestamps, identifiers, and temp-storage helpers;
- explicit failure-injection seams for timeout, cancellation, database, and partial-result flows.

## Rules

- keep support code here, not contract assertions;
- prefer named helpers over ad hoc fixture logic in unrelated test files;
- make setup/teardown behavior observable and testable directly.
