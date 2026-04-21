# integration/harness

Deterministic support layer for the rebuilt integration suite.

## What Lives Here

- PostgreSQL container lifecycle helpers;
- deployment-aware schema bootstrap helpers;
- shared `Brotr` factory fixtures;
- later builder, double, and failure-injection support surfaces.

## Rules

- keep support code here, not contract assertions;
- prefer named helpers over ad hoc fixture logic in unrelated test files;
- make setup/teardown behavior observable and testable directly.
