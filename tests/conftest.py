"""
Pytest configuration and shared fixtures for BigBrotr tests.

Provides:
- Mock fixtures for Pool, Brotr, and asyncpg
- Sample data fixtures for events, relays, and metadata
- Custom pytest markers for test categorization
"""

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.brotr import Brotr
from core.pool import Pool


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
    mock_transaction.__aenter__ = AsyncMock(return_value=None)
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
def mock_pool(mock_asyncpg_pool: MagicMock, mock_connection: MagicMock, monkeypatch: pytest.MonkeyPatch) -> Pool:
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


@pytest.fixture
def sample_event() -> dict[str, Any]:
    """Sample Nostr event for testing."""
    return {
        "event_id": "a" * 64,
        "pubkey": "b" * 64,
        "created_at": 1700000000,
        "kind": 1,
        "tags": [["e", "c" * 64], ["p", "d" * 64]],
        "content": "Test content",
        "sig": "e" * 128,
        "relay_url": "wss://relay.example.com",
        "relay_network": "clearnet",
        "relay_inserted_at": 1700000000,
        "seen_at": 1700000001,
    }


@pytest.fixture
def sample_relay() -> dict[str, Any]:
    """Sample relay for testing."""
    return {
        "url": "wss://relay.example.com",
        "network": "clearnet",
        "inserted_at": 1700000000,
    }


@pytest.fixture
def sample_metadata() -> dict[str, Any]:
    """Sample relay metadata for testing."""
    return {
        "relay_url": "wss://relay.example.com",
        "relay_network": "clearnet",
        "relay_inserted_at": 1700000000,
        "generated_at": 1700000001,
        "nip66": {
            "openable": True,
            "readable": True,
            "writable": False,
            "rtt_open": 120,
            "rtt_read": 50,
            "rtt_write": None,
        },
        "nip11": {
            "name": "Test Relay",
            "description": "A test relay for unit tests",
            "banner": None,
            "icon": None,
            "pubkey": None,
            "contact": None,
            "supported_nips": [1, 2, 9, 11],
            "software": None,
            "version": None,
            "privacy_policy": None,
            "terms_of_service": None,
            "limitation": None,
            "extra_fields": None,
        },
    }


@pytest.fixture
def sample_events_batch(sample_event: dict[str, Any]) -> list[dict[str, Any]]:
    """Generate a batch of sample events."""
    events = []
    for i in range(10):
        event = sample_event.copy()
        event["event_id"] = f"{i:064x}"
        event["created_at"] = 1700000000 + i
        events.append(event)
    return events


@pytest.fixture
def sample_relays_batch() -> list[dict[str, Any]]:
    """Generate a batch of sample relays."""
    return [
        {"url": f"wss://relay{i}.example.com", "network": "clearnet", "inserted_at": 1700000000}
        for i in range(10)
    ]


# ============================================================================
# Helper Functions
# ============================================================================


def create_mock_record(data: dict[str, Any]) -> MagicMock:
    """Create a mock asyncpg Record from a dictionary."""
    record = MagicMock()
    record.__getitem__ = lambda self, key: data[key]
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
    config.addinivalue_line(
        "markers", "unit: marks tests as unit tests (no external dependencies)"
    )
    config.addinivalue_line("markers", "slow: marks tests as slow running")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Auto-mark tests based on location."""
    for item in items:
        if "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
        elif "unit" in str(item.fspath):
            item.add_marker(pytest.mark.unit)