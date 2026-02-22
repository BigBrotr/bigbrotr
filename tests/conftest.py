"""
Pytest configuration and shared fixtures for BigBrotr tests.

Provides:
- Mock fixtures for Pool, Brotr, and asyncpg
- Sample data fixtures for events, relays, and metadata
- Environment variable fixtures for secrets
- Custom pytest markers for test categorization
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from nostr_sdk import Event as NostrEvent

from bigbrotr.core.brotr import Brotr
from bigbrotr.core.pool import Pool
from bigbrotr.models import EventRelay, Relay, RelayMetadata
from bigbrotr.models.event import Event
from bigbrotr.models.metadata import Metadata, MetadataType


pytest_plugins = ["tests.fixtures.relays"]


# ============================================================================
# Logging Configuration
# ============================================================================


@pytest.fixture(scope="session", autouse=True)
def setup_logging() -> None:
    """Configure logging for tests."""
    logging.basicConfig(level=logging.DEBUG)


# ============================================================================
# Environment Fixtures
# ============================================================================


@pytest.fixture
def mock_private_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """Set up a mock private key in environment."""
    key = "0" * 64
    monkeypatch.setenv("PRIVATE_KEY", key)
    return key


@pytest.fixture
def mock_db_password(monkeypatch: pytest.MonkeyPatch) -> str:
    """Set up a mock database password in environment."""
    password = "test_password"  # pragma: allowlist secret
    monkeypatch.setenv("DB_PASSWORD", password)
    return password


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
    mock_asyncpg_pool: MagicMock,
    mock_connection: MagicMock,
    mock_db_password: str,
) -> Pool:
    """Create a Pool with mocked internals."""
    from bigbrotr.core.pool import DatabaseConfig, PoolConfig

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
            "max_size": 500,
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


def make_mock_event(
    event_id: str = "a" * 64,
    pubkey: str = "b" * 64,
    created_at: int = 1700000000,
    kind: int = 1,
    tags: list[list[str]] | None = None,
    content: str = "Test content",
    sig: str = "e" * 128,
) -> MagicMock:
    """Create a mock nostr_sdk.Event for testing."""
    if tags is None:
        tags = [["e", "c" * 64], ["p", "d" * 64]]

    mock_event = MagicMock(spec=NostrEvent)
    mock_event.id.return_value.to_hex.return_value = event_id
    mock_event.author.return_value.to_hex.return_value = pubkey
    mock_event.created_at.return_value.as_secs.return_value = created_at
    mock_event.kind.return_value.as_u16.return_value = kind
    mock_event.content.return_value = content
    # signature() returns hex string directly (not an object with to_hex())
    mock_event.signature.return_value = sig
    mock_event.verify.return_value = True

    # Mock tags
    mock_tags = []
    for tag in tags:
        mock_tag = MagicMock()
        mock_tag.as_vec.return_value = tag
        mock_tags.append(mock_tag)
    mock_event.tags.return_value.to_vec.return_value = mock_tags

    return mock_event


@pytest.fixture
def sample_event() -> EventRelay:
    """Sample Nostr EventRelay for testing."""
    mock_nostr_event = make_mock_event()
    event = Event(mock_nostr_event)
    relay = Relay("wss://relay.example.com", discovered_at=1700000000)
    return EventRelay(event=event, relay=relay, seen_at=1700000001)


@pytest.fixture
def sample_relay() -> Relay:
    """Sample clearnet Relay for testing."""
    return Relay("wss://relay.example.com", discovered_at=1700000000)


@pytest.fixture
def sample_tor_relay() -> Relay:
    """Sample Tor relay for testing."""
    return Relay("wss://example.onion", discovered_at=1700000000)


@pytest.fixture
def sample_i2p_relay() -> Relay:
    """Sample I2P relay for testing."""
    return Relay("wss://example.i2p", discovered_at=1700000000)


@pytest.fixture
def sample_loki_relay() -> Relay:
    """Sample Lokinet relay for testing."""
    return Relay("wss://example.loki", discovered_at=1700000000)


@pytest.fixture
def sample_metadata() -> RelayMetadata:
    """Sample RelayMetadata for testing."""
    relay = Relay("wss://relay.example.com", discovered_at=1700000000)
    metadata = Metadata(
        type=MetadataType.NIP11_INFO,
        data={"name": "Test Relay", "supported_nips": [1, 2, 9, 11]},
    )
    return RelayMetadata(
        relay=relay,
        metadata=metadata,
        generated_at=1700000001,
    )


@pytest.fixture
def sample_events_batch() -> list[EventRelay]:
    """Generate a batch of sample EventRelay objects."""
    relay = Relay("wss://relay.example.com", discovered_at=1700000000)
    return [
        EventRelay(
            event=Event(
                make_mock_event(
                    event_id=f"{i:064x}",
                    created_at=1700000000 + i,
                    tags=[["e", "c" * 64]],
                )
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
    record.keys = data.keys
    record.values = data.values
    record.items = data.items
    return record


# ============================================================================
# Pytest Configuration
# ============================================================================


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "integration: marks tests as integration tests requiring database",
    )
    config.addinivalue_line(
        "markers",
        "unit: marks tests as unit tests (no external dependencies)",
    )
    config.addinivalue_line("markers", "slow: marks tests as slow running")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Auto-mark tests based on location."""
    for item in items:
        if "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
        elif "unit" in str(item.fspath):
            item.add_marker(pytest.mark.unit)
