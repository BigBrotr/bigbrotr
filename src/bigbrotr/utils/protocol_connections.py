"""Relay connection helpers behind the public protocol facade."""

from __future__ import annotations

import asyncio
import ssl
from datetime import timedelta
from typing import TYPE_CHECKING, NamedTuple

from bigbrotr.models.constants import NetworkType


if TYPE_CHECKING:
    import logging
    from collections.abc import Awaitable, Callable

    from nostr_sdk import Client, Keys, RelayUrl

    from bigbrotr.models.relay import Relay


class RelayConnectContext(NamedTuple):
    """Dependencies required to connect a relay."""

    create_client: Callable[..., Awaitable[Client]]
    shutdown_client: Callable[[Client], Awaitable[None]]
    parse_relay_url: Callable[[str], RelayUrl]
    set_event_loop: Callable[[asyncio.AbstractEventLoop], None]
    is_ssl_error: Callable[[str], bool]
    logger: logging.Logger


class RelayConnectOptions(NamedTuple):
    """Parameters controlling how a relay connection is established."""

    keys: Keys | None
    proxy_url: str | None
    timeout: float
    allow_insecure: bool


async def _try_connect_single_relay(
    client: Client,
    relay_url: RelayUrl,
    *,
    connect_timeout: float,
) -> str | None:
    """Try one single-relay client connection and return the failure message, if any."""
    await client.add_relay(relay_url)
    output = await client.try_connect(timedelta(seconds=connect_timeout))
    if relay_url in output.success:
        return None
    return str(output.failed.get(relay_url, "Unknown error"))


async def _connect_overlay_relay(
    relay: Relay,
    relay_url: RelayUrl,
    context: RelayConnectContext,
    options: RelayConnectOptions,
) -> Client:
    """Connect one overlay relay through a configured proxy."""
    proxy_url = options.proxy_url
    if proxy_url is None:
        raise ValueError(f"proxy_url required for {relay.network} relay: {relay.url}")

    client = await context.create_client(options.keys, proxy_url)
    await client.add_relay(relay_url)
    await client.connect()
    await client.wait_for_connection(timedelta(seconds=options.timeout))

    relay_obj = await client.relay(relay_url)
    if not relay_obj.is_connected():
        await context.shutdown_client(client)
        raise TimeoutError(f"Connection timeout: {relay.url}")

    return client


async def connect_relay(
    relay: Relay,
    context: RelayConnectContext,
    options: RelayConnectOptions,
) -> Client:
    """Connect to a relay with automatic SSL fallback for clearnet."""
    relay_url = context.parse_relay_url(relay.url)
    is_overlay = relay.network in (NetworkType.TOR, NetworkType.I2P, NetworkType.LOKI)

    if is_overlay:
        return await _connect_overlay_relay(
            relay,
            relay_url,
            context,
            options,
        )

    context.logger.debug("ssl_connecting relay=%s", relay.url)

    client = await context.create_client(options.keys)
    error_message = await _try_connect_single_relay(
        client,
        relay_url,
        connect_timeout=options.timeout,
    )
    if error_message is None:
        context.logger.debug("ssl_connected relay=%s", relay.url)
        return client

    await context.shutdown_client(client)
    context.logger.debug("connect_failed relay=%s error=%s", relay.url, error_message)

    if not context.is_ssl_error(error_message):
        raise OSError(f"Connection failed: {relay.url} ({error_message})")

    if not options.allow_insecure:
        raise ssl.SSLCertVerificationError(
            f"SSL certificate verification failed for {relay.url}: {error_message}"
        )

    context.logger.debug("ssl_fallback_insecure relay=%s error=%s", relay.url, error_message)
    context.set_event_loop(asyncio.get_running_loop())

    client = await context.create_client(options.keys, allow_insecure=True)
    error_message = await _try_connect_single_relay(
        client,
        relay_url,
        connect_timeout=options.timeout,
    )
    if error_message is not None:
        await context.shutdown_client(client)
        raise OSError(f"Connection failed (insecure): {relay.url} ({error_message})")

    context.logger.debug("insecure_connected relay=%s", relay.url)
    return client
