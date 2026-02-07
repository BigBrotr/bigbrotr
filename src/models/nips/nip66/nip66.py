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

from models.metadata import Metadata, MetadataType
from models.nips.base import DEFAULT_TIMEOUT, BaseMetadata
from models.relay import Relay
from models.relay_metadata import RelayMetadata

from .dns import Nip66DnsMetadata
from .geo import Nip66GeoMetadata
from .http import Nip66HttpMetadata
from .net import Nip66NetMetadata
from .rtt import Nip66RttMetadata
from .ssl import Nip66SslMetadata


if TYPE_CHECKING:
    import geoip2.database
    from nostr_sdk import EventBuilder, Filter, Keys


logger = logging.getLogger("models.nip66")


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
        timeout: float | None = None,
        proxy_url: str | None = None,
        allow_insecure: bool = True,
        run_rtt: bool = True,
        run_ssl: bool = True,
        run_geo: bool = True,
        run_net: bool = True,
        run_dns: bool = True,
        run_http: bool = True,
        keys: Keys | None = None,
        event_builder: EventBuilder | None = None,
        read_filter: Filter | None = None,
        city_reader: geoip2.database.Reader | None = None,
        asn_reader: geoip2.database.Reader | None = None,
    ) -> Nip66:
        """Run monitoring tests against a relay and collect results.

        All tests are enabled by default. Individual tests can be disabled
        via the ``run_*`` flags. Some tests require additional parameters
        (keys for RTT, GeoIP readers for geo/net) and are silently skipped
        when those parameters are not provided.

        Args:
            relay: Relay to test.
            timeout: Connection timeout in seconds (default: 10.0).
            proxy_url: Optional SOCKS5 proxy URL for overlay networks.
            allow_insecure: Fall back to unverified SSL for clearnet relays
                with invalid certificates (default: True).
            run_rtt: Enable the RTT probe test.
            run_ssl: Enable the SSL certificate test.
            run_geo: Enable the geolocation lookup test.
            run_net: Enable the network/ASN lookup test.
            run_dns: Enable the DNS resolution test.
            run_http: Enable the HTTP header extraction test.
            keys: Signing keys for RTT write test events.
            event_builder: Builder for the RTT write test event.
            read_filter: Subscription filter for the RTT read test.
            city_reader: GeoLite2-City database reader for geo test.
            asn_reader: GeoLite2-ASN database reader for net test.

        Returns:
            A populated ``Nip66`` instance with test results.
        """
        timeout = timeout if timeout is not None else DEFAULT_TIMEOUT
        logger.debug("create_started relay=%s timeout_s=%s", relay.url, timeout)

        tasks: list[Any] = []
        task_names: list[str] = []

        # RTT requires all three parameters (keys, event_builder, read_filter)
        if run_rtt and keys and event_builder and read_filter:
            tasks.append(
                Nip66RttMetadata.rtt(
                    relay,
                    keys,
                    event_builder,
                    read_filter,
                    timeout,
                    proxy_url,
                    allow_insecure,
                )
            )
            task_names.append("rtt")

        if run_ssl:
            tasks.append(Nip66SslMetadata.ssl(relay, timeout))
            task_names.append("ssl")

        if run_geo and city_reader:
            tasks.append(Nip66GeoMetadata.geo(relay, city_reader))
            task_names.append("geo")

        if run_net and asn_reader:
            tasks.append(Nip66NetMetadata.net(relay, asn_reader))
            task_names.append("net")

        if run_dns:
            tasks.append(Nip66DnsMetadata.dns(relay, timeout))
            task_names.append("dns")

        if run_http:
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
