# Development Setup

Prerequisites, installation, project layout, and tooling for BigBrotr development.

---

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.11+ | Tested on 3.11, 3.12, 3.13, 3.14 |
| Git | any | For version control and pre-commit hooks |
| Docker | any | Required for integration tests and local deployments |

---

## Installation

```bash
# Clone the repository
git clone https://github.com/BigBrotr/bigbrotr.git
cd bigbrotr

# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install with development and documentation dependencies
uv sync --group dev --group docs

# Install pre-commit hooks
pre-commit install

# Verify the setup
make ci
```

!!! tip
    `make install` runs `uv sync --group dev --group docs` and `pre-commit install` in one step.

---

## IDE Configuration

### VS Code

Create `.vscode/launch.json` to debug a service:

```json
{
    "name": "BigBrotr Finder",
    "type": "debugpy",
    "request": "launch",
    "module": "bigbrotr",
    "args": ["finder", "--log-level", "DEBUG", "--once"],
    "cwd": "${workspaceFolder}/deployments/bigbrotr",
    "env": {
        "DB_ADMIN_PASSWORD": "your_password"
    }
}
```

### PyCharm

- **Module**: `bigbrotr`
- **Parameters**: `finder --log-level DEBUG --once`
- **Working directory**: `deployments/bigbrotr`
- **Environment variables**: `DB_ADMIN_PASSWORD=your_password`

---

## Project Structure

```text
bigbrotr/
+-- src/bigbrotr/                     # Source package
|   +-- __init__.py
|   +-- __main__.py                   # CLI entry point
|   +-- core/                         # Pool, Brotr, BaseService, Logger, Metrics, YAML
|   +-- models/                       # Frozen dataclasses (pure, zero I/O)
|   |   +-- service_state.py          # ServiceState, ServiceStateType
|   +-- nips/                         # NIP-11 and NIP-66 protocol I/O
|   |   +-- nip11/                    # Relay info document fetch/parse
|   |   +-- nip66/                    # Monitoring: dns, geo, http, net, rtt, ssl
|   +-- services/                     # Business logic (6 services)
|   |   +-- seeder/                   # Relay seed loading
|   |   +-- finder/                   # Relay URL discovery
|   |   +-- validator/                # Candidate validation
|   |   +-- monitor/                  # Health check orchestration, publishing, tags
|   |   +-- synchronizer/             # Event collection
|   |   +-- refresher/                # Materialized view refresh
|   |   +-- common/                   # Shared constants, configs, queries, mixins
|   +-- utils/                        # DNS, keys, transport helpers
+-- tests/
|   +-- conftest.py                   # Root fixtures (mock_pool, mock_brotr, etc.)
|   +-- fixtures/
|   |   +-- relays.py                 # Shared relay fixtures
|   +-- unit/                         # Unit tests mirroring src/ structure
|   +-- integration/                  # Integration tests (require database)
+-- deployments/
|   +-- Dockerfile                    # Single parametric Dockerfile
|   +-- bigbrotr/                     # Full-featured deployment
|   +-- lilbrotr/                     # Lightweight deployment
+-- tools/
|   +-- generate_sql.py              # SQL template generator
|   +-- templates/sql/               # Jinja2 SQL templates (base + overrides)
+-- docs/                             # Documentation (MkDocs Material)
+-- .github/                          # CI/CD workflows
+-- Makefile                          # Development commands
+-- pyproject.toml                    # Project configuration
+-- .pre-commit-config.yaml           # Pre-commit hooks
```

---

## Makefile Targets

All common development tasks are available as Makefile targets:

### Code Quality

| Target | Command | Description |
|--------|---------|-------------|
| `make lint` | `ruff check src/ tests/` | Run ruff linter |
| `make format` | `ruff format src/ tests/` | Run ruff formatter |
| `make format-check` | `ruff format --check src/ tests/` | Check formatting without modifying |
| `make typecheck` | `mypy src/bigbrotr` | Run mypy strict type checking |
| `make pre-commit` | `pre-commit run --all-files` | Run all pre-commit hooks |

### Testing

| Target | Command | Description |
|--------|---------|-------------|
| `make test-unit` | `pytest tests/ --ignore=tests/integration/` | Run unit tests |
| `make test-integration` | `pytest tests/integration/` | Run integration tests (requires Docker) |
| `make test-fast` | `pytest -m "not slow"` | Run unit tests excluding slow markers |
| `make coverage` | `pytest --cov=src/bigbrotr --cov-report=html` | Run tests with HTML coverage report |

### Documentation

| Target | Command | Description |
|--------|---------|-------------|
| `make docs` | `mkdocs build --strict` | Build MkDocs documentation site |
| `make docs-serve` | `mkdocs serve` | Serve docs locally with live reload |

### Build and Deploy

| Target | Command | Description |
|--------|---------|-------------|
| `make build` | `uv build` | Build Python package (sdist + wheel) |
| `make docker-build` | `docker build ...` | Build Docker image (`DEPLOYMENT=bigbrotr`) |
| `make docker-up` | `docker compose ... up -d` | Start Docker stack |
| `make docker-down` | `docker compose ... down` | Stop Docker stack |

### Maintenance

| Target | Command | Description |
|--------|---------|-------------|
| `make ci` | lint + format-check + typecheck + test-unit + sql-check + audit | Run all quality checks |
| `make sql-generate` | `python3 tools/generate_sql.py` | Regenerate SQL files from templates |
| `make sql-check` | `python3 tools/generate_sql.py --check` | Verify generated SQL matches templates |
| `make audit` | `uv-secure uv.lock` | Check dependencies for known vulnerabilities |
| `make clean` | rm -rf build artifacts | Remove build artifacts and caches |
| `make install` | `uv sync --group dev --group docs && pre-commit install` | Install dev dependencies and hooks |

!!! note
    The `DEPLOYMENT` variable defaults to `bigbrotr`. Override it for other deployments:
    `make docker-build DEPLOYMENT=lilbrotr`.

---

## Related Documentation

- [Testing](testing.md) -- Test configuration, fixtures, and mock patterns
- [Coding Standards](coding-standards.md) -- Linting, formatting, import rules, and patterns
- [SQL Templates](sql-templates.md) -- Schema generation from Jinja2 templates
- [Contributing](contributing.md) -- Branch workflow and PR process
