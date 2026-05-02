"""Shared relay-check orchestration for the Monitor service."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from nostr_sdk import EventBuilder, Filter, Kind, Tag

from bigbrotr.models.constants import EventKind, NetworkType
from bigbrotr.nips.nip11 import Nip11Options
from bigbrotr.nips.nip66 import Nip66RttDependencies

from .utils import CheckResult, extract_result


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from nostr_sdk import Keys

    from bigbrotr.core.logger import Logger
    from bigbrotr.models import Relay
    from bigbrotr.nips.nip11.info import Nip11InfoMetadata
    from bigbrotr.services.common.configs import NetworksConfig
    from bigbrotr.services.monitor.configs import MetadataFlags, RetriesConfig


@dataclass(frozen=True, slots=True)
class MonitorCheckContext:
    """Runtime context for one relay health-check flow."""

    relay: Relay
    compute: MetadataFlags
    timeout: float
    proxy_url: str | None
    allow_insecure: bool
    nip11_info_max_size: int
    retries: RetriesConfig
    geohash_precision: int
    keys: Keys
    city_reader: Any | None
    asn_reader: Any | None
    logger: Logger
    wait: Callable[[float], Awaitable[bool]]
    generated_at: int


@dataclass(frozen=True, slots=True)
class MonitorCheckDependencies:
    """Injected callables for relay-check execution.

    The Monitor service passes its own module-level symbols into this
    bundle so tests that patch `bigbrotr.services.monitor.service.*`
    keep intercepting the same call sites after extraction.
    """

    retry_fetch: Callable[..., Awaitable[Any]]
    nip11_fetch: Callable[..., Awaitable[Any]]
    rtt_probe: Callable[..., Awaitable[Any]]
    ssl_probe: Callable[..., Awaitable[Any]]
    geo_probe: Callable[..., Awaitable[Any]]
    net_probe: Callable[..., Awaitable[Any]]
    dns_probe: Callable[..., Awaitable[Any]]
    http_probe: Callable[..., Awaitable[Any]]


def build_check_context(  # noqa: PLR0913
    *,
    relay: Relay,
    compute: MetadataFlags,
    timeout: float | None,
    proxy_url: str | None,
    allow_insecure: bool,
    nip11_info_max_size: int,
    retries: RetriesConfig,
    geohash_precision: int,
    keys: Keys,
    city_reader: Any | None,
    asn_reader: Any | None,
    logger: Logger,
    wait: Callable[[float], Awaitable[bool]],
    generated_at: int,
    networks: NetworksConfig,
) -> MonitorCheckContext:
    """Build the shared per-relay monitor check context."""
    network_config = networks.get(relay.network)
    return MonitorCheckContext(
        relay=relay,
        compute=compute,
        timeout=timeout if timeout is not None else network_config.timeout,
        proxy_url=proxy_url if proxy_url is not None else networks.get_proxy_url(relay.network),
        allow_insecure=allow_insecure,
        nip11_info_max_size=nip11_info_max_size,
        retries=retries,
        geohash_precision=geohash_precision,
        keys=keys,
        city_reader=city_reader,
        asn_reader=asn_reader,
        logger=logger,
        wait=wait,
        generated_at=generated_at,
    )


def build_check_dependencies(  # noqa: PLR0913
    *,
    retry_fetch: Callable[..., Awaitable[Any]],
    nip11_fetch: Callable[..., Awaitable[Any]],
    rtt_probe: Callable[..., Awaitable[Any]],
    ssl_probe: Callable[..., Awaitable[Any]],
    geo_probe: Callable[..., Awaitable[Any]],
    net_probe: Callable[..., Awaitable[Any]],
    dns_probe: Callable[..., Awaitable[Any]],
    http_probe: Callable[..., Awaitable[Any]],
) -> MonitorCheckDependencies:
    """Build the shared check dependency bundle for monitor relay probes."""
    return MonitorCheckDependencies(
        retry_fetch=retry_fetch,
        nip11_fetch=nip11_fetch,
        rtt_probe=rtt_probe,
        ssl_probe=ssl_probe,
        geo_probe=geo_probe,
        net_probe=net_probe,
        dns_probe=dns_probe,
        http_probe=http_probe,
    )


def _build_rtt_event_builder(
    relay: Relay,
    nip11_info: Nip11InfoMetadata | None,
) -> EventBuilder:
    """Build the RTT probe event, applying NIP-11 PoW hints when present."""
    event_builder = EventBuilder(Kind(EventKind.NIP66_TEST), "nip66-test").tags(
        [Tag.identifier(relay.url)]
    )
    if nip11_info and nip11_info.succeeded:
        pow_difficulty = nip11_info.data.limitation.min_pow_difficulty
        if pow_difficulty and pow_difficulty > 0:
            event_builder = event_builder.pow(pow_difficulty)
    return event_builder


def build_parallel_checks(
    context: MonitorCheckContext,
    dependencies: MonitorCheckDependencies,
) -> dict[str, Awaitable[Any]]:
    """Build retry-wrapped coroutines for independent relay health checks."""
    tasks: dict[str, Awaitable[Any]] = {}
    relay = context.relay
    compute = context.compute

    if compute.nip66_ssl and relay.network == NetworkType.CLEARNET:
        tasks["ssl"] = dependencies.retry_fetch(
            relay,
            lambda: dependencies.ssl_probe(relay, context.timeout),
            context.retries.nip66_ssl,
            "nip66_ssl",
            wait=context.wait,
        )
    if compute.nip66_dns and relay.network == NetworkType.CLEARNET:
        tasks["dns"] = dependencies.retry_fetch(
            relay,
            lambda: dependencies.dns_probe(relay, context.timeout),
            context.retries.nip66_dns,
            "nip66_dns",
            wait=context.wait,
        )
    if compute.nip66_geo and context.city_reader and relay.network == NetworkType.CLEARNET:
        city_reader = context.city_reader
        precision = context.geohash_precision
        tasks["geo"] = dependencies.retry_fetch(
            relay,
            lambda: dependencies.geo_probe(relay, city_reader, precision, timeout=context.timeout),
            context.retries.nip66_geo,
            "nip66_geo",
            wait=context.wait,
        )
    if compute.nip66_net and context.asn_reader and relay.network == NetworkType.CLEARNET:
        asn_reader = context.asn_reader
        tasks["net"] = dependencies.retry_fetch(
            relay,
            lambda: dependencies.net_probe(relay, asn_reader, timeout=context.timeout),
            context.retries.nip66_net,
            "nip66_net",
            wait=context.wait,
        )
    if compute.nip66_http:
        tasks["http"] = dependencies.retry_fetch(
            relay,
            lambda: dependencies.http_probe(
                relay,
                context.timeout,
                context.proxy_url,
                allow_insecure=context.allow_insecure,
            ),
            context.retries.nip66_http,
            "nip66_http",
            wait=context.wait,
        )

    return tasks


async def check_relay(
    context: MonitorCheckContext,
    dependencies: MonitorCheckDependencies,
) -> CheckResult:
    """Perform all configured health checks on a single relay."""
    empty = CheckResult()
    relay = context.relay
    compute = context.compute

    try:
        nip11_info = None
        if compute.nip11_info:

            async def _fetch_nip11() -> Any:
                return (
                    await dependencies.nip11_fetch(
                        relay,
                        timeout=context.timeout,
                        proxy_url=context.proxy_url,
                        options=Nip11Options(
                            allow_insecure=context.allow_insecure,
                            max_size=context.nip11_info_max_size,
                        ),
                    )
                ).info

            nip11_info = await dependencies.retry_fetch(
                relay,
                _fetch_nip11,
                context.retries.nip11_info,
                "nip11_info",
                wait=context.wait,
            )

        rtt_meta = None
        if compute.nip66_rtt:
            rtt_deps = Nip66RttDependencies(
                keys=context.keys,
                event_builder=_build_rtt_event_builder(relay, nip11_info),
                read_filter=Filter().limit(1),
            )
            rtt_meta = await dependencies.retry_fetch(
                relay,
                lambda: dependencies.rtt_probe(
                    relay,
                    rtt_deps,
                    context.timeout,
                    context.proxy_url,
                    allow_insecure=context.allow_insecure,
                ),
                context.retries.nip66_rtt,
                "nip66_rtt",
                wait=context.wait,
            )

        parallel_tasks = build_parallel_checks(context, dependencies)

        gathered: dict[str, Any] = {}
        if parallel_tasks:
            parallel_results = await asyncio.gather(
                *parallel_tasks.values(), return_exceptions=True
            )
            for result in parallel_results:
                if isinstance(result, asyncio.CancelledError):
                    raise result
            gathered = dict(zip(parallel_tasks.keys(), parallel_results, strict=True))

        result = CheckResult(
            generated_at=context.generated_at,
            nip11_info=nip11_info,
            nip66_rtt=rtt_meta,
            nip66_ssl=extract_result(gathered, "ssl"),
            nip66_geo=extract_result(gathered, "geo"),
            nip66_net=extract_result(gathered, "net"),
            nip66_dns=extract_result(gathered, "dns"),
            nip66_http=extract_result(gathered, "http"),
        )

        if result.has_data:
            context.logger.debug("check_succeeded", url=relay.url)
        else:
            context.logger.debug("check_failed", url=relay.url)

        return result

    except (TimeoutError, OSError) as exc:
        context.logger.debug("check_error", url=relay.url, error=str(exc))
        return empty
