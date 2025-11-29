"""
Unit tests for Finder service.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.base_service import Outcome
from core.brotr import Brotr
from core.pool import Pool
from services.finder import (
    Finder,
    FinderConfig,
    FinderState,
    EventScanConfig,
    ApiConfig,
    ApiSourceConfig,
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
    """Create a mock Brotr."""
    brotr = MagicMock(spec=Brotr)
    brotr.pool = mock_pool
    brotr.insert_relays = AsyncMock(return_value=True)
    return brotr


class TestFinderConfig:
    """Tests for FinderConfig."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = FinderConfig()

        assert config.event_scan.enabled is True
        assert config.event_scan.batch_size == 1000
        assert config.api.enabled is True
        assert len(config.api.sources) == 2
        assert config.discovery_interval == 3600.0

    def test_custom_event_scan(self) -> None:
        """Test custom event scan settings."""
        config = FinderConfig(
            event_scan=EventScanConfig(enabled=False, batch_size=500)
        )

        assert config.event_scan.enabled is False
        assert config.event_scan.batch_size == 500

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


class TestFinderState:
    """Tests for FinderState."""

    def test_default_state(self) -> None:
        """Test default state values."""
        state = FinderState()

        assert state.last_seen_at == 0
        assert state.total_events_processed == 0
        assert state.total_relays_found == 0
        assert state.last_run_at == 0

    def test_to_dict(self) -> None:
        """Test state serialization."""
        state = FinderState(
            last_seen_at=1700000000,
            total_events_processed=1000,
            total_relays_found=50,
            last_run_at=1700000100,
        )

        data = state.to_dict()

        assert data["last_seen_at"] == 1700000000
        assert data["total_events_processed"] == 1000
        assert data["total_relays_found"] == 50
        assert data["last_run_at"] == 1700000100

    def test_from_dict(self) -> None:
        """Test state deserialization."""
        data = {
            "last_seen_at": 1700000000,
            "total_events_processed": 500,
            "total_relays_found": 25,
            "last_run_at": 1700000050,
        }

        state = FinderState.from_dict(data)

        assert state.last_seen_at == 1700000000
        assert state.total_events_processed == 500
        assert state.total_relays_found == 25
        assert state.last_run_at == 1700000050


class TestFinder:
    """Tests for Finder service."""

    def test_init_with_defaults(self, mock_pool: MagicMock) -> None:
        """Test initialization with defaults."""
        finder = Finder(pool=mock_pool)

        assert finder._pool is mock_pool
        assert finder.SERVICE_NAME == "finder"
        assert finder.config.event_scan.enabled is True

    def test_init_with_custom_config(
        self, mock_pool: MagicMock, mock_brotr: MagicMock
    ) -> None:
        """Test initialization with custom config."""
        config = FinderConfig(
            event_scan=EventScanConfig(enabled=False),
            api=ApiConfig(enabled=False),
        )
        finder = Finder(pool=mock_pool, brotr=mock_brotr, config=config)

        assert finder.config.event_scan.enabled is False
        assert finder.config.api.enabled is False

    @pytest.mark.asyncio
    async def test_health_check_connected(self, mock_pool: MagicMock) -> None:
        """Test health check when connected."""
        mock_pool.fetchval = AsyncMock(return_value=1)

        finder = Finder(pool=mock_pool)
        result = await finder.health_check()

        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_disconnected(self, mock_pool: MagicMock) -> None:
        """Test health check when disconnected."""
        mock_pool.fetchval = AsyncMock(side_effect=Exception("Connection error"))

        finder = Finder(pool=mock_pool)
        result = await finder.health_check()

        assert result is False

    @pytest.mark.asyncio
    async def test_run_without_initializer(
        self, mock_pool: MagicMock, mock_brotr: MagicMock
    ) -> None:
        """Test run fails if initializer not completed."""
        # Mock no initializer state found
        mock_pool.fetchrow = AsyncMock(return_value=None)

        config = FinderConfig(
            event_scan=EventScanConfig(enabled=False),
            api=ApiConfig(enabled=False),
        )
        finder = Finder(pool=mock_pool, brotr=mock_brotr, config=config)
        result = await finder.run()

        assert result.success is False
        assert "Initializer" in result.message

    @pytest.mark.asyncio
    async def test_run_with_api_disabled(
        self, mock_pool: MagicMock, mock_brotr: MagicMock
    ) -> None:
        """Test run with only event scanning disabled and API disabled."""
        # Mock initializer state
        mock_pool.fetchrow = AsyncMock(
            return_value={"state": {"initialized": True}}
        )
        mock_pool.fetch = AsyncMock(return_value=[])

        config = FinderConfig(
            event_scan=EventScanConfig(enabled=False),
            api=ApiConfig(enabled=False),
        )
        finder = Finder(pool=mock_pool, brotr=mock_brotr, config=config)
        result = await finder.run()

        assert result.success is True
        assert result.metrics["events_scanned"] == 0
        assert result.metrics["api_sources_checked"] == 0

    @pytest.mark.asyncio
    async def test_fetch_from_apis_all_sources_disabled(
        self, mock_pool: MagicMock, mock_brotr: MagicMock
    ) -> None:
        """Test fetch when all sources are disabled."""
        config = FinderConfig(
            api=ApiConfig(
                enabled=True,
                sources=[
                    ApiSourceConfig(url="https://api.example.com", enabled=False),
                ],
            )
        )
        finder = Finder(pool=mock_pool, brotr=mock_brotr, config=config)

        # No sources should be checked when all disabled
        result = await finder._fetch_from_apis()
        assert result["sources_checked"] == 0


class TestFinderFactoryMethods:
    """Tests for Finder factory methods."""

    def test_from_dict(self, mock_pool: MagicMock, mock_brotr: MagicMock) -> None:
        """Test creation from dictionary."""
        data = {
            "event_scan": {"enabled": False},
            "api": {"enabled": False},
            "discovery_interval": 7200.0,
        }

        finder = Finder.from_dict(data, pool=mock_pool, brotr=mock_brotr)

        assert finder.config.event_scan.enabled is False
        assert finder.config.api.enabled is False
        assert finder.config.discovery_interval == 7200.0


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