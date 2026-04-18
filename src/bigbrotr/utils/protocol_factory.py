"""Client-construction helpers behind the public protocol facade."""

from __future__ import annotations

import asyncio
import socket
from ipaddress import AddressValueError, IPv4Address, IPv6Address
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from nostr_sdk import (
    Client,
    ClientBuilder,
    ClientOptions,
    Connection,
    ConnectionMode,
    ConnectionTarget,
    NostrSigner,
)

from .transport import InsecureWebSocketTransport


if TYPE_CHECKING:
    from nostr_sdk import Keys


async def _resolve_proxy_host(proxy_host: str) -> str:
    """Resolve one proxy host to a numeric IPv4 or IPv6 address."""
    bare_host = proxy_host.strip("[]")

    for address_type in (IPv4Address, IPv6Address):
        try:
            address_type(bare_host)
        except (AddressValueError, ValueError):
            continue
        return bare_host

    ipv4_error: OSError | UnicodeError | None = None
    try:
        return await asyncio.to_thread(socket.gethostbyname, proxy_host)
    except (OSError, UnicodeError) as exc:
        ipv4_error = exc

    try:
        ipv6_result = await asyncio.to_thread(socket.getaddrinfo, proxy_host, None, socket.AF_INET6)
    except (OSError, UnicodeError):
        if ipv4_error is not None:
            raise ipv4_error from None
        raise

    if ipv6_result:
        return str(ipv6_result[0][4][0])

    if ipv4_error is not None:
        raise ipv4_error
    raise OSError(f"Could not resolve proxy host: {proxy_host}")


async def build_client(
    keys: Keys | None = None,
    proxy_url: str | None = None,
    *,
    allow_insecure: bool = False,
) -> Client:
    """Build a nostr-sdk client with optional signer, proxy and SSL override.

    When ``proxy_url`` is provided, the client is configured to route all
    attached relay URLs through the proxy target. BigBrotr uses the same
    helper for Tor, I2P, and Lokinet overlays, so the proxy contract cannot
    stay onion-specific.
    """
    builder = ClientBuilder()

    if keys is not None:
        signer = NostrSigner.keys(keys)
        builder = builder.signer(signer)

    if allow_insecure:
        transport = InsecureWebSocketTransport()
        builder = builder.websocket_transport(transport)

    if proxy_url is not None:
        parsed = urlparse(proxy_url)
        proxy_host = parsed.hostname or "127.0.0.1"
        proxy_port = parsed.port or 9050
        proxy_host = await _resolve_proxy_host(proxy_host)

        proxy_mode = ConnectionMode.PROXY(proxy_host, proxy_port)
        conn = Connection().mode(proxy_mode).target(ConnectionTarget.ALL)
        opts = ClientOptions().connection(conn)
        builder = builder.opts(opts)

    return builder.build()
