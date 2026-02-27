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
    and broadcasting to [bigbrotr.utils.transport][bigbrotr.utils.transport]. The Monitor handles
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
import random
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, NamedTuple, TypeVar

import asyncpg
from nostr_sdk import EventBuilder, Filter, Keys, Kind, Tag

from bigbrotr.core.base_service import BaseService
from bigbrotr.models import Metadata, MetadataType, Relay
from bigbrotr.models.constants import EventKind, NetworkType, ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType
from bigbrotr.nips.event_builders import (
    build_monitor_announcement,
    build_profile_event,
    build_relay_discovery,
)
from bigbrotr.nips.nip11 import Nip11, Nip11Options, Nip11Selection
from bigbrotr.nips.nip66 import (
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
    ChunkProgressMixin,
    GeoReaderMixin,
    NetworkSemaphoresMixin,
)
from bigbrotr.services.common.queries import cleanup_stale_state, fetch_relays_to_monitor
from bigbrotr.utils.http import download_bounded_file
from bigbrotr.utils.protocol import broadcast_events

from .configs import MetadataFlags, MonitorConfig, RetryConfig
from .utils import collect_metadata, get_reason, get_success, safe_result


if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Coroutine

    from bigbrotr.core.brotr import Brotr
    from bigbrotr.nips.nip11.info import Nip11InfoMetadata


_SECONDS_PER_DAY = 86_400

_T = TypeVar("_T")


class CheckResult(NamedTuple):
    """Result of a single relay health check.

    Each field contains the typed NIP metadata container if that check was run
    and produced data, or ``None`` if the check was skipped (disabled in config)
    or failed completely. Use ``has_data`` to test whether any check produced
    results.

    Attributes:
        generated_at: Unix timestamp when the health check was performed.
        nip11: NIP-11 relay information document (name, description, pubkey, etc.).
        nip66_rtt: Round-trip times for open/read/write operations in milliseconds.
        nip66_ssl: SSL certificate validation (valid, expiry timestamp, issuer).
        nip66_geo: Geolocation data (country, city, coordinates, timezone, geohash).
        nip66_net: Network information (IP address, ASN, organization).
        nip66_dns: DNS resolution data (IPs, CNAME, nameservers, reverse DNS).
        nip66_http: HTTP metadata (status code, headers, redirect chain).

    See Also:
        [MetadataFlags][bigbrotr.services.monitor.MetadataFlags]: Boolean
            flags controlling which check types are computed and stored.
    """

    generated_at: int = 0
    nip11: Nip11InfoMetadata | None = None
    nip66_rtt: Nip66RttMetadata | None = None
    nip66_ssl: Nip66SslMetadata | None = None
    nip66_geo: Nip66GeoMetadata | None = None
    nip66_net: Nip66NetMetadata | None = None
    nip66_dns: Nip66DnsMetadata | None = None
    nip66_http: Nip66HttpMetadata | None = None

    @property
    def has_data(self) -> bool:
        """True if at least one NIP check produced data."""
        return any(
            (
                self.nip11,
                self.nip66_rtt,
                self.nip66_ssl,
                self.nip66_geo,
                self.nip66_net,
                self.nip66_dns,
                self.nip66_http,
            )
        )


class Monitor(
    ChunkProgressMixin,
    NetworkSemaphoresMixin,
    GeoReaderMixin,
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
    and broadcasting to [bigbrotr.utils.transport][bigbrotr.utils.transport].

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
        self._keys: Keys = self._config.keys.keys

    async def run(self) -> None:
        """Execute one complete monitoring cycle.

        Orchestrates setup, publishing, monitoring, and cycle-level logging.
        Delegates the core work to ``update_geo_databases``,
        ``publish_profile``, ``publish_announcement``, and ``monitor``.
        """
        self._logger.info(
            "cycle_started",
            chunk_size=self._config.processing.chunk_size,
            max_relays=self._config.processing.max_relays,
            networks=self._config.networks.get_enabled_networks(),
        )

        self.chunk_progress.reset()
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

            self._logger.info(
                "cycle_completed",
                checked=self.chunk_progress.processed,
                successful=self.chunk_progress.succeeded,
                failed=self.chunk_progress.failed,
                chunks=self.chunk_progress.chunks,
                duration_s=self.chunk_progress.elapsed,
            )
        finally:
            self.geo_readers.close()

    async def _update_geo_db(self, path: Path, url: str, db_name: str) -> None:
        """Download a single GeoLite2 database if missing or stale."""
        max_size = self._config.geo.max_download_size
        max_age_days = self._config.geo.max_age_days

        if await asyncio.to_thread(path.exists):
            if max_age_days is None:
                return
            age = time.time() - (await asyncio.to_thread(path.stat)).st_mtime
            if age <= max_age_days * _SECONDS_PER_DAY:
                return
            self._logger.info(
                "updating_geo_db",
                db=db_name,
                age_days=round(age / _SECONDS_PER_DAY, 1),
            )
        else:
            self._logger.info("downloading_geo_db", db=db_name)

        await download_bounded_file(url, path, max_size)

    async def update_geo_databases(self) -> None:
        """Download or re-download GeoLite2 databases if missing or stale.

        Download failures are logged and suppressed so that a transient
        network error does not prevent the monitor cycle from proceeding
        with a stale (or missing) database.
        """
        compute = self._config.processing.compute
        geo = self._config.geo

        updates: list[tuple[Path, str, str]] = []
        if compute.nip66_geo:
            updates.append((Path(geo.city_database_path), geo.city_download_url, "city"))
        if compute.nip66_net:
            updates.append((Path(geo.asn_database_path), geo.asn_download_url, "asn"))

        for path, url, name in updates:
            try:
                await self._update_geo_db(path, url, name)
            except (OSError, ValueError) as e:
                self._logger.warning("geo_db_update_failed", db=name, error=str(e))

    async def monitor(self) -> int:
        """Count, check, persist, and publish all pending relays.

        High-level entry point that counts relays due for checking, processes
        them in chunks via ``check_chunks``, publishes Kind 30166 discovery
        events, persists metadata results, and emits progress metrics.
        Returns the total number of relays processed.

        This is the method ``run()`` delegates to after setup. It can also
        be called standalone when GeoIP update and profile/announcement
        publishing are not desired.

        Returns:
            Total number of relays processed (successful + failed).
        """
        networks = self._config.networks.get_enabled_networks()

        if not networks:
            self._logger.warning("no_networks_enabled")
            self._emit_progress_gauges()
            return self.chunk_progress.processed

        try:
            removed = await cleanup_stale_state(
                self._brotr, self.SERVICE_NAME, ServiceStateType.MONITORING
            )
            if removed:
                self._logger.info("stale_checkpoints_removed", count=removed)
        except (asyncpg.PostgresError, OSError) as e:
            self._logger.warning(
                "stale_checkpoint_cleanup_failed", error=str(e), error_type=type(e).__name__
            )

        relays = await self._fetch_relays(networks)
        self.chunk_progress.total = len(relays)
        self._logger.info("relays_available", total=self.chunk_progress.total)
        self._emit_progress_gauges()

        async for successful, failed in self.check_chunks(relays):
            self.chunk_progress.record(succeeded=len(successful), failed=len(failed))
            await self.publish_relay_discoveries(successful)
            await self._persist_results(successful, failed)
            self._emit_progress_gauges()
            self._logger.info(
                "chunk_completed",
                chunk=self.chunk_progress.chunks,
                successful=len(successful),
                failed=len(failed),
                remaining=self.chunk_progress.remaining,
            )

        self._emit_progress_gauges()
        return self.chunk_progress.processed

    async def check_chunks(
        self,
        relays: list[Relay],
    ) -> AsyncIterator[tuple[list[tuple[Relay, CheckResult]], list[Relay]]]:
        """Yield (successful, failed) for each processed chunk of relays.

        Requires ``geo_readers.open()`` for full checks. Handles budget
        calculation and concurrent health checks. Persistence and publishing
        are left to the caller.

        Args:
            relays: Pre-fetched relays to process, already ordered by
                least-recently-checked.

        Yields:
            Tuple of (successful relay-result pairs, failed relays) per chunk.
        """
        chunk_size = self._config.processing.chunk_size
        max_relays = self._config.processing.max_relays

        if max_relays is not None:
            relays = relays[:max_relays]

        for i in range(0, len(relays), chunk_size):
            if not self.is_running:
                break
            chunk = relays[i : i + chunk_size]
            successful, failed = await self._check_chunk(chunk)
            yield successful, failed

    async def _fetch_relays(self, networks: list[NetworkType]) -> list[Relay]:
        """Fetch all relays due for monitoring.

        See Also:
            ``fetch_relays_to_monitor``: The SQL query executed.
        """
        monitored_before = int(self.chunk_progress.started_at) - self._config.discovery.interval
        return await fetch_relays_to_monitor(self._brotr, monitored_before, networks)

    async def _check_chunk(
        self, relays: list[Relay]
    ) -> tuple[list[tuple[Relay, CheckResult]], list[Relay]]:
        """Run health checks on a chunk of relays concurrently.

        Uses ``asyncio.gather`` with per-network semaphores to bound
        concurrency. A relay is considered successful if any field in
        its [CheckResult][bigbrotr.services.monitor.CheckResult] is
        non-``None``.

        Returns:
            Tuple of (successful relay-result pairs, failed relays).
        """
        tasks = [self.check_relay(r) for r in relays]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        successful: list[tuple[Relay, CheckResult]] = []
        failed: list[Relay] = []

        for relay, result in zip(relays, results, strict=True):
            # gather(return_exceptions=True) captures CancelledError as a result
            if isinstance(result, asyncio.CancelledError):
                raise result
            if isinstance(result, CheckResult) and result.has_data:
                successful.append((relay, result))
            else:
                failed.append(relay)

        return successful, failed

    async def _fetch_nip11_info(
        self,
        relay: Relay,
        timeout: float,  # noqa: ASYNC109
        proxy_url: str | None,
    ) -> Nip11InfoMetadata | None:
        """Fetch NIP-11 info and return the metadata container.

        Unwraps the [Nip11][bigbrotr.nips.nip11.Nip11] wrapper so that
        the returned [Nip11InfoMetadata][bigbrotr.nips.nip11.info.Nip11InfoMetadata]
        is directly compatible with
        [_with_retry][bigbrotr.services.monitor.Monitor._with_retry]
        (which calls [get_success][bigbrotr.services.monitor.utils.get_success]
        on the result's ``.logs`` attribute).
        """
        nip11 = await Nip11.create(
            relay,
            timeout=timeout,
            proxy_url=proxy_url,
            options=Nip11Options(
                allow_insecure=self._config.processing.allow_insecure,
                max_size=self._config.processing.nip11_info_max_size,
            ),
        )
        return nip11.info

    async def _with_retry(
        self,
        coro_factory: Callable[[], Coroutine[Any, Any, _T]],
        retry: RetryConfig,
        operation: str,
        relay_url: str,
    ) -> _T | None:
        """Execute a metadata fetch with exponential backoff retry.

        Retries on network failures up to ``retry.max_attempts`` times.
        Returns the result (possibly with ``success=False``) or ``None`` on
        exception.

        Note:
            The ``coro_factory`` pattern (a callable returning a coroutine)
            is required because Python coroutines are single-use: once
            awaited, they cannot be re-awaited. The factory creates a fresh
            coroutine for each retry attempt.

        Warning:
            Jitter is computed via ``random.uniform()`` (PRNG, ``# noqa: S311``).
            This is intentional -- jitter only needs to decorrelate
            concurrent retries, not provide cryptographic randomness.

        Args:
            coro_factory: Callable that creates the coroutine to execute.
                Must return a fresh coroutine on each call.
            retry: [RetryConfig][bigbrotr.services.monitor.configs.RetryConfig]
                with max retries, delays, and jitter.
            operation: Operation name for structured log messages.
            relay_url: Relay URL for logging context.

        Returns:
            The metadata result, or ``None`` if an exception occurred.
        """
        max_retries = retry.max_attempts
        result = None

        for attempt in range(max_retries + 1):
            try:
                result = await coro_factory()
                if get_success(result):
                    return result
            except (TimeoutError, OSError) as e:
                self._logger.debug(
                    "check_error",
                    operation=operation,
                    relay=relay_url,
                    attempt=attempt + 1,
                    error=str(e),
                )
                result = None

            # Network failure - retry if attempts remaining
            if attempt < max_retries:
                delay = min(retry.initial_delay * (2**attempt), retry.max_delay)
                jitter = random.uniform(0, retry.jitter)  # noqa: S311
                if await self.wait(delay + jitter):
                    return None
                self._logger.debug(
                    "check_retry",
                    operation=operation,
                    relay=relay_url,
                    attempt=attempt + 1,
                    reason=get_reason(result) if result else None,
                    delay_s=round(delay + jitter, 2),
                )

        # All retries exhausted
        self._logger.debug(
            "check_exhausted",
            operation=operation,
            relay=relay_url,
            total_attempts=max_retries + 1,
            reason=get_reason(result) if result else None,
        )
        return result

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

        Note:
            SSL, DNS, Geo, and Net checks are clearnet-only because
            overlay networks (Tor, I2P, Lokinet) do not expose the
            underlying IP address needed for these probes.

        See Also:
            [MetadataFlags][bigbrotr.services.monitor.MetadataFlags]:
                Controls which checks are included.
        """
        tasks: dict[str, Any] = {}

        if compute.nip66_ssl and relay.network == NetworkType.CLEARNET:
            tasks["ssl"] = self._with_retry(
                lambda: Nip66SslMetadata.execute(relay, timeout),
                self._config.processing.retries.nip66_ssl,
                "nip66_ssl",
                relay.url,
            )
        if compute.nip66_dns and relay.network == NetworkType.CLEARNET:
            tasks["dns"] = self._with_retry(
                lambda: Nip66DnsMetadata.execute(relay, timeout),
                self._config.processing.retries.nip66_dns,
                "nip66_dns",
                relay.url,
            )
        if compute.nip66_geo and self.geo_readers.city and relay.network == NetworkType.CLEARNET:
            city_reader = self.geo_readers.city
            precision = self._config.geo.geohash_precision
            tasks["geo"] = self._with_retry(
                lambda: Nip66GeoMetadata.execute(relay, city_reader, precision),
                self._config.processing.retries.nip66_geo,
                "nip66_geo",
                relay.url,
            )
        if compute.nip66_net and self.geo_readers.asn and relay.network == NetworkType.CLEARNET:
            asn_reader = self.geo_readers.asn
            tasks["net"] = self._with_retry(
                lambda: Nip66NetMetadata.execute(relay, asn_reader),
                self._config.processing.retries.nip66_net,
                "nip66_net",
                relay.url,
            )
        if compute.nip66_http:
            tasks["http"] = self._with_retry(
                lambda: Nip66HttpMetadata.execute(
                    relay,
                    timeout,
                    proxy_url,
                    allow_insecure=self._config.processing.allow_insecure,
                ),
                self._config.processing.retries.nip66_http,
                "nip66_http",
                relay.url,
            )

        return tasks

    async def check_relay(self, relay: Relay) -> CheckResult:
        """Perform all configured health checks on a single relay.

        Runs [Nip11][bigbrotr.nips.nip11.Nip11], RTT, SSL, DNS, geo, net,
        and HTTP checks as configured. Uses the network-specific semaphore
        (from [NetworkSemaphoresMixin][bigbrotr.services.common.mixins.NetworkSemaphoresMixin])
        to limit concurrency.

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

        semaphore = self.network_semaphores.get(relay.network)
        if semaphore is None:
            self._logger.warning("unknown_network", url=relay.url, network=relay.network.value)
            return empty

        async with semaphore:
            network_config = self._config.networks.get(relay.network)
            proxy_url = self._config.networks.get_proxy_url(relay.network)
            timeout = network_config.timeout
            compute = self._config.processing.compute

            nip11_info: Nip11InfoMetadata | None = None
            generated_at = int(time.time())

            try:
                if compute.nip11_info:
                    nip11_info = await self._with_retry(
                        lambda: self._fetch_nip11_info(relay, timeout, proxy_url),
                        self._config.processing.retries.nip11_info,
                        "nip11_info",
                        relay.url,
                    )

                rtt_meta: Nip66RttMetadata | None = None

                # RTT test: open/read/write round-trip times
                if compute.nip66_rtt:
                    event_builder = EventBuilder(Kind(EventKind.NIP66_TEST), "nip66-test").tags(
                        [Tag.identifier(relay.url)]
                    )
                    # Apply proof-of-work if NIP-11 specifies minimum difficulty
                    if nip11_info and nip11_info.logs.success:
                        pow_difficulty = nip11_info.data.limitation.min_pow_difficulty
                        if pow_difficulty and pow_difficulty > 0:
                            event_builder = event_builder.pow(pow_difficulty)
                    read_filter = Filter().limit(1)
                    rtt_deps = Nip66RttDependencies(
                        keys=self._keys,
                        event_builder=event_builder,
                        read_filter=read_filter,
                    )
                    rtt_meta = await self._with_retry(
                        lambda: Nip66RttMetadata.execute(
                            relay,
                            rtt_deps,
                            timeout,
                            proxy_url,
                            allow_insecure=self._config.processing.allow_insecure,
                        ),
                        self._config.processing.retries.nip66_rtt,
                        "nip66_rtt",
                        relay.url,
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
                    nip11=nip11_info,
                    nip66_rtt=rtt_meta,
                    nip66_ssl=safe_result(gathered, "ssl"),
                    nip66_geo=safe_result(gathered, "geo"),
                    nip66_net=safe_result(gathered, "net"),
                    nip66_dns=safe_result(gathered, "dns"),
                    nip66_http=safe_result(gathered, "http"),
                )

                if result.has_data:
                    self._logger.debug("check_succeeded", url=relay.url)
                else:
                    self._logger.debug("check_failed", url=relay.url)

                return result

            except (TimeoutError, OSError) as e:
                self._logger.debug("check_error", url=relay.url, error=str(e))
                return empty

    async def _persist_results(
        self,
        successful: list[tuple[Relay, CheckResult]],
        failed: list[Relay],
    ) -> None:
        """Persist health check results to the database.

        Inserts [RelayMetadata][bigbrotr.models.relay_metadata.RelayMetadata]
        records for successful checks and saves monitoring timestamps
        (as [ServiceState][bigbrotr.models.service_state.ServiceState]
        records with ``state_type='monitoring'``) for all checked relays
        (both successful and failed) to avoid re-checking within the
        same interval.

        Note:
            Monitoring markers are saved for *all* relays, including failed ones.
            This prevents the monitor from repeatedly retrying a relay
            that is temporarily down within the same discovery interval.
            The relay will be rechecked in the next cycle after the
            interval elapses.
        """
        now = int(time.time())

        # Insert metadata for successful checks
        if successful:
            metadata = collect_metadata(successful, self._config.processing.store)
            if metadata:
                try:
                    count = await self._brotr.insert_relay_metadata(metadata)
                    self._logger.debug("metadata_inserted", count=count)
                except (asyncpg.PostgresError, OSError) as e:
                    self._logger.error("metadata_insert_failed", error=str(e), count=len(metadata))

        # Save monitoring markers for all checked relays
        all_relays = [relay for relay, _ in successful] + failed
        if all_relays:
            markers: list[ServiceState] = [
                ServiceState(
                    service_name=self.SERVICE_NAME,
                    state_type=ServiceStateType.MONITORING,
                    state_key=relay.url,
                    state_value={"monitored_at": now},
                    updated_at=now,
                )
                for relay in all_relays
            ]
            try:
                await self._brotr.upsert_service_state(markers)
            except (asyncpg.PostgresError, OSError) as e:
                self._logger.error("monitoring_save_failed", error=str(e))

    def _emit_progress_gauges(self) -> None:
        """Emit Prometheus gauges for batch progress."""
        self.set_gauge("total", self.chunk_progress.total)
        self.set_gauge("processed", self.chunk_progress.processed)
        self.set_gauge("success", self.chunk_progress.succeeded)
        self.set_gauge("failure", self.chunk_progress.failed)

    def _get_publish_relays(self, section_relays: list[Relay] | None) -> list[Relay]:
        """Get relays for event publishing, falling back to the global publishing relays."""
        return section_relays if section_relays is not None else self._config.publishing.relays

    async def _publish_if_due(  # noqa: PLR0913
        self,
        *,
        enabled: bool,
        relays: list[Relay],
        interval: int,
        state_key: str,
        builder: EventBuilder,
        event_name: str,
        timeout: float = 30.0,  # noqa: ASYNC109
    ) -> None:
        """Publish an event if enabled, relays configured, and interval elapsed."""
        if not enabled or not relays:
            return

        results = await self._brotr.get_service_state(
            self.SERVICE_NAME,
            ServiceStateType.PUBLICATION,
            state_key,
        )
        last_ts = results[0].state_value.get("published_at", 0) if results else 0
        if time.time() - last_ts < interval:
            return

        sent = await broadcast_events(
            [builder],
            relays,
            self._keys,
            timeout=timeout,
        )
        if not sent:
            self._logger.warning("publish_failed", event=event_name, error="no relays reachable")
            return

        self._logger.info("publish_completed", event=event_name, relays=sent)
        now = int(time.time())
        await self._brotr.upsert_service_state(
            [
                ServiceState(
                    service_name=self.SERVICE_NAME,
                    state_type=ServiceStateType.PUBLICATION,
                    state_key=state_key,
                    state_value={"published_at": now},
                    updated_at=now,
                ),
            ]
        )

    async def publish_announcement(self) -> None:
        """Publish Kind 10166 monitor announcement if the configured interval has elapsed."""
        ann = self._config.announcement
        await self._publish_if_due(
            enabled=ann.enabled,
            relays=self._get_publish_relays(ann.relays),
            interval=ann.interval,
            state_key="last_announcement",
            builder=self._build_kind_10166(),
            event_name="announcement",
            timeout=self._config.publishing.timeout,
        )

    async def publish_profile(self) -> None:
        """Publish Kind 0 profile metadata if the configured interval has elapsed."""
        profile = self._config.profile
        await self._publish_if_due(
            enabled=profile.enabled,
            relays=self._get_publish_relays(profile.relays),
            interval=profile.interval,
            state_key="last_profile",
            builder=self._build_kind_0(),
            event_name="profile",
            timeout=self._config.publishing.timeout,
        )

    async def publish_relay_discoveries(self, successful: list[tuple[Relay, CheckResult]]) -> None:
        """Publish Kind 30166 relay discovery events for successful health checks."""
        disc = self._config.discovery
        relays = self._get_publish_relays(disc.relays)
        if not disc.enabled or not relays:
            return

        builders: list[EventBuilder] = []
        for relay, result in successful:
            try:
                builders.append(self._build_kind_30166(relay, result))
            except (ValueError, KeyError, TypeError) as e:
                self._logger.debug("build_30166_failed", url=relay.url, error=str(e))

        if builders:
            sent = await broadcast_events(
                builders,
                relays,
                self._keys,
                timeout=self._config.publishing.timeout,
            )
            if sent:
                self._logger.debug("discoveries_published", count=len(builders))
            else:
                self._logger.warning(
                    "discoveries_broadcast_failed",
                    count=len(builders),
                    error="no relays reachable",
                )

    def _build_kind_0(self) -> EventBuilder:
        """Build Kind 0 profile metadata event per NIP-01."""
        p = self._config.profile
        return build_profile_event(
            name=p.name,
            about=p.about,
            picture=p.picture,
            nip05=p.nip05,
            website=p.website,
            banner=p.banner,
            lud16=p.lud16,
        )

    def _build_kind_10166(self) -> EventBuilder:
        """Build Kind 10166 monitor announcement event per NIP-66."""
        timeout_ms = int(self._config.networks.clearnet.timeout * 1000)
        include = self._config.discovery.include
        enabled_networks = [
            network for network in NetworkType if self._config.networks.is_enabled(network)
        ]
        return build_monitor_announcement(
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
        )

    def _build_kind_30166(self, relay: Relay, result: CheckResult) -> EventBuilder:
        """Build a Kind 30166 relay discovery event per NIP-66."""
        include = self._config.discovery.include

        nip11_canonical_json = ""
        if result.nip11 and include.nip11_info:
            meta = Metadata(type=MetadataType.NIP11_INFO, data=result.nip11.to_dict())
            nip11_canonical_json = meta.canonical_json

        return build_relay_discovery(
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
