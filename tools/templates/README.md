# templates

Template source of truth for repository-generated artifacts.

## Main Areas

- `sql/`: Jinja-based SQL templates used to build built-in deployment init
  packages and related test-fixture SQL surfaces.

## Rules

- Edit generated artifacts by changing their template source here first.
- Keep template structure obvious enough that storage-profile and test-fixture
  overrides are easy to audit.
