"""NIP-66 net metadata container with lookup capabilities."""

from __future__ import annotations

import asyncio
from typing import Any, Self

import geoip2.database

from utils.network import NetworkType
from logger import Logger
from models.nips.base import BaseMetadata
from models.relay import Relay
from utils.dns import resolve_host

from .data import Nip66NetData
from .logs import Nip66NetLogs


logger = Logger("models.nip66")


class Nip66NetMetadata(BaseMetadata):
    """Container for Net data and logs with lookup capabilities."""

    data: Nip66NetData
    logs: Nip66NetLogs

    # -------------------------------------------------------------------------
    # Net Lookup
    # -------------------------------------------------------------------------

    @staticmethod
    def _net(
        ipv4: str | None,
        ipv6: str | None,
        asn_reader: geoip2.database.Reader,
    ) -> dict[str, Any]:
        """Synchronous network/ASN lookup."""
        result: dict[str, Any] = {}

        # Lookup IPv4
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
                logger.debug("net_asn_ipv4_lookup_error", ip=ipv4, error=str(e))

        # Lookup IPv6
        if ipv6:
            result["net_ipv6"] = ipv6
            try:
                asn_response = asn_reader.asn(ipv6)
                if asn_response.network:
                    result["net_network_v6"] = str(asn_response.network)
                if "net_asn" not in result:
                    if asn_response.autonomous_system_number:
                        result["net_asn"] = asn_response.autonomous_system_number
                    if asn_response.autonomous_system_organization:
                        result["net_asn_org"] = asn_response.autonomous_system_organization
            except Exception as e:
                logger.debug("net_asn_ipv6_lookup_error", ip=ipv6, error=str(e))

        return result

    @classmethod
    async def net(
        cls,
        relay: Relay,
        asn_reader: geoip2.database.Reader,
    ) -> Self:
        """Lookup network/ASN info for relay.

        Raises:
            ValueError: If non-clearnet relay.
        """
        logger.debug("net_testing", relay=relay.url)

        if relay.network != NetworkType.CLEARNET:
            raise ValueError(f"net lookup requires clearnet, got {relay.network.value}")

        logs: dict[str, Any] = {"success": False, "reason": None}

        # Resolve hostname to IPv4 and IPv6
        resolved = await resolve_host(relay.host)

        data: dict[str, Any] = {}
        if resolved.has_ip:
            data = await asyncio.to_thread(cls._net, resolved.ipv4, resolved.ipv6, asn_reader)
            if data:
                logs["success"] = True
                logger.debug("net_completed", relay=relay.url, asn=data.get("net_asn"))
            else:
                logs["reason"] = "no ASN data found for IP"
                logger.debug("net_no_data", relay=relay.url)
        else:
            logs["reason"] = "could not resolve hostname to IP"
            logger.debug("net_no_ip", relay=relay.url)

        return cls(
            data=Nip66NetData.model_validate(Nip66NetData.parse(data)),
            logs=Nip66NetLogs.model_validate(logs),
        )
