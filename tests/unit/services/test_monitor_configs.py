"""
Unit tests for services.monitor.configs module.

Tests:
- MetadataFlags: defaults, custom values, get_missing_from
- RetryConfig / RetriesConfig: defaults and constraints
- GeoConfig: paths and staleness defaults
- MonitorConfig validators: validate_geo_databases, validate_store_requires_compute,
  validate_publish_requires_compute
"""

from unittest.mock import patch

import pytest

from bigbrotr.services.monitor.configs import (
    GeoConfig,
    MetadataFlags,
    MonitorConfig,
    ProcessingConfig,
    RetriesConfig,
    RetryConfig,
)


# Valid secp256k1 test key (DO NOT USE IN PRODUCTION)
VALID_HEX_KEY = (
    "67dea2ed018072d675f5415ecfaed7d2597555e202d85b3d65ea4e58d2d92ffa"  # pragma: allowlist secret
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def set_private_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set PRIVATE_KEY environment variable for Monitor config tests."""
    monkeypatch.setenv("PRIVATE_KEY", VALID_HEX_KEY)


# ============================================================================
# MetadataFlags Tests
# ============================================================================


class TestMetadataFlags:
    """Tests for MetadataFlags Pydantic model."""

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

    def test_defaults(self) -> None:
        """Test default GeoConfig values."""
        config = GeoConfig()

        assert config.city_database_path == "static/GeoLite2-City.mmdb"
        assert config.asn_database_path == "static/GeoLite2-ASN.mmdb"
        assert config.max_age_days == 30
        assert config.max_download_size == 100_000_000
        assert config.geohash_precision == 9

    def test_custom_paths(self) -> None:
        """Test custom database paths."""
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
        from bigbrotr.services.monitor.configs import DiscoveryConfig

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
        from bigbrotr.services.monitor.configs import DiscoveryConfig

        config = MonitorConfig(
            discovery=DiscoveryConfig(
                enabled=True,
                include=MetadataFlags(nip66_geo=False),
            ),
        )
        assert config.discovery.include.nip66_geo is False

    def test_publish_without_compute_raises(self) -> None:
        """Test error when trying to publish metadata that isn't computed."""
        from bigbrotr.services.monitor.configs import DiscoveryConfig

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
        from bigbrotr.services.monitor.configs import DiscoveryConfig

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
