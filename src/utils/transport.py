"""Nostr client transport utilities for BigBrotr.

Provides factory functions and custom transport classes for creating Nostr
clients with proper WebSocket configuration. Supports clearnet and overlay
network connections (Tor, I2P, Lokinet) via SOCKS5 proxies.

Key components:
    - ``create_client``: Standard client factory with optional SOCKS5 proxy.
    - ``create_insecure_client``: Client factory with SSL verification disabled.
    - ``connect_relay``: High-level helper with automatic SSL fallback.
    - ``is_nostr_relay``: Check whether a URL hosts a Nostr relay.

Also handles nostr-sdk UniFFI callback noise by filtering stderr output
from the Rust bindings.

Example::

    from utils.transport import create_client, connect_relay

    client = create_client(keys=my_keys, proxy_url="socks5://tor:9050")
    client = await connect_relay(relay, keys=my_keys, timeout=10.0)
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
from datetime import timedelta as Duration
from typing import TYPE_CHECKING, TextIO
from urllib.parse import urlparse

import aiohttp
from nostr_sdk import (
    Client,
    ClientBuilder,
    ClientOptions,
    Connection,
    ConnectionMode,
    ConnectionTarget,
    CustomWebSocketTransport,
    Filter,
    Kind,
    NostrSigner,
    RelayUrl,
    WebSocketAdapter,
    WebSocketAdapterWrapper,
    WebSocketMessage,
    uniffi_set_event_loop,
)


if TYPE_CHECKING:
    from collections.abc import Generator

    from nostr_sdk import Keys

from core.logger import Logger
from models.nips.base import DEFAULT_TIMEOUT
from models.relay import Relay
from utils.network import NetworkType


logger = Logger("utils.transport")

# Silence nostr-sdk UniFFI callback stack traces (handled by our code)
logging.getLogger("nostr_sdk").setLevel(logging.CRITICAL)


class _UniFFIStderrFilter:
    """Stderr wrapper that suppresses UniFFI traceback noise.

    UniFFI (the Rust-Python binding layer in nostr-sdk) prints tracebacks
    directly to stderr, bypassing Python's logging. This filter intercepts
    those messages and discards them while passing other output through.

    Stateful: enters suppression mode on seeing a UniFFI error header and
    exits on the next empty line (end of traceback).
    """

    def __init__(self, original: TextIO) -> None:
        self._original = original
        self._suppressing = False

    def write(self, text: str) -> int:
        """Write to stderr, suppressing UniFFI tracebacks."""
        if "UniFFI:" in text or "Unhandled exception" in text:
            self._suppressing = True
            return len(text)

        if self._suppressing:
            if text.strip() == "" or text == "\n":
                self._suppressing = False
            return len(text)

        return self._original.write(text)

    def flush(self) -> None:
        """Flush the underlying stream."""
        self._original.flush()

    def __getattr__(self, name: str) -> object:
        """Delegate attribute access to the original stderr stream."""
        return getattr(self._original, name)


if not isinstance(sys.stderr, _UniFFIStderrFilter):
    sys.stderr = _UniFFIStderrFilter(sys.stderr)


@contextlib.contextmanager
def _suppress_stderr() -> Generator[None, None, None]:
    """Completely suppress stderr by redirecting to /dev/null.

    More aggressive than ``_UniFFIStderrFilter``; used during relay
    validation where UniFFI noise is excessive.
    """
    old_stderr = sys.stderr
    with open(os.devnull, "w") as devnull:  # noqa: PTH123 (os.devnull is cross-platform)
        sys.stderr = devnull
        try:
            yield
        finally:
            sys.stderr = old_stderr


# Keywords indicating SSL/TLS certificate errors in nostr-sdk messages
_SSL_ERROR_KEYWORDS = frozenset(
    [
        "ssl",
        "tls",
        "certificate",
        "cert",
        "x509",
        "handshake",
        "verify",
    ]
)


def _is_ssl_error(error_message: str) -> bool:
    """Check if an error message indicates an SSL/TLS certificate error."""
    error_lower = error_message.lower()
    return any(keyword in error_lower for keyword in _SSL_ERROR_KEYWORDS)


class InsecureWebSocketAdapter(WebSocketAdapter):  # type: ignore[misc]
    """aiohttp-based WebSocket adapter with SSL verification disabled.

    Implements the nostr-sdk ``WebSocketAdapter`` interface. Allows connections
    to relays with self-signed, expired, or otherwise invalid certificates.
    """

    def __init__(
        self,
        ws: aiohttp.ClientWebSocketResponse,
        session: aiohttp.ClientSession,
    ) -> None:
        self._ws = ws
        self._session = session

    async def send(self, msg: WebSocketMessage) -> None:
        """Send a WebSocket message (text, binary, ping, or pong)."""
        if msg.is_text():
            await self._ws.send_str(msg.text)
        elif msg.is_binary():
            await self._ws.send_bytes(msg.bytes)
        elif msg.is_ping():
            await self._ws.ping(msg.bytes)
        elif msg.is_pong():
            await self._ws.pong(msg.bytes)

    async def recv(self) -> WebSocketMessage | None:
        """Receive the next WebSocket message (60s timeout).

        Returns:
            The received message in nostr-sdk format, or None if the
            connection closed, errored, or timed out.
        """
        try:
            msg = await asyncio.wait_for(self._ws.receive(), timeout=60.0)
        except TimeoutError:
            return None

        if msg.type == aiohttp.WSMsgType.TEXT:
            return WebSocketMessage.TEXT(msg.data)
        if msg.type == aiohttp.WSMsgType.BINARY:
            return WebSocketMessage.BINARY(msg.data)
        if msg.type == aiohttp.WSMsgType.PING:
            return WebSocketMessage.PING(msg.data)
        if msg.type == aiohttp.WSMsgType.PONG:
            return WebSocketMessage.PONG(msg.data)
        # CLOSE, CLOSED, ERROR -> connection terminated
        return None

    async def close_connection(self) -> None:
        """Close the WebSocket and session with timeouts to prevent hanging."""
        with contextlib.suppress(TimeoutError, Exception):
            await asyncio.wait_for(self._ws.close(), timeout=5.0)
        with contextlib.suppress(TimeoutError, Exception):
            await asyncio.wait_for(self._session.close(), timeout=5.0)


class InsecureWebSocketTransport(CustomWebSocketTransport):  # type: ignore[misc]
    """Custom WebSocket transport with SSL verification disabled.

    Used as a fallback for clearnet relays with invalid/expired certificates.
    Creates aiohttp sessions with an SSL context that accepts any certificate.

    Warning: Disables important security checks. Only use when SSL
    verification has already failed and the connection is still desired.
    """

    async def connect(
        self,
        url: str,
        _mode: ConnectionMode,
        timeout: Duration,
    ) -> WebSocketAdapterWrapper:
        """Connect to a relay URL without SSL certificate verification.

        Args:
            url: WebSocket URL (wss:// or ws://).
            _mode: Connection mode (unused; aiohttp handles this).
            timeout: Connection timeout as a timedelta.

        Returns:
            Wrapped adapter for nostr-sdk communication.

        Raises:
            OSError: On connection failure (network, timeout, DNS, etc.).
            asyncio.CancelledError: If cancelled.
        """
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        connector = aiohttp.TCPConnector(ssl=ssl_context)
        client_timeout = aiohttp.ClientTimeout(total=timeout.total_seconds())
        session = aiohttp.ClientSession(connector=connector, timeout=client_timeout)

        try:
            ws = await session.ws_connect(url)
        except aiohttp.ClientError as e:
            await session.close()
            logger.debug("insecure_ws_connect_failed", url=url, error=str(e))
            raise OSError(f"Connection failed: {e}") from e
        except TimeoutError:
            await session.close()
            logger.debug("insecure_ws_timeout", url=url)
            raise OSError(f"Connection timeout: {url}") from None
        except asyncio.CancelledError:
            await session.close()
            logger.debug("insecure_ws_cancelled", url=url)
            raise
        except BaseException as e:
            await session.close()
            logger.debug("insecure_ws_error", url=url, error=str(e))
            raise OSError(f"Connection failed: {e}") from e

        adapter = InsecureWebSocketAdapter(ws, session)
        return WebSocketAdapterWrapper(adapter)

    def support_ping(self) -> bool:
        """Return True (aiohttp handles ping/pong automatically)."""
        return True


def create_client(
    keys: Keys | None = None,
    proxy_url: str | None = None,
) -> Client:
    """Create a Nostr client with optional SOCKS5 proxy support.

    For overlay networks, uses nostr-sdk's built-in proxy via
    ``ConnectionMode.PROXY``. For clearnet, uses standard SSL connections.

    Args:
        keys: Optional signing keys (None = read-only client).
        proxy_url: SOCKS5 proxy URL for overlay networks (e.g., ``socks5://tor:9050``).

    Returns:
        Configured Client instance (call ``add_relay()`` before use).
    """
    builder = ClientBuilder()

    if keys is not None:
        signer = NostrSigner.keys(keys)
        builder = builder.signer(signer)

    if proxy_url is not None:
        parsed = urlparse(proxy_url)
        proxy_host = parsed.hostname or "127.0.0.1"
        proxy_port = parsed.port or 9050

        # nostr-sdk requires an IP address, not a hostname
        try:
            socket.inet_aton(proxy_host)  # Check if already an IP
        except OSError:
            proxy_host = socket.gethostbyname(proxy_host)

        proxy_mode = ConnectionMode.PROXY(proxy_host, proxy_port)
        conn = Connection().mode(proxy_mode).target(ConnectionTarget.ONION)
        opts = ClientOptions().connection(conn)
        builder = builder.opts(opts)

    return builder.build()


def create_insecure_client(keys: Keys | None = None) -> Client:
    """Create a Nostr client with SSL verification disabled.

    Fallback for clearnet relays with invalid/expired SSL certificates.

    Args:
        keys: Optional signing keys (None = read-only client).

    Returns:
        Client with insecure WebSocket transport.
    """
    builder = ClientBuilder()

    if keys is not None:
        signer = NostrSigner.keys(keys)
        builder = builder.signer(signer)

    transport = InsecureWebSocketTransport()
    builder = builder.websocket_transport(transport)

    return builder.build()


async def connect_relay(
    relay: Relay,
    keys: Keys | None = None,
    proxy_url: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    allow_insecure: bool = True,
) -> Client:
    """Connect to a relay with automatic SSL fallback for clearnet.

    Strategy:
        - Clearnet: Try SSL first; fall back to insecure if allowed.
        - Overlay (Tor/I2P/Loki): Require proxy, no SSL fallback.

    Args:
        relay: Relay to connect to.
        keys: Optional signing keys.
        proxy_url: SOCKS5 proxy URL (required for overlay networks).
        timeout: Connection timeout in seconds.
        allow_insecure: If True, fall back to insecure transport on SSL failure.

    Returns:
        Connected Client ready for use.

    Raises:
        TimeoutError: If connection times out.
        ValueError: If overlay relay requested without proxy_url.
        ssl.SSLCertVerificationError: If SSL fails and allow_insecure is False.
    """
    relay_url = RelayUrl.parse(relay.url)
    is_overlay = relay.network in (NetworkType.TOR, NetworkType.I2P, NetworkType.LOKI)

    if is_overlay:
        if proxy_url is None:
            raise ValueError(f"proxy_url required for {relay.network} relay: {relay.url}")

        client = create_client(keys, proxy_url)
        await client.add_relay(relay_url)
        await client.connect()
        await client.wait_for_connection(timedelta(seconds=timeout))

        relay_obj = await client.relay(relay_url)
        if not relay_obj.is_connected():
            await client.disconnect()
            raise TimeoutError(f"Connection timeout: {relay.url}")

        return client

    # Clearnet: try SSL first, then fall back to insecure if allowed
    logger.debug("ssl_connecting", relay=relay.url)

    client = create_client(keys)
    await client.add_relay(relay_url)
    output = await client.try_connect(timedelta(seconds=timeout))

    if relay_url in output.success:
        logger.debug("ssl_connected", relay=relay.url)
        return client

    await client.disconnect()
    error_message = output.failed.get(relay_url, "Unknown error")
    logger.debug("connect_failed", relay=relay.url, error=error_message)

    if not _is_ssl_error(error_message):
        # Not an SSL error - raise the original error
        raise TimeoutError(f"Connection failed: {relay.url} ({error_message})")

    if not allow_insecure:
        raise ssl.SSLCertVerificationError(
            f"SSL certificate verification failed for {relay.url}: {error_message}"
        )

    logger.debug("ssl_fallback_insecure", relay=relay.url, error=error_message)

    # Required for custom WebSocket transport UniFFI callbacks
    uniffi_set_event_loop(asyncio.get_running_loop())

    client = create_insecure_client(keys)
    await client.add_relay(relay_url)
    output = await client.try_connect(timedelta(seconds=timeout))

    if relay_url not in output.success:
        error_message = output.failed.get(relay_url, "Unknown error")
        await client.disconnect()
        raise TimeoutError(f"Connection failed (insecure): {relay.url} ({error_message})")

    logger.debug("insecure_connected", relay=relay.url)
    return client


async def is_nostr_relay(
    relay: Relay,
    proxy_url: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    suppress_stderr: bool = True,
) -> bool:
    """Check if a URL hosts a Nostr relay by attempting a protocol handshake.

    A relay is considered valid if it responds with EOSE to a REQ, sends
    an AUTH challenge (NIP-42), or returns a CLOSED with "auth-required".

    Args:
        relay: Relay to validate.
        proxy_url: SOCKS5 proxy URL (required for overlay networks).
        timeout: Timeout in seconds for connect and fetch operations.
        suppress_stderr: Suppress UniFFI traceback noise during validation.

    Returns:
        True if the relay speaks the Nostr protocol, False otherwise.
    """
    logger.debug("validation_started", relay=relay.url, timeout_s=timeout)

    # Safety net: 3x timeout + 15s buffer for potential SSL fallback retry
    overall_timeout = timeout * 3 + 15

    ctx = _suppress_stderr() if suppress_stderr else contextlib.nullcontext()

    with ctx:
        client = None
        try:
            async with asyncio.timeout(overall_timeout):
                client = await connect_relay(
                    relay=relay,
                    proxy_url=proxy_url,
                    timeout=timeout,
                )

                req_filter = Filter().kind(Kind(1)).limit(1)
                await client.fetch_events(req_filter, timedelta(seconds=timeout))
                logger.debug("validation_success", relay=relay.url, reason="eose")
                return True

        except TimeoutError:
            logger.debug("validation_timeout", relay=relay.url)
            return False

        except Exception as e:
            # AUTH-required errors indicate a valid Nostr relay (NIP-42)
            error_msg = str(e).lower()
            if "auth" in error_msg:
                logger.debug("validation_success", relay=relay.url, reason="auth")
                return True
            logger.debug("validation_failed", relay=relay.url, error=str(e))
            return False

        finally:
            if client is not None:
                with contextlib.suppress(TimeoutError, Exception):
                    await asyncio.wait_for(client.disconnect(), timeout=10.0)
