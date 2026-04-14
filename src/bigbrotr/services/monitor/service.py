"""Monitor service for relay health monitoring with NIP-66 compliance.

Performs comprehensive health checks on relays and stores results as
content-addressed [Metadata][bigbrotr.models.metadata.Metadata]. Optionally
publishes Kind 30166 relay discovery events and Kind 10166 monitor
announcements to the Nostr network.

Health checks include:

- [Nip11InfoMetadata][bigbrotr.nips.nip11.Nip11InfoMetadata]: Relay info document (name,
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

import time
from typing import TYPE_CHECKING, Any, ClassVar

from bigbrotr.core.base_service import BaseService
from bigbrotr.models.constants import ServiceName
from bigbrotr.nips.event_builders import (
    build_monitor_announcement,
    build_profile_event,
    build_relay_discovery,
    build_relay_list_event,
)
from bigbrotr.nips.nip11 import Nip11
from bigbrotr.nips.nip66 import (
    Nip66DnsMetadata,
    Nip66GeoMetadata,
    Nip66HttpMetadata,
    Nip66NetMetadata,
    Nip66RttMetadata,
    Nip66SslMetadata,
)
from bigbrotr.services.common.mixins import (
    Clients,
    ClientsMixin,
    ConcurrentStreamMixin,
    GeoReaderMixin,
    NetworkSemaphoresMixin,
)
from bigbrotr.utils.http import download_bounded_file
from bigbrotr.utils.protocol import broadcast_events

from .checks import (
    MonitorCheckContext,
    MonitorCheckDependencies,
)
from .checks import (
    build_parallel_checks as build_monitor_parallel_checks,
)
from .checks import (
    check_relay as run_monitor_check_relay,
)
from .configs import MetadataFlags, MonitorConfig
from .geo import update_geo_databases as update_monitor_geo_databases
from .publishing import (
    DiscoveryContext,
    PublishContext,
)
from .publishing import (
    publish_announcement as publish_monitor_announcement,
)
from .publishing import (
    publish_discovery as publish_monitor_discovery,
)
from .publishing import (
    publish_profile as publish_monitor_profile,
)
from .publishing import (
    publish_relay_list as publish_monitor_relay_list,
)
from .queries import (
    count_relays_to_monitor,
    delete_stale_checkpoints,
    insert_relay_metadata,
    is_publish_due,
    iter_relays_to_monitor_pages,
    upsert_monitor_checkpoints,
    upsert_publish_checkpoints,
)
from .utils import (
    CheckResult,
    collect_metadata,
    retry_fetch,
)


if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from nostr_sdk import Keys

    from bigbrotr.core.brotr import Brotr
    from bigbrotr.models import Relay


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
        resolved_keys = config.keys.keys
        super().__init__(
            brotr=brotr,
            config=config,
            networks=config.networks,
            clients=Clients(
                keys=resolved_keys,
                networks=config.networks,
                allow_insecure=config.processing.allow_insecure,
            ),
        )
        self._config: MonitorConfig
        self._keys: Keys = resolved_keys

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
            await self.publish_relay_list()
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
        if self._config.relay_list.enabled:
            keep_keys.append("relay_list")
        return await delete_stale_checkpoints(self._brotr, keep_keys)

    async def update_geo_databases(self) -> None:
        """Download or re-download GeoLite2 databases if missing or stale.

        Download failures are logged and suppressed so that a transient
        network error does not prevent the monitor cycle from proceeding
        with a stale (or missing) database.
        """
        await update_monitor_geo_databases(
            config=self._config,
            logger=self._logger,
            download=download_bounded_file,
        )

    async def publish_profile(self) -> None:
        """Publish Kind 0 profile metadata if the configured interval has elapsed."""
        await publish_monitor_profile(
            context=PublishContext(
                brotr=self._brotr,
                config=self._config,
                clients=self.clients,
                logger=self._logger,
                is_due=is_publish_due,
                broadcast=broadcast_events,
                save_checkpoints=upsert_publish_checkpoints,
            ),
            build_profile=build_profile_event,
        )

    async def publish_relay_list(self) -> None:
        """Publish Kind 10002 relay list metadata if the configured interval has elapsed."""
        await publish_monitor_relay_list(
            context=PublishContext(
                brotr=self._brotr,
                config=self._config,
                clients=self.clients,
                logger=self._logger,
                is_due=is_publish_due,
                broadcast=broadcast_events,
                save_checkpoints=upsert_publish_checkpoints,
            ),
            build_relay_list=build_relay_list_event,
        )

    async def publish_announcement(self) -> None:
        """Publish Kind 10166 monitor announcement if the configured interval has elapsed."""
        await publish_monitor_announcement(
            context=PublishContext(
                brotr=self._brotr,
                config=self._config,
                clients=self.clients,
                logger=self._logger,
                is_due=is_publish_due,
                broadcast=broadcast_events,
                save_checkpoints=upsert_publish_checkpoints,
            ),
            build_announcement=build_monitor_announcement,
        )

    async def publish_discovery(self, relay: Relay, result: CheckResult) -> None:
        """Publish a Kind 30166 relay discovery event for a single relay.

        Resolves discovery publish relays from config, connects lazily
        via ``clients.get_many()``, builds the event, and broadcasts.

        Args:
            relay: The relay that was health-checked.
            result: Health check result containing metadata.
        """
        await publish_monitor_discovery(
            context=DiscoveryContext(
                config=self._config,
                clients=self.clients,
                logger=self._logger,
                broadcast=broadcast_events,
            ),
            relay=relay,
            result=result,
            build_discovery=build_relay_discovery,
        )

    async def check_relay(self, relay: Relay) -> CheckResult:
        """Perform all configured health checks on a single relay.

        Runs NIP-11, RTT, SSL, DNS, geo, net, and HTTP checks as configured.
        The caller is responsible for acquiring the per-network semaphore.

        Note:
            NIP-11 is fetched first because the RTT write-test may need
            the ``min_pow_difficulty`` from NIP-11's ``limitation`` object
            to apply proof-of-work on the test event. All other checks
            (SSL, DNS, Geo, Net, HTTP) run in parallel after NIP-11 and RTT.

        Returns:
            [CheckResult][bigbrotr.services.monitor.CheckResult] with
            metadata for each completed check (``None`` if skipped/failed).
        """
        network_config = self._config.networks.get(relay.network)
        proxy_url = self._config.networks.get_proxy_url(relay.network)
        return await run_monitor_check_relay(
            MonitorCheckContext(
                relay=relay,
                compute=self._config.processing.compute,
                timeout=network_config.timeout,
                proxy_url=proxy_url,
                allow_insecure=self._config.processing.allow_insecure,
                nip11_info_max_size=self._config.processing.nip11_info_max_size,
                retries=self._config.processing.retries,
                geohash_precision=self._config.geo.geohash_precision,
                keys=self._keys,
                city_reader=self.geo_readers.city,
                asn_reader=self.geo_readers.asn,
                logger=self._logger,
                wait=self.wait,
                generated_at=int(time.time()),
            ),
            MonitorCheckDependencies(
                retry_fetch=retry_fetch,
                nip11_fetch=Nip11.fetch,
                rtt_probe=Nip66RttMetadata.probe,
                ssl_probe=Nip66SslMetadata.probe,
                geo_probe=Nip66GeoMetadata.probe,
                net_probe=Nip66NetMetadata.probe,
                dns_probe=Nip66DnsMetadata.probe,
                http_probe=Nip66HttpMetadata.probe,
            ),
        )

    def _build_parallel_checks(
        self,
        relay: Relay,
        compute: MetadataFlags,
        timeout: float,
        proxy_url: str | None,
    ) -> dict[str, Any]:
        """Build a dict of coroutines for independent health checks.

        Each entry maps a check name to a retry-wrapped coroutine. Only
        checks that are enabled in ``compute`` and applicable to the
        relay's network type are included.
        """
        return build_monitor_parallel_checks(
            MonitorCheckContext(
                relay=relay,
                compute=compute,
                timeout=timeout,
                proxy_url=proxy_url,
                allow_insecure=self._config.processing.allow_insecure,
                nip11_info_max_size=self._config.processing.nip11_info_max_size,
                retries=self._config.processing.retries,
                geohash_precision=self._config.geo.geohash_precision,
                keys=self._keys,
                city_reader=self.geo_readers.city,
                asn_reader=self.geo_readers.asn,
                logger=self._logger,
                wait=self.wait,
                generated_at=0,
            ),
            MonitorCheckDependencies(
                retry_fetch=retry_fetch,
                nip11_fetch=Nip11.fetch,
                rtt_probe=Nip66RttMetadata.probe,
                ssl_probe=Nip66SslMetadata.probe,
                geo_probe=Nip66GeoMetadata.probe,
                net_probe=Nip66NetMetadata.probe,
                dns_probe=Nip66DnsMetadata.probe,
                http_probe=Nip66HttpMetadata.probe,
            ),
        )

    async def monitor(self) -> int:
        """Check, persist, and publish all pending relays.

        Fetches relays in pages (``chunk_size``), checks each page
        concurrently via ``_iter_concurrent()``, persists results
        at each pagination boundary, and publishes Kind 30166
        discovery events per successful check.

        Returns:
            Total number of relays processed (succeeded + failed).
        """
        networks = self._config.networks.get_enabled_networks()
        if not networks:
            self._logger.warning("no_networks_enabled")
            return 0

        monitored_before = int(time.time() - self._config.discovery.interval)
        max_relays = self._config.processing.max_relays

        total = await count_relays_to_monitor(self._brotr, monitored_before, networks)
        if max_relays is not None:
            total = min(total, max_relays)
        succeeded = 0
        failed = 0

        self.set_gauge("total", total)
        self.set_gauge("succeeded", 0)
        self.set_gauge("failed", 0)

        self._logger.info("relays_available", total=total)

        chunk_size = self._config.processing.chunk_size

        async for relays in iter_relays_to_monitor_pages(
            self._brotr,
            monitored_before,
            networks,
            page_size=chunk_size,
            max_relays=max_relays,
        ):
            if not self.is_running:
                break

            chunk_successful: list[tuple[Relay, CheckResult]] = []
            chunk_failed: list[Relay] = []

            async for relay, result in self._iter_concurrent(
                relays,
                self._monitor_worker,
                max_concurrency=self.network_semaphores.max_concurrency(networks),
            ):
                if result is not None:
                    chunk_successful.append((relay, result))
                    succeeded += 1
                else:
                    chunk_failed.append(relay)
                    failed += 1
                self.inc_gauge("succeeded" if result is not None else "failed")

            metadata = collect_metadata(chunk_successful, self._config.processing.store)
            await insert_relay_metadata(self._brotr, metadata)
            all_checked = [relay for relay, _ in chunk_successful] + chunk_failed
            await upsert_monitor_checkpoints(self._brotr, all_checked, int(time.time()))

            self._logger.info(
                "chunk_completed",
                succeeded=len(chunk_successful),
                failed=len(chunk_failed),
                remaining=total - succeeded - failed,
            )

        return succeeded + failed

    async def _monitor_worker(
        self, relay: Relay
    ) -> AsyncGenerator[tuple[Relay, CheckResult | None], None]:
        """Health-check a single relay for use with ``_iter_concurrent``.

        Acquires the per-network semaphore, runs all configured checks,
        publishes a Kind 30166 discovery event for successful results,
        and yields ``(relay, result)`` or ``(relay, None)`` on failure.
        Yields exactly once — never raises, so every relay produces a
        result for the caller to classify.
        """
        try:
            semaphore = self.network_semaphores.get(relay.network)
            if semaphore is None:
                self._logger.warning("unknown_network", url=relay.url, network=relay.network.value)
                yield relay, None
                return

            async with semaphore:
                result = await self.check_relay(relay)
                if not result.has_data:
                    yield relay, None
                    return
                await self.publish_discovery(relay, result)
                yield relay, result
        except Exception as e:  # Worker exception boundary — protects TaskGroup
            self._logger.error(
                "check_relay_failed",
                error=str(e),
                error_type=type(e).__name__,
                relay=relay.url,
            )
            yield relay, None
