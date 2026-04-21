# `.claude`

Tracked repository support files for project-local command prompts, deep-dive
engineering guides, and local tool permission defaults.

## What Lives Here

- [`commands/README.md`](commands/README.md): structured task prompts for
  common repository workflows.
- [`guides/README.md`](guides/README.md): deeper engineering references used by
  the local command set.
- `settings.local.json`: tracked local permission and execution defaults for
  the `.claude` workspace tooling.

## Rules

- Treat this tree as contributor tooling support, not as runtime product code.
- Keep command prompts, deep-dive guides, and local settings aligned with the
  live repository contract instead of historical workflows.
