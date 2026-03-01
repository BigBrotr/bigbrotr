"""Shared fixtures and helpers for services.monitor test package."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from nostr_sdk import Keys

from bigbrotr.models import Relay
from bigbrotr.models.constants import ServiceName
from bigbrotr.nips.nip11 import Nip11
from bigbrotr.nips.nip11.data import Nip11InfoData, Nip11InfoDataLimitation
from bigbrotr.nips.nip11.info import Nip11InfoMetadata
from bigbrotr.nips.nip11.logs import Nip11InfoLogs
from bigbrotr.nips.nip66 import Nip66, Nip66RttMetadata, Nip66SslMetadata
from bigbrotr.nips.nip66.data import Nip66RttData, Nip66SslData
from bigbrotr.nips.nip66.logs import Nip66RttMultiPhaseLogs, Nip66SslLogs
from bigbrotr.services.common.configs import ClearnetConfig, NetworksConfig
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


# Valid secp256k1 test key (DO NOT USE IN PRODUCTION)
VALID_HEX_KEY = (
    "67dea2ed018072d675f5415ecfaed7d2597555e202d85b3d65ea4e58d2d92ffa"  # pragma: allowlist secret
)

# Fixed timestamp for deterministic time-based tests
FIXED_TIME = 1_700_000_000.0


@pytest.fixture(autouse=True)
def set_private_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set PRIVATE_KEY environment variable for all monitor tests."""
    monkeypatch.setenv("PRIVATE_KEY", VALID_HEX_KEY)


# ============================================================================
# Config helper
# ============================================================================

_NO_GEO_NET = MetadataFlags(nip66_geo=False, nip66_net=False)


def _make_config(**overrides: Any) -> MonitorConfig:
    """Build a MonitorConfig with geo/net disabled (no GeoIP databases needed).

    Accepts keyword overrides for any MonitorConfig field.
    """
    defaults: dict[str, Any] = {
        "processing": ProcessingConfig(compute=_NO_GEO_NET, store=_NO_GEO_NET),
        "discovery": DiscoveryConfig(include=_NO_GEO_NET),
    }
    defaults.update(overrides)
    return MonitorConfig(**defaults)


# ============================================================================
# Publishing test harness
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
        self.inc_counter = MagicMock()
        self.set_gauge = MagicMock()

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
# Publishing fixtures
# ============================================================================


@pytest.fixture
def test_keys() -> Keys:
    """Return Keys parsed from the valid hex test key."""
    return Keys.parse(VALID_HEX_KEY)


@pytest.fixture
def all_flags_config() -> MonitorConfig:
    """MonitorConfig with all metadata flags enabled and geo/net disabled to avoid DB checks."""
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
    """Return a _MonitorStub with all flags enabled."""
    return _MonitorStub(all_flags_config, test_keys)


# ============================================================================
# Data creation helpers
# ============================================================================


def _create_nip11(relay: Relay, data: dict | None = None, generated_at: int = 1700000001) -> Nip11:
    """Create a Nip11 instance with proper Nip11InfoMetadata structure."""
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
# Publishing helper factories
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
