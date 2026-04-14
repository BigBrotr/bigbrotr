"""
Top-level NIP-66 model with factory method and database serialization.

Orchestrates all [NIP-66](https://github.com/nostr-protocol/nips/blob/master/66.md)
monitoring tests (RTT, SSL, GEO, NET, DNS, HTTP) via the ``probe()``
async factory method, and provides ``to_relay_metadata_tuple()`` for
converting results into database-ready
[RelayMetadata][bigbrotr.models.relay_metadata.RelayMetadata] records.

See Also:
    [bigbrotr.nips.nip66.rtt.Nip66RttMetadata][bigbrotr.nips.nip66.rtt.Nip66RttMetadata]:
        RTT test implementation.
    [bigbrotr.nips.nip66.ssl.Nip66SslMetadata][bigbrotr.nips.nip66.ssl.Nip66SslMetadata]:
        SSL test implementation.
    [bigbrotr.nips.nip66.dns.Nip66DnsMetadata][bigbrotr.nips.nip66.dns.Nip66DnsMetadata]:
        DNS test implementation.
    [bigbrotr.nips.nip66.geo.Nip66GeoMetadata][bigbrotr.nips.nip66.geo.Nip66GeoMetadata]:
        Geolocation test implementation.
    [bigbrotr.nips.nip66.net.Nip66NetMetadata][bigbrotr.nips.nip66.net.Nip66NetMetadata]:
        Network/ASN test implementation.
    [bigbrotr.nips.nip66.http.Nip66HttpMetadata][bigbrotr.nips.nip66.http.Nip66HttpMetadata]:
        HTTP test implementation.
    [bigbrotr.models.metadata.MetadataType][bigbrotr.models.metadata.MetadataType]:
        Enum with ``NIP66_*`` variants for each test type.
    [bigbrotr.nips.nip11.nip11.Nip11][bigbrotr.nips.nip11.nip11.Nip11]:
        Companion NIP-11 model with the same factory/serialization pattern.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, NamedTuple

from nostr_sdk import EventBuilder, Filter, Keys, Kind

from bigbrotr.models.constants import EventKind
from bigbrotr.models.metadata import Metadata, MetadataType
from bigbrotr.models.relay import Relay  # noqa: TC001
from bigbrotr.models.relay_metadata import RelayMetadata
from bigbrotr.nips.base import (
    BaseNip,
    BaseNipDependencies,
    BaseNipMetadata,
    BaseNipOptions,
    BaseNipSelection,
)
from bigbrotr.utils.transport import DEFAULT_TIMEOUT

from .dns import Nip66DnsMetadata
from .geo import Nip66GeoMetadata
from .http import Nip66HttpMetadata
from .net import Nip66NetMetadata
from .rtt import Nip66RttDependencies, Nip66RttMetadata
from .ssl import Nip66SslMetadata


if TYPE_CHECKING:
    import geoip2.database


logger = logging.getLogger("bigbrotr.nips.nip66")


class Nip66Selection(BaseNipSelection):
    """Which NIP-66 checks to execute.

    All checks are enabled by default. Set individual fields to ``False``
    to skip specific test types during
    [Nip66.create][bigbrotr.nips.nip66.nip66.Nip66.create].

    See Also:
        [Nip66Options][bigbrotr.nips.nip66.nip66.Nip66Options]:
            Controls *how* tests are executed (e.g., allow insecure SSL).
        [Nip66Dependencies][bigbrotr.nips.nip66.nip66.Nip66Dependencies]:
            Provides optional dependencies required by specific tests.
    """

    rtt: bool = True
    ssl: bool = True
    geo: bool = True
    net: bool = True
    dns: bool = True
    http: bool = True


class Nip66Options(BaseNipOptions):
    """How to execute the NIP-66 checks.

    Inherits ``allow_insecure`` from
    [BaseNipOptions][bigbrotr.nips.base.BaseNipOptions].

    See Also:
        [Nip66Selection][bigbrotr.nips.nip66.nip66.Nip66Selection]:
            Controls *which* tests are executed.
        [bigbrotr.utils.transport.InsecureWebSocketTransport][bigbrotr.utils.transport.InsecureWebSocketTransport]:
            Transport used when ``allow_insecure`` triggers a fallback.
    """


def _default_keys() -> Keys:
    return Keys.generate()


def _default_event_builder() -> EventBuilder:
    return EventBuilder(Kind(EventKind.NIP66_TEST), "")


def _default_read_filter() -> Filter:
    return Filter().limit(1)


@dataclass(frozen=True, slots=True)
class Nip66Dependencies(BaseNipDependencies):
    """Optional dependencies for NIP-66 monitoring tests.

    RTT tests require ``keys``, ``event_builder``, and ``read_filter``.
    All three are auto-populated with sensible defaults when not provided:
    ``keys`` generates a throwaway keypair, ``event_builder`` creates a
    bare Kind 22456 event, and ``read_filter`` fetches a single event.
    Pass explicit values to override (e.g., for proof-of-work or custom filters).

    Geo/net tests require the corresponding GeoIP database readers and are
    silently skipped when those readers are ``None``.

    See Also:
        [bigbrotr.nips.nip66.rtt.Nip66RttDependencies][bigbrotr.nips.nip66.rtt.Nip66RttDependencies]:
            Focused dependency tuple for RTT-specific needs.
        [bigbrotr.utils.keys.load_keys_from_env][bigbrotr.utils.keys.load_keys_from_env]:
            Function used to load the signing keys.
    """

    keys: Keys = field(default_factory=_default_keys)
    event_builder: EventBuilder = field(default_factory=_default_event_builder)
    read_filter: Filter = field(default_factory=_default_read_filter)
    city_reader: geoip2.database.Reader | None = None
    asn_reader: geoip2.database.Reader | None = None


class RelayNip66MetadataTuple(NamedTuple):
    """Database-ready tuple of NIP-66 ``RelayMetadata`` records.

    Each field is ``None`` if the corresponding test was not run or
    was not applicable to the relay's network type. No ``nip66_`` prefix
    because this is a NIP-66-only container.

    See Also:
        [Nip66.to_relay_metadata_tuple][bigbrotr.nips.nip66.nip66.Nip66.to_relay_metadata_tuple]:
            Method that produces instances of this tuple.
        [bigbrotr.nips.nip11.nip11.RelayNip11MetadataTuple][bigbrotr.nips.nip11.nip11.RelayNip11MetadataTuple]:
            Companion tuple for NIP-11 metadata records.
    """

    rtt: RelayMetadata | None
    ssl: RelayMetadata | None
    geo: RelayMetadata | None
    net: RelayMetadata | None
    dns: RelayMetadata | None
    http: RelayMetadata | None


class Nip66(BaseNip):
    """NIP-66 relay monitoring data.

    Collects relay capability metrics including round-trip times, SSL
    certificate details, DNS records, HTTP headers, network/ASN info,
    and geolocation. Created via the ``probe()`` async factory method.

    Each metadata field is ``None`` when the corresponding test was
    skipped (disabled via selection, missing dependency, or inapplicable
    network type). No ``_metadata`` suffix because this is a NIP-66-only
    container where the field names are unambiguous.

    Attributes:
        relay: The [Relay][bigbrotr.models.relay.Relay] being monitored
            (inherited from [BaseNip][bigbrotr.nips.base.BaseNip]).
        rtt: RTT probe results (requires keys, event_builder, read_filter).
        ssl: SSL/TLS certificate data (clearnet only).
        geo: Geolocation data (requires GeoIP City database).
        net: Network/ASN data (requires GeoIP ASN database).
        dns: DNS resolution data (clearnet only).
        http: HTTP server headers.
        generated_at: Unix timestamp of when monitoring was performed
            (inherited from [BaseNip][bigbrotr.nips.base.BaseNip]).

    Note:
        The ``create()`` factory method runs all enabled tests concurrently
        via ``asyncio.gather(return_exceptions=True)``. Individual test
        failures are recorded in each test's logs field and never raised.
        Unexpected exceptions (bugs) are logged at ERROR level and the
        affected test field is set to ``None``.

    See Also:
        [bigbrotr.nips.nip11.nip11.Nip11][bigbrotr.nips.nip11.nip11.Nip11]:
            Companion NIP-11 model with the same factory/serialization pattern.
        [bigbrotr.services.monitor.Monitor][bigbrotr.services.monitor.Monitor]:
            Service that calls ``create()`` during health check cycles.
        [bigbrotr.nips.event_builders][bigbrotr.nips.event_builders]:
            Tag builder that converts results into kind 30166 event tags.

    Examples:
        ```python
        relay = Relay("wss://relay.damus.io")
        selection = Nip66Selection(rtt=False, geo=False, net=False)
        nip66 = await Nip66.create(relay, timeout=10.0, selection=selection)
        nip66.ssl is not None    # True (SSL test ran)
        nip66.rtt is None        # True (RTT was disabled)
        records = nip66.to_relay_metadata_tuple()
        ```
    """

    rtt: Nip66RttMetadata | None = None
    ssl: Nip66SslMetadata | None = None
    geo: Nip66GeoMetadata | None = None
    net: Nip66NetMetadata | None = None
    dns: Nip66DnsMetadata | None = None
    http: Nip66HttpMetadata | None = None

    def to_relay_metadata_tuple(self) -> RelayNip66MetadataTuple:
        """Convert to a ``RelayMetadata`` tuple for database storage.

        Returns:
            A [RelayNip66MetadataTuple][bigbrotr.nips.nip66.nip66.RelayNip66MetadataTuple]
            with one [RelayMetadata][bigbrotr.models.relay_metadata.RelayMetadata]
            per test that produced results, or ``None`` for tests that were
            skipped. Each record is tagged with the corresponding
            [MetadataType][bigbrotr.models.metadata.MetadataType] variant
            (``NIP66_RTT``, ``NIP66_SSL``, etc.).
        """

        def make(
            metadata: BaseNipMetadata | None, metadata_type: MetadataType
        ) -> RelayMetadata | None:
            if metadata is None:
                return None
            return RelayMetadata(
                relay=self.relay,
                metadata=Metadata(type=metadata_type, data=metadata.to_dict()),
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

    @classmethod
    async def probe(  # noqa: PLR0913
        cls,
        relay: Relay,
        *,
        timeout: float | None = None,  # noqa: ASYNC109
        proxy_url: str | None = None,
        selection: Nip66Selection | None = None,
        options: Nip66Options | None = None,
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
        selection = selection or Nip66Selection()
        options = options or Nip66Options()
        deps = deps or Nip66Dependencies()
        timeout = timeout if timeout is not None else DEFAULT_TIMEOUT
        logger.debug("probe_started relay=%s timeout_s=%s", relay.url, timeout)

        tasks: list[Any] = []
        task_names: list[str] = []

        if selection.rtt:
            rtt_deps = Nip66RttDependencies(
                keys=deps.keys,
                event_builder=deps.event_builder,
                read_filter=deps.read_filter,
            )
            tasks.append(
                Nip66RttMetadata.probe(
                    relay,
                    rtt_deps,
                    timeout,
                    proxy_url,
                    allow_insecure=options.allow_insecure,
                )
            )
            task_names.append("rtt")

        if selection.ssl:
            tasks.append(Nip66SslMetadata.probe(relay, timeout))
            task_names.append("ssl")

        if selection.geo and deps.city_reader:
            tasks.append(Nip66GeoMetadata.probe(relay, deps.city_reader))
            task_names.append("geo")

        if selection.net and deps.asn_reader:
            tasks.append(Nip66NetMetadata.probe(relay, deps.asn_reader))
            task_names.append("net")

        if selection.dns:
            tasks.append(Nip66DnsMetadata.probe(relay, timeout))
            task_names.append("dns")

        if selection.http:
            tasks.append(
                Nip66HttpMetadata.probe(
                    relay, timeout, proxy_url, allow_insecure=options.allow_insecure
                )
            )
            task_names.append("http")

        logger.debug("probe_running tests=%s", task_names)
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Map each result to its corresponding metadata field
        metadata_map: dict[str, Any] = {}
        for name, result in zip(task_names, results, strict=True):
            if isinstance(result, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
                raise result
            if isinstance(result, BaseException):
                logger.error("probe_task_failed test=%s error=%r", name, result)
                metadata_map[name] = None
            else:
                logger.debug("probe_task_succeeded test=%s", name)
                metadata_map[name] = result

        nip66 = cls(relay=relay, **metadata_map)
        logger.debug(
            "probe_completed relay=%s rtt=%s ssl=%s geo=%s net=%s dns=%s http=%s",
            relay.url,
            nip66.rtt is not None,
            nip66.ssl is not None,
            nip66.geo is not None,
            nip66.net is not None,
            nip66.dns is not None,
            nip66.http is not None,
        )
        return nip66

    @classmethod
    async def create(  # type: ignore[override]  # noqa: PLR0913  # NIP-specific params widen base signature
        cls,
        relay: Relay,
        *,
        timeout: float | None = None,  # noqa: ASYNC109
        proxy_url: str | None = None,
        selection: Nip66Selection | None = None,
        options: Nip66Options | None = None,
        deps: Nip66Dependencies | None = None,
    ) -> Nip66:
        """Compatibility alias for the semantic ``probe()`` entrypoint."""
        return await cls.probe(
            relay,
            timeout=timeout,
            proxy_url=proxy_url,
            selection=selection,
            options=options,
            deps=deps,
        )
