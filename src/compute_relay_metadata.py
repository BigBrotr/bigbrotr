"""
Compute relay metadata using nostr-tools library.

This module wraps the nostr-tools fetch_relay_metadata function to maintain
compatibility with the bigbrotr architecture.
"""

from nostr_tools import Client, fetch_relay_metadata
import time


async def compute_relay_metadata(relay, sec, pub, socks5_proxy_url=None, timeout=10):
    """
    Compute comprehensive relay metadata using nostr-tools.

    Args:
        relay: Relay instance from nostr-tools
        sec: Secret key for authentication
        pub: Public key
        socks5_proxy_url: SOCKS5 proxy URL for Tor relays (optional)
        timeout: Timeout in seconds

    Returns:
        RelayMetadata instance with NIP-11 and NIP-66 data
    """
    client = Client(relay=relay, timeout=timeout, socks5_proxy_url=socks5_proxy_url)

    try:
        relay_metadata = await fetch_relay_metadata(
            client=client,
            private_key=sec,
            public_key=pub
        )
        # Ensure generated_at is set
        if relay_metadata:
            relay_metadata.generated_at = int(time.time())
        return relay_metadata
    except Exception:
        # If fetch fails, return minimal metadata
        from nostr_tools import RelayMetadata
        return RelayMetadata(
            relay=relay,
            generated_at=int(time.time()),
            nip11=None,
            nip66=None
        )
