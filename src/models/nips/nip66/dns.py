"""NIP-66 DNS metadata container with resolve capabilities."""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any, Self, cast

import dns.resolver
import tldextract


if TYPE_CHECKING:
    from dns.rdtypes.ANY.CNAME import CNAME
    from dns.rdtypes.ANY.NS import NS
    from dns.rdtypes.ANY.PTR import PTR
    from dns.rdtypes.IN.A import A
    from dns.rdtypes.IN.AAAA import AAAA

from utils.network import NetworkType
from logger import Logger
from models.nips.base import DEFAULT_TIMEOUT, BaseMetadata
from models.relay import Relay

from .data import Nip66DnsData
from .logs import Nip66DnsLogs


logger = Logger("models.nip66")


class Nip66DnsMetadata(BaseMetadata):
    """Container for DNS data and logs with resolve capabilities."""

    data: Nip66DnsData
    logs: Nip66DnsLogs

    # -------------------------------------------------------------------------
    # DNS Resolve
    # -------------------------------------------------------------------------

    @staticmethod
    def _dns(host: str, timeout: float) -> dict[str, Any]:
        """Synchronous comprehensive DNS resolution."""
        result: dict[str, Any] = {}
        resolver = dns.resolver.Resolver()
        resolver.timeout = timeout
        resolver.lifetime = timeout

        # A records (IPv4)
        with contextlib.suppress(Exception):
            answers = resolver.resolve(host, "A")
            ips = [cast("A", rdata).address for rdata in answers]
            if ips:
                result["dns_ips"] = ips
                if answers.rrset:
                    result["dns_ttl"] = answers.rrset.ttl

        # AAAA records (IPv6)
        with contextlib.suppress(Exception):
            answers = resolver.resolve(host, "AAAA")
            ips_v6 = [cast("AAAA", rdata).address for rdata in answers]
            if ips_v6:
                result["dns_ips_v6"] = ips_v6

        # CNAME record
        with contextlib.suppress(Exception):
            answers = resolver.resolve(host, "CNAME")
            for rdata in answers:
                result["dns_cname"] = str(cast("CNAME", rdata).target).rstrip(".")
                break

        # NS records
        with contextlib.suppress(Exception):
            ext = tldextract.extract(host)
            if ext.domain and ext.suffix:
                domain = f"{ext.domain}.{ext.suffix}"
                answers = resolver.resolve(domain, "NS")
                ns_list = [str(cast("NS", rdata).target).rstrip(".") for rdata in answers]
                if ns_list:
                    result["dns_ns"] = ns_list

        # Reverse DNS (PTR)
        if result.get("dns_ips"):
            with contextlib.suppress(Exception):
                ip = result["dns_ips"][0]
                reverse_name = dns.reversename.from_address(ip)
                answers = resolver.resolve(reverse_name, "PTR")
                for rdata in answers:
                    result["dns_reverse"] = str(cast("PTR", rdata).target).rstrip(".")
                    break

        return result

    @classmethod
    async def dns(
        cls,
        relay: Relay,
        timeout: float | None = None,
    ) -> Self:
        """Resolve DNS records for relay.

        Raises:
            ValueError: If non-clearnet relay.
        """
        timeout = timeout if timeout is not None else DEFAULT_TIMEOUT
        logger.debug("dns_testing", relay=relay.url, timeout_s=timeout)

        if relay.network != NetworkType.CLEARNET:
            raise ValueError(f"DNS resolve requires clearnet, got {relay.network.value}")

        logs: dict[str, Any] = {"success": False, "reason": None}
        data: dict[str, Any] = {}

        try:
            logger.debug("dns_resolving", host=relay.host)
            data = await asyncio.to_thread(cls._dns, relay.host, timeout)
            if data:
                logs["success"] = True
                logger.debug("dns_completed", relay=relay.url, ips=data.get("dns_ips"))
            else:
                logs["reason"] = "no DNS records found"
                logger.debug("dns_no_data", relay=relay.url)
        except Exception as e:
            logs["reason"] = str(e)
            logger.debug("dns_error", relay=relay.url, error=str(e))

        return cls(
            data=Nip66DnsData.model_validate(Nip66DnsData.parse(data)),
            logs=Nip66DnsLogs.model_validate(logs),
        )
