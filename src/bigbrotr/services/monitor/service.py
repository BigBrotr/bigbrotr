"""Monitor service for relay health monitoring with NIP-66 compliance.

Performs comprehensive health checks on relays and stores results as
content-addressed [Metadata][bigbrotr.models.metadata.Metadata]. Optionally
publishes Kind 30166 relay discovery events and Kind 10166 monitor
announcements to the Nostr network.

Health checks include:

- [Nip11][bigbrotr.nips.nip11.Nip11]: Relay info document (name,
  description, pubkey, supported NIPs).
- [Nip66RttMetadata][bigbrotr.nips.nip66.Nip66RttMetadata]: Open/read/write
  round-trip times in milliseconds.
- [Nip66SslMetadata][bigbrotr.nips.nip66.Nip66SslMetadata]: SSL certificate
  validation (clearnet only).
- [Nip66DnsMetadata][bigbrotr.nips.nip66.Nip66DnsMetadata]: DNS hostname
  resolution (clearnet only).
- [Nip66GeoMetadata][bigbrotr.nips.nip66.Nip66GeoMetadata]: IP geolocation
  (clearnet only).
- [Nip66NetMetadata][bigbrotr.nips.nip66.Nip66NetMetadata]: ASN/organization
  info (clearnet only).
- [Nip66HttpMetadata][bigbrotr.nips.nip66.Nip66HttpMetadata]: HTTP status
  codes and headers.

Note:
    Event building is delegated to [bigbrotr.nips.event_builders][bigbrotr.nips.event_builders]
    and broadcasting to [bigbrotr.utils.protocol][bigbrotr.utils.protocol]. The Monitor handles
    orchestration: when to publish, which data to extract from
    [CheckResult][bigbrotr.services.monitor.CheckResult], and lifecycle
    management of publishing intervals via service state markers.

See Also:
    [MonitorConfig][bigbrotr.services.monitor.MonitorConfig]: Configuration
        model for networks, processing, geo, publishing, and discovery.
    [BaseService][bigbrotr.core.base_service.BaseService]: Abstract base
        class providing ``run()``, ``run_forever()``, and ``from_yaml()``.
    [Brotr][bigbrotr.core.brotr.Brotr]: Database facade used for metadata
        persistence and state management.
    [Validator][bigbrotr.services.validator.Validator]: Upstream service
        that promotes candidates to the ``relay`` table.

Examples:
    ```python
    from bigbrotr.core import Brotr
    from bigbrotr.services import Monitor

    brotr = Brotr.from_yaml("config/brotr.yaml")
    monitor = Monitor.from_yaml("config/services/monitor.yaml", brotr=brotr)

    async with brotr:
        async with monitor:
            await monitor.run_forever()
    ```
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from bigbrotr.core.base_service import BaseService
from bigbrotr.models import Metadata, MetadataType
from bigbrotr.models.constants import NetworkType, ServiceName
from bigbrotr.nips.event_builders import (
    build_monitor_announcement,
    build_profile_event,
    build_relay_discovery,
)
from bigbrotr.nips.nip11 import Nip11Selection
from bigbrotr.nips.nip66 import Nip66Selection
from bigbrotr.services.common.mixins import (
    ClientsMixin,
    ConcurrentStreamMixin,
    GeoReaderMixin,
    NetworkSemaphoresMixin,
)
from bigbrotr.utils.http import download_bounded_file
from bigbrotr.utils.protocol import broadcast_events

from .configs import MonitorConfig
from .queries import (
    count_relays_to_monitor,
    delete_stale_checkpoints,
    fetch_relays_to_monitor,
    is_publish_due,
    save_publish_checkpoint,
)
from .utils import (
    CheckResult,
    check_relay,
    flush_results,
    get_publish_relays,
)


if TYPE_CHECKING:
    from bigbrotr.core.brotr import Brotr
    from bigbrotr.models import Relay

_SECONDS_PER_DAY = 86_400


class Monitor(
    ConcurrentStreamMixin,
    NetworkSemaphoresMixin,
    GeoReaderMixin,
    ClientsMixin,
    BaseService[MonitorConfig],
):
    """Relay health monitoring service with NIP-66 compliance.

    Performs comprehensive health checks on relays and stores results as
    content-addressed [Metadata][bigbrotr.models.metadata.Metadata].
    Optionally publishes NIP-66 events:

    - **Kind 10166**: Monitor announcement (capabilities, frequency, timeouts).
    - **Kind 30166**: Per-relay discovery event (RTT, SSL, geo, NIP-11 tags).

    Each cycle updates GeoLite2 databases, publishes profile/announcement
    events if due, fetches relays needing checks, processes them in chunks
    with per-network semaphores, persists metadata results, and publishes
    Kind 30166 discovery events. Supports clearnet (direct), Tor, I2P,
    and Lokinet (via SOCKS5 proxy).

    Event building is delegated to [bigbrotr.nips.event_builders][bigbrotr.nips.event_builders]
    and broadcasting to [bigbrotr.utils.protocol][bigbrotr.utils.protocol].

    See Also:
        [MonitorConfig][bigbrotr.services.monitor.MonitorConfig]:
            Configuration model for this service.
        [Validator][bigbrotr.services.validator.Validator]: Upstream
            service that promotes candidates to the ``relay`` table.
        [Synchronizer][bigbrotr.services.synchronizer.Synchronizer]:
            Downstream service that collects events from monitored relays.
    """

    SERVICE_NAME: ClassVar[ServiceName] = ServiceName.MONITOR
    CONFIG_CLASS: ClassVar[type[MonitorConfig]] = MonitorConfig

    def __init__(self, brotr: Brotr, config: MonitorConfig | None = None) -> None:
        config = config or MonitorConfig()
        super().__init__(brotr=brotr, config=config, networks=config.networks)
        self._config: MonitorConfig
        self._keys = self._config.keys.keys

    async def run(self) -> None:
        """Execute one complete monitoring cycle.

        Orchestrates setup, publishing, monitoring, and cleanup.
        Delegates the core work to ``update_geo_databases``,
        ``publish_profile``, ``publish_announcement``, and ``monitor``.

        Publish relay connections are established lazily on first use
        via ``clients.get()`` and torn down in the ``finally``
        block.
        """
        await self.update_geo_databases()

        compute = self._config.processing.compute
        await self.geo_readers.open(
            city_path=self._config.geo.city_database_path if compute.nip66_geo else None,
            asn_path=self._config.geo.asn_database_path if compute.nip66_net else None,
        )

        try:
            await self.publish_profile()
            await self.publish_announcement()
            await self.monitor()
        finally:
            await self.clients.disconnect()
            self.geo_readers.close()

    async def cleanup(self) -> int:
        """Remove stale relay checkpoints and orphaned publishing state."""
        keep_keys: list[str] = []
        if self._config.announcement.enabled:
            keep_keys.append("announcement")
        if self._config.profile.enabled:
            keep_keys.append("profile")
        return await delete_stale_checkpoints(self._brotr, keep_keys)

    async def update_geo_databases(self) -> None:
        """Download or re-download GeoLite2 databases if missing or stale.

        Download failures are logged and suppressed so that a transient
        network error does not prevent the monitor cycle from proceeding
        with a stale (or missing) database.
        """
        compute = self._config.processing.compute
        geo = self._config.geo
        max_age_days = geo.max_age_days

        updates: list[tuple[Path, str, str]] = []
        if compute.nip66_geo:
            updates.append((Path(geo.city_database_path), geo.city_download_url, "city"))
        if compute.nip66_net:
            updates.append((Path(geo.asn_database_path), geo.asn_download_url, "asn"))

        for path, url, name in updates:
            try:
                if await asyncio.to_thread(path.exists):
                    if max_age_days is None:
                        continue
                    age = time.time() - (await asyncio.to_thread(path.stat)).st_mtime
                    if age <= max_age_days * _SECONDS_PER_DAY:
                        continue
                    self._logger.info(
                        "updating_geo_db",
                        db=name,
                        age_days=round(age / _SECONDS_PER_DAY, 1),
                    )
                else:
                    self._logger.info("downloading_geo_db", db=name)
                await download_bounded_file(url, path, geo.max_download_size)
            except (OSError, ValueError) as e:
                self._logger.warning("geo_db_update_failed", db=name, error=str(e))

    async def publish_profile(self) -> None:
        """Publish Kind 0 profile metadata if the configured interval has elapsed."""
        cfg = self._config.profile
        if not cfg.enabled:
            return

        relays = get_publish_relays(cfg.relays, self._config.publishing.relays)
        if not relays:
            return

        if not await is_publish_due(self._brotr, "profile", cfg.interval):
            return

        clients = await self.clients.get_many(relays)
        if not clients:
            self._logger.warning("publish_failed", event="profile", error="no relays reachable")
            return

        sent = await broadcast_events(
            [
                build_profile_event(
                    name=cfg.name,
                    about=cfg.about,
                    picture=cfg.picture,
                    nip05=cfg.nip05,
                    website=cfg.website,
                    banner=cfg.banner,
                    lud16=cfg.lud16,
                ),
            ],
            clients,
        )
        if not sent:
            self._logger.warning("publish_failed", event="profile", error="no relays reachable")
            return

        self._logger.info("publish_completed", event="profile", relays=sent)
        await save_publish_checkpoint(self._brotr, "profile")

    async def publish_announcement(self) -> None:
        """Publish Kind 10166 monitor announcement if the configured interval has elapsed."""
        cfg = self._config.announcement
        if not cfg.enabled:
            return

        relays = get_publish_relays(cfg.relays, self._config.publishing.relays)
        if not relays:
            return

        if not await is_publish_due(self._brotr, "announcement", cfg.interval):
            return

        include = cfg.include
        enabled_networks = [
            network for network in NetworkType if self._config.networks.is_enabled(network)
        ]
        first_network = enabled_networks[0] if enabled_networks else NetworkType.CLEARNET
        timeout_ms = int(self._config.networks.get(first_network).timeout * 1000)

        clients = await self.clients.get_many(relays)
        if not clients:
            self._logger.warning(
                "publish_failed", event="announcement", error="no relays reachable"
            )
            return

        sent = await broadcast_events(
            [
                build_monitor_announcement(
                    interval=int(self._config.interval),
                    timeout_ms=timeout_ms,
                    enabled_networks=enabled_networks,
                    nip11_selection=Nip11Selection(info=include.nip11_info),
                    nip66_selection=Nip66Selection(
                        rtt=include.nip66_rtt,
                        ssl=include.nip66_ssl,
                        geo=include.nip66_geo,
                        net=include.nip66_net,
                        dns=include.nip66_dns,
                        http=include.nip66_http,
                    ),
                ),
            ],
            clients,
        )
        if not sent:
            self._logger.warning(
                "publish_failed", event="announcement", error="no relays reachable"
            )
            return

        self._logger.info("publish_completed", event="announcement", relays=sent)
        await save_publish_checkpoint(self._brotr, "announcement")

    async def publish_discovery(self, relay: Relay, result: CheckResult) -> None:
        """Publish a Kind 30166 relay discovery event for a single relay.

        Resolves discovery publish relays from config, connects lazily
        via ``clients.get_many()``, builds the event, and broadcasts.

        Args:
            relay: The relay that was health-checked.
            result: Health check result containing metadata.
        """
        cfg = self._config.discovery
        if not cfg.enabled:
            return

        relays = get_publish_relays(cfg.relays, self._config.publishing.relays)
        if not relays:
            return

        clients = await self.clients.get_many(relays)
        if not clients:
            return

        include = cfg.include
        try:
            nip11_canonical_json = ""
            if result.nip11 and include.nip11_info:
                meta = Metadata(type=MetadataType.NIP11_INFO, data=result.nip11.to_dict())
                nip11_canonical_json = meta.canonical_json

            builder = build_relay_discovery(
                relay.url,
                relay.network.value,
                nip11_canonical_json,
                rtt_data=result.nip66_rtt.data if result.nip66_rtt and include.nip66_rtt else None,
                ssl_data=result.nip66_ssl.data if result.nip66_ssl and include.nip66_ssl else None,
                net_data=result.nip66_net.data if result.nip66_net and include.nip66_net else None,
                geo_data=result.nip66_geo.data if result.nip66_geo and include.nip66_geo else None,
                nip11_data=result.nip11.data if result.nip11 and include.nip11_info else None,
                rtt_logs=result.nip66_rtt.logs if result.nip66_rtt else None,
            )
        except (ValueError, KeyError, TypeError) as e:
            self._logger.debug("build_30166_failed", url=relay.url, error=str(e))
            return

        sent = await broadcast_events([builder], clients)
        if not sent:
            self._logger.debug("discovery_broadcast_failed", url=relay.url)

    async def monitor(self) -> int:
        """Check, persist, and publish all pending relays.

        Fetches relays in pages (``chunk_size``), checks each page
        concurrently via ``_iter_concurrent()``, and flushes results
        at each pagination boundary. Discovery events are published
        per-result as they complete.

        Returns:
            Total number of relays processed (succeeded + failed).
        """
        networks = self._config.networks.get_enabled_networks()
        if not networks:
            self._logger.warning("no_networks_enabled")
            return 0

        monitored_before = int(time.time() - self._config.discovery.interval)

        total = await count_relays_to_monitor(self._brotr, monitored_before, networks)
        succeeded = 0
        failed = 0

        self.set_gauge("total", total)
        self.set_gauge("succeeded", succeeded)
        self.set_gauge("failed", failed)

        self._logger.info("relays_available", total=total)

        chunk_size = self._config.processing.chunk_size
        max_relays = self._config.processing.max_relays

        while self.is_running:
            if max_relays is not None:
                budget = max_relays - succeeded - failed
                if budget <= 0:
                    break
                limit = min(chunk_size, budget)
            else:
                limit = chunk_size

            relays = await fetch_relays_to_monitor(self._brotr, monitored_before, networks, limit)
            if not relays:
                break

            chunk_successful: list[tuple[Relay, CheckResult]] = []
            chunk_failed: list[Relay] = []

            async for relay, result in self._iter_concurrent(relays, self._monitoring_worker):
                if result is not None:
                    chunk_successful.append((relay, result))
                    succeeded += 1
                    await self.publish_discovery(relay, result)
                else:
                    chunk_failed.append(relay)
                    failed += 1
                self.set_gauge("succeeded", succeeded)
                self.set_gauge("failed", failed)

            await flush_results(self, chunk_successful, chunk_failed, total - succeeded - failed)

        return succeeded + failed

    async def _monitoring_worker(self, relay: Relay) -> tuple[Relay, CheckResult | None]:
        """Health-check a single relay for use with ``_iter_concurrent``.

        Returns ``(relay, result)`` when the check produces data, or
        ``(relay, None)`` on failure or exception.
        """
        try:
            result = await check_relay(self, relay)
            return (relay, result) if result.has_data else (relay, None)
        except Exception as e:  # Worker exception boundary — protects TaskGroup
            self._logger.error(
                "check_relay_failed",
                error=str(e),
                error_type=type(e).__name__,
                relay=relay.url,
            )
            return relay, None
