"""Nostr client transport utilities for BigBrotr.

This module provides factory functions and transport classes for creating
Nostr clients with proper WebSocket configuration. It supports both clearnet
and overlay network connections (Tor, I2P, Lokinet) via SOCKS5 proxies.

Key Components:
    - create_client: Factory for standard Nostr clients with optional proxy
    - create_insecure_client: Factory for clients with SSL verification disabled
    - connect_relay: High-level helper with automatic SSL fallback
    - is_nostr_relay: Validation function to check if a URL is a Nostr relay

Transport Classes:
    - InsecureWebSocketTransport: Custom transport bypassing SSL verification
    - InsecureWebSocketAdapter: aiohttp-based WebSocket adapter

The module also handles nostr-sdk's UniFFI callback noise by filtering
stderr output from the Rust bindings.

Example:
    >>> from utils.transport import create_client, connect_relay
    >>> # Simple client creation
    >>> client = create_client(keys=my_keys, proxy_url="socks5://tor:9050")
    >>> # High-level connection with SSL fallback
    >>> client = await connect_relay(relay, keys=my_keys, timeout=10.0)
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
    NostrSigner,
    RelayUrl,
    WebSocketAdapter,
    WebSocketAdapterWrapper,
    WebSocketMessage,
    uniffi_set_event_loop,
)

from core.logger import Logger
from models.relay import NetworkType, Relay


if TYPE_CHECKING:
    from nostr_sdk import Keys

logger = Logger("utils.transport")

# Silence nostr-sdk UniFFI callback stack traces (they're handled by our code)
logging.getLogger("nostr_sdk").setLevel(logging.CRITICAL)


class _UniFFIStderrFilter:
    """Filter that suppresses UniFFI traceback noise from stderr.

    UniFFI (the Rust-Python binding layer used by nostr-sdk) prints
    "Unhandled exception in trait interface call" with full tracebacks
    directly to stderr, bypassing Python's logging system. This filter
    wraps stderr and suppresses those specific messages while allowing
    other stderr output through.

    The filter is stateful: when it sees a UniFFI error header, it enters
    suppression mode and discards all output until an empty line (which
    marks the end of the traceback).

    Attributes:
        _original: The original stderr stream being wrapped.
        _suppressing: Whether currently in suppression mode.
    """

    def __init__(self, original: TextIO) -> None:
        """Initialize the stderr filter.

        Args:
            original: The original stderr TextIO stream to wrap.
        """
        self._original = original
        self._suppressing = False

    def write(self, text: str) -> int:
        """Write text to stderr, filtering UniFFI tracebacks.

        Args:
            text: Text to write to stderr.

        Returns:
            int: Number of characters "written" (actual or suppressed).
        """
        # Start suppressing when we see UniFFI error header
        if "UniFFI:" in text or "Unhandled exception" in text:
            self._suppressing = True
            return len(text)

        # Stop suppressing after empty line (end of traceback)
        if self._suppressing:
            if text.strip() == "" or text == "\n":
                self._suppressing = False
            return len(text)

        # Pass through normal output
        return self._original.write(text)

    def flush(self) -> None:
        """Flush the underlying stderr stream."""
        self._original.flush()

    def __getattr__(self, name: str) -> object:
        """Delegate attribute access to the original stderr stream.

        Args:
            name: Attribute name to look up.

        Returns:
            The attribute from the original stderr stream.
        """
        return getattr(self._original, name)


# Install the stderr filter once at module import
if not isinstance(sys.stderr, _UniFFIStderrFilter):
    sys.stderr = _UniFFIStderrFilter(sys.stderr)


@contextlib.contextmanager
def _suppress_stderr():
    """Context manager to completely suppress all stderr output.

    Redirects stderr to /dev/null for the duration of the context.
    Used as a fallback when complete stderr suppression is needed,
    such as during relay validation where UniFFI noise is excessive.

    Yields:
        None: Control returns to the caller with stderr redirected.

    Note:
        This is more aggressive than _UniFFIStderrFilter and should
        only be used when you're certain no important errors will
        be printed to stderr.
    """
    old_stderr = sys.stderr
    with open(os.devnull, "w") as devnull:  # noqa: PTH123 (os.devnull is cross-platform)
        sys.stderr = devnull
        try:
            yield
        finally:
            sys.stderr = old_stderr


# --- SSL Error Detection ---

# Keywords that indicate an SSL/TLS certificate error in nostr-sdk error messages
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
    """Check if an error message indicates an SSL/TLS certificate error.

    Args:
        error_message: Error message from nostr-sdk connection failure.

    Returns:
        True if the error appears to be SSL/TLS related.
    """
    error_lower = error_message.lower()
    return any(keyword in error_lower for keyword in _SSL_ERROR_KEYWORDS)


# --- Insecure WebSocket Transport (for clearnet relays with invalid certificates) ---


class InsecureWebSocketAdapter(WebSocketAdapter):
    """WebSocket adapter using aiohttp with SSL verification disabled.

    This adapter implements the nostr-sdk WebSocketAdapter interface using
    aiohttp as the underlying WebSocket library. SSL certificate verification
    is disabled, allowing connections to relays with self-signed, expired,
    or otherwise invalid certificates.

    All methods are async as required by nostr-sdk's UniFFI bindings.

    Attributes:
        _ws: The aiohttp WebSocket response object.
        _session: The aiohttp client session (must be closed with connection).
    """

    def __init__(
        self,
        ws: aiohttp.ClientWebSocketResponse,
        session: aiohttp.ClientSession,
    ) -> None:
        """Initialize the WebSocket adapter.

        Args:
            ws: An established aiohttp WebSocket connection.
            session: The aiohttp ClientSession that owns the connection.
                Must be kept alive for the duration of the connection.
        """
        self._ws = ws
        self._session = session

    async def send(self, msg: WebSocketMessage) -> None:
        """Send a WebSocket message to the relay.

        Args:
            msg: The nostr-sdk WebSocketMessage to send. Can be text,
                binary, ping, or pong frame types.
        """
        if msg.is_text():
            await self._ws.send_str(msg.text)
        elif msg.is_binary():
            await self._ws.send_bytes(msg.bytes)
        elif msg.is_ping():
            await self._ws.ping(msg.bytes)
        elif msg.is_pong():
            await self._ws.pong(msg.bytes)

    async def recv(self) -> WebSocketMessage | None:
        """Receive a WebSocket message from the relay.

        Waits for the next message with a 60-second timeout. This timeout
        is generous but prevents indefinite blocking if the server stops
        responding without closing the connection.

        Returns:
            WebSocketMessage | None: The received message converted to
                nostr-sdk format, or None if the connection closed,
                errored, or timed out.
        """
        try:
            # Timeout prevents indefinite blocking if server stops responding.
            # 60s is generous - if no frame (including pings) for 60s, connection is dead.
            msg = await asyncio.wait_for(self._ws.receive(), timeout=60.0)
        except TimeoutError:
            # Treat recv timeout as connection termination
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
        """Close the WebSocket connection and session with timeout.

        Attempts graceful close of both the WebSocket and the underlying
        aiohttp session. Uses timeouts to prevent hanging if the server
        doesn't respond to the close handshake.
        """
        try:
            # Don't wait forever for close handshake - server may not respond
            await asyncio.wait_for(self._ws.close(), timeout=5.0)
        except (TimeoutError, Exception):
            pass
        try:
            await asyncio.wait_for(self._session.close(), timeout=5.0)
        except (TimeoutError, Exception):
            pass


class InsecureWebSocketTransport(CustomWebSocketTransport):
    """Custom WebSocket transport with SSL certificate verification disabled.

    This transport is used as a fallback when connecting to clearnet relays
    that have invalid, expired, or self-signed SSL certificates. It uses
    aiohttp with an SSL context that accepts any certificate.

    Warning:
        Using this transport disables important security checks. Only use
        for relays where SSL verification has already failed and you've
        decided to proceed anyway.

    All methods are async as required by nostr-sdk's UniFFI bindings.
    """

    async def connect(
        self,
        url: str,
        mode: ConnectionMode,
        timeout: Duration,
    ) -> WebSocketAdapterWrapper:
        """Establish a WebSocket connection without SSL verification.

        Creates an aiohttp session with SSL verification disabled and
        connects to the specified relay URL.

        Args:
            url: The WebSocket URL to connect to (wss:// or ws://).
            mode: The nostr-sdk ConnectionMode (unused, aiohttp handles it).
            timeout: Connection timeout as a timedelta.

        Returns:
            WebSocketAdapterWrapper: Wrapper around the InsecureWebSocketAdapter
                that nostr-sdk can use for communication.

        Raises:
            OSError: If the connection fails for any reason (network error,
                timeout, DNS failure, etc.).
            asyncio.CancelledError: If the connection attempt is cancelled.
        """
        # Create SSL context that accepts any certificate
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        connector = aiohttp.TCPConnector(ssl=ssl_context)
        client_timeout = aiohttp.ClientTimeout(total=timeout.total_seconds())
        session = aiohttp.ClientSession(connector=connector, timeout=client_timeout)

        try:
            ws = await session.ws_connect(url)
        except aiohttp.ClientError as e:
            # Log at debug level and re-raise as OSError for nostr-sdk to handle
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
        """Check if this transport supports WebSocket ping frames.

        Returns:
            bool: Always True, as aiohttp handles ping/pong automatically.
        """
        return True


# --- Client Factory Functions ---


def create_client(
    keys: Keys | None = None,
    proxy_url: str | None = None,
) -> Client:
    """Create a Nostr client with optional SOCKS5 proxy.

    For overlay networks (tor/i2p/loki):
        Uses nostr-sdk's built-in SOCKS5 proxy support via ConnectionMode.PROXY.

    For clearnet relays:
        Uses standard nostr-sdk client with SSL verification.

    Args:
        keys: Optional Keys for signing events. If None, client will be read-only.
        proxy_url: SOCKS5 proxy URL for overlay networks.

    Returns:
        Configured Client instance (no relays added - call add_relay() separately)
    """
    builder = ClientBuilder()

    if keys is not None:
        signer = NostrSigner.keys(keys)
        builder = builder.signer(signer)

    if proxy_url is not None:
        parsed = urlparse(proxy_url)
        proxy_host = parsed.hostname or "127.0.0.1"
        proxy_port = parsed.port or 9050

        # nostr-sdk requires IP address, not hostname - resolve if needed
        try:
            socket.inet_aton(proxy_host)  # Check if already an IP
        except OSError:
            # Not an IP, resolve hostname to IP
            proxy_host = socket.gethostbyname(proxy_host)

        proxy_mode = ConnectionMode.PROXY(proxy_host, proxy_port)
        conn = Connection().mode(proxy_mode).target(ConnectionTarget.ONION)
        opts = ClientOptions().connection(conn)
        builder = builder.opts(opts)

    return builder.build()


def create_insecure_client(keys: Keys | None = None) -> Client:
    """Create a Nostr client with SSL verification disabled.

    Used as fallback for clearnet relays with invalid/expired certificates.
    Should only be used when standard SSL connection fails.

    Args:
        keys: Optional Keys for signing events. If None, client will be read-only.

    Returns:
        Configured Client instance with insecure WebSocket transport.
    """
    builder = ClientBuilder()

    if keys is not None:
        signer = NostrSigner.keys(keys)
        builder = builder.signer(signer)

    transport = InsecureWebSocketTransport()
    builder = builder.websocket_transport(transport)

    return builder.build()


# --- Connection Helper ---


async def connect_relay(
    relay: Relay,
    keys: Keys | None = None,
    proxy_url: str | None = None,
    timeout: float = 10.0,
    allow_insecure: bool = True,
) -> Client:
    """Connect to a relay with optional SSL fallback for clearnet.

    Connection strategy based on network type:
        - Clearnet: Try SSL first, fallback to insecure if allowed and SSL fails
        - Overlay (Tor/I2P/Loki): Use proxy connection (no SSL fallback)

    Args:
        relay: Relay model instance to connect to.
        keys: Optional Keys for signing events.
        proxy_url: SOCKS5 proxy URL (required for overlay networks).
        timeout: Connection timeout in seconds.
        allow_insecure: If True (default), fallback to insecure transport for
            clearnet relays with invalid SSL certificates. If False, only
            connect to relays with valid SSL certificates.

    Returns:
        Connected Client instance ready for use.

    Raises:
        TimeoutError: If connection times out.
        ValueError: If overlay relay requested without proxy_url.
        ssl.SSLCertVerificationError: If SSL certificate is invalid and
            allow_insecure=False.

    Example:
        relay = Relay("wss://relay.damus.io")
        client = await connect_relay(relay, keys)
        events = await client.fetch_events(filter, timeout)
    """
    relay_url = RelayUrl.parse(relay.url)
    is_overlay = relay.network in (NetworkType.TOR, NetworkType.I2P, NetworkType.LOKI)

    # Overlay networks: require proxy, no SSL fallback
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

    # Clearnet: try with SSL verification first using try_connect()
    # try_connect() returns Output with success/failed lists and error messages
    logger.debug("ssl_connecting", relay=relay.url)

    client = create_client(keys)
    await client.add_relay(relay_url)
    output = await client.try_connect(timedelta(seconds=timeout))

    # Check if connection succeeded
    if relay_url in output.success:
        logger.debug("ssl_connected", relay=relay.url)
        return client

    # Connection failed - check error message
    await client.disconnect()
    error_message = output.failed.get(relay_url, "Unknown error")
    logger.debug("connect_failed", relay=relay.url, error=error_message)

    # Check if it's an SSL error
    if not _is_ssl_error(error_message):
        # Not an SSL error - raise the original error
        raise TimeoutError(f"Connection failed: {relay.url} ({error_message})")

    # SSL certificate error - fallback if allowed
    if not allow_insecure:
        raise ssl.SSLCertVerificationError(
            f"SSL certificate verification failed for {relay.url}: {error_message}"
        )

    logger.debug("ssl_fallback_insecure", relay=relay.url, error=error_message)

    # Set event loop for UniFFI callbacks (required for custom WebSocket transport)
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


# --- Relay Validation ---


async def is_nostr_relay(
    relay: Relay,
    proxy_url: str | None = None,
    timeout: float = 10.0,
    suppress_stderr: bool = True,
) -> bool:
    """Check if a relay speaks the Nostr protocol.

    A relay is considered valid if it:
    - Responds with EOSE to a REQ (even with no events)
    - Responds with AUTH challenge (NIP-42)
    - Responds with CLOSED containing "auth-required" (NIP-42)

    Args:
        relay: Relay object to validate.
        proxy_url: SOCKS5 proxy URL (required for overlay networks, None for clearnet).
        timeout: Timeout in seconds for connect and fetch operations.
        suppress_stderr: If True (default), suppress UniFFI traceback noise on stderr.

    Returns:
        True if relay speaks Nostr protocol, False otherwise.
    """
    from nostr_sdk import Filter, Kind

    logger.debug("validation_started", relay=relay.url, timeout_s=timeout)

    # Overall timeout as safety net: connect + fetch + disconnect
    # 3x the specified timeout should be enough for normal operations
    overall_timeout = timeout * 3 + 15  # +15s buffer for SSL fallback retry

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
            # Check if the error indicates AUTH required (NIP-42)
            error_msg = str(e).lower()
            if "auth" in error_msg:
                logger.debug("validation_success", relay=relay.url, reason="auth")
                return True
            logger.debug("validation_failed", relay=relay.url, error=str(e))
            return False

        finally:
            if client is not None:
                try:
                    # Don't let disconnect hang the entire operation
                    await asyncio.wait_for(client.disconnect(), timeout=10.0)
                except (TimeoutError, Exception):
                    pass
