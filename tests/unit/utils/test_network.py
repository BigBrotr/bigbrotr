"""
Unit tests for utils.network module.

Tests:
- ClearnetConfig - Configuration for clearnet (standard internet) relays
- TorConfig - Configuration for Tor (.onion) relays
- I2pConfig - Configuration for I2P (.i2p) relays
- LokiConfig - Configuration for Lokinet (.loki) relays
- NetworkConfig - Unified configuration container for all networks
"""

import pytest
from pydantic import ValidationError

from models.relay import NetworkType
from utils.network import (
    ClearnetConfig,
    I2pConfig,
    LokiConfig,
    NetworkConfig,
    NetworkTypeConfig,
    TorConfig,
)


# =============================================================================
# ClearnetConfig Tests
# =============================================================================


class TestClearnetConfigDefaults:
    """ClearnetConfig default values."""

    def test_default_enabled(self):
        """Clearnet is enabled by default."""
        config = ClearnetConfig()
        assert config.enabled is True

    def test_default_proxy_url(self):
        """Clearnet has no proxy by default."""
        config = ClearnetConfig()
        assert config.proxy_url is None

    def test_default_max_tasks(self):
        """Clearnet has 50 max_tasks by default."""
        config = ClearnetConfig()
        assert config.max_tasks == 50

    def test_default_timeout(self):
        """Clearnet has 10.0s timeout by default."""
        config = ClearnetConfig()
        assert config.timeout == 10.0


class TestClearnetConfigCustomValues:
    """ClearnetConfig with custom values."""

    def test_all_custom_values(self):
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

    def test_partial_custom_values(self):
        """Test partial override preserves defaults."""
        config = ClearnetConfig(enabled=False, max_tasks=25)
        assert config.enabled is False
        assert config.proxy_url is None  # Default preserved
        assert config.max_tasks == 25
        assert config.timeout == 10.0  # Default preserved


# =============================================================================
# TorConfig Tests
# =============================================================================


class TestTorConfigDefaults:
    """TorConfig default values."""

    def test_default_enabled(self):
        """Tor is disabled by default."""
        config = TorConfig()
        assert config.enabled is False

    def test_default_proxy_url(self):
        """Tor has Docker hostname proxy by default."""
        config = TorConfig()
        assert config.proxy_url == "socks5://tor:9050"

    def test_default_max_tasks(self):
        """Tor has 10 max_tasks by default (lower than clearnet)."""
        config = TorConfig()
        assert config.max_tasks == 10

    def test_default_timeout(self):
        """Tor has 30.0s timeout by default (longer than clearnet)."""
        config = TorConfig()
        assert config.timeout == 30.0


class TestTorConfigPartialOverride:
    """TorConfig partial YAML override behavior."""

    def test_partial_override_inherits_proxy_url(self):
        """Key test: partial YAML override inherits proxy_url default."""
        config = TorConfig(enabled=True)
        assert config.enabled is True
        assert config.proxy_url == "socks5://tor:9050"  # Inherited from default

    def test_partial_override_inherits_timeout(self):
        """Partial override inherits timeout default."""
        config = TorConfig(enabled=True, max_tasks=20)
        assert config.timeout == 30.0  # Inherited from default


class TestTorConfigCustomValues:
    """TorConfig with custom values."""

    def test_all_custom_values(self):
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
    """I2pConfig default values."""

    def test_default_enabled(self):
        """I2P is disabled by default."""
        config = I2pConfig()
        assert config.enabled is False

    def test_default_proxy_url(self):
        """I2P has Docker hostname proxy by default."""
        config = I2pConfig()
        assert config.proxy_url == "socks5://i2p:4447"

    def test_default_max_tasks(self):
        """I2P has 5 max_tasks by default (lowest)."""
        config = I2pConfig()
        assert config.max_tasks == 5

    def test_default_timeout(self):
        """I2P has 45.0s timeout by default (longest)."""
        config = I2pConfig()
        assert config.timeout == 45.0


class TestI2pConfigCustomValues:
    """I2pConfig with custom values."""

    def test_partial_override_inherits_defaults(self):
        """Partial override inherits proxy_url and timeout defaults."""
        config = I2pConfig(enabled=True)
        assert config.enabled is True
        assert config.proxy_url == "socks5://i2p:4447"
        assert config.timeout == 45.0


# =============================================================================
# LokiConfig Tests
# =============================================================================


class TestLokiConfigDefaults:
    """LokiConfig default values."""

    def test_default_enabled(self):
        """Lokinet is disabled by default."""
        config = LokiConfig()
        assert config.enabled is False

    def test_default_proxy_url(self):
        """Lokinet has Docker hostname proxy by default."""
        config = LokiConfig()
        assert config.proxy_url == "socks5://lokinet:1080"

    def test_default_max_tasks(self):
        """Lokinet has 5 max_tasks by default."""
        config = LokiConfig()
        assert config.max_tasks == 5

    def test_default_timeout(self):
        """Lokinet has 30.0s timeout by default."""
        config = LokiConfig()
        assert config.timeout == 30.0


class TestLokiConfigCustomValues:
    """LokiConfig with custom values."""

    def test_partial_override_inherits_defaults(self):
        """Partial override inherits proxy_url default."""
        config = LokiConfig(enabled=True)
        assert config.enabled is True
        assert config.proxy_url == "socks5://lokinet:1080"


# =============================================================================
# Validation Tests (max_tasks and timeout constraints)
# =============================================================================


class TestMaxTasksValidation:
    """max_tasks validation constraints across all network configs."""

    def test_max_tasks_minimum_boundary(self):
        """max_tasks=1 is valid (minimum)."""
        config = ClearnetConfig(max_tasks=1)
        assert config.max_tasks == 1

    def test_max_tasks_maximum_boundary(self):
        """max_tasks=200 is valid (maximum)."""
        config = ClearnetConfig(max_tasks=200)
        assert config.max_tasks == 200

    def test_max_tasks_below_minimum_raises(self):
        """max_tasks=0 raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ClearnetConfig(max_tasks=0)
        assert "max_tasks" in str(exc_info.value).lower()

    def test_max_tasks_above_maximum_raises(self):
        """max_tasks=201 raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ClearnetConfig(max_tasks=201)
        assert "max_tasks" in str(exc_info.value).lower()

    def test_max_tasks_negative_raises(self):
        """max_tasks=-1 raises ValidationError."""
        with pytest.raises(ValidationError):
            ClearnetConfig(max_tasks=-1)

    @pytest.mark.parametrize(
        "config_class",
        [ClearnetConfig, TorConfig, I2pConfig, LokiConfig],
    )
    def test_validation_applies_to_all_network_types(self, config_class):
        """max_tasks validation applies to all network config classes."""
        with pytest.raises(ValidationError):
            config_class(max_tasks=0)
        with pytest.raises(ValidationError):
            config_class(max_tasks=201)


class TestTimeoutValidation:
    """timeout validation constraints across all network configs."""

    def test_timeout_minimum_boundary(self):
        """timeout=1.0 is valid (minimum)."""
        config = ClearnetConfig(timeout=1.0)
        assert config.timeout == 1.0

    def test_timeout_maximum_boundary(self):
        """timeout=120.0 is valid (maximum)."""
        config = ClearnetConfig(timeout=120.0)
        assert config.timeout == 120.0

    def test_timeout_below_minimum_raises(self):
        """timeout=0.5 raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ClearnetConfig(timeout=0.5)
        assert "timeout" in str(exc_info.value).lower()

    def test_timeout_above_maximum_raises(self):
        """timeout=121.0 raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ClearnetConfig(timeout=121.0)
        assert "timeout" in str(exc_info.value).lower()

    def test_timeout_zero_raises(self):
        """timeout=0.0 raises ValidationError."""
        with pytest.raises(ValidationError):
            ClearnetConfig(timeout=0.0)

    def test_timeout_negative_raises(self):
        """timeout=-1.0 raises ValidationError."""
        with pytest.raises(ValidationError):
            ClearnetConfig(timeout=-1.0)

    @pytest.mark.parametrize(
        "config_class",
        [ClearnetConfig, TorConfig, I2pConfig, LokiConfig],
    )
    def test_validation_applies_to_all_network_types(self, config_class):
        """timeout validation applies to all network config classes."""
        with pytest.raises(ValidationError):
            config_class(timeout=0.5)
        with pytest.raises(ValidationError):
            config_class(timeout=121.0)


# =============================================================================
# NetworkConfig Tests
# =============================================================================


class TestNetworkConfigDefaults:
    """NetworkConfig default values for all networks."""

    def test_clearnet_defaults(self):
        """Clearnet has correct defaults in NetworkConfig."""
        config = NetworkConfig()
        assert config.clearnet.enabled is True
        assert config.clearnet.proxy_url is None
        assert config.clearnet.max_tasks == 50
        assert config.clearnet.timeout == 10.0

    def test_tor_defaults(self):
        """Tor has correct defaults in NetworkConfig."""
        config = NetworkConfig()
        assert config.tor.enabled is False
        assert config.tor.proxy_url == "socks5://tor:9050"
        assert config.tor.max_tasks == 10
        assert config.tor.timeout == 30.0

    def test_i2p_defaults(self):
        """I2P has correct defaults in NetworkConfig."""
        config = NetworkConfig()
        assert config.i2p.enabled is False
        assert config.i2p.proxy_url == "socks5://i2p:4447"
        assert config.i2p.max_tasks == 5
        assert config.i2p.timeout == 45.0

    def test_loki_defaults(self):
        """Lokinet has correct defaults in NetworkConfig."""
        config = NetworkConfig()
        assert config.loki.enabled is False
        assert config.loki.proxy_url == "socks5://lokinet:1080"
        assert config.loki.max_tasks == 5
        assert config.loki.timeout == 30.0


class TestNetworkConfigCustomValues:
    """NetworkConfig with custom network configurations."""

    def test_custom_clearnet(self):
        """Custom clearnet config with defaults for other networks."""
        config = NetworkConfig(clearnet=ClearnetConfig(max_tasks=100, timeout=5.0))
        assert config.clearnet.max_tasks == 100
        assert config.clearnet.timeout == 5.0
        # Other networks keep defaults
        assert config.tor.enabled is False
        assert config.i2p.max_tasks == 5

    def test_custom_tor(self):
        """Custom tor config with all fields."""
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
        """Multiple networks with custom configurations."""
        config = NetworkConfig(
            clearnet=ClearnetConfig(max_tasks=100),
            tor=TorConfig(enabled=True),
            i2p=I2pConfig(enabled=True, timeout=60.0),
        )
        assert config.clearnet.max_tasks == 100
        assert config.tor.enabled is True
        assert config.tor.proxy_url == "socks5://tor:9050"  # Default inherited
        assert config.i2p.enabled is True
        assert config.i2p.timeout == 60.0
        assert config.loki.enabled is False  # Default

    def test_all_networks_enabled(self):
        """All networks can be enabled simultaneously."""
        config = NetworkConfig(
            clearnet=ClearnetConfig(enabled=True),
            tor=TorConfig(enabled=True),
            i2p=I2pConfig(enabled=True),
            loki=LokiConfig(enabled=True),
        )
        assert config.clearnet.enabled is True
        assert config.tor.enabled is True
        assert config.i2p.enabled is True
        assert config.loki.enabled is True


class TestNetworkConfigGet:
    """NetworkConfig.get() method."""

    def test_get_clearnet(self):
        """get() returns clearnet config."""
        config = NetworkConfig()
        result = config.get(NetworkType.CLEARNET)
        assert result is config.clearnet

    def test_get_tor(self):
        """get() returns tor config."""
        config = NetworkConfig()
        result = config.get(NetworkType.TOR)
        assert result is config.tor

    def test_get_i2p(self):
        """get() returns i2p config."""
        config = NetworkConfig()
        result = config.get(NetworkType.I2P)
        assert result is config.i2p

    def test_get_loki(self):
        """get() returns loki config."""
        config = NetworkConfig()
        result = config.get(NetworkType.LOKI)
        assert result is config.loki

    def test_get_returns_correct_custom_config(self):
        """get() returns the custom config when set."""
        config = NetworkConfig(tor=TorConfig(max_tasks=99, timeout=99.0))
        result = config.get(NetworkType.TOR)
        assert result.max_tasks == 99
        assert result.timeout == 99.0

    def test_get_result_is_network_type_config(self):
        """get() returns NetworkTypeConfig type."""
        config = NetworkConfig()
        for network_type in NetworkType:
            result = config.get(network_type)
            assert isinstance(result, (ClearnetConfig, TorConfig, I2pConfig, LokiConfig))


class TestNetworkConfigGetProxyUrl:
    """NetworkConfig.get_proxy_url() method."""

    def test_clearnet_always_none(self):
        """Clearnet proxy is always None regardless of config."""
        config = NetworkConfig(clearnet=ClearnetConfig(proxy_url="socks5://test:1234"))
        assert config.get_proxy_url(NetworkType.CLEARNET) is None

    def test_clearnet_string_always_none(self):
        """Clearnet proxy is None when using string network type."""
        config = NetworkConfig()
        assert config.get_proxy_url("clearnet") is None

    def test_tor_enabled_returns_proxy(self):
        """Tor proxy is returned when enabled."""
        config = NetworkConfig(tor=TorConfig(enabled=True, proxy_url="socks5://tor:9050"))
        assert config.get_proxy_url(NetworkType.TOR) == "socks5://tor:9050"

    def test_tor_disabled_returns_none(self):
        """Tor proxy is None when disabled."""
        config = NetworkConfig(tor=TorConfig(enabled=False, proxy_url="socks5://tor:9050"))
        assert config.get_proxy_url(NetworkType.TOR) is None

    def test_accepts_string_network(self):
        """get_proxy_url() accepts string network type."""
        config = NetworkConfig(tor=TorConfig(enabled=True, proxy_url="socks5://tor:9050"))
        assert config.get_proxy_url("tor") == "socks5://tor:9050"

    def test_invalid_string_network_returns_none(self):
        """Invalid string network type returns None."""
        config = NetworkConfig()
        assert config.get_proxy_url("invalid_network") is None

    def test_i2p_enabled_returns_proxy(self):
        """I2P proxy is returned when enabled."""
        config = NetworkConfig(i2p=I2pConfig(enabled=True, proxy_url="socks5://i2p:4447"))
        assert config.get_proxy_url(NetworkType.I2P) == "socks5://i2p:4447"

    def test_loki_enabled_returns_proxy(self):
        """Lokinet proxy is returned when enabled."""
        config = NetworkConfig(loki=LokiConfig(enabled=True, proxy_url="socks5://lokinet:1080"))
        assert config.get_proxy_url(NetworkType.LOKI) == "socks5://lokinet:1080"

    def test_custom_proxy_url_returned(self):
        """Custom proxy URL is returned when enabled."""
        config = NetworkConfig(tor=TorConfig(enabled=True, proxy_url="socks5://custom:5555"))
        assert config.get_proxy_url(NetworkType.TOR) == "socks5://custom:5555"


class TestNetworkConfigIsEnabled:
    """NetworkConfig.is_enabled() method."""

    def test_clearnet_enabled_by_default(self):
        """Clearnet is enabled by default."""
        config = NetworkConfig()
        assert config.is_enabled(NetworkType.CLEARNET) is True

    def test_tor_disabled_by_default(self):
        """Tor is disabled by default."""
        config = NetworkConfig()
        assert config.is_enabled(NetworkType.TOR) is False

    def test_i2p_disabled_by_default(self):
        """I2P is disabled by default."""
        config = NetworkConfig()
        assert config.is_enabled(NetworkType.I2P) is False

    def test_loki_disabled_by_default(self):
        """Lokinet is disabled by default."""
        config = NetworkConfig()
        assert config.is_enabled(NetworkType.LOKI) is False

    def test_accepts_string_network(self):
        """is_enabled() accepts string network type."""
        config = NetworkConfig()
        assert config.is_enabled("clearnet") is True
        assert config.is_enabled("tor") is False

    def test_invalid_string_returns_false(self):
        """Invalid string network type returns False."""
        config = NetworkConfig()
        assert config.is_enabled("invalid_network") is False

    def test_custom_enabled_state(self):
        """Custom enabled state is respected."""
        config = NetworkConfig(
            clearnet=ClearnetConfig(enabled=False),
            tor=TorConfig(enabled=True),
        )
        assert config.is_enabled(NetworkType.CLEARNET) is False
        assert config.is_enabled(NetworkType.TOR) is True


class TestNetworkConfigGetEnabledNetworks:
    """NetworkConfig.get_enabled_networks() method."""

    def test_default_only_clearnet(self):
        """Default config has only clearnet enabled."""
        config = NetworkConfig()
        enabled = config.get_enabled_networks()
        assert enabled == ["clearnet"]

    def test_multiple_enabled(self):
        """Multiple enabled networks are returned."""
        config = NetworkConfig(
            clearnet=ClearnetConfig(enabled=True),
            tor=TorConfig(enabled=True),
            i2p=I2pConfig(enabled=True),
            loki=LokiConfig(enabled=False),
        )
        enabled = config.get_enabled_networks()
        assert enabled == ["clearnet", "tor", "i2p"]

    def test_all_enabled(self):
        """All enabled networks are returned."""
        config = NetworkConfig(
            clearnet=ClearnetConfig(enabled=True),
            tor=TorConfig(enabled=True),
            i2p=I2pConfig(enabled=True),
            loki=LokiConfig(enabled=True),
        )
        enabled = config.get_enabled_networks()
        assert enabled == ["clearnet", "tor", "i2p", "loki"]

    def test_none_enabled(self):
        """Empty list when no networks enabled."""
        config = NetworkConfig(
            clearnet=ClearnetConfig(enabled=False),
            tor=TorConfig(enabled=False),
            i2p=I2pConfig(enabled=False),
            loki=LokiConfig(enabled=False),
        )
        enabled = config.get_enabled_networks()
        assert enabled == []

    def test_returns_list_in_field_definition_order(self):
        """Order matches field definition in NetworkConfig."""
        config = NetworkConfig(
            clearnet=ClearnetConfig(enabled=True),
            tor=TorConfig(enabled=True),
            i2p=I2pConfig(enabled=True),
            loki=LokiConfig(enabled=True),
        )
        enabled = config.get_enabled_networks()
        # Order should be: clearnet, tor, i2p, loki (as defined in model)
        assert enabled == ["clearnet", "tor", "i2p", "loki"]


# =============================================================================
# NetworkTypeConfig Type Alias Tests
# =============================================================================


class TestNetworkTypeConfigAlias:
    """NetworkTypeConfig type alias."""

    def test_clearnet_is_network_type_config(self):
        """ClearnetConfig is a NetworkTypeConfig."""
        config: NetworkTypeConfig = ClearnetConfig()
        assert isinstance(config, ClearnetConfig)

    def test_tor_is_network_type_config(self):
        """TorConfig is a NetworkTypeConfig."""
        config: NetworkTypeConfig = TorConfig()
        assert isinstance(config, TorConfig)

    def test_i2p_is_network_type_config(self):
        """I2pConfig is a NetworkTypeConfig."""
        config: NetworkTypeConfig = I2pConfig()
        assert isinstance(config, I2pConfig)

    def test_loki_is_network_type_config(self):
        """LokiConfig is a NetworkTypeConfig."""
        config: NetworkTypeConfig = LokiConfig()
        assert isinstance(config, LokiConfig)


# =============================================================================
# NetworkConfig YAML-like Construction Tests
# =============================================================================


class TestNetworkConfigYamlConstruction:
    """NetworkConfig construction from dict (simulating YAML loading)."""

    def test_from_dict_partial_tor(self):
        """Construct from dict with partial tor config (simulates YAML)."""
        # This simulates: networks.tor.enabled: true in YAML
        config = NetworkConfig(tor=TorConfig.model_validate({"enabled": True}))
        assert config.tor.enabled is True
        assert config.tor.proxy_url == "socks5://tor:9050"  # Default preserved

    def test_from_nested_dict(self):
        """Construct from fully nested dict structure."""
        data = {
            "clearnet": {"max_tasks": 100},
            "tor": {"enabled": True},
        }
        config = NetworkConfig.model_validate(data)
        assert config.clearnet.max_tasks == 100
        assert config.tor.enabled is True
        assert config.tor.proxy_url == "socks5://tor:9050"  # Default

    def test_empty_dict_uses_all_defaults(self):
        """Empty dict uses all default values."""
        config = NetworkConfig.model_validate({})
        assert config.clearnet.enabled is True
        assert config.tor.enabled is False
        assert config.i2p.enabled is False
        assert config.loki.enabled is False
