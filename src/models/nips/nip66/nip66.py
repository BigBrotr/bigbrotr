"""
Top-level NIP-66 model with factory method and database serialization.

Orchestrates all NIP-66 monitoring tests (RTT, SSL, GEO, NET, DNS, HTTP)
via the ``create()`` async factory method, and provides
``to_relay_metadata_tuple()`` for converting results into database-ready
``RelayMetadata`` records.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from time import time
from typing import TYPE_CHECKING, Any, NamedTuple

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from models.constants import DEFAULT_TIMEOUT
from models.metadata import Metadata, MetadataType
from models.nips.base import BaseMetadata  # noqa: TC001
from models.relay import Relay  # noqa: TC001
from models.relay_metadata import RelayMetadata

from .dns import Nip66DnsMetadata
from .geo import Nip66GeoMetadata
from .http import Nip66HttpMetadata
from .net import Nip66NetMetadata
from .rtt import Nip66RttMetadata, RttDependencies
from .ssl import Nip66SslMetadata


if TYPE_CHECKING:
    import geoip2.database
    from nostr_sdk import EventBuilder, Filter, Keys


logger = logging.getLogger("models.nip66")


@dataclass(frozen=True, slots=True)
class Nip66TestFlags:
    """Boolean flags controlling which NIP-66 tests to run.

    All tests are enabled by default. Set individual flags to ``False``
    to skip specific test types during ``Nip66.create()``.

    Attributes:
        allow_insecure: Fall back to unverified SSL for clearnet relays
            with invalid certificates (default: True). Used by RTT.
    """

    run_rtt: bool = True
    run_ssl: bool = True
    run_geo: bool = True
    run_net: bool = True
    run_dns: bool = True
    run_http: bool = True
    allow_insecure: bool = True


class Nip66Dependencies(NamedTuple):
    """Optional dependencies for NIP-66 monitoring tests.

    All fields default to ``None``. RTT tests require ``keys``,
    ``event_builder``, and ``read_filter``. Geo/net tests require
    the corresponding GeoIP database readers.
    """

    keys: Keys | None = None
    event_builder: EventBuilder | None = None
    read_filter: Filter | None = None
    city_reader: geoip2.database.Reader | None = None
    asn_reader: geoip2.database.Reader | None = None


class RelayNip66MetadataTuple(NamedTuple):
    """Database-ready tuple of NIP-66 RelayMetadata records.

    Each field is ``None`` if the corresponding test was not run or
    was not applicable to the relay's network type.
    """

    nip66_rtt: RelayMetadata | None
    nip66_ssl: RelayMetadata | None
    nip66_geo: RelayMetadata | None
    nip66_net: RelayMetadata | None
    nip66_dns: RelayMetadata | None
    nip66_http: RelayMetadata | None


class Nip66(BaseModel):
    """NIP-66 relay monitoring data.

    Collects relay capability metrics including round-trip times, SSL
    certificate details, DNS records, HTTP headers, network/ASN info,
    and geolocation. Created via the ``create()`` async factory method.

    Each metadata field is ``None`` when the corresponding test was
    skipped (disabled via flag, missing dependency, or inapplicable
    network type).

    Attributes:
        relay: The relay being monitored.
        rtt_metadata: RTT probe results (requires keys, event_builder, read_filter).
        ssl_metadata: SSL/TLS certificate data (clearnet only).
        geo_metadata: Geolocation data (requires GeoIP City database).
        net_metadata: Network/ASN data (requires GeoIP ASN database).
        dns_metadata: DNS resolution data (clearnet only).
        http_metadata: HTTP server headers.
        generated_at: Unix timestamp of when monitoring was performed.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    relay: Relay
    rtt_metadata: Nip66RttMetadata | None = None
    ssl_metadata: Nip66SslMetadata | None = None
    geo_metadata: Nip66GeoMetadata | None = None
    net_metadata: Nip66NetMetadata | None = None
    dns_metadata: Nip66DnsMetadata | None = None
    http_metadata: Nip66HttpMetadata | None = None
    generated_at: StrictInt = Field(default_factory=lambda: int(time()), ge=0)

    # -------------------------------------------------------------------------
    # Database Serialization
    # -------------------------------------------------------------------------

    def to_relay_metadata_tuple(self) -> RelayNip66MetadataTuple:
        """Convert to a tuple of RelayMetadata records for database storage.

        Returns:
            A ``RelayNip66MetadataTuple`` with one ``RelayMetadata`` per test
            that produced results, or ``None`` for tests that were skipped.
        """

        def make(
            metadata: BaseMetadata | None, metadata_type: MetadataType
        ) -> RelayMetadata | None:
            if metadata is None:
                return None
            return RelayMetadata(
                relay=self.relay,
                metadata=Metadata(type=metadata_type, value=metadata.to_dict()),
                generated_at=self.generated_at,
            )

        return RelayNip66MetadataTuple(
            nip66_rtt=make(self.rtt_metadata, MetadataType.NIP66_RTT),
            nip66_ssl=make(self.ssl_metadata, MetadataType.NIP66_SSL),
            nip66_geo=make(self.geo_metadata, MetadataType.NIP66_GEO),
            nip66_net=make(self.net_metadata, MetadataType.NIP66_NET),
            nip66_dns=make(self.dns_metadata, MetadataType.NIP66_DNS),
            nip66_http=make(self.http_metadata, MetadataType.NIP66_HTTP),
        )

    # -------------------------------------------------------------------------
    # Factory Method
    # -------------------------------------------------------------------------

    @classmethod
    async def create(
        cls,
        relay: Relay,
        *,
        timeout: float | None = None,  # noqa: ASYNC109
        proxy_url: str | None = None,
        flags: Nip66TestFlags | None = None,
        deps: Nip66Dependencies | None = None,
    ) -> Nip66:
        """Run monitoring tests against a relay and collect results.

        All tests are enabled by default. Individual tests can be disabled
        via the ``flags`` parameter. Some tests require additional dependencies
        (keys for RTT, GeoIP readers for geo/net) provided via ``deps``,
        and are silently skipped when those dependencies are not provided.

        Args:
            relay: Relay to test.
            timeout: Connection timeout in seconds (default: 10.0).
            proxy_url: Optional SOCKS5 proxy URL for overlay networks.
            flags: Test flags controlling which tests to run (default: all enabled).
            deps: Optional dependencies for RTT, geo, and net tests.

        Returns:
            A populated ``Nip66`` instance with test results.
        """
        flags = flags or Nip66TestFlags()
        deps = deps or Nip66Dependencies()
        timeout = timeout if timeout is not None else DEFAULT_TIMEOUT
        logger.debug("create_started relay=%s timeout_s=%s", relay.url, timeout)

        tasks: list[Any] = []
        task_names: list[str] = []

        # RTT requires all three parameters (keys, event_builder, read_filter)
        if flags.run_rtt and deps.keys and deps.event_builder and deps.read_filter:
            rtt_deps = RttDependencies(
                keys=deps.keys,
                event_builder=deps.event_builder,
                read_filter=deps.read_filter,
            )
            tasks.append(
                Nip66RttMetadata.rtt(
                    relay,
                    rtt_deps,
                    timeout,
                    proxy_url,
                    flags.allow_insecure,
                )
            )
            task_names.append("rtt")

        if flags.run_ssl:
            tasks.append(Nip66SslMetadata.ssl(relay, timeout))
            task_names.append("ssl")

        if flags.run_geo and deps.city_reader:
            tasks.append(Nip66GeoMetadata.geo(relay, deps.city_reader))
            task_names.append("geo")

        if flags.run_net and deps.asn_reader:
            tasks.append(Nip66NetMetadata.net(relay, deps.asn_reader))
            task_names.append("net")

        if flags.run_dns:
            tasks.append(Nip66DnsMetadata.dns(relay, timeout))
            task_names.append("dns")

        if flags.run_http:
            tasks.append(Nip66HttpMetadata.http(relay, timeout, proxy_url))
            task_names.append("http")

        logger.debug("create_running tests=%s", task_names)
        results = await asyncio.gather(*tasks)

        # Map each result to its corresponding metadata field
        metadata_map: dict[str, Any] = {}
        for name, result in zip(task_names, results, strict=True):
            logger.debug("create_task_succeeded test=%s", name)
            metadata_map[f"{name}_metadata"] = result

        nip66 = cls(relay=relay, **metadata_map)
        logger.debug(
            "create_completed relay=%s rtt=%s ssl=%s geo=%s net=%s dns=%s http=%s",
            relay.url,
            nip66.rtt_metadata is not None,
            nip66.ssl_metadata is not None,
            nip66.geo_metadata is not None,
            nip66.net_metadata is not None,
            nip66.dns_metadata is not None,
            nip66.http_metadata is not None,
        )
        return nip66
