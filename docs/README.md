# docs

This folder contains the MkDocs site for BigBrotr.

## What Lives Here

- `index.md`, `changelog.md`, and the section entry pages define the human
  documentation surface shipped with the repository.
- `gen_ref_pages.py` generates the API-reference pages consumed by
  `mkdocstrings`.
- `_snippets/` contains reusable markdown fragments intentionally included by
  multiple pages.
- `assets/` contains tracked documentation assets such as the logo, favicon,
  and custom styles.
- `overrides/` only exists when the site genuinely needs MkDocs theme
  overrides.

## Subfolders

- `getting-started/`: installation, quickstart, and first-deployment material.
- `user-guide/`: architecture, services, database, read side, deployments,
  configuration, and monitoring.
- `development/`: contributor-facing engineering guides.
- `how-to/`: operational tasks and deployment recipes.
- `guides/`: longer narrative guides that do not fit the shorter how-to
  format.

## Rules

- Keep docs pages product-facing and implementation-honest.
- Keep local support files out of the public nav unless they are meant to be
  browsed as first-class docs pages.
- If a docs-support markdown file is not meant to become a site page, exclude
  it explicitly in `mkdocs.yml:exclude_docs` rather than relying on implicit
  build warnings or accidental nav omission.
