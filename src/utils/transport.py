"""Nostr client transport utilities.

Provides factory functions for creating Nostr clients with proper transport
configuration for clearnet and overlay networks (Tor, I2P, Loki).
"""

from __future__ import annotations

import asyncio
import logging
import socket
import ssl
from datetime import timedelta
from datetime import timedelta as Duration
from typing import TYPE_CHECKING
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

from models.relay import NetworkType, Relay


if TYPE_CHECKING:
    from nostr_sdk import Keys

logger = logging.getLogger(__name__)

# Silence nostr-sdk UniFFI callback stack traces (they're handled by our code)
logging.getLogger("nostr_sdk").setLevel(logging.CRITICAL)


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


# --- Insecure WebSocket Transport (per relay clearnet con certificati invalidi) ---


class InsecureWebSocketAdapter(WebSocketAdapter):
    """WebSocket adapter using aiohttp with SSL verification disabled.

    All methods are async as required by nostr-sdk's UniFFI bindings.
    """

    def __init__(
        self,
        ws: aiohttp.ClientWebSocketResponse,
        session: aiohttp.ClientSession,
    ) -> None:
        self._ws = ws
        self._session = session

    async def send(self, msg: WebSocketMessage) -> None:
        """Send a WebSocket message."""
        if msg.is_text():
            await self._ws.send_str(msg.text)
        elif msg.is_binary():
            await self._ws.send_bytes(msg.bytes)
        elif msg.is_ping():
            await self._ws.ping(msg.bytes)
        elif msg.is_pong():
            await self._ws.pong(msg.bytes)

    async def recv(self) -> WebSocketMessage | None:
        """Receive a message. Returns None when connection closes."""
        msg = await self._ws.receive()

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
        """Close the WebSocket connection."""
        await self._ws.close()
        await self._session.close()


class InsecureWebSocketTransport(CustomWebSocketTransport):
    """Custom WebSocket transport with SSL verification disabled.

    All methods are async as required by nostr-sdk's UniFFI bindings.
    """

    async def connect(
        self,
        url: str,
        mode: ConnectionMode,
        timeout: Duration,
    ) -> WebSocketAdapterWrapper:
        """Connect to relay without SSL verification."""
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        connector = aiohttp.TCPConnector(ssl=ssl_context)
        client_timeout = aiohttp.ClientTimeout(total=timeout.total_seconds())
        session = aiohttp.ClientSession(connector=connector, timeout=client_timeout)

        try:
            ws = await session.ws_connect(url)
        except aiohttp.ClientError as e:
            # Log at debug level and re-raise as IOError for nostr-sdk to handle
            await session.close()
            logger.debug("InsecureWebSocketTransport: connection failed url=%s error=%s", url, e)
            raise OSError(f"Connection failed: {e}") from e
        except asyncio.TimeoutError:
            await session.close()
            logger.debug("InsecureWebSocketTransport: connection timeout url=%s", url)
            raise OSError(f"Connection timeout: {url}") from None
        except Exception as e:
            await session.close()
            logger.debug("InsecureWebSocketTransport: unexpected error url=%s error=%s", url, e)
            raise OSError(f"Connection failed: {e}") from e

        adapter = InsecureWebSocketAdapter(ws, session)
        return WebSocketAdapterWrapper(adapter)

    def support_ping(self) -> bool:
        """aiohttp handles ping/pong automatically."""
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
    logger.debug("connect_relay: trying SSL connection relay=%s", relay.url)

    client = create_client(keys)
    await client.add_relay(relay_url)
    output = await client.try_connect(timedelta(seconds=timeout))

    # Check if connection succeeded
    if relay_url in output.success:
        logger.debug("connect_relay: SSL connection succeeded relay=%s", relay.url)
        return client

    # Connection failed - check error message
    await client.disconnect()
    error_message = output.failed.get(relay_url, "Unknown error")
    logger.debug("connect_relay: connection failed relay=%s error=%s", relay.url, error_message)

    # Check if it's an SSL error
    if not _is_ssl_error(error_message):
        # Not an SSL error - raise the original error
        raise TimeoutError(f"Connection failed: {relay.url} ({error_message})")

    # SSL certificate error - fallback if allowed
    if not allow_insecure:
        raise ssl.SSLCertVerificationError(
            f"SSL certificate verification failed for {relay.url}: {error_message}"
        )

    logger.info(
        "connect_relay: SSL certificate invalid, using insecure transport relay=%s error=%s",
        relay.url,
        error_message,
    )

    # Set event loop for UniFFI callbacks (required for custom WebSocket transport)
    uniffi_set_event_loop(asyncio.get_running_loop())

    client = create_insecure_client(keys)
    await client.add_relay(relay_url)
    output = await client.try_connect(timedelta(seconds=timeout))

    if relay_url not in output.success:
        error_message = output.failed.get(relay_url, "Unknown error")
        await client.disconnect()
        raise TimeoutError(f"Connection failed (insecure): {relay.url} ({error_message})")

    logger.warning("connect_relay: connected without SSL verification relay=%s", relay.url)
    return client


# --- Relay Validation ---


async def is_nostr_relay(
    relay: Relay,
    proxy_url: str | None = None,
    timeout: float = 10.0,
) -> bool:
    """Check if a relay speaks the Nostr protocol.

    A relay is considered valid if it:
    - Responds with EOSE to a REQ (even with no events)
    - Responds with AUTH challenge (NIP-42)
    - Responds with CLOSED containing "auth-required" (NIP-42)

    Args:
        relay: Relay object to validate.
        proxy_url: SOCKS5 proxy URL (required for overlay networks, None for clearnet).
        timeout: Connection timeout in seconds.

    Returns:
        True if relay speaks Nostr protocol, False otherwise.
    """
    from nostr_sdk import Filter, Kind  # noqa: PLC0415

    logger.debug("is_nostr_relay: starting relay=%s network=%s", relay.url, relay.network)

    try:
        client = await connect_relay(
            relay=relay,
            proxy_url=proxy_url,
            timeout=timeout,
        )

        try:
            # Send REQ for kind:1 limit:1
            req_filter = Filter().kind(Kind(1)).limit(1)

            # Wait for response with timeout
            # If relay responds with EOSE (even empty), it's valid
            await client.fetch_events(req_filter, timedelta(seconds=timeout))
            logger.debug("is_nostr_relay: valid (EOSE received) relay=%s", relay.url)
            return True

        finally:
            await client.disconnect()

    except Exception as e:
        # Check if the error indicates AUTH required (NIP-42)
        # This means the relay speaks Nostr but requires authentication
        error_msg = str(e).lower()
        if "auth" in error_msg:
            logger.debug("is_nostr_relay: valid (AUTH required) relay=%s", relay.url)
            return True
        logger.debug("is_nostr_relay: invalid relay=%s error=%s", relay.url, e)
        return False
