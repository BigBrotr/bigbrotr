"""
Pytest configuration and shared fixtures for BigBrotr tests.
"""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.pool import ConnectionPool
from core.brotr import Brotr
from core.service import Service, ServiceConfig
from core.logger import configure_logging


# ============================================================================
# Logging Configuration
# ============================================================================


@pytest.fixture(scope="session", autouse=True)
def setup_logging() -> None:
    """Configure logging for tests."""
    configure_logging(level="DEBUG", console_output=True, structured=False)


# ============================================================================
# Mock Fixtures
# ============================================================================


@pytest.fixture
def mock_asyncpg_pool() -> MagicMock:
    """Create a mock asyncpg pool."""
    pool = MagicMock()
    pool.close = AsyncMock()

    # Mock connection
    mock_conn = MagicMock()
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_conn.fetchrow = AsyncMock(return_value=None)
    mock_conn.fetchval = AsyncMock(return_value=1)
    mock_conn.execute = AsyncMock(return_value="OK")
    mock_conn.executemany = AsyncMock()

    # Mock transaction context manager
    mock_transaction = MagicMock()
    mock_transaction.__aenter__ = AsyncMock(return_value=None)
    mock_transaction.__aexit__ = AsyncMock(return_value=None)
    mock_conn.transaction = MagicMock(return_value=mock_transaction)

    # Mock acquire context manager
    mock_acquire = MagicMock()
    mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_acquire.__aexit__ = AsyncMock(return_value=None)
    pool.acquire = MagicMock(return_value=mock_acquire)

    return pool


@pytest.fixture
def mock_connection_pool(mock_asyncpg_pool: MagicMock) -> ConnectionPool:
    """Create a ConnectionPool with mocked internals."""
    # Set environment variable for password
    os.environ.setdefault("DB_PASSWORD", "test_password")

    pool = ConnectionPool(
        host="localhost",
        port=5432,
        database="test_db",
        user="test_user",
    )
    # Inject mock pool
    pool._pool = mock_asyncpg_pool
    pool._is_connected = True
    return pool


@pytest.fixture
def mock_brotr(mock_connection_pool: ConnectionPool) -> Brotr:
    """Create a Brotr instance with mocked pool."""
    return Brotr(pool=mock_connection_pool)


# ============================================================================
# Configuration Fixtures
# ============================================================================


@pytest.fixture
def pool_config() -> dict:
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
    }


@pytest.fixture
def brotr_config() -> dict:
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


@pytest.fixture
def service_config() -> ServiceConfig:
    """Sample service configuration."""
    return ServiceConfig(
        logging={"enable_logging": True, "log_level": "DEBUG"},
        health_check={
            "enable_health_checks": True,
            "health_check_interval": 1.0,
            "health_check_timeout": 1.0,
        },
        warmup={"enable_warmup": False},
        circuit_breaker={"enable_circuit_breaker": False},
        metrics={"enable_stats": True, "enable_prometheus_metrics": False},
    )


# ============================================================================
# Sample Data Fixtures
# ============================================================================


@pytest.fixture
def sample_event() -> dict:
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
def sample_relay() -> dict:
    """Sample relay for testing."""
    return {
        "url": "wss://relay.example.com",
        "network": "clearnet",
        "inserted_at": 1700000000,
    }


@pytest.fixture
def sample_metadata() -> dict:
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
            "supported_nips": [1, 2, 9, 11],
        },
    }


# ============================================================================
# Integration Test Markers
# ============================================================================


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests requiring database"
    )
    config.addinivalue_line(
        "markers", "unit: marks tests as unit tests (no external dependencies)"
    )
    config.addinivalue_line(
        "markers", "slow: marks tests as slow running"
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Auto-mark tests based on location."""
    for item in items:
        # Auto-mark tests in integration directory
        if "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
        # Auto-mark tests in unit directory
        elif "unit" in str(item.fspath):
            item.add_marker(pytest.mark.unit)
