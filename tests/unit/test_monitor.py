"""
Unit tests for services.monitor module.

Tests:
- Configuration models (TorConfig, KeysConfig, TimeoutsConfig, etc.)
- Monitor service initialization
- Relay selection logic
- Metadata batch insertion
"""

from unittest.mock import AsyncMock

import pytest
from nostr_tools import generate_keypair

from core.brotr import Brotr
from services.monitor import (
    ConcurrencyConfig,
    KeysConfig,
    Monitor,
    MonitorConfig,
    SelectionConfig,
    TimeoutsConfig,
    TorConfig,
)


# ============================================================================
# TorConfig Tests
# ============================================================================


class TestTorConfig:
    """Tests for TorConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default Tor proxy config."""
        config = TorConfig()

        assert config.enabled is True
        assert config.host == "127.0.0.1"
        assert config.port == 9050

    def test_custom_values(self) -> None:
        """Test custom Tor proxy config."""
        config = TorConfig(enabled=False, host="tor-proxy", port=9150)

        assert config.enabled is False
        assert config.host == "tor-proxy"
        assert config.port == 9150

    def test_port_validation(self) -> None:
        """Test port validation."""
        config = TorConfig(port=9150)
        assert config.port == 9150

        with pytest.raises(ValueError):
            TorConfig(port=0)

        with pytest.raises(ValueError):
            TorConfig(port=70000)


# ============================================================================
# KeysConfig Tests
# ============================================================================


class TestKeysConfig:
    """Tests for KeysConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default keys config (no keys)."""
        config = KeysConfig()

        assert config.private_key is None
        assert config.public_key is None

    def test_custom_public_key(self) -> None:
        """Test custom public key."""
        _, pub = generate_keypair()
        config = KeysConfig(public_key=pub)

        assert config.public_key == pub

    def test_keypair_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test private key loaded from environment."""
        priv, pub = generate_keypair()
        monkeypatch.setenv("MONITOR_PRIVATE_KEY", priv)

        config = KeysConfig(public_key=pub)

        assert config.private_key is not None
        assert config.private_key.get_secret_value() == priv

    def test_keypair_validation_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test valid keypair passes validation."""
        priv, pub = generate_keypair()
        monkeypatch.setenv("MONITOR_PRIVATE_KEY", priv)

        config = KeysConfig(public_key=pub)

        assert config.public_key == pub

    def test_keypair_validation_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test mismatched keypair raises validation error."""
        priv1, _ = generate_keypair()
        _, pub2 = generate_keypair()

        monkeypatch.setenv("MONITOR_PRIVATE_KEY", priv1)

        with pytest.raises(ValueError, match="do not match"):
            KeysConfig(public_key=pub2)


# ============================================================================
# TimeoutsConfig Tests
# ============================================================================


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

    def test_validation_constraints(self) -> None:
        """Test validation constraints."""
        with pytest.raises(ValueError):
            TimeoutsConfig(clearnet=4.0)  # Too low

        with pytest.raises(ValueError):
            TimeoutsConfig(clearnet=121.0)  # Too high

        with pytest.raises(ValueError):
            TimeoutsConfig(tor=9.0)  # Too low

        with pytest.raises(ValueError):
            TimeoutsConfig(tor=181.0)  # Too high


# ============================================================================
# ConcurrencyConfig Tests
# ============================================================================


class TestMonitorConcurrencyConfig:
    """Tests for ConcurrencyConfig (Monitor)."""

    def test_default_values(self) -> None:
        """Test default concurrency config."""
        config = ConcurrencyConfig()

        assert config.max_parallel == 50
        assert config.batch_size == 50

    def test_custom_values(self) -> None:
        """Test custom concurrency values."""
        config = ConcurrencyConfig(max_parallel=100, batch_size=100)

        assert config.max_parallel == 100
        assert config.batch_size == 100

    def test_validation_constraints(self) -> None:
        """Test validation constraints."""
        with pytest.raises(ValueError):
            ConcurrencyConfig(max_parallel=0)

        with pytest.raises(ValueError):
            ConcurrencyConfig(max_parallel=501)

        with pytest.raises(ValueError):
            ConcurrencyConfig(batch_size=0)

        with pytest.raises(ValueError):
            ConcurrencyConfig(batch_size=501)


# ============================================================================
# SelectionConfig Tests
# ============================================================================


class TestSelectionConfig:
    """Tests for SelectionConfig."""

    def test_default_values(self) -> None:
        """Test default selection config."""
        config = SelectionConfig()

        assert config.min_age_since_check == 3600

    def test_custom_values(self) -> None:
        """Test custom selection config."""
        config = SelectionConfig(min_age_since_check=0)

        assert config.min_age_since_check == 0


# ============================================================================
# MonitorConfig Tests
# ============================================================================


class TestMonitorConfig:
    """Tests for MonitorConfig Pydantic model."""

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
        assert config.selection.min_age_since_check == 3600
        assert config.interval == 3600.0

    def test_custom_nested_config(self) -> None:
        """Test custom nested configuration."""
        config = MonitorConfig(
            tor=TorConfig(enabled=False),
            selection=SelectionConfig(min_age_since_check=7200),
            interval=1800.0,
        )

        assert config.tor.enabled is False
        assert config.selection.min_age_since_check == 7200
        assert config.interval == 1800.0


# ============================================================================
# Monitor Initialization Tests
# ============================================================================


class TestMonitorInit:
    """Tests for Monitor initialization."""

    def test_init_with_defaults(self, mock_brotr: Brotr) -> None:
        """Test initialization with defaults."""
        monitor = Monitor(brotr=mock_brotr)

        assert monitor._brotr is mock_brotr
        assert monitor.SERVICE_NAME == "monitor"
        assert monitor.config.tor.enabled is True

    def test_init_with_custom_config(self, mock_brotr: Brotr) -> None:
        """Test initialization with custom config."""
        config = MonitorConfig(
            tor=TorConfig(enabled=False),
            selection=SelectionConfig(min_age_since_check=7200),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)

        assert monitor.config.tor.enabled is False
        assert monitor.config.selection.min_age_since_check == 7200

    def test_from_dict(self, mock_brotr: Brotr) -> None:
        """Test factory method from_dict."""
        data = {
            "tor": {"enabled": False},
            "selection": {"min_age_since_check": 7200},
        }
        monitor = Monitor.from_dict(data, brotr=mock_brotr)

        assert monitor.config.tor.enabled is False
        assert monitor.config.selection.min_age_since_check == 7200


# ============================================================================
# Monitor Fetch Relays Tests
# ============================================================================


class TestMonitorFetchRelays:
    """Tests for Monitor._fetch_relays_to_check() method."""

    @pytest.mark.asyncio
    async def test_fetch_relays_empty(self, mock_brotr: Brotr) -> None:
        """Test fetching relays when none need checking."""
        mock_brotr.pool._mock_connection.fetch = AsyncMock(return_value=[])  # type: ignore[attr-defined]

        monitor = Monitor(brotr=mock_brotr)
        relays = await monitor._fetch_relays_to_check()

        assert relays == []

    @pytest.mark.asyncio
    async def test_fetch_relays_with_results(self, mock_brotr: Brotr) -> None:
        """Test fetching relays that need checking."""
        mock_brotr.pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[
                {"relay_url": "wss://relay1.example.com"},
                {"relay_url": "wss://relay2.example.com"},
            ]
        )

        monitor = Monitor(brotr=mock_brotr)
        relays = await monitor._fetch_relays_to_check()

        assert len(relays) == 2
        assert "relay1.example.com" in relays[0].url
        assert "relay2.example.com" in relays[1].url

    @pytest.mark.asyncio
    async def test_fetch_relays_filters_invalid_urls(self, mock_brotr: Brotr) -> None:
        """Test fetching relays filters invalid URLs."""
        mock_brotr.pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[
                {"relay_url": "wss://valid.relay.com"},
                {"relay_url": "invalid-url"},
            ]
        )

        monitor = Monitor(brotr=mock_brotr)
        relays = await monitor._fetch_relays_to_check()

        assert len(relays) == 1
        assert "valid.relay.com" in relays[0].url

    @pytest.mark.asyncio
    async def test_fetch_relays_skips_tor_when_disabled(self, mock_brotr: Brotr) -> None:
        """Test .onion relays skipped when Tor disabled."""
        onion_url = "ws://oxtrdevav64z64yb7x6rjg4ntzqjhedm5b5zjqulugknhzr46ny2qbad.onion"
        mock_brotr.pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[
                {"relay_url": "wss://clearnet.relay.com"},
                {"relay_url": onion_url},
            ]
        )

        config = MonitorConfig(tor=TorConfig(enabled=False))
        monitor = Monitor(brotr=mock_brotr, config=config)
        relays = await monitor._fetch_relays_to_check()

        assert len(relays) == 1
        assert "clearnet.relay.com" in relays[0].url

    @pytest.mark.asyncio
    async def test_fetch_relays_includes_tor_when_enabled(self, mock_brotr: Brotr) -> None:
        """Test .onion relays included when Tor enabled."""
        onion_url = "ws://oxtrdevav64z64yb7x6rjg4ntzqjhedm5b5zjqulugknhzr46ny2qbad.onion"
        mock_brotr.pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[
                {"relay_url": "wss://clearnet.relay.com"},
                {"relay_url": onion_url},
            ]
        )

        config = MonitorConfig(tor=TorConfig(enabled=True))
        monitor = Monitor(brotr=mock_brotr, config=config)
        relays = await monitor._fetch_relays_to_check()

        assert len(relays) == 2


# ============================================================================
# Monitor Run Tests
# ============================================================================


class TestMonitorRun:
    """Tests for Monitor.run() method."""

    @pytest.mark.asyncio
    async def test_run_no_relays(self, mock_brotr: Brotr) -> None:
        """Test run cycle with no relays to check."""
        mock_brotr.pool._mock_connection.fetch = AsyncMock(return_value=[])  # type: ignore[attr-defined]

        monitor = Monitor(brotr=mock_brotr)
        await monitor.run()

        assert monitor._checked_relays == 0


# ============================================================================
# Monitor Insert Metadata Tests
# ============================================================================


class TestMonitorInsertMetadata:
    """Tests for Monitor._insert_metadata_batch() method."""

    @pytest.mark.asyncio
    async def test_insert_metadata_empty(self, mock_brotr: Brotr) -> None:
        """Test inserting empty metadata batch."""
        mock_brotr.insert_relay_metadata = AsyncMock(return_value=0)  # type: ignore[attr-defined]

        monitor = Monitor(brotr=mock_brotr)
        await monitor._insert_metadata_batch([])

        mock_brotr.insert_relay_metadata.assert_not_called()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_insert_metadata_success(self, mock_brotr: Brotr) -> None:
        """Test successful metadata batch insertion."""
        mock_brotr.insert_relay_metadata = AsyncMock(return_value=2)  # type: ignore[attr-defined]

        monitor = Monitor(brotr=mock_brotr)
        metadata = [
            {"relay_url": "wss://relay1.example.com/", "generated_at": 123456},
            {"relay_url": "wss://relay2.example.com/", "generated_at": 123456},
        ]
        await monitor._insert_metadata_batch(metadata)

        mock_brotr.insert_relay_metadata.assert_called_once_with(metadata)  # type: ignore[attr-defined]

