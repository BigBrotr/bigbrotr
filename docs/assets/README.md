# assets

Tracked support assets consumed by the MkDocs site build.

## What Lives Here

- `images/README.md`: support index for the committed logo and favicon files.
- `stylesheets/README.md`: support index for the custom MkDocs stylesheet
  overrides loaded by `mkdocs.yml`.

## Rules

- Keep only build-time documentation assets here; runtime product assets
  belong elsewhere in the repository.
- When changing asset filenames or paths, update `mkdocs.yml` and adjacent
  folder guidance in the same slice.
