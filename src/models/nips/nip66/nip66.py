"""NIP-66 main class and database tuple."""

from __future__ import annotations

import asyncio
from time import time
from typing import TYPE_CHECKING, Any, NamedTuple

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from core.logger import Logger
from models.metadata import Metadata
from models.nips.base import DEFAULT_TIMEOUT
from models.relay import Relay  # noqa: TC001 - Pydantic needs at runtime
from models.relay_metadata import MetadataType, RelayMetadata

from .dns import Nip66DnsMetadata
from .geo import Nip66GeoMetadata
from .http import Nip66HttpMetadata
from .net import Nip66NetMetadata
from .rtt import Nip66RttMetadata
from .ssl import Nip66SslMetadata


if TYPE_CHECKING:
    import geoip2.database
    from nostr_sdk import EventBuilder, Filter, Keys


logger = Logger("models.nip66")


class RelayNip66MetadataTuple(NamedTuple):
    """Tuple of RelayMetadata records for database storage."""

    nip66_rtt: RelayMetadata | None
    nip66_ssl: RelayMetadata | None
    nip66_geo: RelayMetadata | None
    nip66_net: RelayMetadata | None
    nip66_dns: RelayMetadata | None
    nip66_http: RelayMetadata | None


class Nip66(BaseModel):
    """
    Immutable NIP-66 relay monitoring data.

    Tests relay capabilities (open, read, write) and collects monitoring metrics
    including round-trip times, SSL certificate data, DNS records, HTTP headers,
    network info, and geolocation info.

    Always created via create() - never returns None.
    Check individual metadata fields for availability.

    Attributes:
        relay: The Relay being monitored.
        rtt_metadata: RTT data with probe logs (optional, requires keys/event_builder/read_filter).
        ssl_metadata: SSL/TLS certificate data (optional, clearnet wss:// only).
        geo_metadata: Geolocation data (optional, requires GeoIP City database).
        net_metadata: Network data (optional, requires GeoIP ASN database).
        dns_metadata: DNS resolution data (optional, clearnet only).
        http_metadata: HTTP headers data (optional, from WebSocket upgrade).
        generated_at: Unix timestamp when monitoring was performed (default: now).
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
    # Serialization
    # -------------------------------------------------------------------------

    def to_relay_metadata_tuple(self) -> RelayNip66MetadataTuple:
        """Convert to RelayNip66MetadataTuple for database storage."""

        def make(metadata: BaseModel | None, metadata_type: MetadataType) -> RelayMetadata | None:
            if metadata is None:
                return None
            return RelayMetadata(
                relay=self.relay,
                metadata=Metadata(metadata.to_dict()),  # type: ignore[attr-defined]
                metadata_type=metadata_type,
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
        timeout: float | None = None,
        keys: Keys | None = None,
        event_builder: EventBuilder | None = None,
        read_filter: Filter | None = None,
        city_reader: geoip2.database.Reader | None = None,
        asn_reader: geoip2.database.Reader | None = None,
        run_rtt: bool = True,
        run_ssl: bool = True,
        run_geo: bool = True,
        run_net: bool = True,
        run_dns: bool = True,
        run_http: bool = True,
        proxy_url: str | None = None,
        allow_insecure: bool = True,
    ) -> Nip66:
        """
        Create NIP-66 monitoring data by testing relay.

        All tests are enabled by default. Disable specific tests with run_* flags.

        Args:
            relay: Relay object to test
            timeout: Connection timeout in seconds (default: 10.0)
            keys: Keys for signing test events (required for RTT test)
            event_builder: EventBuilder for write test (required for RTT test)
            read_filter: Filter for read test (required for RTT test)
            city_reader: Pre-opened GeoLite2-City database reader (required if run_geo=True)
            asn_reader: Pre-opened GeoLite2-ASN database reader (required if run_net=True)
            run_rtt: Collect RTT timing and probe data (open/read/write tests).
            run_ssl: Run SSL certificate test (clearnet only)
            run_geo: Run geolocation test. Requires city_reader. Clearnet only.
            run_net: Run network/ASN test. Requires asn_reader. Clearnet only.
            run_dns: Run DNS resolution test (clearnet only)
            run_http: Run HTTP headers test (clearnet, or overlay with proxy)
            proxy_url: Optional SOCKS5 proxy URL for overlay networks (Tor, I2P, Loki)
            allow_insecure: If True (default), fallback to insecure transport for
                clearnet relays with invalid SSL certificates.

        Returns:
            Nip66 instance with test results

        Raises:
            ValueError: If test is not applicable (e.g., clearnet-only test on overlay relay)

        Example::

            nip66 = await Nip66.create(
                relay,
                keys=keys,
                event_builder=event_builder,
                read_filter=read_filter,
                city_reader=city_reader,
                asn_reader=asn_reader,
            )
            if nip66.rtt_metadata:
                print(f"Open RTT: {nip66.rtt_metadata.data.rtt_open}ms")
        """
        timeout = timeout if timeout is not None else DEFAULT_TIMEOUT
        logger.debug("create_started", relay=relay.url, timeout_s=timeout)

        # Build tasks using *Metadata.method() calls
        tasks: list[Any] = []
        task_names: list[str] = []

        if run_rtt and keys is not None and event_builder is not None and read_filter is not None:
            tasks.append(
                Nip66RttMetadata.rtt(
                    relay, keys, event_builder, read_filter, timeout, proxy_url, allow_insecure
                )
            )
            task_names.append("rtt")

        if run_ssl:
            tasks.append(Nip66SslMetadata.ssl(relay, timeout))
            task_names.append("ssl")

        if run_geo and city_reader is not None:
            tasks.append(Nip66GeoMetadata.geo(relay, city_reader))
            task_names.append("geo")

        if run_net and asn_reader is not None:
            tasks.append(Nip66NetMetadata.net(relay, asn_reader))
            task_names.append("net")

        if run_dns:
            tasks.append(Nip66DnsMetadata.dns(relay, timeout))
            task_names.append("dns")

        if run_http:
            tasks.append(Nip66HttpMetadata.http(relay, timeout, proxy_url))
            task_names.append("http")

        logger.debug("create_running", tests=task_names)
        results = await asyncio.gather(*tasks)

        # Map results to metadata fields
        metadata_map: dict[str, Any] = {}
        for name, result in zip(task_names, results, strict=True):
            logger.debug("create_task_succeeded", test=name)
            metadata_map[f"{name}_metadata"] = result

        nip66 = cls(relay=relay, **metadata_map)
        logger.debug(
            "create_completed",
            relay=relay.url,
            has_rtt=nip66.rtt_metadata is not None,
            has_ssl=nip66.ssl_metadata is not None,
            has_geo=nip66.geo_metadata is not None,
            has_net=nip66.net_metadata is not None,
            has_dns=nip66.dns_metadata is not None,
            has_http=nip66.http_metadata is not None,
        )
        return nip66
