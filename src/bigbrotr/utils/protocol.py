"""Nostr protocol client operations for BigBrotr.

Provides client factory, relay connection with SSL fallback, event
broadcasting, relay validation, and event fetching. Built on top of the
WebSocket transport primitives in
[bigbrotr.utils.transport][bigbrotr.utils.transport].

Attributes:
    create_client: Client factory with optional SOCKS5 proxy and SSL override.
    connect_relay: High-level helper with automatic SSL fallback.
    is_nostr_relay: Check whether a URL hosts a Nostr relay.
    broadcast_events: Sign and broadcast events to multiple relays.
    fetch_relay_events: Async generator yielding validated events from a relay.

Note:
    The SSL fallback strategy for clearnet relays follows a two-phase
    approach: first attempt a fully verified TLS connection, then fall back
    to [InsecureWebSocketTransport][bigbrotr.utils.transport.InsecureWebSocketTransport]
    only if the error is SSL-related and ``allow_insecure=True``. This
    ensures security by default while accommodating relays with self-signed
    or expired certificates.

    Overlay networks (Tor, I2P, Lokinet) always use
    ``nostr_sdk.ConnectionMode.PROXY`` with a SOCKS5 proxy and do not
    attempt SSL fallback, as the overlay itself provides encryption.

See Also:
    [bigbrotr.utils.transport][bigbrotr.utils.transport]: WebSocket transport
        primitives used by this module.
    [bigbrotr.models.relay.Relay][bigbrotr.models.relay.Relay]: The relay
        model consumed by all connection functions.
    [bigbrotr.models.constants.NetworkType][bigbrotr.models.constants.NetworkType]:
        Enum used to select between clearnet and overlay transport strategies.

Examples:
    ```python
    from bigbrotr.utils.protocol import create_client, connect_relay

    client = await create_client(keys=my_keys, proxy_url="socks5://tor:9050")
    client = await connect_relay(relay, keys=my_keys, timeout=10.0)
    ```
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import socket
import ssl
import sys
from datetime import timedelta
from ipaddress import AddressValueError, IPv4Address, IPv6Address
from typing import TYPE_CHECKING, TextIO
from urllib.parse import urlparse

from nostr_sdk import (
    Client,
    ClientBuilder,
    ClientOptions,
    Connection,
    ConnectionMode,
    ConnectionTarget,
    Filter,
    Kind,
    KindStandard,
    NostrSigner,
    RelayUrl,
    uniffi_set_event_loop,
)

from bigbrotr.models.constants import NetworkType
from bigbrotr.models.event import Event
from bigbrotr.models.relay import Relay  # noqa: TC001
from bigbrotr.utils.transport import DEFAULT_TIMEOUT, InsecureWebSocketTransport


if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Generator

    from nostr_sdk import EventBuilder, Keys


logger = logging.getLogger(__name__)


# Multi-word patterns for SSL/TLS certificate errors in nostr-sdk messages.
# Single keywords like "verify" or "handshake" are avoided to prevent false
# positives from unrelated errors (e.g. DNS "cannot verify hostname").
_SSL_ERROR_PATTERNS: tuple[str, ...] = (
    "ssl certificate",
    "certificate verify",
    "certificate has expired",
    "self signed certificate",
    "self-signed certificate",
    "unable to get local issuer",
    "x509",
    "tlsv1 alert",
    "ssl handshake",
    "tls handshake failed",
    "certificate_unknown",
    "certificate_expired",
    "ssl error",
    "tls error",
    "cert verify failed",
)


def _is_ssl_error(error_message: str) -> bool:
    """Check if an error message indicates an SSL/TLS certificate error."""
    error_lower = error_message.lower()
    return any(pattern in error_lower for pattern in _SSL_ERROR_PATTERNS)


class _StderrSuppressor:
    """Reference-counted stderr suppressor for async-safe batch suppression.

    Multiple concurrent async tasks can enter suppression without blocking
    the event loop. A ``threading.Lock`` would deadlock here because the
    context manager ``yield`` crosses ``await`` boundaries.
    """

    __slots__ = ("_devnull", "_refcount", "_saved_stderr")

    def __init__(self) -> None:
        self._refcount = 0
        self._saved_stderr: TextIO | None = None
        self._devnull: TextIO | None = None

    @contextlib.contextmanager
    def __call__(self) -> Generator[None, None, None]:
        if self._refcount == 0:
            self._saved_stderr = sys.stderr
            self._devnull = open(os.devnull, "w")  # noqa: PTH123, SIM115  # os.devnull requires built-in open()
        self._refcount += 1
        sys.stderr = self._devnull
        try:
            yield
        finally:
            self._refcount -= 1
            if self._refcount == 0:
                sys.stderr = self._saved_stderr
                if self._devnull is not None:
                    self._devnull.close()
                self._saved_stderr = None
                self._devnull = None


_suppress_stderr = _StderrSuppressor()


async def create_client(
    keys: Keys | None = None,
    proxy_url: str | None = None,
    *,
    allow_insecure: bool = False,
) -> Client:
    """Create a Nostr client with optional SOCKS5 proxy and SSL override.

    For overlay networks, uses nostr-sdk's built-in proxy via
    ``ConnectionMode.PROXY``. For clearnet, uses standard SSL connections
    unless ``allow_insecure`` is ``True``.

    Args:
        keys: Optional signing keys (``None`` = read-only client).
        proxy_url: SOCKS5 proxy URL for overlay networks (e.g., ``socks5://tor:9050``).
        allow_insecure: If ``True``, bypass SSL certificate verification
            using [InsecureWebSocketTransport][bigbrotr.utils.transport.InsecureWebSocketTransport].

    Returns:
        Configured ``Client`` instance (call ``add_relay()`` before use).

    Note:
        When a ``proxy_url`` hostname is not already an IP address, it is
        resolved asynchronously via ``asyncio.to_thread(socket.gethostbyname)``
        because nostr-sdk requires a numeric IP for the proxy connection.

    Warning:
        Setting ``allow_insecure=True`` bypasses all SSL/TLS certificate
        verification. Only use when standard SSL has already been attempted
        and failed.

    See Also:
        [connect_relay][bigbrotr.utils.protocol.connect_relay]: Higher-level
            function that handles connection and automatic SSL fallback.
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

        # nostr-sdk requires an IP address, not a hostname
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


async def connect_relay(
    relay: Relay,
    keys: Keys | None = None,
    proxy_url: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,  # noqa: ASYNC109
    *,
    allow_insecure: bool = False,
) -> Client:
    """Connect to a relay with automatic SSL fallback for clearnet.

    For clearnet relays, tries SSL first and falls back to insecure if allowed.
    Overlay networks (Tor/I2P/Loki) require a proxy and use no SSL fallback.

    Args:
        relay: [Relay][bigbrotr.models.relay.Relay] to connect to.
        keys: Optional signing keys.
        proxy_url: SOCKS5 proxy URL (required for overlay networks).
        timeout: Connection timeout in seconds.
        allow_insecure: If ``True``, fall back to insecure transport on SSL failure.

    Returns:
        Connected ``Client`` ready for use.

    Raises:
        TimeoutError: If connection times out.
        ValueError: If overlay relay requested without ``proxy_url``.
        ssl.SSLCertVerificationError: If SSL fails and ``allow_insecure`` is ``False``.

    Note:
        The clearnet fallback path requires calling ``uniffi_set_event_loop()``
        before creating the
        [InsecureWebSocketTransport][bigbrotr.utils.transport.InsecureWebSocketTransport],
        because the custom transport uses UniFFI callbacks that need access
        to the running asyncio event loop.

    See Also:
        [create_client][bigbrotr.utils.protocol.create_client]: Used for both
            the initial SSL-verified attempt and the insecure fallback.
        [is_nostr_relay][bigbrotr.utils.protocol.is_nostr_relay]: Higher-level
            validation that uses this function internally.
    """
    relay_url = RelayUrl.parse(relay.url)
    is_overlay = relay.network in (NetworkType.TOR, NetworkType.I2P, NetworkType.LOKI)

    if is_overlay:
        if proxy_url is None:
            raise ValueError(f"proxy_url required for {relay.network} relay: {relay.url}")

        client = await create_client(keys, proxy_url)
        await client.add_relay(relay_url)
        await client.connect()
        await client.wait_for_connection(timedelta(seconds=timeout))

        relay_obj = await client.relay(relay_url)
        if not relay_obj.is_connected():
            await client.disconnect()
            raise TimeoutError(f"Connection timeout: {relay.url}")

        return client

    # Clearnet: try SSL first, then fall back to insecure if allowed
    logger.debug("ssl_connecting relay=%s", relay.url)

    client = await create_client(keys)
    await client.add_relay(relay_url)
    output = await client.try_connect(timedelta(seconds=timeout))

    if relay_url in output.success:
        logger.debug("ssl_connected relay=%s", relay.url)
        return client

    await client.disconnect()
    error_message = output.failed.get(relay_url, "Unknown error")
    logger.debug("connect_failed relay=%s error=%s", relay.url, error_message)

    if not _is_ssl_error(error_message):
        raise OSError(f"Connection failed: {relay.url} ({error_message})")

    if not allow_insecure:
        raise ssl.SSLCertVerificationError(
            f"SSL certificate verification failed for {relay.url}: {error_message}"
        )

    logger.debug("ssl_fallback_insecure relay=%s error=%s", relay.url, error_message)

    # Required for custom WebSocket transport UniFFI callbacks
    uniffi_set_event_loop(asyncio.get_running_loop())

    client = await create_client(keys, allow_insecure=True)
    await client.add_relay(relay_url)
    output = await client.try_connect(timedelta(seconds=timeout))

    if relay_url not in output.success:
        error_message = output.failed.get(relay_url, "Unknown error")
        await client.disconnect()
        raise OSError(f"Connection failed (insecure): {relay.url} ({error_message})")

    logger.debug("insecure_connected relay=%s", relay.url)
    return client


async def broadcast_events(
    builders: list[EventBuilder],
    relays: list[Relay],
    keys: Keys,
    *,
    timeout: float = 30.0,  # noqa: ASYNC109
    allow_insecure: bool = True,
) -> int:
    """Sign and broadcast Nostr events to relays.

    Creates a separate client per relay so that SSL fallback can be
    applied independently.  Relays that fail to connect or send are
    logged at WARNING level and skipped.

    Returns:
        Number of relays that successfully received all events.
    """
    if not builders or not relays:
        return 0

    success = 0
    for relay in relays:
        try:
            client = await connect_relay(
                relay,
                keys=keys,
                timeout=timeout,
                allow_insecure=allow_insecure,
            )
        except (OSError, TimeoutError) as e:
            logger.warning("broadcast_connect_failed relay=%s error=%s", relay.url, e)
            continue

        try:
            for builder in builders:
                await client.send_event_builder(builder)
            success += 1
        except (OSError, TimeoutError) as e:
            logger.warning("broadcast_send_failed relay=%s error=%s", relay.url, e)
        finally:
            with contextlib.suppress(Exception):
                await client.shutdown()

    return success


async def is_nostr_relay(
    relay: Relay,
    proxy_url: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,  # noqa: ASYNC109
    *,
    overall_timeout: float | None = None,
    allow_insecure: bool = False,
) -> bool:
    """Check if a URL hosts a Nostr relay by attempting a protocol handshake.

    A relay is considered valid if it responds with EOSE to a REQ, sends
    an AUTH challenge (NIP-42), or returns a CLOSED with ``"auth-required"``.

    Args:
        relay: [Relay][bigbrotr.models.relay.Relay] to validate.
        proxy_url: SOCKS5 proxy URL (required for overlay networks).
        timeout: Timeout in seconds for connect and fetch operations.
        overall_timeout: Total time budget for the entire validation
            (connect + possible SSL fallback + fetch). Defaults to
            ``timeout * 4`` to cover: SSL attempt, disconnect, insecure
            retry, and fetch.
        allow_insecure: If ``True``, fall back to insecure transport on
            SSL failure (passed through to
            [connect_relay][bigbrotr.utils.protocol.connect_relay]).

    Returns:
        ``True`` if the relay speaks the Nostr protocol, ``False`` otherwise.

    See Also:
        [connect_relay][bigbrotr.utils.protocol.connect_relay]: Used
            internally to establish the WebSocket connection.
        [bigbrotr.services.validator.Validator][bigbrotr.services.validator.Validator]:
            Service that calls this function to promote candidates to relays.
    """
    effective_overall = overall_timeout if overall_timeout is not None else timeout * 4

    logger.debug("validation_started relay=%s timeout_s=%s", relay.url, timeout)

    with _suppress_stderr():
        client = None
        try:
            async with asyncio.timeout(effective_overall):
                client = await connect_relay(
                    relay=relay,
                    proxy_url=proxy_url,
                    timeout=timeout,
                    allow_insecure=allow_insecure,
                )

                req_filter = Filter().kind(Kind.from_std(KindStandard.TEXT_NOTE)).limit(1)
                await client.fetch_events(req_filter, timedelta(seconds=timeout))
                logger.debug("validation_success relay=%s reason=%s", relay.url, "eose")
                return True

        except TimeoutError:
            logger.debug("validation_timeout relay=%s", relay.url)
            return False

        except OSError as e:
            # AUTH-required errors indicate a valid Nostr relay (NIP-42)
            error_msg = str(e).lower()
            if "auth-required" in error_msg:
                logger.debug("validation_success relay=%s reason=%s", relay.url, "auth-required")
                return True
            logger.debug("validation_failed relay=%s error=%s", relay.url, str(e))
            return False

        finally:
            if client is not None:
                # nostr-sdk Rust FFI can raise arbitrary exception types during disconnect.
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(client.disconnect(), timeout=timeout)


async def fetch_relay_events(
    relay: Relay,
    event_filter: Filter,
    *,
    timeout: float = DEFAULT_TIMEOUT,  # noqa: ASYNC109
    proxy_url: str | None = None,
    keys: Keys | None = None,
) -> AsyncIterator[Event]:
    """Connect to a relay and yield signature-verified Event objects.

    The connection is managed automatically: opened on iteration start,
    closed when the generator exits (including on break/exception).

    Args:
        relay: Relay to connect to.
        event_filter: nostr-sdk Filter specifying which events to fetch.
        timeout: Request timeout in seconds.
        proxy_url: SOCKS5 proxy URL for overlay networks.
        keys: Optional signing keys for NIP-42 authentication.

    Yields:
        Validated [Event][bigbrotr.models.event.Event] objects
        (signature-verified, model-constructed).

    Examples:
        ```python
        from nostr_sdk import Filter, Kind, Timestamp
        from bigbrotr.models import Relay

        relay = Relay("wss://relay.damus.io")
        f = Filter().kinds([Kind(1)]).since(Timestamp.from_secs(ts)).limit(100)

        async for event in fetch_relay_events(relay, f, timeout=30):
            print(f"Event {event.id[:8]}... kind={event.kind}")
        ```
    """
    client = await create_client(keys, proxy_url)
    await client.add_relay(RelayUrl.parse(relay.url))
    try:
        await client.connect()
        events = await client.fetch_events(event_filter, timedelta(seconds=timeout))
        for evt in events.to_vec():
            try:
                if evt.verify():
                    yield Event(evt)
            except (ValueError, TypeError, OverflowError):
                continue
    finally:
        with contextlib.suppress(Exception):
            await client.shutdown()
