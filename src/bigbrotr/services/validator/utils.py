"""Validator service utility functions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bigbrotr.utils.protocol import is_nostr_relay


if TYPE_CHECKING:
    import asyncio

    from bigbrotr.models.relay import Relay


async def validate_candidate(
    relay: Relay,
    semaphore: asyncio.Semaphore,
    proxy_url: str | None,
    probe_timeout: float,
) -> bool:
    """Validate a relay candidate via WebSocket Nostr protocol probe.

    Acquires the per-network *semaphore* for rate limiting, then delegates
    to [is_nostr_relay][bigbrotr.utils.protocol.is_nostr_relay].

    Args:
        relay: The [Relay][bigbrotr.models.relay.Relay] to probe.
        semaphore: Per-network concurrency limiter.
        proxy_url: Optional SOCKS5 proxy for overlay networks.
        probe_timeout: WebSocket probe timeout in seconds.

    Returns:
        ``True`` if the relay speaks Nostr protocol, ``False`` otherwise.
    """
    async with semaphore:
        try:
            return await is_nostr_relay(relay, proxy_url, probe_timeout)
        except (TimeoutError, OSError):
            return False
