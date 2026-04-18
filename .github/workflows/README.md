# workflows

GitHub Actions workflows that enforce BigBrotr's repository contract.

## Files

- `ci.yml`: main quality gate and test workflow.
- `docs.yml`: documentation build and publication workflow.
- `release.yml`: release automation.
- `codeql.yml`: security analysis workflow.

## Rules

- Workflow changes must stay consistent with local developer commands and the
  documented release process.
- If the repository contract changes, update both the workflow and the
  contributor-facing documentation in the same slice.
