# stylesheets

Custom CSS overrides layered on top of the default MkDocs Material theme.

## What Lives Here

- `extra.css`: tracked theme tweaks for branding, cards, tables, code blocks,
  admonitions, search, Mermaid, and API-reference presentation.

## Rules

- Keep this folder declarative and minimal; prefer theme configuration before
  adding override CSS.
- If a stylesheet path changes, update `mkdocs.yml:extra_css` in the same
  slice.
