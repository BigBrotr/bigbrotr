"""
NIP-66 network metadata container with ASN lookup capabilities.

Resolves a relay's hostname to IPv4/IPv6 addresses and queries the
GeoIP ASN database for autonomous system number, organization name,
and CIDR network ranges. Clearnet relays only.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Self

import geoip2.database  # noqa: TC002

from models.constants import NetworkType
from models.nips.base import BaseMetadata
from models.relay import Relay  # noqa: TC001
from utils.dns import resolve_host

from .data import Nip66NetData
from .logs import Nip66NetLogs


logger = logging.getLogger("models.nip66")


class Nip66NetMetadata(BaseMetadata):
    """Container for network/ASN data and lookup logs.

    Provides the ``net()`` class method that resolves the relay hostname
    and performs GeoIP ASN lookups for both IPv4 and IPv6 addresses.
    """

    data: Nip66NetData
    logs: Nip66NetLogs

    # -------------------------------------------------------------------------
    # Network/ASN Lookup
    # -------------------------------------------------------------------------

    @staticmethod
    def _net(
        ipv4: str | None,
        ipv6: str | None,
        asn_reader: geoip2.database.Reader,
    ) -> dict[str, Any]:
        """Perform synchronous ASN lookups for IPv4 and/or IPv6 addresses.

        IPv4 ASN data takes priority; IPv6 ASN data is used as a fallback
        when IPv4 is not available. IPv6-specific network range is always
        recorded separately.

        Args:
            ipv4: Resolved IPv4 address, or None.
            ipv6: Resolved IPv6 address, or None.
            asn_reader: Open GeoLite2-ASN database reader.

        Returns:
            Dictionary of network fields (IP, ASN, org, CIDR ranges).
        """
        result: dict[str, Any] = {}

        if ipv4:
            result["net_ip"] = ipv4
            try:
                asn_response = asn_reader.asn(ipv4)
                if asn_response.autonomous_system_number:
                    result["net_asn"] = asn_response.autonomous_system_number
                if asn_response.autonomous_system_organization:
                    result["net_asn_org"] = asn_response.autonomous_system_organization
                if asn_response.network:
                    result["net_network"] = str(asn_response.network)
            except Exception as e:
                logger.debug("net_asn_ipv4_lookup_error ip=%s error=%s", ipv4, str(e))

        if ipv6:
            result["net_ipv6"] = ipv6
            try:
                asn_response = asn_reader.asn(ipv6)
                if asn_response.network:
                    result["net_network_v6"] = str(asn_response.network)
                # Use IPv6 ASN data only if IPv4 lookup did not provide it
                if "net_asn" not in result:
                    if asn_response.autonomous_system_number:
                        result["net_asn"] = asn_response.autonomous_system_number
                    if asn_response.autonomous_system_organization:
                        result["net_asn_org"] = asn_response.autonomous_system_organization
            except Exception as e:
                logger.debug("net_asn_ipv6_lookup_error ip=%s error=%s", ipv6, str(e))

        return result

    @classmethod
    async def net(
        cls,
        relay: Relay,
        asn_reader: geoip2.database.Reader,
    ) -> Self:
        """Perform network/ASN lookups for a clearnet relay.

        Resolves the relay hostname to IPv4 and IPv6 addresses, then
        queries the GeoIP ASN database in a thread pool.

        Args:
            relay: Clearnet relay to look up.
            asn_reader: Open GeoLite2-ASN database reader.

        Returns:
            An ``Nip66NetMetadata`` instance with network data and logs.

        Raises:
            ValueError: If the relay is not on the clearnet network.
        """
        logger.debug("net_testing relay=%s", relay.url)

        if relay.network != NetworkType.CLEARNET:
            raise ValueError(f"net lookup requires clearnet, got {relay.network.value}")

        logs: dict[str, Any] = {"success": False, "reason": None}

        resolved = await resolve_host(relay.host)

        data: dict[str, Any] = {}
        if resolved.has_ip:
            data = await asyncio.to_thread(cls._net, resolved.ipv4, resolved.ipv6, asn_reader)
            if data:
                logs["success"] = True
                logger.debug("net_completed relay=%s asn=%s", relay.url, data.get("net_asn"))
            else:
                logs["reason"] = "no ASN data found for IP"
                logger.debug("net_no_data relay=%s", relay.url)
        else:
            logs["reason"] = "could not resolve hostname to IP"
            logger.debug("net_no_ip relay=%s", relay.url)

        return cls(
            data=Nip66NetData.model_validate(Nip66NetData.parse(data)),
            logs=Nip66NetLogs.model_validate(logs),
        )
