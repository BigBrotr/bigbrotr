# workflows

GitHub Actions workflows that enforce BigBrotr's repository contract.

## Files

- `ci.yml`: main quality gate and test workflow.
- `docs.yml`: documentation build and publication workflow.
- `release.yml`: release automation.
- `codeql.yml`: security analysis workflow.
- `AGENTS.md`: local editing rules for workflow changes.

## Rules

- Workflow changes must stay consistent with local developer commands and the
  documented release process.
- Release validation must be at least as honest as the contributor contract:
  comments must match the real gate, and publication steps must not run ahead
  of the repository quality checks.
- If the repository contract changes, update both the workflow and the
  contributor-facing documentation in the same slice.
