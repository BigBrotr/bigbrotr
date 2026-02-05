"""DNS resolution utilities."""

from __future__ import annotations

import asyncio
import contextlib
import socket
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ResolvedHost:
    """Result of hostname resolution with IPv4 and IPv6 addresses."""

    ipv4: str | None = None
    ipv6: str | None = None

    @property
    def has_ip(self) -> bool:
        """Return True if at least one IP address was resolved."""
        return self.ipv4 is not None or self.ipv6 is not None


async def resolve_host(host: str) -> ResolvedHost:
    """Resolve hostname to IPv4 and IPv6 addresses.

    Attempts to resolve both IPv4 (A record) and IPv6 (AAAA record) addresses.
    Each resolution is independent - failure of one doesn't affect the other.

    Note: This function does not log internally. Callers are responsible for
    logging resolution results if needed.

    Args:
        host: Hostname to resolve.

    Returns:
        ResolvedHost with resolved addresses (None for failed resolutions).
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
