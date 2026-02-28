"""
Unit tests for services.common.configs module (network configuration).

Tests:
- ClearnetConfig - Configuration for clearnet (standard internet) relays
- TorConfig - Configuration for Tor (.onion) relays
- I2pConfig - Configuration for I2P (.i2p) relays
- LokiConfig - Configuration for Lokinet (.loki) relays
- NetworksConfig - Unified configuration container for all networks
"""

import pytest
from pydantic import ValidationError

from bigbrotr.models.constants import NetworkType
from bigbrotr.services.common.configs import (
    ClearnetConfig,
    I2pConfig,
    LokiConfig,
    NetworksConfig,
    NetworkTypeConfig,
    TorConfig,
)


# =============================================================================
# ClearnetConfig Tests
# =============================================================================


class TestClearnetConfigDefaults:
    """Tests for ClearnetConfig default values."""

    def test_default_enabled(self) -> None:
        """Test clearnet is enabled by default."""
        config = ClearnetConfig()
        assert config.enabled is True

    def test_default_proxy_url(self) -> None:
        """Test clearnet has no proxy by default."""
        config = ClearnetConfig()
        assert config.proxy_url is None

    def test_default_max_tasks(self) -> None:
        """Test clearnet has 50 max_tasks by default."""
        config = ClearnetConfig()
        assert config.max_tasks == 50

    def test_default_timeout(self) -> None:
        """Test clearnet has 10.0s timeout by default."""
        config = ClearnetConfig()
        assert config.timeout == 10.0


class TestClearnetConfigCustomValues:
    """Tests for ClearnetConfig with custom values."""

    def test_all_custom_values(self) -> None:
        """Test setting all fields to custom values."""
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

    def test_partial_custom_values(self) -> None:
        """Test partial override preserves defaults."""
        config = ClearnetConfig(enabled=False, max_tasks=25)
        assert config.enabled is False
        assert config.proxy_url is None
        assert config.max_tasks == 25
        assert config.timeout == 10.0


# =============================================================================
# TorConfig Tests
# =============================================================================


class TestTorConfigDefaults:
    """Tests for TorConfig default values."""

    def test_default_enabled(self) -> None:
        """Test Tor is disabled by default."""
        config = TorConfig()
        assert config.enabled is False

    def test_default_proxy_url(self) -> None:
        """Test Tor has Docker hostname proxy by default."""
        config = TorConfig()
        assert config.proxy_url == "socks5://tor:9050"

    def test_default_max_tasks(self) -> None:
        """Test Tor has 10 max_tasks by default (lower than clearnet)."""
        config = TorConfig()
        assert config.max_tasks == 10

    def test_default_timeout(self) -> None:
        """Test Tor has 30.0s timeout by default (longer than clearnet)."""
        config = TorConfig()
        assert config.timeout == 30.0


class TestTorConfigPartialOverride:
    """Tests for TorConfig partial YAML override behavior."""

    def test_partial_override_inherits_proxy_url(self) -> None:
        """Test partial YAML override inherits proxy_url default."""
        config = TorConfig(enabled=True)
        assert config.enabled is True
        assert config.proxy_url == "socks5://tor:9050"

    def test_partial_override_inherits_timeout(self) -> None:
        """Test partial override inherits timeout default."""
        config = TorConfig(enabled=True, max_tasks=20)
        assert config.timeout == 30.0


class TestTorConfigCustomValues:
    """Tests for TorConfig with custom values."""

    def test_all_custom_values(self) -> None:
        """Test setting all fields to custom values."""
        config = TorConfig(
            enabled=True,
            proxy_url="socks5://localhost:9050",
            max_tasks=20,
            timeout=45.0,
        )
        assert config.enabled is True
        assert config.proxy_url == "socks5://localhost:9050"
        assert config.max_tasks == 20
        assert config.timeout == 45.0


# =============================================================================
# I2pConfig Tests
# =============================================================================


class TestI2pConfigDefaults:
    """Tests for I2pConfig default values."""

    def test_default_enabled(self) -> None:
        """Test I2P is disabled by default."""
        config = I2pConfig()
        assert config.enabled is False

    def test_default_proxy_url(self) -> None:
        """Test I2P has Docker hostname proxy by default."""
        config = I2pConfig()
        assert config.proxy_url == "socks5://i2p:4447"

    def test_default_max_tasks(self) -> None:
        """Test I2P has 5 max_tasks by default (lowest)."""
        config = I2pConfig()
        assert config.max_tasks == 5

    def test_default_timeout(self) -> None:
        """Test I2P has 45.0s timeout by default (longest)."""
        config = I2pConfig()
        assert config.timeout == 45.0


class TestI2pConfigCustomValues:
    """Tests for I2pConfig with custom values."""

    def test_partial_override_inherits_defaults(self) -> None:
        """Test partial override inherits proxy_url and timeout defaults."""
        config = I2pConfig(enabled=True)
        assert config.enabled is True
        assert config.proxy_url == "socks5://i2p:4447"
        assert config.timeout == 45.0


# =============================================================================
# LokiConfig Tests
# =============================================================================


class TestLokiConfigDefaults:
    """Tests for LokiConfig default values."""

    def test_default_enabled(self) -> None:
        """Test Lokinet is disabled by default."""
        config = LokiConfig()
        assert config.enabled is False

    def test_default_proxy_url(self) -> None:
        """Test Lokinet has Docker hostname proxy by default."""
        config = LokiConfig()
        assert config.proxy_url == "socks5://lokinet:1080"

    def test_default_max_tasks(self) -> None:
        """Test Lokinet has 5 max_tasks by default."""
        config = LokiConfig()
        assert config.max_tasks == 5

    def test_default_timeout(self) -> None:
        """Test Lokinet has 30.0s timeout by default."""
        config = LokiConfig()
        assert config.timeout == 30.0


class TestLokiConfigCustomValues:
    """Tests for LokiConfig with custom values."""

    def test_partial_override_inherits_defaults(self) -> None:
        """Test partial override inherits proxy_url default."""
        config = LokiConfig(enabled=True)
        assert config.enabled is True
        assert config.proxy_url == "socks5://lokinet:1080"


# =============================================================================
# Validation Tests (max_tasks and timeout constraints)
# =============================================================================


class TestMaxTasksValidation:
    """Tests for max_tasks validation constraints across all network configs."""

    def test_max_tasks_minimum_boundary(self) -> None:
        """Test max_tasks=1 is valid (minimum)."""
        config = ClearnetConfig(max_tasks=1)
        assert config.max_tasks == 1

    def test_max_tasks_maximum_boundary(self) -> None:
        """Test max_tasks=200 is valid (maximum)."""
        config = ClearnetConfig(max_tasks=200)
        assert config.max_tasks == 200

    def test_max_tasks_below_minimum_raises(self) -> None:
        """Test max_tasks=0 raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ClearnetConfig(max_tasks=0)
        assert "max_tasks" in str(exc_info.value).lower()

    def test_max_tasks_above_maximum_raises(self) -> None:
        """Test max_tasks=201 raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ClearnetConfig(max_tasks=201)
        assert "max_tasks" in str(exc_info.value).lower()

    def test_max_tasks_negative_raises(self) -> None:
        """Test max_tasks=-1 raises ValidationError."""
        with pytest.raises(ValidationError):
            ClearnetConfig(max_tasks=-1)

    @pytest.mark.parametrize(
        "config_class",
        [ClearnetConfig, TorConfig, I2pConfig, LokiConfig],
    )
    def test_validation_applies_to_all_network_types(self, config_class: type) -> None:
        """Test max_tasks validation applies to all network config classes."""
        with pytest.raises(ValidationError):
            config_class(max_tasks=0)
        with pytest.raises(ValidationError):
            config_class(max_tasks=201)


class TestTimeoutValidation:
    """Tests for timeout validation constraints across all network configs."""

    def test_timeout_minimum_boundary(self) -> None:
        """Test timeout=1.0 is valid (minimum)."""
        config = ClearnetConfig(timeout=1.0)
        assert config.timeout == 1.0

    def test_timeout_maximum_boundary(self) -> None:
        """Test timeout=120.0 is valid (maximum)."""
        config = ClearnetConfig(timeout=120.0)
        assert config.timeout == 120.0

    def test_timeout_below_minimum_raises(self) -> None:
        """Test timeout=0.5 raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ClearnetConfig(timeout=0.5)
        assert "timeout" in str(exc_info.value).lower()

    def test_timeout_above_maximum_raises(self) -> None:
        """Test timeout=121.0 raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ClearnetConfig(timeout=121.0)
        assert "timeout" in str(exc_info.value).lower()

    def test_timeout_zero_raises(self) -> None:
        """Test timeout=0.0 raises ValidationError."""
        with pytest.raises(ValidationError):
            ClearnetConfig(timeout=0.0)

    def test_timeout_negative_raises(self) -> None:
        """Test timeout=-1.0 raises ValidationError."""
        with pytest.raises(ValidationError):
            ClearnetConfig(timeout=-1.0)

    @pytest.mark.parametrize(
        "config_class",
        [ClearnetConfig, TorConfig, I2pConfig, LokiConfig],
    )
    def test_validation_applies_to_all_network_types(self, config_class: type) -> None:
        """Test timeout validation applies to all network config classes."""
        with pytest.raises(ValidationError):
            config_class(timeout=0.5)
        with pytest.raises(ValidationError):
            config_class(timeout=121.0)


# =============================================================================
# NetworksConfig Tests
# =============================================================================


class TestNetworksConfigDefaults:
    """Tests for NetworksConfig default values for all networks."""

    def test_clearnet_defaults(self) -> None:
        """Test clearnet has correct defaults in NetworksConfig."""
        config = NetworksConfig()
        assert config.clearnet.enabled is True
        assert config.clearnet.proxy_url is None
        assert config.clearnet.max_tasks == 50
        assert config.clearnet.timeout == 10.0

    def test_tor_defaults(self) -> None:
        """Test Tor has correct defaults in NetworksConfig."""
        config = NetworksConfig()
        assert config.tor.enabled is False
        assert config.tor.proxy_url == "socks5://tor:9050"
        assert config.tor.max_tasks == 10
        assert config.tor.timeout == 30.0

    def test_i2p_defaults(self) -> None:
        """Test I2P has correct defaults in NetworksConfig."""
        config = NetworksConfig()
        assert config.i2p.enabled is False
        assert config.i2p.proxy_url == "socks5://i2p:4447"
        assert config.i2p.max_tasks == 5
        assert config.i2p.timeout == 45.0

    def test_loki_defaults(self) -> None:
        """Test Lokinet has correct defaults in NetworksConfig."""
        config = NetworksConfig()
        assert config.loki.enabled is False
        assert config.loki.proxy_url == "socks5://lokinet:1080"
        assert config.loki.max_tasks == 5
        assert config.loki.timeout == 30.0


class TestNetworksConfigCustomValues:
    """Tests for NetworksConfig with custom network configurations."""

    def test_custom_clearnet(self) -> None:
        """Test custom clearnet config with defaults for other networks."""
        config = NetworksConfig(clearnet=ClearnetConfig(max_tasks=100, timeout=5.0))
        assert config.clearnet.max_tasks == 100
        assert config.clearnet.timeout == 5.0
        assert config.tor.enabled is False
        assert config.i2p.max_tasks == 5

    def test_custom_tor(self) -> None:
        """Test custom Tor config with all fields."""
        config = NetworksConfig(
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

    def test_multiple_networks_custom(self) -> None:
        """Test multiple networks with custom configurations."""
        config = NetworksConfig(
            clearnet=ClearnetConfig(max_tasks=100),
            tor=TorConfig(enabled=True),
            i2p=I2pConfig(enabled=True, timeout=60.0),
        )
        assert config.clearnet.max_tasks == 100
        assert config.tor.enabled is True
        assert config.tor.proxy_url == "socks5://tor:9050"
        assert config.i2p.enabled is True
        assert config.i2p.timeout == 60.0
        assert config.loki.enabled is False

    def test_all_networks_enabled(self) -> None:
        """Test all networks can be enabled simultaneously."""
        config = NetworksConfig(
            clearnet=ClearnetConfig(enabled=True),
            tor=TorConfig(enabled=True),
            i2p=I2pConfig(enabled=True),
            loki=LokiConfig(enabled=True),
        )
        assert config.clearnet.enabled is True
        assert config.tor.enabled is True
        assert config.i2p.enabled is True
        assert config.loki.enabled is True


class TestNetworksConfigGet:
    """Tests for NetworksConfig.get() method."""

    def test_get_clearnet(self) -> None:
        """Test get() returns clearnet config."""
        config = NetworksConfig()
        result = config.get(NetworkType.CLEARNET)
        assert result is config.clearnet

    def test_get_tor(self) -> None:
        """Test get() returns Tor config."""
        config = NetworksConfig()
        result = config.get(NetworkType.TOR)
        assert result is config.tor

    def test_get_i2p(self) -> None:
        """Test get() returns I2P config."""
        config = NetworksConfig()
        result = config.get(NetworkType.I2P)
        assert result is config.i2p

    def test_get_loki(self) -> None:
        """Test get() returns Lokinet config."""
        config = NetworksConfig()
        result = config.get(NetworkType.LOKI)
        assert result is config.loki

    def test_get_returns_correct_custom_config(self) -> None:
        """Test get() returns the custom config when set."""
        config = NetworksConfig(tor=TorConfig(max_tasks=99, timeout=99.0))
        result = config.get(NetworkType.TOR)
        assert result.max_tasks == 99
        assert result.timeout == 99.0

    def test_get_result_is_network_type_config(self) -> None:
        """Test get() returns NetworkTypeConfig type."""
        config = NetworksConfig()
        for network_type in NetworkType:
            result = config.get(network_type)
            assert isinstance(result, (ClearnetConfig, TorConfig, I2pConfig, LokiConfig))


class TestNetworksConfigGetProxyUrl:
    """Tests for NetworksConfig.get_proxy_url() method."""

    def test_clearnet_always_none(self) -> None:
        """Test clearnet proxy is always None regardless of config."""
        config = NetworksConfig(clearnet=ClearnetConfig(proxy_url="socks5://test:1234"))
        assert config.get_proxy_url(NetworkType.CLEARNET) is None

    def test_tor_enabled_returns_proxy(self) -> None:
        """Test Tor proxy is returned when enabled."""
        config = NetworksConfig(tor=TorConfig(enabled=True, proxy_url="socks5://tor:9050"))
        assert config.get_proxy_url(NetworkType.TOR) == "socks5://tor:9050"

    def test_tor_disabled_returns_none(self) -> None:
        """Test Tor proxy is None when disabled."""
        config = NetworksConfig(tor=TorConfig(enabled=False, proxy_url="socks5://tor:9050"))
        assert config.get_proxy_url(NetworkType.TOR) is None

    def test_i2p_enabled_returns_proxy(self) -> None:
        """Test I2P proxy is returned when enabled."""
        config = NetworksConfig(i2p=I2pConfig(enabled=True, proxy_url="socks5://i2p:4447"))
        assert config.get_proxy_url(NetworkType.I2P) == "socks5://i2p:4447"

    def test_loki_enabled_returns_proxy(self) -> None:
        """Test Lokinet proxy is returned when enabled."""
        config = NetworksConfig(loki=LokiConfig(enabled=True, proxy_url="socks5://lokinet:1080"))
        assert config.get_proxy_url(NetworkType.LOKI) == "socks5://lokinet:1080"

    def test_custom_proxy_url_returned(self) -> None:
        """Test custom proxy URL is returned when enabled."""
        config = NetworksConfig(tor=TorConfig(enabled=True, proxy_url="socks5://custom:5555"))
        assert config.get_proxy_url(NetworkType.TOR) == "socks5://custom:5555"


class TestNetworksConfigIsEnabled:
    """Tests for NetworksConfig.is_enabled() method."""

    def test_clearnet_enabled_by_default(self) -> None:
        """Test clearnet is enabled by default."""
        config = NetworksConfig()
        assert config.is_enabled(NetworkType.CLEARNET) is True

    def test_tor_disabled_by_default(self) -> None:
        """Test Tor is disabled by default."""
        config = NetworksConfig()
        assert config.is_enabled(NetworkType.TOR) is False

    def test_i2p_disabled_by_default(self) -> None:
        """Test I2P is disabled by default."""
        config = NetworksConfig()
        assert config.is_enabled(NetworkType.I2P) is False

    def test_loki_disabled_by_default(self) -> None:
        """Test Lokinet is disabled by default."""
        config = NetworksConfig()
        assert config.is_enabled(NetworkType.LOKI) is False

    def test_custom_enabled_state(self) -> None:
        """Test custom enabled state is respected."""
        config = NetworksConfig(
            clearnet=ClearnetConfig(enabled=False),
            tor=TorConfig(enabled=True),
        )
        assert config.is_enabled(NetworkType.CLEARNET) is False
        assert config.is_enabled(NetworkType.TOR) is True


class TestNetworksConfigGetEnabledNetworks:
    """Tests for NetworksConfig.get_enabled_networks() method."""

    def test_default_only_clearnet(self) -> None:
        """Test default config has only clearnet enabled."""
        config = NetworksConfig()
        enabled = config.get_enabled_networks()
        assert enabled == [NetworkType.CLEARNET]

    def test_multiple_enabled(self) -> None:
        """Test multiple enabled networks are returned."""
        config = NetworksConfig(
            clearnet=ClearnetConfig(enabled=True),
            tor=TorConfig(enabled=True),
            i2p=I2pConfig(enabled=True),
            loki=LokiConfig(enabled=False),
        )
        enabled = config.get_enabled_networks()
        assert enabled == [NetworkType.CLEARNET, NetworkType.TOR, NetworkType.I2P]

    def test_all_enabled(self) -> None:
        """Test all enabled networks are returned."""
        config = NetworksConfig(
            clearnet=ClearnetConfig(enabled=True),
            tor=TorConfig(enabled=True),
            i2p=I2pConfig(enabled=True),
            loki=LokiConfig(enabled=True),
        )
        enabled = config.get_enabled_networks()
        assert enabled == [NetworkType.CLEARNET, NetworkType.TOR, NetworkType.I2P, NetworkType.LOKI]

    def test_none_enabled(self) -> None:
        """Test empty list when no networks enabled."""
        config = NetworksConfig(
            clearnet=ClearnetConfig(enabled=False),
            tor=TorConfig(enabled=False),
            i2p=I2pConfig(enabled=False),
            loki=LokiConfig(enabled=False),
        )
        enabled = config.get_enabled_networks()
        assert enabled == []

    def test_returns_list_in_field_definition_order(self) -> None:
        """Test order matches field definition in NetworksConfig."""
        config = NetworksConfig(
            clearnet=ClearnetConfig(enabled=True),
            tor=TorConfig(enabled=True),
            i2p=I2pConfig(enabled=True),
            loki=LokiConfig(enabled=True),
        )
        enabled = config.get_enabled_networks()
        assert enabled == [NetworkType.CLEARNET, NetworkType.TOR, NetworkType.I2P, NetworkType.LOKI]


# =============================================================================
# NetworkTypeConfig Type Alias Tests
# =============================================================================


class TestNetworkTypeConfigAlias:
    """Tests for NetworkTypeConfig type alias."""

    def test_clearnet_is_network_type_config(self) -> None:
        """Test ClearnetConfig is a NetworkTypeConfig."""
        config: NetworkTypeConfig = ClearnetConfig()
        assert isinstance(config, ClearnetConfig)

    def test_tor_is_network_type_config(self) -> None:
        """Test TorConfig is a NetworkTypeConfig."""
        config: NetworkTypeConfig = TorConfig()
        assert isinstance(config, TorConfig)

    def test_i2p_is_network_type_config(self) -> None:
        """Test I2pConfig is a NetworkTypeConfig."""
        config: NetworkTypeConfig = I2pConfig()
        assert isinstance(config, I2pConfig)

    def test_loki_is_network_type_config(self) -> None:
        """Test LokiConfig is a NetworkTypeConfig."""
        config: NetworkTypeConfig = LokiConfig()
        assert isinstance(config, LokiConfig)


# =============================================================================
# NetworksConfig YAML-like Construction Tests
# =============================================================================


class TestNetworksConfigYamlConstruction:
    """Tests for NetworksConfig construction from dict (simulating YAML loading)."""

    def test_from_dict_partial_tor(self) -> None:
        """Test construction from dict with partial Tor config."""
        config = NetworksConfig(tor=TorConfig.model_validate({"enabled": True}))
        assert config.tor.enabled is True
        assert config.tor.proxy_url == "socks5://tor:9050"

    def test_from_nested_dict(self) -> None:
        """Test construction from fully nested dict structure."""
        data = {
            "clearnet": {"max_tasks": 100},
            "tor": {"enabled": True},
        }
        config = NetworksConfig.model_validate(data)
        assert config.clearnet.max_tasks == 100
        assert config.tor.enabled is True
        assert config.tor.proxy_url == "socks5://tor:9050"

    def test_empty_dict_uses_all_defaults(self) -> None:
        """Test empty dict uses all default values."""
        config = NetworksConfig.model_validate({})
        assert config.clearnet.enabled is True
        assert config.tor.enabled is False
        assert config.i2p.enabled is False
        assert config.loki.enabled is False
