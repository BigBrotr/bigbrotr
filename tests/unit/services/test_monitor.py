"""
Unit tests for services.monitor module.

Tests:
- Configuration models (MetadataFlags, MonitorProcessingConfig, GeoConfig, etc.)
- Monitor service initialization
- Relay selection logic
- Metadata batch insertion
- NIP-66 data classes
- Kind 30166 tag builder methods
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.models import Relay, RelayMetadata
from bigbrotr.models.constants import NetworkType
from bigbrotr.nips.nip11 import Nip11
from bigbrotr.nips.nip66 import Nip66
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
        assert config.nip11_max_size == 1048576
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

    def test_nip11_max_size_custom(self) -> None:
        """Test custom NIP-11 max size."""
        config = MonitorProcessingConfig(nip11_max_size=2097152)  # 2MB
        assert config.nip11_max_size == 2097152


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
    from bigbrotr.nips.nip11 import Nip11FetchData, Nip11FetchLogs, Nip11InfoMetadata

    if data is None:
        data = {}
    fetch_data = Nip11FetchData.model_validate(Nip11FetchData.parse(data))
    fetch_logs = Nip11FetchLogs(success=True)
    fetch_metadata = Nip11InfoMetadata(data=fetch_data, logs=fetch_logs)
    return Nip11(relay=relay, fetch_metadata=fetch_metadata, generated_at=generated_at)


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
        """Test NIP-11 with empty data - access via fetch_metadata.data."""
        relay = Relay("wss://relay.example.com")
        nip11 = _create_nip11(relay, {})

        assert nip11.fetch_metadata.data.name is None
        assert nip11.fetch_metadata.data.supported_nips is None

    def test_properties(self) -> None:
        """Test NIP-11 property access via fetch_metadata.data."""
        relay = Relay("wss://relay.example.com")
        nip11 = _create_nip11(relay, {"name": "Test Relay", "supported_nips": [1, 11, 66]})

        assert nip11.fetch_metadata.data.name == "Test Relay"
        assert nip11.fetch_metadata.data.supported_nips == [1, 11, 66]

    def test_to_relay_metadata(self) -> None:
        """Test NIP-11 to_relay_metadata_tuple factory method."""
        relay = Relay("wss://relay.example.com")
        nip11 = _create_nip11(relay, {"name": "Test"})

        metadata_tuple = nip11.to_relay_metadata_tuple()

        assert metadata_tuple.nip11_info is not None
        assert metadata_tuple.nip11_info.metadata.type == "nip11_info"
        assert metadata_tuple.nip11_info.relay == relay
        assert metadata_tuple.nip11_info.metadata.value["data"]["name"] == "Test"

    def test_additional_properties(self) -> None:
        """Test additional NIP-11 properties via fetch_metadata.data."""
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

        assert nip11.fetch_metadata.data.name == "Test Relay"


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
        assert metadata_tuple.rtt.metadata.value["data"]["rtt_open"] == 100
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
        assert metadata_tuple.rtt.metadata.value["data"]["rtt_open"] == 100
        assert metadata_tuple.ssl is None
        assert metadata_tuple.geo is not None
        assert metadata_tuple.geo.metadata.type == "nip66_geo"
        assert metadata_tuple.geo.metadata.value["data"]["geo_hash"] == "abc123"
        assert metadata_tuple.geo.metadata.value["data"]["geo_country"] == "US"
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
        assert metadata_tuple.ssl.metadata.value["data"]["ssl_valid"] is True
        assert metadata_tuple.ssl.metadata.value["data"]["ssl_issuer"] == "Let's Encrypt"
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
        assert metadata_tuple.net.metadata.value["data"]["net_ip"] == "8.8.8.8"
        assert metadata_tuple.net.metadata.value["data"]["net_asn"] == 15169

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
        assert metadata_tuple.ssl.metadata.value["data"]["ssl_valid"] is True
        assert metadata_tuple.ssl.metadata.value["data"]["ssl_issuer"] == "Let's Encrypt"
        assert metadata_tuple.geo is not None
        assert metadata_tuple.geo.metadata.type == "nip66_geo"
        assert metadata_tuple.geo.metadata.value["data"]["geo_hash"] == "abc123"
        assert metadata_tuple.geo.metadata.value["data"]["geo_country"] == "US"
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
        metadata_obj = Metadata(type=MetadataType.NIP11_INFO, value={"name": "Test"})

        rm = RelayMetadata(
            relay=relay,
            metadata=metadata_obj,
            generated_at=1700000001,
        )

        assert "relay.example.com" in rm.relay.url
        assert rm.relay.network == NetworkType.CLEARNET
        assert rm.metadata.type == MetadataType.NIP11_INFO
        assert rm.metadata.value == {"name": "Test"}
        assert rm.generated_at == 1700000001

    def test_to_db_params(self) -> None:
        """Test RelayMetadata to_db_params for database insertion."""
        from bigbrotr.models import MetadataType
        from bigbrotr.models.metadata import Metadata

        relay = Relay("wss://relay.example.com")
        metadata_obj = Metadata(type=MetadataType.NIP66_RTT, value={"rtt_open": 100})

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
        assert params[4] == metadata_obj.to_db_params().payload
        assert params[5] == "nip66_rtt"
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

    @pytest.mark.asyncio
    @patch(
        "bigbrotr.services.monitor.fetch_relays_due_for_check",
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
        monitor._progress.reset()
        relays = await monitor._fetch_chunk(["clearnet"], 100)

        assert relays == []
        mock_fetch.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("bigbrotr.services.monitor.fetch_relays_due_for_check", new_callable=AsyncMock)
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
        monitor._progress.reset()
        relays = await monitor._fetch_chunk(["clearnet"], 100)

        assert len(relays) == 2
        assert "relay1.example.com" in str(relays[0].url)
        assert "relay2.example.com" in str(relays[1].url)

    @pytest.mark.asyncio
    @patch("bigbrotr.services.monitor.fetch_relays_due_for_check", new_callable=AsyncMock)
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
        monitor._progress.reset()
        relays = await monitor._fetch_chunk(["clearnet"], 100)

        assert len(relays) == 1
        assert "valid.relay.com" in str(relays[0].url)

    @pytest.mark.asyncio
    @patch("bigbrotr.services.monitor.fetch_relays_due_for_check", new_callable=AsyncMock)
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
        monitor._progress.reset()
        await monitor._fetch_chunk(["clearnet"], 50)

        assert mock_fetch.call_args[0][4] == 50  # limit is 5th positional arg


# ============================================================================
# Monitor Run Tests
# ============================================================================


class TestMonitorRun:
    """Tests for Monitor.run() method."""

    @pytest.mark.asyncio
    @patch(
        "bigbrotr.services.monitor.fetch_relays_due_for_check",
        new_callable=AsyncMock,
        return_value=[],
    )
    @patch(
        "bigbrotr.services.monitor.count_relays_due_for_check",
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

        assert monitor._progress.processed == 0

    @pytest.mark.asyncio
    @patch(
        "bigbrotr.services.monitor.fetch_relays_due_for_check",
        new_callable=AsyncMock,
        return_value=[],
    )
    @patch(
        "bigbrotr.services.monitor.count_relays_due_for_check",
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
        monitor._progress.success = 10
        monitor._progress.failure = 5

        await monitor.run()

        assert monitor._progress.success == 0
        assert monitor._progress.failure == 0


# ============================================================================
# Monitor Insert Metadata Tests
# ============================================================================


class TestMonitorPersistResults:
    """Tests for Monitor._persist_results() method."""

    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
    async def test_persist_results_with_successful(self, mock_brotr: Brotr, tmp_path: Path) -> None:
        """Test persisting successful check results."""
        from bigbrotr.models import Metadata

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
        rtt1 = RelayMetadata(relay1, Metadata({"rtt_open": 100}), "nip66_rtt")
        rtt2 = RelayMetadata(relay2, Metadata({"rtt_open": 200}), "nip66_rtt")

        # Create CheckResult with rtt metadata
        result1 = CheckResult(
            nip11=None,
            nip66_rtt=rtt1,
            nip66_ssl=None,
            nip66_geo=None,
            nip66_net=None,
            nip66_dns=None,
            nip66_http=None,
        )
        result2 = CheckResult(
            nip11=None,
            nip66_rtt=rtt2,
            nip66_ssl=None,
            nip66_geo=None,
            nip66_net=None,
            nip66_dns=None,
            nip66_http=None,
        )

        successful = [(relay1, result1), (relay2, result2)]
        await monitor._persist_results(successful, [])

        mock_brotr.insert_relay_metadata.assert_called_once()  # type: ignore[attr-defined]
        mock_brotr.upsert_service_state.assert_called_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
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
# Tag Builder Tests
# ============================================================================


class TestTagBuilders:
    """Tests for Kind 30166 tag builder methods.

    These verify that tag builders correctly extract fields from the nested
    ``{"data": {...}, "logs": {...}}`` structure produced by BaseMetadata.to_dict().
    """

    @pytest.fixture
    def monitor(self, mock_brotr: Brotr) -> Monitor:
        """Create a Monitor with all metadata flags enabled."""
        config = MonitorConfig(
            processing=MonitorProcessingConfig(
                compute=MetadataFlags(),
                store=MetadataFlags(),
            ),
            discovery=DiscoveryConfig(include=MetadataFlags()),
        )
        return Monitor(brotr=mock_brotr, config=config)

    @staticmethod
    def _make_relay_metadata(
        metadata_type: str,
        value: dict,
    ) -> RelayMetadata:
        """Build a RelayMetadata with the given nested value dict."""
        from bigbrotr.models import MetadataType
        from bigbrotr.models.metadata import Metadata

        relay = Relay("wss://relay.example.com")
        return RelayMetadata(
            relay=relay,
            metadata=Metadata(type=MetadataType(metadata_type), value=value),
            generated_at=1700000000,
        )

    def test_add_rtt_tags_extracts_from_data(self, monitor: Monitor) -> None:
        """Test _add_rtt_tags extracts RTT values from nested data dict."""
        rm = self._make_relay_metadata(
            "nip66_rtt",
            {
                "data": {"rtt_open": 45, "rtt_read": 120, "rtt_write": 85},
                "logs": {"open_success": True},
            },
        )
        result = CheckResult(
            nip11=None,
            nip66_rtt=rm,
            nip66_ssl=None,
            nip66_geo=None,
            nip66_net=None,
            nip66_dns=None,
            nip66_http=None,
        )
        tags: list = []
        monitor._add_rtt_tags(tags, result, MetadataFlags())

        tag_map = {t.as_vec()[0]: t.as_vec()[1] for t in tags}
        assert tag_map["rtt-open"] == "45"
        assert tag_map["rtt-read"] == "120"
        assert tag_map["rtt-write"] == "85"

    def test_add_ssl_tags_extracts_from_data(self, monitor: Monitor) -> None:
        """Test _add_ssl_tags extracts SSL values from nested data dict."""
        rm = self._make_relay_metadata(
            "nip66_ssl",
            {
                "data": {
                    "ssl_valid": True,
                    "ssl_expires": 1735689600,
                    "ssl_issuer": "Let's Encrypt",
                },
                "logs": {"success": True},
            },
        )
        result = CheckResult(
            nip11=None,
            nip66_rtt=None,
            nip66_ssl=rm,
            nip66_geo=None,
            nip66_net=None,
            nip66_dns=None,
            nip66_http=None,
        )
        tags: list = []
        monitor._add_ssl_tags(tags, result, MetadataFlags())

        tag_map = {t.as_vec()[0]: t.as_vec()[1] for t in tags}
        assert tag_map["ssl"] == "valid"
        assert tag_map["ssl-expires"] == "1735689600"
        assert tag_map["ssl-issuer"] == "Let's Encrypt"

    def test_add_net_tags_extracts_from_data(self, monitor: Monitor) -> None:
        """Test _add_net_tags extracts network values from nested data dict."""
        rm = self._make_relay_metadata(
            "nip66_net",
            {
                "data": {"net_ip": "1.2.3.4", "net_asn": 13335, "net_asn_org": "Cloudflare"},
                "logs": {"success": True},
            },
        )
        result = CheckResult(
            nip11=None,
            nip66_rtt=None,
            nip66_ssl=None,
            nip66_geo=None,
            nip66_net=rm,
            nip66_dns=None,
            nip66_http=None,
        )
        tags: list = []
        monitor._add_net_tags(tags, result, MetadataFlags())

        tag_map = {t.as_vec()[0]: t.as_vec()[1] for t in tags}
        assert tag_map["net-ip"] == "1.2.3.4"
        assert tag_map["net-asn"] == "13335"
        assert tag_map["net-asn-org"] == "Cloudflare"

    def test_add_geo_tags_extracts_from_data(self, monitor: Monitor) -> None:
        """Test _add_geo_tags extracts geolocation values from nested data dict."""
        rm = self._make_relay_metadata(
            "nip66_geo",
            {
                "data": {
                    "geo_hash": "u33dc",
                    "geo_country": "DE",
                    "geo_city": "Frankfurt",
                    "geo_lat": 50.1109,
                    "geo_lon": 8.6821,
                    "geo_tz": "Europe/Berlin",
                },
                "logs": {"success": True},
            },
        )
        result = CheckResult(
            nip11=None,
            nip66_rtt=None,
            nip66_ssl=None,
            nip66_geo=rm,
            nip66_net=None,
            nip66_dns=None,
            nip66_http=None,
        )
        tags: list = []
        monitor._add_geo_tags(tags, result, MetadataFlags())

        tag_map = {t.as_vec()[0]: t.as_vec()[1] for t in tags}
        assert tag_map["g"] == "u33dc"
        assert tag_map["geo-country"] == "DE"
        assert tag_map["geo-city"] == "Frankfurt"
        assert tag_map["geo-lat"] == "50.1109"
        assert tag_map["geo-lon"] == "8.6821"
        assert tag_map["geo-tz"] == "Europe/Berlin"

    def test_add_nip11_tags_extracts_from_data(self, monitor: Monitor) -> None:
        """Test _add_nip11_tags extracts NIP-11 values from nested data dict."""
        rm = self._make_relay_metadata(
            "nip11_info",
            {
                "data": {"supported_nips": [1, 11, 50], "tags": ["social", "chat"]},
                "logs": {"success": True},
            },
        )
        result = CheckResult(
            nip11=rm,
            nip66_rtt=None,
            nip66_ssl=None,
            nip66_geo=None,
            nip66_net=None,
            nip66_dns=None,
            nip66_http=None,
        )
        tags: list = []
        monitor._add_nip11_tags(tags, result, MetadataFlags())

        tag_vecs = [t.as_vec() for t in tags]
        nip_tags = [(v[0], v[1]) for v in tag_vecs if v[0] == "N"]
        assert ("N", "1") in nip_tags
        assert ("N", "11") in nip_tags
        assert ("N", "50") in nip_tags

        topic_tags = [(v[0], v[1]) for v in tag_vecs if v[0] == "t"]
        assert ("t", "social") in topic_tags
        assert ("t", "chat") in topic_tags

    def test_rtt_tags_empty_when_data_missing(self, monitor: Monitor) -> None:
        """Test that tag builders produce no tags when data key is absent."""
        rm = self._make_relay_metadata(
            "nip66_rtt",
            {
                "logs": {"open_success": False},
            },
        )
        result = CheckResult(
            nip11=None,
            nip66_rtt=rm,
            nip66_ssl=None,
            nip66_geo=None,
            nip66_net=None,
            nip66_dns=None,
            nip66_http=None,
        )
        tags: list = []
        monitor._add_rtt_tags(tags, result, MetadataFlags())

        assert tags == []

    def test_requirement_tags_use_logs_for_probe(self, monitor: Monitor) -> None:
        """Test _add_requirement_and_type_tags reads probe logs from 'logs' key."""
        rtt_rm = self._make_relay_metadata(
            "nip66_rtt",
            {
                "data": {"rtt_open": 45, "rtt_read": 120},
                "logs": {"write_success": False, "write_reason": "auth-required: NIP-42"},
            },
        )
        nip11_rm = self._make_relay_metadata(
            "nip11_info",
            {
                "data": {"supported_nips": [1, 42], "limitation": {"auth_required": True}},
                "logs": {"success": True},
            },
        )
        result = CheckResult(
            nip11=nip11_rm,
            nip66_rtt=rtt_rm,
            nip66_ssl=None,
            nip66_geo=None,
            nip66_net=None,
            nip66_dns=None,
            nip66_http=None,
        )
        tags: list = []
        monitor._add_requirement_and_type_tags(
            tags,
            result,
            {"supported_nips": [1, 42], "limitation": {"auth_required": True}},
            [1, 42],
        )

        tag_vecs = [t.as_vec() for t in tags]
        req_tags = [v for v in tag_vecs if v[0] == "R"]
        assert any("auth" in v[1] for v in req_tags)
