# `.vscode`

Tracked Visual Studio Code workspace defaults for the BigBrotr repository.

## What Lives Here

- `settings.json`: editor, Ruff, mypy, pytest, and search-exclude defaults for
  local VS Code workspaces.

## Rules

- Keep tracked settings aligned with the repository's actual lint, typecheck,
  and test contract.
- Treat optional developer-local files such as `launch.json` as untracked
  workspace helpers unless the repository deliberately standardizes them.
