"""Unit tests for Validator configuration models."""

import pytest

from bigbrotr.services.common.configs import (
    ClearnetConfig,
    NetworksConfig,
    TorConfig,
)
from bigbrotr.services.validator import (
    CleanupConfig,
    ProcessingConfig,
    ValidatorConfig,
)


# ============================================================================
# ProcessingConfig Tests
# ============================================================================


class TestProcessingConfig:
    """Tests for ProcessingConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default processing configuration."""
        config = ProcessingConfig()
        assert config.chunk_size == 100
        assert config.max_candidates is None

    def test_custom_values(self) -> None:
        """Test custom processing configuration."""
        config = ProcessingConfig(chunk_size=200, max_candidates=1000)
        assert config.chunk_size == 200
        assert config.max_candidates == 1000

    def test_chunk_size_bounds(self) -> None:
        """Test chunk_size validation bounds."""
        # Valid values
        config_min = ProcessingConfig(chunk_size=10)
        assert config_min.chunk_size == 10

        config_max = ProcessingConfig(chunk_size=1000)
        assert config_max.chunk_size == 1000

        # Below minimum
        with pytest.raises(ValueError):
            ProcessingConfig(chunk_size=5)

        # Above maximum
        with pytest.raises(ValueError):
            ProcessingConfig(chunk_size=2000)

    def test_max_candidates_none(self) -> None:
        """Test max_candidates can be None (unlimited)."""
        config = ProcessingConfig(max_candidates=None)
        assert config.max_candidates is None


# ============================================================================
# CleanupConfig Tests
# ============================================================================


class TestCleanupConfig:
    """Tests for CleanupConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default cleanup configuration."""
        config = CleanupConfig()
        assert config.enabled is False
        assert config.max_failures == 100

    def test_custom_values(self) -> None:
        """Test custom cleanup configuration."""
        config = CleanupConfig(enabled=True, max_failures=5)
        assert config.enabled is True
        assert config.max_failures == 5

    def test_max_failures_bounds(self) -> None:
        """Test max_failures validation bounds."""
        # Valid values
        config_min = CleanupConfig(max_failures=1)
        assert config_min.max_failures == 1

        config_max = CleanupConfig(max_failures=1000)
        assert config_max.max_failures == 1000

        # Below minimum
        with pytest.raises(ValueError):
            CleanupConfig(max_failures=0)


# ============================================================================
# ValidatorConfig Tests
# ============================================================================


class TestValidatorConfig:
    """Tests for ValidatorConfig."""

    def test_default_config(self) -> None:
        """Test default configuration values."""
        config = ValidatorConfig()

        assert config.interval == 300.0
        assert config.processing.chunk_size == 100
        assert config.processing.max_candidates is None
        assert config.cleanup.enabled is False
        assert config.cleanup.max_failures == 100
        assert config.networks.clearnet.max_tasks == 50

    def test_custom_config(self) -> None:
        """Test custom configuration values."""
        config = ValidatorConfig(
            interval=600.0,
            processing={"chunk_size": 200, "max_candidates": 1000},
            cleanup={"enabled": True, "max_failures": 5},
        )

        assert config.interval == 600.0
        assert config.processing.chunk_size == 200
        assert config.processing.max_candidates == 1000
        assert config.cleanup.enabled is True
        assert config.cleanup.max_failures == 5

    def test_chunk_size_bounds(self) -> None:
        """Test chunk_size validation bounds."""
        with pytest.raises(ValueError):
            ValidatorConfig(processing={"chunk_size": 5})  # Below 10

        with pytest.raises(ValueError):
            ValidatorConfig(processing={"chunk_size": 2000})  # Above 1000

    def test_interval_minimum(self) -> None:
        """Test interval minimum constraint."""
        with pytest.raises(ValueError):
            ValidatorConfig(interval=30.0)

    def test_networks_config(self) -> None:
        """Test networks configuration."""
        config = ValidatorConfig(
            networks=NetworksConfig(
                clearnet=ClearnetConfig(max_tasks=100),
                tor=TorConfig(enabled=True, max_tasks=10),
            )
        )
        assert config.networks.clearnet.max_tasks == 100
        assert config.networks.tor.enabled is True
        assert config.networks.tor.max_tasks == 10


# ============================================================================
# Network Configuration Tests
# ============================================================================


class TestNetworkConfiguration:
    """Tests for network configuration via ValidatorConfig.networks."""

    def test_enabled_networks_default(self) -> None:
        """Test default enabled networks via config."""
        config = NetworksConfig()
        enabled = config.get_enabled_networks()
        assert "clearnet" in enabled

    def test_enabled_networks_with_tor(self) -> None:
        """Test enabled networks with Tor enabled."""
        config = NetworksConfig(
            clearnet=ClearnetConfig(enabled=True),
            tor=TorConfig(enabled=True),
        )
        enabled = config.get_enabled_networks()
        assert "clearnet" in enabled
        assert "tor" in enabled

    def test_network_config_for_clearnet(self) -> None:
        """Test getting network config for clearnet."""
        config = NetworksConfig(clearnet=ClearnetConfig(timeout=10.0, max_tasks=25))

        assert config.clearnet.timeout == 10.0
        assert config.clearnet.max_tasks == 25

    def test_network_config_for_tor(self) -> None:
        """Test getting network config for Tor."""
        config = NetworksConfig(
            tor=TorConfig(enabled=True, timeout=60.0, proxy_url="socks5://tor:9050")
        )

        assert config.tor.timeout == 60.0
        assert config.tor.proxy_url == "socks5://tor:9050"
