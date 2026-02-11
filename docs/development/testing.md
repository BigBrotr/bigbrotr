# Testing

Test configuration, running tests, shared fixtures, mock patterns, and coverage requirements.

---

## Test Configuration

All test settings are defined in `pyproject.toml`:

| Setting | Value | Description |
|---------|-------|-------------|
| `asyncio_mode` | `auto` | No `@pytest.mark.asyncio` needed on async tests |
| `asyncio_default_fixture_loop_scope` | `function` | Each test gets its own event loop |
| `--timeout` | `120` | Global timeout per test (seconds) |
| `--strict-markers` | enabled | Undefined markers cause errors |
| `--strict-config` | enabled | Invalid config keys cause errors |
| `fail_under` | `80` | Minimum branch coverage percentage |

### Markers

Three markers are available for test categorization:

- **`slow`** -- Long-running tests (deselect with `-m "not slow"`)
- **`integration`** -- Tests requiring a database connection
- **`unit`** -- Tests with no external dependencies

!!! note
    Tests are auto-marked based on directory. Files under `tests/unit/` receive the `unit` marker;
    files under `tests/integration/` receive the `integration` marker.

---

## Running Tests

```bash
# All unit tests
make test-unit

# Skip slow tests
make test-fast

# Single file
pytest tests/unit/core/test_pool.py -v

# Single class
pytest tests/unit/core/test_pool.py::TestPoolRetry -v

# Pattern matching
pytest -k "test_health_check" -v

# Integration tests (requires Docker)
make test-integration

# Coverage with HTML report
make coverage
open htmlcov/index.html
```

---

## Test Structure

Tests mirror the source package layout under `tests/unit/`:

```text
tests/
+-- conftest.py                  # Root fixtures and pytest configuration
+-- fixtures/
|   +-- relays.py                # Shared relay fixtures (registered via pytest_plugins)
+-- unit/
|   +-- core/                    # test_pool.py, test_brotr.py, test_logger.py, ...
|   +-- models/                  # test_event.py, test_relay.py, test_metadata.py, ...
|   +-- nips/
|   |   +-- nip11/               # test_fetch.py, test_data.py, test_nip11.py, ...
|   |   +-- nip66/               # test_rtt.py, test_ssl.py, test_dns.py, test_geo.py, ...
|   +-- services/                # test_finder.py, test_validator.py, test_monitor.py, ...
|   |   +-- common/              # test_constants.py, test_queries.py, test_mixins.py
|   +-- utils/                   # test_dns.py, test_keys.py, test_transport.py, ...
+-- integration/                 # Integration tests (testcontainers PostgreSQL)
```

---

## Shared Fixtures

### Root Conftest (`tests/conftest.py`)

The root conftest provides core fixtures used across the entire test suite:

| Fixture | Type | Description |
|---------|------|-------------|
| `mock_pool` | `Pool` | Pool with mocked asyncpg internals |
| `mock_brotr` | `Brotr` | Brotr instance wrapping the mock pool |
| `mock_connection` | `MagicMock` | Mock asyncpg connection with async methods |
| `mock_asyncpg_pool` | `MagicMock` | Mock asyncpg pool with acquire context manager |
| `sample_event` | `EventRelay` | Sample Nostr event with relay association |
| `sample_relay` | `Relay` | Standard clearnet relay |
| `sample_metadata` | `RelayMetadata` | Sample relay metadata (NIP-11 info) |
| `sample_events_batch` | `list[EventRelay]` | Batch of 10 sample events |
| `sample_relays_batch` | `list[Relay]` | Batch of 10 clearnet relays |

The `create_mock_record()` helper function creates mock asyncpg `Record` objects from dictionaries.

### Relay Fixtures (`tests/fixtures/relays.py`)

Shared relay fixtures are registered via `pytest_plugins` in the root conftest:

```python
pytest_plugins = ["tests.fixtures.relays"]
```

Available fixtures:

| Fixture | Description |
|---------|-------------|
| `relay_clearnet` | Standard `wss://` clearnet relay |
| `relay_clearnet_with_port` | Clearnet relay with explicit port |
| `relay_clearnet_ws` | Non-TLS `ws://` clearnet relay |
| `relay_tor` | Tor `.onion` relay (56-char v3 address) |
| `relay_i2p` | I2P `.i2p` relay |
| `relay_loki` | Lokinet `.loki` relay |
| `relay_ipv6` | IPv6 relay with explicit port |
| `relay_overlay` | Parametrized overlay relay (tor/i2p/loki) |
| `relay_batch` | Batch of 10 clearnet relays |

---

## Mock Patterns

### Mocking Brotr Methods

Use `mock_brotr` for database operations. Its methods are pre-configured as `AsyncMock`:

```python
class TestMyService:
    async def test_fetch_relays(self, mock_brotr: Brotr) -> None:
        mock_brotr.fetch.return_value = [mock_record]
        mock_brotr.fetchval.return_value = 42
        mock_brotr.execute.return_value = "DELETE 5"
```

### Mocking at Service Module Namespace

Always mock at the **service module** namespace, not at the source definition:

```python
from unittest.mock import patch

# Correct: mock where the name is looked up
@patch("bigbrotr.services.validator.is_nostr_relay")
async def test_validation(mock_is_nostr):
    mock_is_nostr.return_value = True
    ...

# Incorrect: mocking at the definition site
@patch("bigbrotr.utils.transport.is_nostr_relay")  # won't affect the service
```

### Mocking Query Functions

Service tests mock query functions at the service module namespace:

```python
@patch("bigbrotr.services.finder.get_pending_urls")
async def test_finder_run(mock_get_pending):
    mock_get_pending.return_value = []
    ...
```

---

## Writing New Tests

### Conventions

- **File naming**: `test_<module>.py`, matching the source module name
- **Class naming**: `TestClassName` grouping related tests
- **Method naming**: `test_<behavior>` describing the expected outcome
- **Docstrings**: Brief description of what each test verifies
- **Async tests**: Use `async def` directly -- `asyncio_mode = "auto"` handles the rest

### Example

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

from bigbrotr.core.brotr import Brotr


class TestMyFeature:
    """Tests for the my_feature module."""

    async def test_success_returns_results(self, mock_brotr: Brotr) -> None:
        """Successful call returns expected results."""
        mock_brotr.fetch.return_value = [{"url": "wss://relay.example.com"}]
        # ... test logic ...

    async def test_empty_input_returns_empty(self, mock_brotr: Brotr) -> None:
        """Empty input produces empty output."""
        mock_brotr.fetch.return_value = []
        # ... test logic ...
```

---

## Integration Tests

Integration tests use [testcontainers](https://testcontainers-python.readthedocs.io/) to spin up
a real PostgreSQL instance in Docker:

```bash
# Run integration tests (requires Docker)
make test-integration
```

!!! warning
    Integration tests require Docker to be running. They start a PostgreSQL 16 container,
    run migrations, and execute tests against the real database.

The integration test suite validates stored procedures, cascade functions, and materialized
view refresh operations against a live database.

---

## Coverage Requirements

- **Minimum threshold**: 80% branch coverage (`fail_under = 80`)
- **Branch coverage** is enabled (`branch = true`)
- **Source**: `src/bigbrotr`

Lines excluded from coverage:

- `pragma: no cover` comments
- `if TYPE_CHECKING:` blocks
- `__repr__` methods
- Abstract methods

Generate a coverage report:

```bash
make coverage
open htmlcov/index.html
```

---

## Related Documentation

- [Setup](setup.md) -- Prerequisites, installation, and Makefile targets
- [Contributing](contributing.md) -- Code standards, PR process, and architecture rules
