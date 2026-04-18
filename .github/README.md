# .github

Repository automation, policy, and contributor entrypoints.

## What Lives Here

- `workflows/`: CI, docs publishing, release, and security automation.
- `ISSUE_TEMPLATE/`: GitHub issue forms and issue-template config.
- `AGENTS.md`: local editing rules for this folder.
- `CODEOWNERS`: default review ownership.
- `PULL_REQUEST_TEMPLATE.md`: pull request checklist and structure.
- `SECURITY.md`, `CODE_OF_CONDUCT.md`, `dependabot.yml`, `codeql-config.yml`:
  repository policy and automation configuration.

## Rules

- Keep workflow behavior aligned with the actual engineering contract:
  `make ci`, strict typing, docs build, and release discipline.
- Treat this folder as product infrastructure, not as disconnected GitHub
  decoration.
