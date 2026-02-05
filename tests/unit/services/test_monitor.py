"""
Unit tests for services.monitor module.

Tests:
- Configuration models (MetadataFlags, ProcessingConfig, GeoConfig, etc.)
- Monitor service initialization
- Relay selection logic
- Metadata batch insertion
- NIP-66 data classes
"""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from core.brotr import Brotr
from models import Nip11, Nip66, Relay, RelayMetadata
from models.relay import NetworkType
from services.monitor import (
    AnnouncementConfig,
    CheckResult,
    DiscoveryConfig,
    GeoConfig,
    MetadataFlags,
    Monitor,
    MonitorConfig,
    ProcessingConfig,
    ProfileConfig,
    PublishingConfig,
)
from utils.network import ClearnetConfig, NetworkConfig, TorConfig


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

        assert flags.nip11 is True
        assert flags.nip66_rtt is True
        assert flags.nip66_probe is True
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
        assert flags.nip66_probe is True

    def test_all_flags_disabled(self) -> None:
        """Test disabling all flags."""
        flags = MetadataFlags(
            nip11=False,
            nip66_rtt=False,
            nip66_probe=False,
            nip66_ssl=False,
            nip66_geo=False,
            nip66_net=False,
            nip66_dns=False,
            nip66_http=False,
        )

        assert flags.nip11 is False
        assert flags.nip66_rtt is False
        assert flags.nip66_probe is False
        assert flags.nip66_ssl is False
        assert flags.nip66_geo is False
        assert flags.nip66_net is False
        assert flags.nip66_dns is False
        assert flags.nip66_http is False


# ============================================================================
# ProcessingConfig Tests
# ============================================================================


class TestProcessingConfig:
    """Tests for ProcessingConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default processing config."""
        config = ProcessingConfig()

        assert config.chunk_size == 100
        assert config.nip11_max_size == 1048576
        assert config.compute.nip11 is True
        assert config.store.nip11 is True

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

    def test_nip11_max_size_custom(self) -> None:
        """Test custom NIP-11 max size."""
        config = ProcessingConfig(nip11_max_size=2097152)  # 2MB
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
        assert config.include.nip11 is True
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
# Helper Functions for Test Data Creation
# ============================================================================


def _create_nip11(relay: Relay, data: dict | None = None, generated_at: int = 1700000001) -> Nip11:
    """Create a Nip11 instance with proper Nip11FetchMetadata structure."""
    from models.nips.nip11 import Nip11FetchData, Nip11FetchLogs, Nip11FetchMetadata

    if data is None:
        data = {}
    fetch_data = Nip11FetchData.model_validate(Nip11FetchData.parse(data))
    fetch_logs = Nip11FetchLogs(success=True)
    fetch_metadata = Nip11FetchMetadata(data=fetch_data, logs=fetch_logs)
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
    from models.nips.nip66 import (
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
        Nip66RttLogs,
        Nip66RttMetadata,
        Nip66SslData,
        Nip66SslLogs,
        Nip66SslMetadata,
    )

    rtt_metadata = None
    if rtt_data is not None:
        rtt_metadata = Nip66RttMetadata(
            data=Nip66RttData.model_validate(Nip66RttData.parse(rtt_data)),
            logs=Nip66RttLogs(open_success=True),
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
        rtt_metadata=rtt_metadata,
        ssl_metadata=ssl_metadata,
        geo_metadata=geo_metadata,
        net_metadata=net_metadata,
        dns_metadata=dns_metadata,
        http_metadata=http_metadata,
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

        assert metadata_tuple.nip11_fetch is not None
        assert metadata_tuple.nip11_fetch.metadata.type == "nip11_fetch"
        assert metadata_tuple.nip11_fetch.relay == relay
        # Metadata is nested under "data" key (from to_dict())
        assert metadata_tuple.nip11_fetch.metadata.value["data"]["name"] == "Test"

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

        # No metadata when not provided
        assert nip66.rtt_metadata is None
        assert nip66.ssl_metadata is None
        assert nip66.geo_metadata is None

    def test_metadata_access(self) -> None:
        """Test NIP-66 metadata access via data attributes."""
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(relay, rtt_data={"rtt_open": 100, "rtt_read": 50})

        # Access via data attributes
        assert nip66.rtt_metadata is not None
        assert nip66.rtt_metadata.data.rtt_open == 100
        assert nip66.rtt_metadata.data.rtt_read == 50
        assert nip66.rtt_metadata.data.rtt_write is None

    def test_to_relay_metadata_rtt_only(self) -> None:
        """Test NIP-66 to_relay_metadata_tuple with RTT data only."""
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(relay, rtt_data={"rtt_open": 100})

        metadata_tuple = nip66.to_relay_metadata_tuple()

        assert metadata_tuple.nip66_rtt is not None
        assert metadata_tuple.nip66_rtt.metadata.type == "nip66_rtt"
        assert metadata_tuple.nip66_rtt.relay == relay
        # Metadata is nested under "data" key (from to_dict())
        assert metadata_tuple.nip66_rtt.metadata.value["data"]["rtt_open"] == 100
        assert metadata_tuple.nip66_ssl is None
        assert metadata_tuple.nip66_geo is None
        assert metadata_tuple.nip66_net is None
        assert metadata_tuple.nip66_dns is None
        assert metadata_tuple.nip66_http is None

    def test_to_relay_metadata_with_geo(self) -> None:
        """Test NIP-66 to_relay_metadata_tuple with RTT and geo data."""
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(
            relay,
            rtt_data={"rtt_open": 100},
            geo_data={"geohash": "abc123", "geo_country": "US"},
        )

        metadata_tuple = nip66.to_relay_metadata_tuple()

        assert metadata_tuple.nip66_rtt is not None
        assert metadata_tuple.nip66_rtt.metadata.type == "nip66_rtt"
        # Metadata is nested under "data" key (from to_dict())
        assert metadata_tuple.nip66_rtt.metadata.value["data"]["rtt_open"] == 100
        assert metadata_tuple.nip66_ssl is None
        assert metadata_tuple.nip66_geo is not None
        assert metadata_tuple.nip66_geo.metadata.type == "nip66_geo"
        assert metadata_tuple.nip66_geo.metadata.value["data"]["geohash"] == "abc123"
        assert metadata_tuple.nip66_geo.metadata.value["data"]["geo_country"] == "US"
        assert metadata_tuple.nip66_net is None
        assert metadata_tuple.nip66_dns is None
        assert metadata_tuple.nip66_http is None

    def test_to_relay_metadata_with_ssl(self) -> None:
        """Test NIP-66 to_relay_metadata_tuple with RTT and SSL data."""
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(
            relay,
            rtt_data={"rtt_open": 100},
            ssl_data={"ssl_valid": True, "ssl_issuer": "Let's Encrypt"},
        )

        metadata_tuple = nip66.to_relay_metadata_tuple()

        assert metadata_tuple.nip66_rtt is not None
        assert metadata_tuple.nip66_rtt.metadata.type == "nip66_rtt"
        assert metadata_tuple.nip66_ssl is not None
        assert metadata_tuple.nip66_ssl.metadata.type == "nip66_ssl"
        # Metadata is nested under "data" key (from to_dict())
        assert metadata_tuple.nip66_ssl.metadata.value["data"]["ssl_valid"] is True
        assert metadata_tuple.nip66_ssl.metadata.value["data"]["ssl_issuer"] == "Let's Encrypt"
        assert metadata_tuple.nip66_geo is None
        assert metadata_tuple.nip66_net is None
        assert metadata_tuple.nip66_dns is None
        assert metadata_tuple.nip66_http is None

    def test_to_relay_metadata_with_net(self) -> None:
        """Test NIP-66 to_relay_metadata_tuple with RTT and net data."""
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(
            relay,
            rtt_data={"rtt_open": 100},
            net_data={"net_ip": "8.8.8.8", "net_asn": 15169},
        )

        metadata_tuple = nip66.to_relay_metadata_tuple()

        assert metadata_tuple.nip66_rtt is not None
        assert metadata_tuple.nip66_net is not None
        assert metadata_tuple.nip66_net.metadata.type == "nip66_net"
        # Metadata is nested under "data" key (from to_dict())
        assert metadata_tuple.nip66_net.metadata.value["data"]["net_ip"] == "8.8.8.8"
        assert metadata_tuple.nip66_net.metadata.value["data"]["net_asn"] == 15169

    def test_to_relay_metadata_with_dns(self) -> None:
        """Test NIP-66 to_relay_metadata_tuple with RTT and DNS data."""
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(
            relay,
            rtt_data={"rtt_open": 100},
            dns_data={"dns_resolved": True},
        )

        metadata_tuple = nip66.to_relay_metadata_tuple()

        assert metadata_tuple.nip66_rtt is not None
        assert metadata_tuple.nip66_dns is not None
        assert metadata_tuple.nip66_dns.metadata.type == "nip66_dns"

    def test_to_relay_metadata_with_http(self) -> None:
        """Test NIP-66 to_relay_metadata_tuple with RTT and HTTP data."""
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(
            relay,
            rtt_data={"rtt_open": 100},
            http_data={"http_server": "nginx"},
        )

        metadata_tuple = nip66.to_relay_metadata_tuple()

        assert metadata_tuple.nip66_rtt is not None
        assert metadata_tuple.nip66_http is not None
        assert metadata_tuple.nip66_http.metadata.type == "nip66_http"

    def test_to_relay_metadata_with_all(self) -> None:
        """Test NIP-66 to_relay_metadata_tuple with all metadata types."""
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(
            relay,
            rtt_data={"rtt_open": 100},
            ssl_data={"ssl_valid": True, "ssl_issuer": "Let's Encrypt"},
            geo_data={"geohash": "abc123", "geo_country": "US"},
            net_data={"net_ip": "8.8.8.8"},
            dns_data={"dns_resolved": True},
            http_data={"http_server": "nginx"},
        )

        metadata_tuple = nip66.to_relay_metadata_tuple()

        assert metadata_tuple.nip66_rtt is not None
        assert metadata_tuple.nip66_rtt.metadata.type == "nip66_rtt"
        assert metadata_tuple.nip66_ssl is not None
        assert metadata_tuple.nip66_ssl.metadata.type == "nip66_ssl"
        # Metadata is nested under "data" key (from to_dict())
        assert metadata_tuple.nip66_ssl.metadata.value["data"]["ssl_valid"] is True
        assert metadata_tuple.nip66_ssl.metadata.value["data"]["ssl_issuer"] == "Let's Encrypt"
        assert metadata_tuple.nip66_geo is not None
        assert metadata_tuple.nip66_geo.metadata.type == "nip66_geo"
        assert metadata_tuple.nip66_geo.metadata.value["data"]["geohash"] == "abc123"
        assert metadata_tuple.nip66_geo.metadata.value["data"]["geo_country"] == "US"
        # Net, DNS and HTTP are also present
        assert metadata_tuple.nip66_net is not None
        assert metadata_tuple.nip66_dns is not None
        assert metadata_tuple.nip66_http is not None

    def test_ssl_metadata_access(self) -> None:
        """Test NIP-66 SSL metadata access via data attributes."""
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(
            relay,
            rtt_data={"rtt_open": 100},
            ssl_data={"ssl_valid": True, "ssl_issuer": "Let's Encrypt", "ssl_expires": 1700000000},
        )

        assert nip66.ssl_metadata is not None
        assert nip66.ssl_metadata.data.ssl_valid is True
        assert nip66.ssl_metadata.data.ssl_issuer == "Let's Encrypt"
        assert nip66.ssl_metadata.data.ssl_expires == 1700000000

    def test_ssl_metadata_none(self) -> None:
        """Test NIP-66 SSL metadata when not provided."""
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(relay, rtt_data={"rtt_open": 100})

        assert nip66.ssl_metadata is None

    def test_rtt_logs_access(self) -> None:
        """Test NIP-66 RTT logs access (probe data is in logs)."""
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(
            relay,
            rtt_data={"rtt_open": 100},
        )

        # Probe data is now in RTT logs
        assert nip66.rtt_metadata is not None
        assert nip66.rtt_metadata.logs.open_success is True


class TestRelayMetadataType:
    """Tests for RelayMetadata dataclass."""

    def test_creation(self) -> None:
        """Test RelayMetadata creation."""
        from models import MetadataType
        from models.metadata import Metadata

        relay = Relay("wss://relay.example.com")
        metadata_obj = Metadata(type=MetadataType.NIP11_FETCH, value={"name": "Test"})

        rm = RelayMetadata(
            relay=relay,
            metadata=metadata_obj,
            generated_at=1700000001,
        )

        assert "relay.example.com" in rm.relay.url
        assert rm.relay.network == NetworkType.CLEARNET
        assert rm.metadata.type == MetadataType.NIP11_FETCH
        assert rm.metadata.value == {"name": "Test"}
        assert rm.generated_at == 1700000001

    def test_to_db_params(self) -> None:
        """Test RelayMetadata to_db_params for database insertion."""
        from models import MetadataType
        from models.metadata import Metadata

        relay = Relay("wss://relay.example.com")
        metadata_obj = Metadata(type=MetadataType.NIP66_RTT, value={"rtt_open": 100})

        rm = RelayMetadata(
            relay=relay,
            metadata=metadata_obj,
            generated_at=1700000001,
        )

        params = rm.to_db_params()

        # 7 params: relay_url, network, discovered_at, metadata_id, metadata_value, type, generated_at
        assert len(params) == 7
        assert params[0] == "wss://relay.example.com"  # relay_url with scheme
        assert params[1] == "clearnet"  # network
        assert isinstance(params[3], bytes) and len(params[3]) == 32  # metadata_id (SHA-256)
        assert params[4] == metadata_obj.to_db_params().value  # metadata as JSON string
        assert params[5] == "nip66_rtt"  # metadata_type
        assert params[6] == 1700000001  # generated_at


# ============================================================================
# Monitor Initialization Tests
# ============================================================================


class TestMonitorInit:
    """Tests for Monitor initialization."""

    def test_init_with_defaults(self, mock_brotr: Brotr, tmp_path: Path) -> None:
        """Test initialization with defaults (geo/net disabled)."""
        config = MonitorConfig(
            processing=ProcessingConfig(
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
            processing=ProcessingConfig(
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
    async def test_fetch_chunk_empty(self, mock_brotr: Brotr, tmp_path: Path) -> None:
        """Test fetching relays when none need checking."""
        mock_brotr.pool.fetch = AsyncMock(return_value=[])  # type: ignore[method-assign]

        config = MonitorConfig(
            processing=ProcessingConfig(
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

    @pytest.mark.asyncio
    async def test_fetch_chunk_with_results(self, mock_brotr: Brotr, tmp_path: Path) -> None:
        """Test fetching relays that need checking."""
        mock_brotr.pool.fetch = AsyncMock(  # type: ignore[method-assign]
            return_value=[
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
        )

        config = MonitorConfig(
            processing=ProcessingConfig(
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
    async def test_fetch_chunk_filters_invalid_urls(
        self, mock_brotr: Brotr, tmp_path: Path
    ) -> None:
        """Test fetching relays filters invalid URLs."""
        mock_brotr.pool.fetch = AsyncMock(  # type: ignore[method-assign]
            return_value=[
                {
                    "url": "wss://valid.relay.com",
                    "network": "clearnet",
                    "discovered_at": 1700000000,
                },
                {"url": "invalid-url", "network": "unknown", "discovered_at": 1700000000},
            ]
        )

        config = MonitorConfig(
            processing=ProcessingConfig(
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
    async def test_fetch_chunk_respects_limit(self, mock_brotr: Brotr, tmp_path: Path) -> None:
        """Test that fetch_chunk respects the limit parameter."""
        mock_brotr.pool.fetch = AsyncMock(  # type: ignore[method-assign]
            return_value=[
                {
                    "url": "wss://relay1.example.com",
                    "network": "clearnet",
                    "discovered_at": 1700000000,
                },
            ]
        )

        config = MonitorConfig(
            processing=ProcessingConfig(
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

        # Verify limit was passed to fetch call
        # Args: query, networks, threshold, limit
        call_args = mock_brotr.pool.fetch.call_args  # type: ignore[attr-defined]
        assert call_args[0][3] == 50  # Fourth positional arg is the limit


# ============================================================================
# Monitor Run Tests
# ============================================================================


class TestMonitorRun:
    """Tests for Monitor.run() method."""

    @pytest.mark.asyncio
    async def test_run_no_relays(self, mock_brotr: Brotr, tmp_path: Path) -> None:
        """Test run cycle with no relays to check."""
        # Mock pool methods
        mock_brotr.pool.fetchrow = AsyncMock(return_value={"count": 0})  # type: ignore[method-assign]
        mock_brotr.pool.fetch = AsyncMock(return_value=[])  # type: ignore[method-assign]
        mock_brotr.get_service_data = AsyncMock(return_value=[])  # type: ignore[method-assign]

        config = MonitorConfig(
            processing=ProcessingConfig(
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
    async def test_run_resets_progress(self, mock_brotr: Brotr, tmp_path: Path) -> None:
        """Test run cycle resets progress at start."""
        mock_brotr.pool.fetchrow = AsyncMock(return_value={"count": 0})  # type: ignore[method-assign]
        mock_brotr.pool.fetch = AsyncMock(return_value=[])  # type: ignore[method-assign]
        mock_brotr.get_service_data = AsyncMock(return_value=[])  # type: ignore[method-assign]

        config = MonitorConfig(
            processing=ProcessingConfig(
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
        mock_brotr.upsert_service_data = AsyncMock(return_value=None)  # type: ignore[method-assign]

        config = MonitorConfig(
            processing=ProcessingConfig(
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
        from models import Metadata

        mock_brotr.insert_relay_metadata = AsyncMock(return_value=2)  # type: ignore[method-assign]
        mock_brotr.upsert_service_data = AsyncMock(return_value=None)  # type: ignore[method-assign]

        config = MonitorConfig(
            processing=ProcessingConfig(
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
            nip11=None, rtt=rtt1, probe=None, ssl=None, geo=None, net=None, dns=None, http=None
        )
        result2 = CheckResult(
            nip11=None, rtt=rtt2, probe=None, ssl=None, geo=None, net=None, dns=None, http=None
        )

        successful = [(relay1, result1), (relay2, result2)]
        await monitor._persist_results(successful, [])

        mock_brotr.insert_relay_metadata.assert_called_once()  # type: ignore[attr-defined]
        mock_brotr.upsert_service_data.assert_called_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_persist_results_with_failed(self, mock_brotr: Brotr, tmp_path: Path) -> None:
        """Test persisting failed check results updates checkpoint."""
        mock_brotr.insert_relay_metadata = AsyncMock(return_value=0)  # type: ignore[method-assign]
        mock_brotr.upsert_service_data = AsyncMock(return_value=None)  # type: ignore[method-assign]

        config = MonitorConfig(
            processing=ProcessingConfig(
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
        mock_brotr.upsert_service_data.assert_called_once()  # type: ignore[attr-defined]


# ============================================================================
# Network Configuration Tests
# ============================================================================


class TestMonitorNetworkConfiguration:
    """Tests for network configuration in Monitor."""

    def test_enabled_networks_default(self, mock_brotr: Brotr) -> None:
        """Test default enabled networks via config.networks."""
        config = MonitorConfig(
            processing=ProcessingConfig(
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
            processing=ProcessingConfig(
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
