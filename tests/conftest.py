"""
Pytest configuration and shared fixtures for BigBrotr tests.

Provides:
- Mock fixtures for Pool, Brotr, and asyncpg
- Sample data fixtures for events, relays, and metadata
- Custom pytest markers for test categorization
"""

import logging
import sys
from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.brotr import Brotr
from core.pool import Pool
from models import EventRelay, Nip11, Nip66, Relay, RelayMetadata

# ============================================================================
# Logging Configuration
# ============================================================================


@pytest.fixture(scope="session", autouse=True)
def setup_logging() -> None:
    """Configure logging for tests."""
    logging.basicConfig(level=logging.DEBUG)


# ============================================================================
# Mock Fixtures
# ============================================================================


@pytest.fixture
def mock_connection() -> MagicMock:
    """Create a mock asyncpg connection."""
    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetchval = AsyncMock(return_value=1)
    conn.execute = AsyncMock(return_value="OK")
    conn.executemany = AsyncMock()

    # Mock transaction context manager
    mock_transaction = MagicMock()
    mock_transaction.__aenter__ = AsyncMock(return_value=conn)
    mock_transaction.__aexit__ = AsyncMock(return_value=None)
    conn.transaction = MagicMock(return_value=mock_transaction)

    return conn


@pytest.fixture
def mock_asyncpg_pool(mock_connection: MagicMock) -> MagicMock:
    """Create a mock asyncpg pool."""
    pool = MagicMock()
    pool.close = AsyncMock()

    # Mock acquire context manager
    mock_acquire = MagicMock()
    mock_acquire.__aenter__ = AsyncMock(return_value=mock_connection)
    mock_acquire.__aexit__ = AsyncMock(return_value=None)
    pool.acquire = MagicMock(return_value=mock_acquire)

    return pool


@pytest.fixture
def mock_pool(
    mock_asyncpg_pool: MagicMock, mock_connection: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> Pool:
    """Create a Pool with mocked internals."""
    from core.pool import DatabaseConfig, PoolConfig

    monkeypatch.setenv("DB_PASSWORD", "test_password")

    config = PoolConfig(
        database=DatabaseConfig(
            host="localhost",
            port=5432,
            database="test_db",
            user="test_user",
        )
    )
    pool = Pool(config=config)
    pool._pool = mock_asyncpg_pool
    pool._is_connected = True

    # Store mock connection for easy access in tests
    pool._mock_connection = mock_connection  # type: ignore[attr-defined]

    return pool


@pytest.fixture
def mock_brotr(mock_pool: Pool) -> Brotr:
    """Create a Brotr instance with mocked pool."""
    return Brotr(pool=mock_pool)


# ============================================================================
# Configuration Fixtures
# ============================================================================


@pytest.fixture
def pool_config_dict() -> dict[str, Any]:
    """Sample pool configuration dictionary."""
    return {
        "database": {
            "host": "localhost",
            "port": 5432,
            "database": "test_db",
            "user": "test_user",
        },
        "limits": {
            "min_size": 2,
            "max_size": 10,
            "max_queries": 1000,
            "max_inactive_connection_lifetime": 60.0,
        },
        "timeouts": {
            "acquisition": 5.0,
            "health_check": 3.0,
        },
        "retry": {
            "max_attempts": 2,
            "initial_delay": 0.5,
            "max_delay": 2.0,
            "exponential_backoff": True,
        },
        "server_settings": {
            "application_name": "test_app",
            "timezone": "UTC",
        },
    }


@pytest.fixture
def brotr_config_dict() -> dict[str, Any]:
    """Sample Brotr configuration dictionary."""
    return {
        "pool": {
            "database": {
                "host": "localhost",
                "port": 5432,
                "database": "test_db",
                "user": "test_user",
            },
            "limits": {
                "min_size": 2,
                "max_size": 10,
            },
        },
        "batch": {
            "max_batch_size": 500,
        },
        "timeouts": {
            "query": 30.0,
            "procedure": 60.0,
            "batch": 90.0,
        },
    }


# ============================================================================
# Sample Data Fixtures
# ============================================================================


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
    if tags is None:
        tags = [["e", "c" * 64], ["p", "d" * 64]]

    mock_event = MagicMock()
    mock_event.id.return_value.to_hex.return_value = event_id
    mock_event.author.return_value.to_hex.return_value = pubkey
    mock_event.created_at.return_value.as_secs.return_value = created_at
    mock_event.kind.return_value.as_u16.return_value = kind
    mock_event.content.return_value = content
    mock_event.signature.return_value.to_hex.return_value = sig

    # Mock tags
    mock_tags = []
    for tag in tags:
        mock_tag = MagicMock()
        mock_tag.as_vec.return_value = tag
        mock_tags.append(mock_tag)
    mock_event.tags.return_value.to_vec.return_value = mock_tags

    return mock_event


def _create_nip11(
    relay: Relay, data: Optional[dict] = None, generated_at: int = 1700000001
) -> Nip11:
    """Create a Nip11 instance using object.__new__ pattern."""
    from models import Metadata

    if data is None:
        data = {
            "name": "Test Relay",
            "description": "A test relay for unit tests",
            "supported_nips": [1, 2, 9, 11],
        }
    metadata = Metadata(data)
    instance = object.__new__(Nip11)
    object.__setattr__(instance, "relay", relay)
    object.__setattr__(instance, "metadata", metadata)
    object.__setattr__(instance, "generated_at", generated_at)
    return instance


def _create_nip66(
    relay: Relay,
    rtt_data: Optional[dict] = None,
    geo_data: Optional[dict] = None,
    generated_at: int = 1700000001,
) -> Nip66:
    """Create a Nip66 instance using object.__new__ pattern."""
    from models import Metadata

    if rtt_data is None:
        rtt_data = {
            "rtt_open": 120,
            "rtt_read": 50,
            "network": "clearnet",
        }
    rtt_metadata = Metadata(rtt_data)
    geo_metadata = Metadata(geo_data) if geo_data else None

    instance = object.__new__(Nip66)
    object.__setattr__(instance, "relay", relay)
    object.__setattr__(instance, "rtt_metadata", rtt_metadata)
    object.__setattr__(instance, "geo_metadata", geo_metadata)
    object.__setattr__(instance, "generated_at", generated_at)
    return instance


@pytest.fixture
def sample_event() -> EventRelay:
    """Sample Nostr EventRelay for testing."""
    event = _make_mock_event()
    relay = Relay("wss://relay.example.com", discovered_at=1700000000)
    return EventRelay(event=event, relay=relay, seen_at=1700000001)


@pytest.fixture
def sample_relay() -> Relay:
    """Sample Relay for testing."""
    return Relay("wss://relay.example.com", discovered_at=1700000000)


@pytest.fixture
def sample_metadata() -> RelayMetadata:
    """Sample RelayMetadata for testing."""
    from models import Metadata

    relay = Relay("wss://relay.example.com", discovered_at=1700000000)
    metadata = Metadata({"name": "Test Relay", "supported_nips": [1, 2, 9, 11]})
    return RelayMetadata(
        relay=relay,
        metadata=metadata,
        metadata_type="nip11",
        generated_at=1700000001,
    )


@pytest.fixture
def sample_events_batch() -> list[EventRelay]:
    """Generate a batch of sample EventRelay objects."""
    relay = Relay("wss://relay.example.com", discovered_at=1700000000)
    return [
        EventRelay(
            event=_make_mock_event(
                event_id=f"{i:064x}",
                created_at=1700000000 + i,
                tags=[["e", "c" * 64]],
            ),
            relay=relay,
            seen_at=1700000001,
        )
        for i in range(10)
    ]


@pytest.fixture
def sample_relays_batch() -> list[Relay]:
    """Generate a batch of sample Relay objects."""
    return [Relay(f"wss://relay{i}.example.com", discovered_at=1700000000) for i in range(10)]


# ============================================================================
# Helper Functions
# ============================================================================


def create_mock_record(data: dict[str, Any]) -> MagicMock:
    """Create a mock asyncpg Record from a dictionary."""
    record = MagicMock()
    record.__getitem__ = lambda _, key: data[key]
    record.get = lambda key, default=None: data.get(key, default)
    record.keys = lambda: data.keys()
    record.values = lambda: data.values()
    record.items = lambda: data.items()
    return record


# ============================================================================
# Pytest Configuration
# ============================================================================


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests requiring database"
    )
    config.addinivalue_line("markers", "unit: marks tests as unit tests (no external dependencies)")
    config.addinivalue_line("markers", "slow: marks tests as slow running")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Auto-mark tests based on location."""
    for item in items:
        if "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
        elif "unit" in str(item.fspath):
            item.add_marker(pytest.mark.unit)
