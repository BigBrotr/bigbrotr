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


async def build_client(
    keys: Keys | None = None,
    proxy_url: str | None = None,
    *,
    allow_insecure: bool = False,
) -> Client:
    """Build a nostr-sdk client with optional signer, proxy and SSL override."""
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

        bare_host = proxy_host.strip("[]")
        try:
            IPv4Address(bare_host)
        except (AddressValueError, ValueError):
            try:
                IPv6Address(bare_host)
                proxy_host = bare_host
            except (AddressValueError, ValueError):
                proxy_host = await asyncio.to_thread(socket.gethostbyname, proxy_host)

        proxy_mode = ConnectionMode.PROXY(proxy_host, proxy_port)
        conn = Connection().mode(proxy_mode).target(ConnectionTarget.ONION)
        opts = ClientOptions().connection(conn)
        builder = builder.opts(opts)

    return builder.build()
