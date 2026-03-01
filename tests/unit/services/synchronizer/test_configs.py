"""
Unit tests for services.synchronizer config models.

Tests:
- FilterConfig validation (ids, kinds, authors, tags, limit)
- TimeRangeConfig defaults and custom values
- TimeoutsConfig defaults and get_relay_timeout
- ConcurrencyConfig defaults
- SourceConfig defaults and custom values
- RelayOverrideTimeouts validation (zero, negative, valid)
- RelayOverride validation (valid URL, empty URL)
- SynchronizerConfig defaults and nested configuration
"""

import pytest

from bigbrotr.models.constants import NetworkType
from bigbrotr.services.common.configs import NetworksConfig, TorConfig
from bigbrotr.services.synchronizer import (
    ConcurrencyConfig,
    FilterConfig,
    RelayOverride,
    RelayOverrideTimeouts,
    SourceConfig,
    SynchronizerConfig,
    TimeoutsConfig,
    TimeRangeConfig,
)


# ============================================================================
# FilterConfig Tests
# ============================================================================


class TestFilterConfig:
    """Tests for FilterConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default filter config."""
        config = FilterConfig()

        assert config.ids is None
        assert config.kinds is None
        assert config.authors is None
        assert config.tags is None
        assert config.limit == 500

    def test_custom_values(self) -> None:
        """Test custom filter config."""
        valid_id1 = "a" * 64
        valid_id2 = "b" * 64
        valid_author = "c" * 64
        config = FilterConfig(
            ids=[valid_id1, valid_id2],
            kinds=[1, 3, 4],
            authors=[valid_author],
            tags={"e": ["event1"]},
            limit=1000,
        )

        assert config.ids == [valid_id1, valid_id2]
        assert config.kinds == [1, 3, 4]
        assert config.authors == [valid_author]
        assert config.tags == {"e": ["event1"]}
        assert config.limit == 1000

    def test_limit_validation(self) -> None:
        """Test limit validation."""
        config = FilterConfig(limit=1)
        assert config.limit == 1

        config = FilterConfig(limit=5000)
        assert config.limit == 5000

        with pytest.raises(ValueError):
            FilterConfig(limit=0)

        with pytest.raises(ValueError):
            FilterConfig(limit=5001)

    def test_kinds_validation_valid_range(self) -> None:
        """Test event kinds within valid range (0-65535)."""
        config = FilterConfig(kinds=[0, 1, 30023, 65535])
        assert config.kinds == [0, 1, 30023, 65535]

    def test_kinds_validation_invalid_range(self) -> None:
        """Test event kinds outside valid range are rejected."""
        with pytest.raises(ValueError, match="out of valid range"):
            FilterConfig(kinds=[70000])

        with pytest.raises(ValueError, match="out of valid range"):
            FilterConfig(kinds=[-1])

    def test_ids_validation_valid_hex(self) -> None:
        """Test valid 64-character hex strings for IDs."""
        valid_hex = "a" * 64
        config = FilterConfig(ids=[valid_hex])
        assert config.ids == [valid_hex]

    def test_ids_validation_invalid_length(self) -> None:
        """Test IDs with invalid length are rejected."""
        with pytest.raises(ValueError, match="Invalid hex string length"):
            FilterConfig(ids=["short"])

    def test_authors_validation_valid_hex(self) -> None:
        """Test valid 64-character hex strings for authors."""
        valid_hex = "b" * 64
        config = FilterConfig(authors=[valid_hex])
        assert config.authors == [valid_hex]

    def test_authors_validation_invalid_hex_chars(self) -> None:
        """Test authors with invalid hex characters are rejected."""
        with pytest.raises(ValueError, match="Invalid hex string"):
            FilterConfig(authors=["z" * 64])


# ============================================================================
# TimeRangeConfig Tests
# ============================================================================


class TestTimeRangeConfig:
    """Tests for TimeRangeConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default time range config."""
        config = TimeRangeConfig()

        assert config.default_start == 0
        assert config.use_relay_state is True
        assert config.lookback_seconds == 86400

    def test_custom_values(self) -> None:
        """Test custom time range config."""
        config = TimeRangeConfig(
            default_start=1000000,
            use_relay_state=False,
            lookback_seconds=3600,
        )

        assert config.default_start == 1000000
        assert config.use_relay_state is False
        assert config.lookback_seconds == 3600


# ============================================================================
# TimeoutsConfig Tests
# ============================================================================


class TestTimeoutsConfig:
    """Tests for TimeoutsConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default sync timeouts."""
        config = TimeoutsConfig()

        assert config.relay_clearnet == 1800.0
        assert config.relay_tor == 3600.0
        assert config.relay_i2p == 3600.0
        assert config.relay_loki == 3600.0

    def test_get_relay_timeout(self) -> None:
        """Test get_relay_timeout method."""
        config = TimeoutsConfig()

        assert config.get_relay_timeout(NetworkType.CLEARNET) == 1800.0
        assert config.get_relay_timeout(NetworkType.TOR) == 3600.0
        assert config.get_relay_timeout(NetworkType.I2P) == 3600.0
        assert config.get_relay_timeout(NetworkType.LOKI) == 3600.0

    def test_custom_values(self) -> None:
        """Test custom sync timeouts."""
        config = TimeoutsConfig(
            relay_clearnet=900.0,
            relay_tor=1800.0,
        )

        assert config.relay_clearnet == 900.0
        assert config.relay_tor == 1800.0


# ============================================================================
# ConcurrencyConfig Tests
# ============================================================================


class TestConcurrencyConfig:
    """Tests for ConcurrencyConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default concurrency config."""
        config = ConcurrencyConfig()

        assert config.cursor_flush_interval == 50


# ============================================================================
# SourceConfig Tests
# ============================================================================


class TestSourceConfig:
    """Tests for SourceConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default source config."""
        config = SourceConfig()

        assert config.from_database is True

    def test_custom_values(self) -> None:
        """Test custom source config."""
        config = SourceConfig(
            from_database=False,
        )

        assert config.from_database is False


# ============================================================================
# RelayOverrideTimeouts Tests
# ============================================================================


class TestRelayOverrideTimeouts:
    """Tests for RelayOverrideTimeouts Pydantic model."""

    def test_defaults(self) -> None:
        """Test default values are None."""
        config = RelayOverrideTimeouts()
        assert config.request is None
        assert config.relay is None

    def test_valid_values(self) -> None:
        """Test valid timeout values."""
        config = RelayOverrideTimeouts(request=0.1, relay=60.0)
        assert config.request == 0.1
        assert config.relay == 60.0

    def test_zero_timeout_rejected(self) -> None:
        """Test that zero timeout is rejected."""
        with pytest.raises(ValueError):
            RelayOverrideTimeouts(request=0.0)

    def test_negative_timeout_rejected(self) -> None:
        """Test that negative timeout is rejected."""
        with pytest.raises(ValueError):
            RelayOverrideTimeouts(relay=-1.0)


class TestRelayOverride:
    """Tests for RelayOverride Pydantic model."""

    def test_valid(self) -> None:
        """Test valid relay override."""
        config = RelayOverride(url="wss://relay.example.com")
        assert config.url == "wss://relay.example.com"

    def test_empty_url_rejected(self) -> None:
        """Test that empty URL is rejected."""
        with pytest.raises(ValueError):
            RelayOverride(url="")


# ============================================================================
# SynchronizerConfig Tests
# ============================================================================


class TestSynchronizerConfig:
    """Tests for SynchronizerConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default configuration values (only clearnet enabled)."""
        config = SynchronizerConfig()

        assert config.networks.clearnet.enabled is True
        assert config.networks.tor.enabled is False  # disabled by default
        assert config.filter.limit == 500
        assert config.time_range.default_start == 0
        assert config.networks.clearnet.timeout == 10.0
        assert config.timeouts.relay_clearnet == 1800.0
        assert config.concurrency.cursor_flush_interval == 50
        assert config.source.from_database is True
        assert config.interval == 300.0

    def test_custom_nested_config(self) -> None:
        """Test custom nested configuration with Tor enabled."""
        config = SynchronizerConfig(
            networks=NetworksConfig(tor=TorConfig(enabled=True)),
            concurrency=ConcurrencyConfig(cursor_flush_interval=25),
            interval=1800.0,
        )

        assert config.networks.tor.enabled is True
        assert config.concurrency.cursor_flush_interval == 25
        assert config.interval == 1800.0

    def test_no_worker_log_level_field(self) -> None:
        """Test that worker_log_level field has been removed."""
        assert not hasattr(SynchronizerConfig(), "worker_log_level")
