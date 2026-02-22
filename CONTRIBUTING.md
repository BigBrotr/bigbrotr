# Contributing to BigBrotr

Guidelines for contributing to BigBrotr: workflow, conventions, and quality checks.

---

## Code of Conduct

This project adheres to the [Contributor Covenant Code of Conduct](https://github.com/BigBrotr/bigbrotr/blob/main/.github/CODE_OF_CONDUCT.md).
By participating, you are expected to uphold this code.

---

## Development Setup

### Prerequisites

- Python 3.11 or higher
- Docker and Docker Compose
- Git

### Quick Start

```bash
# Clone the repository
git clone https://github.com/BigBrotr/bigbrotr.git
cd bigbrotr

# Install uv (one-time)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies (includes dev tools and pre-commit hooks)
make install

# Run tests to verify setup
make test-unit
```

### Finding Issues

- Look for issues labeled `good first issue` for beginner-friendly tasks
- Issues labeled `help wanted` are open for community contribution
- Check [GitHub Issues](https://github.com/BigBrotr/bigbrotr/issues) for planned work

---

## Branch Naming

Create branches from `develop` with a descriptive prefix:

```text
feat/add-api-service
fix/connection-timeout
refactor/pool-retry-logic
docs/update-readme
test/add-monitor-tests
chore/update-dependencies
```

---

## Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

| Prefix | Use case |
|--------|----------|
| `feat:` | New feature |
| `fix:` | Bug fix |
| `refactor:` | Code restructuring (no behavior change) |
| `docs:` | Documentation only |
| `test:` | Adding or updating tests |
| `chore:` | Dependency updates, CI config, tooling |

Examples:

```text
feat: add REST API service with OpenAPI documentation
fix: handle connection timeout in pool retry logic
refactor: split monitor into publisher and tags modules
```

---

## Pull Request Process

### Before Submitting

Run all quality checks:

```bash
# Run lint, format check, typecheck, unit tests, SQL checks, audit
make ci

# Run integration tests
make test-integration

# Run all pre-commit hooks
make pre-commit
```

Update documentation if you changed:

- Public API or configuration options
- Database schema or stored procedures
- Deployment process

Add your changes to `CHANGELOG.md` under `[Unreleased]`.

### Submitting

1. Push your branch to your fork
2. Create a Pull Request targeting `develop` (or `main` for releases)
3. Fill out the PR template completely
4. Wait for CI checks to pass
5. Address any review feedback

### PR Requirements Checklist

- [ ] Unit tests pass (`make test-unit`)
- [ ] Integration tests pass (`make test-integration`)
- [ ] Pre-commit hooks pass (`make pre-commit`)
- [ ] Documentation updated (if applicable)
- [ ] `CHANGELOG.md` updated

---

## Questions?

- Open a [Discussion](https://github.com/BigBrotr/bigbrotr/discussions) for questions
- Open an [Issue](https://github.com/BigBrotr/bigbrotr/issues) for bugs or feature requests
- Check existing issues before creating new ones
