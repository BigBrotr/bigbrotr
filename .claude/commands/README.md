# `commands`

Project-local command prompts for recurring repository workflows.

## What Lives Here

- `audit.md`: repository or area audit workflow.
- `check.md`: verification workflow for targeted changes.
- `implement.md`: structured implementation workflow.
- `new-nip.md`: workflow for adding a new NIP helper or integration.
- `new-service.md`: workflow for adding a new service.
- `pr.md`: pull-request preparation workflow.
- `release.md`: release preparation workflow.
- `review.md`: diff-review workflow.
- `sql-migrate.md`: SQL migration or schema-change workflow.
- `sync-docs.md`: documentation synchronization workflow.
- `validate-schema.md`: schema validation workflow.

## Rules

- Keep prompt assumptions aligned with the repository's actual branch, quality,
  and review contract.
- If a workflow changes materially, update the relevant prompt and the linked
  guide or public contributor docs in the same slice.
