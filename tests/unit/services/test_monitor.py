"""Unit tests for the monitor service package."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nostr_sdk import Keys

from bigbrotr.core.brotr import Brotr
from bigbrotr.models import Relay
from bigbrotr.models.constants import NetworkType, ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType
from bigbrotr.nips.base import BaseLogs
from bigbrotr.nips.nip11 import Nip11
from bigbrotr.nips.nip11.data import Nip11InfoData, Nip11InfoDataLimitation
from bigbrotr.nips.nip11.info import Nip11InfoMetadata
from bigbrotr.nips.nip11.logs import Nip11InfoLogs
from bigbrotr.nips.nip66 import Nip66RttMetadata
from bigbrotr.nips.nip66.data import Nip66RttData
from bigbrotr.nips.nip66.logs import Nip66RttMultiPhaseLogs
from bigbrotr.services.common.configs import (
    ClearnetConfig,
    I2pConfig,
    LokiConfig,
    NetworksConfig,
    TorConfig,
)
from bigbrotr.services.monitor import (
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
    RelayListConfig,
)
from bigbrotr.services.monitor.configs import RetriesConfig, RetryConfig
from bigbrotr.services.monitor.queries import (
    count_relays_to_monitor,
    delete_stale_checkpoints,
    fetch_relays_to_monitor,
    fetch_relays_to_monitor_page,
    insert_relay_metadata,
    is_publish_due,
    iter_relays_to_monitor_pages,
    upsert_monitor_checkpoints,
    upsert_publish_checkpoints,
)
from bigbrotr.services.monitor.service import (
    Nip66DnsMetadata,
    Nip66GeoMetadata,
    Nip66HttpMetadata,
    Nip66NetMetadata,
    Nip66SslMetadata,
)
from bigbrotr.services.monitor.utils import (
    collect_metadata,
    extract_result,
    log_reason,
    log_success,
    retry_fetch,
)
from bigbrotr.utils.protocol import BroadcastClientResult, broadcast_events_detailed


if TYPE_CHECKING:
    from pathlib import Path


# Valid secp256k1 test key (DO NOT USE IN PRODUCTION)
VALID_HEX_KEY = (
    "67dea2ed018072d675f5415ecfaed7d2597555e202d85b3d65ea4e58d2d92ffa"  # pragma: allowlist secret
)

# ============================================================================
# Fixtures & Helpers
# ============================================================================


@pytest.fixture(autouse=True)
def set_private_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOSTR_PRIVATE_KEY_MONITOR", VALID_HEX_KEY)


_NO_GEO_NET = MetadataFlags(nip66_geo=False, nip66_net=False)


def _make_config(**overrides: Any) -> MonitorConfig:
    defaults: dict[str, Any] = {
        "processing": ProcessingConfig(compute=_NO_GEO_NET, store=_NO_GEO_NET),
        "discovery": DiscoveryConfig(include=_NO_GEO_NET),
        "announcement": AnnouncementConfig(include=_NO_GEO_NET),
    }
    defaults.update(overrides)
    return MonitorConfig(**defaults)


def _broadcast_results(
    *,
    successful_relays: tuple[str, ...] = ("wss://publish.example.com",),
    failed_relays: dict[str, str] | None = None,
) -> list[BroadcastClientResult]:
    return [
        BroadcastClientResult(
            event_ids=("event-id",),
            successful_relays=successful_relays,
            failed_relays=failed_relays or {},
        )
    ]


class _MonitorStub:
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
        self.inc_counter = MagicMock()
        self.set_gauge = MagicMock()
        self.inc_gauge = MagicMock()
        self.clients = MagicMock()
        self.clients.get = AsyncMock(return_value=AsyncMock())
        self.clients.get_many = AsyncMock(return_value=[AsyncMock()])
        self.clients.disconnect = AsyncMock()

    # Publishing methods bound from Monitor
    _publish_context = Monitor._publish_context
    _check_context = Monitor._check_context
    _check_dependencies = Monitor._check_dependencies
    publish_announcement = Monitor.publish_announcement
    publish_profile = Monitor.publish_profile
    publish_relay_list = Monitor.publish_relay_list


@pytest.fixture
def test_keys() -> Keys:
    return Keys.parse(VALID_HEX_KEY)


@pytest.fixture
def all_flags_config() -> MonitorConfig:
    return _make_config(
        interval=3600.0,
        discovery=DiscoveryConfig(
            enabled=True,
            include=_NO_GEO_NET,
            relays=["wss://disc.relay.com"],
        ),
        announcement=AnnouncementConfig(
            enabled=True,
            interval=86400,
            include=_NO_GEO_NET,
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
        networks=NetworksConfig(clearnet=ClearnetConfig(timeout=10.0)),
    )


@pytest.fixture
def stub(all_flags_config: MonitorConfig, test_keys: Keys) -> _MonitorStub:
    return _MonitorStub(all_flags_config, test_keys)


def _make_nip11_meta(
    *,
    name: str | None = None,
    supported_nips: list[int] | None = None,
    tags: list[str] | None = None,
    language_tags: list[str] | None = None,
    limitation: Nip11InfoDataLimitation | None = None,
    success: bool = True,
) -> Nip11InfoMetadata:
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
    return Nip66RttMetadata(
        data=Nip66RttData(rtt_open=rtt_open, rtt_read=rtt_read, rtt_write=rtt_write),
        logs=Nip66RttMultiPhaseLogs(
            open_success=open_success,
            open_reason=None if open_success else "connection failed",
            write_success=write_success,
            write_reason=write_reason,
        ),
    )


def _make_check_result(
    *,
    generated_at: int = 1700000000,
    nip11_info: Nip11InfoMetadata | None = None,
    nip66_rtt: Nip66RttMetadata | None = None,
) -> CheckResult:
    return CheckResult(
        generated_at=generated_at,
        nip11_info=nip11_info,
        nip66_rtt=nip66_rtt,
    )


@pytest.fixture
def query_brotr() -> MagicMock:
    brotr = MagicMock()
    brotr.fetch = AsyncMock(return_value=[])
    brotr.fetchval = AsyncMock(return_value=0)
    brotr.upsert_service_state = AsyncMock(return_value=0)
    brotr.insert_relay_metadata = AsyncMock(return_value=0)
    brotr.config.batch.max_size = 1000
    return brotr


def _make_dict_row(data: dict[str, Any]) -> dict[str, Any]:
    return data


async def _mock_pages(*pages: list[Relay]):
    for page in pages:
        yield page


# ============================================================================
# Configs
# ============================================================================


class TestMetadataFlags:
    def test_default_values(self) -> None:
        flags = MetadataFlags()

        assert flags.nip11_info is True
        assert flags.nip66_rtt is True
        assert flags.nip66_ssl is True
        assert flags.nip66_geo is True
        assert flags.nip66_net is True
        assert flags.nip66_dns is True
        assert flags.nip66_http is True

    def test_disable_flags(self) -> None:
        flags = MetadataFlags(nip66_geo=False, nip66_net=False)

        assert flags.nip66_geo is False
        assert flags.nip66_net is False
        assert flags.nip66_rtt is True

    def test_all_flags_disabled(self) -> None:
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

    def test_get_missing_from_no_missing(self) -> None:
        subset = MetadataFlags(nip66_geo=True, nip66_net=True)
        superset = MetadataFlags()

        assert subset.get_missing_from(superset) == []

    def test_get_missing_from_some_missing(self) -> None:
        subset = MetadataFlags(nip66_geo=True, nip66_net=True)
        superset = MetadataFlags(nip66_geo=False, nip66_net=False)

        missing = subset.get_missing_from(superset)
        assert "nip66_geo" in missing
        assert "nip66_net" in missing

    def test_get_missing_from_all_disabled(self) -> None:
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


class TestProcessingConfig:
    def test_default_values(self) -> None:
        config = ProcessingConfig()

        assert config.chunk_size == 100
        assert config.nip11_info_max_size == 1048576
        assert config.compute.nip11_info is True
        assert config.store.nip11_info is True

    def test_custom_values(self) -> None:
        config = ProcessingConfig(
            chunk_size=50,
            compute=MetadataFlags(nip66_geo=False),
            store=MetadataFlags(nip66_geo=False),
        )

        assert config.chunk_size == 50
        assert config.compute.nip66_geo is False
        assert config.store.nip66_geo is False

    def test_chunk_size_bounds(self) -> None:
        # Valid values
        config_min = ProcessingConfig(chunk_size=10)
        assert config_min.chunk_size == 10

        config_max = ProcessingConfig(chunk_size=1000)
        assert config_max.chunk_size == 1000

    def test_nip11_info_max_size_custom(self) -> None:
        config = ProcessingConfig(nip11_info_max_size=2097152)  # 2MB
        assert config.nip11_info_max_size == 2097152


class TestRetryConfig:
    def test_defaults(self) -> None:
        config = RetryConfig()

        assert config.max_attempts == 0
        assert config.initial_delay == 1.0
        assert config.max_delay == 10.0
        assert config.jitter == 0.5

    def test_custom_values(self) -> None:
        config = RetryConfig(max_attempts=3, initial_delay=2.0, max_delay=30.0, jitter=1.0)

        assert config.max_attempts == 3
        assert config.initial_delay == 2.0
        assert config.max_delay == 30.0
        assert config.jitter == 1.0

    def test_constraint_max_attempts(self) -> None:
        with pytest.raises(ValueError):
            RetryConfig(max_attempts=-1)
        with pytest.raises(ValueError):
            RetryConfig(max_attempts=11)

    def test_max_delay_less_than_initial_rejected(self) -> None:
        with pytest.raises(ValueError, match="max_delay"):
            RetryConfig(initial_delay=5.0, max_delay=2.0)

    def test_max_delay_equals_initial_accepted(self) -> None:
        config = RetryConfig(initial_delay=5.0, max_delay=5.0)
        assert config.max_delay == 5.0


class TestRetriesConfig:
    def test_defaults(self) -> None:
        config = RetriesConfig()

        assert config.nip11_info.max_attempts == 0
        assert config.nip66_rtt.max_attempts == 0
        assert config.nip66_ssl.max_attempts == 0
        assert config.nip66_geo.max_attempts == 0
        assert config.nip66_net.max_attempts == 0
        assert config.nip66_dns.max_attempts == 0
        assert config.nip66_http.max_attempts == 0


class TestGeoConfig:
    def test_default_values(self) -> None:
        config = GeoConfig()

        assert config.city_database_path == "static/GeoLite2-City.mmdb"
        assert config.asn_database_path == "static/GeoLite2-ASN.mmdb"
        assert config.max_age_days == 30
        assert config.max_download_size == 100_000_000
        assert config.geohash_precision == 9

    def test_custom_paths(self) -> None:
        config = GeoConfig(
            city_database_path="/custom/path/city.mmdb",
            asn_database_path="/custom/path/asn.mmdb",
            max_age_days=7,
        )

        assert config.city_database_path == "/custom/path/city.mmdb"
        assert config.asn_database_path == "/custom/path/asn.mmdb"
        assert config.max_age_days == 7

    def test_max_age_days_validation(self) -> None:
        config = GeoConfig(max_age_days=1)
        assert config.max_age_days == 1

        config2 = GeoConfig(max_age_days=365)
        assert config2.max_age_days == 365

    def test_max_age_none(self) -> None:
        config = GeoConfig(max_age_days=None)
        assert config.max_age_days is None

    def test_empty_city_path_rejected(self) -> None:
        with pytest.raises(ValueError):
            GeoConfig(city_database_path="")

    def test_empty_asn_path_rejected(self) -> None:
        with pytest.raises(ValueError):
            GeoConfig(asn_database_path="")


class TestPublishingConfig:
    def test_default_values(self) -> None:
        config = PublishingConfig()

        assert len(config.relays) == 4
        assert config.relays[0].url == "wss://relay.mostr.pub"
        assert config.relays[1].url == "wss://relay.damus.io"
        assert config.relays[2].url == "wss://nos.lol"
        assert config.relays[3].url == "wss://relay.primal.net"

    def test_custom_values(self) -> None:
        config = PublishingConfig(relays=["wss://relay1.com", "wss://relay2.com"])

        assert len(config.relays) == 2
        assert config.relays[0].url == "wss://relay1.com"
        assert config.relays[1].url == "wss://relay2.com"

    def test_single_relay(self) -> None:
        config = PublishingConfig(relays=["wss://single.relay.com"])
        assert len(config.relays) == 1


class TestDiscoveryConfig:
    def test_default_values(self) -> None:
        config = DiscoveryConfig()

        assert config.enabled is True
        assert config.interval == 14_400
        assert config.include.nip11_info is True
        assert config.relays is None

    def test_custom_values(self) -> None:
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
        config = DiscoveryConfig(interval=60)
        assert config.interval == 60

        config2 = DiscoveryConfig(interval=86400)
        assert config2.interval == 86400

    def test_interval_upper_bound_rejected(self) -> None:
        with pytest.raises(ValueError):
            DiscoveryConfig(interval=604801.0)


class TestAnnouncementConfig:
    def test_default_values(self) -> None:
        config = AnnouncementConfig()

        assert config.enabled is True
        assert config.interval == 86400
        assert config.relays is None

    def test_custom_values(self) -> None:
        config = AnnouncementConfig(
            enabled=False,
            interval=3600,
            relays=["wss://relay.com"],
        )

        assert config.enabled is False
        assert config.interval == 3600
        assert len(config.relays) == 1

    def test_interval_upper_bound_rejected(self) -> None:
        with pytest.raises(ValueError):
            AnnouncementConfig(interval=604801.0)


class TestProfileConfig:
    def test_default_values(self) -> None:
        config = ProfileConfig()

        assert config.enabled is True
        assert config.interval == 86400
        assert config.relays is None
        assert config.name == "BigBrotr Monitor"
        assert config.about == "Nostr relay monitoring service"

    def test_custom_values(self) -> None:
        config = ProfileConfig(
            enabled=True,
            interval=43200,
            relays=["wss://profile.relay.com"],
        )

        assert config.enabled is True
        assert config.interval == 43200
        assert len(config.relays) == 1

    def test_interval_upper_bound_rejected(self) -> None:
        with pytest.raises(ValueError):
            ProfileConfig(interval=604801.0)


class TestMonitorConfig:
    def test_default_values_with_geo_disabled(self, tmp_path: Path) -> None:
        config = MonitorConfig(
            processing=ProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            discovery=DiscoveryConfig(
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            announcement=AnnouncementConfig(
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
        )

        assert config.networks.clearnet.enabled is True
        assert config.networks.tor.enabled is False
        assert config.processing.compute.nip66_geo is False
        assert config.processing.compute.nip66_net is False

    def test_store_requires_compute_validation(self, tmp_path: Path) -> None:
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
        config = MonitorConfig(
            processing=ProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            discovery=DiscoveryConfig(
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            announcement=AnnouncementConfig(
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
        config = MonitorConfig(
            interval=600.0,
            processing=ProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            discovery=DiscoveryConfig(
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            announcement=AnnouncementConfig(
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
        )

        assert config.interval == 600.0


class TestMonitorConfigValidateGeoDatabases:
    def test_valid_with_download_url(self) -> None:
        config = MonitorConfig()
        assert config.geo.city_download_url != ""
        assert config.geo.asn_download_url != ""

    def test_geo_missing_city_no_url_raises(self) -> None:
        with (
            patch("bigbrotr.services.monitor.configs.Path.exists", return_value=False),
            pytest.raises(ValueError, match="GeoLite2 City database not found"),
        ):
            MonitorConfig(geo=GeoConfig(city_download_url=""))

    def test_geo_missing_asn_no_url_raises(self) -> None:
        with (
            patch("bigbrotr.services.monitor.configs.Path.exists", return_value=False),
            pytest.raises(ValueError, match="GeoLite2 ASN database not found"),
        ):
            MonitorConfig(geo=GeoConfig(asn_download_url=""))

    def test_geo_check_skipped_when_compute_disabled(self) -> None:
        config = MonitorConfig(
            processing=ProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            discovery=DiscoveryConfig(
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            announcement=AnnouncementConfig(
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            geo=GeoConfig(city_download_url="", asn_download_url=""),
        )
        assert config.processing.compute.nip66_geo is False


class TestMonitorConfigValidateClearnetOnlyChecks:
    """Clearnet-only compute flags must be disabled when clearnet is off."""

    def _overlay_only_networks(self) -> NetworksConfig:
        return NetworksConfig(
            clearnet=ClearnetConfig(enabled=False),
            tor=TorConfig(enabled=True),
        )

    def test_valid_clearnet_enabled(self) -> None:
        config = MonitorConfig(
            processing=ProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            discovery=DiscoveryConfig(
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
            announcement=AnnouncementConfig(
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
        )
        assert config.networks.is_enabled(NetworkType.CLEARNET)
        assert config.processing.compute.nip66_ssl is True

    def test_valid_clearnet_disabled_flags_off(self) -> None:
        config = MonitorConfig(
            networks=self._overlay_only_networks(),
            processing=ProcessingConfig(
                compute=MetadataFlags(
                    nip66_ssl=False,
                    nip66_geo=False,
                    nip66_net=False,
                    nip66_dns=False,
                ),
                store=MetadataFlags(
                    nip66_ssl=False,
                    nip66_geo=False,
                    nip66_net=False,
                    nip66_dns=False,
                ),
            ),
            discovery=DiscoveryConfig(
                include=MetadataFlags(
                    nip66_ssl=False,
                    nip66_geo=False,
                    nip66_net=False,
                    nip66_dns=False,
                ),
            ),
            announcement=AnnouncementConfig(
                include=MetadataFlags(
                    nip66_ssl=False,
                    nip66_geo=False,
                    nip66_net=False,
                    nip66_dns=False,
                ),
            ),
        )
        assert not config.networks.is_enabled(NetworkType.CLEARNET)
        assert config.processing.compute.nip66_ssl is False

    def test_clearnet_disabled_ssl_enabled_raises(self) -> None:
        with pytest.raises(ValueError, match="clearnet-only checks are enabled"):
            MonitorConfig(
                networks=self._overlay_only_networks(),
                processing=ProcessingConfig(
                    compute=MetadataFlags(
                        nip66_ssl=True,
                        nip66_geo=False,
                        nip66_net=False,
                        nip66_dns=False,
                    ),
                    store=MetadataFlags(
                        nip66_ssl=False,
                        nip66_geo=False,
                        nip66_net=False,
                        nip66_dns=False,
                    ),
                ),
                discovery=DiscoveryConfig(
                    include=MetadataFlags(
                        nip66_ssl=False,
                        nip66_geo=False,
                        nip66_net=False,
                        nip66_dns=False,
                    ),
                ),
                announcement=AnnouncementConfig(
                    include=MetadataFlags(
                        nip66_ssl=False,
                        nip66_geo=False,
                        nip66_net=False,
                        nip66_dns=False,
                    ),
                ),
            )

    def test_clearnet_disabled_multiple_flags_raises(self) -> None:
        with pytest.raises(ValueError, match=r"nip66_ssl.*nip66_dns|nip66_dns.*nip66_ssl"):
            MonitorConfig(
                networks=self._overlay_only_networks(),
                processing=ProcessingConfig(
                    compute=MetadataFlags(
                        nip66_ssl=True,
                        nip66_geo=False,
                        nip66_net=False,
                        nip66_dns=True,
                    ),
                    store=MetadataFlags(
                        nip66_ssl=False,
                        nip66_geo=False,
                        nip66_net=False,
                        nip66_dns=False,
                    ),
                ),
                discovery=DiscoveryConfig(
                    include=MetadataFlags(
                        nip66_ssl=False,
                        nip66_geo=False,
                        nip66_net=False,
                        nip66_dns=False,
                    ),
                ),
                announcement=AnnouncementConfig(
                    include=MetadataFlags(
                        nip66_ssl=False,
                        nip66_geo=False,
                        nip66_net=False,
                        nip66_dns=False,
                    ),
                ),
            )

    @pytest.mark.parametrize("flag", ["nip66_ssl", "nip66_geo", "nip66_net", "nip66_dns"])
    def test_clearnet_disabled_each_flag_raises(self, flag: str) -> None:
        flags = {"nip66_ssl": False, "nip66_geo": False, "nip66_net": False, "nip66_dns": False}
        flags[flag] = True
        with pytest.raises(ValueError, match=flag):
            MonitorConfig(
                networks=self._overlay_only_networks(),
                processing=ProcessingConfig(
                    compute=MetadataFlags(**flags),
                    store=MetadataFlags(
                        nip66_ssl=False,
                        nip66_geo=False,
                        nip66_net=False,
                        nip66_dns=False,
                    ),
                ),
                discovery=DiscoveryConfig(
                    include=MetadataFlags(
                        nip66_ssl=False,
                        nip66_geo=False,
                        nip66_net=False,
                        nip66_dns=False,
                    ),
                ),
                announcement=AnnouncementConfig(
                    include=MetadataFlags(
                        nip66_ssl=False,
                        nip66_geo=False,
                        nip66_net=False,
                        nip66_dns=False,
                    ),
                ),
            )


class TestMonitorConfigValidateStoreRequiresCompute:
    def test_valid_store_subset_of_compute(self) -> None:
        config = MonitorConfig(
            processing=ProcessingConfig(
                compute=MetadataFlags(),
                store=MetadataFlags(nip66_geo=False),
            ),
        )
        assert config.processing.store.nip66_geo is False

    def test_store_without_compute_raises(self) -> None:
        with pytest.raises(ValueError, match="Cannot store metadata that is not computed"):
            MonitorConfig(
                processing=ProcessingConfig(
                    compute=MetadataFlags(nip66_geo=False),
                    store=MetadataFlags(nip66_geo=True),
                ),
            )

    def test_multiple_store_without_compute_raises(self) -> None:
        with pytest.raises(ValueError, match=r"nip66_geo.*nip66_net|nip66_net.*nip66_geo"):
            MonitorConfig(
                processing=ProcessingConfig(
                    compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                    store=MetadataFlags(nip66_geo=True, nip66_net=True),
                ),
            )


class TestMonitorConfigValidatePublishRequiresCompute:
    def test_valid_publish_subset_of_compute(self) -> None:
        config = MonitorConfig(
            discovery=DiscoveryConfig(
                enabled=True,
                include=MetadataFlags(nip66_geo=False),
            ),
        )
        assert config.discovery.include.nip66_geo is False

    def test_publish_without_compute_raises(self) -> None:
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
        config = MonitorConfig(
            processing=ProcessingConfig(
                compute=MetadataFlags(nip66_ssl=False),
                store=MetadataFlags(nip66_ssl=False),
            ),
            discovery=DiscoveryConfig(
                enabled=False,
                include=MetadataFlags(nip66_ssl=True),
            ),
            announcement=AnnouncementConfig(
                enabled=False,
                include=MetadataFlags(nip66_ssl=True),
            ),
        )
        assert config.discovery.enabled is False

    def test_announcement_without_compute_raises(self) -> None:
        with pytest.raises(ValueError, match="Cannot announce metadata that is not computed"):
            MonitorConfig(
                processing=ProcessingConfig(
                    compute=MetadataFlags(nip66_dns=False),
                    store=MetadataFlags(nip66_dns=False),
                ),
                discovery=DiscoveryConfig(
                    include=MetadataFlags(nip66_dns=False),
                ),
                announcement=AnnouncementConfig(
                    enabled=True,
                    include=MetadataFlags(nip66_dns=True),
                ),
            )

    def test_announcement_check_skipped_when_disabled(self) -> None:
        config = MonitorConfig(
            processing=ProcessingConfig(
                compute=MetadataFlags(nip66_dns=False),
                store=MetadataFlags(nip66_dns=False),
            ),
            discovery=DiscoveryConfig(
                include=MetadataFlags(nip66_dns=False),
            ),
            announcement=AnnouncementConfig(
                enabled=False,
                include=MetadataFlags(nip66_dns=True),
            ),
        )
        assert config.announcement.enabled is False


# ============================================================================
# Utils
# ============================================================================


class TestLogSuccess:
    def test_base_logs_success_true(self) -> None:
        logs = BaseLogs(success=True, reason=None)
        result = MagicMock()
        result.logs = logs

        assert log_success(result) is True

    def test_base_logs_success_false(self) -> None:
        logs = BaseLogs(success=False, reason="connection refused")
        result = MagicMock()
        result.logs = logs

        assert log_success(result) is False

    def test_rtt_multi_phase_logs_success(self) -> None:
        logs = Nip66RttMultiPhaseLogs(
            open_success=True,
            open_reason=None,
            read_success=True,
            read_reason=None,
            write_success=True,
            write_reason=None,
        )
        result = MagicMock()
        result.logs = logs

        assert log_success(result) is True

    def test_rtt_multi_phase_logs_failure(self) -> None:
        logs = Nip66RttMultiPhaseLogs(
            open_success=False,
            open_reason="timeout",
            read_success=False,
            read_reason="timeout",
            write_success=False,
            write_reason="timeout",
        )
        result = MagicMock()
        result.logs = logs

        assert log_success(result) is False

    def test_unknown_logs_type(self) -> None:
        result = MagicMock()
        result.logs = "not a logs object"

        assert log_success(result) is False


class TestLogReason:
    def test_base_logs_with_reason(self) -> None:
        logs = BaseLogs(success=False, reason="connection refused")
        result = MagicMock()
        result.logs = logs

        assert log_reason(result) == "connection refused"

    def test_base_logs_no_reason(self) -> None:
        logs = BaseLogs(success=True, reason=None)
        result = MagicMock()
        result.logs = logs

        assert log_reason(result) is None

    def test_rtt_multi_phase_logs_with_reason(self) -> None:
        logs = Nip66RttMultiPhaseLogs(
            open_success=False,
            open_reason="timeout",
            read_success=False,
            read_reason="timeout",
            write_success=False,
            write_reason="timeout",
        )
        result = MagicMock()
        result.logs = logs

        assert log_reason(result) == "timeout"

    def test_rtt_multi_phase_logs_no_reason(self) -> None:
        logs = Nip66RttMultiPhaseLogs(
            open_success=True,
            open_reason=None,
            read_success=True,
            read_reason=None,
            write_success=True,
            write_reason=None,
        )
        result = MagicMock()
        result.logs = logs

        assert log_reason(result) is None

    def test_unknown_logs_type(self) -> None:
        result = MagicMock()
        result.logs = "not a logs object"

        assert log_reason(result) is None


class TestExtractResult:
    def test_valid_result(self) -> None:
        results = {"nip11": MagicMock(), "nip66_rtt": MagicMock()}

        value = extract_result(results, "nip11")
        assert value is not None

    def test_exception_result(self) -> None:
        results = {"nip11": ValueError("some error")}

        value = extract_result(results, "nip11")
        assert value is None

    def test_missing_key(self) -> None:
        results = {"nip11": MagicMock()}

        value = extract_result(results, "nip66_rtt")
        assert value is None

    def test_none_value(self) -> None:
        results = {"nip11": None}

        value = extract_result(results, "nip11")
        assert value is None

    def test_base_exception_result(self) -> None:
        results = {"nip11": KeyboardInterrupt()}

        value = extract_result(results, "nip11")
        assert value is None


# ============================================================================
# Queries
# ============================================================================


class TestDeleteStaleCheckpoints:
    async def test_calls_fetchval_with_correct_params(self, query_brotr: MagicMock) -> None:
        query_brotr.fetchval = AsyncMock(return_value=4)

        result = await delete_stale_checkpoints(query_brotr, ["announcement", "profile"])

        query_brotr.fetchval.assert_awaited_once()
        args = query_brotr.fetchval.call_args
        sql = args[0][0]
        assert "DELETE FROM service_state" in sql
        assert "!= ALL" in sql
        assert "NOT EXISTS" in sql
        assert args[0][1] == ServiceName.MONITOR
        assert args[0][2] == ServiceStateType.CHECKPOINT
        assert args[0][3] == ["announcement", "profile"]
        assert result == 4


class TestFetchRelaysToMonitor:
    async def test_calls_fetch_with_correct_params(self, query_brotr: MagicMock) -> None:
        await fetch_relays_to_monitor(
            query_brotr,
            monitored_before=1700000000,
            networks=[NetworkType.CLEARNET],
        )

        query_brotr.fetch.assert_awaited_once()
        args = query_brotr.fetch.call_args
        sql = args[0][0]
        assert "FROM relay r" in sql
        assert "LEFT JOIN service_state ss" in sql
        assert "service_name = $3" in sql
        assert "state_type = $4" in sql
        assert "LIMIT" not in sql
        assert args[0][1] == [NetworkType.CLEARNET]
        assert args[0][2] == 1700000000
        assert args[0][3] == ServiceName.MONITOR
        assert args[0][4] == ServiceStateType.CHECKPOINT

    async def test_returns_relay_objects(self, query_brotr: MagicMock) -> None:
        row = _make_dict_row(
            {"url": "wss://relay.example.com", "network": "clearnet", "discovered_at": 1700000000}
        )
        query_brotr.fetch = AsyncMock(return_value=[row])

        result = await fetch_relays_to_monitor(query_brotr, 1700000000, [NetworkType.CLEARNET])

        assert len(result) == 1
        assert result[0].url == "wss://relay.example.com"

    async def test_skips_invalid_urls(self, query_brotr: MagicMock) -> None:
        rows = [
            _make_dict_row(
                {"url": "wss://valid.relay.com", "network": "clearnet", "discovered_at": 1700000000}
            ),
            _make_dict_row(
                {"url": "not-valid", "network": "clearnet", "discovered_at": 1700000000}
            ),
        ]
        query_brotr.fetch = AsyncMock(return_value=rows)

        result = await fetch_relays_to_monitor(query_brotr, 1700000000, [NetworkType.CLEARNET])

        assert len(result) == 1
        assert result[0].url == "wss://valid.relay.com"

    async def test_empty_result(self, query_brotr: MagicMock) -> None:
        result = await fetch_relays_to_monitor(query_brotr, 1700000000, [NetworkType.CLEARNET])

        assert result == []


class TestMonitorRelayPages:
    async def test_count_relays_to_monitor_uses_scalar_query(self, query_brotr: MagicMock) -> None:
        query_brotr.fetchval = AsyncMock(return_value=9)

        result = await count_relays_to_monitor(query_brotr, 1700000000, [NetworkType.CLEARNET])

        assert result == 9
        args = query_brotr.fetchval.call_args[0]
        assert "count(*)::int" in args[0]
        assert args[1] == [NetworkType.CLEARNET]
        assert args[2] == 1700000000
        assert args[3] == ServiceName.MONITOR
        assert args[4] == ServiceStateType.CHECKPOINT

    async def test_page_query_applies_limit_and_after_token(self, query_brotr: MagicMock) -> None:
        await fetch_relays_to_monitor_page(
            query_brotr,
            1700000000,
            [NetworkType.CLEARNET],
            after=None,
            limit=50,
        )

        args = query_brotr.fetch.call_args[0]
        sql = args[0]
        assert "LIMIT $8" in sql
        assert "r.url" in sql
        assert args[8] == 50

    async def test_iter_pages_respects_max_relays(self, query_brotr: MagicMock) -> None:
        query_brotr.fetch = AsyncMock(
            side_effect=[
                [
                    _make_dict_row(
                        {
                            "url": "wss://relay1.example.com",
                            "network": "clearnet",
                            "discovered_at": 1,
                            "last_monitored": 0,
                        }
                    ),
                    _make_dict_row(
                        {
                            "url": "wss://relay2.example.com",
                            "network": "clearnet",
                            "discovered_at": 2,
                            "last_monitored": 0,
                        }
                    ),
                ],
                [
                    _make_dict_row(
                        {
                            "url": "wss://relay3.example.com",
                            "network": "clearnet",
                            "discovered_at": 3,
                            "last_monitored": 0,
                        }
                    ),
                ],
            ]
        )

        pages = [
            page
            async for page in iter_relays_to_monitor_pages(
                query_brotr,
                1700000000,
                [NetworkType.CLEARNET],
                page_size=2,
                max_relays=3,
            )
        ]

        assert [[relay.url for relay in page] for page in pages] == [
            ["wss://relay1.example.com", "wss://relay2.example.com"],
            ["wss://relay3.example.com"],
        ]


class TestInsertRelayMetadata:
    async def test_delegates_to_batched_insert(self, query_brotr: MagicMock) -> None:
        query_brotr.insert_relay_metadata = AsyncMock(return_value=5)

        result = await insert_relay_metadata(query_brotr, [MagicMock(), MagicMock()])

        assert result == 5
        query_brotr.insert_relay_metadata.assert_awaited_once()

    async def test_splits_large_batch(self, query_brotr: MagicMock) -> None:
        query_brotr.config.batch.max_size = 2
        query_brotr.insert_relay_metadata = AsyncMock(return_value=2)

        records = [MagicMock() for _ in range(5)]
        result = await insert_relay_metadata(query_brotr, records)

        assert result == 6  # 2 + 2 + 2
        assert query_brotr.insert_relay_metadata.await_count == 3

    async def test_empty_returns_zero(self, query_brotr: MagicMock) -> None:
        result = await insert_relay_metadata(query_brotr, [])
        assert result == 0
        query_brotr.insert_relay_metadata.assert_not_awaited()


class TestSaveMonitoringMarkers:
    async def test_calls_upsert_for_each_relay(self, query_brotr: MagicMock) -> None:
        query_brotr.upsert_service_state = AsyncMock(return_value=2)

        relays = [Relay("wss://r1.example.com"), Relay("wss://r2.example.com")]
        await upsert_monitor_checkpoints(query_brotr, relays, 1700000000)

        query_brotr.upsert_service_state.assert_awaited_once()
        states = query_brotr.upsert_service_state.call_args[0][0]
        assert len(states) == 2

    async def test_state_record_fields(self, query_brotr: MagicMock) -> None:
        query_brotr.upsert_service_state = AsyncMock(return_value=1)

        relay = Relay("wss://relay.example.com")
        now = 1700000000
        await upsert_monitor_checkpoints(query_brotr, [relay], now)

        states = query_brotr.upsert_service_state.call_args[0][0]
        state = states[0]
        assert isinstance(state, ServiceState)
        assert state.service_name == ServiceName.MONITOR
        assert state.state_type == ServiceStateType.CHECKPOINT
        assert state.state_key == relay.url
        assert state.state_value == {"timestamp": now}

    async def test_empty_relay_list_no_db_call(self, query_brotr: MagicMock) -> None:
        query_brotr.upsert_service_state = AsyncMock(return_value=0)

        await upsert_monitor_checkpoints(query_brotr, [], 1700000000)

        query_brotr.upsert_service_state.assert_not_awaited()


class TestIsPublishDue:
    async def test_no_prior_state_returns_true(self, query_brotr: MagicMock) -> None:
        query_brotr.fetch = AsyncMock(return_value=[])
        assert await is_publish_due(query_brotr, "announcement", 86400) is True

    async def test_interval_not_elapsed_returns_false(self, query_brotr: MagicMock) -> None:
        now = int(time.time())
        query_brotr.fetch = AsyncMock(
            return_value=[{"state_key": "announcement", "state_value": {"timestamp": now}}]
        )
        assert await is_publish_due(query_brotr, "announcement", 86400) is False

    async def test_interval_elapsed_returns_true(self, query_brotr: MagicMock) -> None:
        old = int(time.time()) - 100_000
        query_brotr.fetch = AsyncMock(
            return_value=[{"state_key": "profile", "state_value": {"timestamp": old}}]
        )
        assert await is_publish_due(query_brotr, "profile", 86400) is True

    async def test_missing_timestamp_key_returns_true(self, query_brotr: MagicMock) -> None:
        query_brotr.fetch = AsyncMock(
            return_value=[{"state_key": "announcement", "state_value": {}}]
        )
        assert await is_publish_due(query_brotr, "announcement", 86400) is True

    async def test_invalid_key_raises(self, query_brotr: MagicMock) -> None:
        with pytest.raises(ValueError, match="invalid publish keys"):
            await is_publish_due(query_brotr, "bogus", 86400)


class TestUpsertPublishCheckpoints:
    async def test_upserts_single_checkpoint(self, query_brotr: MagicMock) -> None:
        query_brotr.upsert_service_state = AsyncMock(return_value=1)

        await upsert_publish_checkpoints(query_brotr, ["announcement"])

        query_brotr.upsert_service_state.assert_awaited_once()
        states = query_brotr.upsert_service_state.call_args[0][0]
        assert len(states) == 1
        state = states[0]
        assert isinstance(state, ServiceState)
        assert state.service_name == ServiceName.MONITOR
        assert state.state_type == ServiceStateType.CHECKPOINT
        assert state.state_key == "announcement"
        assert "timestamp" in state.state_value

    async def test_upserts_multiple_checkpoints(self, query_brotr: MagicMock) -> None:
        query_brotr.upsert_service_state = AsyncMock(return_value=2)

        await upsert_publish_checkpoints(query_brotr, ["announcement", "profile"])

        query_brotr.upsert_service_state.assert_awaited_once()
        states = query_brotr.upsert_service_state.call_args[0][0]
        assert len(states) == 2
        keys = {s.state_key for s in states}
        assert keys == {"announcement", "profile"}

    async def test_empty_list_skips(self, query_brotr: MagicMock) -> None:
        query_brotr.upsert_service_state = AsyncMock(return_value=0)

        await upsert_publish_checkpoints(query_brotr, [])

        query_brotr.upsert_service_state.assert_not_awaited()

    async def test_invalid_key_raises(self, query_brotr: MagicMock) -> None:
        with pytest.raises(ValueError, match="invalid publish keys"):
            await upsert_publish_checkpoints(query_brotr, ["bogus"])


# ============================================================================
# Service: Monitor init
# ============================================================================


class TestMonitorInit:
    def test_init_with_defaults(self, mock_brotr: Brotr, tmp_path: Path) -> None:
        config = _make_config()
        monitor = Monitor(brotr=mock_brotr, config=config)

        assert monitor._brotr is mock_brotr
        assert monitor.SERVICE_NAME == "monitor"

    def test_init_with_custom_config(self, mock_brotr: Brotr, tmp_path: Path) -> None:
        config = _make_config(networks=NetworksConfig(tor=TorConfig(enabled=False)))
        monitor = Monitor(brotr=mock_brotr, config=config)

        assert monitor.config.networks.tor.enabled is False

    def test_config_class_attribute(self, mock_brotr: Brotr) -> None:
        assert MonitorConfig == Monitor.CONFIG_CLASS

    def test_service_name_attribute(self, mock_brotr: Brotr) -> None:
        assert Monitor.SERVICE_NAME == "monitor"


class TestMonitorHelpers:
    def test_publish_context_uses_monitor_dependencies(self, mock_brotr: Brotr) -> None:
        config = _make_config()
        monitor = Monitor(brotr=mock_brotr, config=config)

        context = monitor._publish_context()

        assert context.brotr is mock_brotr
        assert context.config is config
        assert context.clients is monitor.clients
        assert context.logger is monitor._logger
        assert context.is_due is is_publish_due
        assert context.broadcast is broadcast_events_detailed
        assert context.save_checkpoints is upsert_publish_checkpoints

    def test_check_context_defaults_to_network_timeout_and_proxy(self, mock_brotr: Brotr) -> None:
        config = _make_config(
            networks=NetworksConfig(
                clearnet=ClearnetConfig(timeout=5.0),
                tor=TorConfig(enabled=True, timeout=30.0, proxy_url="socks5://tor:9050"),
            )
        )
        monitor = Monitor(brotr=mock_brotr, config=config)
        relay = Relay(f"ws://{'a' * 56}.onion")
        monitor.geo_readers.city = MagicMock()
        monitor.geo_readers.asn = MagicMock()

        context = monitor._check_context(relay, generated_at=123)

        assert context.relay == relay
        assert context.compute == config.processing.compute
        assert context.timeout == 30.0
        assert context.proxy_url == "socks5://tor:9050"
        assert context.generated_at == 123
        assert context.city_reader is monitor.geo_readers.city
        assert context.asn_reader is monitor.geo_readers.asn

    def test_check_dependencies_match_monitor_probe_functions(self, mock_brotr: Brotr) -> None:
        monitor = Monitor(brotr=mock_brotr, config=_make_config())

        deps = monitor._check_dependencies()

        assert deps.retry_fetch is retry_fetch
        assert deps.nip11_fetch.__func__ is Nip11.fetch.__func__
        assert deps.rtt_probe.__func__ is Nip66RttMetadata.probe.__func__
        assert deps.ssl_probe.__func__ is Nip66SslMetadata.probe.__func__
        assert deps.geo_probe.__func__ is Nip66GeoMetadata.probe.__func__
        assert deps.net_probe.__func__ is Nip66NetMetadata.probe.__func__
        assert deps.dns_probe.__func__ is Nip66DnsMetadata.probe.__func__
        assert deps.http_probe.__func__ is Nip66HttpMetadata.probe.__func__


# ============================================================================
# Service: Monitor run
# ============================================================================


class TestMonitorRun:
    @patch(
        "bigbrotr.services.monitor.service.iter_relays_to_monitor_pages",
        return_value=_mock_pages(),
    )
    @patch(
        "bigbrotr.services.monitor.service.count_relays_to_monitor",
        new_callable=AsyncMock,
        return_value=0,
    )
    @patch(
        "bigbrotr.services.monitor.service.is_publish_due",
        new_callable=AsyncMock,
        return_value=False,
    )
    async def test_run_no_relays(
        self,
        mock_publish_due: AsyncMock,
        mock_count: AsyncMock,
        mock_iter_pages: MagicMock,
        mock_brotr: Brotr,
        tmp_path: Path,
    ) -> None:
        config = _make_config()
        monitor = Monitor(brotr=mock_brotr, config=config)
        monitor.clients = MagicMock()
        monitor.clients.get = AsyncMock(return_value=None)
        monitor.clients.get_many = AsyncMock(return_value=[])
        monitor.clients.disconnect = AsyncMock()
        await monitor.run()

        mock_count.assert_awaited_once()
        mock_iter_pages.assert_called_once()

    async def test_monitor_no_networks_enabled_returns_zero(self, mock_brotr: Brotr) -> None:
        no_clearnet = MetadataFlags(
            nip66_ssl=False, nip66_geo=False, nip66_net=False, nip66_dns=False
        )
        config = _make_config(
            networks=NetworksConfig(
                clearnet=ClearnetConfig(enabled=False),
                tor=TorConfig(enabled=False),
                i2p=I2pConfig(enabled=False),
                loki=LokiConfig(enabled=False),
            ),
            processing=ProcessingConfig(compute=no_clearnet, store=no_clearnet),
            discovery=DiscoveryConfig(include=no_clearnet),
            announcement=AnnouncementConfig(include=no_clearnet),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)

        result = await monitor.monitor()

        assert result == 0


# ============================================================================
# Service: Monitor cleanup
# ============================================================================


class TestMonitorCleanup:
    @patch(
        "bigbrotr.services.monitor.service.delete_stale_checkpoints",
        new_callable=AsyncMock,
        return_value=3,
    )
    async def test_cleanup_both_enabled(self, mock_delete: AsyncMock, mock_brotr: Brotr) -> None:
        config = _make_config(profile=ProfileConfig(enabled=True))
        monitor = Monitor(brotr=mock_brotr, config=config)
        result = await monitor.cleanup()

        mock_delete.assert_awaited_once_with(mock_brotr, ["announcement", "profile", "relay_list"])
        assert result == 3

    @patch(
        "bigbrotr.services.monitor.service.delete_stale_checkpoints",
        new_callable=AsyncMock,
        return_value=2,
    )
    async def test_cleanup_announcement_disabled(
        self, mock_delete: AsyncMock, mock_brotr: Brotr
    ) -> None:
        config = _make_config(
            announcement=AnnouncementConfig(enabled=False, include=_NO_GEO_NET),
            profile=ProfileConfig(enabled=True),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)
        result = await monitor.cleanup()

        mock_delete.assert_awaited_once_with(mock_brotr, ["profile", "relay_list"])
        assert result == 2

    @patch(
        "bigbrotr.services.monitor.service.delete_stale_checkpoints",
        new_callable=AsyncMock,
        return_value=1,
    )
    async def test_cleanup_profile_disabled(
        self, mock_delete: AsyncMock, mock_brotr: Brotr
    ) -> None:
        config = _make_config(profile=ProfileConfig(enabled=False))
        monitor = Monitor(brotr=mock_brotr, config=config)
        result = await monitor.cleanup()

        mock_delete.assert_awaited_once_with(mock_brotr, ["announcement", "relay_list"])
        assert result == 1

    @patch(
        "bigbrotr.services.monitor.service.delete_stale_checkpoints",
        new_callable=AsyncMock,
        return_value=5,
    )
    async def test_cleanup_both_disabled(self, mock_delete: AsyncMock, mock_brotr: Brotr) -> None:
        config = _make_config(
            announcement=AnnouncementConfig(enabled=False, include=_NO_GEO_NET),
            profile=ProfileConfig(enabled=False),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)
        result = await monitor.cleanup()

        mock_delete.assert_awaited_once_with(mock_brotr, ["relay_list"])
        assert result == 5

    @patch(
        "bigbrotr.services.monitor.service.delete_stale_checkpoints",
        new_callable=AsyncMock,
        return_value=0,
    )
    async def test_cleanup_all_disabled(self, mock_delete: AsyncMock, mock_brotr: Brotr) -> None:
        config = _make_config(
            announcement=AnnouncementConfig(enabled=False, include=_NO_GEO_NET),
            profile=ProfileConfig(enabled=False),
            relay_list=RelayListConfig(enabled=False),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)
        result = await monitor.cleanup()

        mock_delete.assert_awaited_once_with(mock_brotr, [])
        assert result == 0


# ============================================================================
# Service: Monitoring worker
# ============================================================================


class TestMonitoringWorker:
    async def test_successful_result(self, mock_brotr: Brotr) -> None:
        config = _make_config()
        monitor = Monitor(brotr=mock_brotr, config=config)
        relay = Relay("wss://relay.example.com")
        result = _make_check_result(nip66_rtt=_make_rtt_meta(rtt_open=100))

        with patch.object(
            Monitor,
            "check_relay",
            new_callable=AsyncMock,
            return_value=result,
        ):
            results = [item async for item in monitor._monitor_worker(relay)]
            r, res = results[0]

        assert r is relay
        assert res is result

    async def test_empty_result_returns_none(self, mock_brotr: Brotr) -> None:
        config = _make_config()
        monitor = Monitor(brotr=mock_brotr, config=config)
        relay = Relay("wss://relay.example.com")
        empty_result = _make_check_result()

        with patch.object(
            Monitor,
            "check_relay",
            new_callable=AsyncMock,
            return_value=empty_result,
        ):
            results = [item async for item in monitor._monitor_worker(relay)]
            r, res = results[0]

        assert r is relay
        assert res is None

    async def test_exception_returns_none(self, mock_brotr: Brotr) -> None:
        config = _make_config()
        monitor = Monitor(brotr=mock_brotr, config=config)
        relay = Relay("wss://relay.example.com")

        with patch.object(
            Monitor,
            "check_relay",
            new_callable=AsyncMock,
            side_effect=RuntimeError("connection lost"),
        ):
            results = [item async for item in monitor._monitor_worker(relay)]
            r, res = results[0]

        assert r is relay
        assert res is None

    @pytest.mark.parametrize("exc_type", [asyncio.CancelledError, KeyboardInterrupt, SystemExit])
    async def test_fatal_exception_propagates(
        self, exc_type: type[BaseException], mock_brotr: Brotr
    ) -> None:
        config = _make_config()
        monitor = Monitor(brotr=mock_brotr, config=config)
        relay = Relay("wss://relay.example.com")

        with (
            patch.object(
                Monitor,
                "check_relay",
                new_callable=AsyncMock,
                side_effect=exc_type,
            ),
            pytest.raises(exc_type),
        ):
            async for _ in monitor._monitor_worker(relay):
                pass


# ============================================================================
# Service: Publish announcement
# ============================================================================


class TestPublishAnnouncement:
    async def test_publish_announcement_when_disabled(self, test_keys: Keys) -> None:
        config = _make_config(announcement=AnnouncementConfig(enabled=False, include=_NO_GEO_NET))
        harness = _MonitorStub(config, test_keys)
        with patch(
            "bigbrotr.services.monitor.service.is_publish_due", new_callable=AsyncMock
        ) as mock_get:
            await harness.publish_announcement()
            mock_get.assert_not_awaited()

    async def test_publish_announcement_when_no_relays(self, test_keys: Keys) -> None:
        config = _make_config(
            announcement=AnnouncementConfig(enabled=True, include=_NO_GEO_NET, relays=[]),
            publishing=PublishingConfig(relays=[]),
        )
        harness = _MonitorStub(config, test_keys)
        with patch(
            "bigbrotr.services.monitor.service.is_publish_due", new_callable=AsyncMock
        ) as mock_get:
            await harness.publish_announcement()
            mock_get.assert_not_awaited()

    async def test_publish_announcement_interval_not_elapsed(self, stub: _MonitorStub) -> None:
        with patch(
            "bigbrotr.services.monitor.service.is_publish_due",
            new_callable=AsyncMock,
            return_value=False,
        ):
            await stub.publish_announcement()
            stub.clients.get_many.assert_not_awaited()

    async def test_publish_announcement_no_prior_state(self, stub: _MonitorStub) -> None:
        with (
            patch(
                "bigbrotr.services.monitor.service.is_publish_due",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "bigbrotr.services.monitor.service.broadcast_events_detailed",
                new_callable=AsyncMock,
                return_value=_broadcast_results(),
            ) as mock_broadcast,
            patch(
                "bigbrotr.services.monitor.service.upsert_publish_checkpoints",
                new_callable=AsyncMock,
            ) as mock_save,
        ):
            await stub.publish_announcement()

        mock_broadcast.assert_awaited_once()
        mock_save.assert_awaited_once()
        stub._logger.info.assert_called_with(
            "publish_completed",
            event="announcement",
            relays=1,
            failed_relays=0,
        )

    async def test_publish_announcement_interval_elapsed(self, stub: _MonitorStub) -> None:
        with (
            patch(
                "bigbrotr.services.monitor.service.is_publish_due",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "bigbrotr.services.monitor.service.broadcast_events_detailed",
                new_callable=AsyncMock,
                return_value=_broadcast_results(),
            ) as mock_broadcast,
            patch(
                "bigbrotr.services.monitor.service.upsert_publish_checkpoints",
                new_callable=AsyncMock,
            ) as mock_save,
        ):
            await stub.publish_announcement()

        mock_broadcast.assert_awaited_once()
        mock_save.assert_awaited_once()

    async def test_publish_announcement_no_reachable_clients(self, stub: _MonitorStub) -> None:
        stub.clients.get_many = AsyncMock(return_value=[])
        with (
            patch(
                "bigbrotr.services.monitor.service.is_publish_due",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "bigbrotr.services.monitor.service.broadcast_events_detailed",
                new_callable=AsyncMock,
            ) as mock_broadcast,
        ):
            await stub.publish_announcement()

        mock_broadcast.assert_not_awaited()
        stub._logger.warning.assert_called_once_with(
            "publish_failed", event="announcement", error="no relays reachable"
        )

    async def test_publish_announcement_broadcast_failure(self, stub: _MonitorStub) -> None:
        with (
            patch(
                "bigbrotr.services.monitor.service.is_publish_due",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "bigbrotr.services.monitor.service.broadcast_events_detailed",
                new_callable=AsyncMock,
                return_value=_broadcast_results(
                    successful_relays=(),
                    failed_relays={"wss://publish.example.com": "timeout"},
                ),
            ),
            patch(
                "bigbrotr.services.monitor.service.upsert_publish_checkpoints",
                new_callable=AsyncMock,
            ) as mock_save,
        ):
            await stub.publish_announcement()

        mock_save.assert_not_awaited()
        stub._logger.warning.assert_called_once()
        stub._logger.warning.assert_called_once_with(
            "publish_failed",
            event="announcement",
            error="no relays accepted event",
            failed_relays={"wss://publish.example.com": "timeout"},
        )


# ============================================================================
# Service: Publish profile
# ============================================================================


class TestPublishProfile:
    async def test_publish_profile_when_disabled(self, test_keys: Keys) -> None:
        config = _make_config(profile=ProfileConfig(enabled=False))
        harness = _MonitorStub(config, test_keys)
        with patch(
            "bigbrotr.services.monitor.service.is_publish_due", new_callable=AsyncMock
        ) as mock_get:
            await harness.publish_profile()
            mock_get.assert_not_awaited()

    async def test_publish_profile_when_no_relays(self, test_keys: Keys) -> None:
        config = _make_config(
            profile=ProfileConfig(enabled=True, relays=[]),
            publishing=PublishingConfig(relays=[]),
        )
        harness = _MonitorStub(config, test_keys)
        with patch(
            "bigbrotr.services.monitor.service.is_publish_due", new_callable=AsyncMock
        ) as mock_get:
            await harness.publish_profile()
            mock_get.assert_not_awaited()

    async def test_publish_profile_interval_not_elapsed(self, stub: _MonitorStub) -> None:
        with patch(
            "bigbrotr.services.monitor.service.is_publish_due",
            new_callable=AsyncMock,
            return_value=False,
        ):
            await stub.publish_profile()
            stub.clients.get_many.assert_not_awaited()

    async def test_publish_profile_successful(self, stub: _MonitorStub) -> None:
        with (
            patch(
                "bigbrotr.services.monitor.service.is_publish_due",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "bigbrotr.services.monitor.service.broadcast_events_detailed",
                new_callable=AsyncMock,
                return_value=_broadcast_results(),
            ) as mock_broadcast,
            patch(
                "bigbrotr.services.monitor.service.upsert_publish_checkpoints",
                new_callable=AsyncMock,
            ) as mock_save,
        ):
            await stub.publish_profile()

        mock_broadcast.assert_awaited_once()
        mock_save.assert_awaited_once()
        stub._logger.info.assert_called_with(
            "publish_completed",
            event="profile",
            relays=1,
            failed_relays=0,
        )

    async def test_publish_profile_no_reachable_clients(self, stub: _MonitorStub) -> None:
        stub.clients.get_many = AsyncMock(return_value=[])
        with (
            patch(
                "bigbrotr.services.monitor.service.is_publish_due",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "bigbrotr.services.monitor.service.broadcast_events_detailed",
                new_callable=AsyncMock,
            ) as mock_broadcast,
        ):
            await stub.publish_profile()

        mock_broadcast.assert_not_awaited()
        stub._logger.warning.assert_called_once_with(
            "publish_failed", event="profile", error="no relays reachable"
        )

    async def test_publish_profile_broadcast_failure(self, stub: _MonitorStub) -> None:
        with (
            patch(
                "bigbrotr.services.monitor.service.is_publish_due",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "bigbrotr.services.monitor.service.broadcast_events_detailed",
                new_callable=AsyncMock,
                return_value=_broadcast_results(
                    successful_relays=(),
                    failed_relays={"wss://publish.example.com": "timeout"},
                ),
            ),
            patch(
                "bigbrotr.services.monitor.service.upsert_publish_checkpoints",
                new_callable=AsyncMock,
            ) as mock_save,
        ):
            await stub.publish_profile()

        mock_save.assert_not_awaited()
        stub._logger.warning.assert_called_once()
        stub._logger.warning.assert_called_once_with(
            "publish_failed",
            event="profile",
            error="no relays accepted event",
            failed_relays={"wss://publish.example.com": "timeout"},
        )


# ============================================================================
# Service: Publish relay list (Kind 10002)
# ============================================================================


class TestPublishRelayList:
    async def test_disabled(self, test_keys: Keys) -> None:
        config = _make_config(relay_list=RelayListConfig(enabled=False))
        harness = _MonitorStub(config, test_keys)
        with patch(
            "bigbrotr.services.monitor.service.is_publish_due", new_callable=AsyncMock
        ) as mock_due:
            await harness.publish_relay_list()
            mock_due.assert_not_awaited()

    async def test_uses_override_relays(self, stub: _MonitorStub) -> None:
        stub._config = _make_config(
            relay_list=RelayListConfig(enabled=True, relays=["wss://custom.relay.com"]),
        )
        with (
            patch(
                "bigbrotr.services.monitor.service.is_publish_due",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "bigbrotr.services.monitor.service.broadcast_events_detailed",
                new_callable=AsyncMock,
                return_value=_broadcast_results(),
            ),
            patch(
                "bigbrotr.services.monitor.service.upsert_publish_checkpoints",
                new_callable=AsyncMock,
            ),
        ):
            await stub.publish_relay_list()
        stub.clients.get_many.assert_awaited_once()
        call_relays = stub.clients.get_many.call_args[0][0]
        assert len(call_relays) == 1
        assert call_relays[0].url == "wss://custom.relay.com"

    async def test_no_relays(self, test_keys: Keys) -> None:
        config = _make_config(
            relay_list=RelayListConfig(enabled=True, relays=[]),
            publishing=PublishingConfig(relays=[]),
        )
        harness = _MonitorStub(config, test_keys)
        with patch(
            "bigbrotr.services.monitor.service.is_publish_due", new_callable=AsyncMock
        ) as mock_due:
            await harness.publish_relay_list()
            mock_due.assert_not_awaited()

    async def test_interval_not_elapsed(self, stub: _MonitorStub) -> None:
        with patch(
            "bigbrotr.services.monitor.service.is_publish_due",
            new_callable=AsyncMock,
            return_value=False,
        ):
            await stub.publish_relay_list()
            stub.clients.get_many.assert_not_awaited()

    async def test_successful(self, stub: _MonitorStub) -> None:
        with (
            patch(
                "bigbrotr.services.monitor.service.is_publish_due",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "bigbrotr.services.monitor.service.broadcast_events_detailed",
                new_callable=AsyncMock,
                return_value=_broadcast_results(),
            ) as mock_broadcast,
            patch(
                "bigbrotr.services.monitor.service.upsert_publish_checkpoints",
                new_callable=AsyncMock,
            ) as mock_save,
        ):
            await stub.publish_relay_list()

        mock_broadcast.assert_awaited_once()
        mock_save.assert_awaited_once_with(stub._brotr, ["relay_list"])
        stub._logger.info.assert_called_with(
            "publish_completed",
            event="relay_list",
            relays=1,
            failed_relays=0,
        )

    async def test_no_reachable_clients(self, stub: _MonitorStub) -> None:
        stub.clients.get_many = AsyncMock(return_value=[])
        with (
            patch(
                "bigbrotr.services.monitor.service.is_publish_due",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "bigbrotr.services.monitor.service.broadcast_events_detailed",
                new_callable=AsyncMock,
            ) as mock_broadcast,
        ):
            await stub.publish_relay_list()

        mock_broadcast.assert_not_awaited()
        stub._logger.warning.assert_called_once_with(
            "publish_failed", event="relay_list", error="no relays reachable"
        )

    async def test_broadcast_failure(self, stub: _MonitorStub) -> None:
        with (
            patch(
                "bigbrotr.services.monitor.service.is_publish_due",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "bigbrotr.services.monitor.service.broadcast_events_detailed",
                new_callable=AsyncMock,
                return_value=_broadcast_results(
                    successful_relays=(),
                    failed_relays={"wss://publish.example.com": "timeout"},
                ),
            ),
            patch(
                "bigbrotr.services.monitor.service.upsert_publish_checkpoints",
                new_callable=AsyncMock,
            ) as mock_save,
        ):
            await stub.publish_relay_list()

        mock_save.assert_not_awaited()
        stub._logger.warning.assert_called_once_with(
            "publish_failed",
            event="relay_list",
            error="no relays accepted event",
            failed_relays={"wss://publish.example.com": "timeout"},
        )


# ============================================================================
# Service: Publish relay discoveries
# ============================================================================


class TestPublishDiscovery:
    async def test_publish_discovery_disabled(self, mock_brotr: Brotr) -> None:
        config = _make_config(discovery=DiscoveryConfig(enabled=False, include=_NO_GEO_NET))
        monitor = Monitor(brotr=mock_brotr, config=config)
        relay = Relay("wss://relay.example.com")
        result = _make_check_result(nip11_info=_make_nip11_meta(name="Test"))

        with patch(
            "bigbrotr.services.monitor.service.broadcast_events_detailed",
            new_callable=AsyncMock,
        ) as mock_broadcast:
            await monitor.publish_discovery(relay, result)
            mock_broadcast.assert_not_awaited()

    async def test_publish_discovery_no_relays(self, mock_brotr: Brotr) -> None:
        config = _make_config(publishing=PublishingConfig(relays=[]))
        monitor = Monitor(brotr=mock_brotr, config=config)
        relay = Relay("wss://relay.example.com")
        result = _make_check_result(nip11_info=_make_nip11_meta(name="Test"))

        with patch(
            "bigbrotr.services.monitor.service.broadcast_events_detailed",
            new_callable=AsyncMock,
        ) as mock_broadcast:
            await monitor.publish_discovery(relay, result)
            mock_broadcast.assert_not_awaited()

    async def test_publish_discovery_no_reachable_clients(self, mock_brotr: Brotr) -> None:
        config = _make_config(
            discovery=DiscoveryConfig(
                include=_NO_GEO_NET,
                relays=["wss://publish.example.com"],
            ),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)
        monitor.clients = MagicMock()
        monitor.clients.get_many = AsyncMock(return_value=[])
        relay = Relay("wss://relay.example.com")
        result = _make_check_result(nip11_info=_make_nip11_meta(name="Test"))

        with patch(
            "bigbrotr.services.monitor.service.broadcast_events_detailed",
            new_callable=AsyncMock,
        ) as mock_broadcast:
            await monitor.publish_discovery(relay, result)
            mock_broadcast.assert_not_awaited()

    async def test_publish_discovery_successful(self, mock_brotr: Brotr) -> None:
        config = _make_config(
            discovery=DiscoveryConfig(
                include=_NO_GEO_NET,
                relays=["wss://publish.example.com"],
            ),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)
        monitor.clients = MagicMock()
        monitor.clients.get_many = AsyncMock(return_value=[AsyncMock()])
        relay = Relay("wss://relay.example.com")
        result = _make_check_result(nip11_info=_make_nip11_meta(name="Test Relay"))

        with patch(
            "bigbrotr.services.monitor.service.broadcast_events_detailed",
            new_callable=AsyncMock,
            return_value=_broadcast_results(),
        ) as mock_broadcast:
            await monitor.publish_discovery(relay, result)

        mock_broadcast.assert_awaited_once()

    async def test_publish_discovery_build_failure(self, mock_brotr: Brotr) -> None:
        config = _make_config(
            discovery=DiscoveryConfig(
                include=_NO_GEO_NET,
                relays=["wss://publish.example.com"],
            ),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)
        monitor.clients = MagicMock()
        monitor.clients.get_many = AsyncMock(return_value=[AsyncMock()])
        relay = Relay("wss://relay.example.com")
        result = _make_check_result()

        with (
            patch(
                "bigbrotr.services.monitor.service.build_relay_discovery",
                side_effect=ValueError("build failed"),
            ),
            patch(
                "bigbrotr.services.monitor.service.broadcast_events_detailed",
                new_callable=AsyncMock,
            ) as mock_broadcast,
        ):
            await monitor.publish_discovery(relay, result)

        mock_broadcast.assert_not_awaited()

    async def test_publish_discovery_broadcast_failure(self, mock_brotr: Brotr) -> None:
        config = _make_config(
            discovery=DiscoveryConfig(
                include=_NO_GEO_NET,
                relays=["wss://publish.example.com"],
            ),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)
        monitor._logger = MagicMock()
        monitor.clients = MagicMock()
        monitor.clients.get_many = AsyncMock(return_value=[AsyncMock()])
        relay = Relay("wss://relay.example.com")
        result = _make_check_result(nip11_info=_make_nip11_meta(name="Test"))

        with patch(
            "bigbrotr.services.monitor.service.broadcast_events_detailed",
            new_callable=AsyncMock,
            return_value=_broadcast_results(
                successful_relays=(),
                failed_relays={"wss://publish.example.com": "timeout"},
            ),
        ):
            await monitor.publish_discovery(relay, result)

        monitor._logger.debug.assert_any_call(
            "discovery_broadcast_failed",
            url=relay.url,
            failed_relays={"wss://publish.example.com": "timeout"},
        )


# ============================================================================
# Service -- Prometheus metrics
# ============================================================================


class TestMonitorMetrics:
    async def test_monitor_emits_gauges(self, mock_brotr: Brotr) -> None:
        config = _make_config(
            discovery=DiscoveryConfig(
                enabled=False,
                include=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)

        relay1 = Relay("wss://ok.example.com")
        relay2 = Relay("wss://fail.example.com")
        result = _make_check_result(nip66_rtt=_make_rtt_meta(rtt_open=50))

        async def fake_monitor_worker(relay: Relay):
            if relay.url == relay1.url:
                yield (relay, result)
            else:
                yield (relay, None)

        monitor.clients = MagicMock()
        monitor.clients.get = AsyncMock(return_value=None)
        monitor.clients.get_many = AsyncMock(return_value=[])
        monitor.clients.disconnect = AsyncMock()

        with (
            patch(
                "bigbrotr.services.monitor.service.count_relays_to_monitor",
                new_callable=AsyncMock,
                return_value=2,
            ),
            patch(
                "bigbrotr.services.monitor.service.iter_relays_to_monitor_pages",
                return_value=_mock_pages([relay1, relay2]),
            ),
            patch.object(monitor, "_monitor_worker", side_effect=fake_monitor_worker),
            patch(
                "bigbrotr.services.monitor.service.insert_relay_metadata",
                new_callable=AsyncMock,
            ),
            patch(
                "bigbrotr.services.monitor.service.upsert_monitor_checkpoints",
                new_callable=AsyncMock,
            ),
            patch.object(monitor, "set_gauge") as mock_set,
            patch.object(monitor, "inc_gauge") as mock_inc,
        ):
            await monitor.monitor()

        mock_set.assert_any_call("total", 2)
        succeeded = [c for c in mock_inc.call_args_list if c.args[0] == "succeeded"]
        failed = [c for c in mock_inc.call_args_list if c.args[0] == "failed"]
        assert len(succeeded) == 1
        assert len(failed) == 1


# ============================================================================
# Update Geo Databases
# ============================================================================


class TestUpdateGeoDatabases:
    async def test_skips_when_no_geo_or_net_enabled(self, mock_brotr: Brotr) -> None:
        config = _make_config(
            processing=ProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=False),
                store=MetadataFlags(nip66_geo=False, nip66_net=False),
            ),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)
        with patch(
            "bigbrotr.services.monitor.service.download_bounded_file",
            new_callable=AsyncMock,
        ) as mock_download:
            await monitor.update_geo_databases()
            mock_download.assert_not_awaited()

    async def test_downloads_missing_city_db(self, mock_brotr: Brotr, tmp_path: Path) -> None:
        city_path = str(tmp_path / "missing_city.mmdb")
        config = _make_config(
            processing=ProcessingConfig(
                compute=MetadataFlags(nip66_geo=True, nip66_net=False),
                store=MetadataFlags(nip66_geo=True, nip66_net=False),
            ),
            geo=GeoConfig(
                city_database_path=city_path,
                city_download_url="https://example.com/city.mmdb",
            ),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)
        with patch(
            "bigbrotr.services.monitor.service.download_bounded_file",
            new_callable=AsyncMock,
        ) as mock_download:
            await monitor.update_geo_databases()
            mock_download.assert_awaited_once()

    async def test_downloads_missing_asn_db(self, mock_brotr: Brotr, tmp_path: Path) -> None:
        asn_path = str(tmp_path / "missing_asn.mmdb")
        config = _make_config(
            processing=ProcessingConfig(
                compute=MetadataFlags(nip66_geo=False, nip66_net=True),
                store=MetadataFlags(nip66_geo=False, nip66_net=True),
            ),
            geo=GeoConfig(
                asn_database_path=asn_path,
                asn_download_url="https://example.com/asn.mmdb",
            ),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)
        with patch(
            "bigbrotr.services.monitor.service.download_bounded_file",
            new_callable=AsyncMock,
        ) as mock_download:
            await monitor.update_geo_databases()
            mock_download.assert_awaited_once()

    async def test_skips_fresh_db(self, mock_brotr: Brotr, tmp_path: Path) -> None:
        city_file = tmp_path / "city.mmdb"
        city_file.write_bytes(b"data")
        config = _make_config(
            processing=ProcessingConfig(
                compute=MetadataFlags(nip66_geo=True, nip66_net=False),
                store=MetadataFlags(nip66_geo=True, nip66_net=False),
            ),
            geo=GeoConfig(
                city_database_path=str(city_file),
                city_download_url="https://example.com/city.mmdb",
                max_age_days=30,
            ),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)
        with patch(
            "bigbrotr.services.monitor.service.download_bounded_file",
            new_callable=AsyncMock,
        ) as mock_download:
            await monitor.update_geo_databases()
            mock_download.assert_not_awaited()

    async def test_skips_when_max_age_none(self, mock_brotr: Brotr, tmp_path: Path) -> None:
        city_file = tmp_path / "city.mmdb"
        city_file.write_bytes(b"data")
        config = _make_config(
            processing=ProcessingConfig(
                compute=MetadataFlags(nip66_geo=True, nip66_net=False),
                store=MetadataFlags(nip66_geo=True, nip66_net=False),
            ),
            geo=GeoConfig(
                city_database_path=str(city_file),
                city_download_url="https://example.com/city.mmdb",
                max_age_days=None,
            ),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)
        with patch(
            "bigbrotr.services.monitor.service.download_bounded_file",
            new_callable=AsyncMock,
        ) as mock_download:
            await monitor.update_geo_databases()
            mock_download.assert_not_awaited()

    async def test_redownloads_stale_db(self, mock_brotr: Brotr, tmp_path: Path) -> None:
        import os

        city_file = tmp_path / "city.mmdb"
        city_file.write_bytes(b"data")
        stale_time = time.time() - (31 * 86400)
        os.utime(city_file, (stale_time, stale_time))
        config = _make_config(
            processing=ProcessingConfig(
                compute=MetadataFlags(nip66_geo=True, nip66_net=False),
                store=MetadataFlags(nip66_geo=True, nip66_net=False),
            ),
            geo=GeoConfig(
                city_database_path=str(city_file),
                city_download_url="https://example.com/city.mmdb",
                max_age_days=30,
            ),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)
        with patch(
            "bigbrotr.services.monitor.service.download_bounded_file",
            new_callable=AsyncMock,
        ) as mock_download:
            await monitor.update_geo_databases()
            mock_download.assert_awaited_once()

    async def test_download_failure_logged_and_suppressed(
        self, mock_brotr: Brotr, tmp_path: Path
    ) -> None:
        city_path = str(tmp_path / "missing_city.mmdb")
        config = _make_config(
            processing=ProcessingConfig(
                compute=MetadataFlags(nip66_geo=True, nip66_net=False),
                store=MetadataFlags(nip66_geo=True, nip66_net=False),
            ),
            geo=GeoConfig(
                city_database_path=city_path,
                city_download_url="https://example.com/city.mmdb",
            ),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)
        with patch(
            "bigbrotr.services.monitor.service.download_bounded_file",
            new_callable=AsyncMock,
            side_effect=OSError("download failed"),
        ):
            await monitor.update_geo_databases()


# ============================================================================
# Check Relay
# ============================================================================


class TestCheckRelay:
    @staticmethod
    def _flags(**kw: bool) -> MetadataFlags:
        base = {
            "nip11_info": False,
            "nip66_rtt": False,
            "nip66_ssl": False,
            "nip66_geo": False,
            "nip66_net": False,
            "nip66_dns": False,
            "nip66_http": False,
        }
        base.update(kw)
        return MetadataFlags(**base)

    def _cfg(self, **compute_kw: bool) -> MonitorConfig:
        flags = self._flags(**compute_kw)
        return _make_config(
            processing=ProcessingConfig(compute=flags, store=flags),
            discovery=DiscoveryConfig(include=flags),
            announcement=AnnouncementConfig(include=flags),
        )

    async def test_check_relay_unknown_network(self, mock_brotr: Brotr) -> None:
        config = _make_config()
        monitor = Monitor(brotr=mock_brotr, config=config)
        relay = Relay("wss://relay.example.com")
        monitor.network_semaphores = {}

        results = [r async for r in monitor._monitor_worker(relay)]

        assert len(results) == 1
        assert results[0] == (relay, None)

    async def test_check_relay_nip11_only(self, mock_brotr: Brotr) -> None:
        config = self._cfg(nip11_info=True)
        monitor = Monitor(brotr=mock_brotr, config=config)
        relay = Relay("wss://relay.example.com")
        nip11_meta = _make_nip11_meta(name="Test")

        with patch(
            "bigbrotr.services.monitor.service.retry_fetch",
            new_callable=AsyncMock,
            return_value=nip11_meta,
        ):
            result = await monitor.check_relay(relay)

        assert result.has_data
        assert result.nip11_info is nip11_meta
        assert result.nip66_rtt is None

    async def test_check_relay_nip11_and_rtt(self, mock_brotr: Brotr) -> None:
        config = self._cfg(nip11_info=True, nip66_rtt=True)
        monitor = Monitor(brotr=mock_brotr, config=config)
        relay = Relay("wss://relay.example.com")
        nip11_meta = _make_nip11_meta(name="Test")
        rtt_meta = _make_rtt_meta(rtt_open=50)

        with patch(
            "bigbrotr.services.monitor.service.retry_fetch",
            new_callable=AsyncMock,
            side_effect=[nip11_meta, rtt_meta],
        ):
            result = await monitor.check_relay(relay)

        assert result.has_data
        assert result.nip11_info is nip11_meta
        assert result.nip66_rtt is rtt_meta

    async def test_check_relay_with_parallel_checks(self, mock_brotr: Brotr) -> None:
        config = self._cfg(nip66_http=True)
        monitor = Monitor(brotr=mock_brotr, config=config)
        relay = Relay("wss://relay.example.com")

        from bigbrotr.nips.nip66 import Nip66HttpData, Nip66HttpLogs, Nip66HttpMetadata

        http_meta = Nip66HttpMetadata(data=Nip66HttpData(), logs=Nip66HttpLogs(success=True))

        async def fake_retry(*args: Any, **kwargs: Any) -> Nip66HttpMetadata:
            return http_meta

        with patch(
            "bigbrotr.services.monitor.service.retry_fetch",
            side_effect=fake_retry,
        ):
            result = await monitor.check_relay(relay)

        assert result.nip66_http is http_meta

    async def test_check_relay_all_fail_returns_empty(self, mock_brotr: Brotr) -> None:
        config = self._cfg(nip11_info=True)
        monitor = Monitor(brotr=mock_brotr, config=config)
        relay = Relay("wss://relay.example.com")

        with patch(
            "bigbrotr.services.monitor.service.retry_fetch",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await monitor.check_relay(relay)

        assert not result.has_data

    @pytest.mark.parametrize("exc_type", [TimeoutError, OSError])
    async def test_check_relay_network_error_returns_empty(
        self, exc_type: type[Exception], mock_brotr: Brotr
    ) -> None:
        config = self._cfg(nip11_info=True)
        monitor = Monitor(brotr=mock_brotr, config=config)
        relay = Relay("wss://relay.example.com")

        with patch(
            "bigbrotr.services.monitor.service.retry_fetch",
            new_callable=AsyncMock,
            side_effect=exc_type("error"),
        ):
            result = await monitor.check_relay(relay)

        assert not result.has_data
        assert result.generated_at == 0

    async def test_check_relay_rtt_skips_pow_when_nip11_absent(self, mock_brotr: Brotr) -> None:
        config = self._cfg(nip11_info=True, nip66_rtt=True)
        monitor = Monitor(brotr=mock_brotr, config=config)
        relay = Relay("wss://relay.example.com")
        rtt_meta = _make_rtt_meta(rtt_open=50)

        with patch(
            "bigbrotr.services.monitor.service.retry_fetch",
            new_callable=AsyncMock,
            side_effect=[None, rtt_meta],
        ):
            result = await monitor.check_relay(relay)

        assert result.nip11_info is None
        assert result.nip66_rtt is rtt_meta

    async def test_check_relay_nip11_closure_calls_fetch(self, mock_brotr: Brotr) -> None:
        config = self._cfg(nip11_info=True)
        monitor = Monitor(brotr=mock_brotr, config=config)
        relay = Relay("wss://relay.example.com")
        nip11_meta = _make_nip11_meta(name="Test")

        mock_nip11 = MagicMock()
        mock_nip11.info = nip11_meta

        async def call_through(relay, coro_factory, *args, **kwargs):
            return await coro_factory()

        with (
            patch("bigbrotr.services.monitor.service.retry_fetch", side_effect=call_through),
            patch(
                "bigbrotr.services.monitor.service.Nip11.fetch",
                new_callable=AsyncMock,
                return_value=mock_nip11,
            ) as mock_fetch,
        ):
            result = await monitor.check_relay(relay)

        mock_fetch.assert_awaited_once()
        assert result.nip11_info is nip11_meta

    async def test_check_relay_rtt_with_pow(self, mock_brotr: Brotr) -> None:
        config = self._cfg(nip11_info=True, nip66_rtt=True)
        monitor = Monitor(brotr=mock_brotr, config=config)
        relay = Relay("wss://relay.example.com")
        nip11_meta = _make_nip11_meta(
            name="Test",
            limitation=Nip11InfoDataLimitation(min_pow_difficulty=16),
        )
        rtt_meta = _make_rtt_meta(rtt_open=50)

        with patch(
            "bigbrotr.services.monitor.service.retry_fetch",
            new_callable=AsyncMock,
            side_effect=[nip11_meta, rtt_meta],
        ):
            result = await monitor.check_relay(relay)

        assert result.nip11_info is nip11_meta
        assert result.nip66_rtt is rtt_meta

    async def test_check_relay_cancelled_error_in_parallel_reraises(
        self, mock_brotr: Brotr
    ) -> None:
        config = self._cfg(nip66_http=True)
        monitor = Monitor(brotr=mock_brotr, config=config)
        relay = Relay("wss://relay.example.com")

        cancelled = asyncio.CancelledError()

        async def fake_retry(*args: Any, **kwargs: Any) -> None:
            raise cancelled

        with (
            patch("bigbrotr.services.monitor.service.retry_fetch", side_effect=fake_retry),
            pytest.raises(asyncio.CancelledError),
        ):
            await monitor.check_relay(relay)


# ============================================================================
# Build Parallel Checks
# ============================================================================


class TestBuildParallelChecks:
    @staticmethod
    def _flags(**kw: bool) -> MetadataFlags:
        base = {
            "nip11_info": False,
            "nip66_rtt": False,
            "nip66_ssl": False,
            "nip66_geo": False,
            "nip66_net": False,
            "nip66_dns": False,
            "nip66_http": False,
        }
        base.update(kw)
        return MetadataFlags(**base)

    def _cfg(self, **compute_kw: bool) -> MonitorConfig:
        flags = self._flags(**compute_kw)
        return _make_config(
            processing=ProcessingConfig(compute=flags, store=flags),
            discovery=DiscoveryConfig(include=flags),
            announcement=AnnouncementConfig(include=flags),
        )

    def test_no_checks_enabled(self, mock_brotr: Brotr) -> None:
        config = self._cfg()
        monitor = Monitor(brotr=mock_brotr, config=config)
        relay = Relay("wss://relay.example.com")

        tasks = monitor._build_parallel_checks(relay, config.processing.compute, 10.0, None)

        assert tasks == {}

    def test_http_check_for_any_network(self, mock_brotr: Brotr) -> None:
        config = self._cfg(nip66_http=True)
        monitor = Monitor(brotr=mock_brotr, config=config)
        onion = "a" * 56
        relay = Relay(f"ws://{onion}.onion")

        tasks = monitor._build_parallel_checks(
            relay, config.processing.compute, 10.0, "socks5://localhost:9050"
        )

        assert "http" in tasks
        assert "ssl" not in tasks
        assert "dns" not in tasks
        for coro in tasks.values():
            coro.close()

    def test_clearnet_only_checks_for_clearnet(self, mock_brotr: Brotr) -> None:
        config = self._cfg(nip66_ssl=True, nip66_dns=True)
        monitor = Monitor(brotr=mock_brotr, config=config)
        relay = Relay("wss://relay.example.com")

        tasks = monitor._build_parallel_checks(relay, config.processing.compute, 10.0, None)

        assert "ssl" in tasks
        assert "dns" in tasks
        for coro in tasks.values():
            coro.close()

    def test_clearnet_only_checks_skipped_for_tor(self, mock_brotr: Brotr) -> None:
        config = self._cfg(nip66_ssl=True, nip66_dns=True)
        monitor = Monitor(brotr=mock_brotr, config=config)
        onion = "a" * 56
        relay = Relay(f"ws://{onion}.onion")

        tasks = monitor._build_parallel_checks(
            relay, config.processing.compute, 10.0, "socks5://localhost:9050"
        )

        assert "ssl" not in tasks
        assert "dns" not in tasks

    def test_geo_check_requires_reader(self, mock_brotr: Brotr) -> None:
        config = self._cfg(nip66_geo=True)
        monitor = Monitor(brotr=mock_brotr, config=config)
        relay = Relay("wss://relay.example.com")

        tasks = monitor._build_parallel_checks(relay, config.processing.compute, 10.0, None)

        assert "geo" not in tasks

    def test_geo_check_included_with_reader(self, mock_brotr: Brotr) -> None:
        config = self._cfg(nip66_geo=True)
        monitor = Monitor(brotr=mock_brotr, config=config)
        monitor.geo_readers.city = MagicMock()
        relay = Relay("wss://relay.example.com")

        tasks = monitor._build_parallel_checks(relay, config.processing.compute, 10.0, None)

        assert "geo" in tasks
        for coro in tasks.values():
            coro.close()

    def test_net_check_requires_reader(self, mock_brotr: Brotr) -> None:
        config = self._cfg(nip66_net=True)
        monitor = Monitor(brotr=mock_brotr, config=config)
        relay = Relay("wss://relay.example.com")

        tasks = monitor._build_parallel_checks(relay, config.processing.compute, 10.0, None)

        assert "net" not in tasks

    def test_net_check_included_with_reader(self, mock_brotr: Brotr) -> None:
        config = self._cfg(nip66_net=True)
        monitor = Monitor(brotr=mock_brotr, config=config)
        monitor.geo_readers.asn = MagicMock()
        relay = Relay("wss://relay.example.com")

        tasks = monitor._build_parallel_checks(relay, config.processing.compute, 10.0, None)

        assert "net" in tasks
        for coro in tasks.values():
            coro.close()


# ============================================================================
# Monitor with max_relays budget
# ============================================================================


class TestMonitorMaxRelaysBudget:
    async def test_monitor_stops_at_max_relays(self, mock_brotr: Brotr) -> None:
        config = _make_config(
            processing=ProcessingConfig(
                compute=_NO_GEO_NET,
                store=_NO_GEO_NET,
                max_relays=2,
                chunk_size=10,
            ),
            discovery=DiscoveryConfig(enabled=False, include=_NO_GEO_NET),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)
        relay1 = Relay("wss://r1.example.com")
        relay2 = Relay("wss://r2.example.com")
        relay3 = Relay("wss://r3.example.com")
        result = _make_check_result(nip66_rtt=_make_rtt_meta(rtt_open=50))

        async def fake_worker(relay: Relay):
            yield (relay, result)

        monitor.clients = MagicMock()
        monitor.clients.disconnect = AsyncMock()

        with (
            patch(
                "bigbrotr.services.monitor.service.count_relays_to_monitor",
                new_callable=AsyncMock,
                return_value=3,
            ),
            patch(
                "bigbrotr.services.monitor.service.iter_relays_to_monitor_pages",
                return_value=_mock_pages([relay1, relay2, relay3]),
            ),
            patch.object(monitor, "_monitor_worker", side_effect=fake_worker),
            patch(
                "bigbrotr.services.monitor.service.insert_relay_metadata",
                new_callable=AsyncMock,
            ),
            patch(
                "bigbrotr.services.monitor.service.upsert_monitor_checkpoints",
                new_callable=AsyncMock,
            ),
        ):
            total = await monitor.monitor()

        assert total <= 3

    async def test_monitor_max_relays_truncates_list(self, mock_brotr: Brotr) -> None:
        config = _make_config(
            processing=ProcessingConfig(
                compute=_NO_GEO_NET,
                store=_NO_GEO_NET,
                max_relays=1,
                chunk_size=100,
            ),
            discovery=DiscoveryConfig(enabled=False, include=_NO_GEO_NET),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)
        relay1 = Relay("wss://r1.example.com")
        result = _make_check_result(nip66_rtt=_make_rtt_meta(rtt_open=50))

        async def fake_worker(relay: Relay):
            yield (relay, result)

        monitor.clients = MagicMock()
        monitor.clients.disconnect = AsyncMock()

        with (
            patch(
                "bigbrotr.services.monitor.service.count_relays_to_monitor",
                new_callable=AsyncMock,
                return_value=2,
            ),
            patch(
                "bigbrotr.services.monitor.service.iter_relays_to_monitor_pages",
                return_value=_mock_pages([relay1]),
            ),
            patch.object(monitor, "_monitor_worker", side_effect=fake_worker),
            patch(
                "bigbrotr.services.monitor.service.insert_relay_metadata",
                new_callable=AsyncMock,
            ),
            patch(
                "bigbrotr.services.monitor.service.upsert_monitor_checkpoints",
                new_callable=AsyncMock,
            ),
        ):
            total = await monitor.monitor()

        assert total == 1

    async def test_monitor_stops_on_shutdown(self, mock_brotr: Brotr) -> None:
        config = _make_config(
            processing=ProcessingConfig(
                compute=_NO_GEO_NET,
                store=_NO_GEO_NET,
                chunk_size=10,
            ),
            discovery=DiscoveryConfig(enabled=False, include=_NO_GEO_NET),
        )
        monitor = Monitor(brotr=mock_brotr, config=config)
        relay1 = Relay("wss://r1.example.com")
        relay2 = Relay("wss://r2.example.com")

        monitor.clients = MagicMock()
        monitor.clients.disconnect = AsyncMock()
        monitor.request_shutdown()

        with (
            patch(
                "bigbrotr.services.monitor.service.count_relays_to_monitor",
                new_callable=AsyncMock,
                return_value=2,
            ),
            patch(
                "bigbrotr.services.monitor.service.iter_relays_to_monitor_pages",
                return_value=_mock_pages([relay1, relay2]),
            ),
        ):
            total = await monitor.monitor()

        assert total == 0


# ============================================================================
# Retry Fetch
# ============================================================================


class TestRetryFetch:
    async def test_success_on_first_attempt(self) -> None:
        relay = Relay("wss://relay.example.com")
        meta = _make_nip11_meta(name="Test")
        retry = RetryConfig(max_attempts=2, initial_delay=0.1, max_delay=1.0, jitter=0.0)

        result = await retry_fetch(relay, AsyncMock(return_value=meta), retry, "nip11_info")

        assert result is meta

    async def test_retry_on_failure_then_succeed(self) -> None:
        relay = Relay("wss://relay.example.com")
        failed_meta = _make_nip11_meta(name="Test", success=False)
        success_meta = _make_nip11_meta(name="Test", success=True)
        retry = RetryConfig(max_attempts=2, initial_delay=0.1, max_delay=1.0, jitter=0.0)

        call_count = 0

        async def factory() -> Nip11InfoMetadata:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return failed_meta
            return success_meta

        result = await retry_fetch(relay, factory, retry, "nip11_info")

        assert result is success_meta
        assert call_count == 2

    async def test_retry_on_timeout_then_succeed(self) -> None:
        relay = Relay("wss://relay.example.com")
        success_meta = _make_nip11_meta(name="Test")
        retry = RetryConfig(max_attempts=2, initial_delay=0.1, max_delay=1.0, jitter=0.0)

        call_count = 0

        async def factory() -> Nip11InfoMetadata:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TimeoutError("timed out")
            return success_meta

        result = await retry_fetch(relay, factory, retry, "nip11_info")

        assert result is success_meta
        assert call_count == 2

    async def test_retry_on_os_error_then_succeed(self) -> None:
        relay = Relay("wss://relay.example.com")
        success_meta = _make_nip11_meta(name="Test")
        retry = RetryConfig(max_attempts=1, initial_delay=0.1, max_delay=1.0, jitter=0.0)

        call_count = 0

        async def factory() -> Nip11InfoMetadata:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError("connection refused")
            return success_meta

        result = await retry_fetch(relay, factory, retry, "nip11_info")

        assert result is success_meta

    async def test_all_retries_exhausted_returns_last_result(self) -> None:
        relay = Relay("wss://relay.example.com")
        failed_meta = _make_nip11_meta(name="Test", success=False)
        retry = RetryConfig(max_attempts=1, initial_delay=0.1, max_delay=1.0, jitter=0.0)

        result = await retry_fetch(relay, AsyncMock(return_value=failed_meta), retry, "nip11_info")

        assert result is failed_meta

    async def test_all_retries_exhausted_with_exceptions(self) -> None:
        relay = Relay("wss://relay.example.com")
        retry = RetryConfig(max_attempts=1, initial_delay=0.1, max_delay=1.0, jitter=0.0)

        result = await retry_fetch(
            relay,
            AsyncMock(side_effect=TimeoutError("timed out")),
            retry,
            "nip11_info",
        )

        assert result is None

    async def test_no_retries(self) -> None:
        relay = Relay("wss://relay.example.com")
        failed_meta = _make_nip11_meta(name="Test", success=False)
        retry = RetryConfig(max_attempts=0)

        result = await retry_fetch(relay, AsyncMock(return_value=failed_meta), retry, "nip11_info")

        assert result is failed_meta

    async def test_wait_callback_called(self) -> None:
        relay = Relay("wss://relay.example.com")
        failed_meta = _make_nip11_meta(name="Test", success=False)
        success_meta = _make_nip11_meta(name="Test", success=True)
        retry = RetryConfig(max_attempts=1, initial_delay=0.1, max_delay=1.0, jitter=0.0)

        call_count = 0

        async def factory() -> Nip11InfoMetadata:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return failed_meta
            return success_meta

        async def wait_fn(delay: float) -> bool:
            return False

        result = await retry_fetch(relay, factory, retry, "nip11_info", wait=wait_fn)

        assert result is success_meta

    async def test_wait_callback_signals_shutdown(self) -> None:
        relay = Relay("wss://relay.example.com")
        failed_meta = _make_nip11_meta(name="Test", success=False)
        retry = RetryConfig(max_attempts=2, initial_delay=0.1, max_delay=1.0, jitter=0.0)

        async def wait_fn(delay: float) -> bool:
            return True

        result = await retry_fetch(
            relay, AsyncMock(return_value=failed_meta), retry, "nip11_info", wait=wait_fn
        )

        assert result is None

    async def test_delay_capped_by_max_delay(self) -> None:
        relay = Relay("wss://relay.example.com")
        failed_meta = _make_nip11_meta(name="Test", success=False)
        retry = RetryConfig(max_attempts=3, initial_delay=5.0, max_delay=5.0, jitter=0.0)

        delays: list[float] = []

        async def wait_fn(delay: float) -> bool:
            delays.append(delay)
            return False

        await retry_fetch(
            relay, AsyncMock(return_value=failed_meta), retry, "nip11_info", wait=wait_fn
        )

        for d in delays:
            assert d <= 5.0 + retry.jitter


# ============================================================================
# Collect Metadata
# ============================================================================


class TestCollectMetadata:
    def test_empty_input(self) -> None:
        store = MetadataFlags()
        result = collect_metadata([], store)

        assert result == []

    def test_collects_enabled_types(self) -> None:
        relay = Relay("wss://relay.example.com")
        nip11_meta = _make_nip11_meta(name="Test")
        check_result = _make_check_result(generated_at=1700000000, nip11_info=nip11_meta)
        store = MetadataFlags(
            nip11_info=True,
            nip66_rtt=True,
            nip66_ssl=True,
            nip66_geo=True,
            nip66_net=True,
            nip66_dns=True,
            nip66_http=True,
        )

        result = collect_metadata([(relay, check_result)], store)

        assert len(result) == 1
        assert result[0].relay is relay
        assert result[0].generated_at == 1700000000

    def test_skips_disabled_types(self) -> None:
        relay = Relay("wss://relay.example.com")
        nip11_meta = _make_nip11_meta(name="Test")
        check_result = _make_check_result(generated_at=1700000000, nip11_info=nip11_meta)
        store = MetadataFlags(nip11_info=False)

        result = collect_metadata([(relay, check_result)], store)

        assert len(result) == 0

    def test_skips_none_metadata(self) -> None:
        relay = Relay("wss://relay.example.com")
        check_result = _make_check_result(generated_at=1700000000)
        store = MetadataFlags()

        result = collect_metadata([(relay, check_result)], store)

        assert len(result) == 0

    def test_multiple_relays_and_types(self) -> None:
        relay1 = Relay("wss://r1.example.com")
        relay2 = Relay("wss://r2.example.com")
        nip11 = _make_nip11_meta(name="Test")
        rtt = _make_rtt_meta(rtt_open=50)
        result1 = _make_check_result(generated_at=100, nip11_info=nip11, nip66_rtt=rtt)
        result2 = _make_check_result(generated_at=200, nip11_info=nip11)
        store = MetadataFlags()

        result = collect_metadata([(relay1, result1), (relay2, result2)], store)

        assert len(result) == 3
