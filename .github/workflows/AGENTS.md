# .github/workflows/AGENTS.md

## Purpose

This folder contains the GitHub Actions workflows that enforce the repository
contract.

## Files

- `ci.yml`: quality gate and branch-protection workflow.
- `docs.yml`: MkDocs build and deployment workflow.
- `release.yml`: release validation, package/image publishing, and GitHub
  release creation.
- `codeql.yml`: static analysis and security scanning workflow.

## Editing Rules

- Keep workflow steps aligned with the commands contributors are expected to
  run locally.
- Prefer explicit contract gates over narrative comments. If a workflow claims
  to validate more than it actually does, either strengthen the workflow or
  narrow the claim.
- Treat release automation as production infrastructure:
  - validate version/tag/branch assumptions explicitly;
  - gate publication behind the real repository quality checks;
  - keep artifact naming and retention consistent with the release guide.
- Keep SHA-pinned actions and update them intentionally.
