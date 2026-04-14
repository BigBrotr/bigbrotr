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

import asyncio
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from nostr_sdk import EventBuilder, Filter, Kind, Tag

from bigbrotr.core.base_service import BaseService
from bigbrotr.models.constants import EventKind, NetworkType, ServiceName
from bigbrotr.nips.event_builders import (
    build_monitor_announcement,
    build_profile_event,
    build_relay_discovery,
    build_relay_list_event,
)
from bigbrotr.nips.nip11 import Nip11, Nip11Options, Nip11Selection
from bigbrotr.nips.nip66 import (
    Nip66,
    Nip66DnsMetadata,
    Nip66GeoMetadata,
    Nip66HttpMetadata,
    Nip66NetMetadata,
    Nip66RttDependencies,
    Nip66RttMetadata,
    Nip66Selection,
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

from .configs import MetadataFlags, MonitorConfig
from .queries import (
    delete_stale_checkpoints,
    fetch_relays_to_monitor,
    insert_relay_metadata,
    is_publish_due,
    upsert_monitor_checkpoints,
    upsert_publish_checkpoints,
)
from .utils import (
    CheckResult,
    collect_metadata,
    extract_result,
    retry_fetch,
)


if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from nostr_sdk import Keys

    from bigbrotr.core.brotr import Brotr
    from bigbrotr.models import Relay
    from bigbrotr.nips.nip11.info import Nip11InfoMetadata

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

        relays = cfg.relays if cfg.relays is not None else self._config.publishing.relays
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
        await upsert_publish_checkpoints(self._brotr, ["profile"])

    async def publish_relay_list(self) -> None:
        """Publish Kind 10002 relay list metadata if the configured interval has elapsed."""
        cfg = self._config.relay_list
        if not cfg.enabled:
            return

        relays = cfg.relays if cfg.relays is not None else self._config.publishing.relays
        if not relays:
            return

        if not await is_publish_due(self._brotr, "relay_list", cfg.interval):
            return

        clients = await self.clients.get_many(relays)
        if not clients:
            self._logger.warning("publish_failed", event="relay_list", error="no relays reachable")
            return

        sent = await broadcast_events([build_relay_list_event(relays)], clients)
        if not sent:
            self._logger.warning("publish_failed", event="relay_list", error="no relays reachable")
            return

        self._logger.info("publish_completed", event="relay_list", relays=sent)
        await upsert_publish_checkpoints(self._brotr, ["relay_list"])

    async def publish_announcement(self) -> None:
        """Publish Kind 10166 monitor announcement if the configured interval has elapsed."""
        cfg = self._config.announcement
        if not cfg.enabled:
            return

        relays = cfg.relays if cfg.relays is not None else self._config.publishing.relays
        if not relays:
            return

        if not await is_publish_due(self._brotr, "announcement", cfg.interval):
            return

        include = cfg.include
        enabled_networks = self._config.networks.get_enabled_networks()
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
                    interval=int(self._config.discovery.interval),
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
                    geohash=cfg.geohash,
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
        await upsert_publish_checkpoints(self._brotr, ["announcement"])

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

        relays = cfg.relays if cfg.relays is not None else self._config.publishing.relays
        if not relays:
            return

        clients = await self.clients.get_many(relays)
        if not clients:
            return

        include = cfg.include
        try:
            nip11 = Nip11(
                relay=relay,
                info=result.nip11_info if include.nip11_info else None,
            )
            nip66 = Nip66(
                relay=relay,
                rtt=result.nip66_rtt if include.nip66_rtt else None,
                ssl=result.nip66_ssl if include.nip66_ssl else None,
                geo=result.nip66_geo if include.nip66_geo else None,
                net=result.nip66_net if include.nip66_net else None,
                dns=result.nip66_dns if include.nip66_dns else None,
                http=result.nip66_http if include.nip66_http else None,
            )
            builder = build_relay_discovery(relay, nip11, nip66)
        except (ValueError, KeyError, TypeError) as e:
            self._logger.debug("build_30166_failed", url=relay.url, error=str(e))
            return

        sent = await broadcast_events([builder], clients)
        if not sent:
            self._logger.debug("discovery_broadcast_failed", url=relay.url)

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
        empty = CheckResult()

        network_config = self._config.networks.get(relay.network)
        proxy_url = self._config.networks.get_proxy_url(relay.network)
        timeout = network_config.timeout
        compute = self._config.processing.compute

        nip11_info: Nip11InfoMetadata | None = None
        generated_at = int(time.time())

        try:
            if compute.nip11_info:

                async def _fetch_nip11() -> Nip11InfoMetadata | None:
                    return (
                        await Nip11.fetch(
                            relay,
                            timeout=timeout,
                            proxy_url=proxy_url,
                            options=Nip11Options(
                                allow_insecure=self._config.processing.allow_insecure,
                                max_size=self._config.processing.nip11_info_max_size,
                            ),
                        )
                    ).info

                nip11_info = await retry_fetch(
                    relay,
                    _fetch_nip11,
                    self._config.processing.retries.nip11_info,
                    "nip11_info",
                    wait=self.wait,
                )

            rtt_meta: Nip66RttMetadata | None = None

            # RTT test: open/read/write round-trip times
            if compute.nip66_rtt:
                event_builder = EventBuilder(Kind(EventKind.NIP66_TEST), "nip66-test").tags(
                    [Tag.identifier(relay.url)]
                )
                # Apply proof-of-work if NIP-11 specifies minimum difficulty
                if nip11_info and nip11_info.succeeded:
                    pow_difficulty = nip11_info.data.limitation.min_pow_difficulty
                    if pow_difficulty and pow_difficulty > 0:
                        event_builder = event_builder.pow(pow_difficulty)
                read_filter = Filter().limit(1)
                rtt_deps = Nip66RttDependencies(
                    keys=self._keys,
                    event_builder=event_builder,
                    read_filter=read_filter,
                )
                rtt_meta = await retry_fetch(
                    relay,
                    lambda: Nip66RttMetadata.probe(
                        relay,
                        rtt_deps,
                        timeout,
                        proxy_url,
                        allow_insecure=self._config.processing.allow_insecure,
                    ),
                    self._config.processing.retries.nip66_rtt,
                    "nip66_rtt",
                    wait=self.wait,
                )

            # Run independent checks (SSL, DNS, Geo, Net, HTTP) in parallel
            parallel_tasks = self._build_parallel_checks(relay, compute, timeout, proxy_url)

            gathered: dict[str, Any] = {}
            if parallel_tasks:
                parallel_results = await asyncio.gather(
                    *parallel_tasks.values(), return_exceptions=True
                )
                # Re-raise CancelledError from parallel checks
                for r in parallel_results:
                    if isinstance(r, asyncio.CancelledError):
                        raise r
                gathered = dict(zip(parallel_tasks.keys(), parallel_results, strict=True))

            result = CheckResult(
                generated_at=generated_at,
                nip11_info=nip11_info,
                nip66_rtt=rtt_meta,
                nip66_ssl=extract_result(gathered, "ssl"),
                nip66_geo=extract_result(gathered, "geo"),
                nip66_net=extract_result(gathered, "net"),
                nip66_dns=extract_result(gathered, "dns"),
                nip66_http=extract_result(gathered, "http"),
            )

            if result.has_data:
                self._logger.debug("check_succeeded", url=relay.url)
            else:
                self._logger.debug("check_failed", url=relay.url)

            return result

        except (TimeoutError, OSError) as e:
            self._logger.debug("check_error", url=relay.url, error=str(e))
            return empty

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
        tasks: dict[str, Any] = {}

        if compute.nip66_ssl and relay.network == NetworkType.CLEARNET:
            tasks["ssl"] = retry_fetch(
                relay,
                lambda: Nip66SslMetadata.probe(relay, timeout),
                self._config.processing.retries.nip66_ssl,
                "nip66_ssl",
                wait=self.wait,
            )
        if compute.nip66_dns and relay.network == NetworkType.CLEARNET:
            tasks["dns"] = retry_fetch(
                relay,
                lambda: Nip66DnsMetadata.probe(relay, timeout),
                self._config.processing.retries.nip66_dns,
                "nip66_dns",
                wait=self.wait,
            )
        if compute.nip66_geo and self.geo_readers.city and relay.network == NetworkType.CLEARNET:
            city_reader = self.geo_readers.city
            precision = self._config.geo.geohash_precision
            tasks["geo"] = retry_fetch(
                relay,
                lambda: Nip66GeoMetadata.probe(relay, city_reader, precision, timeout=timeout),
                self._config.processing.retries.nip66_geo,
                "nip66_geo",
                wait=self.wait,
            )
        if compute.nip66_net and self.geo_readers.asn and relay.network == NetworkType.CLEARNET:
            asn_reader = self.geo_readers.asn
            tasks["net"] = retry_fetch(
                relay,
                lambda: Nip66NetMetadata.probe(relay, asn_reader, timeout=timeout),
                self._config.processing.retries.nip66_net,
                "nip66_net",
                wait=self.wait,
            )
        if compute.nip66_http:
            tasks["http"] = retry_fetch(
                relay,
                lambda: Nip66HttpMetadata.probe(
                    relay,
                    timeout,
                    proxy_url,
                    allow_insecure=self._config.processing.allow_insecure,
                ),
                self._config.processing.retries.nip66_http,
                "nip66_http",
                wait=self.wait,
            )

        return tasks

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

        all_relays = await fetch_relays_to_monitor(self._brotr, monitored_before, networks)
        if max_relays is not None:
            all_relays = all_relays[:max_relays]

        total = len(all_relays)
        succeeded = 0
        failed = 0

        self.set_gauge("total", total)
        self.set_gauge("succeeded", 0)
        self.set_gauge("failed", 0)

        self._logger.info("relays_available", total=total)

        chunk_size = self._config.processing.chunk_size

        for i in range(0, total, chunk_size):
            if not self.is_running:
                break

            relays = all_relays[i : i + chunk_size]
            chunk_successful: list[tuple[Relay, CheckResult]] = []
            chunk_failed: list[Relay] = []

            async for relay, result in self._iter_concurrent(relays, self._monitor_worker):
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
