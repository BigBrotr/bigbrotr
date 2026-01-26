# Testing Reference

Complete testing guide for BigBrotr including fixtures, patterns, mock strategies, and example tests for each layer.

## Test Organization

```
tests/
+-- conftest.py                  # Shared fixtures and configuration
+-- unit/                        # Unit tests
|   +-- core/                    # Core layer tests
|   |   +-- test_pool.py
|   |   +-- test_brotr.py
|   |   +-- test_base_service.py
|   |   +-- test_logger.py
|   +-- services/                # Service layer tests
|   |   +-- test_seeder.py
|   |   +-- test_finder.py
|   |   +-- test_validator.py
|   |   +-- test_monitor.py
|   |   +-- test_synchronizer.py
|   +-- models/                  # Model layer tests
|       +-- test_relay.py
|       +-- test_event_relay.py
|       +-- test_metadata.py
|       +-- test_nip11.py
|       +-- test_nip66.py
+-- integration/                 # Integration tests (planned)
```

---

## Pytest Configuration

**Custom Markers** (in `conftest.py`):
```python
@pytest.mark.unit         # Unit tests (no external dependencies)
@pytest.mark.integration  # Integration tests (require database)
@pytest.mark.slow         # Slow running tests
```

**Run Commands**:
```bash
# All unit tests
pytest tests/ -v

# Specific test file
pytest tests/unit/core/test_pool.py -v

# Pattern matching
pytest -k "test_insert" -v

# With coverage
pytest tests/ --cov=src --cov-report=html

# Markers
pytest -m unit -v
pytest -m "not slow" -v
```

---

## Available Fixtures

### Mock Fixtures

#### mock_connection

Mock asyncpg connection with common methods.

```python
@pytest.fixture
def mock_connection() -> MagicMock:
    """Create a mock asyncpg connection."""
    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetchval = AsyncMock(return_value=1)
    conn.execute = AsyncMock(return_value="OK")
    conn.executemany = AsyncMock()
    # Transaction support
    conn.transaction = MagicMock(return_value=mock_transaction)
    return conn
```

**Usage**:
```python
async def test_query(mock_connection):
    result = await mock_connection.fetch("SELECT * FROM events")
    assert result == []
```

#### mock_asyncpg_pool

Mock asyncpg pool with acquire context manager.

```python
@pytest.fixture
def mock_asyncpg_pool(mock_connection: MagicMock) -> MagicMock:
    """Create a mock asyncpg pool."""
    pool = MagicMock()
    pool.close = AsyncMock()
    mock_acquire = MagicMock()
    mock_acquire.__aenter__ = AsyncMock(return_value=mock_connection)
    mock_acquire.__aexit__ = AsyncMock(return_value=None)
    pool.acquire = MagicMock(return_value=mock_acquire)
    return pool
```

#### mock_pool

Pool with mocked internals (ready to use).

```python
@pytest.fixture
def mock_pool(mock_asyncpg_pool, mock_connection, monkeypatch) -> Pool:
    """Create a Pool with mocked internals."""
    monkeypatch.setenv("DB_PASSWORD", "test_password")

    config = PoolConfig(
        database=DatabaseConfig(
            host="localhost",
            port=5432,
            database="test_db",
            user="test_user"
        )
    )
    pool = Pool(config=config)
    pool._pool = mock_asyncpg_pool
    pool._is_connected = True
    pool._mock_connection = mock_connection  # For easy access
    return pool
```

**Usage**:
```python
async def test_with_pool(mock_pool):
    result = await mock_pool.fetch("SELECT 1")
    assert mock_pool._mock_connection.fetch.called
```

#### mock_brotr

Brotr with mocked pool.

```python
@pytest.fixture
def mock_brotr(mock_pool: Pool) -> Brotr:
    """Create a Brotr instance with mocked pool."""
    return Brotr(pool=mock_pool)
```

---

### Configuration Fixtures

#### pool_config_dict

Sample pool configuration dictionary.

```python
@pytest.fixture
def pool_config_dict() -> dict[str, Any]:
    """Sample pool configuration dictionary."""
    return {
        "database": {
            "host": "localhost",
            "port": 5432,
            "database": "test_db",
            "user": "test_user"
        },
        "limits": {
            "min_size": 2,
            "max_size": 10,
            "max_queries": 1000,
            "max_inactive_connection_lifetime": 60.0
        },
        "timeouts": {
            "acquisition": 5.0,
            "health_check": 3.0
        },
        "retry": {
            "max_attempts": 2,
            "initial_delay": 0.5,
            "max_delay": 2.0,
            "exponential_backoff": True
        }
    }
```

#### brotr_config_dict

Sample Brotr configuration dictionary.

```python
@pytest.fixture
def brotr_config_dict() -> dict[str, Any]:
    """Sample Brotr configuration dictionary."""
    return {
        "pool": {...},  # Pool config
        "batch": {"max_batch_size": 500},
        "timeouts": {
            "query": 30.0,
            "procedure": 60.0,
            "batch": 90.0
        }
    }
```

---

### Sample Data Fixtures

#### sample_relay

Sample Relay for testing.

```python
@pytest.fixture
def sample_relay() -> Relay:
    """Sample Relay for testing."""
    return Relay("wss://relay.example.com", discovered_at=1700000000)
```

#### sample_event

Sample EventRelay for testing.

```python
@pytest.fixture
def sample_event() -> EventRelay:
    """Sample Nostr EventRelay for testing."""
    event = _make_mock_event()
    relay = Relay("wss://relay.example.com", discovered_at=1700000000)
    return EventRelay(event=event, relay=relay, seen_at=1700000001)
```

#### sample_metadata

Sample RelayMetadata for testing.

```python
@pytest.fixture
def sample_metadata() -> RelayMetadata:
    """Sample RelayMetadata for testing."""
    relay = Relay("wss://relay.example.com", discovered_at=1700000000)
    metadata = Metadata({"name": "Test Relay", "supported_nips": [1, 2, 9, 11]})
    return RelayMetadata(
        relay=relay,
        metadata=metadata,
        metadata_type="nip11",
        snapshot_at=1700000001
    )
```

#### sample_events_batch / sample_relays_batch

Batch of sample data.

```python
@pytest.fixture
def sample_events_batch() -> list[EventRelay]:
    """Generate a batch of sample EventRelay objects."""
    relay = Relay("wss://relay.example.com")
    return [EventRelay(event=_make_mock_event(...), relay=relay) for i in range(10)]

@pytest.fixture
def sample_relays_batch() -> list[Relay]:
    """Generate a batch of sample Relay objects."""
    return [Relay(f"wss://relay{i}.example.com") for i in range(10)]
```

---

## Helper Functions

### _make_mock_event

Create a mock nostr_sdk.Event for testing.

```python
def _make_mock_event(
    event_id: str = "a" * 64,
    pubkey: str = "b" * 64,
    created_at: int = 1700000000,
    kind: int = 1,
    tags: Optional[list[list[str]]] = None,
    content: str = "Test content",
    sig: str = "e" * 128,
) -> MagicMock:
    """Create a mock nostr_sdk.Event for testing."""
    mock_event = MagicMock()
    mock_event.id.return_value.to_hex.return_value = event_id
    mock_event.author.return_value.to_hex.return_value = pubkey
    mock_event.created_at.return_value.as_secs.return_value = created_at
    mock_event.kind.return_value.as_u16.return_value = kind
    mock_event.content.return_value = content
    mock_event.signature.return_value.to_hex.return_value = sig
    # Mock tags...
    return mock_event
```

### _create_nip11 / _create_nip66

Create Nip11/Nip66 instances using object.__new__ pattern.

```python
def _create_nip11(relay: Relay, data: Optional[dict] = None, snapshot_at: int = 1700000001) -> Nip11:
    """Create a Nip11 instance using object.__new__ pattern."""
    if data is None:
        data = {"name": "Test Relay", "supported_nips": [1, 2, 9, 11]}
    metadata = Metadata(data)
    instance = object.__new__(Nip11)
    object.__setattr__(instance, "relay", relay)
    object.__setattr__(instance, "metadata", metadata)
    object.__setattr__(instance, "snapshot_at", snapshot_at)
    return instance
```

### create_mock_record

Create a mock asyncpg Record from a dictionary.

```python
def create_mock_record(data: dict[str, Any]) -> MagicMock:
    """Create a mock asyncpg Record from a dictionary."""
    record = MagicMock()
    record.__getitem__ = lambda _, key: data[key]
    record.get = lambda key, default=None: data.get(key, default)
    return record
```

---

## Testing Patterns

### Unit Test Pattern (No External Dependencies)

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

async def test_pool_fetch(mock_pool):
    """Test Pool.fetch method."""
    # Setup
    expected_result = [{"id": 1, "name": "test"}]
    mock_pool._mock_connection.fetch = AsyncMock(return_value=expected_result)

    # Execute
    result = await mock_pool.fetch("SELECT * FROM events")

    # Verify
    assert result == expected_result
    mock_pool._mock_connection.fetch.assert_called_once_with(
        "SELECT * FROM events",
        timeout=None
    )
```

### Integration Test Pattern (Requires Database)

```python
import pytest

@pytest.mark.integration
async def test_insert_events_real_db():
    """Test event insertion with real database."""
    # Setup
    pool = Pool.from_yaml("tests/config/test_pool.yaml")
    brotr = Brotr(pool=pool)

    async with pool:
        # Execute
        relay = Relay("wss://test.relay.com")
        event = EventRelay.from_nostr_event(mock_event, relay)
        inserted, skipped = await brotr.insert_events([event])

        # Verify
        assert inserted == 1
        assert skipped == 0

        # Cleanup
        await pool.execute("DELETE FROM events WHERE id = $1", event_id)
```

### Service Test Pattern

```python
import pytest
from unittest.mock import AsyncMock

async def test_finder_run(mock_brotr):
    """Test Finder.run method."""
    # Setup
    config = FinderConfig(
        interval=60.0,
        events=EventsConfig(enabled=False),
        api=ApiConfig(enabled=False)
    )
    finder = Finder(brotr=mock_brotr, config=config)

    # Mock database responses
    mock_brotr.pool.fetch = AsyncMock(return_value=[])

    # Execute
    await finder.run()

    # Verify
    assert mock_brotr.pool.fetch.called
```

### Model Test Pattern

```python
import pytest

def test_relay_creation():
    """Test Relay creation and validation."""
    # Valid relay
    relay = Relay("wss://relay.example.com")
    assert relay.url == "wss://relay.example.com"
    assert relay.network == "clearnet"
    assert relay.scheme == "wss"
    assert relay.host == "relay.example.com"

    # Invalid relay (local address)
    with pytest.raises(ValueError, match="Local addresses not allowed"):
        Relay("wss://localhost")

    # Invalid relay (unknown network)
    with pytest.raises(ValueError, match="Invalid host"):
        Relay("wss://invalid..host")
```

---

## Example Tests by Layer

### Core Layer Tests

**test_pool.py**:
```python
import pytest
from core import Pool, PoolConfig

async def test_pool_connect_success(mock_asyncpg_pool, monkeypatch):
    """Test successful pool connection."""
    monkeypatch.setenv("DB_PASSWORD", "test_password")

    pool = Pool(config=PoolConfig())
    pool._pool = mock_asyncpg_pool

    await pool.connect()
    assert pool.is_connected

async def test_pool_fetch(mock_pool):
    """Test fetch method."""
    mock_pool._mock_connection.fetch = AsyncMock(return_value=[{"id": 1}])
    result = await mock_pool.fetch("SELECT * FROM events")
    assert len(result) == 1
```

**test_brotr.py**:
```python
import pytest
from core import Brotr

async def test_insert_events(mock_brotr, sample_events_batch):
    """Test event insertion."""
    mock_brotr.pool._mock_connection.executemany = AsyncMock()

    inserted, skipped = await mock_brotr.insert_events(sample_events_batch)

    assert inserted == 10
    assert skipped == 0
    assert mock_brotr.pool._mock_connection.executemany.called
```

**test_base_service.py**:
```python
import pytest
from core import BaseService
from pydantic import BaseModel

class TestConfig(BaseModel):
    value: int = 42

class TestService(BaseService[TestConfig]):
    SERVICE_NAME = "test"
    CONFIG_CLASS = TestConfig

    async def run(self):
        self._logger.info("running")

async def test_service_lifecycle(mock_brotr):
    """Test service lifecycle."""
    service = TestService(brotr=mock_brotr, config=TestConfig())

    async with service:
        assert service.is_running
        await service.run()

    assert not service.is_running
```

### Service Layer Tests

**test_finder.py**:
```python
import pytest
from services.finder import Finder, FinderConfig

async def test_finder_find_from_events(mock_brotr):
    """Test event scanning."""
    config = FinderConfig(
        events=EventsConfig(enabled=True),
        api=ApiConfig(enabled=False)
    )
    finder = Finder(brotr=mock_brotr, config=config)

    # Mock database responses
    mock_brotr.pool.fetch = AsyncMock(return_value=[])

    await finder._find_from_events()

    assert mock_brotr.pool.fetch.called
```

**test_monitor.py**:
```python
import pytest
from services.monitor import Monitor, MonitorConfig

async def test_monitor_process_relay(mock_brotr, sample_relay):
    """Test relay processing."""
    config = MonitorConfig(
        checks=ChecksConfig(geo=False)  # Disable geo to avoid DB requirement
    )
    monitor = Monitor(brotr=mock_brotr, config=config)

    semaphore = asyncio.Semaphore(1)
    result = await monitor._process_relay(sample_relay, semaphore)

    assert isinstance(result, list)
```

### Model Layer Tests

**test_relay.py**:
```python
import pytest
from models import Relay

def test_relay_url_parsing():
    """Test URL parsing."""
    relay = Relay("wss://relay.example.com:9000/path")
    assert relay.host == "relay.example.com"
    assert relay.port == 9000
    assert relay.path == "/path"
    assert relay.network == "clearnet"

def test_relay_network_detection():
    """Test network detection."""
    assert Relay("wss://abc123.onion").network == "tor"
    assert Relay("wss://example.i2p").network == "i2p"
    assert Relay("wss://example.loki").network == "loki"
    assert Relay("wss://relay.com").network == "clearnet"

def test_relay_to_db_params():
    """Test database parameter conversion."""
    relay = Relay("wss://relay.example.com", discovered_at=1700000000)
    params = relay.to_db_params()
    assert params == ("wss://relay.example.com", "clearnet", 1700000000)
```

**test_nip11.py**:
```python
import pytest
from models import Nip11, Relay, Metadata

async def test_nip11_fetch_success(monkeypatch):
    """Test NIP-11 fetch."""
    relay = Relay("wss://relay.example.com")

    # Mock aiohttp response
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={"name": "Test Relay"})

    # Patch aiohttp.ClientSession
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=mock_response)
    monkeypatch.setattr("aiohttp.ClientSession", lambda **kwargs: mock_session)

    nip11 = await Nip11.fetch(relay)
    assert nip11 is not None
    assert nip11.name == "Test Relay"
```

---

## Mock Strategies

### Mocking asyncpg

```python
# Mock connection
conn = MagicMock()
conn.fetch = AsyncMock(return_value=[])
conn.fetchrow = AsyncMock(return_value=None)

# Mock transaction
mock_transaction = MagicMock()
mock_transaction.__aenter__ = AsyncMock(return_value=None)
mock_transaction.__aexit__ = AsyncMock(return_value=None)
conn.transaction = MagicMock(return_value=mock_transaction)
```

### Mocking nostr_sdk.Event

```python
mock_event = MagicMock()
mock_event.id.return_value.to_hex.return_value = "a" * 64
mock_event.author.return_value.to_hex.return_value = "b" * 64
mock_event.created_at.return_value.as_secs.return_value = 1700000000
mock_event.kind.return_value.as_u16.return_value = 1
```

### Mocking aiohttp

```python
import aiohttp
from unittest.mock import AsyncMock, MagicMock

# Mock response
mock_response = AsyncMock()
mock_response.status = 200
mock_response.json = AsyncMock(return_value={"data": "value"})

# Mock session
mock_session = MagicMock()
mock_session.get = AsyncMock(return_value=mock_response)
monkeypatch.setattr("aiohttp.ClientSession", lambda **kwargs: mock_session)
```

---

## Coverage Guidelines

**Target**: 80%+ code coverage for core and services layers

**Run Coverage**:
```bash
pytest tests/ --cov=src --cov-report=html
open htmlcov/index.html
```

**Focus Areas**:
- Core layer: 90%+ (critical infrastructure)
- Service layer: 80%+ (business logic)
- Model layer: 70%+ (mostly validation)

**Excluded**:
- `__init__.py` files
- Type stubs
- Migration scripts
