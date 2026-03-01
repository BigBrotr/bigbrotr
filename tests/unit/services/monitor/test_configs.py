"""Unit tests for services.monitor.configs module.

Tests:
- MetadataFlags: defaults, custom values, get_missing_from
- ProcessingConfig: defaults, custom, bounds
- RetryConfig / RetriesConfig: defaults and constraints
- GeoConfig: paths, staleness defaults, empty paths rejected
- PublishingConfig: defaults, custom, single relay, upper bound
- DiscoveryConfig: defaults, custom, interval validation, upper bound
- AnnouncementConfig: defaults, custom, upper bound
- ProfileConfig: defaults, custom, upper bound
- MonitorConfig: geo disabled, store validation, networks, interval
- MonitorConfig validators: validate_geo_databases, validate_store_requires_compute,
  validate_publish_requires_compute
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from bigbrotr.services.common.configs import ClearnetConfig, NetworksConfig, TorConfig
from bigbrotr.services.monitor import (
    AnnouncementConfig,
    DiscoveryConfig,
    GeoConfig,
    MetadataFlags,
    MonitorConfig,
    ProcessingConfig,
    ProfileConfig,
    PublishingConfig,
)
from bigbrotr.services.monitor.configs import RetriesConfig, RetryConfig


if TYPE_CHECKING:
    from pathlib import Path


# ============================================================================
# MetadataFlags Tests
# ============================================================================


class TestMetadataFlags:
    """Tests for MetadataFlags Pydantic model."""

    def test_default_values(self) -> None:
        """Test all flags enabled by default."""
        flags = MetadataFlags()

        assert flags.nip11_info is True
        assert flags.nip66_rtt is True
        assert flags.nip66_ssl is True
        assert flags.nip66_geo is True
        assert flags.nip66_net is True
        assert flags.nip66_dns is True
        assert flags.nip66_http is True

    def test_disable_flags(self) -> None:
        """Test disabling specific flags."""
        flags = MetadataFlags(nip66_geo=False, nip66_net=False)

        assert flags.nip66_geo is False
        assert flags.nip66_net is False
        assert flags.nip66_rtt is True

    def test_all_flags_disabled(self) -> None:
        """Test disabling all flags."""
        flags = MetadataFlags(
            nip11_info=False,
            nip66_rtt=False,
            nip66_ssl=False,
            nip66_geo=False,
            nip66_net=False,
            nip66_dns=False,
            nip66_http=False,
        )

        assert flags.nip11_info is False
        assert flags.nip66_rtt is False
        assert flags.nip66_ssl is False
        assert flags.nip66_geo is False
        assert flags.nip66_net is False
        assert flags.nip66_dns is False
        assert flags.nip66_http is False

    def test_default_all_true(self) -> None:
        """Test all flags default to True."""
        flags = MetadataFlags()

        assert flags.nip11_info is True
        assert flags.nip66_rtt is True
        assert flags.nip66_ssl is True
        assert flags.nip66_geo is True
        assert flags.nip66_net is True
        assert flags.nip66_dns is True
        assert flags.nip66_http is True

    def test_custom_values(self) -> None:
        """Test custom flag values."""
        flags = MetadataFlags(nip66_geo=False, nip66_net=False)

        assert flags.nip11_info is True
        assert flags.nip66_geo is False
        assert flags.nip66_net is False

    def test_get_missing_from_no_missing(self) -> None:
        """Test get_missing_from returns empty when superset covers all."""
        subset = MetadataFlags(nip66_geo=True, nip66_net=True)
        superset = MetadataFlags()

        assert subset.get_missing_from(superset) == []

    def test_get_missing_from_some_missing(self) -> None:
        """Test get_missing_from returns fields enabled in self but not superset."""
        subset = MetadataFlags(nip66_geo=True, nip66_net=True)
        superset = MetadataFlags(nip66_geo=False, nip66_net=False)

        missing = subset.get_missing_from(superset)
        assert "nip66_geo" in missing
        assert "nip66_net" in missing

    def test_get_missing_from_all_disabled(self) -> None:
        """Test get_missing_from when self has all flags disabled."""
        subset = MetadataFlags(
            nip11_info=False,
            nip66_rtt=False,
            nip66_ssl=False,
            nip66_geo=False,
            nip66_net=False,
            nip66_dns=False,
            nip66_http=False,
        )
        superset = MetadataFlags()

        assert subset.get_missing_from(superset) == []


# ============================================================================
# ProcessingConfig Tests
# ============================================================================


class TestProcessingConfig:
    """Tests for ProcessingConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default processing config."""
        config = ProcessingConfig()

        assert config.chunk_size == 100
        assert config.nip11_info_max_size == 1048576
        assert config.compute.nip11_info is True
        assert config.store.nip11_info is True

    def test_custom_values(self) -> None:
        """Test custom processing config."""
        config = ProcessingConfig(
            chunk_size=50,
            compute=MetadataFlags(nip66_geo=False),
            store=MetadataFlags(nip66_geo=False),
        )

        assert config.chunk_size == 50
        assert config.compute.nip66_geo is False
        assert config.store.nip66_geo is False

    def test_chunk_size_bounds(self) -> None:
        """Test chunk_size validation bounds."""
        # Valid values
        config_min = ProcessingConfig(chunk_size=10)
        assert config_min.chunk_size == 10

        config_max = ProcessingConfig(chunk_size=1000)
        assert config_max.chunk_size == 1000

    def test_nip11_info_max_size_custom(self) -> None:
        """Test custom NIP-11 info max size."""
        config = ProcessingConfig(nip11_info_max_size=2097152)  # 2MB
        assert config.nip11_info_max_size == 2097152


# ============================================================================
# RetryConfig Tests
# ============================================================================


class TestRetryConfig:
    """Tests for RetryConfig Pydantic model."""

    def test_defaults(self) -> None:
        """Test default retry settings."""
        config = RetryConfig()

        assert config.max_attempts == 0
        assert config.initial_delay == 1.0
        assert config.max_delay == 10.0
        assert config.jitter == 0.5

    def test_custom_values(self) -> None:
        """Test custom retry settings."""
        config = RetryConfig(max_attempts=3, initial_delay=2.0, max_delay=30.0, jitter=1.0)

        assert config.max_attempts == 3
        assert config.initial_delay == 2.0
        assert config.max_delay == 30.0
        assert config.jitter == 1.0

    def test_constraint_max_attempts(self) -> None:
        """Test max_attempts within bounds."""
        with pytest.raises(ValueError):
            RetryConfig(max_attempts=-1)
        with pytest.raises(ValueError):
            RetryConfig(max_attempts=11)

    def test_max_delay_less_than_initial_rejected(self) -> None:
        """Test that max_delay < initial_delay is rejected."""
        with pytest.raises(ValueError, match="max_delay"):
            RetryConfig(initial_delay=5.0, max_delay=2.0)

    def test_max_delay_equals_initial_accepted(self) -> None:
        """Test that max_delay == initial_delay is accepted."""
        config = RetryConfig(initial_delay=5.0, max_delay=5.0)
        assert config.max_delay == 5.0


# ============================================================================
# RetriesConfig Tests
# ============================================================================


class TestRetriesConfig:
    """Tests for RetriesConfig Pydantic model."""

    def test_defaults(self) -> None:
        """Test all retry types get default RetryConfig."""
        config = RetriesConfig()

        assert config.nip11_info.max_attempts == 0
        assert config.nip66_rtt.max_attempts == 0
        assert config.nip66_ssl.max_attempts == 0
        assert config.nip66_geo.max_attempts == 0
        assert config.nip66_net.max_attempts == 0
        assert config.nip66_dns.max_attempts == 0
        assert config.nip66_http.max_attempts == 0


# ============================================================================
# GeoConfig Tests
# ============================================================================


class TestGeoConfig:
    """Tests for GeoConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default geo config."""
        config = GeoConfig()

        assert config.city_database_path == "static/GeoLite2-City.mmdb"
        assert config.asn_database_path == "static/GeoLite2-ASN.mmdb"
        assert config.max_age_days == 30

    def test_custom_paths(self) -> None:
        """Test custom database paths with max_age_days override."""
        config = GeoConfig(
            city_database_path="/custom/path/city.mmdb",
            asn_database_path="/custom/path/asn.mmdb",
            max_age_days=7,
        )

        assert config.city_database_path == "/custom/path/city.mmdb"
        assert config.asn_database_path == "/custom/path/asn.mmdb"
        assert config.max_age_days == 7

    def test_max_age_days_validation(self) -> None:
        """Test max_age_days can be set to various values."""
        config = GeoConfig(max_age_days=1)
        assert config.max_age_days == 1

        config2 = GeoConfig(max_age_days=365)
        assert config2.max_age_days == 365

    def test_defaults_extended(self) -> None:
        """Test default GeoConfig values including download size and precision."""
        config = GeoConfig()

        assert config.city_database_path == "static/GeoLite2-City.mmdb"
        assert config.asn_database_path == "static/GeoLite2-ASN.mmdb"
        assert config.max_age_days == 30
        assert config.max_download_size == 100_000_000
        assert config.geohash_precision == 9

    def test_custom_database_paths(self) -> None:
        """Test custom database paths without max_age_days override."""
        config = GeoConfig(
            city_database_path="/custom/city.mmdb",
            asn_database_path="/custom/asn.mmdb",
        )

        assert config.city_database_path == "/custom/city.mmdb"
        assert config.asn_database_path == "/custom/asn.mmdb"

    def test_max_age_none(self) -> None:
        """Test max_age_days can be None (never stale)."""
        config = GeoConfig(max_age_days=None)
        assert config.max_age_days is None

    def test_empty_city_path_rejected(self) -> None:
        """Test that empty city_database_path is rejected."""
        with pytest.raises(ValueError):
            GeoConfig(city_database_path="")

    def test_empty_asn_path_rejected(self) -> None:
        """Test that empty asn_database_path is rejected."""
        with pytest.raises(ValueError):
            GeoConfig(asn_database_path="")


# ============================================================================
# PublishingConfig Tests
# ============================================================================


class TestPublishingConfig:
    """Tests for PublishingConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default publishing config."""
        config = PublishingConfig()

        assert config.relays == []

    def test_custom_values(self) -> None:
        """Test custom publishing config."""
        config = PublishingConfig(relays=["wss://relay1.com", "wss://relay2.com"])

        assert len(config.relays) == 2
        assert config.relays[0].url == "wss://relay1.com"
        assert config.relays[1].url == "wss://relay2.com"

    def test_single_relay(self) -> None:
        """Test publishing config with single relay."""
        config = PublishingConfig(relays=["wss://single.relay.com"])
        assert len(config.relays) == 1

    def test_timeout_upper_bound_rejected(self) -> None:
        """Timeout above 300s is rejected."""
        with pytest.raises(ValueError):
            PublishingConfig(timeout=301.0)


# ============================================================================
# DiscoveryConfig Tests
# ============================================================================


class TestDiscoveryConfig:
    """Tests for DiscoveryConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default discovery config."""
        config = DiscoveryConfig()

        assert config.enabled is True
        assert config.interval == 3600
        assert config.include.nip11_info is True
        assert config.relays is None

    def test_custom_values(self) -> None:
        """Test custom discovery config."""
        config = DiscoveryConfig(
            enabled=False,
            interval=7200,
            include=MetadataFlags(nip66_http=False),
            relays=["wss://relay1.com"],
        )

        assert config.enabled is False
        assert config.interval == 7200
        assert config.include.nip66_http is False
        assert len(config.relays) == 1

    def test_interval_validation(self) -> None:
        """Test interval can be set to various values."""
        config = DiscoveryConfig(interval=60)
        assert config.interval == 60

        config2 = DiscoveryConfig(interval=86400)
        assert config2.interval == 86400

    def test_interval_upper_bound_rejected(self) -> None:
        """Interval above 7 days is rejected."""
        with pytest.raises(ValueError):
            DiscoveryConfig(interval=604801.0)


# ============================================================================
# AnnouncementConfig Tests
# ============================================================================


class TestAnnouncementConfig:
    """Tests for AnnouncementConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default announcement config."""
        config = AnnouncementConfig()

        assert config.enabled is True
        assert config.interval == 86400
        assert config.relays is None

    def test_custom_values(self) -> None:
        """Test custom announcement config."""
        config = AnnouncementConfig(
            enabled=False,
            interval=3600,
            relays=["wss://relay.com"],
        )

        assert config.enabled is False
        assert config.interval == 3600
        assert len(config.relays) == 1

    def test_interval_upper_bound_rejected(self) -> None:
        """Interval above 7 days is rejected."""
        with pytest.raises(ValueError):
            AnnouncementConfig(interval=604801.0)


# ============================================================================
# ProfileConfig Tests
# ============================================================================


class TestProfileConfig:
    """Tests for ProfileConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default profile config."""
        config = ProfileConfig()

        assert config.enabled is False
        assert config.interval == 86400
        assert config.relays is None

    def test_custom_values(self) -> None:
        """Test custom profile config."""
        config = ProfileConfig(
            enabled=True,
            interval=43200,
            relays=["wss://profile.relay.com"],
        )

        assert config.enabled is True
        assert config.interval == 43200
        assert len(config.relays) == 1

    def test_interval_upper_bound_rejected(self) -> None:
        """Interval above 7 days is rejected."""
        with pytest.raises(ValueError):
            ProfileConfig(interval=604801.0)


# ============================================================================
# MonitorConfig Tests
# ============================================================================


class TestMonitorConfig:
    """Tests for MonitorConfig Pydantic model."""

    def test_default_values_with_geo_disabled(self, tmp_path: Path) -> None:
        """Test default configuration with geo/net disabled (no database needed)."""
        config = MonitorConfig(
            processing=ProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            discovery=DiscoveryConfig(
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
        )

        assert config.networks.clearnet.enabled is True
        assert config.networks.tor.enabled is False
        assert config.processing.compute.nip66_geo is False
        assert config.processing.compute.nip66_net is False

    def test_store_requires_compute_validation(self, tmp_path: Path) -> None:
        """Test that storing requires computing."""
        with pytest.raises(ValueError, match="Cannot store metadata that is not computed"):
            MonitorConfig(
                processing=ProcessingConfig(
                    compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                    store=MetadataFlags(
                        nip66_geo=True, nip66_net=False
                    ),  # geo store without compute
                ),
                discovery=DiscoveryConfig(
                    include=MetadataFlags(nip66_geo=False, nip66_net=False),
                ),
            )

    def test_networks_config(self) -> None:
        """Test networks configuration."""
        config = MonitorConfig(
            processing=ProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            discovery=DiscoveryConfig(
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            networks=NetworksConfig(
                clearnet=ClearnetConfig(timeout=5.0),
                tor=TorConfig(enabled=True, timeout=30.0),
            ),
        )

        assert config.networks.clearnet.timeout == 5.0
        assert config.networks.tor.enabled is True
        assert config.networks.tor.timeout == 30.0

    def test_interval_config(self) -> None:
        """Test interval configuration from base service config."""
        config = MonitorConfig(
            interval=600.0,
            processing=ProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            discovery=DiscoveryConfig(
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
        )

        assert config.interval == 600.0


# ============================================================================
# MonitorConfig Validator Tests
# ============================================================================


class TestMonitorConfigValidateGeoDatabases:
    """Tests for MonitorConfig.validate_geo_databases validator."""

    def test_valid_with_download_url(self) -> None:
        """Test no error when geo databases have download URLs."""
        # Default config has download URLs, so geo validation passes
        config = MonitorConfig()
        assert config.geo.city_download_url != ""
        assert config.geo.asn_download_url != ""

    def test_geo_missing_city_no_url_raises(self) -> None:
        """Test error when city DB missing and no download URL."""
        with (
            patch("bigbrotr.services.monitor.configs.Path.exists", return_value=False),
            pytest.raises(ValueError, match="GeoLite2 City database not found"),
        ):
            MonitorConfig(geo=GeoConfig(city_download_url=""))

    def test_geo_missing_asn_no_url_raises(self) -> None:
        """Test error when ASN DB missing and no download URL."""
        with (
            patch("bigbrotr.services.monitor.configs.Path.exists", return_value=False),
            pytest.raises(ValueError, match="GeoLite2 ASN database not found"),
        ):
            MonitorConfig(geo=GeoConfig(asn_download_url=""))

    def test_geo_check_skipped_when_compute_disabled(self) -> None:
        """Test geo validation is skipped when compute flags are disabled."""
        config = MonitorConfig(
            processing=ProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            discovery=DiscoveryConfig(
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            geo=GeoConfig(city_download_url="", asn_download_url=""),
        )
        assert config.processing.compute.nip66_geo is False


class TestMonitorConfigValidateStoreRequiresCompute:
    """Tests for MonitorConfig.validate_store_requires_compute validator."""

    def test_valid_store_subset_of_compute(self) -> None:
        """Test no error when stored flags are a subset of computed flags."""
        config = MonitorConfig(
            processing=ProcessingConfig(
                compute=MetadataFlags(),
                store=MetadataFlags(nip66_geo=False),
            ),
        )
        assert config.processing.store.nip66_geo is False

    def test_store_without_compute_raises(self) -> None:
        """Test error when trying to store metadata that isn't computed."""
        with pytest.raises(ValueError, match="Cannot store metadata that is not computed"):
            MonitorConfig(
                processing=ProcessingConfig(
                    compute=MetadataFlags(nip66_geo=False),
                    store=MetadataFlags(nip66_geo=True),
                ),
            )

    def test_multiple_store_without_compute_raises(self) -> None:
        """Test error message includes all invalid fields."""
        with pytest.raises(ValueError, match=r"nip66_geo.*nip66_net|nip66_net.*nip66_geo"):
            MonitorConfig(
                processing=ProcessingConfig(
                    compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                    store=MetadataFlags(nip66_geo=True, nip66_net=True),
                ),
            )


class TestMonitorConfigValidatePublishRequiresCompute:
    """Tests for MonitorConfig.validate_publish_requires_compute validator."""

    def test_valid_publish_subset_of_compute(self) -> None:
        """Test no error when published flags are a subset of computed flags."""
        config = MonitorConfig(
            discovery=DiscoveryConfig(
                enabled=True,
                include=MetadataFlags(nip66_geo=False),
            ),
        )
        assert config.discovery.include.nip66_geo is False

    def test_publish_without_compute_raises(self) -> None:
        """Test error when trying to publish metadata that isn't computed."""
        with pytest.raises(ValueError, match="Cannot publish metadata that is not computed"):
            MonitorConfig(
                processing=ProcessingConfig(
                    compute=MetadataFlags(nip66_ssl=False),
                    store=MetadataFlags(nip66_ssl=False),
                ),
                discovery=DiscoveryConfig(
                    enabled=True,
                    include=MetadataFlags(nip66_ssl=True),
                ),
            )

    def test_publish_check_skipped_when_discovery_disabled(self) -> None:
        """Test publish validation is skipped when discovery is disabled."""
        config = MonitorConfig(
            processing=ProcessingConfig(
                compute=MetadataFlags(nip66_ssl=False),
                store=MetadataFlags(nip66_ssl=False),
            ),
            discovery=DiscoveryConfig(
                enabled=False,
                include=MetadataFlags(nip66_ssl=True),
            ),
        )
        assert config.discovery.enabled is False
