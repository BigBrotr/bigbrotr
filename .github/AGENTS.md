# .github/AGENTS.md

## Purpose

This directory contains repository automation and contributor-facing policy
surfaces.

Read this file before changing GitHub workflows, issue forms, PR templates, or
repository policy files under `.github/`.

## Current Structure

- `workflows/`: CI, docs publishing, release, and security automation.
- `ISSUE_TEMPLATE/`: public issue forms and contact links.
- `CODEOWNERS`: default review ownership.
- `PULL_REQUEST_TEMPLATE.md`: PR checklist and reviewer-facing change summary.
- `SECURITY.md`, `CODE_OF_CONDUCT.md`, `dependabot.yml`, `codeql-config.yml`:
  repository policy and automation configuration.

## Editing Rules

- Keep workflow behavior aligned with the real repository contract:
  - `make ci`
  - `uv lock --check`
  - `mkdocs build --strict`
  - SQL generation checks when deployment packages change
- Treat issue forms and PR templates as part of the product surface. They must
  reflect the actual service set, contributor workflow, and support paths.
- Prefer the public documentation site over repository-path links when pointing
  users to docs.
- Keep release automation conservative and explicit. If a workflow comment
  claims a stronger validation contract than the job actually enforces, fix the
  drift.
- Keep this directory free of stale local-guidance leftovers. The maintained
  guidance surface here is this `AGENTS.md`; user-facing policy lives in the
  specific GitHub policy/template files and in `docs/`.
