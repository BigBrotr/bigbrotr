"""
Unit tests for Monitor service.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.brotr import Brotr
from core.pool import Pool
from services.monitor import (
    Monitor,
    MonitorConfig,
    TorConfig,
    KeysConfig,
    TimeoutsConfig,
    ConcurrencyConfig,
    SelectionConfig,
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
    brotr.insert_relay_metadata = AsyncMock(return_value=True)
    return brotr


class TestMonitorConfig:
    """Tests for MonitorConfig."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = MonitorConfig()

        assert config.tor.enabled is True
        assert config.tor.host == "127.0.0.1"
        assert config.tor.port == 9050
        assert config.keys.private_key is None
        assert config.keys.public_key is None
        assert config.timeouts.clearnet == 30.0
        assert config.timeouts.tor == 60.0
        assert config.concurrency.max_parallel == 50
        assert config.concurrency.batch_size == 50
        assert config.selection.min_age_since_check == 3600
        assert config.interval == 3600.0

    def test_custom_tor(self) -> None:
        """Test custom Tor proxy settings."""
        config = MonitorConfig(
            tor=TorConfig(enabled=False, host="tor", port=9150)
        )

        assert config.tor.enabled is False
        assert config.tor.host == "tor"
        assert config.tor.port == 9150

    def test_custom_keys(self) -> None:
        """Test custom keys settings with public_key from config."""
        from nostr_tools import generate_keypair
        _, pub = generate_keypair()

        config = MonitorConfig(
            keys=KeysConfig(public_key=pub)
        )

        assert config.keys.public_key == pub

    def test_private_key_from_env(self) -> None:
        """Test private key is loaded from environment variable."""
        from nostr_tools import generate_keypair
        priv, pub = generate_keypair()

        os.environ["MONITOR_PRIVATE_KEY"] = priv
        config = MonitorConfig(keys=KeysConfig(public_key=pub))

        assert config.keys.private_key is not None
        assert config.keys.private_key.get_secret_value() == priv

        # Cleanup
        del os.environ["MONITOR_PRIVATE_KEY"]

    def test_keypair_validation_success(self) -> None:
        """Test valid keypair passes validation."""
        from nostr_tools import generate_keypair
        priv, pub = generate_keypair()

        os.environ["MONITOR_PRIVATE_KEY"] = priv
        config = MonitorConfig(keys=KeysConfig(public_key=pub))

        assert config.keys.public_key == pub
        assert config.keys.private_key is not None
        assert config.keys.private_key.get_secret_value() == priv

        # Cleanup
        del os.environ["MONITOR_PRIVATE_KEY"]

    def test_keypair_validation_failure(self) -> None:
        """Test mismatched keypair raises validation error."""
        from nostr_tools import generate_keypair
        priv1, _ = generate_keypair()
        _, pub2 = generate_keypair()

        os.environ["MONITOR_PRIVATE_KEY"] = priv1

        with pytest.raises(ValueError, match="do not match"):
            KeysConfig(public_key=pub2)

        # Cleanup
        del os.environ["MONITOR_PRIVATE_KEY"]

    def test_keypair_validation_skipped_without_both(self) -> None:
        """Test validation is skipped if only one key is provided."""
        from nostr_tools import generate_keypair
        _, pub = generate_keypair()

        # Only public key - should not raise
        config = KeysConfig(public_key=pub)
        assert config.public_key == pub

        # Only private key - should not raise
        priv, _ = generate_keypair()
        os.environ["MONITOR_PRIVATE_KEY"] = priv
        config = KeysConfig()
        assert config.private_key is not None
        assert config.private_key.get_secret_value() == priv

        # Cleanup
        del os.environ["MONITOR_PRIVATE_KEY"]

    def test_custom_concurrency(self) -> None:
        """Test custom concurrency settings."""
        config = MonitorConfig(
            concurrency=ConcurrencyConfig(
                max_parallel=100,
                batch_size=100,
            )
        )

        assert config.concurrency.max_parallel == 100
        assert config.concurrency.batch_size == 100

    def test_custom_timeouts(self) -> None:
        """Test custom timeouts settings."""
        config = MonitorConfig(
            timeouts=TimeoutsConfig(
                clearnet=45.0,
                tor=90.0,
            )
        )

        assert config.timeouts.clearnet == 45.0
        assert config.timeouts.tor == 90.0

    def test_custom_selection(self) -> None:
        """Test custom selection settings."""
        config = MonitorConfig(
            selection=SelectionConfig(
                min_age_since_check=7200,
            )
        )

        assert config.selection.min_age_since_check == 7200


class TestTorConfig:
    """Tests for TorConfig."""

    def test_default_values(self) -> None:
        """Test default Tor proxy config."""
        config = TorConfig()

        assert config.enabled is True
        assert config.host == "127.0.0.1"
        assert config.port == 9050

    def test_port_validation(self) -> None:
        """Test port validation."""
        # Valid port
        config = TorConfig(port=9150)
        assert config.port == 9150

        # Invalid port should raise
        with pytest.raises(ValueError):
            TorConfig(port=0)

        with pytest.raises(ValueError):
            TorConfig(port=70000)


class TestTimeoutsConfig:
    """Tests for TimeoutsConfig."""

    def test_default_values(self) -> None:
        """Test default timeouts config."""
        config = TimeoutsConfig()

        assert config.clearnet == 30.0
        assert config.tor == 60.0

    def test_custom_values(self) -> None:
        """Test custom timeouts values."""
        config = TimeoutsConfig(clearnet=45.0, tor=90.0)

        assert config.clearnet == 45.0
        assert config.tor == 90.0

    def test_validation(self) -> None:
        """Test validation constraints."""
        # Valid values
        config = TimeoutsConfig(clearnet=5.0, tor=10.0)
        assert config.clearnet == 5.0
        assert config.tor == 10.0

        # Invalid clearnet timeout (too low)
        with pytest.raises(ValueError):
            TimeoutsConfig(clearnet=4.0)

        # Invalid clearnet timeout (too high)
        with pytest.raises(ValueError):
            TimeoutsConfig(clearnet=121.0)

        # Invalid tor timeout (too low)
        with pytest.raises(ValueError):
            TimeoutsConfig(tor=9.0)

        # Invalid tor timeout (too high)
        with pytest.raises(ValueError):
            TimeoutsConfig(tor=181.0)


class TestConcurrencyConfig:
    """Tests for ConcurrencyConfig."""

    def test_default_values(self) -> None:
        """Test default concurrency config."""
        config = ConcurrencyConfig()

        assert config.max_parallel == 50
        assert config.batch_size == 50

    def test_custom_max_parallel(self) -> None:
        """Test custom max_parallel values."""
        config = ConcurrencyConfig(max_parallel=100)
        assert config.max_parallel == 100

        config = ConcurrencyConfig(max_parallel=10)
        assert config.max_parallel == 10

    def test_validation(self) -> None:
        """Test validation constraints."""
        # Valid values
        config = ConcurrencyConfig(
            max_parallel=1,
            batch_size=1,
        )
        assert config.max_parallel == 1

        # Invalid max_parallel
        with pytest.raises(ValueError):
            ConcurrencyConfig(max_parallel=0)

        with pytest.raises(ValueError):
            ConcurrencyConfig(max_parallel=501)

        # Invalid batch_size
        with pytest.raises(ValueError):
            ConcurrencyConfig(batch_size=0)

        with pytest.raises(ValueError):
            ConcurrencyConfig(batch_size=501)


class TestSelectionConfig:
    """Tests for SelectionConfig."""

    def test_default_values(self) -> None:
        """Test default selection config."""
        config = SelectionConfig()

        assert config.min_age_since_check == 3600

    def test_custom_values(self) -> None:
        """Test custom selection config."""
        config = SelectionConfig(
            min_age_since_check=0,
        )

        assert config.min_age_since_check == 0


class TestMonitor:
    """Tests for Monitor service."""

    def test_init_with_defaults(self, mock_brotr: MagicMock) -> None:
        """Test initialization with defaults."""
        monitor = Monitor(brotr=mock_brotr)

        assert monitor._brotr is mock_brotr
        assert monitor._brotr.pool is mock_brotr.pool
        assert monitor.SERVICE_NAME == "monitor"
        assert monitor.config.tor.enabled is True

    def test_init_with_custom_config(self, mock_brotr: MagicMock) -> None:
        """Test initialization with custom config."""
        config = MonitorConfig(
            tor=TorConfig(enabled=False),
            selection=SelectionConfig(min_age_since_check=7200),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)

        assert monitor.config.tor.enabled is False
        assert monitor.config.selection.min_age_since_check == 7200

    @pytest.mark.asyncio
    async def test_health_check_connected(self, mock_brotr: MagicMock) -> None:
        """Test health check when connected."""
        mock_brotr.pool.fetchval = AsyncMock(return_value=1)

        monitor = Monitor(brotr=mock_brotr)
        result = await monitor.health_check()

        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_disconnected(self, mock_brotr: MagicMock) -> None:
        """Test health check when disconnected."""
        mock_brotr.pool.fetchval = AsyncMock(side_effect=Exception("Connection error"))

        monitor = Monitor(brotr=mock_brotr)
        result = await monitor.health_check()

        assert result is False

    @pytest.mark.asyncio
    async def test_fetch_relays_to_check_empty(self, mock_brotr: MagicMock) -> None:
        """Test fetching relays when none need checking."""
        mock_brotr.pool.fetch = AsyncMock(return_value=[])

        monitor = Monitor(brotr=mock_brotr)
        relays = await monitor._fetch_relays_to_check()

        assert relays == []

    @pytest.mark.asyncio
    async def test_fetch_relays_to_check_with_relays(
        self, mock_brotr: MagicMock
    ) -> None:
        """Test fetching relays that need checking."""
        mock_brotr.pool.fetch = AsyncMock(
            return_value=[
                {"relay_url": "wss://relay1.example.com"},
                {"relay_url": "wss://relay2.example.com"},
            ]
        )

        monitor = Monitor(brotr=mock_brotr)
        relays = await monitor._fetch_relays_to_check()

        assert len(relays) == 2
        # URL normalization depends on nostr_tools implementation
        assert "relay1.example.com" in relays[0].url
        assert "relay2.example.com" in relays[1].url

    @pytest.mark.asyncio
    async def test_fetch_relays_to_check_invalid_url(
        self, mock_brotr: MagicMock
    ) -> None:
        """Test fetching relays with invalid URL."""
        mock_brotr.pool.fetch = AsyncMock(
            return_value=[
                {"relay_url": "wss://valid.relay.com"},
                {"relay_url": "invalid-url"},
            ]
        )

        monitor = Monitor(brotr=mock_brotr)
        relays = await monitor._fetch_relays_to_check()

        # Only valid relay should be returned
        assert len(relays) == 1
        assert "valid.relay.com" in relays[0].url

    @pytest.mark.asyncio
    async def test_fetch_relays_skips_tor_when_disabled(
        self, mock_brotr: MagicMock
    ) -> None:
        """Test that .onion relays are skipped when Tor proxy is disabled."""
        # Valid v3 onion address (56 characters)
        onion_url = "ws://oxtrdevav64z64yb7x6rjg4ntzqjhedm5b5zjqulugknhzr46ny2qbad.onion"
        mock_brotr.pool.fetch = AsyncMock(
            return_value=[
                {"relay_url": "wss://clearnet.relay.com"},
                {"relay_url": onion_url},
            ]
        )

        config = MonitorConfig(
            tor=TorConfig(enabled=False),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)
        relays = await monitor._fetch_relays_to_check()

        # Only clearnet relay should be returned
        assert len(relays) == 1
        assert "clearnet.relay.com" in relays[0].url

    @pytest.mark.asyncio
    async def test_fetch_relays_includes_tor_when_enabled(
        self, mock_brotr: MagicMock
    ) -> None:
        """Test that .onion relays are included when Tor proxy is enabled."""
        # Valid v3 onion address (56 characters)
        onion_url = "ws://oxtrdevav64z64yb7x6rjg4ntzqjhedm5b5zjqulugknhzr46ny2qbad.onion"
        mock_brotr.pool.fetch = AsyncMock(
            return_value=[
                {"relay_url": "wss://clearnet.relay.com"},
                {"relay_url": onion_url},
            ]
        )

        config = MonitorConfig(
            tor=TorConfig(enabled=True),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)
        relays = await monitor._fetch_relays_to_check()

        # Both relays should be returned
        assert len(relays) == 2

    @pytest.mark.asyncio
    async def test_run_no_relays(self, mock_brotr: MagicMock) -> None:
        """Test run cycle with no relays to check."""
        mock_brotr.pool.fetch = AsyncMock(return_value=[])

        monitor = Monitor(brotr=mock_brotr)
        await monitor.run()

        # Should complete without error
        assert monitor._checked_relays == 0

    @pytest.mark.asyncio
    async def test_insert_metadata_batch_empty(self, mock_brotr: MagicMock) -> None:
        """Test inserting empty metadata batch."""
        monitor = Monitor(brotr=mock_brotr)
        await monitor._insert_metadata_batch([])

        mock_brotr.insert_relay_metadata.assert_not_called()

    @pytest.mark.asyncio
    async def test_insert_metadata_batch_success(self, mock_brotr: MagicMock) -> None:
        """Test successful metadata batch insertion."""
        mock_brotr.insert_relay_metadata = AsyncMock(return_value=True)

        monitor = Monitor(brotr=mock_brotr)
        metadata = [
            {"relay_url": "wss://relay1.example.com/", "generated_at": 123456},
            {"relay_url": "wss://relay2.example.com/", "generated_at": 123456},
        ]
        await monitor._insert_metadata_batch(metadata)

        mock_brotr.insert_relay_metadata.assert_called_once_with(metadata)


class TestMonitorFactoryMethods:
    """Tests for Monitor factory methods."""

    def test_from_dict(self, mock_brotr: MagicMock) -> None:
        """Test creation from dictionary."""
        data = {
            "tor": {"enabled": False},
            "selection": {"min_age_since_check": 7200},
        }

        monitor = Monitor.from_dict(data, brotr=mock_brotr)

        assert monitor.config.tor.enabled is False
        assert monitor.config.selection.min_age_since_check == 7200

    def test_from_dict_partial(self, mock_brotr: MagicMock) -> None:
        """Test creation from partial dictionary."""
        data = {
            "interval": 7200.0,
        }

        monitor = Monitor.from_dict(data, brotr=mock_brotr)

        assert monitor.config.interval == 7200.0
        # Defaults should be preserved
        assert monitor.config.tor.enabled is True
