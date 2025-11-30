"""
Unit tests for Finder service.
"""

import os
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.brotr import Brotr
from core.pool import Pool
from services.finder import (
    ApiConfig,
    ApiSourceConfig,
    EventsConfig,
    Finder,
    FinderConfig,
)


@pytest.fixture
def mock_pool() -> MagicMock:
    """Create a mock pool."""
    os.environ.setdefault("DB_PASSWORD", "test_password")
    pool = MagicMock(spec=Pool)
    pool.fetch = AsyncMock(return_value=[])
    pool.fetchrow = AsyncMock(return_value=None)
    pool.fetchval = AsyncMock(return_value=1)
    pool.execute = AsyncMock(return_value="OK")
    pool.is_connected = True

    # Mock transaction
    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock(return_value="OK")

    mock_transaction = MagicMock()
    mock_transaction.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_transaction.__aexit__ = AsyncMock(return_value=None)
    pool.transaction = MagicMock(return_value=mock_transaction)

    return pool


@pytest.fixture
def mock_brotr(mock_pool: MagicMock) -> MagicMock:
    """Create a mock Brotr with pool."""
    brotr = MagicMock(spec=Brotr)
    brotr.pool = mock_pool
    brotr.insert_relays = AsyncMock(return_value=True)
    return brotr


class TestFinderConfig:
    """Tests for FinderConfig."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = FinderConfig()

        assert config.events.enabled is True
        assert config.api.enabled is True
        assert len(config.api.sources) == 2

    def test_custom_events(self) -> None:
        """Test custom events settings."""
        config = FinderConfig(events=EventsConfig(enabled=False))

        assert config.events.enabled is False

    def test_custom_api(self) -> None:
        """Test custom API settings."""
        config = FinderConfig(
            api=ApiConfig(
                enabled=False,
                sources=[ApiSourceConfig(url="https://custom.api/relays")],
            )
        )

        assert config.api.enabled is False
        assert len(config.api.sources) == 1
        assert config.api.sources[0].url == "https://custom.api/relays"


class TestFinder:
    """Tests for Finder service."""

    def test_init_with_defaults(self, mock_brotr: MagicMock) -> None:
        """Test initialization with defaults."""
        finder = Finder(brotr=mock_brotr)

        assert finder._brotr is mock_brotr
        assert finder._brotr.pool is mock_brotr.pool
        assert finder.SERVICE_NAME == "finder"
        assert finder.config.api.enabled is True

    def test_init_with_custom_config(self, mock_brotr: MagicMock) -> None:
        """Test initialization with custom config."""
        config = FinderConfig(
            api=ApiConfig(enabled=False),
        )
        finder = Finder(brotr=mock_brotr, config=config)

        assert finder.config.api.enabled is False

    @pytest.mark.asyncio
    async def test_health_check_connected(self, mock_brotr: MagicMock) -> None:
        """Test health check when connected."""
        mock_brotr.pool.fetchval = AsyncMock(return_value=1)

        finder = Finder(brotr=mock_brotr)
        result = await finder.health_check()

        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_disconnected(self, mock_brotr: MagicMock) -> None:
        """Test health check when disconnected."""
        mock_brotr.pool.fetchval = AsyncMock(side_effect=Exception("Connection error"))

        finder = Finder(brotr=mock_brotr)
        result = await finder.health_check()

        assert result is False

    @pytest.mark.asyncio
    async def test_run_loop_stops_on_shutdown(self, mock_brotr: MagicMock) -> None:
        """Test run loop stops when shutdown is requested."""
        config = FinderConfig(
            events=EventsConfig(enabled=False),
            api=ApiConfig(enabled=False),
        )
        finder = Finder(brotr=mock_brotr, config=config)
        finder._is_running = True

        # Request shutdown immediately
        finder.request_shutdown()

        # Should complete without hanging
        await finder.run()

    @pytest.mark.asyncio
    async def test_find_from_api_all_sources_disabled(self, mock_brotr: MagicMock) -> None:
        """Test API fetch when all sources are disabled."""
        config = FinderConfig(
            api=ApiConfig(
                enabled=True,
                sources=[
                    ApiSourceConfig(url="https://api.example.com", enabled=False),
                ],
            )
        )
        finder = Finder(brotr=mock_brotr, config=config)

        # No sources should be checked when all disabled
        await finder._find_from_api()
        # Should complete without error, no relays inserted
        assert finder._found_relays == 0


class TestFinderFactoryMethods:
    """Tests for Finder factory methods."""

    def test_from_dict(self, mock_brotr: MagicMock) -> None:
        """Test creation from dictionary."""
        data = {
            "api": {"enabled": False},
        }

        finder = Finder.from_dict(data, brotr=mock_brotr)

        assert finder.config.api.enabled is False


class TestApiSourceConfig:
    """Tests for ApiSourceConfig."""

    def test_default_values(self) -> None:
        """Test default API source config."""
        source = ApiSourceConfig(url="https://api.example.com")

        assert source.url == "https://api.example.com"
        assert source.enabled is True
        assert source.timeout == 30.0

    def test_custom_values(self) -> None:
        """Test custom API source config."""
        source = ApiSourceConfig(
            url="https://api.custom.com",
            enabled=False,
            timeout=60.0,
        )

        assert source.url == "https://api.custom.com"
        assert source.enabled is False
        assert source.timeout == 60.0
