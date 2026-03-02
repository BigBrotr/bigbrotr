"""Unit tests for Validator configuration models."""

import pytest

from bigbrotr.models.constants import NetworkType
from bigbrotr.services.common.configs import (
    ClearnetConfig,
    I2pConfig,
    LokiConfig,
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
    """Tests for ProcessingConfig validation and defaults."""

    def test_defaults(self) -> None:
        cfg = ProcessingConfig()
        assert cfg.chunk_size == 1000
        assert cfg.max_candidates is None
        assert cfg.interval == 3600.0

    def test_chunk_size_minimum(self) -> None:
        cfg = ProcessingConfig(chunk_size=100)
        assert cfg.chunk_size == 100

    def test_chunk_size_maximum(self) -> None:
        cfg = ProcessingConfig(chunk_size=10000)
        assert cfg.chunk_size == 10000

    def test_chunk_size_below_minimum_rejected(self) -> None:
        with pytest.raises(ValueError):
            ProcessingConfig(chunk_size=99)

    def test_chunk_size_above_maximum_rejected(self) -> None:
        with pytest.raises(ValueError):
            ProcessingConfig(chunk_size=10001)

    def test_max_candidates_none(self) -> None:
        cfg = ProcessingConfig(max_candidates=None)
        assert cfg.max_candidates is None

    def test_max_candidates_minimum(self) -> None:
        cfg = ProcessingConfig(max_candidates=1)
        assert cfg.max_candidates == 1

    def test_max_candidates_zero_rejected(self) -> None:
        with pytest.raises(ValueError):
            ProcessingConfig(max_candidates=0)

    def test_interval_zero(self) -> None:
        cfg = ProcessingConfig(interval=0.0)
        assert cfg.interval == 0.0

    def test_interval_maximum(self) -> None:
        cfg = ProcessingConfig(interval=604_800.0)
        assert cfg.interval == 604_800.0

    def test_interval_above_maximum_rejected(self) -> None:
        with pytest.raises(ValueError):
            ProcessingConfig(interval=604_801.0)


# ============================================================================
# CleanupConfig Tests
# ============================================================================


class TestCleanupConfig:
    """Tests for CleanupConfig validation and defaults."""

    def test_defaults(self) -> None:
        cfg = CleanupConfig()
        assert cfg.enabled is False
        assert cfg.max_failures == 720

    def test_enabled_true(self) -> None:
        cfg = CleanupConfig(enabled=True)
        assert cfg.enabled is True

    def test_max_failures_minimum(self) -> None:
        cfg = CleanupConfig(max_failures=1)
        assert cfg.max_failures == 1

    def test_max_failures_zero_rejected(self) -> None:
        with pytest.raises(ValueError):
            CleanupConfig(max_failures=0)

    def test_custom_values(self) -> None:
        cfg = CleanupConfig(enabled=True, max_failures=100)
        assert cfg.enabled is True
        assert cfg.max_failures == 100


# ============================================================================
# ValidatorConfig Tests
# ============================================================================


class TestValidatorConfig:
    """Tests for ValidatorConfig and inherited BaseServiceConfig fields."""

    def test_defaults(self) -> None:
        cfg = ValidatorConfig()
        assert cfg.interval == 300.0
        assert cfg.max_consecutive_failures == 5
        assert isinstance(cfg.networks, NetworksConfig)
        assert isinstance(cfg.processing, ProcessingConfig)
        assert isinstance(cfg.cleanup, CleanupConfig)

    def test_interval_minimum(self) -> None:
        cfg = ValidatorConfig(interval=60.0)
        assert cfg.interval == 60.0

    def test_interval_below_minimum_rejected(self) -> None:
        with pytest.raises(ValueError):
            ValidatorConfig(interval=59.9)

    def test_max_consecutive_failures_zero(self) -> None:
        cfg = ValidatorConfig(max_consecutive_failures=0)
        assert cfg.max_consecutive_failures == 0

    def test_max_consecutive_failures_above_maximum_rejected(self) -> None:
        with pytest.raises(ValueError):
            ValidatorConfig(max_consecutive_failures=101)

    def test_nested_processing_via_dict(self) -> None:
        cfg = ValidatorConfig(processing={"chunk_size": 200, "max_candidates": 5000})
        assert cfg.processing.chunk_size == 200
        assert cfg.processing.max_candidates == 5000

    def test_nested_cleanup_via_dict(self) -> None:
        cfg = ValidatorConfig(cleanup={"enabled": True, "max_failures": 50})
        assert cfg.cleanup.enabled is True
        assert cfg.cleanup.max_failures == 50

    def test_nested_networks(self) -> None:
        cfg = ValidatorConfig(networks=NetworksConfig(tor=TorConfig(enabled=True)))
        assert cfg.networks.tor.enabled is True

    def test_processing_validation_propagated(self) -> None:
        with pytest.raises(ValueError):
            ValidatorConfig(processing={"chunk_size": 50})


# ============================================================================
# NetworksConfig Tests
# ============================================================================


class TestNetworksConfig:
    """Tests for NetworksConfig container and helper methods."""

    def test_defaults(self) -> None:
        cfg = NetworksConfig()
        assert cfg.clearnet.enabled is True
        assert cfg.tor.enabled is False
        assert cfg.i2p.enabled is False
        assert cfg.loki.enabled is False

    def test_get_enabled_networks_default(self) -> None:
        cfg = NetworksConfig()
        assert cfg.get_enabled_networks() == [NetworkType.CLEARNET]

    def test_get_enabled_networks_with_tor(self) -> None:
        cfg = NetworksConfig(tor=TorConfig(enabled=True))
        enabled = cfg.get_enabled_networks()
        assert NetworkType.CLEARNET in enabled
        assert NetworkType.TOR in enabled

    def test_get_enabled_networks_all_disabled(self) -> None:
        cfg = NetworksConfig(clearnet=ClearnetConfig(enabled=False))
        assert cfg.get_enabled_networks() == []

    def test_get_enabled_networks_all_enabled(self) -> None:
        cfg = NetworksConfig(
            clearnet=ClearnetConfig(enabled=True),
            tor=TorConfig(enabled=True),
            i2p=I2pConfig(enabled=True),
            loki=LokiConfig(enabled=True),
        )
        assert len(cfg.get_enabled_networks()) == 4

    def test_get_returns_correct_config(self) -> None:
        cfg = NetworksConfig(clearnet=ClearnetConfig(timeout=15.0))
        assert cfg.get(NetworkType.CLEARNET).timeout == 15.0

    def test_get_proxy_url_clearnet_always_none(self) -> None:
        assert NetworksConfig().get_proxy_url(NetworkType.CLEARNET) is None

    def test_get_proxy_url_tor_when_enabled(self) -> None:
        cfg = NetworksConfig(tor=TorConfig(enabled=True, proxy_url="socks5://tor:9050"))
        assert cfg.get_proxy_url(NetworkType.TOR) == "socks5://tor:9050"

    def test_get_proxy_url_tor_when_disabled(self) -> None:
        assert NetworksConfig(tor=TorConfig(enabled=False)).get_proxy_url(NetworkType.TOR) is None

    def test_is_enabled_clearnet_default(self) -> None:
        assert NetworksConfig().is_enabled(NetworkType.CLEARNET) is True

    def test_is_enabled_tor_default(self) -> None:
        assert NetworksConfig().is_enabled(NetworkType.TOR) is False


# ============================================================================
# Per-Network Config Tests
# ============================================================================


class TestClearnetConfig:
    """Tests for ClearnetConfig defaults and field bounds."""

    def test_defaults(self) -> None:
        cfg = ClearnetConfig()
        assert cfg.enabled is True
        assert cfg.proxy_url is None
        assert cfg.max_tasks == 50
        assert cfg.timeout == 10.0

    def test_max_tasks_minimum(self) -> None:
        assert ClearnetConfig(max_tasks=1).max_tasks == 1

    def test_max_tasks_above_maximum_rejected(self) -> None:
        with pytest.raises(ValueError):
            ClearnetConfig(max_tasks=201)

    def test_timeout_minimum(self) -> None:
        assert ClearnetConfig(timeout=1.0).timeout == 1.0

    def test_timeout_above_maximum_rejected(self) -> None:
        with pytest.raises(ValueError):
            ClearnetConfig(timeout=121.0)


class TestTorConfig:
    """Tests for TorConfig defaults and proxy settings."""

    def test_defaults(self) -> None:
        cfg = TorConfig()
        assert cfg.enabled is False
        assert cfg.proxy_url == "socks5://tor:9050"
        assert cfg.max_tasks == 10
        assert cfg.timeout == 30.0

    def test_custom_proxy(self) -> None:
        assert TorConfig(proxy_url="socks5://localhost:9150").proxy_url == "socks5://localhost:9150"

    def test_proxy_can_be_none(self) -> None:
        assert TorConfig(proxy_url=None).proxy_url is None


class TestI2pConfig:
    """Tests for I2pConfig defaults."""

    def test_defaults(self) -> None:
        cfg = I2pConfig()
        assert cfg.enabled is False
        assert cfg.proxy_url == "socks5://i2p:4447"
        assert cfg.max_tasks == 5
        assert cfg.timeout == 45.0


class TestLokiConfig:
    """Tests for LokiConfig defaults."""

    def test_defaults(self) -> None:
        cfg = LokiConfig()
        assert cfg.enabled is False
        assert cfg.proxy_url == "socks5://lokinet:1080"
        assert cfg.max_tasks == 5
        assert cfg.timeout == 30.0
