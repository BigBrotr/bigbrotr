"""DNS resolution utilities for BigBrotr.

Provides async hostname resolution for both IPv4 (A record) and IPv6 (AAAA record)
addresses. Used by the [Monitor][bigbrotr.services.monitor.Monitor] service for
relay DNS checks and IP geolocation.

Note:
    Resolution uses the system resolver via ``socket.gethostbyname`` and
    ``socket.getaddrinfo``, delegated to threads with ``asyncio.to_thread``
    to avoid blocking the event loop. Each address family is resolved
    independently so that failure of one does not affect the other.

    This module provides **basic** A/AAAA resolution only. For comprehensive
    DNS record collection (CNAME, NS, PTR, TTL), see the NIP-66 DNS module.

See Also:
    [bigbrotr.nips.nip66.dns.Nip66DnsMetadata][bigbrotr.nips.nip66.dns.Nip66DnsMetadata]:
        Full DNS record collection (A, AAAA, CNAME, NS, PTR) using ``dnspython``.
    [bigbrotr.nips.nip66.geo.Nip66GeoMetadata][bigbrotr.nips.nip66.geo.Nip66GeoMetadata]:
        Geolocation lookup that depends on this module for IP resolution.
    [bigbrotr.nips.nip66.net.Nip66NetMetadata][bigbrotr.nips.nip66.net.Nip66NetMetadata]:
        Network/ASN lookup that depends on this module for IP resolution.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ResolvedHost:
    """Immutable result of hostname resolution containing IPv4 and IPv6 addresses.

    See Also:
        [resolve_host][bigbrotr.utils.dns.resolve_host]: The async function
            that produces instances of this class.
    """

    ipv4: str | None = None
    ipv6: str | None = None

    @property
    def has_ip(self) -> bool:
        """Return True if at least one IP address was resolved."""
        return self.ipv4 is not None or self.ipv6 is not None


async def resolve_host(host: str, *, timeout: float = 5.0) -> ResolvedHost:  # noqa: ASYNC109
    """Resolve a hostname to IPv4 and IPv6 addresses asynchronously.

    Performs independent A and AAAA record lookups using the system resolver
    via ``asyncio.to_thread``. Failure of one address family does not affect
    the other. Each lookup is bounded by *timeout* to prevent indefinite
    blocking on unresponsive DNS servers.

    Args:
        host: Hostname to resolve (e.g., ``"relay.damus.io"``).
        timeout: Maximum seconds to wait for each DNS lookup (default 5.0).

    Returns:
        [ResolvedHost][bigbrotr.utils.dns.ResolvedHost] with resolved
            addresses (``None`` for failed lookups).

    Note:
        All exceptions from the underlying socket calls are suppressed,
        including ``asyncio.TimeoutError``.
        A completely unresolvable hostname returns a
        [ResolvedHost][bigbrotr.utils.dns.ResolvedHost] with both fields
        set to ``None`` and ``has_ip == False`` rather than raising.

    Examples:
        ```python
        result = await resolve_host("relay.damus.io")
        result.ipv4    # '35.232.163.46'
        result.has_ip  # True
        ```
    """
    ipv4: str | None = None
    ipv6: str | None = None

    # Resolve IPv4
    with contextlib.suppress(OSError, UnicodeError, TimeoutError):
        ipv4 = await asyncio.wait_for(
            asyncio.to_thread(socket.gethostbyname, host), timeout=timeout
        )

    # Resolve IPv6
    with contextlib.suppress(OSError, UnicodeError, TimeoutError):
        ipv6_result = await asyncio.wait_for(
            asyncio.to_thread(socket.getaddrinfo, host, None, socket.AF_INET6),
            timeout=timeout,
        )
        if ipv6_result:
            ipv6 = str(ipv6_result[0][4][0])

    return ResolvedHost(ipv4=ipv4, ipv6=ipv6)
