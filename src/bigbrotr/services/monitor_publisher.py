"""Nostr event publishing for the Monitor service (Kind 0, 10166, 30166)."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

import asyncpg
from nostr_sdk import EventBuilder, Kind, RelayUrl, Tag
from nostr_sdk import Metadata as NostrMetadata

from bigbrotr.utils.transport import create_client

from .common.constants import EventKind, ServiceState, StateType


if TYPE_CHECKING:
    from bigbrotr.models import Relay

    from .monitor import CheckResult


class MonitorPublisherMixin:
    """Publishing methods for the Monitor service.

    Mixed into ``Monitor`` to provide Nostr event publishing without
    cluttering the main orchestration module.  All methods assume the host
    class provides ``self._config``, ``self._keys``, ``self._logger``, and
    ``self._brotr``.
    """

    # -------------------------------------------------------------------------
    # Publishing
    # -------------------------------------------------------------------------

    async def _broadcast_events(self, builders: list[EventBuilder], relays: list[Relay]) -> None:
        """Sign and broadcast multiple events to the specified relays."""
        if not builders or not relays:
            return

        client = create_client(self._keys)  # type: ignore[attr-defined]
        for relay in relays:
            await client.add_relay(RelayUrl.parse(relay.url))
        try:
            await client.connect()
            for builder in builders:
                await client.send_event_builder(builder)
        finally:
            await client.shutdown()

    def _get_discovery_relays(self) -> list[Relay]:
        """Get relays for Kind 30166 events (falls back to publishing.relays)."""
        return self._config.discovery.relays or self._config.publishing.relays  # type: ignore[attr-defined, no-any-return]

    def _get_announcement_relays(self) -> list[Relay]:
        """Get relays for Kind 10166 events (falls back to publishing.relays)."""
        return self._config.announcement.relays or self._config.publishing.relays  # type: ignore[attr-defined, no-any-return]

    def _get_profile_relays(self) -> list[Relay]:
        """Get relays for Kind 0 events (falls back to publishing.relays)."""
        return self._config.profile.relays or self._config.publishing.relays  # type: ignore[attr-defined, no-any-return]

    async def _publish_announcement(self) -> None:
        """Publish Kind 10166 monitor announcement if the configured interval has elapsed."""
        ann = self._config.announcement  # type: ignore[attr-defined]
        relays = self._get_announcement_relays()
        if not ann.enabled or not relays:
            return

        results = await self._brotr.get_service_state(  # type: ignore[attr-defined]
            self.SERVICE_NAME,  # type: ignore[attr-defined]
            StateType.CURSOR,
            "last_announcement",
        )
        last_announcement = results[0].get("payload", {}).get("timestamp", 0.0) if results else 0.0
        elapsed = time.time() - last_announcement
        if elapsed < ann.interval:
            return

        try:
            builder = self._build_kind_10166()
            await self._broadcast_events([builder], relays)
            self._logger.info("announcement_published", relays=len(relays))  # type: ignore[attr-defined]
            now = time.time()
            await self._brotr.upsert_service_state(  # type: ignore[attr-defined]
                [
                    ServiceState(
                        service_name=self.SERVICE_NAME,  # type: ignore[attr-defined]
                        state_type=StateType.CURSOR,
                        state_key="last_announcement",
                        payload={"timestamp": now},
                        updated_at=int(now),
                    )
                ]
            )
        except (TimeoutError, OSError, asyncpg.PostgresError) as e:
            self._logger.warning("announcement_failed", error=str(e))  # type: ignore[attr-defined]

    async def _publish_profile(self) -> None:
        """Publish Kind 0 profile metadata if the configured interval has elapsed."""
        profile = self._config.profile  # type: ignore[attr-defined]
        relays = self._get_profile_relays()
        if not profile.enabled or not relays:
            return

        results = await self._brotr.get_service_state(  # type: ignore[attr-defined]
            self.SERVICE_NAME,  # type: ignore[attr-defined]
            StateType.CURSOR,
            "last_profile",
        )
        last_profile = results[0].get("payload", {}).get("timestamp", 0.0) if results else 0.0
        elapsed = time.time() - last_profile
        if elapsed < profile.interval:
            return

        try:
            builder = self._build_kind_0()
            await self._broadcast_events([builder], relays)
            self._logger.info("profile_published", relays=len(relays))  # type: ignore[attr-defined]
            now = time.time()
            await self._brotr.upsert_service_state(  # type: ignore[attr-defined]
                [
                    ServiceState(
                        service_name=self.SERVICE_NAME,  # type: ignore[attr-defined]
                        state_type=StateType.CURSOR,
                        state_key="last_profile",
                        payload={"timestamp": now},
                        updated_at=int(now),
                    )
                ]
            )
        except (TimeoutError, OSError, asyncpg.PostgresError) as e:
            self._logger.warning("profile_failed", error=str(e))  # type: ignore[attr-defined]

    async def _publish_relay_discoveries(self, successful: list[tuple[Relay, CheckResult]]) -> None:
        """Publish Kind 30166 relay discovery events for each successful health check."""
        disc = self._config.discovery  # type: ignore[attr-defined]
        relays = self._get_discovery_relays()
        if not disc.enabled or not relays:
            return

        builders: list[EventBuilder] = []
        for relay, result in successful:
            try:
                builders.append(self._build_kind_30166(relay, result))  # type: ignore[attr-defined]
            except (ValueError, KeyError, TypeError) as e:
                self._logger.debug("build_30166_failed", url=relay.url, error=str(e))  # type: ignore[attr-defined]

        if builders:
            try:
                await self._broadcast_events(builders, relays)
                self._logger.debug("discoveries_published", count=len(builders))  # type: ignore[attr-defined]
            except (TimeoutError, OSError) as e:
                self._logger.warning(  # type: ignore[attr-defined]
                    "discoveries_broadcast_failed", count=len(builders), error=str(e)
                )

    # -------------------------------------------------------------------------
    # Event Builders
    # -------------------------------------------------------------------------

    def _build_kind_0(self) -> EventBuilder:
        """Build Kind 0 profile metadata event per NIP-01."""
        profile = self._config.profile  # type: ignore[attr-defined]
        profile_data: dict[str, str] = {}
        if profile.name:
            profile_data["name"] = profile.name
        if profile.about:
            profile_data["about"] = profile.about
        if profile.picture:
            profile_data["picture"] = profile.picture
        if profile.nip05:
            profile_data["nip05"] = profile.nip05
        if profile.website:
            profile_data["website"] = profile.website
        if profile.banner:
            profile_data["banner"] = profile.banner
        if profile.lud16:
            profile_data["lud16"] = profile.lud16
        return EventBuilder.metadata(NostrMetadata.from_json(json.dumps(profile_data)))

    def _build_kind_10166(self) -> EventBuilder:
        """Build Kind 10166 monitor announcement event per NIP-66."""
        timeout_ms = str(int(self._config.networks.clearnet.timeout * 1000))  # type: ignore[attr-defined]
        include = self._config.discovery.include  # type: ignore[attr-defined]

        tags = [Tag.parse(["frequency", str(int(self._config.interval))])]  # type: ignore[attr-defined]

        # Timeout tags per check type
        if include.nip66_rtt:
            tags.append(Tag.parse(["timeout", "open", timeout_ms]))
            tags.append(Tag.parse(["timeout", "read", timeout_ms]))
            tags.append(Tag.parse(["timeout", "write", timeout_ms]))
        if include.nip11_info:
            tags.append(Tag.parse(["timeout", "nip11", timeout_ms]))
        if include.nip66_ssl:
            tags.append(Tag.parse(["timeout", "ssl", timeout_ms]))
        if include.nip66_dns:
            tags.append(Tag.parse(["timeout", "dns", timeout_ms]))
        if include.nip66_http:
            tags.append(Tag.parse(["timeout", "http", timeout_ms]))

        # Check type tags (c)
        if include.nip66_rtt:
            tags.append(Tag.parse(["c", "open"]))
            tags.append(Tag.parse(["c", "read"]))
            tags.append(Tag.parse(["c", "write"]))
        if include.nip11_info:
            tags.append(Tag.parse(["c", "nip11"]))
        if include.nip66_ssl:
            tags.append(Tag.parse(["c", "ssl"]))
        if include.nip66_geo:
            tags.append(Tag.parse(["c", "geo"]))
        if include.nip66_net:
            tags.append(Tag.parse(["c", "net"]))
        if include.nip66_dns:
            tags.append(Tag.parse(["c", "dns"]))
        if include.nip66_http:
            tags.append(Tag.parse(["c", "http"]))

        return EventBuilder(Kind(EventKind.MONITOR_ANNOUNCEMENT), "").tags(tags)


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "MonitorPublisherMixin",
]
