"""WebSocket transport primitives for BigBrotr.

Provides custom WebSocket transport classes for nostr-sdk with SSL
verification bypass and UniFFI stderr noise suppression. These are
low-level building blocks consumed by
[bigbrotr.utils.protocol][bigbrotr.utils.protocol].

Attributes:
    DEFAULT_TIMEOUT: Default timeout for network operations (10 seconds).
    InsecureWebSocketAdapter: aiohttp WebSocket adapter with SSL disabled.
    InsecureWebSocketTransport: nostr-sdk custom transport wrapping the adapter.

Note:
    The ``_NostrSdkStderrFilter`` is installed globally at import time to
    suppress UniFFI traceback noise from nostr-sdk's Rust layer. This is
    separate from the ``_StderrSuppressor`` in
    [bigbrotr.utils.protocol][bigbrotr.utils.protocol] which provides
    batch-level suppression during relay validation.

See Also:
    [bigbrotr.utils.protocol][bigbrotr.utils.protocol]: Higher-level Nostr
        protocol operations built on these transport primitives.
    [bigbrotr.models.relay.Relay][bigbrotr.models.relay.Relay]: The relay
        model consumed by connection functions.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import ssl
import sys
from typing import TYPE_CHECKING, Final, TextIO

import aiohttp
from nostr_sdk import (
    ConnectionMode,
    CustomWebSocketTransport,
    WebSocketAdapter,
    WebSocketAdapterWrapper,
    WebSocketMessage,
)


if TYPE_CHECKING:
    from datetime import timedelta as Duration  # noqa: N812


DEFAULT_TIMEOUT: Final[float] = 10.0


logger = logging.getLogger("utils.transport")

# Silence nostr-sdk UniFFI callback stack traces (handled by our code)
logging.getLogger("nostr_sdk").setLevel(logging.CRITICAL)


class _NostrSdkStderrFilter:
    """Stderr wrapper that suppresses UniFFI traceback noise.

    UniFFI (the Rust-Python binding layer in nostr-sdk) prints tracebacks
    directly to stderr, bypassing Python's logging. This filter intercepts
    those messages and discards them while passing other output through.

    Stateful: enters suppression mode on seeing a UniFFI error header and
    exits on the next empty line (end of traceback).

    Note:
        This filter is installed globally at module import time. It wraps
        ``sys.stderr`` once, checked via ``isinstance`` to prevent double-
        wrapping on repeated imports.
    """

    __slots__ = ("_original", "_suppressing")

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


# nostr-sdk's Rust layer (via UniFFI) prints tracebacks directly to stderr
# from background threads, bypassing Python's logging entirely. Neither
# contextlib.redirect_stderr nor logging.Filter can intercept this output
# because it originates from non-Python threads. A global stderr wrapper is
# the only way to suppress it.
if not isinstance(sys.stderr, _NostrSdkStderrFilter):
    sys.stderr = _NostrSdkStderrFilter(sys.stderr)


_WS_RECV_TIMEOUT = 60.0
_WS_CLOSE_TIMEOUT = 5.0


class InsecureWebSocketAdapter(WebSocketAdapter):
    """aiohttp-based WebSocket adapter with SSL verification disabled.

    Implements the ``nostr_sdk.WebSocketAdapter`` interface. Allows connections
    to relays with self-signed, expired, or otherwise invalid certificates.

    Warning:
        This adapter creates an ``ssl.SSLContext`` with ``CERT_NONE`` and
        ``check_hostname=False``, disabling all certificate verification.
        It should only be used as a fallback after standard SSL has failed.

    See Also:
        [InsecureWebSocketTransport][bigbrotr.utils.transport.InsecureWebSocketTransport]:
            The transport class that creates instances of this adapter.
    """

    def __init__(
        self,
        ws: aiohttp.ClientWebSocketResponse,
        session: aiohttp.ClientSession,
        recv_timeout: float = _WS_RECV_TIMEOUT,
        close_timeout: float = _WS_CLOSE_TIMEOUT,
    ) -> None:
        self._ws = ws
        self._session = session
        self._recv_timeout = recv_timeout
        self._close_timeout = close_timeout

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
            msg = await asyncio.wait_for(self._ws.receive(), timeout=self._recv_timeout)
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
        # aiohttp/websockets can raise ClientError, ServerDisconnectedError, etc.
        # during close — broad suppression is intentional for cleanup teardown.
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self._ws.close(), timeout=self._close_timeout)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self._session.close(), timeout=self._close_timeout)


class InsecureWebSocketTransport(CustomWebSocketTransport):
    """Custom WebSocket transport with SSL verification disabled.

    Used as a fallback for clearnet relays with invalid/expired certificates.
    Creates aiohttp sessions with an SSL context that accepts any certificate.

    Warning:
        Disables **all** SSL/TLS certificate verification, including hostname
        checking and chain validation. This makes the connection vulnerable to
        man-in-the-middle attacks. Only use when standard SSL verification has
        already failed and the connection is still desired (e.g., monitoring
        relays with self-signed certificates).

    Note:
        This transport implements the ``nostr_sdk.CustomWebSocketTransport``
        interface so it can be injected into the nostr-sdk client via
        ``ClientBuilder.websocket_transport()``. The UniFFI event loop must
        be set via ``uniffi_set_event_loop()`` before using this transport.

    See Also:
        [InsecureWebSocketAdapter][bigbrotr.utils.transport.InsecureWebSocketAdapter]:
            The per-connection adapter created by this transport.
        [create_client][bigbrotr.utils.protocol.create_client]: Factory function
            that wires this transport into a client via ``allow_insecure=True``.
        [connect_relay][bigbrotr.utils.protocol.connect_relay]: High-level
            function that uses this transport as an SSL fallback.
    """

    def __init__(
        self,
        recv_timeout: float = _WS_RECV_TIMEOUT,
        close_timeout: float = _WS_CLOSE_TIMEOUT,
    ) -> None:
        self._recv_timeout = recv_timeout
        self._close_timeout = close_timeout

    async def connect(
        self,
        url: str,
        _mode: ConnectionMode,
        timeout: Duration,  # noqa: ASYNC109
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
            logger.debug("insecure_ws_connect_failed url=%s error=%s", url, str(e))
            raise OSError(f"Connection failed: {e}") from e
        except TimeoutError:
            await session.close()
            logger.debug("insecure_ws_timeout url=%s", url)
            raise OSError(f"Connection timeout: {url}") from None
        except asyncio.CancelledError:
            await session.close()
            logger.debug("insecure_ws_cancelled url=%s", url)
            raise
        except (ssl.SSLError, OSError) as e:
            await session.close()
            logger.debug("insecure_ws_error url=%s error=%s", url, str(e))
            raise OSError(f"Connection failed: {e}") from e

        adapter = InsecureWebSocketAdapter(
            ws,
            session,
            recv_timeout=self._recv_timeout,
            close_timeout=self._close_timeout,
        )
        return WebSocketAdapterWrapper(adapter)

    def support_ping(self) -> bool:
        """Return True (aiohttp handles ping/pong automatically)."""
        return True
