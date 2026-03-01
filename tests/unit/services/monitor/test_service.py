"""Unit tests for services.monitor.service module.

Tests:
- Nip11 / Nip66 dataclass construction and metadata tuple conversion
- RelayMetadata creation and DB params
- Monitor initialization and configuration
- Monitor fetch relays, run cycle
- Monitor persist results
- Network configuration
- Publishing relay getters
- Publishing: announcement, profile, relay discoveries
- Event builders: Kind 0, 10166, 30166
- End-to-end tag generation
- Metrics counter emissions
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

from bigbrotr.core.brotr import Brotr
from bigbrotr.models import Relay, RelayMetadata
from bigbrotr.models.constants import NetworkType, ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType
from bigbrotr.nips.nip11.data import Nip11InfoDataLimitation
from bigbrotr.services.common.configs import ClearnetConfig, NetworksConfig, TorConfig
from bigbrotr.services.monitor import (
    AnnouncementConfig,
    CheckResult,
    DiscoveryConfig,
    MetadataFlags,
    Monitor,
    MonitorConfig,
    ProcessingConfig,
    ProfileConfig,
    PublishingConfig,
)
from tests.unit.services.monitor.conftest import (
    _create_nip11,
    _create_nip66,
    _make_check_result,
    _make_nip11_meta,
    _make_rtt_meta,
    _make_ssl_meta,
    _MonitorStub,
)


if TYPE_CHECKING:
    from pathlib import Path

    from nostr_sdk import Keys


# ============================================================================
# NIP-11 Tests
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


# ============================================================================
# NIP-66 Tests
# ============================================================================


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


# ============================================================================
# RelayMetadata Tests
# ============================================================================


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
            networks=NetworksConfig(tor=TorConfig(enabled=False)),
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


class TestMonitorFetchRelays:
    """Tests for Monitor._fetch_relays() method."""

    @patch(
        "bigbrotr.services.monitor.service.fetch_relays_to_monitor",
        new_callable=AsyncMock,
        return_value=[],
    )
    async def test_fetch_relays_empty(
        self, mock_fetch: AsyncMock, mock_brotr: Brotr, tmp_path: Path
    ) -> None:
        """Test fetching relays when none need checking."""
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
        monitor.chunk_progress.reset()
        relays = await monitor._fetch_relays([NetworkType.CLEARNET])

        assert relays == []
        mock_fetch.assert_awaited_once()

    @patch("bigbrotr.services.monitor.service.fetch_relays_to_monitor", new_callable=AsyncMock)
    async def test_fetch_relays_with_results(
        self, mock_fetch: AsyncMock, mock_brotr: Brotr, tmp_path: Path
    ) -> None:
        """Test fetching relays that need checking."""
        mock_fetch.return_value = [
            Relay("wss://relay1.example.com"),
            Relay("wss://relay2.example.com"),
        ]

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
        monitor.chunk_progress.reset()
        relays = await monitor._fetch_relays([NetworkType.CLEARNET])

        assert len(relays) == 2
        assert relays[0].url == "wss://relay1.example.com"
        assert relays[1].url == "wss://relay2.example.com"


# ============================================================================
# Monitor Run Tests
# ============================================================================


class TestMonitorRun:
    """Tests for Monitor.run() method."""

    @patch(
        "bigbrotr.services.monitor.service.fetch_relays_to_monitor",
        new_callable=AsyncMock,
        return_value=[],
    )
    async def test_run_no_relays(
        self,
        mock_fetch: AsyncMock,
        mock_brotr: Brotr,
        tmp_path: Path,
    ) -> None:
        """Test run cycle with no relays to check."""
        mock_brotr.get_service_state = AsyncMock(return_value=[])  # type: ignore[method-assign]

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

        assert monitor.chunk_progress.processed == 0

    @patch(
        "bigbrotr.services.monitor.service.fetch_relays_to_monitor",
        new_callable=AsyncMock,
        return_value=[],
    )
    async def test_run_resets_progress(
        self,
        mock_fetch: AsyncMock,
        mock_brotr: Brotr,
        tmp_path: Path,
    ) -> None:
        """Test run cycle resets progress at start."""
        mock_brotr.get_service_state = AsyncMock(return_value=[])  # type: ignore[method-assign]

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
        monitor.chunk_progress.succeeded = 10
        monitor.chunk_progress.failed = 5

        await monitor.run()

        assert monitor.chunk_progress.succeeded == 0
        assert monitor.chunk_progress.failed == 0


# ============================================================================
# Monitor Persist Results Tests
# ============================================================================


class TestMonitorPersistResults:
    """Tests for Monitor._persist_results() method."""

    async def test_persist_results_empty(self, mock_brotr: Brotr, tmp_path: Path) -> None:
        """Test persisting empty results batch."""
        mock_brotr.insert_relay_metadata = AsyncMock(return_value=0)  # type: ignore[method-assign]
        mock_brotr.upsert_service_state = AsyncMock(return_value=0)  # type: ignore[method-assign]

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

    async def test_persist_results_with_successful(self, mock_brotr: Brotr, tmp_path: Path) -> None:
        """Test persisting successful check results."""
        mock_brotr.insert_relay_metadata = AsyncMock(return_value=2)  # type: ignore[method-assign]
        mock_brotr.upsert_service_state = AsyncMock(return_value=0)  # type: ignore[method-assign]

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

        result1 = _make_check_result(nip66_rtt=_make_rtt_meta(rtt_open=100))
        result2 = _make_check_result(nip66_rtt=_make_rtt_meta(rtt_open=200))

        successful = [(relay1, result1), (relay2, result2)]
        await monitor._persist_results(successful, [])

        mock_brotr.insert_relay_metadata.assert_called_once()  # type: ignore[attr-defined]
        mock_brotr.upsert_service_state.assert_called_once()  # type: ignore[attr-defined]

    async def test_persist_results_with_failed(self, mock_brotr: Brotr, tmp_path: Path) -> None:
        """Test persisting failed check results updates checkpoint."""
        mock_brotr.insert_relay_metadata = AsyncMock(return_value=0)  # type: ignore[method-assign]
        mock_brotr.upsert_service_state = AsyncMock(return_value=0)  # type: ignore[method-assign]

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
        mock_brotr.upsert_service_state.assert_called_once()  # type: ignore[attr-defined]


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
            networks=NetworksConfig(
                clearnet=ClearnetConfig(enabled=True),
                tor=TorConfig(enabled=True),
            ),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)
        enabled = monitor._config.networks.get_enabled_networks()
        assert "clearnet" in enabled
        assert "tor" in enabled


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
        """Test _get_publish_relays falls back to publishing.relays when discovery relays unset."""
        config = MonitorConfig(
            processing=ProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            discovery=DiscoveryConfig(
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            publishing=PublishingConfig(relays=["wss://fallback.relay.com"]),
        )
        harness = _MonitorStub(config, test_keys)
        relays = harness._get_publish_relays(harness._config.discovery.relays)
        assert len(relays) == 1
        assert relays[0].url == "wss://fallback.relay.com"

    def test_get_publish_relays_discovery_empty_list_no_fallback(self, test_keys: Keys) -> None:
        """Test _get_publish_relays returns empty list when discovery relays explicitly []."""
        config = MonitorConfig(
            processing=ProcessingConfig(
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
        assert relays == []

    def test_get_publish_relays_returns_announcement_primary(self, stub: _MonitorStub) -> None:
        """Test _get_publish_relays returns announcement-specific relays when set."""
        relays = stub._get_publish_relays(stub._config.announcement.relays)
        assert len(relays) == 1
        assert relays[0].url == "wss://ann.relay.com"

    def test_get_publish_relays_announcement_falls_back_to_publishing(
        self, test_keys: Keys
    ) -> None:
        """Test _get_publish_relays falls back to publishing.relays when announcement relays unset."""
        config = MonitorConfig(
            processing=ProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            discovery=DiscoveryConfig(
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            publishing=PublishingConfig(relays=["wss://fallback.relay.com"]),
        )
        harness = _MonitorStub(config, test_keys)
        relays = harness._get_publish_relays(harness._config.announcement.relays)
        assert len(relays) == 1
        assert relays[0].url == "wss://fallback.relay.com"

    def test_get_publish_relays_announcement_empty_list_no_fallback(self, test_keys: Keys) -> None:
        """Test _get_publish_relays returns empty list when announcement relays explicitly []."""
        config = MonitorConfig(
            processing=ProcessingConfig(
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
        assert relays == []

    def test_get_publish_relays_returns_profile_primary(self, stub: _MonitorStub) -> None:
        """Test _get_publish_relays returns profile-specific relays when set."""
        relays = stub._get_publish_relays(stub._config.profile.relays)
        assert len(relays) == 1
        assert relays[0].url == "wss://profile.relay.com"

    def test_get_publish_relays_profile_falls_back_to_publishing(self, test_keys: Keys) -> None:
        """Test _get_publish_relays falls back to publishing.relays when profile relays unset."""
        config = MonitorConfig(
            processing=ProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            discovery=DiscoveryConfig(
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            publishing=PublishingConfig(relays=["wss://fallback.relay.com"]),
        )
        harness = _MonitorStub(config, test_keys)
        relays = harness._get_publish_relays(harness._config.profile.relays)
        assert len(relays) == 1
        assert relays[0].url == "wss://fallback.relay.com"

    def test_get_publish_relays_profile_empty_list_no_fallback(self, test_keys: Keys) -> None:
        """Test _get_publish_relays returns empty list when profile relays explicitly []."""
        config = MonitorConfig(
            processing=ProcessingConfig(
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
        assert relays == []


# ============================================================================
# Monitor.publish_announcement
# ============================================================================


class TestPublishAnnouncement:
    """Tests for Monitor.publish_announcement."""

    async def test_publish_announcement_when_disabled(self, test_keys: Keys) -> None:
        """Test that publish_announcement returns immediately when disabled."""
        config = MonitorConfig(
            processing=ProcessingConfig(
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
            processing=ProcessingConfig(
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
                    state_type=ServiceStateType.PUBLICATION,
                    state_key="last_announcement",
                    state_value={"published_at": now},
                    updated_at=int(now),
                )
            ]
        )
        with patch(
            "bigbrotr.services.monitor.service.broadcast_events", new_callable=AsyncMock
        ) as mock_broadcast:
            await stub.publish_announcement()
            mock_broadcast.assert_not_awaited()

    async def test_publish_announcement_no_prior_state(self, stub: _MonitorStub) -> None:
        """Test successful announcement publish when no prior state exists."""
        stub._brotr.get_service_state = AsyncMock(return_value=[])

        with patch(
            "bigbrotr.services.monitor.service.broadcast_events",
            new_callable=AsyncMock,
            return_value=1,
        ) as mock_broadcast:
            await stub.publish_announcement()

        mock_broadcast.assert_awaited_once()
        stub._brotr.upsert_service_state.assert_awaited_once()
        stub._logger.info.assert_called_with("publish_completed", event="announcement", relays=1)

    async def test_publish_announcement_interval_elapsed(self, stub: _MonitorStub) -> None:
        """Test successful announcement publish when interval has elapsed."""
        old_timestamp = time.time() - 100000  # well past the 86400 interval
        stub._brotr.get_service_state = AsyncMock(
            return_value=[
                ServiceState(
                    service_name=ServiceName.MONITOR,
                    state_type=ServiceStateType.PUBLICATION,
                    state_key="last_announcement",
                    state_value={"published_at": old_timestamp},
                    updated_at=int(old_timestamp),
                )
            ]
        )

        with patch(
            "bigbrotr.services.monitor.service.broadcast_events",
            new_callable=AsyncMock,
            return_value=1,
        ) as mock_broadcast:
            await stub.publish_announcement()

        mock_broadcast.assert_awaited_once()
        stub._brotr.upsert_service_state.assert_awaited_once()

    async def test_publish_announcement_broadcast_failure(self, stub: _MonitorStub) -> None:
        """Test that announcement failure is logged as warning."""
        stub._brotr.get_service_state = AsyncMock(return_value=[])

        with patch(
            "bigbrotr.services.monitor.service.broadcast_events",
            new_callable=AsyncMock,
            return_value=0,
        ):
            await stub.publish_announcement()

        stub._logger.warning.assert_called_once()
        stub._logger.warning.assert_called_once_with(
            "publish_failed", event="announcement", error="no relays reachable"
        )


# ============================================================================
# Monitor.publish_profile
# ============================================================================


class TestPublishProfile:
    """Tests for Monitor.publish_profile."""

    async def test_publish_profile_when_disabled(self, test_keys: Keys) -> None:
        """Test that publish_profile returns immediately when disabled."""
        config = MonitorConfig(
            processing=ProcessingConfig(
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
            processing=ProcessingConfig(
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
                    state_type=ServiceStateType.PUBLICATION,
                    state_key="last_profile",
                    state_value={"published_at": now},
                    updated_at=int(now),
                )
            ]
        )
        with patch(
            "bigbrotr.services.monitor.service.broadcast_events", new_callable=AsyncMock
        ) as mock_broadcast:
            await stub.publish_profile()
            mock_broadcast.assert_not_awaited()

    async def test_publish_profile_successful(self, stub: _MonitorStub) -> None:
        """Test successful profile publish when interval has elapsed."""
        stub._brotr.get_service_state = AsyncMock(return_value=[])

        with patch(
            "bigbrotr.services.monitor.service.broadcast_events",
            new_callable=AsyncMock,
            return_value=1,
        ) as mock_broadcast:
            await stub.publish_profile()

        mock_broadcast.assert_awaited_once()
        stub._brotr.upsert_service_state.assert_awaited_once()
        stub._logger.info.assert_called_with("publish_completed", event="profile", relays=1)

    async def test_publish_profile_broadcast_failure(self, stub: _MonitorStub) -> None:
        """Test that profile failure is logged as warning."""
        stub._brotr.get_service_state = AsyncMock(return_value=[])

        with patch(
            "bigbrotr.services.monitor.service.broadcast_events",
            new_callable=AsyncMock,
            return_value=0,
        ):
            await stub.publish_profile()

        stub._logger.warning.assert_called_once()
        stub._logger.warning.assert_called_once_with(
            "publish_failed", event="profile", error="no relays reachable"
        )


# ============================================================================
# Monitor.publish_relay_discoveries
# ============================================================================


class TestPublishRelayDiscoveries:
    """Tests for Monitor.publish_relay_discoveries."""

    async def test_publish_discoveries_when_disabled(self, test_keys: Keys) -> None:
        """Test that discoveries returns immediately when disabled."""
        config = MonitorConfig(
            processing=ProcessingConfig(
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

        with patch(
            "bigbrotr.services.monitor.service.broadcast_events", new_callable=AsyncMock
        ) as mock_broadcast:
            await harness.publish_relay_discoveries([(relay, result)])
            mock_broadcast.assert_not_awaited()

    async def test_publish_discoveries_when_no_relays(self, test_keys: Keys) -> None:
        """Test that discoveries returns when no relays configured."""
        config = MonitorConfig(
            processing=ProcessingConfig(
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

        with patch(
            "bigbrotr.services.monitor.service.broadcast_events", new_callable=AsyncMock
        ) as mock_broadcast:
            await harness.publish_relay_discoveries([(relay, result)])
            mock_broadcast.assert_not_awaited()

    async def test_publish_discoveries_successful(self, stub: _MonitorStub) -> None:
        """Test successful relay discovery publishing."""
        relay = Relay("wss://relay.example.com")
        result = _make_check_result(nip11=_make_nip11_meta(name="Test Relay"))

        with patch(
            "bigbrotr.services.monitor.service.broadcast_events",
            new_callable=AsyncMock,
            return_value=1,
        ) as mock_broadcast:
            await stub.publish_relay_discoveries([(relay, result)])

        mock_broadcast.assert_awaited_once()
        stub._logger.debug.assert_any_call("discoveries_published", count=1)

    async def test_publish_discoveries_build_failure_for_individual(
        self, stub: _MonitorStub
    ) -> None:
        """Test that build failure for one relay does not prevent others."""
        relay1 = Relay("wss://relay1.example.com")
        relay2 = Relay("wss://relay2.example.com")
        result1 = _make_check_result()
        result2 = _make_check_result(nip11=_make_nip11_meta(name="Test"))

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
            "bigbrotr.services.monitor.service.broadcast_events",
            new_callable=AsyncMock,
            return_value=1,
        ) as mock_broadcast:
            await stub.publish_relay_discoveries([(relay1, result1), (relay2, result2)])

        mock_broadcast.assert_awaited_once()
        stub._logger.debug.assert_any_call(
            "build_30166_failed", url=relay1.url, error="build failed for relay1"
        )

    async def test_publish_discoveries_broadcast_failure(self, stub: _MonitorStub) -> None:
        """Test that broadcast failure is logged as warning."""
        relay = Relay("wss://relay.example.com")
        result = _make_check_result()

        with patch(
            "bigbrotr.services.monitor.service.broadcast_events",
            new_callable=AsyncMock,
            return_value=0,
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
            processing=ProcessingConfig(
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
            processing=ProcessingConfig(
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
            processing=ProcessingConfig(
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
            networks=NetworksConfig(clearnet=ClearnetConfig(timeout=5.0)),
        )
        harness = _MonitorStub(config, test_keys)
        builder = harness._build_kind_10166()
        assert builder is not None

    def test_build_kind_10166_no_flags(self, test_keys: Keys) -> None:
        """Test Kind 10166 builder with all flags disabled."""
        config = MonitorConfig(
            interval=600.0,
            processing=ProcessingConfig(
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
            networks=NetworksConfig(clearnet=ClearnetConfig(timeout=10.0)),
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


# ============================================================================
# Metrics Tests
# ============================================================================


class TestMonitorMetrics:
    """Tests for Monitor Prometheus counter emissions."""

    async def test_monitor_emits_check_counters(self, mock_brotr: Brotr) -> None:
        """Check succeeded/failed counters emitted after each chunk."""
        config = MonitorConfig(
            processing=ProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            discovery=DiscoveryConfig(
                enabled=False,
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)

        relay1 = Relay("wss://ok.example.com")
        relay2 = Relay("wss://fail.example.com")
        result = _make_check_result(nip66_rtt=_make_rtt_meta(rtt_open=50))
        successful = [(relay1, result)]
        failed_relays = [relay2]

        async def fake_check_chunks(relays):  # type: ignore[no-untyped-def]
            yield successful, failed_relays

        with (
            patch.object(monitor, "inc_counter") as mock_counter,
            patch.object(monitor, "_fetch_relays", new_callable=AsyncMock, return_value=[relay1]),
            patch.object(monitor, "check_chunks", side_effect=fake_check_chunks),
            patch.object(monitor, "publish_relay_discoveries", new_callable=AsyncMock),
            patch.object(monitor, "_persist_results", new_callable=AsyncMock),
            patch(
                "bigbrotr.services.monitor.service.cleanup_service_state",
                new_callable=AsyncMock,
                return_value=0,
            ),
        ):
            await monitor.monitor()

        mock_counter.assert_any_call("total_checks_succeeded", 1)
        mock_counter.assert_any_call("total_checks_failed", 1)

    async def test_persist_results_emits_metadata_counter(self, mock_brotr: Brotr) -> None:
        """Metadata stored counter emitted after successful insert."""
        mock_brotr.insert_relay_metadata = AsyncMock(return_value=3)  # type: ignore[method-assign]
        mock_brotr.upsert_service_state = AsyncMock(return_value=0)  # type: ignore[method-assign]

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

        relay = Relay("wss://relay.example.com")
        result = _make_check_result(nip66_rtt=_make_rtt_meta(rtt_open=100))
        successful = [(relay, result)]

        with patch.object(monitor, "inc_counter") as mock_counter:
            await monitor._persist_results(successful, [])

        mock_counter.assert_any_call("total_metadata_stored", 3)

    async def test_publish_discoveries_emits_counter(self, mock_brotr: Brotr) -> None:
        """Events published counter emitted after successful broadcast."""
        config = MonitorConfig(
            processing=ProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            discovery=DiscoveryConfig(
                enabled=True,
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
                relays=["wss://disc.relay.com"],
            ),
            publishing=PublishingConfig(relays=["wss://fallback.relay.com"]),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)

        relay = Relay("wss://relay.example.com")
        result = _make_check_result(nip66_rtt=_make_rtt_meta(rtt_open=100))

        with (
            patch.object(monitor, "inc_counter") as mock_counter,
            patch(
                "bigbrotr.services.monitor.service.broadcast_events",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            await monitor.publish_relay_discoveries([(relay, result)])

        mock_counter.assert_any_call("total_events_published", 1)
