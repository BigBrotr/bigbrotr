"""
NIP-66 DNS metadata container with resolution capabilities.

Performs comprehensive DNS resolution for a relay hostname, including
A, AAAA, CNAME, NS, and PTR record lookups as part of
[NIP-66](https://github.com/nostr-protocol/nips/blob/master/66.md)
monitoring. Clearnet relays only.

Note:
    Unlike the simpler [resolve_host][bigbrotr.utils.dns.resolve_host]
    utility (which uses the system resolver for A/AAAA only), this module
    uses the ``dnspython`` library for comprehensive record collection.
    Individual record type lookups are wrapped in exception suppression so
    that a failure in one type does not prevent the others from being
    collected.

    NS records are resolved against the **registered domain** (e.g.,
    ``damus.io`` for ``relay.damus.io``) using ``tldextract`` to identify
    the public suffix boundary. Reverse DNS (PTR) uses the first resolved
    IPv4 address.

See Also:
    [bigbrotr.nips.nip66.data.Nip66DnsData][bigbrotr.nips.nip66.data.Nip66DnsData]:
        Data model for DNS resolution results.
    [bigbrotr.nips.nip66.logs.Nip66DnsLogs][bigbrotr.nips.nip66.logs.Nip66DnsLogs]:
        Log model for DNS resolution results.
    [bigbrotr.utils.dns.resolve_host][bigbrotr.utils.dns.resolve_host]:
        Simpler A/AAAA-only resolution used by geo and net tests.
    [bigbrotr.nips.nip66.geo.Nip66GeoMetadata][bigbrotr.nips.nip66.geo.Nip66GeoMetadata]:
        Geolocation test that depends on IP resolution.
    [bigbrotr.nips.nip66.net.Nip66NetMetadata][bigbrotr.nips.nip66.net.Nip66NetMetadata]:
        Network/ASN test that depends on IP resolution.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any, Self, cast

import dns.exception
import dns.resolver
import tldextract


if TYPE_CHECKING:
    from dns.rdtypes.ANY.CNAME import CNAME
    from dns.rdtypes.ANY.NS import NS
    from dns.rdtypes.ANY.PTR import PTR
    from dns.rdtypes.IN.A import A
    from dns.rdtypes.IN.AAAA import AAAA

from bigbrotr.models.constants import NetworkType
from bigbrotr.models.relay import Relay  # noqa: TC001
from bigbrotr.nips.base import BaseNipMetadata
from bigbrotr.utils.transport import DEFAULT_TIMEOUT

from .data import Nip66DnsData
from .logs import Nip66DnsLogs


logger = logging.getLogger("bigbrotr.nips.nip66")


class Nip66DnsMetadata(BaseNipMetadata):
    """Container for DNS resolution data and operation logs.

    Provides the ``execute()`` class method that performs a comprehensive
    set of DNS queries (A, AAAA, CNAME, NS, reverse PTR) for a relay
    hostname.

    See Also:
        [bigbrotr.nips.nip66.nip66.Nip66][bigbrotr.nips.nip66.nip66.Nip66]:
            Top-level model that orchestrates this alongside other tests.
        [bigbrotr.models.metadata.MetadataType][bigbrotr.models.metadata.MetadataType]:
            The ``NIP66_DNS`` variant used when storing these results.
    """

    data: Nip66DnsData
    logs: Nip66DnsLogs

    # -------------------------------------------------------------------------
    # DNS Resolution
    # -------------------------------------------------------------------------

    @staticmethod
    def _dns(host: str, timeout: float) -> dict[str, Any]:
        """Perform synchronous DNS resolution across multiple record types.

        Individual record lookups are wrapped in exception suppression so
        that a failure in one type does not prevent the others from being
        collected.

        Args:
            host: Hostname to resolve.
            timeout: Resolver timeout in seconds.

        Returns:
            Dictionary of DNS fields (IPs, CNAME, NS, PTR, TTL).
        """
        result: dict[str, Any] = {}
        resolver = dns.resolver.Resolver()
        resolver.timeout = timeout
        resolver.lifetime = timeout

        _dns_errors = (OSError, dns.exception.DNSException)

        # A records (IPv4)
        with contextlib.suppress(*_dns_errors):
            answers = resolver.resolve(host, "A")
            ips = [cast("A", rdata).address for rdata in answers]
            if ips:
                result["dns_ips"] = ips
                if answers.rrset:
                    result["dns_ttl"] = answers.rrset.ttl

        # AAAA records (IPv6)
        with contextlib.suppress(*_dns_errors):
            answers = resolver.resolve(host, "AAAA")
            ips_v6 = [cast("AAAA", rdata).address for rdata in answers]
            if ips_v6:
                result["dns_ips_v6"] = ips_v6

        # CNAME record
        with contextlib.suppress(*_dns_errors):
            answers = resolver.resolve(host, "CNAME")
            for rdata in answers:
                result["dns_cname"] = str(cast("CNAME", rdata).target).rstrip(".")
                break

        # NS records (resolved against the registered domain)
        with contextlib.suppress(*_dns_errors):
            ext = tldextract.extract(host)
            if ext.domain and ext.suffix:
                domain = f"{ext.domain}.{ext.suffix}"
                answers = resolver.resolve(domain, "NS")
                ns_list = [str(cast("NS", rdata).target).rstrip(".") for rdata in answers]
                if ns_list:
                    result["dns_ns"] = ns_list

        # Reverse DNS (PTR) using the first resolved IPv4 address
        if result.get("dns_ips"):
            with contextlib.suppress(*_dns_errors):
                ip = result["dns_ips"][0]
                reverse_name = dns.reversename.from_address(ip)
                answers = resolver.resolve(reverse_name, "PTR")
                for rdata in answers:
                    result["dns_reverse"] = str(cast("PTR", rdata).target).rstrip(".")
                    break

        return result

    @classmethod
    async def execute(
        cls,
        relay: Relay,
        timeout: float | None = None,  # noqa: ASYNC109
    ) -> Self:
        """Resolve DNS records for a clearnet relay.

        Runs the synchronous DNS resolver in a thread pool to avoid
        blocking the event loop.

        Args:
            relay: Clearnet relay to resolve.
            timeout: Resolver timeout in seconds (default: 10.0).

        Returns:
            An ``Nip66DnsMetadata`` instance with resolution data and logs.
        """
        timeout = timeout if timeout is not None else DEFAULT_TIMEOUT
        logger.debug("dns_testing relay=%s timeout_s=%s", relay.url, timeout)

        if relay.network != NetworkType.CLEARNET:
            return cls(
                data=Nip66DnsData(),
                logs=Nip66DnsLogs(
                    success=False, reason=f"requires clearnet, got {relay.network.value}"
                ),
            )

        logs: dict[str, Any] = {"success": False, "reason": None}
        data: dict[str, Any] = {}

        try:
            logger.debug("dns_resolving host=%s", relay.host)
            data = await asyncio.to_thread(cls._dns, relay.host, timeout)
            if data:
                logs["success"] = True
                logger.debug("dns_completed relay=%s ips=%s", relay.url, data.get("dns_ips"))
            else:
                logs["reason"] = "no DNS records found"
                logger.debug("dns_no_data relay=%s", relay.url)
        except (OSError, dns.exception.DNSException) as e:
            logs["reason"] = str(e) or type(e).__name__
            logger.debug("dns_error relay=%s error=%s", relay.url, str(e))

        return cls(
            data=Nip66DnsData.model_validate(Nip66DnsData.parse(data)),
            logs=Nip66DnsLogs.model_validate(logs),
        )
