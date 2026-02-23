# Development

Resources for setting up, testing, and contributing to the BigBrotr project.

---

## Sections

### [Setup](setup.md)

Prerequisites, installation, IDE configuration, project structure, and Makefile targets.
Everything you need to get a working development environment.

### [Testing](testing.md)

Test configuration, running tests, shared fixtures, mock patterns, async patterns,
service and model test patterns, and coverage requirements.

### [Coding Standards](coding-standards.md)

Ruff linting, mypy strict mode, pre-commit hooks, import conventions, model patterns,
error handling, architecture rules, and documentation standards.

### [SQL Templates](sql-templates.md)

How the Jinja2 template system generates deployment-specific database initialization
files. Adding, modifying, and verifying SQL templates.

### [Contributing](contributing.md)

Code of conduct, branch and commit conventions, and pull request process.

---

## Quick Verification

After completing the [setup](setup.md), verify everything works:

```bash
make ci
```

This runs linting, format checking, type checking, unit tests, SQL template verification,
and dependency auditing in one step.
