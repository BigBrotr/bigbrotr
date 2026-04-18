# templates

Template source of truth for repository-generated artifacts.

## Main Areas

- `sql/`: Jinja-based SQL templates used to build deployment init packages.

## Rules

- Edit generated artifacts by changing their template source here first.
- Keep template structure obvious enough that deployment-specific overrides are
  easy to audit.
