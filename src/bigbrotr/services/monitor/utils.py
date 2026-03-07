"""Monitor service utility functions.

Pure helpers for health check result inspection, metadata collection,
relay discovery event building, relay list selection, and extracted
service operations that accept a ``Monitor`` instance.
"""

from __future__ import annotations

import asyncio
import random
import time
from typing import TYPE_CHECKING, Any, NamedTuple, TypeVar

import asyncpg
from nostr_sdk import EventBuilder, Filter, Kind, Tag

from bigbrotr.models import Metadata, MetadataType, RelayMetadata
from bigbrotr.models.constants import EventKind, NetworkType
from bigbrotr.nips.base import BaseLogs, BaseNipMetadata
from bigbrotr.nips.event_builders import build_relay_discovery
from bigbrotr.nips.nip11 import Nip11, Nip11Options
from bigbrotr.nips.nip66 import (
    Nip66DnsMetadata,
    Nip66GeoMetadata,
    Nip66HttpMetadata,
    Nip66NetMetadata,
    Nip66RttDependencies,
    Nip66RttMetadata,
    Nip66SslMetadata,
)
from bigbrotr.nips.nip66.logs import Nip66RttMultiPhaseLogs

from .queries import insert_relay_metadata, save_monitoring_markers


if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from bigbrotr.models import Relay
    from bigbrotr.nips.nip11.info import Nip11InfoMetadata
    from bigbrotr.services.monitor.configs import MetadataFlags, RetryConfig
    from bigbrotr.services.monitor.service import Monitor


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
        nip66_http: HTTP metadata (server software and framework headers).

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


def get_success(result: Any) -> bool:
    """Extract success status from a metadata result's logs object."""
    logs = result.logs
    if isinstance(logs, BaseLogs):
        return bool(logs.success)
    if isinstance(logs, Nip66RttMultiPhaseLogs):
        return bool(logs.open_success)
    return False


def get_reason(result: Any) -> str | None:
    """Extract failure reason from a metadata result's logs object."""
    logs = result.logs
    if isinstance(logs, BaseLogs):
        return str(logs.reason) if logs.reason else None
    if isinstance(logs, Nip66RttMultiPhaseLogs):
        return str(logs.open_reason) if logs.open_reason else None
    return None


def safe_result(results: dict[str, Any], key: str) -> Any:
    """Extract a successful result from asyncio.gather output.

    Returns None if the key is absent or the result is an exception.
    """
    value = results.get(key)
    if value is None or isinstance(value, BaseException):
        return None
    return value


def collect_metadata(
    successful: list[tuple[Relay, CheckResult]],
    store: MetadataFlags,
) -> list[RelayMetadata]:
    """Collect storable metadata from successful health check results.

    Converts typed NIP metadata into
    [RelayMetadata][bigbrotr.models.relay_metadata.RelayMetadata]
    records for database insertion.

    Args:
        successful: List of ([Relay][bigbrotr.models.relay.Relay],
            [CheckResult][bigbrotr.services.monitor.CheckResult])
            pairs from health checks.
        store: Flags controlling which metadata types to persist.

    Returns:
        List of [RelayMetadata][bigbrotr.models.relay_metadata.RelayMetadata]
        records ready for database insertion.
    """
    metadata: list[RelayMetadata] = []
    check_specs: list[tuple[str, str, MetadataType]] = [
        ("nip11", "nip11_info", MetadataType.NIP11_INFO),
        ("nip66_rtt", "nip66_rtt", MetadataType.NIP66_RTT),
        ("nip66_ssl", "nip66_ssl", MetadataType.NIP66_SSL),
        ("nip66_geo", "nip66_geo", MetadataType.NIP66_GEO),
        ("nip66_net", "nip66_net", MetadataType.NIP66_NET),
        ("nip66_dns", "nip66_dns", MetadataType.NIP66_DNS),
        ("nip66_http", "nip66_http", MetadataType.NIP66_HTTP),
    ]
    for relay, result in successful:
        for result_field, store_field, meta_type in check_specs:
            nip_meta: BaseNipMetadata | None = getattr(result, result_field)
            if nip_meta and getattr(store, store_field):
                metadata.append(
                    RelayMetadata(
                        relay=relay,
                        metadata=Metadata(type=meta_type, data=nip_meta.to_dict()),
                        generated_at=result.generated_at,
                    )
                )
    return metadata


def get_publish_relays(
    section_relays: list[Relay] | None,
    default_relays: list[Relay],
) -> list[Relay]:
    """Return section-specific relays, falling back to the default publishing list.

    Args:
        section_relays: Section-specific relay list, or ``None`` if not configured.
        default_relays: Fallback relay list from ``publishing.relays``.

    Returns:
        ``section_relays`` if set (even if empty), otherwise ``default_relays``.
    """
    return section_relays if section_relays is not None else default_relays


# ============================================================================
# Extracted service operations
# ============================================================================


async def with_retry(
    monitor: Monitor,
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
    """
    max_retries = retry.max_attempts
    result = None

    for attempt in range(max_retries + 1):
        try:
            result = await coro_factory()
            if get_success(result):
                return result
        except (TimeoutError, OSError) as e:
            monitor._logger.debug(
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
            if await monitor.wait(delay + jitter):
                return None
            monitor._logger.debug(
                "check_retry",
                operation=operation,
                relay=relay_url,
                attempt=attempt + 1,
                reason=get_reason(result) if result else None,
                delay_s=round(delay + jitter, 2),
            )

    # All retries exhausted
    monitor._logger.debug(
        "check_exhausted",
        operation=operation,
        relay=relay_url,
        total_attempts=max_retries + 1,
        reason=get_reason(result) if result else None,
    )
    return result


def build_parallel_checks(
    monitor: Monitor,
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
        tasks["ssl"] = with_retry(
            monitor,
            lambda: Nip66SslMetadata.execute(relay, timeout),
            monitor._config.processing.retries.nip66_ssl,
            "nip66_ssl",
            relay.url,
        )
    if compute.nip66_dns and relay.network == NetworkType.CLEARNET:
        tasks["dns"] = with_retry(
            monitor,
            lambda: Nip66DnsMetadata.execute(relay, timeout),
            monitor._config.processing.retries.nip66_dns,
            "nip66_dns",
            relay.url,
        )
    if compute.nip66_geo and monitor.geo_readers.city and relay.network == NetworkType.CLEARNET:
        city_reader = monitor.geo_readers.city
        precision = monitor._config.geo.geohash_precision
        tasks["geo"] = with_retry(
            monitor,
            lambda: Nip66GeoMetadata.execute(relay, city_reader, precision),
            monitor._config.processing.retries.nip66_geo,
            "nip66_geo",
            relay.url,
        )
    if compute.nip66_net and monitor.geo_readers.asn and relay.network == NetworkType.CLEARNET:
        asn_reader = monitor.geo_readers.asn
        tasks["net"] = with_retry(
            monitor,
            lambda: Nip66NetMetadata.execute(relay, asn_reader),
            monitor._config.processing.retries.nip66_net,
            "nip66_net",
            relay.url,
        )
    if compute.nip66_http:
        tasks["http"] = with_retry(
            monitor,
            lambda: Nip66HttpMetadata.execute(
                relay,
                timeout,
                proxy_url,
                allow_insecure=monitor._config.processing.allow_insecure,
            ),
            monitor._config.processing.retries.nip66_http,
            "nip66_http",
            relay.url,
        )

    return tasks


async def check_relay(monitor: Monitor, relay: Relay) -> CheckResult:
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

    semaphore = monitor.network_semaphores.get(relay.network)
    if semaphore is None:
        monitor._logger.warning("unknown_network", url=relay.url, network=relay.network.value)
        return empty

    async with semaphore:
        network_config = monitor._config.networks.get(relay.network)
        proxy_url = monitor._config.networks.get_proxy_url(relay.network)
        timeout = network_config.timeout
        compute = monitor._config.processing.compute

        nip11_info: Nip11InfoMetadata | None = None
        generated_at = int(time.time())

        try:
            if compute.nip11_info:

                async def _fetch_nip11() -> Nip11InfoMetadata | None:
                    return (
                        await Nip11.create(
                            relay,
                            timeout=timeout,
                            proxy_url=proxy_url,
                            options=Nip11Options(
                                allow_insecure=monitor._config.processing.allow_insecure,
                                max_size=monitor._config.processing.nip11_info_max_size,
                            ),
                        )
                    ).info

                nip11_info = await with_retry(
                    monitor,
                    _fetch_nip11,
                    monitor._config.processing.retries.nip11_info,
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
                    keys=monitor._keys,
                    event_builder=event_builder,
                    read_filter=read_filter,
                )
                rtt_meta = await with_retry(
                    monitor,
                    lambda: Nip66RttMetadata.execute(
                        relay,
                        rtt_deps,
                        timeout,
                        proxy_url,
                        allow_insecure=monitor._config.processing.allow_insecure,
                    ),
                    monitor._config.processing.retries.nip66_rtt,
                    "nip66_rtt",
                    relay.url,
                )

            # Run independent checks (SSL, DNS, Geo, Net, HTTP) in parallel
            parallel_tasks = build_parallel_checks(monitor, relay, compute, timeout, proxy_url)

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
                monitor._logger.debug("check_succeeded", url=relay.url)
            else:
                monitor._logger.debug("check_failed", url=relay.url)

            return result

        except (TimeoutError, OSError) as e:
            monitor._logger.debug("check_error", url=relay.url, error=str(e))
            return empty


def build_discovery_event(
    relay: Relay,
    result: CheckResult,
    include: MetadataFlags,
) -> EventBuilder:
    """Build a Kind 30166 relay discovery event for a single relay.

    Args:
        relay: The relay that was health-checked.
        result: Health check result containing metadata.
        include: Flags controlling which metadata types to include.

    Returns:
        An [EventBuilder][nostr_sdk.EventBuilder] ready for signing and broadcast.
    """
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


async def flush_results(
    monitor: Monitor,
    successful: list[tuple[Relay, CheckResult]],
    failed: list[Relay],
    remaining: int,
) -> None:
    """Persist health check results and log chunk completion.

    Inserts [RelayMetadata][bigbrotr.models.relay_metadata.RelayMetadata]
    records for successful checks and saves monitoring timestamps
    for all checked relays (both successful and failed) to prevent
    re-checking within the same interval.
    """
    now = int(time.time())

    if successful:
        metadata = collect_metadata(successful, monitor._config.processing.store)
        if metadata:
            try:
                count = await insert_relay_metadata(monitor._brotr, metadata)
                monitor._logger.debug("metadata_inserted", count=count)
                monitor.inc_counter("total_metadata_stored", count)
            except (asyncpg.PostgresError, OSError) as e:
                monitor._logger.error("metadata_insert_failed", error=str(e), count=len(metadata))

    all_relays = [relay for relay, _ in successful] + failed
    if all_relays:
        try:
            await save_monitoring_markers(monitor._brotr, all_relays, now)
        except (asyncpg.PostgresError, OSError) as e:
            monitor._logger.error("monitoring_save_failed", error=str(e))

    monitor._logger.info(
        "chunk_completed",
        succeeded=len(successful),
        failed=len(failed),
        remaining=remaining,
    )
