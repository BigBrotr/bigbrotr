"""Validator service utility functions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bigbrotr.utils.protocol import is_nostr_relay


if TYPE_CHECKING:
    from bigbrotr.models.relay import Relay


async def validate_candidate(
    relay: Relay,
    proxy_url: str | None,
    probe_timeout: float,
    *,
    allow_insecure: bool = False,
) -> bool:
    """Validate a relay candidate via WebSocket Nostr protocol probe.

    Delegates to [is_nostr_relay][bigbrotr.utils.protocol.is_nostr_relay].
    The caller is responsible for acquiring the per-network semaphore.

    Args:
        relay: The [Relay][bigbrotr.models.relay.Relay] to probe.
        proxy_url: Optional SOCKS5 proxy for overlay networks.
        probe_timeout: WebSocket probe timeout in seconds.
        allow_insecure: Fall back to insecure transport on SSL failure.

    Returns:
        ``True`` if the relay speaks Nostr protocol, ``False`` otherwise.
    """
    try:
        return await is_nostr_relay(relay, proxy_url, probe_timeout, allow_insecure=allow_insecure)
    except (TimeoutError, OSError):
        return False
