"""
Unit tests for services.monitor_publisher and services.monitor_tags modules.

Tests:
- MonitorPublisherMixin: broadcasting, relay getters, announcement/profile/discovery publishing,
  Kind 0 and Kind 10166 event builders
- MonitorTagsMixin: RTT, SSL, net, geo, NIP-11, language, requirement/type tags,
  Kind 30166 event builder

Uses a lightweight test harness that provides the attributes the mixins expect
(self._config, self._keys, self._logger, self._brotr, self.SERVICE_NAME)
without instantiating the full Monitor class.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nostr_sdk import Keys, Tag

from bigbrotr.models import Relay, RelayMetadata
from bigbrotr.models.constants import ServiceName
from bigbrotr.models.metadata import Metadata, MetadataType
from bigbrotr.models.service_state import ServiceState, ServiceStateType
from bigbrotr.services.common.configs import ClearnetConfig, NetworkConfig
from bigbrotr.services.monitor import (
    AnnouncementConfig,
    CheckResult,
    DiscoveryConfig,
    MetadataFlags,
    MonitorConfig,
    MonitorProcessingConfig,
    ProfileConfig,
    PublishingConfig,
)
from bigbrotr.services.monitor_publisher import MonitorPublisherMixin
from bigbrotr.services.monitor_tags import MonitorTagsMixin


# Valid secp256k1 test key (DO NOT USE IN PRODUCTION)
VALID_HEX_KEY = (
    "67dea2ed018072d675f5415ecfaed7d2597555e202d85b3d65ea4e58d2d92ffa"  # pragma: allowlist secret
)


# ============================================================================
# Test Harness
# ============================================================================


class _PublisherHarness(MonitorPublisherMixin):
    """Lightweight harness providing the attributes MonitorPublisherMixin expects."""

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
        self.SERVICE_NAME = ServiceName.MONITOR


class _TagsHarness(MonitorTagsMixin):
    """Lightweight harness providing the attributes MonitorTagsMixin expects."""

    def __init__(self, config: MonitorConfig) -> None:
        self._config = config


class _CombinedHarness(MonitorTagsMixin, MonitorPublisherMixin):
    """Combined harness for methods that span both mixins (e.g. _build_kind_30166)."""

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
        self.SERVICE_NAME = ServiceName.MONITOR


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def set_private_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set PRIVATE_KEY environment variable for all tests in this module."""
    monkeypatch.setenv("PRIVATE_KEY", VALID_HEX_KEY)


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
def publisher(all_flags_config: MonitorConfig, test_keys: Keys) -> _PublisherHarness:
    """Return a _PublisherHarness with all flags enabled."""
    return _PublisherHarness(all_flags_config, test_keys)


@pytest.fixture
def tags_harness(all_flags_config: MonitorConfig) -> _TagsHarness:
    """Return a _TagsHarness with all flags enabled."""
    return _TagsHarness(all_flags_config)


@pytest.fixture
def combined_harness(all_flags_config: MonitorConfig, test_keys: Keys) -> _CombinedHarness:
    """Return a _CombinedHarness for cross-mixin methods."""
    return _CombinedHarness(all_flags_config, test_keys)


# ============================================================================
# Helper functions
# ============================================================================


def _make_relay_metadata(
    metadata_type: str,
    value: dict[str, Any],
) -> RelayMetadata:
    """Build a RelayMetadata with the given nested value dict."""
    relay = Relay("wss://relay.example.com")
    return RelayMetadata(
        relay=relay,
        metadata=Metadata(type=MetadataType(metadata_type), data=value),
        generated_at=1700000000,
    )


def _make_check_result(
    nip11: RelayMetadata | None = None,
    nip66_rtt: RelayMetadata | None = None,
    nip66_ssl: RelayMetadata | None = None,
    nip66_geo: RelayMetadata | None = None,
    nip66_net: RelayMetadata | None = None,
    nip66_dns: RelayMetadata | None = None,
    nip66_http: RelayMetadata | None = None,
) -> CheckResult:
    """Build a CheckResult with optional metadata fields."""
    return CheckResult(
        nip11=nip11,
        nip66_rtt=nip66_rtt,
        nip66_ssl=nip66_ssl,
        nip66_geo=nip66_geo,
        nip66_net=nip66_net,
        nip66_dns=nip66_dns,
        nip66_http=nip66_http,
    )


def _extract_tag_vecs(tags: list[Tag]) -> list[list[str]]:
    """Convert a list of nostr_sdk Tags to their vector representation."""
    return [t.as_vec() for t in tags]


def _extract_tag_map(tags: list[Tag]) -> dict[str, str]:
    """Convert tags to a {key: first_value} mapping (single-value tags only)."""
    return {t.as_vec()[0]: t.as_vec()[1] for t in tags if len(t.as_vec()) >= 2}


def _extract_tag_pairs(tags: list[Tag]) -> list[tuple[str, str]]:
    """Convert tags to a list of (key, first_value) tuples."""
    return [(t.as_vec()[0], t.as_vec()[1]) for t in tags if len(t.as_vec()) >= 2]


# ============================================================================
# MonitorPublisherMixin Tests: _broadcast_events
# ============================================================================


class TestBroadcastEvents:
    """Tests for MonitorPublisherMixin._broadcast_events."""

    async def test_broadcast_events_with_builders_and_relays(
        self, publisher: _PublisherHarness
    ) -> None:
        """Test that builders are signed and sent to all relays."""
        mock_client = AsyncMock()
        relay = Relay("wss://relay.example.com")
        mock_builder = MagicMock()

        with patch(
            "bigbrotr.services.monitor_publisher.create_client",
            return_value=mock_client,
        ):
            await publisher._broadcast_events([mock_builder], [relay])

        mock_client.add_relay.assert_awaited_once()
        mock_client.connect.assert_awaited_once()
        mock_client.send_event_builder.assert_awaited_once_with(mock_builder)
        mock_client.shutdown.assert_awaited_once()

    async def test_broadcast_events_multiple_builders_and_relays(
        self, publisher: _PublisherHarness
    ) -> None:
        """Test broadcasting multiple builders to multiple relays."""
        mock_client = AsyncMock()
        relays = [
            Relay("wss://relay1.example.com"),
            Relay("wss://relay2.example.com"),
        ]
        builders = [MagicMock(), MagicMock(), MagicMock()]

        with patch(
            "bigbrotr.services.monitor_publisher.create_client",
            return_value=mock_client,
        ):
            await publisher._broadcast_events(builders, relays)

        assert mock_client.add_relay.await_count == 2
        assert mock_client.send_event_builder.await_count == 3
        mock_client.shutdown.assert_awaited_once()

    async def test_broadcast_events_empty_builders(self, publisher: _PublisherHarness) -> None:
        """Test that empty builders list triggers early return."""
        relay = Relay("wss://relay.example.com")

        with patch(
            "bigbrotr.services.monitor_publisher.create_client",
        ) as mock_create:
            await publisher._broadcast_events([], [relay])
            mock_create.assert_not_called()

    async def test_broadcast_events_empty_relays(self, publisher: _PublisherHarness) -> None:
        """Test that empty relays list triggers early return."""
        mock_builder = MagicMock()

        with patch(
            "bigbrotr.services.monitor_publisher.create_client",
        ) as mock_create:
            await publisher._broadcast_events([mock_builder], [])
            mock_create.assert_not_called()

    async def test_broadcast_events_shutdown_called_on_error(
        self, publisher: _PublisherHarness
    ) -> None:
        """Test that client.shutdown() is called even when send_event_builder raises."""
        mock_client = AsyncMock()
        mock_client.send_event_builder.side_effect = OSError("send failed")
        relay = Relay("wss://relay.example.com")
        mock_builder = MagicMock()

        with (
            patch(
                "bigbrotr.services.monitor_publisher.create_client",
                return_value=mock_client,
            ),
            pytest.raises(OSError, match="send failed"),
        ):
            await publisher._broadcast_events([mock_builder], [relay])

        mock_client.shutdown.assert_awaited_once()


# ============================================================================
# MonitorPublisherMixin Tests: Relay Getters
# ============================================================================


class TestRelayGetters:
    """Tests for relay getter methods with primary and fallback logic."""

    def test_get_discovery_relays_returns_primary(self, publisher: _PublisherHarness) -> None:
        """Test _get_discovery_relays returns discovery-specific relays when set."""
        relays = publisher._get_discovery_relays()
        assert len(relays) == 1
        assert relays[0].url == "wss://disc.relay.com"

    def test_get_discovery_relays_falls_back_to_publishing(self, test_keys: Keys) -> None:
        """Test _get_discovery_relays falls back to publishing.relays when empty."""
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
        harness = _PublisherHarness(config, test_keys)
        relays = harness._get_discovery_relays()
        assert len(relays) == 1
        assert relays[0].url == "wss://fallback.relay.com"

    def test_get_announcement_relays_returns_primary(self, publisher: _PublisherHarness) -> None:
        """Test _get_announcement_relays returns announcement-specific relays when set."""
        relays = publisher._get_announcement_relays()
        assert len(relays) == 1
        assert relays[0].url == "wss://ann.relay.com"

    def test_get_announcement_relays_falls_back_to_publishing(self, test_keys: Keys) -> None:
        """Test _get_announcement_relays falls back to publishing.relays when empty."""
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
        harness = _PublisherHarness(config, test_keys)
        relays = harness._get_announcement_relays()
        assert len(relays) == 1
        assert relays[0].url == "wss://fallback.relay.com"

    def test_get_profile_relays_returns_primary(self, publisher: _PublisherHarness) -> None:
        """Test _get_profile_relays returns profile-specific relays when set."""
        relays = publisher._get_profile_relays()
        assert len(relays) == 1
        assert relays[0].url == "wss://profile.relay.com"

    def test_get_profile_relays_falls_back_to_publishing(self, test_keys: Keys) -> None:
        """Test _get_profile_relays falls back to publishing.relays when empty."""
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
        harness = _PublisherHarness(config, test_keys)
        relays = harness._get_profile_relays()
        assert len(relays) == 1
        assert relays[0].url == "wss://fallback.relay.com"


# ============================================================================
# MonitorPublisherMixin Tests: _publish_announcement
# ============================================================================


class TestPublishAnnouncement:
    """Tests for MonitorPublisherMixin._publish_announcement."""

    async def test_publish_announcement_when_disabled(self, test_keys: Keys) -> None:
        """Test that _publish_announcement returns immediately when disabled."""
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
        harness = _PublisherHarness(config, test_keys)
        await harness._publish_announcement()
        harness._brotr.get_service_state.assert_not_awaited()

    async def test_publish_announcement_when_no_relays(self, test_keys: Keys) -> None:
        """Test that _publish_announcement returns when no relays configured."""
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
        harness = _PublisherHarness(config, test_keys)
        await harness._publish_announcement()
        harness._brotr.get_service_state.assert_not_awaited()

    async def test_publish_announcement_interval_not_elapsed(
        self, publisher: _PublisherHarness
    ) -> None:
        """Test that announcement is skipped when interval has not elapsed."""
        now = time.time()
        publisher._brotr.get_service_state = AsyncMock(
            return_value=[
                ServiceState(
                    service_name=ServiceName.MONITOR,
                    state_type=ServiceStateType.CURSOR,
                    state_key="last_announcement",
                    state_value={"timestamp": now},
                    updated_at=int(now),
                )
            ]
        )
        with patch(
            "bigbrotr.services.monitor_publisher.create_client",
        ) as mock_create:
            await publisher._publish_announcement()
            mock_create.assert_not_called()

    async def test_publish_announcement_no_prior_state(self, publisher: _PublisherHarness) -> None:
        """Test successful announcement publish when no prior state exists."""
        publisher._brotr.get_service_state = AsyncMock(return_value=[])
        mock_client = AsyncMock()

        with patch(
            "bigbrotr.services.monitor_publisher.create_client",
            return_value=mock_client,
        ):
            await publisher._publish_announcement()

        mock_client.connect.assert_awaited_once()
        mock_client.send_event_builder.assert_awaited_once()
        mock_client.shutdown.assert_awaited_once()
        publisher._brotr.upsert_service_state.assert_awaited_once()
        publisher._logger.info.assert_called_with("announcement_published", relays=1)

    async def test_publish_announcement_interval_elapsed(
        self, publisher: _PublisherHarness
    ) -> None:
        """Test successful announcement publish when interval has elapsed."""
        old_timestamp = time.time() - 100000  # well past the 86400 interval
        publisher._brotr.get_service_state = AsyncMock(
            return_value=[
                ServiceState(
                    service_name=ServiceName.MONITOR,
                    state_type=ServiceStateType.CURSOR,
                    state_key="last_announcement",
                    state_value={"timestamp": old_timestamp},
                    updated_at=int(old_timestamp),
                )
            ]
        )
        mock_client = AsyncMock()

        with patch(
            "bigbrotr.services.monitor_publisher.create_client",
            return_value=mock_client,
        ):
            await publisher._publish_announcement()

        mock_client.send_event_builder.assert_awaited_once()
        publisher._brotr.upsert_service_state.assert_awaited_once()

    async def test_publish_announcement_broadcast_failure(
        self, publisher: _PublisherHarness
    ) -> None:
        """Test that announcement failure is logged as warning."""
        publisher._brotr.get_service_state = AsyncMock(return_value=[])
        mock_client = AsyncMock()
        mock_client.connect.side_effect = TimeoutError("connect timeout")

        with patch(
            "bigbrotr.services.monitor_publisher.create_client",
            return_value=mock_client,
        ):
            await publisher._publish_announcement()

        publisher._logger.warning.assert_called_once()
        assert "announcement_failed" in publisher._logger.warning.call_args[0]


# ============================================================================
# MonitorPublisherMixin Tests: _publish_profile
# ============================================================================


class TestPublishProfile:
    """Tests for MonitorPublisherMixin._publish_profile."""

    async def test_publish_profile_when_disabled(self, test_keys: Keys) -> None:
        """Test that _publish_profile returns immediately when disabled."""
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
        harness = _PublisherHarness(config, test_keys)
        await harness._publish_profile()
        harness._brotr.get_service_state.assert_not_awaited()

    async def test_publish_profile_when_no_relays(self, test_keys: Keys) -> None:
        """Test that _publish_profile returns when no relays configured."""
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
        harness = _PublisherHarness(config, test_keys)
        await harness._publish_profile()
        harness._brotr.get_service_state.assert_not_awaited()

    async def test_publish_profile_interval_not_elapsed(self, publisher: _PublisherHarness) -> None:
        """Test that profile is skipped when interval has not elapsed."""
        now = time.time()
        publisher._brotr.get_service_state = AsyncMock(
            return_value=[
                ServiceState(
                    service_name=ServiceName.MONITOR,
                    state_type=ServiceStateType.CURSOR,
                    state_key="last_profile",
                    state_value={"timestamp": now},
                    updated_at=int(now),
                )
            ]
        )
        with patch(
            "bigbrotr.services.monitor_publisher.create_client",
        ) as mock_create:
            await publisher._publish_profile()
            mock_create.assert_not_called()

    async def test_publish_profile_successful(self, publisher: _PublisherHarness) -> None:
        """Test successful profile publish when interval has elapsed."""
        publisher._brotr.get_service_state = AsyncMock(return_value=[])
        mock_client = AsyncMock()

        with patch(
            "bigbrotr.services.monitor_publisher.create_client",
            return_value=mock_client,
        ):
            await publisher._publish_profile()

        mock_client.connect.assert_awaited_once()
        mock_client.send_event_builder.assert_awaited_once()
        publisher._brotr.upsert_service_state.assert_awaited_once()
        publisher._logger.info.assert_called_with("profile_published", relays=1)

    async def test_publish_profile_broadcast_failure(self, publisher: _PublisherHarness) -> None:
        """Test that profile failure is logged as warning."""
        publisher._brotr.get_service_state = AsyncMock(return_value=[])
        mock_client = AsyncMock()
        mock_client.connect.side_effect = OSError("connection refused")

        with patch(
            "bigbrotr.services.monitor_publisher.create_client",
            return_value=mock_client,
        ):
            await publisher._publish_profile()

        publisher._logger.warning.assert_called_once()
        assert "profile_failed" in publisher._logger.warning.call_args[0]


# ============================================================================
# MonitorPublisherMixin Tests: _publish_relay_discoveries
# ============================================================================


class TestPublishRelayDiscoveries:
    """Tests for MonitorPublisherMixin._publish_relay_discoveries."""

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
        harness = _CombinedHarness(config, test_keys)

        relay = Relay("wss://relay.example.com")
        result = _make_check_result()

        with patch(
            "bigbrotr.services.monitor_publisher.create_client",
        ) as mock_create:
            await harness._publish_relay_discoveries([(relay, result)])
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
        harness = _CombinedHarness(config, test_keys)

        relay = Relay("wss://relay.example.com")
        result = _make_check_result()

        with patch(
            "bigbrotr.services.monitor_publisher.create_client",
        ) as mock_create:
            await harness._publish_relay_discoveries([(relay, result)])
            mock_create.assert_not_called()

    async def test_publish_discoveries_successful(self, combined_harness: _CombinedHarness) -> None:
        """Test successful relay discovery publishing."""
        relay = Relay("wss://relay.example.com")
        nip11 = _make_relay_metadata(
            "nip11_info",
            {"data": {"name": "Test Relay"}, "logs": {"success": True}},
        )
        result = _make_check_result(nip11=nip11)
        mock_client = AsyncMock()

        with patch(
            "bigbrotr.services.monitor_publisher.create_client",
            return_value=mock_client,
        ):
            await combined_harness._publish_relay_discoveries([(relay, result)])

        mock_client.connect.assert_awaited_once()
        mock_client.send_event_builder.assert_awaited_once()
        combined_harness._logger.debug.assert_any_call("discoveries_published", count=1)

    async def test_publish_discoveries_build_failure_for_individual(
        self, combined_harness: _CombinedHarness
    ) -> None:
        """Test that build failure for one relay does not prevent others."""
        relay1 = Relay("wss://relay1.example.com")
        relay2 = Relay("wss://relay2.example.com")
        result1 = _make_check_result()
        nip11 = _make_relay_metadata(
            "nip11_info",
            {"data": {"name": "Test"}, "logs": {"success": True}},
        )
        result2 = _make_check_result(nip11=nip11)

        mock_client = AsyncMock()

        # Patch _build_kind_30166 to raise on the first relay only
        original_build = combined_harness._build_kind_30166
        call_count = 0

        def _patched_build(relay: Relay, result: CheckResult) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("build failed for relay1")
            return original_build(relay, result)

        combined_harness._build_kind_30166 = _patched_build  # type: ignore[assignment]

        with patch(
            "bigbrotr.services.monitor_publisher.create_client",
            return_value=mock_client,
        ):
            await combined_harness._publish_relay_discoveries(
                [(relay1, result1), (relay2, result2)]
            )

        # One builder should have succeeded
        mock_client.send_event_builder.assert_awaited_once()
        combined_harness._logger.debug.assert_any_call(
            "build_30166_failed", url=relay1.url, error="build failed for relay1"
        )

    async def test_publish_discoveries_broadcast_failure(
        self, combined_harness: _CombinedHarness
    ) -> None:
        """Test that broadcast failure is logged as warning."""
        relay = Relay("wss://relay.example.com")
        result = _make_check_result()
        mock_client = AsyncMock()
        mock_client.connect.side_effect = TimeoutError("broadcast timeout")

        with patch(
            "bigbrotr.services.monitor_publisher.create_client",
            return_value=mock_client,
        ):
            await combined_harness._publish_relay_discoveries([(relay, result)])

        combined_harness._logger.warning.assert_called_once()
        assert "discoveries_broadcast_failed" in combined_harness._logger.warning.call_args[0]


# ============================================================================
# MonitorPublisherMixin Tests: _build_kind_0
# ============================================================================


class TestBuildKind0:
    """Tests for MonitorPublisherMixin._build_kind_0 (profile metadata)."""

    def test_build_kind_0_all_fields(self, publisher: _PublisherHarness) -> None:
        """Test Kind 0 builder with all profile fields populated."""
        builder = publisher._build_kind_0()
        # EventBuilder is returned; just verify it doesn't raise
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
        harness = _PublisherHarness(config, test_keys)
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
        harness = _PublisherHarness(config, test_keys)
        builder = harness._build_kind_0()
        assert builder is not None


# ============================================================================
# MonitorPublisherMixin Tests: _build_kind_10166
# ============================================================================


class TestBuildKind10166:
    """Tests for MonitorPublisherMixin._build_kind_10166 (monitor announcement)."""

    def test_build_kind_10166_all_flags_enabled(self, publisher: _PublisherHarness) -> None:
        """Test Kind 10166 builder with all metadata flags enabled."""
        builder = publisher._build_kind_10166()
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
        harness = _PublisherHarness(config, test_keys)
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
        harness = _PublisherHarness(config, test_keys)
        builder = harness._build_kind_10166()
        assert builder is not None


# ============================================================================
# MonitorTagsMixin Tests: _add_rtt_tags
# ============================================================================


class TestAddRttTags:
    """Tests for MonitorTagsMixin._add_rtt_tags."""

    def test_add_rtt_tags_with_data(self, tags_harness: _TagsHarness) -> None:
        """Test RTT tags are added when data is present."""
        rm = _make_relay_metadata(
            "nip66_rtt",
            {
                "data": {"rtt_open": 45, "rtt_read": 120, "rtt_write": 85},
                "logs": {"open_success": True},
            },
        )
        result = _make_check_result(nip66_rtt=rm)
        tags: list[Tag] = []
        tags_harness._add_rtt_tags(tags, result, MetadataFlags())

        tag_map = _extract_tag_map(tags)
        assert tag_map["rtt-open"] == "45"
        assert tag_map["rtt-read"] == "120"
        assert tag_map["rtt-write"] == "85"

    def test_add_rtt_tags_partial_data(self, tags_harness: _TagsHarness) -> None:
        """Test RTT tags with only rtt_open present."""
        rm = _make_relay_metadata(
            "nip66_rtt",
            {
                "data": {"rtt_open": 30},
                "logs": {"open_success": True},
            },
        )
        result = _make_check_result(nip66_rtt=rm)
        tags: list[Tag] = []
        tags_harness._add_rtt_tags(tags, result, MetadataFlags())

        tag_map = _extract_tag_map(tags)
        assert tag_map["rtt-open"] == "30"
        assert "rtt-read" not in tag_map
        assert "rtt-write" not in tag_map

    def test_add_rtt_tags_no_result(self, tags_harness: _TagsHarness) -> None:
        """Test RTT tags when nip66_rtt is None."""
        result = _make_check_result()
        tags: list[Tag] = []
        tags_harness._add_rtt_tags(tags, result, MetadataFlags())
        assert tags == []

    def test_add_rtt_tags_flag_disabled(self, tags_harness: _TagsHarness) -> None:
        """Test RTT tags are not added when include flag is disabled."""
        rm = _make_relay_metadata(
            "nip66_rtt",
            {
                "data": {"rtt_open": 45, "rtt_read": 120, "rtt_write": 85},
                "logs": {"open_success": True},
            },
        )
        result = _make_check_result(nip66_rtt=rm)
        tags: list[Tag] = []
        tags_harness._add_rtt_tags(tags, result, MetadataFlags(nip66_rtt=False))
        assert tags == []

    def test_add_rtt_tags_missing_data_key(self, tags_harness: _TagsHarness) -> None:
        """Test RTT tags when data key is absent from metadata value."""
        rm = _make_relay_metadata(
            "nip66_rtt",
            {"logs": {"open_success": False}},
        )
        result = _make_check_result(nip66_rtt=rm)
        tags: list[Tag] = []
        tags_harness._add_rtt_tags(tags, result, MetadataFlags())
        assert tags == []


# ============================================================================
# MonitorTagsMixin Tests: _add_ssl_tags
# ============================================================================


class TestAddSslTags:
    """Tests for MonitorTagsMixin._add_ssl_tags."""

    def test_add_ssl_tags_valid(self, tags_harness: _TagsHarness) -> None:
        """Test SSL tags with valid certificate data."""
        rm = _make_relay_metadata(
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
        result = _make_check_result(nip66_ssl=rm)
        tags: list[Tag] = []
        tags_harness._add_ssl_tags(tags, result, MetadataFlags())

        tag_map = _extract_tag_map(tags)
        assert tag_map["ssl"] == "valid"
        assert tag_map["ssl-expires"] == "1735689600"
        assert tag_map["ssl-issuer"] == "Let's Encrypt"

    def test_add_ssl_tags_invalid(self, tags_harness: _TagsHarness) -> None:
        """Test SSL tags with invalid certificate."""
        rm = _make_relay_metadata(
            "nip66_ssl",
            {
                "data": {"ssl_valid": False, "ssl_expires": 1600000000},
                "logs": {"success": True},
            },
        )
        result = _make_check_result(nip66_ssl=rm)
        tags: list[Tag] = []
        tags_harness._add_ssl_tags(tags, result, MetadataFlags())

        tag_map = _extract_tag_map(tags)
        assert tag_map["ssl"] == "!valid"
        assert tag_map["ssl-expires"] == "1600000000"
        assert "ssl-issuer" not in tag_map

    def test_add_ssl_tags_missing_fields(self, tags_harness: _TagsHarness) -> None:
        """Test SSL tags when only ssl_valid is present."""
        rm = _make_relay_metadata(
            "nip66_ssl",
            {
                "data": {"ssl_valid": True},
                "logs": {"success": True},
            },
        )
        result = _make_check_result(nip66_ssl=rm)
        tags: list[Tag] = []
        tags_harness._add_ssl_tags(tags, result, MetadataFlags())

        tag_map = _extract_tag_map(tags)
        assert tag_map["ssl"] == "valid"
        assert "ssl-expires" not in tag_map
        assert "ssl-issuer" not in tag_map

    def test_add_ssl_tags_no_result(self, tags_harness: _TagsHarness) -> None:
        """Test SSL tags when nip66_ssl is None."""
        result = _make_check_result()
        tags: list[Tag] = []
        tags_harness._add_ssl_tags(tags, result, MetadataFlags())
        assert tags == []

    def test_add_ssl_tags_flag_disabled(self, tags_harness: _TagsHarness) -> None:
        """Test SSL tags are not added when include flag is disabled."""
        rm = _make_relay_metadata(
            "nip66_ssl",
            {
                "data": {"ssl_valid": True},
                "logs": {"success": True},
            },
        )
        result = _make_check_result(nip66_ssl=rm)
        tags: list[Tag] = []
        tags_harness._add_ssl_tags(tags, result, MetadataFlags(nip66_ssl=False))
        assert tags == []


# ============================================================================
# MonitorTagsMixin Tests: _add_net_tags
# ============================================================================


class TestAddNetTags:
    """Tests for MonitorTagsMixin._add_net_tags."""

    def test_add_net_tags_all_fields(self, tags_harness: _TagsHarness) -> None:
        """Test net tags with all fields present."""
        rm = _make_relay_metadata(
            "nip66_net",
            {
                "data": {
                    "net_ip": "1.2.3.4",
                    "net_ipv6": "2001:db8::1",
                    "net_asn": 13335,
                    "net_asn_org": "Cloudflare",
                },
                "logs": {"success": True},
            },
        )
        result = _make_check_result(nip66_net=rm)
        tags: list[Tag] = []
        tags_harness._add_net_tags(tags, result, MetadataFlags())

        tag_map = _extract_tag_map(tags)
        assert tag_map["net-ip"] == "1.2.3.4"
        assert tag_map["net-ipv6"] == "2001:db8::1"
        assert tag_map["net-asn"] == "13335"
        assert tag_map["net-asn-org"] == "Cloudflare"

    def test_add_net_tags_partial_fields(self, tags_harness: _TagsHarness) -> None:
        """Test net tags with only IP and ASN present."""
        rm = _make_relay_metadata(
            "nip66_net",
            {
                "data": {"net_ip": "8.8.8.8", "net_asn": 15169},
                "logs": {"success": True},
            },
        )
        result = _make_check_result(nip66_net=rm)
        tags: list[Tag] = []
        tags_harness._add_net_tags(tags, result, MetadataFlags())

        tag_map = _extract_tag_map(tags)
        assert tag_map["net-ip"] == "8.8.8.8"
        assert tag_map["net-asn"] == "15169"
        assert "net-ipv6" not in tag_map
        assert "net-asn-org" not in tag_map

    def test_add_net_tags_no_result(self, tags_harness: _TagsHarness) -> None:
        """Test net tags when nip66_net is None."""
        result = _make_check_result()
        tags: list[Tag] = []
        tags_harness._add_net_tags(tags, result, MetadataFlags())
        assert tags == []

    def test_add_net_tags_flag_disabled(self, tags_harness: _TagsHarness) -> None:
        """Test net tags are not added when include flag is disabled."""
        rm = _make_relay_metadata(
            "nip66_net",
            {
                "data": {"net_ip": "1.2.3.4"},
                "logs": {"success": True},
            },
        )
        result = _make_check_result(nip66_net=rm)
        tags: list[Tag] = []
        tags_harness._add_net_tags(tags, result, MetadataFlags(nip66_net=False))
        assert tags == []


# ============================================================================
# MonitorTagsMixin Tests: _add_geo_tags
# ============================================================================


class TestAddGeoTags:
    """Tests for MonitorTagsMixin._add_geo_tags."""

    def test_add_geo_tags_all_fields(self, tags_harness: _TagsHarness) -> None:
        """Test geo tags with all fields present."""
        rm = _make_relay_metadata(
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
        result = _make_check_result(nip66_geo=rm)
        tags: list[Tag] = []
        tags_harness._add_geo_tags(tags, result, MetadataFlags())

        tag_map = _extract_tag_map(tags)
        assert tag_map["g"] == "u33dc"
        assert tag_map["geo-country"] == "DE"
        assert tag_map["geo-city"] == "Frankfurt"
        assert tag_map["geo-lat"] == "50.1109"
        assert tag_map["geo-lon"] == "8.6821"
        assert tag_map["geo-tz"] == "Europe/Berlin"

    def test_add_geo_tags_partial_fields(self, tags_harness: _TagsHarness) -> None:
        """Test geo tags with only country and geohash present."""
        rm = _make_relay_metadata(
            "nip66_geo",
            {
                "data": {"geo_hash": "abc", "geo_country": "US"},
                "logs": {"success": True},
            },
        )
        result = _make_check_result(nip66_geo=rm)
        tags: list[Tag] = []
        tags_harness._add_geo_tags(tags, result, MetadataFlags())

        tag_map = _extract_tag_map(tags)
        assert tag_map["g"] == "abc"
        assert tag_map["geo-country"] == "US"
        assert "geo-city" not in tag_map
        assert "geo-lat" not in tag_map
        assert "geo-lon" not in tag_map
        assert "geo-tz" not in tag_map

    def test_add_geo_tags_no_result(self, tags_harness: _TagsHarness) -> None:
        """Test geo tags when nip66_geo is None."""
        result = _make_check_result()
        tags: list[Tag] = []
        tags_harness._add_geo_tags(tags, result, MetadataFlags())
        assert tags == []

    def test_add_geo_tags_flag_disabled(self, tags_harness: _TagsHarness) -> None:
        """Test geo tags are not added when include flag is disabled."""
        rm = _make_relay_metadata(
            "nip66_geo",
            {
                "data": {"geo_hash": "u33dc", "geo_country": "DE"},
                "logs": {"success": True},
            },
        )
        result = _make_check_result(nip66_geo=rm)
        tags: list[Tag] = []
        tags_harness._add_geo_tags(tags, result, MetadataFlags(nip66_geo=False))
        assert tags == []


# ============================================================================
# MonitorTagsMixin Tests: _add_nip11_tags
# ============================================================================


class TestAddNip11Tags:
    """Tests for MonitorTagsMixin._add_nip11_tags."""

    def test_add_nip11_tags_with_nips(self, tags_harness: _TagsHarness) -> None:
        """Test NIP-11 tags with supported_nips."""
        rm = _make_relay_metadata(
            "nip11_info",
            {
                "data": {"supported_nips": [1, 11, 42, 50]},
                "logs": {"success": True},
            },
        )
        result = _make_check_result(nip11=rm)
        tags: list[Tag] = []
        tags_harness._add_nip11_tags(tags, result, MetadataFlags())

        pairs = _extract_tag_pairs(tags)
        nip_tags = [(k, v) for k, v in pairs if k == "N"]
        assert ("N", "1") in nip_tags
        assert ("N", "11") in nip_tags
        assert ("N", "42") in nip_tags
        assert ("N", "50") in nip_tags

    def test_add_nip11_tags_with_topic_tags(self, tags_harness: _TagsHarness) -> None:
        """Test NIP-11 tags with topic (t) tags."""
        rm = _make_relay_metadata(
            "nip11_info",
            {
                "data": {"tags": ["social", "bitcoin", "nostr"]},
                "logs": {"success": True},
            },
        )
        result = _make_check_result(nip11=rm)
        tags: list[Tag] = []
        tags_harness._add_nip11_tags(tags, result, MetadataFlags())

        pairs = _extract_tag_pairs(tags)
        topic_tags = [(k, v) for k, v in pairs if k == "t"]
        assert ("t", "social") in topic_tags
        assert ("t", "bitcoin") in topic_tags
        assert ("t", "nostr") in topic_tags

    def test_add_nip11_tags_with_languages(self, tags_harness: _TagsHarness) -> None:
        """Test NIP-11 tags with language_tags."""
        rm = _make_relay_metadata(
            "nip11_info",
            {
                "data": {"language_tags": ["en", "de", "fr-FR"]},
                "logs": {"success": True},
            },
        )
        result = _make_check_result(nip11=rm)
        tags: list[Tag] = []
        tags_harness._add_nip11_tags(tags, result, MetadataFlags())

        tag_vecs = _extract_tag_vecs(tags)
        lang_tags = [v for v in tag_vecs if v[0] == "l"]
        lang_primaries = [v[1] for v in lang_tags]
        assert "en" in lang_primaries
        assert "de" in lang_primaries
        assert "fr" in lang_primaries  # fr-FR -> fr

    def test_add_nip11_tags_with_requirements(self, tags_harness: _TagsHarness) -> None:
        """Test NIP-11 tags add requirement (R) tags."""
        rm = _make_relay_metadata(
            "nip11_info",
            {
                "data": {
                    "limitation": {"auth_required": True, "payment_required": False},
                },
                "logs": {"success": True},
            },
        )
        result = _make_check_result(nip11=rm)
        tags: list[Tag] = []
        tags_harness._add_nip11_tags(tags, result, MetadataFlags())

        pairs = _extract_tag_pairs(tags)
        req_tags = [(k, v) for k, v in pairs if k == "R"]
        assert ("R", "auth") in req_tags
        assert ("R", "!payment") in req_tags

    def test_add_nip11_tags_no_result(self, tags_harness: _TagsHarness) -> None:
        """Test NIP-11 tags when nip11 is None."""
        result = _make_check_result()
        tags: list[Tag] = []
        tags_harness._add_nip11_tags(tags, result, MetadataFlags())
        assert tags == []

    def test_add_nip11_tags_flag_disabled(self, tags_harness: _TagsHarness) -> None:
        """Test NIP-11 tags are not added when include flag is disabled."""
        rm = _make_relay_metadata(
            "nip11_info",
            {
                "data": {"supported_nips": [1, 11]},
                "logs": {"success": True},
            },
        )
        result = _make_check_result(nip11=rm)
        tags: list[Tag] = []
        tags_harness._add_nip11_tags(tags, result, MetadataFlags(nip11_info=False))
        assert tags == []


# ============================================================================
# MonitorTagsMixin Tests: _add_language_tags
# ============================================================================


class TestAddLanguageTags:
    """Tests for MonitorTagsMixin._add_language_tags."""

    def test_add_language_tags_filtering(self, tags_harness: _TagsHarness) -> None:
        """Test language tags filter to ISO 639-1 (2-char) codes."""
        nip11_data = {"language_tags": ["en", "de", "en-US", "fr-FR", "zz"]}
        tags: list[Tag] = []
        tags_harness._add_language_tags(tags, nip11_data)

        tag_vecs = _extract_tag_vecs(tags)
        lang_primaries = [v[1] for v in tag_vecs if v[0] == "l"]
        assert "en" in lang_primaries
        assert "de" in lang_primaries
        assert "fr" in lang_primaries
        assert "zz" in lang_primaries

    def test_add_language_tags_wildcard(self, tags_harness: _TagsHarness) -> None:
        """Test language tags are skipped when wildcard is present."""
        nip11_data = {"language_tags": ["en", "*", "de"]}
        tags: list[Tag] = []
        tags_harness._add_language_tags(tags, nip11_data)
        assert tags == []

    def test_add_language_tags_dedup(self, tags_harness: _TagsHarness) -> None:
        """Test language tags deduplication of primary codes."""
        nip11_data = {"language_tags": ["en", "en-US", "en-GB"]}
        tags: list[Tag] = []
        tags_harness._add_language_tags(tags, nip11_data)

        tag_vecs = _extract_tag_vecs(tags)
        lang_primaries = [v[1] for v in tag_vecs if v[0] == "l"]
        assert lang_primaries == ["en"]  # Only one "en" despite three entries

    def test_add_language_tags_empty(self, tags_harness: _TagsHarness) -> None:
        """Test language tags with empty list."""
        nip11_data = {"language_tags": []}
        tags: list[Tag] = []
        tags_harness._add_language_tags(tags, nip11_data)
        assert tags == []

    def test_add_language_tags_no_key(self, tags_harness: _TagsHarness) -> None:
        """Test language tags when key is missing."""
        nip11_data: dict[str, Any] = {}
        tags: list[Tag] = []
        tags_harness._add_language_tags(tags, nip11_data)
        assert tags == []

    def test_add_language_tags_uses_iso_639_1_label(self, tags_harness: _TagsHarness) -> None:
        """Test that language tags have ISO-639-1 as third element."""
        nip11_data = {"language_tags": ["en"]}
        tags: list[Tag] = []
        tags_harness._add_language_tags(tags, nip11_data)

        assert len(tags) == 1
        vec = tags[0].as_vec()
        assert vec[0] == "l"
        assert vec[1] == "en"
        assert vec[2] == "ISO-639-1"


# ============================================================================
# MonitorTagsMixin Tests: _add_requirement_and_type_tags
# ============================================================================


class TestAddRequirementAndTypeTags:
    """Tests for MonitorTagsMixin._add_requirement_and_type_tags."""

    def test_auth_from_nip11(self, tags_harness: _TagsHarness) -> None:
        """Test auth requirement from NIP-11 limitation."""
        result = _make_check_result()
        nip11_data: dict[str, Any] = {"limitation": {"auth_required": True}}
        tags: list[Tag] = []
        tags_harness._add_requirement_and_type_tags(tags, result, nip11_data, None)

        pairs = _extract_tag_pairs(tags)
        assert ("R", "auth") in pairs

    def test_auth_from_rtt_probe(self, tags_harness: _TagsHarness) -> None:
        """Test auth requirement detected from RTT probe write failure."""
        rtt_rm = _make_relay_metadata(
            "nip66_rtt",
            {
                "data": {"rtt_open": 45},
                "logs": {"write_success": False, "write_reason": "auth-required: NIP-42"},
            },
        )
        result = _make_check_result(nip66_rtt=rtt_rm)
        nip11_data: dict[str, Any] = {}
        tags: list[Tag] = []
        tags_harness._add_requirement_and_type_tags(tags, result, nip11_data, None)

        pairs = _extract_tag_pairs(tags)
        assert ("R", "auth") in pairs

    def test_payment_from_nip11(self, tags_harness: _TagsHarness) -> None:
        """Test payment requirement from NIP-11 limitation."""
        result = _make_check_result()
        nip11_data: dict[str, Any] = {"limitation": {"payment_required": True}}
        tags: list[Tag] = []
        tags_harness._add_requirement_and_type_tags(tags, result, nip11_data, None)

        pairs = _extract_tag_pairs(tags)
        assert ("R", "payment") in pairs

    def test_payment_from_rtt_probe(self, tags_harness: _TagsHarness) -> None:
        """Test payment requirement detected from RTT probe write failure."""
        rtt_rm = _make_relay_metadata(
            "nip66_rtt",
            {
                "data": {"rtt_open": 45},
                "logs": {"write_success": False, "write_reason": "payment required"},
            },
        )
        result = _make_check_result(nip66_rtt=rtt_rm)
        nip11_data: dict[str, Any] = {}
        tags: list[Tag] = []
        tags_harness._add_requirement_and_type_tags(tags, result, nip11_data, None)

        pairs = _extract_tag_pairs(tags)
        assert ("R", "payment") in pairs

    def test_restricted_writes_from_nip11(self, tags_harness: _TagsHarness) -> None:
        """Test restricted_writes requirement from NIP-11."""
        result = _make_check_result()
        nip11_data: dict[str, Any] = {"limitation": {"restricted_writes": True}}
        tags: list[Tag] = []
        tags_harness._add_requirement_and_type_tags(tags, result, nip11_data, None)

        pairs = _extract_tag_pairs(tags)
        assert ("R", "writes") in pairs

    def test_writes_cleared_when_write_succeeds(self, tags_harness: _TagsHarness) -> None:
        """Test writes restriction is cleared when RTT probe write succeeds."""
        rtt_rm = _make_relay_metadata(
            "nip66_rtt",
            {
                "data": {"rtt_open": 45, "rtt_write": 100},
                "logs": {"write_success": True},
            },
        )
        result = _make_check_result(nip66_rtt=rtt_rm)
        nip11_data: dict[str, Any] = {"limitation": {"restricted_writes": True}}
        tags: list[Tag] = []
        tags_harness._add_requirement_and_type_tags(tags, result, nip11_data, None)

        pairs = _extract_tag_pairs(tags)
        assert ("R", "!writes") in pairs  # Overridden by probe success

    def test_pow_requirement(self, tags_harness: _TagsHarness) -> None:
        """Test PoW requirement from NIP-11 limitation."""
        result = _make_check_result()
        nip11_data: dict[str, Any] = {"limitation": {"min_pow_difficulty": 16}}
        tags: list[Tag] = []
        tags_harness._add_requirement_and_type_tags(tags, result, nip11_data, None)

        pairs = _extract_tag_pairs(tags)
        assert ("R", "pow") in pairs

    def test_no_pow_when_zero(self, tags_harness: _TagsHarness) -> None:
        """Test no PoW requirement when min_pow_difficulty is 0."""
        result = _make_check_result()
        nip11_data: dict[str, Any] = {"limitation": {"min_pow_difficulty": 0}}
        tags: list[Tag] = []
        tags_harness._add_requirement_and_type_tags(tags, result, nip11_data, None)

        pairs = _extract_tag_pairs(tags)
        assert ("R", "!pow") in pairs

    def test_all_restrictions_false(self, tags_harness: _TagsHarness) -> None:
        """Test all restrictions are negated when no restrictions apply."""
        result = _make_check_result()
        nip11_data: dict[str, Any] = {}
        tags: list[Tag] = []
        tags_harness._add_requirement_and_type_tags(tags, result, nip11_data, None)

        pairs = _extract_tag_pairs(tags)
        assert ("R", "!auth") in pairs
        assert ("R", "!payment") in pairs
        assert ("R", "!writes") in pairs
        assert ("R", "!pow") in pairs

    def test_auth_and_payment_combined(self, tags_harness: _TagsHarness) -> None:
        """Test combined auth and payment requirements."""
        result = _make_check_result()
        nip11_data: dict[str, Any] = {
            "limitation": {
                "auth_required": True,
                "payment_required": True,
            }
        }
        tags: list[Tag] = []
        tags_harness._add_requirement_and_type_tags(tags, result, nip11_data, None)

        pairs = _extract_tag_pairs(tags)
        assert ("R", "auth") in pairs
        assert ("R", "payment") in pairs

    def test_read_auth_from_rtt_probe(self, tags_harness: _TagsHarness) -> None:
        """Test read_auth detection from RTT probe read failure with auth reason."""
        rtt_rm = _make_relay_metadata(
            "nip66_rtt",
            {
                "data": {"rtt_open": 45},
                "logs": {
                    "read_success": False,
                    "read_reason": "auth-required",
                    "write_success": False,
                    "write_reason": "auth-required: NIP-42",
                },
            },
        )
        result = _make_check_result(nip66_rtt=rtt_rm)
        nip11_data: dict[str, Any] = {"limitation": {"auth_required": True}}
        tags: list[Tag] = []
        tags_harness._add_requirement_and_type_tags(tags, result, nip11_data, None)

        pairs = _extract_tag_pairs(tags)
        # read_auth + auth -> PrivateStorage
        assert ("T", "PrivateStorage") in pairs


# ============================================================================
# MonitorTagsMixin Tests: _add_type_tags
# ============================================================================


class TestAddTypeTags:
    """Tests for MonitorTagsMixin._add_type_tags."""

    def test_search_type(self, tags_harness: _TagsHarness) -> None:
        """Test Search type tag when NIP-50 is supported."""
        from bigbrotr.services.monitor_tags import _AccessFlags

        tags: list[Tag] = []
        access = _AccessFlags(payment=False, auth=False, writes=False, read_auth=False)
        tags_harness._add_type_tags(tags, [50], access)

        pairs = _extract_tag_pairs(tags)
        assert ("T", "Search") in pairs

    def test_community_type(self, tags_harness: _TagsHarness) -> None:
        """Test Community type tag when NIP-29 is supported."""
        from bigbrotr.services.monitor_tags import _AccessFlags

        tags: list[Tag] = []
        access = _AccessFlags(payment=False, auth=False, writes=False, read_auth=False)
        tags_harness._add_type_tags(tags, [29], access)

        pairs = _extract_tag_pairs(tags)
        assert ("T", "Community") in pairs

    def test_blob_type(self, tags_harness: _TagsHarness) -> None:
        """Test Blob type tag when NIP-95 is supported."""
        from bigbrotr.services.monitor_tags import _AccessFlags

        tags: list[Tag] = []
        access = _AccessFlags(payment=False, auth=False, writes=False, read_auth=False)
        tags_harness._add_type_tags(tags, [95], access)

        pairs = _extract_tag_pairs(tags)
        assert ("T", "Blob") in pairs

    def test_paid_type(self, tags_harness: _TagsHarness) -> None:
        """Test Paid type tag when payment is required."""
        from bigbrotr.services.monitor_tags import _AccessFlags

        tags: list[Tag] = []
        access = _AccessFlags(payment=True, auth=False, writes=False, read_auth=False)
        tags_harness._add_type_tags(tags, None, access)

        pairs = _extract_tag_pairs(tags)
        assert ("T", "Paid") in pairs
        # Payment without read_auth -> PublicOutbox
        assert ("T", "PublicOutbox") in pairs

    def test_public_inbox_type(self, tags_harness: _TagsHarness) -> None:
        """Test PublicInbox type tag for open relay with no restrictions."""
        from bigbrotr.services.monitor_tags import _AccessFlags

        tags: list[Tag] = []
        access = _AccessFlags(payment=False, auth=False, writes=False, read_auth=False)
        tags_harness._add_type_tags(tags, None, access)

        pairs = _extract_tag_pairs(tags)
        assert ("T", "PublicInbox") in pairs

    def test_public_outbox_type_auth(self, tags_harness: _TagsHarness) -> None:
        """Test PublicOutbox type tag when auth is required (no read_auth)."""
        from bigbrotr.services.monitor_tags import _AccessFlags

        tags: list[Tag] = []
        access = _AccessFlags(payment=False, auth=True, writes=False, read_auth=False)
        tags_harness._add_type_tags(tags, None, access)

        pairs = _extract_tag_pairs(tags)
        assert ("T", "PublicOutbox") in pairs

    def test_public_outbox_type_writes(self, tags_harness: _TagsHarness) -> None:
        """Test PublicOutbox type tag when writes are restricted (no read_auth)."""
        from bigbrotr.services.monitor_tags import _AccessFlags

        tags: list[Tag] = []
        access = _AccessFlags(payment=False, auth=False, writes=True, read_auth=False)
        tags_harness._add_type_tags(tags, None, access)

        pairs = _extract_tag_pairs(tags)
        assert ("T", "PublicOutbox") in pairs

    def test_private_storage_type(self, tags_harness: _TagsHarness) -> None:
        """Test PrivateStorage type tag when read_auth and auth are both true."""
        from bigbrotr.services.monitor_tags import _AccessFlags

        tags: list[Tag] = []
        access = _AccessFlags(payment=False, auth=True, writes=False, read_auth=True)
        tags_harness._add_type_tags(tags, None, access)

        pairs = _extract_tag_pairs(tags)
        assert ("T", "PrivateStorage") in pairs

    def test_private_inbox_type(self, tags_harness: _TagsHarness) -> None:
        """Test PrivateInbox type tag when read_auth is true but auth is false."""
        from bigbrotr.services.monitor_tags import _AccessFlags

        tags: list[Tag] = []
        access = _AccessFlags(payment=False, auth=False, writes=False, read_auth=True)
        tags_harness._add_type_tags(tags, None, access)

        pairs = _extract_tag_pairs(tags)
        assert ("T", "PrivateInbox") in pairs

    def test_multiple_capability_types(self, tags_harness: _TagsHarness) -> None:
        """Test multiple capability-based type tags when multiple NIPs are supported."""
        from bigbrotr.services.monitor_tags import _AccessFlags

        tags: list[Tag] = []
        access = _AccessFlags(payment=False, auth=False, writes=False, read_auth=False)
        tags_harness._add_type_tags(tags, [29, 50, 95], access)

        pairs = _extract_tag_pairs(tags)
        assert ("T", "Search") in pairs
        assert ("T", "Community") in pairs
        assert ("T", "Blob") in pairs
        assert ("T", "PublicInbox") in pairs

    def test_paid_search_relay(self, tags_harness: _TagsHarness) -> None:
        """Test combined Paid and Search type tags."""
        from bigbrotr.services.monitor_tags import _AccessFlags

        tags: list[Tag] = []
        access = _AccessFlags(payment=True, auth=False, writes=False, read_auth=False)
        tags_harness._add_type_tags(tags, [50], access)

        pairs = _extract_tag_pairs(tags)
        assert ("T", "Search") in pairs
        assert ("T", "Paid") in pairs
        assert ("T", "PublicOutbox") in pairs


# ============================================================================
# MonitorTagsMixin Tests: _build_kind_30166
# ============================================================================


class TestBuildKind30166:
    """Tests for MonitorTagsMixin._build_kind_30166."""

    def test_build_kind_30166_full_event(self, combined_harness: _CombinedHarness) -> None:
        """Test full Kind 30166 event construction with all metadata."""
        relay = Relay("wss://relay.example.com")
        nip11 = _make_relay_metadata(
            "nip11_info",
            {
                "data": {
                    "name": "Test Relay",
                    "supported_nips": [1, 11, 50],
                    "tags": ["social"],
                    "language_tags": ["en"],
                },
                "logs": {"success": True},
            },
        )
        rtt = _make_relay_metadata(
            "nip66_rtt",
            {
                "data": {"rtt_open": 45, "rtt_read": 120, "rtt_write": 85},
                "logs": {"open_success": True},
            },
        )
        ssl_meta = _make_relay_metadata(
            "nip66_ssl",
            {
                "data": {"ssl_valid": True, "ssl_expires": 1735689600},
                "logs": {"success": True},
            },
        )
        builder = combined_harness._build_kind_30166(
            relay,
            _make_check_result(
                nip11=nip11,
                nip66_rtt=rtt,
                nip66_ssl=ssl_meta,
            ),
        )
        assert builder is not None

    def test_build_kind_30166_minimal(self, combined_harness: _CombinedHarness) -> None:
        """Test Kind 30166 event with no metadata results."""
        relay = Relay("wss://relay.example.com")
        result = _make_check_result()
        builder = combined_harness._build_kind_30166(relay, result)
        assert builder is not None

    def test_build_kind_30166_has_d_tag_and_network(self, tags_harness: _TagsHarness) -> None:
        """Test that Kind 30166 builder creates d-tag with relay URL and n-tag with network."""
        relay = Relay("wss://relay.example.com")
        result = _make_check_result()

        # Use the tags harness since _build_kind_30166 is on MonitorTagsMixin
        builder = tags_harness._build_kind_30166(relay, result)
        assert builder is not None

    def test_build_kind_30166_content_from_nip11(self, combined_harness: _CombinedHarness) -> None:
        """Test that Kind 30166 content contains NIP-11 canonical JSON when available."""
        relay = Relay("wss://relay.example.com")
        nip11 = _make_relay_metadata(
            "nip11_info",
            {
                "data": {"name": "Test Relay"},
                "logs": {"success": True},
            },
        )
        result = _make_check_result(nip11=nip11)
        # The builder should use nip11.metadata.canonical_json as content
        builder = combined_harness._build_kind_30166(relay, result)
        assert builder is not None

    def test_build_kind_30166_empty_content_when_no_nip11(
        self, combined_harness: _CombinedHarness
    ) -> None:
        """Test that Kind 30166 content is empty string when no NIP-11 data."""
        relay = Relay("wss://relay.example.com")
        result = _make_check_result()
        builder = combined_harness._build_kind_30166(relay, result)
        assert builder is not None

    def test_build_kind_30166_tor_relay_network_tag(
        self, combined_harness: _CombinedHarness
    ) -> None:
        """Test that Kind 30166 uses the correct network value for Tor relays."""
        onion = "a" * 56
        relay = Relay(f"ws://{onion}.onion")
        result = _make_check_result()
        builder = combined_harness._build_kind_30166(relay, result)
        assert builder is not None


# ============================================================================
# Integration-style: end-to-end tag generation
# ============================================================================


class TestEndToEndTagGeneration:
    """Integration-style tests verifying complete tag generation flows."""

    def test_full_relay_with_all_metadata(self, combined_harness: _CombinedHarness) -> None:
        """Test a relay with RTT, SSL, NIP-11 produces expected tag set."""
        nip11 = _make_relay_metadata(
            "nip11_info",
            {
                "data": {
                    "name": "Production Relay",
                    "supported_nips": [1, 11, 42, 50],
                    "tags": ["social"],
                    "language_tags": ["en", "de"],
                    "limitation": {
                        "auth_required": False,
                        "payment_required": False,
                        "restricted_writes": False,
                        "min_pow_difficulty": 0,
                    },
                },
                "logs": {"success": True},
            },
        )
        rtt = _make_relay_metadata(
            "nip66_rtt",
            {
                "data": {"rtt_open": 30, "rtt_read": 100, "rtt_write": 80},
                "logs": {"open_success": True, "write_success": True},
            },
        )
        ssl_meta = _make_relay_metadata(
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

        relay = Relay("wss://relay.example.com")
        result = _make_check_result(nip11=nip11, nip66_rtt=rtt, nip66_ssl=ssl_meta)
        builder = combined_harness._build_kind_30166(relay, result)
        assert builder is not None

    def test_auth_required_relay_types(self, tags_harness: _TagsHarness) -> None:
        """Test that auth-required relay gets PublicOutbox type."""
        rtt_rm = _make_relay_metadata(
            "nip66_rtt",
            {
                "data": {"rtt_open": 45},
                "logs": {"write_success": False, "write_reason": "auth-required: NIP-42"},
            },
        )
        result = _make_check_result(nip66_rtt=rtt_rm)
        nip11_data: dict[str, Any] = {"limitation": {"auth_required": True}}
        tags: list[Tag] = []
        tags_harness._add_requirement_and_type_tags(tags, result, nip11_data, None)

        pairs = _extract_tag_pairs(tags)
        assert ("R", "auth") in pairs
        assert ("T", "PublicOutbox") in pairs

    def test_payment_required_with_paid_write_reason(self, tags_harness: _TagsHarness) -> None:
        """Test payment detection from 'paid' keyword in write_reason."""
        rtt_rm = _make_relay_metadata(
            "nip66_rtt",
            {
                "data": {"rtt_open": 45},
                "logs": {"write_success": False, "write_reason": "paid relay only"},
            },
        )
        result = _make_check_result(nip66_rtt=rtt_rm)
        nip11_data: dict[str, Any] = {}
        tags: list[Tag] = []
        tags_harness._add_requirement_and_type_tags(tags, result, nip11_data, None)

        pairs = _extract_tag_pairs(tags)
        assert ("R", "payment") in pairs
        assert ("T", "Paid") in pairs
