# BigBrotr Commands

8 slash commands for auditing, development, and release workflows.

## All Commands

| Command | Description | Arguments |
|---------|-------------|-----------|
| `/audit-quick` | Fast 5-skill parallel audit | `[scope]` |
| `/audit-core` | Comprehensive 11-skill parallel audit | `[scope]` |
| `/audit-full` | Full 22-skill audit in 3 waves | `[scope]` |
| `/check` | Run ruff, mypy, pytest quality checks | `[--fix] [--coverage]` |
| `/implement` | Plan and implement a feature/fix with checkpoints | `<description>` |
| `/review` | Multi-skill review of current changes | `[--staged] [--scope=<skills>]` |
| `/validate-schema` | Cross-validate models, SQL, stored procedures | `[--fix] [--impl=<name>]` |
| `/release` | Prepare a release (version, changelog, checks) | `<version> [--dry-run]` |

---

## Audit Commands

Three tiers of codebase analysis using specialized skill agents.

| Tier | Skills | Execution | Use When |
|------|--------|-----------|----------|
| `/audit-quick` | 5 | Parallel | Quick health check during development |
| `/audit-core` | 11 | Parallel | Before committing significant changes |
| `/audit-full` | 22 | 3 waves | Before releases or major refactoring |

All audit commands share the same JSON schema and post-execution workflow defined in:
```
.claude/skills/bigbrotr-expert/references/audit-schema.md
```

### Approval Options

| Option | Example |
|--------|---------|
| All | "all" |
| By severity | "critical and high" |
| By category | "security and database" |
| By skill | "postgres-pro findings" |
| Specific IDs | "CR-001, PG-003" |
| Skip | "skip" |

For `/audit-full` only: "by wave" and "by consensus (2+ skills)".

---

## Development Commands

| Command | Purpose |
|---------|---------|
| `/check` | Run all quality checks (ruff lint, ruff format, mypy, pytest) in parallel. Use `--fix` to auto-fix. |
| `/implement` | Structured feature/fix workflow: explore, plan, implement, verify. Checkpoints at each phase. |
| `/review` | Review uncommitted changes from multiple skill perspectives. Auto-selects skills based on file types. |

---

## Database Commands

| Command | Purpose |
|---------|---------|
| `/validate-schema` | Cross-validate Python models against SQL tables, stored procedures, and domain queries. Checks column mapping, parameter ordering, enum consistency, and index coverage across all implementations. |

---

## Release Commands

| Command | Purpose |
|---------|---------|
| `/release` | Prepare a release: bump version in pyproject.toml, update CHANGELOG.md, run all quality checks, create release commit. Use `--dry-run` to preview without changes. |

---

## Command Template Pattern

All commands follow a consistent structure:
- **YAML frontmatter** with `description` and `argument-hint`
- **`$ARGUMENTS`** placeholder for user input
- **Numbered phases** with explicit checkpoints
- **Failure conditions** that prevent unsafe operations
- **Output template** showing expected results format
- **Constraints** (MUST DO / MUST NOT DO)
