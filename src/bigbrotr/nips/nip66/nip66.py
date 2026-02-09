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
from time import time
from typing import TYPE_CHECKING, Any, NamedTuple

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from bigbrotr.models.constants import DEFAULT_TIMEOUT
from bigbrotr.models.metadata import Metadata, MetadataType
from bigbrotr.models.relay import Relay  # noqa: TC001
from bigbrotr.models.relay_metadata import RelayMetadata
from bigbrotr.nips.base import BaseMetadata  # noqa: TC001

from .dns import Nip66DnsMetadata
from .geo import Nip66GeoMetadata
from .http import Nip66HttpMetadata
from .net import Nip66NetMetadata
from .rtt import Nip66RttDependencies, Nip66RttMetadata
from .ssl import Nip66SslMetadata


if TYPE_CHECKING:
    import geoip2.database
    from nostr_sdk import EventBuilder, Filter, Keys


logger = logging.getLogger("bigbrotr.nips.nip66")


class Nip66TestSelection(BaseModel):
    """Which NIP-66 checks to execute.

    All checks are enabled by default. Set individual fields to ``False``
    to skip specific test types during ``Nip66.create()``.
    """

    rtt: bool = True
    ssl: bool = True
    geo: bool = True
    net: bool = True
    dns: bool = True
    http: bool = True


class Nip66TestOptions(BaseModel):
    """How to execute the NIP-66 checks.

    Attributes:
        allow_insecure: Fall back to unverified SSL for clearnet relays
            with invalid certificates (default: False). Used by RTT.
    """

    allow_insecure: bool = False


# Backwards-compatible alias
Nip66TestFlags = Nip66TestSelection


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
    was not applicable to the relay's network type. No ``nip66_`` prefix
    because this is a NIP-66-only container.
    """

    rtt: RelayMetadata | None
    ssl: RelayMetadata | None
    geo: RelayMetadata | None
    net: RelayMetadata | None
    dns: RelayMetadata | None
    http: RelayMetadata | None


class Nip66(BaseModel):
    """NIP-66 relay monitoring data.

    Collects relay capability metrics including round-trip times, SSL
    certificate details, DNS records, HTTP headers, network/ASN info,
    and geolocation. Created via the ``create()`` async factory method.

    Each metadata field is ``None`` when the corresponding test was
    skipped (disabled via selection, missing dependency, or inapplicable
    network type). No ``_metadata`` suffix because this is a NIP-66-only
    container where the field names are unambiguous.

    Attributes:
        relay: The relay being monitored.
        rtt: RTT probe results (requires keys, event_builder, read_filter).
        ssl: SSL/TLS certificate data (clearnet only).
        geo: Geolocation data (requires GeoIP City database).
        net: Network/ASN data (requires GeoIP ASN database).
        dns: DNS resolution data (clearnet only).
        http: HTTP server headers.
        generated_at: Unix timestamp of when monitoring was performed.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    relay: Relay
    rtt: Nip66RttMetadata | None = None
    ssl: Nip66SslMetadata | None = None
    geo: Nip66GeoMetadata | None = None
    net: Nip66NetMetadata | None = None
    dns: Nip66DnsMetadata | None = None
    http: Nip66HttpMetadata | None = None
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
            rtt=make(self.rtt, MetadataType.NIP66_RTT),
            ssl=make(self.ssl, MetadataType.NIP66_SSL),
            geo=make(self.geo, MetadataType.NIP66_GEO),
            net=make(self.net, MetadataType.NIP66_NET),
            dns=make(self.dns, MetadataType.NIP66_DNS),
            http=make(self.http, MetadataType.NIP66_HTTP),
        )

    # -------------------------------------------------------------------------
    # Factory Method
    # -------------------------------------------------------------------------

    @classmethod
    async def create(  # noqa: PLR0913
        cls,
        relay: Relay,
        *,
        timeout: float | None = None,  # noqa: ASYNC109
        proxy_url: str | None = None,
        selection: Nip66TestSelection | None = None,
        options: Nip66TestOptions | None = None,
        deps: Nip66Dependencies | None = None,
    ) -> Nip66:
        """Run monitoring tests against a relay and collect results.

        All tests are enabled by default. Individual tests can be disabled
        via the ``selection`` parameter. Execution behavior can be tuned
        via the ``options`` parameter. Some tests require additional
        dependencies (keys for RTT, GeoIP readers for geo/net) provided
        via ``deps``, and are silently skipped when those dependencies
        are not provided.

        Args:
            relay: Relay to test.
            timeout: Connection timeout in seconds (default: 10.0).
            proxy_url: Optional SOCKS5 proxy URL for overlay networks.
            selection: Which tests to run (default: all enabled).
            options: How to execute the tests (default: secure mode).
            deps: Optional dependencies for RTT, geo, and net tests.

        Returns:
            A populated ``Nip66`` instance with test results.
        """
        selection = selection or Nip66TestSelection()
        options = options or Nip66TestOptions()
        deps = deps or Nip66Dependencies()
        timeout = timeout if timeout is not None else DEFAULT_TIMEOUT
        logger.debug("create_started relay=%s timeout_s=%s", relay.url, timeout)

        tasks: list[Any] = []
        task_names: list[str] = []

        # RTT requires all three parameters (keys, event_builder, read_filter)
        if selection.rtt and deps.keys and deps.event_builder and deps.read_filter:
            rtt_deps = Nip66RttDependencies(
                keys=deps.keys,
                event_builder=deps.event_builder,
                read_filter=deps.read_filter,
            )
            tasks.append(
                Nip66RttMetadata.execute(
                    relay,
                    rtt_deps,
                    timeout,
                    proxy_url,
                    allow_insecure=options.allow_insecure,
                )
            )
            task_names.append("rtt")

        if selection.ssl:
            tasks.append(Nip66SslMetadata.execute(relay, timeout))
            task_names.append("ssl")

        if selection.geo and deps.city_reader:
            tasks.append(Nip66GeoMetadata.execute(relay, deps.city_reader))
            task_names.append("geo")

        if selection.net and deps.asn_reader:
            tasks.append(Nip66NetMetadata.execute(relay, deps.asn_reader))
            task_names.append("net")

        if selection.dns:
            tasks.append(Nip66DnsMetadata.execute(relay, timeout))
            task_names.append("dns")

        if selection.http:
            tasks.append(Nip66HttpMetadata.execute(relay, timeout, proxy_url))
            task_names.append("http")

        logger.debug("create_running tests=%s", task_names)
        results = await asyncio.gather(*tasks)

        # Map each result to its corresponding metadata field
        metadata_map: dict[str, Any] = {}
        for name, result in zip(task_names, results, strict=True):
            logger.debug("create_task_succeeded test=%s", name)
            metadata_map[name] = result

        nip66 = cls(relay=relay, **metadata_map)
        logger.debug(
            "create_completed relay=%s rtt=%s ssl=%s geo=%s net=%s dns=%s http=%s",
            relay.url,
            nip66.rtt is not None,
            nip66.ssl is not None,
            nip66.geo is not None,
            nip66.net is not None,
            nip66.dns is not None,
            nip66.http is not None,
        )
        return nip66
