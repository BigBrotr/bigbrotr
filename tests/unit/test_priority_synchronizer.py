"""
Unit tests for PrioritySynchronizer service.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.brotr import Brotr, BrotrConfig
from core.pool import Pool
from services.priority_synchronizer import (
    PrioritySynchronizer,
    PrioritySynchronizerConfig,
    PriorityRelaySourceConfig,
)
from services.synchronizer import (
    TorProxyConfig,
    FilterConfig,
    ConcurrencyConfig,
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
    brotr.insert_events = AsyncMock(return_value=True)

    # Mock config with batch settings
    mock_batch_config = MagicMock()
    mock_batch_config.max_batch_size = 100
    mock_config = MagicMock(spec=BrotrConfig)
    mock_config.batch = mock_batch_config
    brotr.config = mock_config

    return brotr


@pytest.fixture
def temp_priority_file() -> str:
    """Create a temporary priority relays file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("# Priority relays\n")
        f.write("wss://relay1.example.com\n")
        f.write("wss://relay2.example.com\n")
        f.write("\n")  # Empty line
        f.write("# Comment line\n")
        f.write("wss://relay3.example.com\n")
        return f.name


class TestPrioritySynchronizerConfig:
    """Tests for PrioritySynchronizerConfig."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = PrioritySynchronizerConfig()

        # Check priority source defaults
        assert config.priority_source.filepath == "data/priority_relays.txt"

        # Check inherited defaults from SynchronizerConfig
        assert config.tor_proxy.enabled is True
        assert config.filter.limit == 500
        assert config.concurrency.max_concurrent_relays == 10
        assert config.sync_interval == 900.0

    def test_custom_priority_source(self) -> None:
        """Test custom priority source settings."""
        config = PrioritySynchronizerConfig(
            priority_source=PriorityRelaySourceConfig(
                filepath="custom/path/relays.txt"
            )
        )

        assert config.priority_source.filepath == "custom/path/relays.txt"

    def test_inherits_synchronizer_config(self) -> None:
        """Test that config inherits from SynchronizerConfig."""
        config = PrioritySynchronizerConfig(
            tor_proxy=TorProxyConfig(enabled=False),
            filter=FilterConfig(kinds=[1, 3]),
            concurrency=ConcurrencyConfig(max_concurrent_relays=3),
            sync_interval=1800.0,
        )

        assert config.tor_proxy.enabled is False
        assert config.filter.kinds == [1, 3]
        assert config.concurrency.max_concurrent_relays == 3
        assert config.sync_interval == 1800.0


class TestPriorityRelaySourceConfig:
    """Tests for PriorityRelaySourceConfig."""

    def test_default_values(self) -> None:
        """Test default priority relay source config."""
        config = PriorityRelaySourceConfig()

        assert config.filepath == "data/priority_relays.txt"

    def test_custom_filepath(self) -> None:
        """Test custom filepath."""
        config = PriorityRelaySourceConfig(filepath="/etc/relays/priority.txt")

        assert config.filepath == "/etc/relays/priority.txt"


class TestPrioritySynchronizer:
    """Tests for PrioritySynchronizer service."""

    def test_init_with_defaults(self, mock_brotr: MagicMock) -> None:
        """Test initialization with defaults."""
        sync = PrioritySynchronizer(brotr=mock_brotr)

        assert sync._brotr is mock_brotr
        assert sync._brotr.pool is mock_brotr.pool
        assert sync.SERVICE_NAME == "priority_synchronizer"
        assert sync.config.priority_source.filepath == "data/priority_relays.txt"

    def test_init_with_custom_config(self, mock_brotr: MagicMock) -> None:
        """Test initialization with custom config."""
        config = PrioritySynchronizerConfig(
            priority_source=PriorityRelaySourceConfig(filepath="custom.txt"),
            tor_proxy=TorProxyConfig(enabled=False),
        )
        sync = PrioritySynchronizer(brotr=mock_brotr, config=config)

        assert sync.config.priority_source.filepath == "custom.txt"
        assert sync.config.tor_proxy.enabled is False

    def test_inherits_from_synchronizer(self, mock_brotr: MagicMock) -> None:
        """Test that PrioritySynchronizer inherits from Synchronizer."""
        from services.synchronizer import Synchronizer

        sync = PrioritySynchronizer(brotr=mock_brotr)
        assert isinstance(sync, Synchronizer)

    @pytest.mark.asyncio
    async def test_health_check_connected(self, mock_brotr: MagicMock) -> None:
        """Test health check when connected."""
        mock_brotr.pool.fetchval = AsyncMock(return_value=1)

        sync = PrioritySynchronizer(brotr=mock_brotr)
        result = await sync.health_check()

        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_disconnected(self, mock_brotr: MagicMock) -> None:
        """Test health check when disconnected."""
        mock_brotr.pool.fetchval = AsyncMock(side_effect=Exception("Connection error"))

        sync = PrioritySynchronizer(brotr=mock_brotr)
        result = await sync.health_check()

        assert result is False

    @pytest.mark.asyncio
    async def test_fetch_relays_file_not_found(self, mock_brotr: MagicMock) -> None:
        """Test fetching relays when file doesn't exist."""
        config = PrioritySynchronizerConfig(
            priority_source=PriorityRelaySourceConfig(
                filepath="nonexistent/file.txt"
            )
        )
        sync = PrioritySynchronizer(brotr=mock_brotr, config=config)
        relays = await sync._fetch_relays()

        assert relays == []

    @pytest.mark.asyncio
    async def test_fetch_relays_from_file(
        self, mock_brotr: MagicMock, temp_priority_file: str
    ) -> None:
        """Test fetching relays from priority file."""
        config = PrioritySynchronizerConfig(
            priority_source=PriorityRelaySourceConfig(filepath=temp_priority_file)
        )
        sync = PrioritySynchronizer(brotr=mock_brotr, config=config)
        relays = await sync._fetch_relays()

        # Should have 3 relays (comments and empty lines ignored)
        assert len(relays) == 3
        urls = [r.url for r in relays]
        # Check that all expected relay domains are present
        assert any("relay1.example.com" in url for url in urls)
        assert any("relay2.example.com" in url for url in urls)
        assert any("relay3.example.com" in url for url in urls)

        # Cleanup
        Path(temp_priority_file).unlink()

    @pytest.mark.asyncio
    async def test_fetch_relays_skips_invalid_urls(
        self, mock_brotr: MagicMock
    ) -> None:
        """Test that invalid URLs are skipped."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("wss://valid.relay.com\n")
            f.write("invalid-url\n")
            f.write("http://not-websocket.com\n")
            temp_file = f.name

        config = PrioritySynchronizerConfig(
            priority_source=PriorityRelaySourceConfig(filepath=temp_file)
        )
        sync = PrioritySynchronizer(brotr=mock_brotr, config=config)
        relays = await sync._fetch_relays()

        # Only valid relay should be returned
        assert len(relays) == 1
        assert "valid.relay.com" in relays[0].url

        # Cleanup
        Path(temp_file).unlink()

    @pytest.mark.asyncio
    async def test_fetch_relays_removes_duplicates(
        self, mock_brotr: MagicMock
    ) -> None:
        """Test that duplicate URLs are removed."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("wss://relay1.example.com\n")
            f.write("wss://relay1.example.com/\n")  # Same relay with trailing slash
            f.write("wss://relay2.example.com\n")
            f.write("wss://relay1.example.com\n")  # Duplicate
            temp_file = f.name

        config = PrioritySynchronizerConfig(
            priority_source=PriorityRelaySourceConfig(filepath=temp_file)
        )
        sync = PrioritySynchronizer(brotr=mock_brotr, config=config)
        relays = await sync._fetch_relays()

        # Should have only 2 unique relays
        assert len(relays) == 2
        urls = [r.url for r in relays]
        assert any("relay1.example.com" in url for url in urls)
        assert any("relay2.example.com" in url for url in urls)

        # Cleanup
        Path(temp_file).unlink()

    @pytest.mark.asyncio
    async def test_fetch_relays_empty_file(self, mock_brotr: MagicMock) -> None:
        """Test fetching relays from empty file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("# Only comments\n")
            f.write("\n")
            temp_file = f.name

        config = PrioritySynchronizerConfig(
            priority_source=PriorityRelaySourceConfig(filepath=temp_file)
        )
        sync = PrioritySynchronizer(brotr=mock_brotr, config=config)
        relays = await sync._fetch_relays()

        assert relays == []

        # Cleanup
        Path(temp_file).unlink()

    @pytest.mark.asyncio
    async def test_run_no_relays(self, mock_brotr: MagicMock) -> None:
        """Test run cycle with no relays."""
        config = PrioritySynchronizerConfig(
            priority_source=PriorityRelaySourceConfig(filepath="nonexistent.txt")
        )
        sync = PrioritySynchronizer(brotr=mock_brotr, config=config)
        await sync.run()

        # Should complete without error
        assert sync._synced_relays == 0
        assert sync._synced_events == 0


class TestPrioritySynchronizerFactoryMethods:
    """Tests for PrioritySynchronizer factory methods."""

    def test_from_dict(self, mock_brotr: MagicMock) -> None:
        """Test creation from dictionary."""
        data = {
            "priority_source": {"filepath": "custom/relays.txt"},
            "tor_proxy": {"enabled": False},
        }

        sync = PrioritySynchronizer.from_dict(data, brotr=mock_brotr)

        assert sync.config.priority_source.filepath == "custom/relays.txt"
        assert sync.config.tor_proxy.enabled is False

    def test_from_dict_with_inherited_config(self, mock_brotr: MagicMock) -> None:
        """Test creation from dictionary with inherited config values."""
        data = {
            "priority_source": {"filepath": "priority.txt"},
            "filter": {"kinds": [1, 3]},
            "concurrency": {"max_concurrent_relays": 3},
            "sync_interval": 600.0,
        }

        sync = PrioritySynchronizer.from_dict(data, brotr=mock_brotr)

        assert sync.config.priority_source.filepath == "priority.txt"
        assert sync.config.filter.kinds == [1, 3]
        assert sync.config.concurrency.max_concurrent_relays == 3
        assert sync.config.sync_interval == 600.0

    def test_from_dict_partial(self, mock_brotr: MagicMock) -> None:
        """Test creation from partial dictionary."""
        data = {
            "sync_interval": 1800.0,
        }

        sync = PrioritySynchronizer.from_dict(data, brotr=mock_brotr)

        assert sync.config.sync_interval == 1800.0
        # Defaults should be preserved
        assert sync.config.priority_source.filepath == "data/priority_relays.txt"
        assert sync.config.tor_proxy.enabled is True


class TestPrioritySynchronizerIntegration:
    """Integration-style tests for PrioritySynchronizer."""

    @pytest.mark.asyncio
    async def test_uses_synchronizer_methods(
        self, mock_brotr: MagicMock, temp_priority_file: str
    ) -> None:
        """Test that PrioritySynchronizer uses Synchronizer methods."""
        config = PrioritySynchronizerConfig(
            priority_source=PriorityRelaySourceConfig(filepath=temp_priority_file)
        )
        sync = PrioritySynchronizer(brotr=mock_brotr, config=config)

        # Test that inherited methods exist and work
        assert hasattr(sync, "_sync_relay")
        assert hasattr(sync, "_get_start_time")
        assert hasattr(sync, "_create_filter")
        assert hasattr(sync, "_fetch_batch")
        assert hasattr(sync, "_insert_batch")

        # Cleanup
        Path(temp_priority_file).unlink()

    @pytest.mark.asyncio
    async def test_service_name_is_different(self, mock_brotr: MagicMock) -> None:
        """Test that service name is different from parent."""
        from services.synchronizer import Synchronizer

        sync = Synchronizer(brotr=mock_brotr)
        priority_sync = PrioritySynchronizer(brotr=mock_brotr)

        assert sync.SERVICE_NAME == "synchronizer"
        assert priority_sync.SERVICE_NAME == "priority_synchronizer"
        assert sync.SERVICE_NAME != priority_sync.SERVICE_NAME
