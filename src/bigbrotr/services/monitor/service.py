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

    brotr = Brotr.from_yaml("deployments/bigbrotr/config/brotr.yaml")
    monitor = Monitor.from_yaml(
        "deployments/bigbrotr/config/services/monitor.yaml",
        brotr=brotr,
    )

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
from bigbrotr.services.common.mixins import ConcurrentStreamMixin, NetworkSemaphoresMixin
from bigbrotr.utils.http import download_bounded_file
from bigbrotr.utils.protocol import NostrClientManager, broadcast_events_detailed

from .checks import (
    MonitorCheckContext,
    MonitorCheckDependencies,
)
from .checks import (
    build_check_context as build_monitor_check_context,
)
from .checks import (
    build_check_dependencies as build_monitor_check_dependencies,
)
from .checks import (
    build_parallel_checks as build_monitor_parallel_checks,
)
from .checks import (
    check_relay as run_monitor_check_relay,
)
from .configs import MetadataFlags, MonitorConfig
from .geo import update_geo_databases as update_monitor_geo_databases
from .processing import (
    MonitorChunkContext,
    MonitorChunkPersistence,
    MonitorWorkerContext,
    log_chunk_outcome,
    monitor_chunk,
    monitor_worker,
    persist_chunk_outcome,
    start_monitor_progress,
)
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
from .resources import GeoReaders
from .runtime import (
    build_monitor_cycle_plan,
    close_cycle_resources,
    open_cycle_resources,
)
from .utils import (
    CheckResult,
    MonitorChunkOutcome,
    MonitorCyclePlan,
    MonitorProgress,
    retry_fetch,
)


if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator

    from nostr_sdk import Keys

    from bigbrotr.core.brotr import Brotr
    from bigbrotr.models import Relay


class Monitor(
    ConcurrentStreamMixin,
    NetworkSemaphoresMixin,
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
        )
        self._config: MonitorConfig
        self._keys: Keys = resolved_keys
        self.clients = NostrClientManager(
            keys=resolved_keys,
            networks=config.networks,
            allow_insecure=config.processing.allow_insecure,
        )

        async def publish_is_due(brotr: Brotr, key: str, interval: float) -> bool:
            return await is_publish_due(brotr, key, interval)

        async def publish_broadcast(events: list[Any], clients: list[Any]) -> list[Any]:
            return await broadcast_events_detailed(events, clients)

        async def publish_save_checkpoints(brotr: Brotr, keys: list[str]) -> None:
            await upsert_publish_checkpoints(brotr, keys)

        self._publish_context = PublishContext(
            brotr=self._brotr,
            config=self._config,
            clients=self.clients,
            logger=self._logger,
            is_due=publish_is_due,
            broadcast=publish_broadcast,
            save_checkpoints=publish_save_checkpoints,
        )
        self.geo_readers = GeoReaders()

    async def run(self) -> None:
        """Execute one complete monitoring cycle.

        Orchestrates setup, publishing, monitoring, and cleanup.
        Delegates the core work to ``update_geo_databases``,
        ``publish_profile``, ``publish_announcement``, and ``monitor``.

        Publish relay connections are established lazily on first use
        via ``clients.get_relay_client()`` and torn down in the ``finally``
        block.
        """
        await self._open_cycle_resources()

        try:
            await self.publish_profile()
            await self.publish_relay_list()
            await self.publish_announcement()
            await self.monitor()
        finally:
            await self._close_cycle_resources()

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

    async def _open_cycle_resources(self) -> None:
        """Prepare shared resources needed for one monitor cycle."""
        await open_cycle_resources(
            config=self._config,
            geo_readers=self.geo_readers,
            update_geo_databases_fn=self.update_geo_databases,
            open_geo_readers_fn=self.geo_readers.open,
        )

    async def _close_cycle_resources(self) -> None:
        """Release shared resources owned by one monitor cycle."""
        await close_cycle_resources(
            clients_disconnect_fn=self.clients.disconnect,
            geo_readers=self.geo_readers,
            close_geo_readers_fn=self.geo_readers.close,
        )

    async def publish_profile(self) -> None:
        """Publish Kind 0 profile metadata if the configured interval has elapsed."""
        await publish_monitor_profile(
            context=self._publish_context,
            build_profile=build_profile_event,
        )

    async def publish_relay_list(self) -> None:
        """Publish Kind 10002 relay list metadata if the configured interval has elapsed."""
        await publish_monitor_relay_list(
            context=self._publish_context,
            build_relay_list=build_relay_list_event,
        )

    async def publish_announcement(self) -> None:
        """Publish Kind 10166 monitor announcement if the configured interval has elapsed."""
        await publish_monitor_announcement(
            context=self._publish_context,
            build_announcement=build_monitor_announcement,
        )

    async def publish_discovery(self, relay: Relay, result: CheckResult) -> None:
        """Publish a Kind 30166 relay discovery event for a single relay.

        Resolves discovery publish relays from config, connects lazily
        via ``clients.get_relay_clients()``, builds the event, and broadcasts.

        Args:
            relay: The relay that was health-checked.
            result: Health check result containing metadata.
        """
        await publish_monitor_discovery(
            context=DiscoveryContext(
                config=self._config,
                clients=self.clients,
                logger=self._logger,
                broadcast=broadcast_events_detailed,
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
        return await run_monitor_check_relay(
            self._check_context(relay, generated_at=int(time.time())),
            self._check_dependencies(),
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
            self._check_context(
                relay,
                compute=compute,
                timeout=timeout,
                proxy_url=proxy_url,
                generated_at=0,
            ),
            self._check_dependencies(),
        )

    def _check_context(
        self,
        relay: Relay,
        *,
        generated_at: int,
        compute: MetadataFlags | None = None,
        timeout: float | None = None,
        proxy_url: str | None = None,
    ) -> MonitorCheckContext:
        """Build the shared per-relay monitor check context."""
        return build_monitor_check_context(
            relay=relay,
            compute=compute or self._config.processing.compute,
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
            generated_at=generated_at,
            networks=self._config.networks,
        )

    def _check_dependencies(self) -> MonitorCheckDependencies:
        """Build the shared check dependency bundle for monitor relay probes."""
        return build_monitor_check_dependencies(
            retry_fetch=retry_fetch,
            nip11_fetch=Nip11.fetch,
            rtt_probe=Nip66RttMetadata.probe,
            ssl_probe=Nip66SslMetadata.probe,
            geo_probe=Nip66GeoMetadata.probe,
            net_probe=Nip66NetMetadata.probe,
            dns_probe=Nip66DnsMetadata.probe,
            http_probe=Nip66HttpMetadata.probe,
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
        plan = await self._build_monitor_cycle_plan()
        if plan is None:
            return 0

        progress = self._start_monitor_progress(plan.total)
        self._logger.info("relays_available", total=plan.total)
        progress = await self._process_monitor_pages(plan, progress)
        return progress.processed

    async def _build_monitor_cycle_plan(
        self,
        *,
        now: int | None = None,
    ) -> MonitorCyclePlan | None:
        """Build the relay-selection plan for one monitor cycle."""
        if not self._config.networks.get_enabled_networks():
            self._logger.warning("no_networks_enabled")
            return None
        return await build_monitor_cycle_plan(
            brotr=self._brotr,
            config=self._config,
            network_semaphores=self.network_semaphores,
            now=now,
            count_relays_fn=count_relays_to_monitor,
        )

    async def _monitor_chunk(
        self,
        relays: list[Relay],
        plan: MonitorCyclePlan,
    ) -> MonitorChunkOutcome:
        """Run one page of relay checks and classify the results."""
        return await monitor_chunk(
            context=MonitorChunkContext(
                iter_concurrent=self._iter_concurrent,
                worker=self._monitor_worker,
                inc_gauge=self.inc_gauge,
            ),
            relays=relays,
            max_concurrency=plan.max_concurrency,
        )

    def _start_monitor_progress(self, total: int) -> MonitorProgress:
        """Initialize gauges and progress totals for one monitor cycle."""
        return start_monitor_progress(total=total, set_gauge=self.set_gauge)

    async def _process_monitor_pages(
        self,
        plan: MonitorCyclePlan,
        progress: MonitorProgress,
    ) -> MonitorProgress:
        """Process all eligible relay pages for one monitor cycle."""
        async for relays in self._iter_monitor_pages(plan):
            if not self.is_running:
                break

            progress = await self._process_monitor_page(
                relays,
                plan,
                progress,
            )

        return progress

    def _iter_monitor_pages(
        self,
        plan: MonitorCyclePlan,
    ) -> AsyncIterator[list[Relay]]:
        """Yield relay pages selected for one monitor cycle."""
        return iter_relays_to_monitor_pages(
            self._brotr,
            plan.monitored_before,
            list(plan.networks),
            page_size=plan.chunk_size,
            max_relays=plan.max_relays,
        )

    async def _process_monitor_page(
        self,
        relays: list[Relay],
        plan: MonitorCyclePlan,
        progress: MonitorProgress,
    ) -> MonitorProgress:
        """Process one relay page and return updated cycle progress."""
        chunk_outcome = await self._monitor_chunk(relays, plan)
        await self._persist_chunk_outcome(chunk_outcome, checked_at=int(time.time()))

        next_progress = progress.advance(chunk_outcome)
        self._log_chunk_outcome(
            chunk_outcome,
            total=next_progress.total,
            succeeded=next_progress.succeeded,
            failed=next_progress.failed,
        )
        return next_progress

    async def _persist_chunk_outcome(
        self,
        chunk_outcome: MonitorChunkOutcome,
        *,
        checked_at: int,
    ) -> None:
        """Persist one processed monitor chunk to metadata and service state."""
        await persist_chunk_outcome(
            context=MonitorChunkPersistence(
                brotr=self._brotr,
                store=self._config.processing.store,
                insert_relay_metadata=insert_relay_metadata,
                upsert_monitor_checkpoints=upsert_monitor_checkpoints,
            ),
            chunk_outcome=chunk_outcome,
            checked_at=checked_at,
        )

    def _log_chunk_outcome(
        self,
        chunk_outcome: MonitorChunkOutcome,
        *,
        total: int,
        succeeded: int,
        failed: int,
    ) -> None:
        """Emit the standard monitor chunk completion log line."""
        log_chunk_outcome(
            logger=self._logger,
            chunk_outcome=chunk_outcome,
            total=total,
            succeeded=succeeded,
            failed=failed,
        )

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
        async for item in monitor_worker(
            context=MonitorWorkerContext(
                network_semaphores=self.network_semaphores,
                logger=self._logger,
                check_relay=self.check_relay,
                publish_discovery=self.publish_discovery,
            ),
            relay=relay,
        ):
            yield item
