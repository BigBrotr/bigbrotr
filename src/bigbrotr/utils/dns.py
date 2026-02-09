"""DNS resolution utilities for BigBrotr.

Provides async hostname resolution for both IPv4 (A record) and IPv6 (AAAA record)
addresses. Used by the Monitor service for relay DNS checks and IP geolocation.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ResolvedHost:
    """Immutable result of hostname resolution containing IPv4 and IPv6 addresses."""

    ipv4: str | None = None
    ipv6: str | None = None

    @property
    def has_ip(self) -> bool:
        """Return True if at least one IP address was resolved."""
        return self.ipv4 is not None or self.ipv6 is not None


async def resolve_host(host: str) -> ResolvedHost:
    """Resolve a hostname to IPv4 and IPv6 addresses asynchronously.

    Performs independent A and AAAA record lookups using the system resolver
    via ``asyncio.to_thread``. Failure of one address family does not affect
    the other.

    Args:
        host: Hostname to resolve (e.g., ``"relay.damus.io"``).

    Returns:
        ResolvedHost with resolved addresses (None for failed lookups).
    """
    ipv4: str | None = None
    ipv6: str | None = None

    # Resolve IPv4
    with contextlib.suppress(Exception):
        ipv4 = await asyncio.to_thread(socket.gethostbyname, host)

    # Resolve IPv6
    with contextlib.suppress(Exception):
        ipv6_result = await asyncio.to_thread(socket.getaddrinfo, host, None, socket.AF_INET6)
        if ipv6_result:
            ipv6 = str(ipv6_result[0][4][0])

    return ResolvedHost(ipv4=ipv4, ipv6=ipv6)
