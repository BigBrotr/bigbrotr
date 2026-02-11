# Development

Resources for setting up, testing, and contributing to the BigBrotr project.

---

## Sections

### [Setup](setup.md)

Prerequisites, installation, IDE configuration, project structure, and Makefile targets.
Everything you need to get a working development environment.

### [Testing](testing.md)

Test configuration, running tests, shared fixtures, mock patterns, writing new tests,
integration tests, and coverage requirements.

### [Contributing](contributing.md)

Code of conduct, branch and commit conventions, pull request process, coding standards,
architecture rules, and documentation guidelines.

---

## Quick Verification

After completing the [setup](setup.md), verify everything works:

```bash
make ci
```

This runs linting, formatting, type checking, unit tests, and SQL template checks in one step.
