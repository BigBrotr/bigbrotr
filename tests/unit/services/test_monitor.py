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
    DiscoveryConfig,
    GeoConfig,
    MetadataFlags,
    Monitor,
    MonitorConfig,
    ProcessingConfig,
    ProfileConfig,
)
from utils.network import NetworkConfig, NetworkTypeConfig


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
        assert config.update_frequency == "monthly"

    def test_custom_paths(self) -> None:
        """Test custom database paths."""
        config = GeoConfig(
            city_database_path="/custom/path/city.mmdb",
            asn_database_path="/custom/path/asn.mmdb",
            update_frequency="weekly",
        )

        assert config.city_database_path == "/custom/path/city.mmdb"
        assert config.asn_database_path == "/custom/path/asn.mmdb"
        assert config.update_frequency == "weekly"


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
        assert config.monitored_relay is True
        assert config.configured_relays is True
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


# ============================================================================
# Helper Functions for Test Data Creation
# ============================================================================


def _create_nip11(relay: Relay, data: dict | None = None, generated_at: int = 1700000001) -> Nip11:
    """Create a Nip11 instance using object.__new__ pattern."""
    from models import Metadata

    if data is None:
        data = {}
    metadata = Metadata(data)
    instance = object.__new__(Nip11)
    object.__setattr__(instance, "relay", relay)
    object.__setattr__(instance, "metadata", metadata)
    object.__setattr__(instance, "generated_at", generated_at)
    return instance


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
    """Create a Nip66 instance using object.__new__ pattern."""
    from models import Metadata

    if rtt_data is None:
        rtt_data = {}
    rtt_metadata = Metadata(rtt_data)
    ssl_metadata = Metadata(ssl_data) if ssl_data else None
    geo_metadata = Metadata(geo_data) if geo_data else None
    net_metadata = Metadata(net_data) if net_data else None
    dns_metadata = Metadata(dns_data) if dns_data else None
    http_metadata = Metadata(http_data) if http_data else None

    instance = object.__new__(Nip66)
    object.__setattr__(instance, "relay", relay)
    object.__setattr__(instance, "rtt_metadata", rtt_metadata)
    object.__setattr__(instance, "ssl_metadata", ssl_metadata)
    object.__setattr__(instance, "geo_metadata", geo_metadata)
    object.__setattr__(instance, "net_metadata", net_metadata)
    object.__setattr__(instance, "dns_metadata", dns_metadata)
    object.__setattr__(instance, "http_metadata", http_metadata)
    object.__setattr__(instance, "generated_at", generated_at)
    return instance


# ============================================================================
# NIP-66 Data Classes Tests
# ============================================================================


class TestNip11:
    """Tests for Nip11 dataclass."""

    def test_default_values(self) -> None:
        """Test NIP-11 with empty data."""
        relay = Relay("wss://relay.example.com")
        data = _create_nip11(relay, {})

        assert data.name is None
        assert data.supported_nips is None

    def test_properties(self) -> None:
        """Test NIP-11 property access."""
        relay = Relay("wss://relay.example.com")
        data = _create_nip11(relay, {"name": "Test Relay", "supported_nips": [1, 11, 66]})

        assert data.name == "Test Relay"
        assert data.supported_nips == [1, 11, 66]

    def test_to_relay_metadata(self) -> None:
        """Test NIP-11 to_relay_metadata factory method."""
        relay = Relay("wss://relay.example.com")
        nip11 = _create_nip11(relay, {"name": "Test"})

        rm = nip11.to_relay_metadata()

        assert rm.metadata_type == "nip11"
        assert rm.relay == relay
        assert rm.metadata.data == {"name": "Test"}


class TestNip66:
    """Tests for Nip66 dataclass."""

    def test_default_values(self) -> None:
        """Test NIP-66 with empty data."""
        relay = Relay("wss://relay.example.com")
        data = _create_nip66(relay, {})

        assert data.is_openable is False
        assert data.rtt_open is None
        assert data.rtt_read is None
        assert data.rtt_write is None

    def test_properties(self) -> None:
        """Test NIP-66 property access."""
        relay = Relay("wss://relay.example.com")
        data = _create_nip66(relay, rtt_data={"rtt_open": 100, "rtt_read": 50})

        assert data.is_openable is True
        assert data.rtt_open == 100
        assert data.rtt_read == 50
        assert data.rtt_write is None

    def test_to_relay_metadata_rtt_only(self) -> None:
        """Test NIP-66 to_relay_metadata factory with RTT data only."""
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(relay, rtt_data={"rtt_open": 100})

        rtt, ssl, geo, net, dns, http = nip66.to_relay_metadata()

        assert rtt is not None
        assert rtt.metadata_type == "nip66_rtt"
        assert rtt.relay == relay
        assert rtt.metadata.data == {"rtt_open": 100}
        assert ssl is None
        assert geo is None
        assert net is None
        assert dns is None
        assert http is None

    def test_to_relay_metadata_with_geo(self) -> None:
        """Test NIP-66 to_relay_metadata factory with RTT and geo data."""
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(
            relay,
            rtt_data={"rtt_open": 100},
            geo_data={"geohash": "abc123", "geo_country": "US"},
        )

        rtt, ssl, geo, net, dns, http = nip66.to_relay_metadata()

        assert rtt is not None
        assert rtt.metadata_type == "nip66_rtt"
        assert rtt.metadata.data == {"rtt_open": 100}
        assert ssl is None
        assert geo is not None
        assert geo.metadata_type == "nip66_geo"
        assert geo.metadata.data == {"geohash": "abc123", "geo_country": "US"}
        assert net is None
        assert dns is None
        assert http is None

    def test_to_relay_metadata_with_ssl(self) -> None:
        """Test NIP-66 to_relay_metadata factory with RTT and SSL data."""
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(
            relay,
            rtt_data={"rtt_open": 100},
            ssl_data={"ssl_valid": True, "ssl_issuer": "Let's Encrypt"},
        )

        rtt, ssl, geo, net, dns, http = nip66.to_relay_metadata()

        assert rtt is not None
        assert rtt.metadata_type == "nip66_rtt"
        assert rtt.metadata.data == {"rtt_open": 100}
        assert ssl is not None
        assert ssl.metadata_type == "nip66_ssl"
        assert ssl.metadata.data == {"ssl_valid": True, "ssl_issuer": "Let's Encrypt"}
        assert geo is None
        assert net is None
        assert dns is None
        assert http is None

    def test_to_relay_metadata_with_net(self) -> None:
        """Test NIP-66 to_relay_metadata factory with RTT and net data."""
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(
            relay,
            rtt_data={"rtt_open": 100},
            net_data={"net_ip": "8.8.8.8", "net_asn": 15169},
        )

        rtt, _ssl, _geo, net, _dns, _http = nip66.to_relay_metadata()

        assert rtt is not None
        assert net is not None
        assert net.metadata_type == "nip66_net"
        assert net.metadata.data == {"net_ip": "8.8.8.8", "net_asn": 15169}

    def test_to_relay_metadata_with_all(self) -> None:
        """Test NIP-66 to_relay_metadata factory with all metadata types."""
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(
            relay,
            rtt_data={"rtt_open": 100, "network": "clearnet"},
            ssl_data={"ssl_valid": True, "ssl_issuer": "Let's Encrypt"},
            geo_data={"geohash": "abc123", "geo_country": "US"},
        )

        rtt, ssl, geo, net, dns, http = nip66.to_relay_metadata()

        assert rtt is not None
        assert rtt.metadata_type == "nip66_rtt"
        assert rtt.metadata.data == {"rtt_open": 100, "network": "clearnet"}
        assert ssl is not None
        assert ssl.metadata_type == "nip66_ssl"
        assert ssl.metadata.data == {"ssl_valid": True, "ssl_issuer": "Let's Encrypt"}
        assert geo is not None
        assert geo.metadata_type == "nip66_geo"
        assert geo.metadata.data == {"geohash": "abc123", "geo_country": "US"}
        # Net, DNS and HTTP are optional
        assert net is None
        assert dns is None
        assert http is None

    def test_ssl_metadata_access(self) -> None:
        """Test NIP-66 SSL metadata access."""
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(
            relay,
            rtt_data={"rtt_open": 100},
            ssl_data={"ssl_valid": True, "ssl_issuer": "Let's Encrypt", "ssl_expires": 1700000000},
        )

        assert nip66.ssl_metadata is not None
        assert nip66.ssl_metadata.data["ssl_valid"] is True
        assert nip66.ssl_metadata.data["ssl_issuer"] == "Let's Encrypt"
        assert nip66.ssl_metadata.data["ssl_expires"] == 1700000000

    def test_ssl_metadata_none(self) -> None:
        """Test NIP-66 SSL metadata when not provided."""
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(relay, rtt_data={"rtt_open": 100})

        assert nip66.ssl_metadata is None


class TestRelayMetadataType:
    """Tests for RelayMetadata dataclass."""

    def test_creation(self) -> None:
        """Test RelayMetadata creation."""
        from models import Metadata

        relay = Relay("wss://relay.example.com")
        metadata_obj = Metadata({"name": "Test"})

        rm = RelayMetadata(
            relay=relay,
            metadata=metadata_obj,
            metadata_type="nip11",
            generated_at=1700000001,
        )

        assert "relay.example.com" in rm.relay.url
        assert rm.relay.network == NetworkType.CLEARNET
        assert rm.metadata_type == "nip11"
        assert rm.metadata.data == {"name": "Test"}
        assert rm.generated_at == 1700000001

    def test_to_db_params(self) -> None:
        """Test RelayMetadata to_db_params for database insertion."""
        from models import Metadata

        relay = Relay("wss://relay.example.com")
        metadata_obj = Metadata({"rtt_open": 100})

        rm = RelayMetadata(
            relay=relay,
            metadata=metadata_obj,
            metadata_type="nip66_rtt",
            generated_at=1700000001,
        )

        params = rm.to_db_params()

        # 6 params: relay_url, network, discovered_at, metadata_data, type, generated_at
        assert len(params) == 6
        assert params[0] == "wss://relay.example.com"  # relay_url with scheme
        assert params[1] == "clearnet"  # network
        assert params[3] == metadata_obj.to_db_params()[0]  # metadata as JSON string
        assert params[4] == "nip66_rtt"  # metadata_type
        assert params[5] == 1700000001  # generated_at


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
            networks=NetworkConfig(tor=NetworkTypeConfig(enabled=False)),
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
        monitor._reset_cycle_state()
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
        monitor._reset_cycle_state()
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
        monitor._reset_cycle_state()
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
        monitor._reset_cycle_state()
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

        assert monitor._checked == 0


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
        metadata1 = RelayMetadata(relay1, Metadata({"rtt_open": 100}), "nip66_rtt")
        metadata2 = RelayMetadata(relay2, Metadata({"rtt_open": 200}), "nip66_rtt")

        successful = [(relay1, [metadata1]), (relay2, [metadata2])]
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
