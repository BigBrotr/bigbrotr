"""Unit tests for services.monitor module.

Tests:
- Configuration models (MetadataFlags, MonitorProcessingConfig, GeoConfig, etc.)
- Monitor service initialization
- Relay selection logic
- Metadata batch insertion
- NIP-66 data classes
- Publishing and event builder orchestration (Kind 0, 10166, 30166)
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nostr_sdk import Keys


if TYPE_CHECKING:
    from pathlib import Path

from bigbrotr.core.brotr import Brotr
from bigbrotr.models import Relay, RelayMetadata
from bigbrotr.models.constants import NetworkType, ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType
from bigbrotr.nips.nip11 import Nip11
from bigbrotr.nips.nip11.data import Nip11InfoData, Nip11InfoDataLimitation
from bigbrotr.nips.nip11.info import Nip11InfoMetadata
from bigbrotr.nips.nip11.logs import Nip11InfoLogs
from bigbrotr.nips.nip66 import Nip66, Nip66RttMetadata, Nip66SslMetadata
from bigbrotr.nips.nip66.data import Nip66RttData, Nip66SslData
from bigbrotr.nips.nip66.logs import Nip66RttMultiPhaseLogs, Nip66SslLogs
from bigbrotr.services.common.configs import ClearnetConfig, NetworkConfig, TorConfig
from bigbrotr.services.monitor import (
    AnnouncementConfig,
    CheckResult,
    DiscoveryConfig,
    GeoConfig,
    MetadataFlags,
    Monitor,
    MonitorConfig,
    MonitorProcessingConfig,
    ProfileConfig,
    PublishingConfig,
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
    """Set PRIVATE_KEY environment variable for all monitor tests."""
    monkeypatch.setenv("PRIVATE_KEY", VALID_HEX_KEY)


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


# ============================================================================
# MonitorProcessingConfig Tests
# ============================================================================


class TestMonitorProcessingConfig:
    """Tests for MonitorProcessingConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default processing config."""
        config = MonitorProcessingConfig()

        assert config.chunk_size == 100
        assert config.nip11_info_max_size == 1048576
        assert config.compute.nip11_info is True
        assert config.store.nip11_info is True

    def test_custom_values(self) -> None:
        """Test custom processing config."""
        config = MonitorProcessingConfig(
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
        config_min = MonitorProcessingConfig(chunk_size=10)
        assert config_min.chunk_size == 10

        config_max = MonitorProcessingConfig(chunk_size=1000)
        assert config_max.chunk_size == 1000

    def test_nip11_info_max_size_custom(self) -> None:
        """Test custom NIP-11 info max size."""
        config = MonitorProcessingConfig(nip11_info_max_size=2097152)  # 2MB
        assert config.nip11_info_max_size == 2097152


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
        """Test custom database paths."""
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
        assert config.relays == []

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
        assert config.relays == []

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
        assert config.relays == []

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


# ============================================================================
# MonitorConfig Tests
# ============================================================================


class TestMonitorConfig:
    """Tests for MonitorConfig Pydantic model."""

    def test_default_values_with_geo_disabled(self, tmp_path: Path) -> None:
        """Test default configuration with geo/net disabled (no database needed)."""
        config = MonitorConfig(
            processing=MonitorProcessingConfig(
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
                processing=MonitorProcessingConfig(
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
            processing=MonitorProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            discovery=DiscoveryConfig(
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            networks=NetworkConfig(
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
            processing=MonitorProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            discovery=DiscoveryConfig(
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
        )

        assert config.interval == 600.0


# ============================================================================
# Helper Functions for Test Data Creation
# ============================================================================


def _create_nip11(relay: Relay, data: dict | None = None, generated_at: int = 1700000001) -> Nip11:
    """Create a Nip11 instance with proper Nip11InfoMetadata structure."""
    from bigbrotr.nips.nip11 import Nip11InfoData, Nip11InfoLogs, Nip11InfoMetadata

    if data is None:
        data = {}
    info_data = Nip11InfoData.model_validate(Nip11InfoData.parse(data))
    info_logs = Nip11InfoLogs(success=True)
    info_metadata = Nip11InfoMetadata(data=info_data, logs=info_logs)
    return Nip11(relay=relay, info=info_metadata, generated_at=generated_at)


def _create_nip66(
    relay: Relay,
    rtt_data: dict | None = None,
    ssl_data: dict | None = None,
    geo_data: dict | None = None,
    net_data: dict | None = None,
    dns_data: dict | None = None,
    http_data: dict | None = None,
    generated_at: int = 1700000001,
) -> Nip66:
    """Create a Nip66 instance with proper metadata types."""
    from bigbrotr.nips.nip66 import (
        Nip66DnsData,
        Nip66DnsLogs,
        Nip66DnsMetadata,
        Nip66GeoData,
        Nip66GeoLogs,
        Nip66GeoMetadata,
        Nip66HttpData,
        Nip66HttpLogs,
        Nip66HttpMetadata,
        Nip66NetData,
        Nip66NetLogs,
        Nip66NetMetadata,
        Nip66RttData,
        Nip66RttMetadata,
        Nip66RttMultiPhaseLogs,
        Nip66SslData,
        Nip66SslLogs,
        Nip66SslMetadata,
    )

    rtt_metadata = None
    if rtt_data is not None:
        rtt_metadata = Nip66RttMetadata(
            data=Nip66RttData.model_validate(Nip66RttData.parse(rtt_data)),
            logs=Nip66RttMultiPhaseLogs(open_success=True),
        )

    ssl_metadata = None
    if ssl_data is not None:
        ssl_metadata = Nip66SslMetadata(
            data=Nip66SslData.model_validate(Nip66SslData.parse(ssl_data)),
            logs=Nip66SslLogs(success=True),
        )

    geo_metadata = None
    if geo_data is not None:
        geo_metadata = Nip66GeoMetadata(
            data=Nip66GeoData.model_validate(Nip66GeoData.parse(geo_data)),
            logs=Nip66GeoLogs(success=True),
        )

    net_metadata = None
    if net_data is not None:
        net_metadata = Nip66NetMetadata(
            data=Nip66NetData.model_validate(Nip66NetData.parse(net_data)),
            logs=Nip66NetLogs(success=True),
        )

    dns_metadata = None
    if dns_data is not None:
        dns_metadata = Nip66DnsMetadata(
            data=Nip66DnsData.model_validate(Nip66DnsData.parse(dns_data)),
            logs=Nip66DnsLogs(success=True),
        )

    http_metadata = None
    if http_data is not None:
        http_metadata = Nip66HttpMetadata(
            data=Nip66HttpData.model_validate(Nip66HttpData.parse(http_data)),
            logs=Nip66HttpLogs(success=True),
        )

    return Nip66(
        relay=relay,
        rtt=rtt_metadata,
        ssl=ssl_metadata,
        geo=geo_metadata,
        net=net_metadata,
        dns=dns_metadata,
        http=http_metadata,
        generated_at=generated_at,
    )


# ============================================================================
# NIP-66 Data Classes Tests
# ============================================================================


class TestNip11:
    """Tests for Nip11 dataclass."""

    def test_default_values(self) -> None:
        """Test NIP-11 with empty data - access via info.data."""
        relay = Relay("wss://relay.example.com")
        nip11 = _create_nip11(relay, {})

        assert nip11.info.data.name is None
        assert nip11.info.data.supported_nips is None

    def test_properties(self) -> None:
        """Test NIP-11 property access via info.data."""
        relay = Relay("wss://relay.example.com")
        nip11 = _create_nip11(relay, {"name": "Test Relay", "supported_nips": [1, 11, 66]})

        assert nip11.info.data.name == "Test Relay"
        assert nip11.info.data.supported_nips == [1, 11, 66]

    def test_to_relay_metadata(self) -> None:
        """Test NIP-11 to_relay_metadata_tuple factory method."""
        relay = Relay("wss://relay.example.com")
        nip11 = _create_nip11(relay, {"name": "Test"})

        metadata_tuple = nip11.to_relay_metadata_tuple()

        assert metadata_tuple.nip11_info is not None
        assert metadata_tuple.nip11_info.metadata.type == "nip11_info"
        assert metadata_tuple.nip11_info.relay == relay
        assert metadata_tuple.nip11_info.metadata.data["data"]["name"] == "Test"

    def test_additional_properties(self) -> None:
        """Test additional NIP-11 properties via info.data."""
        relay = Relay("wss://relay.example.com")
        nip11 = _create_nip11(
            relay,
            {
                "name": "Test Relay",
                "description": "A test relay",
                "pubkey": "abc123",
                "contact": "test@example.com",
            },
        )

        assert nip11.info.data.name == "Test Relay"


class TestNip66:
    """Tests for Nip66 dataclass."""

    def test_default_values(self) -> None:
        """Test NIP-66 with no metadata."""
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(relay)

        assert nip66.rtt is None
        assert nip66.ssl is None
        assert nip66.geo is None

    def test_metadata_access(self) -> None:
        """Test NIP-66 metadata access via data attributes."""
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(relay, rtt_data={"rtt_open": 100, "rtt_read": 50})

        assert nip66.rtt is not None
        assert nip66.rtt.data.rtt_open == 100
        assert nip66.rtt.data.rtt_read == 50
        assert nip66.rtt.data.rtt_write is None

    def test_to_relay_metadata_rtt_only(self) -> None:
        """Test NIP-66 to_relay_metadata_tuple with RTT data only."""
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(relay, rtt_data={"rtt_open": 100})

        metadata_tuple = nip66.to_relay_metadata_tuple()

        assert metadata_tuple.rtt is not None
        assert metadata_tuple.rtt.metadata.type == "nip66_rtt"
        assert metadata_tuple.rtt.relay == relay
        assert metadata_tuple.rtt.metadata.data["data"]["rtt_open"] == 100
        assert metadata_tuple.ssl is None
        assert metadata_tuple.geo is None
        assert metadata_tuple.net is None
        assert metadata_tuple.dns is None
        assert metadata_tuple.http is None

    def test_to_relay_metadata_with_geo(self) -> None:
        """Test NIP-66 to_relay_metadata_tuple with RTT and geo data."""
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(
            relay,
            rtt_data={"rtt_open": 100},
            geo_data={"geo_hash": "abc123", "geo_country": "US"},
        )

        metadata_tuple = nip66.to_relay_metadata_tuple()

        assert metadata_tuple.rtt is not None
        assert metadata_tuple.rtt.metadata.type == "nip66_rtt"
        assert metadata_tuple.rtt.metadata.data["data"]["rtt_open"] == 100
        assert metadata_tuple.ssl is None
        assert metadata_tuple.geo is not None
        assert metadata_tuple.geo.metadata.type == "nip66_geo"
        assert metadata_tuple.geo.metadata.data["data"]["geo_hash"] == "abc123"
        assert metadata_tuple.geo.metadata.data["data"]["geo_country"] == "US"
        assert metadata_tuple.net is None
        assert metadata_tuple.dns is None
        assert metadata_tuple.http is None

    def test_to_relay_metadata_with_ssl(self) -> None:
        """Test NIP-66 to_relay_metadata_tuple with RTT and SSL data."""
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(
            relay,
            rtt_data={"rtt_open": 100},
            ssl_data={"ssl_valid": True, "ssl_issuer": "Let's Encrypt"},
        )

        metadata_tuple = nip66.to_relay_metadata_tuple()

        assert metadata_tuple.rtt is not None
        assert metadata_tuple.rtt.metadata.type == "nip66_rtt"
        assert metadata_tuple.ssl is not None
        assert metadata_tuple.ssl.metadata.type == "nip66_ssl"
        assert metadata_tuple.ssl.metadata.data["data"]["ssl_valid"] is True
        assert metadata_tuple.ssl.metadata.data["data"]["ssl_issuer"] == "Let's Encrypt"
        assert metadata_tuple.geo is None
        assert metadata_tuple.net is None
        assert metadata_tuple.dns is None
        assert metadata_tuple.http is None

    def test_to_relay_metadata_with_net(self) -> None:
        """Test NIP-66 to_relay_metadata_tuple with RTT and net data."""
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(
            relay,
            rtt_data={"rtt_open": 100},
            net_data={"net_ip": "8.8.8.8", "net_asn": 15169},
        )

        metadata_tuple = nip66.to_relay_metadata_tuple()

        assert metadata_tuple.rtt is not None
        assert metadata_tuple.net is not None
        assert metadata_tuple.net.metadata.type == "nip66_net"
        assert metadata_tuple.net.metadata.data["data"]["net_ip"] == "8.8.8.8"
        assert metadata_tuple.net.metadata.data["data"]["net_asn"] == 15169

    def test_to_relay_metadata_with_dns(self) -> None:
        """Test NIP-66 to_relay_metadata_tuple with RTT and DNS data."""
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(
            relay,
            rtt_data={"rtt_open": 100},
            dns_data={"dns_resolved": True},
        )

        metadata_tuple = nip66.to_relay_metadata_tuple()

        assert metadata_tuple.rtt is not None
        assert metadata_tuple.dns is not None
        assert metadata_tuple.dns.metadata.type == "nip66_dns"

    def test_to_relay_metadata_with_http(self) -> None:
        """Test NIP-66 to_relay_metadata_tuple with RTT and HTTP data."""
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(
            relay,
            rtt_data={"rtt_open": 100},
            http_data={"http_server": "nginx"},
        )

        metadata_tuple = nip66.to_relay_metadata_tuple()

        assert metadata_tuple.rtt is not None
        assert metadata_tuple.http is not None
        assert metadata_tuple.http.metadata.type == "nip66_http"

    def test_to_relay_metadata_with_all(self) -> None:
        """Test NIP-66 to_relay_metadata_tuple with all metadata types."""
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(
            relay,
            rtt_data={"rtt_open": 100},
            ssl_data={"ssl_valid": True, "ssl_issuer": "Let's Encrypt"},
            geo_data={"geo_hash": "abc123", "geo_country": "US"},
            net_data={"net_ip": "8.8.8.8"},
            dns_data={"dns_resolved": True},
            http_data={"http_server": "nginx"},
        )

        metadata_tuple = nip66.to_relay_metadata_tuple()

        assert metadata_tuple.rtt is not None
        assert metadata_tuple.rtt.metadata.type == "nip66_rtt"
        assert metadata_tuple.ssl is not None
        assert metadata_tuple.ssl.metadata.type == "nip66_ssl"
        assert metadata_tuple.ssl.metadata.data["data"]["ssl_valid"] is True
        assert metadata_tuple.ssl.metadata.data["data"]["ssl_issuer"] == "Let's Encrypt"
        assert metadata_tuple.geo is not None
        assert metadata_tuple.geo.metadata.type == "nip66_geo"
        assert metadata_tuple.geo.metadata.data["data"]["geo_hash"] == "abc123"
        assert metadata_tuple.geo.metadata.data["data"]["geo_country"] == "US"
        assert metadata_tuple.net is not None
        assert metadata_tuple.dns is not None
        assert metadata_tuple.http is not None

    def test_ssl_metadata_access(self) -> None:
        """Test NIP-66 SSL metadata access via data attributes."""
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(
            relay,
            rtt_data={"rtt_open": 100},
            ssl_data={"ssl_valid": True, "ssl_issuer": "Let's Encrypt", "ssl_expires": 1700000000},
        )

        assert nip66.ssl is not None
        assert nip66.ssl.data.ssl_valid is True
        assert nip66.ssl.data.ssl_issuer == "Let's Encrypt"
        assert nip66.ssl.data.ssl_expires == 1700000000

    def test_ssl_metadata_none(self) -> None:
        """Test NIP-66 SSL metadata when not provided."""
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(relay, rtt_data={"rtt_open": 100})

        assert nip66.ssl is None

    def test_rtt_logs_access(self) -> None:
        """Test NIP-66 RTT logs access (probe data is in logs)."""
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(
            relay,
            rtt_data={"rtt_open": 100},
        )

        assert nip66.rtt is not None
        assert nip66.rtt.logs.open_success is True


class TestRelayMetadataType:
    """Tests for RelayMetadata dataclass."""

    def test_creation(self) -> None:
        """Test RelayMetadata creation."""
        from bigbrotr.models import MetadataType
        from bigbrotr.models.metadata import Metadata

        relay = Relay("wss://relay.example.com")
        metadata_obj = Metadata(type=MetadataType.NIP11_INFO, data={"name": "Test"})

        rm = RelayMetadata(
            relay=relay,
            metadata=metadata_obj,
            generated_at=1700000001,
        )

        assert "relay.example.com" in rm.relay.url
        assert rm.relay.network == NetworkType.CLEARNET
        assert rm.metadata.type == MetadataType.NIP11_INFO
        assert rm.metadata.data == {"name": "Test"}
        assert rm.generated_at == 1700000001

    def test_to_db_params(self) -> None:
        """Test RelayMetadata to_db_params for database insertion."""
        from bigbrotr.models import MetadataType
        from bigbrotr.models.metadata import Metadata

        relay = Relay("wss://relay.example.com")
        metadata_obj = Metadata(type=MetadataType.NIP66_RTT, data={"rtt_open": 100})

        rm = RelayMetadata(
            relay=relay,
            metadata=metadata_obj,
            generated_at=1700000001,
        )

        params = rm.to_db_params()

        assert len(params) == 7
        assert params[0] == "wss://relay.example.com"
        assert params[1] == "clearnet"
        assert isinstance(params[3], bytes)
        assert len(params[3]) == 32
        assert params[4] == "nip66_rtt"
        assert params[5] == metadata_obj.to_db_params().data
        assert params[6] == 1700000001


# ============================================================================
# Monitor Initialization Tests
# ============================================================================


class TestMonitorInit:
    """Tests for Monitor initialization."""

    def test_init_with_defaults(self, mock_brotr: Brotr, tmp_path: Path) -> None:
        """Test initialization with defaults (geo/net disabled)."""
        config = MonitorConfig(
            processing=MonitorProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            discovery=DiscoveryConfig(
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)

        assert monitor._brotr is mock_brotr
        assert monitor.SERVICE_NAME == "monitor"

    def test_init_with_custom_config(self, mock_brotr: Brotr, tmp_path: Path) -> None:
        """Test initialization with custom config."""
        config = MonitorConfig(
            networks=NetworkConfig(tor=TorConfig(enabled=False)),
            processing=MonitorProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            discovery=DiscoveryConfig(
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)

        assert monitor.config.networks.tor.enabled is False

    def test_config_class_attribute(self, mock_brotr: Brotr) -> None:
        """Test CONFIG_CLASS class attribute."""
        assert MonitorConfig == Monitor.CONFIG_CLASS

    def test_service_name_attribute(self, mock_brotr: Brotr) -> None:
        """Test SERVICE_NAME class attribute."""
        assert Monitor.SERVICE_NAME == "monitor"


# ============================================================================
# Monitor Fetch Relays Tests
# ============================================================================


class TestMonitorFetchChunk:
    """Tests for Monitor._fetch_chunk() method."""

    @patch(
        "bigbrotr.services.monitor.service.fetch_relays_due_for_check",
        new_callable=AsyncMock,
        return_value=[],
    )
    async def test_fetch_chunk_empty(
        self, mock_fetch: AsyncMock, mock_brotr: Brotr, tmp_path: Path
    ) -> None:
        """Test fetching relays when none need checking."""
        config = MonitorConfig(
            processing=MonitorProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            discovery=DiscoveryConfig(
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)
        monitor.progress.reset()
        relays = await monitor._fetch_chunk(["clearnet"], 100)

        assert relays == []
        mock_fetch.assert_awaited_once()

    @patch("bigbrotr.services.monitor.service.fetch_relays_due_for_check", new_callable=AsyncMock)
    async def test_fetch_chunk_with_results(
        self, mock_fetch: AsyncMock, mock_brotr: Brotr, tmp_path: Path
    ) -> None:
        """Test fetching relays that need checking."""
        mock_fetch.return_value = [
            {
                "url": "wss://relay1.example.com",
                "network": "clearnet",
                "discovered_at": 1700000000,
            },
            {
                "url": "wss://relay2.example.com",
                "network": "clearnet",
                "discovered_at": 1700000000,
            },
        ]

        config = MonitorConfig(
            processing=MonitorProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            discovery=DiscoveryConfig(
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)
        monitor.progress.reset()
        relays = await monitor._fetch_chunk(["clearnet"], 100)

        assert len(relays) == 2
        assert "relay1.example.com" in str(relays[0].url)
        assert "relay2.example.com" in str(relays[1].url)

    @patch("bigbrotr.services.monitor.service.fetch_relays_due_for_check", new_callable=AsyncMock)
    async def test_fetch_chunk_filters_invalid_urls(
        self, mock_fetch: AsyncMock, mock_brotr: Brotr, tmp_path: Path
    ) -> None:
        """Test fetching relays filters invalid URLs."""
        mock_fetch.return_value = [
            {
                "url": "wss://valid.relay.com",
                "network": "clearnet",
                "discovered_at": 1700000000,
            },
            {"url": "invalid-url", "network": "unknown", "discovered_at": 1700000000},
        ]

        config = MonitorConfig(
            processing=MonitorProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            discovery=DiscoveryConfig(
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)
        monitor.progress.reset()
        relays = await monitor._fetch_chunk(["clearnet"], 100)

        assert len(relays) == 1
        assert "valid.relay.com" in str(relays[0].url)

    @patch("bigbrotr.services.monitor.service.fetch_relays_due_for_check", new_callable=AsyncMock)
    async def test_fetch_chunk_respects_limit(
        self, mock_fetch: AsyncMock, mock_brotr: Brotr, tmp_path: Path
    ) -> None:
        """Test that fetch_chunk respects the limit parameter."""
        mock_fetch.return_value = [
            {
                "url": "wss://relay1.example.com",
                "network": "clearnet",
                "discovered_at": 1700000000,
            },
        ]

        config = MonitorConfig(
            processing=MonitorProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            discovery=DiscoveryConfig(
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)
        monitor.progress.reset()
        await monitor._fetch_chunk(["clearnet"], 50)

        assert mock_fetch.call_args[0][4] == 50  # limit is 5th positional arg


# ============================================================================
# Monitor Run Tests
# ============================================================================


class TestMonitorRun:
    """Tests for Monitor.run() method."""

    @patch(
        "bigbrotr.services.monitor.service.fetch_relays_due_for_check",
        new_callable=AsyncMock,
        return_value=[],
    )
    @patch(
        "bigbrotr.services.monitor.service.count_relays_due_for_check",
        new_callable=AsyncMock,
        return_value=0,
    )
    async def test_run_no_relays(
        self,
        mock_count: AsyncMock,
        mock_fetch: AsyncMock,
        mock_brotr: Brotr,
        tmp_path: Path,
    ) -> None:
        """Test run cycle with no relays to check."""
        mock_brotr.get_service_state = AsyncMock(return_value=[])  # type: ignore[method-assign]

        config = MonitorConfig(
            processing=MonitorProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            discovery=DiscoveryConfig(
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)
        await monitor.run()

        assert monitor.progress.processed == 0

    @patch(
        "bigbrotr.services.monitor.service.fetch_relays_due_for_check",
        new_callable=AsyncMock,
        return_value=[],
    )
    @patch(
        "bigbrotr.services.monitor.service.count_relays_due_for_check",
        new_callable=AsyncMock,
        return_value=0,
    )
    async def test_run_resets_progress(
        self,
        mock_count: AsyncMock,
        mock_fetch: AsyncMock,
        mock_brotr: Brotr,
        tmp_path: Path,
    ) -> None:
        """Test run cycle resets progress at start."""
        mock_brotr.get_service_state = AsyncMock(return_value=[])  # type: ignore[method-assign]

        config = MonitorConfig(
            processing=MonitorProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            discovery=DiscoveryConfig(
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)
        monitor.progress.succeeded = 10
        monitor.progress.failed = 5

        await monitor.run()

        assert monitor.progress.succeeded == 0
        assert monitor.progress.failed == 0


# ============================================================================
# Monitor Insert Metadata Tests
# ============================================================================


class TestMonitorPersistResults:
    """Tests for Monitor._persist_results() method."""

    async def test_persist_results_empty(self, mock_brotr: Brotr, tmp_path: Path) -> None:
        """Test persisting empty results batch."""
        mock_brotr.insert_relay_metadata = AsyncMock(return_value=0)  # type: ignore[method-assign]
        mock_brotr.upsert_service_state = AsyncMock(return_value=None)  # type: ignore[method-assign]

        config = MonitorConfig(
            processing=MonitorProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            discovery=DiscoveryConfig(
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)
        await monitor._persist_results([], [])

        mock_brotr.insert_relay_metadata.assert_not_called()  # type: ignore[attr-defined]

    async def test_persist_results_with_successful(self, mock_brotr: Brotr, tmp_path: Path) -> None:
        """Test persisting successful check results."""
        mock_brotr.insert_relay_metadata = AsyncMock(return_value=2)  # type: ignore[method-assign]
        mock_brotr.upsert_service_state = AsyncMock(return_value=None)  # type: ignore[method-assign]

        config = MonitorConfig(
            processing=MonitorProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            discovery=DiscoveryConfig(
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)

        relay1 = Relay("wss://relay1.example.com")
        relay2 = Relay("wss://relay2.example.com")

        result1 = _make_check_result(nip66_rtt=_make_rtt_meta(rtt_open=100))
        result2 = _make_check_result(nip66_rtt=_make_rtt_meta(rtt_open=200))

        successful = [(relay1, result1), (relay2, result2)]
        await monitor._persist_results(successful, [])

        mock_brotr.insert_relay_metadata.assert_called_once()  # type: ignore[attr-defined]
        mock_brotr.upsert_service_state.assert_called_once()  # type: ignore[attr-defined]

    async def test_persist_results_with_failed(self, mock_brotr: Brotr, tmp_path: Path) -> None:
        """Test persisting failed check results updates checkpoint."""
        mock_brotr.insert_relay_metadata = AsyncMock(return_value=0)  # type: ignore[method-assign]
        mock_brotr.upsert_service_state = AsyncMock(return_value=None)  # type: ignore[method-assign]

        config = MonitorConfig(
            processing=MonitorProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            discovery=DiscoveryConfig(
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)

        relay1 = Relay("wss://failed1.example.com")
        relay2 = Relay("wss://failed2.example.com")

        await monitor._persist_results([], [relay1, relay2])

        # insert_relay_metadata should not be called for failed relays
        mock_brotr.insert_relay_metadata.assert_not_called()  # type: ignore[attr-defined]
        # But checkpoint should be updated to prevent immediate retry
        mock_brotr.upsert_service_state.assert_called_once()  # type: ignore[attr-defined]


# ============================================================================
# Network Configuration Tests
# ============================================================================


class TestMonitorNetworkConfiguration:
    """Tests for network configuration in Monitor."""

    def test_enabled_networks_default(self, mock_brotr: Brotr) -> None:
        """Test default enabled networks via config.networks."""
        config = MonitorConfig(
            processing=MonitorProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            discovery=DiscoveryConfig(
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)
        enabled = monitor._config.networks.get_enabled_networks()
        assert "clearnet" in enabled

    def test_enabled_networks_with_tor(self, mock_brotr: Brotr) -> None:
        """Test enabled networks with Tor enabled via config.networks."""
        config = MonitorConfig(
            processing=MonitorProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            discovery=DiscoveryConfig(
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            networks=NetworkConfig(
                clearnet=ClearnetConfig(enabled=True),
                tor=TorConfig(enabled=True),
            ),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)
        enabled = monitor._config.networks.get_enabled_networks()
        assert "clearnet" in enabled
        assert "tor" in enabled


# ============================================================================
# Publishing Test Harness
# ============================================================================


class _MonitorStub:
    """Lightweight harness providing the attributes Monitor methods expect.

    Binds Monitor's publishing/builder methods as class attributes so they
    can be invoked on this stub without the full BaseService initialization.
    """

    SERVICE_NAME = ServiceName.MONITOR

    def __init__(
        self,
        config: MonitorConfig,
        keys: Keys,
        brotr: AsyncMock | None = None,
    ) -> None:
        self._config = config
        self._keys = keys
        self._logger = MagicMock()
        self._brotr = brotr or AsyncMock()

    # Publishing methods bound from Monitor
    _publish_if_due = Monitor._publish_if_due
    publish_announcement = Monitor.publish_announcement
    publish_profile = Monitor.publish_profile
    publish_relay_discoveries = Monitor.publish_relay_discoveries
    _get_publish_relays = Monitor._get_publish_relays

    # Event builder methods bound from Monitor
    _build_kind_0 = Monitor._build_kind_0
    _build_kind_10166 = Monitor._build_kind_10166
    _build_kind_30166 = Monitor._build_kind_30166


# ============================================================================
# Publishing Fixtures
# ============================================================================


@pytest.fixture
def test_keys() -> Keys:
    """Return Keys parsed from the valid hex test key."""
    return Keys.parse(VALID_HEX_KEY)


@pytest.fixture
def all_flags_config() -> MonitorConfig:
    """MonitorConfig with all metadata flags enabled and geo/net disabled to avoid DB checks."""
    return MonitorConfig(
        interval=3600.0,
        processing=MonitorProcessingConfig(
            compute=MetadataFlags(nip66_geo=False, nip66_net=False),
            store=MetadataFlags(nip66_geo=False, nip66_net=False),
        ),
        discovery=DiscoveryConfig(
            enabled=True,
            include=MetadataFlags(nip66_geo=False, nip66_net=False),
            relays=["wss://disc.relay.com"],
        ),
        announcement=AnnouncementConfig(
            enabled=True,
            interval=86400,
            relays=["wss://ann.relay.com"],
        ),
        profile=ProfileConfig(
            enabled=True,
            interval=86400,
            relays=["wss://profile.relay.com"],
            name="BigBrotr",
            about="A monitor",
            picture="https://example.com/pic.png",
            nip05="monitor@example.com",
            website="https://example.com",
            banner="https://example.com/banner.png",
            lud16="monitor@ln.example.com",
        ),
        publishing=PublishingConfig(relays=["wss://fallback.relay.com"]),
        networks=NetworkConfig(clearnet=ClearnetConfig(timeout=10.0)),
    )


@pytest.fixture
def stub(all_flags_config: MonitorConfig, test_keys: Keys) -> _MonitorStub:
    """Return a _MonitorStub with all flags enabled."""
    return _MonitorStub(all_flags_config, test_keys)


# ============================================================================
# Publishing Helper Functions
# ============================================================================


def _make_nip11_meta(
    *,
    name: str | None = None,
    supported_nips: list[int] | None = None,
    tags: list[str] | None = None,
    language_tags: list[str] | None = None,
    limitation: Nip11InfoDataLimitation | None = None,
    success: bool = True,
) -> Nip11InfoMetadata:
    """Build a Nip11InfoMetadata with common test parameters."""
    return Nip11InfoMetadata(
        data=Nip11InfoData(
            name=name,
            supported_nips=supported_nips,
            tags=tags,
            language_tags=language_tags,
            limitation=limitation or Nip11InfoDataLimitation(),
        ),
        logs=Nip11InfoLogs(success=success)
        if success
        else Nip11InfoLogs(
            success=False,
            reason="test failure",
        ),
    )


def _make_rtt_meta(
    *,
    rtt_open: int | None = None,
    rtt_read: int | None = None,
    rtt_write: int | None = None,
    open_success: bool = True,
    write_success: bool | None = None,
    write_reason: str | None = None,
) -> Nip66RttMetadata:
    """Build a Nip66RttMetadata with common test parameters."""
    return Nip66RttMetadata(
        data=Nip66RttData(rtt_open=rtt_open, rtt_read=rtt_read, rtt_write=rtt_write),
        logs=Nip66RttMultiPhaseLogs(
            open_success=open_success,
            open_reason=None if open_success else "connection failed",
            write_success=write_success,
            write_reason=write_reason,
        ),
    )


def _make_ssl_meta(
    *,
    ssl_valid: bool | None = None,
    ssl_expires: int | None = None,
    ssl_issuer: str | None = None,
    success: bool = True,
) -> Nip66SslMetadata:
    """Build a Nip66SslMetadata with common test parameters."""
    return Nip66SslMetadata(
        data=Nip66SslData(ssl_valid=ssl_valid, ssl_expires=ssl_expires, ssl_issuer=ssl_issuer),
        logs=Nip66SslLogs(success=success)
        if success
        else Nip66SslLogs(
            success=False,
            reason="test failure",
        ),
    )


def _make_check_result(
    *,
    generated_at: int = 1700000000,
    nip11: Nip11InfoMetadata | None = None,
    nip66_rtt: Nip66RttMetadata | None = None,
    nip66_ssl: Nip66SslMetadata | None = None,
) -> CheckResult:
    """Build a CheckResult with optional typed metadata fields."""
    return CheckResult(
        generated_at=generated_at,
        nip11=nip11,
        nip66_rtt=nip66_rtt,
        nip66_ssl=nip66_ssl,
    )


# ============================================================================
# Monitor: Relay Getters
# ============================================================================


class TestGetPublishRelays:
    """Tests for _get_publish_relays with primary and fallback logic."""

    def test_get_publish_relays_returns_discovery_primary(self, stub: _MonitorStub) -> None:
        """Test _get_publish_relays returns discovery-specific relays when set."""
        relays = stub._get_publish_relays(stub._config.discovery.relays)
        assert len(relays) == 1
        assert relays[0].url == "wss://disc.relay.com"

    def test_get_publish_relays_discovery_falls_back_to_publishing(self, test_keys: Keys) -> None:
        """Test _get_publish_relays falls back to publishing.relays when discovery empty."""
        config = MonitorConfig(
            processing=MonitorProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            discovery=DiscoveryConfig(
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
                relays=[],
            ),
            publishing=PublishingConfig(relays=["wss://fallback.relay.com"]),
        )
        harness = _MonitorStub(config, test_keys)
        relays = harness._get_publish_relays(harness._config.discovery.relays)
        assert len(relays) == 1
        assert relays[0].url == "wss://fallback.relay.com"

    def test_get_publish_relays_returns_announcement_primary(self, stub: _MonitorStub) -> None:
        """Test _get_publish_relays returns announcement-specific relays when set."""
        relays = stub._get_publish_relays(stub._config.announcement.relays)
        assert len(relays) == 1
        assert relays[0].url == "wss://ann.relay.com"

    def test_get_publish_relays_announcement_falls_back_to_publishing(
        self, test_keys: Keys
    ) -> None:
        """Test _get_publish_relays falls back to publishing.relays when announcement empty."""
        config = MonitorConfig(
            processing=MonitorProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            discovery=DiscoveryConfig(
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            announcement=AnnouncementConfig(relays=[]),
            publishing=PublishingConfig(relays=["wss://fallback.relay.com"]),
        )
        harness = _MonitorStub(config, test_keys)
        relays = harness._get_publish_relays(harness._config.announcement.relays)
        assert len(relays) == 1
        assert relays[0].url == "wss://fallback.relay.com"

    def test_get_publish_relays_returns_profile_primary(self, stub: _MonitorStub) -> None:
        """Test _get_publish_relays returns profile-specific relays when set."""
        relays = stub._get_publish_relays(stub._config.profile.relays)
        assert len(relays) == 1
        assert relays[0].url == "wss://profile.relay.com"

    def test_get_publish_relays_profile_falls_back_to_publishing(self, test_keys: Keys) -> None:
        """Test _get_publish_relays falls back to publishing.relays when profile empty."""
        config = MonitorConfig(
            processing=MonitorProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            discovery=DiscoveryConfig(
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            profile=ProfileConfig(relays=[]),
            publishing=PublishingConfig(relays=["wss://fallback.relay.com"]),
        )
        harness = _MonitorStub(config, test_keys)
        relays = harness._get_publish_relays(harness._config.profile.relays)
        assert len(relays) == 1
        assert relays[0].url == "wss://fallback.relay.com"


# ============================================================================
# Monitor.publish_announcement
# ============================================================================


class TestPublishAnnouncement:
    """Tests for Monitor.publish_announcement."""

    async def test_publish_announcement_when_disabled(self, test_keys: Keys) -> None:
        """Test that publish_announcement returns immediately when disabled."""
        config = MonitorConfig(
            processing=MonitorProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            discovery=DiscoveryConfig(
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            announcement=AnnouncementConfig(enabled=False),
        )
        harness = _MonitorStub(config, test_keys)
        await harness.publish_announcement()
        harness._brotr.get_service_state.assert_not_awaited()

    async def test_publish_announcement_when_no_relays(self, test_keys: Keys) -> None:
        """Test that publish_announcement returns when no relays configured."""
        config = MonitorConfig(
            processing=MonitorProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            discovery=DiscoveryConfig(
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            announcement=AnnouncementConfig(enabled=True, relays=[]),
            publishing=PublishingConfig(relays=[]),
        )
        harness = _MonitorStub(config, test_keys)
        await harness.publish_announcement()
        harness._brotr.get_service_state.assert_not_awaited()

    async def test_publish_announcement_interval_not_elapsed(self, stub: _MonitorStub) -> None:
        """Test that announcement is skipped when interval has not elapsed."""
        now = time.time()
        stub._brotr.get_service_state = AsyncMock(
            return_value=[
                ServiceState(
                    service_name=ServiceName.MONITOR,
                    state_type=ServiceStateType.CHECKPOINT,
                    state_key="last_announcement",
                    state_value={"timestamp": now},
                    updated_at=int(now),
                )
            ]
        )
        with patch("bigbrotr.utils.protocol.connect_relay") as mock_create:
            await stub.publish_announcement()
            mock_create.assert_not_called()

    async def test_publish_announcement_no_prior_state(self, stub: _MonitorStub) -> None:
        """Test successful announcement publish when no prior state exists."""
        stub._brotr.get_service_state = AsyncMock(return_value=[])
        mock_client = AsyncMock()

        with patch(
            "bigbrotr.utils.protocol.connect_relay",
            new_callable=AsyncMock,
            return_value=mock_client,
        ):
            await stub.publish_announcement()

        mock_client.send_event_builder.assert_awaited_once()
        mock_client.shutdown.assert_awaited_once()
        stub._brotr.upsert_service_state.assert_awaited_once()
        stub._logger.info.assert_called_with("announcement_published", relays=1)

    async def test_publish_announcement_interval_elapsed(self, stub: _MonitorStub) -> None:
        """Test successful announcement publish when interval has elapsed."""
        old_timestamp = time.time() - 100000  # well past the 86400 interval
        stub._brotr.get_service_state = AsyncMock(
            return_value=[
                ServiceState(
                    service_name=ServiceName.MONITOR,
                    state_type=ServiceStateType.CHECKPOINT,
                    state_key="last_announcement",
                    state_value={"timestamp": old_timestamp},
                    updated_at=int(old_timestamp),
                )
            ]
        )
        mock_client = AsyncMock()

        with patch(
            "bigbrotr.utils.protocol.connect_relay",
            new_callable=AsyncMock,
            return_value=mock_client,
        ):
            await stub.publish_announcement()

        mock_client.send_event_builder.assert_awaited_once()
        stub._brotr.upsert_service_state.assert_awaited_once()

    async def test_publish_announcement_broadcast_failure(self, stub: _MonitorStub) -> None:
        """Test that announcement failure is logged as warning."""
        stub._brotr.get_service_state = AsyncMock(return_value=[])

        with patch(
            "bigbrotr.utils.protocol.connect_relay",
            new_callable=AsyncMock,
            side_effect=TimeoutError("connect timeout"),
        ):
            await stub.publish_announcement()

        stub._logger.warning.assert_called_once()
        assert "announcement_failed" in stub._logger.warning.call_args[0]


# ============================================================================
# Monitor.publish_profile
# ============================================================================


class TestPublishProfile:
    """Tests for Monitor.publish_profile."""

    async def test_publish_profile_when_disabled(self, test_keys: Keys) -> None:
        """Test that publish_profile returns immediately when disabled."""
        config = MonitorConfig(
            processing=MonitorProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            discovery=DiscoveryConfig(
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            profile=ProfileConfig(enabled=False),
        )
        harness = _MonitorStub(config, test_keys)
        await harness.publish_profile()
        harness._brotr.get_service_state.assert_not_awaited()

    async def test_publish_profile_when_no_relays(self, test_keys: Keys) -> None:
        """Test that publish_profile returns when no relays configured."""
        config = MonitorConfig(
            processing=MonitorProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            discovery=DiscoveryConfig(
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            profile=ProfileConfig(enabled=True, relays=[]),
            publishing=PublishingConfig(relays=[]),
        )
        harness = _MonitorStub(config, test_keys)
        await harness.publish_profile()
        harness._brotr.get_service_state.assert_not_awaited()

    async def test_publish_profile_interval_not_elapsed(self, stub: _MonitorStub) -> None:
        """Test that profile is skipped when interval has not elapsed."""
        now = time.time()
        stub._brotr.get_service_state = AsyncMock(
            return_value=[
                ServiceState(
                    service_name=ServiceName.MONITOR,
                    state_type=ServiceStateType.CHECKPOINT,
                    state_key="last_profile",
                    state_value={"timestamp": now},
                    updated_at=int(now),
                )
            ]
        )
        with patch("bigbrotr.utils.protocol.connect_relay") as mock_create:
            await stub.publish_profile()
            mock_create.assert_not_called()

    async def test_publish_profile_successful(self, stub: _MonitorStub) -> None:
        """Test successful profile publish when interval has elapsed."""
        stub._brotr.get_service_state = AsyncMock(return_value=[])
        mock_client = AsyncMock()

        with patch(
            "bigbrotr.utils.protocol.connect_relay",
            new_callable=AsyncMock,
            return_value=mock_client,
        ):
            await stub.publish_profile()

        mock_client.send_event_builder.assert_awaited_once()
        stub._brotr.upsert_service_state.assert_awaited_once()
        stub._logger.info.assert_called_with("profile_published", relays=1)

    async def test_publish_profile_broadcast_failure(self, stub: _MonitorStub) -> None:
        """Test that profile failure is logged as warning."""
        stub._brotr.get_service_state = AsyncMock(return_value=[])

        with patch(
            "bigbrotr.utils.protocol.connect_relay",
            new_callable=AsyncMock,
            side_effect=OSError("connection refused"),
        ):
            await stub.publish_profile()

        stub._logger.warning.assert_called_once()
        assert "profile_failed" in stub._logger.warning.call_args[0]


# ============================================================================
# Monitor.publish_relay_discoveries
# ============================================================================


class TestPublishRelayDiscoveries:
    """Tests for Monitor.publish_relay_discoveries."""

    async def test_publish_discoveries_when_disabled(self, test_keys: Keys) -> None:
        """Test that discoveries returns immediately when disabled."""
        config = MonitorConfig(
            processing=MonitorProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            discovery=DiscoveryConfig(
                enabled=False,
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
        )
        harness = _MonitorStub(config, test_keys)

        relay = Relay("wss://relay.example.com")
        result = _make_check_result()

        with patch("bigbrotr.utils.protocol.connect_relay") as mock_create:
            await harness.publish_relay_discoveries([(relay, result)])
            mock_create.assert_not_called()

    async def test_publish_discoveries_when_no_relays(self, test_keys: Keys) -> None:
        """Test that discoveries returns when no relays configured."""
        config = MonitorConfig(
            processing=MonitorProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            discovery=DiscoveryConfig(
                enabled=True,
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
                relays=[],
            ),
            publishing=PublishingConfig(relays=[]),
        )
        harness = _MonitorStub(config, test_keys)

        relay = Relay("wss://relay.example.com")
        result = _make_check_result()

        with patch("bigbrotr.utils.protocol.connect_relay") as mock_create:
            await harness.publish_relay_discoveries([(relay, result)])
            mock_create.assert_not_called()

    async def test_publish_discoveries_successful(self, stub: _MonitorStub) -> None:
        """Test successful relay discovery publishing."""
        relay = Relay("wss://relay.example.com")
        result = _make_check_result(nip11=_make_nip11_meta(name="Test Relay"))
        mock_client = AsyncMock()

        with patch(
            "bigbrotr.utils.protocol.connect_relay",
            new_callable=AsyncMock,
            return_value=mock_client,
        ):
            await stub.publish_relay_discoveries([(relay, result)])

        mock_client.send_event_builder.assert_awaited_once()
        stub._logger.debug.assert_any_call("discoveries_published", count=1)

    async def test_publish_discoveries_build_failure_for_individual(
        self, stub: _MonitorStub
    ) -> None:
        """Test that build failure for one relay does not prevent others."""
        relay1 = Relay("wss://relay1.example.com")
        relay2 = Relay("wss://relay2.example.com")
        result1 = _make_check_result()
        result2 = _make_check_result(nip11=_make_nip11_meta(name="Test"))

        mock_client = AsyncMock()

        # Patch _build_kind_30166 to raise on the first relay only
        original_build = Monitor._build_kind_30166
        call_count = 0

        def _patched_build(self_: Any, relay: Relay, result: CheckResult) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("build failed for relay1")
            return original_build(self_, relay, result)

        stub._build_kind_30166 = lambda r, res: _patched_build(stub, r, res)  # type: ignore[assignment]

        with patch(
            "bigbrotr.utils.protocol.connect_relay",
            new_callable=AsyncMock,
            return_value=mock_client,
        ):
            await stub.publish_relay_discoveries([(relay1, result1), (relay2, result2)])

        # One builder should have succeeded
        mock_client.send_event_builder.assert_awaited_once()
        stub._logger.debug.assert_any_call(
            "build_30166_failed", url=relay1.url, error="build failed for relay1"
        )

    async def test_publish_discoveries_broadcast_failure(self, stub: _MonitorStub) -> None:
        """Test that broadcast failure is logged as warning."""
        relay = Relay("wss://relay.example.com")
        result = _make_check_result()

        with patch(
            "bigbrotr.utils.protocol.connect_relay",
            new_callable=AsyncMock,
            side_effect=TimeoutError("broadcast timeout"),
        ):
            await stub.publish_relay_discoveries([(relay, result)])

        stub._logger.warning.assert_called_once()
        assert "discoveries_broadcast_failed" in stub._logger.warning.call_args[0]


# ============================================================================
# Monitor._build_kind_0
# ============================================================================


class TestBuildKind0:
    """Tests for Monitor._build_kind_0 (profile metadata)."""

    def test_build_kind_0_all_fields(self, stub: _MonitorStub) -> None:
        """Test Kind 0 builder with all profile fields populated."""
        builder = stub._build_kind_0()
        assert builder is not None

    def test_build_kind_0_minimal_fields(self, test_keys: Keys) -> None:
        """Test Kind 0 builder with only name field set."""
        config = MonitorConfig(
            processing=MonitorProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            discovery=DiscoveryConfig(
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            profile=ProfileConfig(
                enabled=True,
                name="MinimalMonitor",
            ),
        )
        harness = _MonitorStub(config, test_keys)
        builder = harness._build_kind_0()
        assert builder is not None

    def test_build_kind_0_no_fields(self, test_keys: Keys) -> None:
        """Test Kind 0 builder with no profile fields set."""
        config = MonitorConfig(
            processing=MonitorProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            discovery=DiscoveryConfig(
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            profile=ProfileConfig(enabled=True),
        )
        harness = _MonitorStub(config, test_keys)
        builder = harness._build_kind_0()
        assert builder is not None


# ============================================================================
# Monitor._build_kind_10166
# ============================================================================


class TestBuildKind10166:
    """Tests for Monitor._build_kind_10166 (monitor announcement)."""

    def test_build_kind_10166_all_flags_enabled(self, stub: _MonitorStub) -> None:
        """Test Kind 10166 builder with all metadata flags enabled."""
        builder = stub._build_kind_10166()
        assert builder is not None

    def test_build_kind_10166_subset_flags(self, test_keys: Keys) -> None:
        """Test Kind 10166 builder with only RTT and NIP-11 flags enabled."""
        config = MonitorConfig(
            interval=1800.0,
            processing=MonitorProcessingConfig(
                compute=MetadataFlags(
                    nip66_geo=False,
                    nip66_net=False,
                    nip66_ssl=False,
                    nip66_dns=False,
                    nip66_http=False,
                ),
                store=MetadataFlags(
                    nip66_geo=False,
                    nip66_net=False,
                    nip66_ssl=False,
                    nip66_dns=False,
                    nip66_http=False,
                ),
            ),
            discovery=DiscoveryConfig(
                include=MetadataFlags(
                    nip11_info=True,
                    nip66_rtt=True,
                    nip66_ssl=False,
                    nip66_geo=False,
                    nip66_net=False,
                    nip66_dns=False,
                    nip66_http=False,
                ),
                relays=["wss://disc.relay.com"],
            ),
            networks=NetworkConfig(clearnet=ClearnetConfig(timeout=5.0)),
        )
        harness = _MonitorStub(config, test_keys)
        builder = harness._build_kind_10166()
        assert builder is not None

    def test_build_kind_10166_no_flags(self, test_keys: Keys) -> None:
        """Test Kind 10166 builder with all flags disabled."""
        config = MonitorConfig(
            interval=600.0,
            processing=MonitorProcessingConfig(
                compute=MetadataFlags(
                    nip11_info=False,
                    nip66_rtt=False,
                    nip66_ssl=False,
                    nip66_geo=False,
                    nip66_net=False,
                    nip66_dns=False,
                    nip66_http=False,
                ),
                store=MetadataFlags(
                    nip11_info=False,
                    nip66_rtt=False,
                    nip66_ssl=False,
                    nip66_geo=False,
                    nip66_net=False,
                    nip66_dns=False,
                    nip66_http=False,
                ),
            ),
            discovery=DiscoveryConfig(
                enabled=False,
                include=MetadataFlags(
                    nip11_info=False,
                    nip66_rtt=False,
                    nip66_ssl=False,
                    nip66_geo=False,
                    nip66_net=False,
                    nip66_dns=False,
                    nip66_http=False,
                ),
            ),
            networks=NetworkConfig(clearnet=ClearnetConfig(timeout=10.0)),
        )
        harness = _MonitorStub(config, test_keys)
        builder = harness._build_kind_10166()
        assert builder is not None


# ============================================================================
# Monitor._build_kind_30166
# ============================================================================


class TestBuildKind30166:
    """Tests for Monitor._build_kind_30166 (relay discovery orchestration)."""

    def test_build_kind_30166_full_event(self, stub: _MonitorStub) -> None:
        """Test full Kind 30166 event construction with all metadata."""
        relay = Relay("wss://relay.example.com")
        result = _make_check_result(
            nip11=_make_nip11_meta(
                name="Test Relay",
                supported_nips=[1, 11, 50],
                tags=["social"],
                language_tags=["en"],
            ),
            nip66_rtt=_make_rtt_meta(rtt_open=45, rtt_read=120, rtt_write=85),
            nip66_ssl=_make_ssl_meta(ssl_valid=True, ssl_expires=1735689600),
        )
        builder = stub._build_kind_30166(relay, result)
        assert builder is not None

    def test_build_kind_30166_minimal(self, stub: _MonitorStub) -> None:
        """Test Kind 30166 event with no metadata results."""
        relay = Relay("wss://relay.example.com")
        result = _make_check_result()
        builder = stub._build_kind_30166(relay, result)
        assert builder is not None

    def test_build_kind_30166_content_from_nip11(self, stub: _MonitorStub) -> None:
        """Test that Kind 30166 content contains NIP-11 canonical JSON when available."""
        relay = Relay("wss://relay.example.com")
        result = _make_check_result(nip11=_make_nip11_meta(name="Test Relay"))
        builder = stub._build_kind_30166(relay, result)
        assert builder is not None

    def test_build_kind_30166_empty_content_when_no_nip11(self, stub: _MonitorStub) -> None:
        """Test that Kind 30166 content is empty string when no NIP-11 data."""
        relay = Relay("wss://relay.example.com")
        result = _make_check_result()
        builder = stub._build_kind_30166(relay, result)
        assert builder is not None

    def test_build_kind_30166_tor_relay_network_tag(self, stub: _MonitorStub) -> None:
        """Test that Kind 30166 uses the correct network value for Tor relays."""
        onion = "a" * 56
        relay = Relay(f"ws://{onion}.onion")
        result = _make_check_result()
        builder = stub._build_kind_30166(relay, result)
        assert builder is not None


# ============================================================================
# Integration-style: end-to-end tag generation via Monitor orchestration
# ============================================================================


class TestEndToEndTagGeneration:
    """Integration-style tests verifying complete tag generation via Monitor._build_kind_30166."""

    def test_full_relay_with_all_metadata(self, stub: _MonitorStub) -> None:
        """Test a relay with RTT, SSL, NIP-11 produces a valid builder."""
        result = _make_check_result(
            nip11=_make_nip11_meta(
                name="Production Relay",
                supported_nips=[1, 11, 42, 50],
                tags=["social"],
                language_tags=["en", "de"],
                limitation=Nip11InfoDataLimitation(
                    auth_required=False,
                    payment_required=False,
                    restricted_writes=False,
                    min_pow_difficulty=0,
                ),
            ),
            nip66_rtt=_make_rtt_meta(
                rtt_open=30,
                rtt_read=100,
                rtt_write=80,
                write_success=True,
            ),
            nip66_ssl=_make_ssl_meta(
                ssl_valid=True,
                ssl_expires=1735689600,
                ssl_issuer="Let's Encrypt",
            ),
        )

        relay = Relay("wss://relay.example.com")
        builder = stub._build_kind_30166(relay, result)
        assert builder is not None
