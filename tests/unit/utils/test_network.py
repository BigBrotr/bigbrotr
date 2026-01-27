"""
Unit tests for utils.network module.

Tests:
- ClearnetConfig, TorConfig, I2pConfig, LokiConfig - Network-specific configs
- NetworkConfig - Unified configuration for all networks
"""

import pytest
from pydantic import ValidationError

from models.relay import NetworkType
from utils.network import (
    ClearnetConfig,
    I2pConfig,
    LokiConfig,
    NetworkConfig,
    TorConfig,
)


# =============================================================================
# ClearnetConfig Tests
# =============================================================================


class TestClearnetConfigDefaults:
    """ClearnetConfig default values."""

    def test_default_enabled(self):
        config = ClearnetConfig()
        assert config.enabled is True

    def test_default_proxy_url(self):
        config = ClearnetConfig()
        assert config.proxy_url is None

    def test_default_max_tasks(self):
        config = ClearnetConfig()
        assert config.max_tasks == 50

    def test_default_timeout(self):
        config = ClearnetConfig()
        assert config.timeout == 10.0


class TestClearnetConfigCustomValues:
    """ClearnetConfig with custom values."""

    def test_all_custom_values(self):
        config = ClearnetConfig(
            enabled=False,
            proxy_url="socks5://127.0.0.1:9050",
            max_tasks=100,
            timeout=30.0,
        )
        assert config.enabled is False
        assert config.proxy_url == "socks5://127.0.0.1:9050"
        assert config.max_tasks == 100
        assert config.timeout == 30.0

    def test_partial_custom_values(self):
        config = ClearnetConfig(enabled=False, max_tasks=25)
        assert config.enabled is False
        assert config.proxy_url is None  # Inherits default
        assert config.max_tasks == 25
        assert config.timeout == 10.0  # Inherits default


# =============================================================================
# Validation Tests (using ClearnetConfig as concrete class)
# =============================================================================


class TestMaxTasksValidation:
    """max_tasks validation constraints (inherited from NetworkTypeConfig)."""

    def test_max_tasks_minimum_boundary(self):
        config = ClearnetConfig(max_tasks=1)
        assert config.max_tasks == 1

    def test_max_tasks_maximum_boundary(self):
        config = ClearnetConfig(max_tasks=200)
        assert config.max_tasks == 200

    def test_max_tasks_below_minimum_raises(self):
        with pytest.raises(ValidationError):
            ClearnetConfig(max_tasks=0)

    def test_max_tasks_above_maximum_raises(self):
        with pytest.raises(ValidationError):
            ClearnetConfig(max_tasks=201)

    def test_max_tasks_negative_raises(self):
        with pytest.raises(ValidationError):
            ClearnetConfig(max_tasks=-1)


class TestTimeoutValidation:
    """timeout validation constraints (inherited from NetworkTypeConfig)."""

    def test_timeout_minimum_boundary(self):
        config = ClearnetConfig(timeout=1.0)
        assert config.timeout == 1.0

    def test_timeout_maximum_boundary(self):
        config = ClearnetConfig(timeout=120.0)
        assert config.timeout == 120.0

    def test_timeout_below_minimum_raises(self):
        with pytest.raises(ValidationError):
            ClearnetConfig(timeout=0.5)

    def test_timeout_above_maximum_raises(self):
        with pytest.raises(ValidationError):
            ClearnetConfig(timeout=121.0)

    def test_timeout_zero_raises(self):
        with pytest.raises(ValidationError):
            ClearnetConfig(timeout=0.0)


# =============================================================================
# TorConfig Tests
# =============================================================================


class TestTorConfigDefaults:
    """TorConfig default values."""

    def test_default_enabled(self):
        config = TorConfig()
        assert config.enabled is False

    def test_default_proxy_url(self):
        config = TorConfig()
        assert config.proxy_url == "socks5://tor:9050"

    def test_default_max_tasks(self):
        config = TorConfig()
        assert config.max_tasks == 10

    def test_default_timeout(self):
        config = TorConfig()
        assert config.timeout == 30.0

    def test_partial_override_inherits_proxy_url(self):
        """Key test: partial YAML override inherits proxy_url default."""
        config = TorConfig(enabled=True)
        assert config.enabled is True
        assert config.proxy_url == "socks5://tor:9050"  # Inherited!


# =============================================================================
# NetworkConfig Tests
# =============================================================================


class TestNetworkConfigDefaults:
    """NetworkConfig default values."""

    def test_clearnet_defaults(self):
        config = NetworkConfig()
        assert config.clearnet.enabled is True
        assert config.clearnet.proxy_url is None
        assert config.clearnet.max_tasks == 50
        assert config.clearnet.timeout == 10.0

    def test_tor_defaults(self):
        config = NetworkConfig()
        assert config.tor.enabled is False
        assert config.tor.proxy_url == "socks5://tor:9050"
        assert config.tor.max_tasks == 10
        assert config.tor.timeout == 30.0

    def test_i2p_defaults(self):
        config = NetworkConfig()
        assert config.i2p.enabled is False
        assert config.i2p.proxy_url == "socks5://i2p:4447"
        assert config.i2p.max_tasks == 5
        assert config.i2p.timeout == 45.0

    def test_loki_defaults(self):
        config = NetworkConfig()
        assert config.loki.enabled is False
        assert config.loki.proxy_url == "socks5://lokinet:1080"
        assert config.loki.max_tasks == 5
        assert config.loki.timeout == 30.0


class TestNetworkConfigCustomValues:
    """NetworkConfig with custom values."""

    def test_custom_clearnet(self):
        config = NetworkConfig(clearnet=ClearnetConfig(max_tasks=100, timeout=5.0))
        assert config.clearnet.max_tasks == 100
        assert config.clearnet.timeout == 5.0
        # Other networks keep defaults
        assert config.tor.enabled is False

    def test_custom_tor(self):
        config = NetworkConfig(
            tor=TorConfig(
                enabled=True,
                proxy_url="socks5://localhost:9050",
                max_tasks=20,
                timeout=45.0,
            )
        )
        assert config.tor.enabled is True
        assert config.tor.proxy_url == "socks5://localhost:9050"
        assert config.tor.max_tasks == 20
        assert config.tor.timeout == 45.0

    def test_multiple_networks_custom(self):
        config = NetworkConfig(
            clearnet=ClearnetConfig(max_tasks=100),
            tor=TorConfig(enabled=True),
            i2p=I2pConfig(enabled=True, timeout=60.0),
        )
        assert config.clearnet.max_tasks == 100
        assert config.tor.enabled is True
        assert config.i2p.enabled is True
        assert config.i2p.timeout == 60.0


class TestNetworkConfigGet:
    """NetworkConfig.get() method."""

    def test_get_clearnet(self):
        config = NetworkConfig()
        result = config.get(NetworkType.CLEARNET)
        assert result == config.clearnet

    def test_get_tor(self):
        config = NetworkConfig()
        result = config.get(NetworkType.TOR)
        assert result == config.tor

    def test_get_i2p(self):
        config = NetworkConfig()
        result = config.get(NetworkType.I2P)
        assert result == config.i2p

    def test_get_loki(self):
        config = NetworkConfig()
        result = config.get(NetworkType.LOKI)
        assert result == config.loki

    def test_get_returns_correct_custom_config(self):
        config = NetworkConfig(tor=TorConfig(max_tasks=99, timeout=99.0))
        result = config.get(NetworkType.TOR)
        assert result.max_tasks == 99
        assert result.timeout == 99.0


class TestNetworkConfigGetProxyUrl:
    """NetworkConfig.get_proxy_url() method."""

    def test_clearnet_always_none(self):
        config = NetworkConfig()
        assert config.get_proxy_url(NetworkType.CLEARNET) is None

    def test_clearnet_string_always_none(self):
        config = NetworkConfig()
        assert config.get_proxy_url("clearnet") is None

    def test_tor_enabled_returns_proxy(self):
        config = NetworkConfig(tor=TorConfig(enabled=True, proxy_url="socks5://tor:9050"))
        assert config.get_proxy_url(NetworkType.TOR) == "socks5://tor:9050"

    def test_tor_disabled_returns_none(self):
        config = NetworkConfig(tor=TorConfig(enabled=False, proxy_url="socks5://tor:9050"))
        assert config.get_proxy_url(NetworkType.TOR) is None

    def test_accepts_string_network(self):
        config = NetworkConfig(tor=TorConfig(enabled=True, proxy_url="socks5://tor:9050"))
        assert config.get_proxy_url("tor") == "socks5://tor:9050"

    def test_invalid_string_network_returns_none(self):
        config = NetworkConfig()
        assert config.get_proxy_url("invalid_network") is None

    def test_i2p_enabled_returns_proxy(self):
        config = NetworkConfig(i2p=I2pConfig(enabled=True, proxy_url="socks5://i2p:4447"))
        assert config.get_proxy_url(NetworkType.I2P) == "socks5://i2p:4447"

    def test_loki_enabled_returns_proxy(self):
        config = NetworkConfig(loki=LokiConfig(enabled=True, proxy_url="socks5://lokinet:1080"))
        assert config.get_proxy_url(NetworkType.LOKI) == "socks5://lokinet:1080"


class TestNetworkConfigIsEnabled:
    """NetworkConfig.is_enabled() method."""

    def test_clearnet_enabled_by_default(self):
        config = NetworkConfig()
        assert config.is_enabled(NetworkType.CLEARNET) is True

    def test_tor_disabled_by_default(self):
        config = NetworkConfig()
        assert config.is_enabled(NetworkType.TOR) is False

    def test_i2p_disabled_by_default(self):
        config = NetworkConfig()
        assert config.is_enabled(NetworkType.I2P) is False

    def test_loki_disabled_by_default(self):
        config = NetworkConfig()
        assert config.is_enabled(NetworkType.LOKI) is False

    def test_accepts_string_network(self):
        config = NetworkConfig()
        assert config.is_enabled("clearnet") is True
        assert config.is_enabled("tor") is False

    def test_invalid_string_returns_false(self):
        config = NetworkConfig()
        assert config.is_enabled("invalid_network") is False

    def test_custom_enabled_state(self):
        config = NetworkConfig(
            clearnet=ClearnetConfig(enabled=False),
            tor=TorConfig(enabled=True),
        )
        assert config.is_enabled(NetworkType.CLEARNET) is False
        assert config.is_enabled(NetworkType.TOR) is True


class TestNetworkConfigGetEnabledNetworks:
    """NetworkConfig.get_enabled_networks() method."""

    def test_default_only_clearnet(self):
        config = NetworkConfig()
        enabled = config.get_enabled_networks()
        assert enabled == ["clearnet"]

    def test_multiple_enabled(self):
        config = NetworkConfig(
            clearnet=ClearnetConfig(enabled=True),
            tor=TorConfig(enabled=True),
            i2p=I2pConfig(enabled=True),
            loki=LokiConfig(enabled=False),
        )
        enabled = config.get_enabled_networks()
        assert enabled == ["clearnet", "tor", "i2p"]

    def test_all_enabled(self):
        config = NetworkConfig(
            clearnet=ClearnetConfig(enabled=True),
            tor=TorConfig(enabled=True),
            i2p=I2pConfig(enabled=True),
            loki=LokiConfig(enabled=True),
        )
        enabled = config.get_enabled_networks()
        assert enabled == ["clearnet", "tor", "i2p", "loki"]

    def test_none_enabled(self):
        config = NetworkConfig(
            clearnet=ClearnetConfig(enabled=False),
            tor=TorConfig(enabled=False),
            i2p=I2pConfig(enabled=False),
            loki=LokiConfig(enabled=False),
        )
        enabled = config.get_enabled_networks()
        assert enabled == []

    def test_returns_list_in_field_definition_order(self):
        config = NetworkConfig(
            clearnet=ClearnetConfig(enabled=True),
            tor=TorConfig(enabled=True),
            i2p=I2pConfig(enabled=True),
            loki=LokiConfig(enabled=True),
        )
        enabled = config.get_enabled_networks()
        # Order matches field definition in NetworkConfig
        assert enabled == ["clearnet", "tor", "i2p", "loki"]
