"""
Unit tests for services.monitor module.

Tests:
- Configuration models (TorConfig, KeysConfig, TimeoutsConfig, etc.)
- Monitor service initialization
- Relay selection logic
- Metadata batch insertion
- NIP-66 data classes
"""

from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock

import pytest

from models import Nip11, Nip66, Relay, RelayMetadata
from core.brotr import Brotr
from services.monitor import (
    ChecksConfig,
    ConcurrencyConfig,
    GeoConfig,
    KeysConfig,
    Monitor,
    MonitorConfig,
    PublishingConfig,
    SelectionConfig,
    TimeoutsConfig,
    TorConfig,
    build_kind_10166_tags,
    build_kind_30166_tags,
)

# ============================================================================
# Relay Type Tests
# ============================================================================


class TestRelayType:
    """Tests for Relay dataclass."""

    def test_network_clearnet(self) -> None:
        """Test clearnet relay detection."""
        relay = Relay("wss://relay.example.com")
        assert relay.network == "clearnet"

    def test_network_tor(self) -> None:
        """Test tor relay detection."""
        relay = Relay("ws://xyz.onion:80")
        assert relay.network == "tor"


# ============================================================================
# TorConfig Tests
# ============================================================================


class TestTorConfig:
    """Tests for TorConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default Tor proxy config."""
        config = TorConfig()

        assert config.enabled is True
        assert config.host == "127.0.0.1"
        assert config.port == 9050

    def test_custom_values(self) -> None:
        """Test custom Tor proxy config."""
        config = TorConfig(enabled=False, host="tor-proxy", port=9150)

        assert config.enabled is False
        assert config.host == "tor-proxy"
        assert config.port == 9150

    def test_port_validation(self) -> None:
        """Test port validation."""
        config = TorConfig(port=9150)
        assert config.port == 9150

        with pytest.raises(ValueError):
            TorConfig(port=0)

        with pytest.raises(ValueError):
            TorConfig(port=70000)

    def test_proxy_url_property(self) -> None:
        """Test proxy_url property."""
        config = TorConfig(host="127.0.0.1", port=9050)

        assert config.proxy_url == "socks5://127.0.0.1:9050"


# ============================================================================
# KeysConfig Tests
# ============================================================================


class TestKeysConfig:
    """Tests for KeysConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default keys config (no keys)."""
        config = KeysConfig()

        assert config.keys is None

    def test_keypair_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test private key loaded from environment."""
        # Use a valid nostr private key (hex format)
        test_key = "a" * 64
        monkeypatch.setenv("PRIVATE_KEY", test_key)

        config = KeysConfig()

        assert config.keys is not None


# ============================================================================
# PublishingConfig Tests
# ============================================================================


class TestPublishingConfig:
    """Tests for PublishingConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default publishing config."""
        config = PublishingConfig()

        assert config.enabled is True
        assert config.destination == "monitored_relay"
        assert config.relays == []

    def test_custom_values(self) -> None:
        """Test custom publishing config."""
        config = PublishingConfig(
            enabled=False,
            destination="configured_relays",
            relays=["wss://relay1.com", "wss://relay2.com"],
        )

        assert config.enabled is False
        assert config.destination == "configured_relays"
        assert len(config.relays) == 2


# ============================================================================
# ChecksConfig Tests
# ============================================================================


class TestChecksConfig:
    """Tests for ChecksConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test all checks enabled by default."""
        config = ChecksConfig()

        assert config.open is True
        assert config.read is True
        assert config.write is True
        assert config.nip11 is True
        assert config.ssl is True
        assert config.dns is True
        assert config.geo is True

    def test_disable_checks(self) -> None:
        """Test disabling specific checks."""
        config = ChecksConfig(write=False, geo=False)

        assert config.write is False
        assert config.geo is False


# ============================================================================
# GeoConfig Tests
# ============================================================================


class TestGeoConfig:
    """Tests for GeoConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default geo config."""
        config = GeoConfig()

        assert config.database_path == "/usr/share/GeoIP/GeoLite2-City.mmdb"
        assert config.asn_database_path is None

    def test_custom_paths(self) -> None:
        """Test custom database paths."""
        config = GeoConfig(
            database_path="/custom/path/city.mmdb",
            asn_database_path="/custom/path/asn.mmdb",
        )

        assert config.database_path == "/custom/path/city.mmdb"
        assert config.asn_database_path == "/custom/path/asn.mmdb"


# ============================================================================
# TimeoutsConfig Tests
# ============================================================================


class TestTimeoutsConfig:
    """Tests for TimeoutsConfig."""

    def test_default_values(self) -> None:
        """Test default timeouts config."""
        config = TimeoutsConfig()

        assert config.clearnet == 30.0
        assert config.tor == 60.0

    def test_custom_values(self) -> None:
        """Test custom timeouts values."""
        config = TimeoutsConfig(clearnet=45.0, tor=90.0)

        assert config.clearnet == 45.0
        assert config.tor == 90.0

    def test_validation_constraints(self) -> None:
        """Test validation constraints."""
        with pytest.raises(ValueError):
            TimeoutsConfig(clearnet=4.0)  # Too low

        with pytest.raises(ValueError):
            TimeoutsConfig(clearnet=121.0)  # Too high

        with pytest.raises(ValueError):
            TimeoutsConfig(tor=9.0)  # Too low

        with pytest.raises(ValueError):
            TimeoutsConfig(tor=181.0)  # Too high


# ============================================================================
# ConcurrencyConfig Tests
# ============================================================================


class TestMonitorConcurrencyConfig:
    """Tests for ConcurrencyConfig (Monitor)."""

    def test_default_values(self) -> None:
        """Test default concurrency config."""
        config = ConcurrencyConfig()

        assert config.max_parallel == 50
        assert config.batch_size == 50

    def test_custom_values(self) -> None:
        """Test custom concurrency values."""
        config = ConcurrencyConfig(max_parallel=100, batch_size=100)

        assert config.max_parallel == 100
        assert config.batch_size == 100

    def test_validation_constraints(self) -> None:
        """Test validation constraints."""
        with pytest.raises(ValueError):
            ConcurrencyConfig(max_parallel=0)

        with pytest.raises(ValueError):
            ConcurrencyConfig(max_parallel=501)

        with pytest.raises(ValueError):
            ConcurrencyConfig(batch_size=0)

        with pytest.raises(ValueError):
            ConcurrencyConfig(batch_size=501)


# ============================================================================
# SelectionConfig Tests
# ============================================================================


class TestSelectionConfig:
    """Tests for SelectionConfig."""

    def test_default_values(self) -> None:
        """Test default selection config."""
        config = SelectionConfig()

        assert config.min_age_since_check == 3600

    def test_custom_values(self) -> None:
        """Test custom selection config."""
        config = SelectionConfig(min_age_since_check=0)

        assert config.min_age_since_check == 0


# ============================================================================
# MonitorConfig Tests
# ============================================================================


class TestMonitorConfig:
    """Tests for MonitorConfig Pydantic model."""

    def test_default_values_with_mocked_checks(self, tmp_path: Path) -> None:
        """Test default configuration values with mocked geo check."""
        # Create a fake geo database file
        geo_db = tmp_path / "GeoLite2-City.mmdb"
        geo_db.write_bytes(b"fake")

        config = MonitorConfig(
            publishing=PublishingConfig(destination="database_only"),
            checks=ChecksConfig(geo=False),
        )

        assert config.tor.enabled is True
        assert config.keys.keys is None
        assert config.publishing.destination == "database_only"

    def test_publishing_requires_key_validation(self, tmp_path: Path) -> None:
        """Test publishing with enabled requires private key."""
        geo_db = tmp_path / "GeoLite2-City.mmdb"
        geo_db.write_bytes(b"fake")

        # Should raise because publishing is enabled but no key
        with pytest.raises(ValueError, match="PRIVATE_KEY"):
            MonitorConfig(
                publishing=PublishingConfig(enabled=True, destination="monitored_relay"),
                checks=ChecksConfig(geo=False),
            )

    def test_publishing_database_only_no_key_required(self, tmp_path: Path) -> None:
        """Test publishing to database_only doesn't require key."""
        geo_db = tmp_path / "GeoLite2-City.mmdb"
        geo_db.write_bytes(b"fake")

        # Should not raise
        config = MonitorConfig(
            publishing=PublishingConfig(enabled=True, destination="database_only"),
            checks=ChecksConfig(geo=False),
        )

        assert config.publishing.destination == "database_only"

    def test_geo_database_validation(self) -> None:
        """Test geo check requires database file to exist."""
        with pytest.raises(ValueError, match="geo.database_path"):
            MonitorConfig(
                publishing=PublishingConfig(destination="database_only"),
                checks=ChecksConfig(geo=True),
                geo=GeoConfig(database_path="/nonexistent/path.mmdb"),
            )


# ============================================================================
# Helper Functions for Test Data Creation
# ============================================================================


def _create_nip11(relay: Relay, data: Optional[dict] = None, generated_at: int = 1700000001) -> Nip11:
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
    rtt_data: Optional[dict] = None,
    ssl_data: Optional[dict] = None,
    geo_data: Optional[dict] = None,
    generated_at: int = 1700000001,
) -> Nip66:
    """Create a Nip66 instance using object.__new__ pattern."""
    from models import Metadata

    if rtt_data is None:
        rtt_data = {}
    rtt_metadata = Metadata(rtt_data)
    ssl_metadata = Metadata(ssl_data) if ssl_data else None
    geo_metadata = Metadata(geo_data) if geo_data else None

    instance = object.__new__(Nip66)
    object.__setattr__(instance, "relay", relay)
    object.__setattr__(instance, "rtt_metadata", rtt_metadata)
    object.__setattr__(instance, "ssl_metadata", ssl_metadata)
    object.__setattr__(instance, "geo_metadata", geo_metadata)
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
        assert data.supported_nips == []

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
        assert data.is_readable is False
        assert data.is_writable is False
        assert data.rtt_open is None

    def test_properties(self) -> None:
        """Test NIP-66 property access."""
        relay = Relay("wss://relay.example.com")
        data = _create_nip66(relay, rtt_data={"rtt_open": 100, "rtt_read": 50})

        assert data.is_openable is True
        assert data.is_readable is True
        assert data.is_writable is False
        assert data.rtt_open == 100
        assert data.rtt_read == 50

    def test_to_relay_metadata_rtt_only(self) -> None:
        """Test NIP-66 to_relay_metadata factory with RTT data only."""
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(relay, rtt_data={"rtt_open": 100})

        rm_list = nip66.to_relay_metadata()

        assert len(rm_list) == 1
        assert rm_list[0].metadata_type == "nip66_rtt"
        assert rm_list[0].relay == relay
        assert rm_list[0].metadata.data == {"rtt_open": 100}

    def test_to_relay_metadata_with_geo(self) -> None:
        """Test NIP-66 to_relay_metadata factory with RTT and geo data."""
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(
            relay,
            rtt_data={"rtt_open": 100},
            geo_data={"geohash": "abc123", "geo_country": "US"},
        )

        rm_list = nip66.to_relay_metadata()

        assert len(rm_list) == 2
        assert rm_list[0].metadata_type == "nip66_rtt"
        assert rm_list[0].metadata.data == {"rtt_open": 100}
        assert rm_list[1].metadata_type == "nip66_geo"
        assert rm_list[1].metadata.data == {"geohash": "abc123", "geo_country": "US"}

    def test_to_relay_metadata_with_ssl(self) -> None:
        """Test NIP-66 to_relay_metadata factory with RTT and SSL data."""
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(
            relay,
            rtt_data={"rtt_open": 100},
            ssl_data={"ssl_valid": True, "ssl_issuer": "Let's Encrypt"},
        )

        rm_list = nip66.to_relay_metadata()

        assert len(rm_list) == 2
        assert rm_list[0].metadata_type == "nip66_rtt"
        assert rm_list[0].metadata.data == {"rtt_open": 100}
        assert rm_list[1].metadata_type == "nip66_ssl"
        assert rm_list[1].metadata.data == {"ssl_valid": True, "ssl_issuer": "Let's Encrypt"}

    def test_to_relay_metadata_with_all(self) -> None:
        """Test NIP-66 to_relay_metadata factory with RTT, SSL, and geo data."""
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(
            relay,
            rtt_data={"rtt_open": 100, "network": "clearnet"},
            ssl_data={"ssl_valid": True, "ssl_issuer": "Let's Encrypt"},
            geo_data={"geohash": "abc123", "geo_country": "US"},
        )

        rm_list = nip66.to_relay_metadata()

        assert len(rm_list) == 3
        assert rm_list[0].metadata_type == "nip66_rtt"
        assert rm_list[0].metadata.data == {"rtt_open": 100, "network": "clearnet"}
        assert rm_list[1].metadata_type == "nip66_ssl"
        assert rm_list[1].metadata.data == {"ssl_valid": True, "ssl_issuer": "Let's Encrypt"}
        assert rm_list[2].metadata_type == "nip66_geo"
        assert rm_list[2].metadata.data == {"geohash": "abc123", "geo_country": "US"}

    def test_ssl_properties(self) -> None:
        """Test NIP-66 SSL property access."""
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(
            relay,
            rtt_data={"rtt_open": 100},
            ssl_data={"ssl_valid": True, "ssl_issuer": "Let's Encrypt", "ssl_expires": 1700000000},
        )

        assert nip66.has_ssl is True
        assert nip66.ssl_valid is True
        assert nip66.ssl_issuer == "Let's Encrypt"
        assert nip66.ssl_expires == 1700000000

    def test_ssl_properties_no_ssl(self) -> None:
        """Test NIP-66 SSL properties when SSL metadata is None."""
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(relay, rtt_data={"rtt_open": 100})

        assert nip66.has_ssl is False
        assert nip66.ssl_valid is None
        assert nip66.ssl_issuer is None
        assert nip66.ssl_expires is None


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
        assert rm.relay.network == "clearnet"
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

        # 6 params: relay_url, network, inserted_at, generated_at, type, data_jsonb
        assert len(params) == 6
        assert params[0] == "relay.example.com"  # relay_url without scheme
        assert params[1] == "clearnet"  # network
        assert params[3] == 1700000001  # generated_at
        assert params[4] == "nip66_rtt"  # metadata_type
        assert params[5] == metadata_obj.data_jsonb  # metadata as JSON string


# ============================================================================
# Tag Building Tests
# ============================================================================


class TestBuildKind30166Tags:
    """Tests for build_kind_30166_tags function."""

    def test_basic_tags(self) -> None:
        """Test basic tag generation."""
        relay = Relay("wss://relay.example.com")

        tags = build_kind_30166_tags(relay, None, None)

        # Extract tag values for easier testing
        tag_dict = {tag.as_vec()[0]: tag.as_vec()[1:] for tag in tags}

        assert "d" in tag_dict
        assert "relay.example.com" in tag_dict["d"][0]
        assert "n" in tag_dict
        assert tag_dict["n"][0] == "clearnet"

    def test_with_nip66_data(self) -> None:
        """Test tags with NIP-66 data."""
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(relay, rtt_data={"rtt_open": 100, "rtt_read": 50})

        tags = build_kind_30166_tags(relay, None, nip66)

        tag_dict = {tag.as_vec()[0]: tag.as_vec()[1:] for tag in tags}

        assert "rtt-open" in tag_dict
        assert tag_dict["rtt-open"][0] == "100"
        assert "rtt-read" in tag_dict
        assert tag_dict["rtt-read"][0] == "50"

    def test_with_nip11_data(self) -> None:
        """Test tags with NIP-11 data."""
        relay = Relay("wss://relay.example.com")
        nip11 = _create_nip11(relay, {"supported_nips": [1, 11, 66]})

        tags = build_kind_30166_tags(relay, nip11, None)

        # Count N tags
        n_tags = [tag for tag in tags if tag.as_vec()[0] == "N"]

        assert len(n_tags) == 3


class TestBuildKind10166Tags:
    """Tests for build_kind_10166_tags function."""

    def test_basic_announcement_tags(self, tmp_path: Path) -> None:
        """Test basic announcement tag generation."""
        geo_db = tmp_path / "GeoLite2-City.mmdb"
        geo_db.write_bytes(b"fake")

        config = MonitorConfig(
            interval=3600,
            publishing=PublishingConfig(destination="database_only"),
            checks=ChecksConfig(geo=False),
        )

        tags = build_kind_10166_tags(config)

        tag_dict = {tag.as_vec()[0]: tag.as_vec()[1:] for tag in tags}

        assert "frequency" in tag_dict
        assert tag_dict["frequency"][0] == "3600"


# ============================================================================
# Monitor Initialization Tests
# ============================================================================


class TestMonitorInit:
    """Tests for Monitor initialization."""

    def test_init_with_defaults(self, mock_brotr: Brotr, tmp_path: Path) -> None:
        """Test initialization with defaults."""
        geo_db = tmp_path / "GeoLite2-City.mmdb"
        geo_db.write_bytes(b"fake")

        config = MonitorConfig(
            publishing=PublishingConfig(destination="database_only"),
            checks=ChecksConfig(geo=False),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)

        assert monitor._brotr is mock_brotr
        assert monitor.SERVICE_NAME == "monitor"

    def test_init_with_custom_config(self, mock_brotr: Brotr, tmp_path: Path) -> None:
        """Test initialization with custom config."""
        geo_db = tmp_path / "GeoLite2-City.mmdb"
        geo_db.write_bytes(b"fake")

        config = MonitorConfig(
            tor=TorConfig(enabled=False),
            selection=SelectionConfig(min_age_since_check=7200),
            publishing=PublishingConfig(destination="database_only"),
            checks=ChecksConfig(geo=False),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)

        assert monitor.config.tor.enabled is False
        assert monitor.config.selection.min_age_since_check == 7200


# ============================================================================
# Monitor Fetch Relays Tests
# ============================================================================


class TestMonitorFetchRelays:
    """Tests for Monitor._fetch_relays_to_check() method."""

    @pytest.mark.asyncio
    async def test_fetch_relays_empty(self, mock_brotr: Brotr, tmp_path: Path) -> None:
        """Test fetching relays when none need checking."""
        geo_db = tmp_path / "GeoLite2-City.mmdb"
        geo_db.write_bytes(b"fake")

        mock_brotr.pool._mock_connection.fetch = AsyncMock(return_value=[])  # type: ignore[attr-defined]

        config = MonitorConfig(
            publishing=PublishingConfig(destination="database_only"),
            checks=ChecksConfig(geo=False),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)
        relays = await monitor._fetch_relays_to_check()

        assert relays == []

    @pytest.mark.asyncio
    async def test_fetch_relays_with_results(self, mock_brotr: Brotr, tmp_path: Path) -> None:
        """Test fetching relays that need checking."""
        geo_db = tmp_path / "GeoLite2-City.mmdb"
        geo_db.write_bytes(b"fake")

        mock_brotr.pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            side_effect=[
                [],  # First call: get_service_data returns no checkpoints
                [  # Second call: relay query
                    {"url": "wss://relay1.example.com", "network": "clearnet", "discovered_at": 1700000000},
                    {"url": "wss://relay2.example.com", "network": "clearnet", "discovered_at": 1700000000},
                ]
            ]
        )

        config = MonitorConfig(
            publishing=PublishingConfig(destination="database_only"),
            checks=ChecksConfig(geo=False),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)
        relays = await monitor._fetch_relays_to_check()

        assert len(relays) == 2
        # relays is now list[Relay], url is RelayUrl
        assert "relay1.example.com" in str(relays[0].url)
        assert "relay2.example.com" in str(relays[1].url)

    @pytest.mark.asyncio
    async def test_fetch_relays_filters_invalid_urls(self, mock_brotr: Brotr, tmp_path: Path) -> None:
        """Test fetching relays filters invalid URLs."""
        geo_db = tmp_path / "GeoLite2-City.mmdb"
        geo_db.write_bytes(b"fake")

        mock_brotr.pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            side_effect=[
                [],  # First call: get_service_data returns no checkpoints
                [  # Second call: relay query
                    {"url": "wss://valid.relay.com", "network": "clearnet", "discovered_at": 1700000000},
                    {"url": "invalid-url", "network": "unknown", "discovered_at": 1700000000},
                ]
            ]
        )

        config = MonitorConfig(
            publishing=PublishingConfig(destination="database_only"),
            checks=ChecksConfig(geo=False),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)
        relays = await monitor._fetch_relays_to_check()

        assert len(relays) == 1
        # relays is now list[Relay], url is RelayUrl
        assert "valid.relay.com" in str(relays[0].url)

    @pytest.mark.asyncio
    async def test_fetch_relays_skips_tor_when_disabled(self, mock_brotr: Brotr, tmp_path: Path) -> None:
        """Test .onion relays skipped when Tor disabled."""
        geo_db = tmp_path / "GeoLite2-City.mmdb"
        geo_db.write_bytes(b"fake")

        onion_url = "ws://oxtrdevav64z64yb7x6rjg4ntzqjhedm5b5zjqulugknhzr46ny2qbad.onion"
        mock_brotr.pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            side_effect=[
                [],  # First call: get_service_data returns no checkpoints
                [  # Second call: relay query
                    {"url": "wss://clearnet.relay.com", "network": "clearnet", "discovered_at": 1700000000},
                    {"url": onion_url, "network": "tor", "discovered_at": 1700000000},
                ]
            ]
        )

        config = MonitorConfig(
            tor=TorConfig(enabled=False),
            publishing=PublishingConfig(destination="database_only"),
            checks=ChecksConfig(geo=False),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)
        relays = await monitor._fetch_relays_to_check()

        assert len(relays) == 1
        # relays is now list[Relay], url is RelayUrl
        assert "clearnet.relay.com" in str(relays[0].url)


# ============================================================================
# Monitor Run Tests
# ============================================================================


class TestMonitorRun:
    """Tests for Monitor.run() method."""

    @pytest.mark.asyncio
    async def test_run_no_relays(self, mock_brotr: Brotr, tmp_path: Path) -> None:
        """Test run cycle with no relays to check."""
        geo_db = tmp_path / "GeoLite2-City.mmdb"
        geo_db.write_bytes(b"fake")

        mock_brotr.pool._mock_connection.fetch = AsyncMock(return_value=[])  # type: ignore[attr-defined]

        config = MonitorConfig(
            publishing=PublishingConfig(destination="database_only"),
            checks=ChecksConfig(geo=False),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)
        await monitor.run()

        assert monitor._checked_relays == 0


# ============================================================================
# Monitor Insert Metadata Tests
# ============================================================================


class TestMonitorInsertMetadata:
    """Tests for Monitor._insert_metadata_batch() method."""

    @pytest.mark.asyncio
    async def test_insert_metadata_empty(self, mock_brotr: Brotr, tmp_path: Path) -> None:
        """Test inserting empty metadata batch."""
        geo_db = tmp_path / "GeoLite2-City.mmdb"
        geo_db.write_bytes(b"fake")

        mock_brotr.insert_relay_metadata = AsyncMock(return_value=0)  # type: ignore[attr-defined]

        config = MonitorConfig(
            publishing=PublishingConfig(destination="database_only"),
            checks=ChecksConfig(geo=False),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)
        await monitor._insert_metadata_batch([])

        mock_brotr.insert_relay_metadata.assert_not_called()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_insert_metadata_success(self, mock_brotr: Brotr, tmp_path: Path) -> None:
        """Test successful metadata batch insertion."""
        geo_db = tmp_path / "GeoLite2-City.mmdb"
        geo_db.write_bytes(b"fake")

        mock_brotr.insert_relay_metadata = AsyncMock(return_value=2)  # type: ignore[attr-defined]

        config = MonitorConfig(
            publishing=PublishingConfig(destination="database_only"),
            checks=ChecksConfig(geo=False),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)
        metadata = [
            {"relay_url": "wss://relay1.example.com/", "generated_at": 123456},
            {"relay_url": "wss://relay2.example.com/", "generated_at": 123456},
        ]
        await monitor._insert_metadata_batch(metadata)

        mock_brotr.insert_relay_metadata.assert_called_once_with(metadata)  # type: ignore[attr-defined]
