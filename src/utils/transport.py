"""Nostr client transport utilities.

Provides factory functions for creating Nostr clients with proper transport
configuration for clearnet and overlay networks (Tor, I2P, Loki).
"""

from __future__ import annotations

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


if TYPE_CHECKING:
    from nostr_sdk import Keys


def create_client(
    keys: Keys | None = None,
    proxy_url: str | None = None,
) -> Client:
    """Create a Nostr client with optional SOCKS5 proxy.

    For overlay networks (tor/i2p/loki):
        Uses nostr-sdk's built-in SOCKS5 proxy support via ConnectionMode.PROXY.
        The proxy_url should be provided when connecting to .onion/.i2p/.loki relays.

    For clearnet relays:
        Uses standard nostr-sdk client (no proxy needed).
        Pass proxy_url=None for clearnet connections.

    Args:
        keys: Optional Keys for signing events. If None, client will be read-only.
        proxy_url: SOCKS5 proxy URL for overlay networks (e.g., "socks5://127.0.0.1:9050").
            Pass None for clearnet relays.

    Returns:
        Configured Client instance (no relays added - call add_relay() separately)

    Example:
        # Clearnet relay
        client = create_client(keys)
        await client.add_relay("wss://relay.damus.io")

        # Tor relay via proxy
        client = create_client(keys, proxy_url="socks5://127.0.0.1:9050")
        await client.add_relay("wss://relay.onion")
    """
    builder = ClientBuilder()

    if keys is not None:
        signer = NostrSigner.keys(keys)
        builder = builder.signer(signer)

    if proxy_url is not None:
        # Parse proxy URL for host/port
        parsed = urlparse(proxy_url)
        proxy_host = parsed.hostname or "127.0.0.1"
        proxy_port = parsed.port or 9050

        # Configure connection for overlay network via SOCKS5 proxy
        proxy_mode = ConnectionMode.PROXY(proxy_host, proxy_port)
        conn = Connection().mode(proxy_mode).target(ConnectionTarget.ONION)
        opts = ClientOptions().connection(conn)
        builder = builder.opts(opts)

    return builder.build()
