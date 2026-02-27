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

## Test Organization

### Class Per Logical Unit

Group tests by the method or behavior under test. Each class covers one logical unit:

```python
class TestPoolConnect:
    """Tests for Pool.connect() method."""

    async def test_connect_success(self, mock_db_password: str) -> None:
        """First connection attempt succeeds."""
        ...

    async def test_connect_retry_on_failure(self, mock_db_password: str) -> None:
        """Retries with backoff on connection error."""
        ...

    async def test_connect_exhausted(self, mock_db_password: str) -> None:
        """Raises ConnectionError after max attempts."""
        ...
```

Class-specific fixtures go as methods on the class; shared fixtures belong in conftest.

### Naming Conventions

- **Files**: `test_<module>.py` mirrors `<module>.py` in source
- **Classes**: `TestClassName` grouping related tests (e.g., `TestPoolConnect`, `TestPoolRetry`)
- **Methods**: `test_<method>_<scenario>` describing what is being tested and under what condition

### What to Test

Every public method should have tests covering at minimum:

1. **Happy path** -- Normal input produces expected output
2. **Empty input** -- Empty list, None, zero-length string
3. **Error path** -- Exceptions raised, error handling behavior
4. **Edge cases** -- Boundary values, unusual but valid input

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

The `create_mock_record()` helper function creates mock asyncpg `Record` objects from dictionaries:

```python
from tests.conftest import create_mock_record

record = create_mock_record({"url": "wss://relay.example.com", "network": "clearnet"})
assert record["url"] == "wss://relay.example.com"
```

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

### Mock Target Rule

Always mock at the **consumer's namespace**, not at the source definition:

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

### Mocking Brotr Methods

Use `mock_brotr` for database operations. Its methods are pre-configured as `AsyncMock`:

```python
class TestMyService:
    async def test_fetch_relays(self, mock_brotr: Brotr) -> None:
        mock_brotr.fetch.return_value = [mock_record]
        mock_brotr.fetchval.return_value = 42
        mock_brotr.execute.return_value = "DELETE 5"
```

### Mocking Query Functions

Service tests mock query functions at the service module namespace:

```python
@patch("bigbrotr.services.seeder.filter_new_relay_urls", new_callable=AsyncMock)
@patch("bigbrotr.services.seeder.get_all_relay_urls", new_callable=AsyncMock)
async def test_seeder_run(self, mock_get_urls, mock_filter, mock_brotr):
    mock_get_urls.return_value = ["wss://a.com"]
    mock_filter.return_value = ["wss://new.com"]
    ...
```

### Mock asyncpg Connection

The root conftest provides `mock_connection` with pre-configured async methods:

```python
@pytest.fixture
def mock_connection() -> MagicMock:
    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetchval = AsyncMock(return_value=1)
    conn.execute = AsyncMock(return_value="OK")
    conn.executemany = AsyncMock()

    # Transaction context manager
    mock_transaction = MagicMock()
    mock_transaction.__aenter__ = AsyncMock(return_value=conn)
    mock_transaction.__aexit__ = AsyncMock(return_value=None)
    conn.transaction = MagicMock(return_value=mock_transaction)
    return conn
```

### Mock nostr_sdk Events

```python
from tests.conftest import make_mock_event

mock_event = make_mock_event(
    event_id="a" * 64,
    pubkey="b" * 64,
    created_at=1700000000,
    kind=1,
    tags=[["e", "c" * 64], ["p", "d" * 64]],
    content="Test content",
)
event = Event(mock_event)
```

---

## Async Test Patterns

### Basic Async Tests

`asyncio_mode = "auto"` handles event loop setup -- use `async def` directly:

```python
async def test_fetch_returns_rows(self, mock_pool: Pool) -> None:
    rows = await mock_pool.fetch("SELECT 1")
    assert rows == []
```

Async fixtures also need no special decorator:

```python
@pytest.fixture
async def connected_pool(mock_pool: Pool) -> Pool:
    await mock_pool.connect()
    return mock_pool
```

### Testing `run_forever()`

Mock `wait()` to return `True` (shutdown requested) after the first cycle:

```python
async def test_run_forever_single_cycle(self, service: MyService) -> None:
    service.wait = AsyncMock(return_value=True)
    service.run = AsyncMock()

    await service.run_forever()

    service.run.assert_called_once()
```

### Testing Service Lifecycle

Test the `async with` context manager protocol:

```python
async def test_service_lifecycle(self, mock_brotr: Brotr) -> None:
    service = MyService(brotr=mock_brotr)
    async with service:
        assert service.is_running
    assert not service.is_running
```

---

## Service Test Patterns

### Config Validation

```python
class TestMyServiceConfig:
    def test_defaults(self) -> None:
        config = MyConfig()
        assert config.interval == 300.0
        assert config.batch_size == 100

    def test_custom_values(self) -> None:
        config = MyConfig(interval=60.0, batch_size=50)
        assert config.interval == 60.0

    def test_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            MyConfig(batch_size=-1)  # ge=1 constraint
```

### Error Handling

```python
async def test_run_handles_connectivity_error(self, service, mock_brotr):
    mock_brotr.fetch.side_effect = ConnectionError("unreachable")

    # Should not raise -- handled internally
    await service.run()

    service._logger.error.assert_called()
```

### Metrics

```python
async def test_run_increments_counter(self, service):
    await service.run()
    service.inc_counter.assert_any_call("total_processed", 5)
    service.set_gauge.assert_any_call("pending", 0)
```

---

## Model Test Patterns

### Construction and Validation

```python
class TestRelay:
    def test_valid_clearnet(self) -> None:
        relay = Relay("wss://relay.example.com", discovered_at=1700000000)
        assert relay.network == NetworkType.CLEARNET

    def test_invalid_scheme_rejected(self) -> None:
        with pytest.raises(ValueError, match="scheme"):
            Relay("http://relay.example.com", discovered_at=1700000000)

    def test_local_ip_rejected(self) -> None:
        with pytest.raises(ValueError, match="local"):
            Relay("wss://192.168.1.1", discovered_at=1700000000)
```

### Immutability

```python
def test_frozen(self) -> None:
    relay = Relay("wss://relay.example.com", discovered_at=1700000000)
    with pytest.raises(FrozenInstanceError):
        relay.url = "wss://other.com"
```

### Parametrized Network Tests

```python
@pytest.mark.parametrize("url,expected_network", [
    ("wss://relay.example.com", NetworkType.CLEARNET),
    ("wss://example.onion", NetworkType.TOR),
    ("wss://example.i2p", NetworkType.I2P),
    ("wss://example.loki", NetworkType.LOKI),
])
def test_network_detection(self, url, expected_network) -> None:
    relay = Relay(url, discovered_at=1700000000)
    assert relay.network == expected_network
```

Use the shared `relay_overlay` fixture for 3-way parametrized tests (tor, i2p, loki).

---

## Common Pitfalls

### Mock at Wrong Namespace

Mocking at the definition site (`bigbrotr.utils.transport.func`) instead of the
consumer's namespace (`bigbrotr.services.validator.func`) has no effect. The import
already resolved the reference. Always mock where the name is looked up.

### Forgetting `new_callable=AsyncMock`

When using `@patch` on async functions, pass `new_callable=AsyncMock`. A regular
`MagicMock` returns a `MagicMock` (not a coroutine) on call, causing `TypeError`
or unexpected behavior:

```python
# Correct
@patch("bigbrotr.services.finder.discover_urls", new_callable=AsyncMock)

# Wrong -- returns MagicMock, not awaitable
@patch("bigbrotr.services.finder.discover_urls")
```

### Forgetting `await`

If an async mock returns a value but the test sees a coroutine object, you likely
forgot `await`. This manifests as assertions passing on the coroutine itself
(truthy) rather than the actual value.

### Stale Fixtures After Refactoring

After moving or renaming modules, update patch targets in tests. A mock targeting
a stale import path silently does nothing -- the real function runs instead.

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
- [Coding Standards](coding-standards.md) -- Linting, formatting, import rules, and patterns
- [Contributing](contributing.md) -- Branch workflow and PR process
