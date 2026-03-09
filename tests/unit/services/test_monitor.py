"""Unit tests for the monitor service package."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nostr_sdk import Keys

from bigbrotr.core.brotr import Brotr
from bigbrotr.models import Relay, RelayMetadata
from bigbrotr.models.constants import NetworkType, ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType
from bigbrotr.nips.base import BaseLogs
from bigbrotr.nips.event_builders import (
    build_monitor_announcement,
    build_profile_event,
    build_relay_discovery,
)
from bigbrotr.nips.nip11 import Nip11, Nip11Selection
from bigbrotr.nips.nip11.data import Nip11InfoData, Nip11InfoDataLimitation
from bigbrotr.nips.nip11.info import Nip11InfoMetadata
from bigbrotr.nips.nip11.logs import Nip11InfoLogs
from bigbrotr.nips.nip66 import Nip66, Nip66RttMetadata, Nip66Selection, Nip66SslMetadata
from bigbrotr.nips.nip66.data import Nip66RttData, Nip66SslData
from bigbrotr.nips.nip66.logs import Nip66RttMultiPhaseLogs, Nip66SslLogs
from bigbrotr.services.common.configs import ClearnetConfig, NetworksConfig, TorConfig
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
)
from bigbrotr.services.monitor.configs import RetriesConfig, RetryConfig
from bigbrotr.services.monitor.queries import (
    count_relays_to_monitor,
    delete_stale_checkpoints,
    fetch_relays_to_monitor,
    insert_relay_metadata,
    is_publish_due,
    upsert_monitor_checkpoints,
    upsert_publish_checkpoints,
)
from bigbrotr.services.monitor.utils import (
    collect_metadata,
    extract_result,
    log_reason,
    log_success,
    retry_fetch,
)


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
    monkeypatch.setenv("NOSTR_PRIVATE_KEY", VALID_HEX_KEY)


_NO_GEO_NET = MetadataFlags(nip66_geo=False, nip66_net=False)


def _make_config(**overrides: Any) -> MonitorConfig:
    defaults: dict[str, Any] = {
        "processing": ProcessingConfig(compute=_NO_GEO_NET, store=_NO_GEO_NET),
        "discovery": DiscoveryConfig(include=_NO_GEO_NET),
        "announcement": AnnouncementConfig(include=_NO_GEO_NET),
    }
    defaults.update(overrides)
    return MonitorConfig(**defaults)


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
        self.clients = MagicMock()
        self.clients.get = AsyncMock(return_value=AsyncMock())
        self.clients.get_many = AsyncMock(return_value=[AsyncMock()])
        self.clients.disconnect = AsyncMock()

    # Publishing methods bound from Monitor
    publish_announcement = Monitor.publish_announcement
    publish_profile = Monitor.publish_profile


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


def _create_nip11(relay: Relay, data: dict | None = None, generated_at: int = 1700000001) -> Nip11:
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


def _make_ssl_meta(
    *,
    ssl_valid: bool | None = None,
    ssl_expires: int | None = None,
    ssl_issuer: str | None = None,
    success: bool = True,
) -> Nip66SslMetadata:
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
    nip11_info: Nip11InfoMetadata | None = None,
    nip66_rtt: Nip66RttMetadata | None = None,
    nip66_ssl: Nip66SslMetadata | None = None,
) -> CheckResult:
    return CheckResult(
        generated_at=generated_at,
        nip11_info=nip11_info,
        nip66_rtt=nip66_rtt,
        nip66_ssl=nip66_ssl,
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

        assert config.relays == []

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
        assert config.interval == 3600
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

        assert config.enabled is False
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


class TestCountRelaysToMonitor:
    async def test_calls_fetchval_with_correct_params(self, query_brotr: MagicMock) -> None:
        query_brotr.fetchval = AsyncMock(return_value=42)

        result = await count_relays_to_monitor(
            query_brotr,
            monitored_before=1700000000,
            networks=[NetworkType.CLEARNET],
        )

        query_brotr.fetchval.assert_awaited_once()
        args = query_brotr.fetchval.call_args
        sql = args[0][0]
        assert "count(*)::int" in sql
        assert "FROM relay r" in sql
        assert "LEFT JOIN service_state ss" in sql
        assert args[0][1] == [NetworkType.CLEARNET]
        assert args[0][2] == 1700000000
        assert args[0][3] == ServiceName.MONITOR
        assert args[0][4] == ServiceStateType.CHECKPOINT
        assert result == 42


class TestFetchRelaysToMonitor:
    async def test_calls_fetch_with_correct_params(self, query_brotr: MagicMock) -> None:
        await fetch_relays_to_monitor(
            query_brotr,
            monitored_before=1700000000,
            networks=[NetworkType.CLEARNET],
            limit=100,
        )

        query_brotr.fetch.assert_awaited_once()
        args = query_brotr.fetch.call_args
        sql = args[0][0]
        assert "FROM relay r" in sql
        assert "LEFT JOIN service_state ss" in sql
        assert "service_name = $3" in sql
        assert "state_type = $4" in sql
        assert "LIMIT $5" in sql
        assert args[0][1] == [NetworkType.CLEARNET]
        assert args[0][2] == 1700000000
        assert args[0][3] == ServiceName.MONITOR
        assert args[0][4] == ServiceStateType.CHECKPOINT
        assert args[0][5] == 100

    async def test_returns_relay_objects(self, query_brotr: MagicMock) -> None:
        row = _make_dict_row(
            {"url": "wss://relay.example.com", "network": "clearnet", "discovered_at": 1700000000}
        )
        query_brotr.fetch = AsyncMock(return_value=[row])

        result = await fetch_relays_to_monitor(query_brotr, 1700000000, [NetworkType.CLEARNET], 100)

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

        result = await fetch_relays_to_monitor(query_brotr, 1700000000, [NetworkType.CLEARNET], 100)

        assert len(result) == 1
        assert result[0].url == "wss://valid.relay.com"

    async def test_empty_result(self, query_brotr: MagicMock) -> None:
        result = await fetch_relays_to_monitor(query_brotr, 1700000000, [NetworkType.CLEARNET], 100)

        assert result == []


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
        query_brotr.get_service_state = AsyncMock(return_value=[])
        assert await is_publish_due(query_brotr, "announcement", 86400) is True

    async def test_interval_not_elapsed_returns_false(self, query_brotr: MagicMock) -> None:
        now = int(time.time())
        query_brotr.get_service_state = AsyncMock(
            return_value=[
                ServiceState(
                    service_name=ServiceName.MONITOR,
                    state_type=ServiceStateType.CHECKPOINT,
                    state_key="announcement",
                    state_value={"timestamp": now},
                )
            ]
        )
        assert await is_publish_due(query_brotr, "announcement", 86400) is False

    async def test_interval_elapsed_returns_true(self, query_brotr: MagicMock) -> None:
        old = int(time.time()) - 100_000
        query_brotr.get_service_state = AsyncMock(
            return_value=[
                ServiceState(
                    service_name=ServiceName.MONITOR,
                    state_type=ServiceStateType.CHECKPOINT,
                    state_key="profile",
                    state_value={"timestamp": old},
                )
            ]
        )
        assert await is_publish_due(query_brotr, "profile", 86400) is True

    async def test_missing_timestamp_key_returns_true(self, query_brotr: MagicMock) -> None:
        query_brotr.get_service_state = AsyncMock(
            return_value=[
                ServiceState(
                    service_name=ServiceName.MONITOR,
                    state_type=ServiceStateType.CHECKPOINT,
                    state_key="announcement",
                    state_value={},
                )
            ]
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
        query_brotr.upsert_service_state = AsyncMock()

        await upsert_publish_checkpoints(query_brotr, [])

        query_brotr.upsert_service_state.assert_not_awaited()

    async def test_invalid_key_raises(self, query_brotr: MagicMock) -> None:
        with pytest.raises(ValueError, match="invalid publish keys"):
            await upsert_publish_checkpoints(query_brotr, ["bogus"])


# ============================================================================
# Service -- Nip11 dataclass
# ============================================================================


class TestNip11:
    def test_default_values(self) -> None:
        relay = Relay("wss://relay.example.com")
        nip11 = _create_nip11(relay, {})

        assert nip11.info.data.name is None
        assert nip11.info.data.supported_nips is None

    def test_properties(self) -> None:
        relay = Relay("wss://relay.example.com")
        nip11 = _create_nip11(relay, {"name": "Test Relay", "supported_nips": [1, 11, 66]})

        assert nip11.info.data.name == "Test Relay"
        assert nip11.info.data.supported_nips == [1, 11, 66]

    def test_to_relay_metadata(self) -> None:
        relay = Relay("wss://relay.example.com")
        nip11 = _create_nip11(relay, {"name": "Test"})

        metadata_tuple = nip11.to_relay_metadata_tuple()

        assert metadata_tuple.nip11_info is not None
        assert metadata_tuple.nip11_info.metadata.type == "nip11_info"
        assert metadata_tuple.nip11_info.relay == relay
        assert metadata_tuple.nip11_info.metadata.data["data"]["name"] == "Test"

    def test_additional_properties(self) -> None:
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
# Service -- Nip66 dataclass
# ============================================================================


class TestNip66:
    def test_default_values(self) -> None:
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(relay)

        assert nip66.rtt is None
        assert nip66.ssl is None
        assert nip66.geo is None

    def test_metadata_access(self) -> None:
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(relay, rtt_data={"rtt_open": 100, "rtt_read": 50})

        assert nip66.rtt is not None
        assert nip66.rtt.data.rtt_open == 100
        assert nip66.rtt.data.rtt_read == 50
        assert nip66.rtt.data.rtt_write is None

    def test_to_relay_metadata_rtt_only(self) -> None:
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
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(relay, rtt_data={"rtt_open": 100})

        assert nip66.ssl is None

    def test_rtt_logs_access(self) -> None:
        relay = Relay("wss://relay.example.com")
        nip66 = _create_nip66(
            relay,
            rtt_data={"rtt_open": 100},
        )

        assert nip66.rtt is not None
        assert nip66.rtt.logs.open_success is True


# ============================================================================
# Service: RelayMetadata type
# ============================================================================


class TestRelayMetadataType:
    def test_creation(self) -> None:
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


# ============================================================================
# Service: Monitor run
# ============================================================================


class TestMonitorRun:
    @patch(
        "bigbrotr.services.monitor.service.is_publish_due",
        new_callable=AsyncMock,
        return_value=False,
    )
    @patch(
        "bigbrotr.services.monitor.service.fetch_relays_to_monitor",
        new_callable=AsyncMock,
        return_value=[],
    )
    @patch(
        "bigbrotr.services.monitor.service.count_relays_to_monitor",
        new_callable=AsyncMock,
        return_value=0,
    )
    async def test_run_no_relays(
        self,
        mock_count: AsyncMock,
        mock_fetch: AsyncMock,
        mock_checkpoint: AsyncMock,
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
        mock_fetch.assert_awaited_once()

    async def test_monitor_no_networks_returns_zero(self, mock_brotr: Brotr) -> None:
        no_clearnet_checks = MetadataFlags(
            nip66_ssl=False, nip66_dns=False, nip66_geo=False, nip66_net=False
        )
        config = _make_config(
            networks=NetworksConfig(clearnet=ClearnetConfig(enabled=False)),
            processing=ProcessingConfig(compute=no_clearnet_checks, store=no_clearnet_checks),
            discovery=DiscoveryConfig(include=no_clearnet_checks),
            announcement=AnnouncementConfig(include=no_clearnet_checks),
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

        mock_delete.assert_awaited_once_with(mock_brotr, ["announcement", "profile"])
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

        mock_delete.assert_awaited_once_with(mock_brotr, ["profile"])
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

        mock_delete.assert_awaited_once_with(mock_brotr, ["announcement"])
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

        mock_delete.assert_awaited_once_with(mock_brotr, [])
        assert result == 5


# ============================================================================
# Service: Monitor persist results
# ============================================================================


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
            r, res = await monitor._monitoring_worker(relay)

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
            r, res = await monitor._monitoring_worker(relay)

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
            r, res = await monitor._monitoring_worker(relay)

        assert r is relay
        assert res is None

    async def test_cancelled_error_propagates(self, mock_brotr: Brotr) -> None:
        config = _make_config()
        monitor = Monitor(brotr=mock_brotr, config=config)
        relay = Relay("wss://relay.example.com")

        with (
            patch.object(
                Monitor,
                "check_relay",
                new_callable=AsyncMock,
                side_effect=asyncio.CancelledError,
            ),
            pytest.raises(asyncio.CancelledError),
        ):
            await monitor._monitoring_worker(relay)

    async def test_keyboard_interrupt_propagates(self, mock_brotr: Brotr) -> None:
        config = _make_config()
        monitor = Monitor(brotr=mock_brotr, config=config)
        relay = Relay("wss://relay.example.com")

        with (
            patch.object(
                Monitor,
                "check_relay",
                new_callable=AsyncMock,
                side_effect=KeyboardInterrupt,
            ),
            pytest.raises(KeyboardInterrupt),
        ):
            await monitor._monitoring_worker(relay)

    async def test_system_exit_propagates(self, mock_brotr: Brotr) -> None:
        config = _make_config()
        monitor = Monitor(brotr=mock_brotr, config=config)
        relay = Relay("wss://relay.example.com")

        with (
            patch.object(
                Monitor,
                "check_relay",
                new_callable=AsyncMock,
                side_effect=SystemExit(1),
            ),
            pytest.raises(SystemExit),
        ):
            await monitor._monitoring_worker(relay)


# ============================================================================
# Service: Network configuration
# ============================================================================


class TestMonitorNetworkConfiguration:
    def test_enabled_networks_default(self, mock_brotr: Brotr) -> None:
        config = _make_config()
        monitor = Monitor(brotr=mock_brotr, config=config)
        enabled = monitor._config.networks.get_enabled_networks()
        assert "clearnet" in enabled

    def test_enabled_networks_with_tor(self, mock_brotr: Brotr) -> None:
        config = _make_config(
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
# Service: Publish relays
# ============================================================================


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
                "bigbrotr.services.monitor.service.broadcast_events",
                new_callable=AsyncMock,
                return_value=1,
            ) as mock_broadcast,
            patch(
                "bigbrotr.services.monitor.service.upsert_publish_checkpoints",
                new_callable=AsyncMock,
            ) as mock_save,
        ):
            await stub.publish_announcement()

        mock_broadcast.assert_awaited_once()
        mock_save.assert_awaited_once()
        stub._logger.info.assert_called_with("publish_completed", event="announcement", relays=1)

    async def test_publish_announcement_interval_elapsed(self, stub: _MonitorStub) -> None:
        with (
            patch(
                "bigbrotr.services.monitor.service.is_publish_due",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "bigbrotr.services.monitor.service.broadcast_events",
                new_callable=AsyncMock,
                return_value=1,
            ) as mock_broadcast,
            patch(
                "bigbrotr.services.monitor.service.upsert_publish_checkpoints",
                new_callable=AsyncMock,
            ) as mock_save,
        ):
            await stub.publish_announcement()

        mock_broadcast.assert_awaited_once()
        mock_save.assert_awaited_once()

    async def test_publish_announcement_broadcast_failure(self, stub: _MonitorStub) -> None:
        with (
            patch(
                "bigbrotr.services.monitor.service.is_publish_due",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "bigbrotr.services.monitor.service.broadcast_events",
                new_callable=AsyncMock,
                return_value=0,
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
            "publish_failed", event="announcement", error="no relays reachable"
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
                "bigbrotr.services.monitor.service.broadcast_events",
                new_callable=AsyncMock,
                return_value=1,
            ) as mock_broadcast,
            patch(
                "bigbrotr.services.monitor.service.upsert_publish_checkpoints",
                new_callable=AsyncMock,
            ) as mock_save,
        ):
            await stub.publish_profile()

        mock_broadcast.assert_awaited_once()
        mock_save.assert_awaited_once()
        stub._logger.info.assert_called_with("publish_completed", event="profile", relays=1)

    async def test_publish_profile_broadcast_failure(self, stub: _MonitorStub) -> None:
        with (
            patch(
                "bigbrotr.services.monitor.service.is_publish_due",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "bigbrotr.services.monitor.service.broadcast_events",
                new_callable=AsyncMock,
                return_value=0,
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
            "publish_failed", event="profile", error="no relays reachable"
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
            "bigbrotr.services.monitor.service.broadcast_events",
            new_callable=AsyncMock,
        ) as mock_broadcast:
            await monitor.publish_discovery(relay, result)
            mock_broadcast.assert_not_awaited()

    async def test_publish_discovery_no_relays(self, mock_brotr: Brotr) -> None:
        config = _make_config()
        monitor = Monitor(brotr=mock_brotr, config=config)
        relay = Relay("wss://relay.example.com")
        result = _make_check_result(nip11_info=_make_nip11_meta(name="Test"))

        with patch(
            "bigbrotr.services.monitor.service.broadcast_events",
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
            "bigbrotr.services.monitor.service.broadcast_events",
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
            "bigbrotr.services.monitor.service.broadcast_events",
            new_callable=AsyncMock,
            return_value=1,
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
                "bigbrotr.services.monitor.service.broadcast_events",
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
        monitor.clients = MagicMock()
        monitor.clients.get_many = AsyncMock(return_value=[AsyncMock()])
        relay = Relay("wss://relay.example.com")
        result = _make_check_result(nip11_info=_make_nip11_meta(name="Test"))

        with patch(
            "bigbrotr.services.monitor.service.broadcast_events",
            new_callable=AsyncMock,
            return_value=0,
        ):
            await monitor.publish_discovery(relay, result)


# ============================================================================
# Service: Build kind 0
# ============================================================================


class TestBuildProfileEvent:
    def test_all_fields(self) -> None:
        builder = build_profile_event(
            name="BigBrotr Monitor",
            about="A relay monitor",
            picture="https://example.com/pic.png",
            nip05="monitor@example.com",
            website="https://example.com",
            banner="https://example.com/banner.png",
            lud16="monitor@ln.example.com",
        )
        assert builder is not None

    def test_minimal_fields(self) -> None:
        builder = build_profile_event(name="MinimalMonitor")
        assert builder is not None

    def test_no_fields(self) -> None:
        builder = build_profile_event()
        assert builder is not None


# ============================================================================
# Service: Build kind 10166
# ============================================================================


class TestBuildMonitorAnnouncement:
    def test_all_flags_enabled(self) -> None:
        flags = MetadataFlags()
        builder = build_monitor_announcement(
            interval=3600,
            timeout_ms=5000,
            enabled_networks=[NetworkType.CLEARNET],
            nip11_selection=Nip11Selection(info=flags.nip11_info),
            nip66_selection=Nip66Selection(
                rtt=flags.nip66_rtt,
                ssl=flags.nip66_ssl,
                geo=flags.nip66_geo,
                net=flags.nip66_net,
                dns=flags.nip66_dns,
                http=flags.nip66_http,
            ),
        )
        assert builder is not None

    def test_subset_flags(self) -> None:
        builder = build_monitor_announcement(
            interval=1800,
            timeout_ms=5000,
            enabled_networks=[NetworkType.CLEARNET],
            nip11_selection=Nip11Selection(info=True),
            nip66_selection=Nip66Selection(
                rtt=True, ssl=False, geo=False, net=False, dns=False, http=False
            ),
        )
        assert builder is not None

    def test_no_flags(self) -> None:
        builder = build_monitor_announcement(
            interval=600,
            timeout_ms=10000,
            enabled_networks=[NetworkType.CLEARNET],
            nip11_selection=Nip11Selection(info=False),
            nip66_selection=Nip66Selection(
                rtt=False, ssl=False, geo=False, net=False, dns=False, http=False
            ),
        )
        assert builder is not None


# ============================================================================
# Service: Build kind 30166
# ============================================================================


class TestBuildRelayDiscovery:
    def test_full_event(self) -> None:
        relay = Relay("wss://relay.example.com")
        result = _make_check_result(
            nip11_info=_make_nip11_meta(
                name="Test Relay",
                supported_nips=[1, 11, 50],
                tags=["social"],
                language_tags=["en"],
            ),
            nip66_rtt=_make_rtt_meta(rtt_open=45, rtt_read=120, rtt_write=85),
            nip66_ssl=_make_ssl_meta(ssl_valid=True, ssl_expires=1735689600),
        )
        builder = build_relay_discovery(
            relay.url,
            relay.network.value,
            "",
            rtt_data=result.nip66_rtt.data if result.nip66_rtt else None,
            ssl_data=result.nip66_ssl.data if result.nip66_ssl else None,
            nip11_data=result.nip11_info.data if result.nip11_info else None,
            rtt_logs=result.nip66_rtt.logs if result.nip66_rtt else None,
        )
        assert builder is not None

    def test_minimal(self) -> None:
        relay = Relay("wss://relay.example.com")
        builder = build_relay_discovery(relay.url, relay.network.value, "")
        assert builder is not None

    def test_tor_relay_network(self) -> None:
        onion = "a" * 56
        relay = Relay(f"ws://{onion}.onion")
        builder = build_relay_discovery(relay.url, relay.network.value, "")
        assert builder is not None


# ============================================================================
# Service: End-to-end tag generation
# ============================================================================


class TestEndToEndTagGeneration:
    def test_full_relay_with_all_metadata(self) -> None:
        result = _make_check_result(
            nip11_info=_make_nip11_meta(
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
        builder = build_relay_discovery(
            relay.url,
            relay.network.value,
            "",
            rtt_data=result.nip66_rtt.data if result.nip66_rtt else None,
            ssl_data=result.nip66_ssl.data if result.nip66_ssl else None,
            nip11_data=result.nip11_info.data if result.nip11_info else None,
            rtt_logs=result.nip66_rtt.logs if result.nip66_rtt else None,
        )
        assert builder is not None


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

        async def fake_monitoring_worker(relay: Relay) -> tuple[Relay, CheckResult | None]:
            if relay.url == relay1.url:
                return (relay, result)
            return (relay, None)

        monitor.clients = MagicMock()
        monitor.clients.get = AsyncMock(return_value=None)
        monitor.clients.get_many = AsyncMock(return_value=[])
        monitor.clients.disconnect = AsyncMock()

        gauge_calls: list[tuple[str, int]] = []
        with (
            patch(
                "bigbrotr.services.monitor.service.count_relays_to_monitor",
                new_callable=AsyncMock,
                return_value=2,
            ),
            patch(
                "bigbrotr.services.monitor.service.fetch_relays_to_monitor",
                new_callable=AsyncMock,
                side_effect=[[relay1, relay2], []],
            ),
            patch.object(monitor, "_monitoring_worker", side_effect=fake_monitoring_worker),
            patch(
                "bigbrotr.services.monitor.service.insert_relay_metadata",
                new_callable=AsyncMock,
            ),
            patch(
                "bigbrotr.services.monitor.service.upsert_monitor_checkpoints",
                new_callable=AsyncMock,
            ),
            patch.object(
                monitor,
                "set_gauge",
                side_effect=lambda n, val: gauge_calls.append((n, val)),
            ),
        ):
            await monitor.monitor()

        calls = {(n, v) for n, v in gauge_calls}
        assert ("total", 2) in calls
        assert ("succeeded", 1) in calls
        assert ("failed", 1) in calls


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
# Publish -- no clients reachable
# ============================================================================


class TestPublishAnnouncementNoClients:
    async def test_announcement_no_clients_reachable(self, test_keys: Keys) -> None:
        config = _make_config(
            announcement=AnnouncementConfig(
                enabled=True,
                include=_NO_GEO_NET,
                relays=["wss://ann.relay.com"],
            ),
        )
        harness = _MonitorStub(config, test_keys)
        harness.clients.get_many = AsyncMock(return_value=[])
        with (
            patch(
                "bigbrotr.services.monitor.service.is_publish_due",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "bigbrotr.services.monitor.service.broadcast_events",
                new_callable=AsyncMock,
            ) as mock_broadcast,
            patch(
                "bigbrotr.services.monitor.service.upsert_publish_checkpoints",
                new_callable=AsyncMock,
            ) as mock_save,
        ):
            await harness.publish_announcement()

        mock_broadcast.assert_not_awaited()
        mock_save.assert_not_awaited()
        harness._logger.warning.assert_called_once_with(
            "publish_failed", event="announcement", error="no relays reachable"
        )


class TestPublishProfileNoClients:
    async def test_profile_no_clients_reachable(self, test_keys: Keys) -> None:
        config = _make_config(
            profile=ProfileConfig(
                enabled=True,
                relays=["wss://profile.relay.com"],
            ),
        )
        harness = _MonitorStub(config, test_keys)
        harness.clients.get_many = AsyncMock(return_value=[])
        with (
            patch(
                "bigbrotr.services.monitor.service.is_publish_due",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "bigbrotr.services.monitor.service.broadcast_events",
                new_callable=AsyncMock,
            ) as mock_broadcast,
            patch(
                "bigbrotr.services.monitor.service.upsert_publish_checkpoints",
                new_callable=AsyncMock,
            ) as mock_save,
        ):
            await harness.publish_profile()

        mock_broadcast.assert_not_awaited()
        mock_save.assert_not_awaited()
        harness._logger.warning.assert_called_once_with(
            "publish_failed", event="profile", error="no relays reachable"
        )


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
        monitor.network_semaphores = MagicMock()
        monitor.network_semaphores.get = MagicMock(return_value=None)

        result = await monitor.check_relay(relay)

        assert not result.has_data
        assert result.generated_at == 0

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

    async def test_check_relay_timeout_returns_empty(self, mock_brotr: Brotr) -> None:
        config = self._cfg(nip11_info=True)
        monitor = Monitor(brotr=mock_brotr, config=config)
        relay = Relay("wss://relay.example.com")

        with patch(
            "bigbrotr.services.monitor.service.retry_fetch",
            new_callable=AsyncMock,
            side_effect=TimeoutError("timed out"),
        ):
            result = await monitor.check_relay(relay)

        assert not result.has_data
        assert result.generated_at == 0

    async def test_check_relay_os_error_returns_empty(self, mock_brotr: Brotr) -> None:
        config = self._cfg(nip11_info=True)
        monitor = Monitor(brotr=mock_brotr, config=config)
        relay = Relay("wss://relay.example.com")

        with patch(
            "bigbrotr.services.monitor.service.retry_fetch",
            new_callable=AsyncMock,
            side_effect=OSError("connection refused"),
        ):
            result = await monitor.check_relay(relay)

        assert not result.has_data

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

        async def fake_worker(relay: Relay) -> tuple[Relay, CheckResult | None]:
            return (relay, result)

        monitor.clients = MagicMock()
        monitor.clients.disconnect = AsyncMock()

        with (
            patch(
                "bigbrotr.services.monitor.service.count_relays_to_monitor",
                new_callable=AsyncMock,
                return_value=3,
            ),
            patch(
                "bigbrotr.services.monitor.service.fetch_relays_to_monitor",
                new_callable=AsyncMock,
                side_effect=[[relay1, relay2, relay3], []],
            ),
            patch.object(monitor, "_monitoring_worker", side_effect=fake_worker),
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

    async def test_monitor_budget_limits_fetch(self, mock_brotr: Brotr) -> None:
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

        async def fake_worker(relay: Relay) -> tuple[Relay, CheckResult | None]:
            return (relay, result)

        monitor.clients = MagicMock()
        monitor.clients.disconnect = AsyncMock()

        with (
            patch(
                "bigbrotr.services.monitor.service.count_relays_to_monitor",
                new_callable=AsyncMock,
                return_value=10,
            ),
            patch(
                "bigbrotr.services.monitor.service.fetch_relays_to_monitor",
                new_callable=AsyncMock,
                side_effect=[[relay1], []],
            ) as mock_fetch,
            patch.object(monitor, "_monitoring_worker", side_effect=fake_worker),
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
        first_call_args = mock_fetch.call_args_list[0]
        assert first_call_args[0][3] == 1


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
