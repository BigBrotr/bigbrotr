# Contributing to BigBrotr

Thank you for your interest in contributing to BigBrotr! This document provides guidelines and instructions for contributing.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Making Changes](#making-changes)
- [Pull Request Process](#pull-request-process)
- [Coding Standards](#coding-standards)
- [Testing](#testing)
- [Documentation](#documentation)

---

## Code of Conduct

This project adheres to a [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

---

## Getting Started

### Prerequisites

- Python 3.9 or higher
- Docker and Docker Compose
- Git

### Finding Issues

- Look for issues labeled `good first issue` for beginner-friendly tasks
- Issues labeled `help wanted` are open for community contribution
- Check the [roadmap](releases/v2.0.0.md#future-roadmap) for planned features

---

## Development Setup

```bash
# Clone the repository
git clone https://github.com/bigbrotr/bigbrotr.git
cd bigbrotr

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt -r requirements-dev.txt

# Install pre-commit hooks
pre-commit install

# Start database for testing
cd implementations/bigbrotr
docker-compose up -d postgres pgbouncer
cd ../..

# Run tests to verify setup
pytest tests/unit/ -v
```

---

## Making Changes

### Branch Naming

Create a branch from `develop` with a descriptive name:

```
feature/add-api-service
fix/connection-timeout
refactor/pool-retry-logic
docs/update-readme
test/add-monitor-tests
```

### Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add REST API service with OpenAPI documentation
fix: handle connection timeout in pool retry logic
refactor: simplify retry logic in connection pool
docs: update architecture documentation
test: add monitor health check tests
chore: update dependencies
```

### Code Changes

1. **Create a branch** from `develop`
2. **Make your changes** following the coding standards
3. **Write tests** for new functionality
4. **Run the test suite** to ensure nothing is broken
5. **Update documentation** if needed
6. **Commit your changes** with a clear message

---

## Pull Request Process

### Before Submitting

1. Run all checks:
   ```bash
   # Run tests
   pytest tests/unit/ -v

   # Run linting and formatting
   pre-commit run --all-files
   ```

2. Update documentation if you changed:
   - Public API
   - Configuration options
   - Database schema
   - Deployment process

3. Add your changes to `CHANGELOG.md` under `[Unreleased]`

### Submitting

1. Push your branch to your fork
2. Create a Pull Request to `develop` (or `main` for releases)
3. Fill out the PR template completely
4. Wait for CI checks to pass
5. Address any review feedback

### PR Requirements

- [ ] Tests pass
- [ ] Pre-commit hooks pass
- [ ] Documentation updated (if applicable)
- [ ] CHANGELOG.md updated
- [ ] PR description explains the changes

---

## Coding Standards

### Python Style

- Follow [PEP 8](https://peps.python.org/pep-0008/)
- Use type hints for all public interfaces
- Maximum line length: 88 characters (Black default)
- Use docstrings for classes and public methods

### Code Quality Tools

```bash
# Linting
ruff check src/ tests/

# Formatting
ruff format src/ tests/

# Type checking
mypy src/

# All checks via pre-commit
pre-commit run --all-files
```

### Architecture Guidelines

- **Core layer** is implementation-agnostic
- **Services** receive dependencies via injection
- **Configuration** uses Pydantic models
- **Database** operations use stored procedures
- **Async** for all I/O operations

---

## Testing

### Running Tests

```bash
# All tests
pytest tests/unit/ -v

# Specific file
pytest tests/unit/test_pool.py -v

# With coverage
pytest tests/unit/ --cov=src --cov-report=html

# Matching pattern
pytest -k "health_check" -v
```

### Writing Tests

- Place tests in `tests/unit/`
- Name test files `test_<module>.py`
- Use fixtures from `conftest.py`
- Mock external dependencies
- Test both success and error cases

Example:

```python
import pytest
from unittest.mock import MagicMock, AsyncMock

class TestMyService:
    @pytest.fixture
    def mock_brotr(self) -> MagicMock:
        brotr = MagicMock()
        brotr.pool = MagicMock()
        brotr.pool.fetch = AsyncMock(return_value=[])
        return brotr

    @pytest.mark.asyncio
    async def test_run_success(self, mock_brotr: MagicMock) -> None:
        service = MyService(brotr=mock_brotr)
        await service.run()
        mock_brotr.pool.fetch.assert_called_once()
```

---

## Documentation

### When to Update

- New features or services
- Configuration changes
- Database schema changes
- API changes
- Deployment process changes

### Documentation Files

| File | Purpose |
|------|---------|
| `README.md` | Project overview, quick start |
| `docs/ARCHITECTURE.md` | System architecture |
| `docs/CONFIGURATION.md` | Configuration reference |
| `docs/DATABASE.md` | Database schema |
| `docs/DEVELOPMENT.md` | Development guide |
| `docs/DEPLOYMENT.md` | Deployment instructions |
| `CHANGELOG.md` | Version history |

### Style

- Use clear, concise language
- Include code examples where helpful
- Keep documentation in sync with code
- Use tables for structured information

---

## Questions?

- Open a [Discussion](https://github.com/bigbrotr/bigbrotr/discussions) for questions
- Open an [Issue](https://github.com/bigbrotr/bigbrotr/issues) for bugs or feature requests
- Check existing issues before creating new ones

Thank you for contributing!
