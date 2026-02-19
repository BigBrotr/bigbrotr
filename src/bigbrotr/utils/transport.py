"""Nostr client transport utilities for BigBrotr.

Provides factory functions and custom transport classes for creating Nostr
clients with proper WebSocket configuration. Supports clearnet and overlay
network connections (Tor, I2P, Lokinet) via SOCKS5 proxies.

Attributes:
    create_client: Standard client factory with optional SOCKS5 proxy.
    create_insecure_client: Client factory with SSL verification disabled.
    connect_relay: High-level helper with automatic SSL fallback.
    is_nostr_relay: Check whether a URL hosts a Nostr relay.

Also handles nostr-sdk UniFFI callback noise by filtering stderr output
from the Rust bindings.

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
    [bigbrotr.models.relay.Relay][bigbrotr.models.relay.Relay]: The relay
        model consumed by all connection functions.
    [bigbrotr.models.constants.NetworkType][bigbrotr.models.constants.NetworkType]:
        Enum used to select between clearnet and overlay transport strategies.
    [bigbrotr.core.pool][bigbrotr.core.pool]: Database connection pool (distinct
        from the WebSocket transport layer managed here).
    [bigbrotr.nips.nip66.rtt.Nip66RttMetadata][bigbrotr.nips.nip66.rtt.Nip66RttMetadata]:
        RTT probe that uses ``connect_relay`` for latency measurement.

Examples:
    ```python
    from bigbrotr.utils.transport import create_client, connect_relay

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
from dataclasses import dataclass
from datetime import timedelta
from datetime import timedelta as Duration  # noqa: N812
from ipaddress import AddressValueError, IPv4Address, IPv6Address
from typing import TYPE_CHECKING, Final, TextIO
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
    KindStandard,
    NostrSigner,
    RelayUrl,
    WebSocketAdapter,
    WebSocketAdapterWrapper,
    WebSocketMessage,
    uniffi_set_event_loop,
)


if TYPE_CHECKING:
    from collections.abc import Generator

    from nostr_sdk import EventBuilder, Keys

from bigbrotr.models.constants import NetworkType
from bigbrotr.models.relay import Relay  # noqa: TC001


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
            self._devnull = open(os.devnull, "w")  # noqa: PTH123, SIM115
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
        [create_insecure_client][bigbrotr.utils.transport.create_insecure_client]:
            Factory function that wires this transport into a client.
        [connect_relay][bigbrotr.utils.transport.connect_relay]: High-level
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


async def create_client(
    keys: Keys | None = None,
    proxy_url: str | None = None,
) -> Client:
    """Create a Nostr client with optional SOCKS5 proxy support.

    For overlay networks, uses nostr-sdk's built-in proxy via
    ``ConnectionMode.PROXY``. For clearnet, uses standard SSL connections.

    Args:
        keys: Optional signing keys (``None`` = read-only client).
        proxy_url: SOCKS5 proxy URL for overlay networks (e.g., ``socks5://tor:9050``).

    Returns:
        Configured ``Client`` instance (call ``add_relay()`` before use).

    Note:
        When a ``proxy_url`` hostname is not already an IP address, it is
        resolved asynchronously via ``asyncio.to_thread(socket.gethostbyname)``
        because nostr-sdk requires a numeric IP for the proxy connection.

    See Also:
        [create_insecure_client][bigbrotr.utils.transport.create_insecure_client]:
            Alternative factory with SSL verification disabled.
        [connect_relay][bigbrotr.utils.transport.connect_relay]: Higher-level
            function that handles connection and SSL fallback.
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


def create_insecure_client(keys: Keys | None = None) -> Client:
    """Create a Nostr client with SSL verification disabled.

    Fallback for clearnet relays with invalid/expired SSL certificates.

    Args:
        keys: Optional signing keys (``None`` = read-only client).

    Returns:
        ``Client`` with
        [InsecureWebSocketTransport][bigbrotr.utils.transport.InsecureWebSocketTransport].

    Warning:
        The returned client bypasses all SSL/TLS certificate verification.
        Only use when standard SSL has already been attempted and failed.

    See Also:
        [create_client][bigbrotr.utils.transport.create_client]: Standard
            factory with full SSL verification.
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
        [create_client][bigbrotr.utils.transport.create_client]: Used for the
            initial SSL-verified connection attempt.
        [create_insecure_client][bigbrotr.utils.transport.create_insecure_client]:
            Used for the fallback insecure connection.
        [is_nostr_relay][bigbrotr.utils.transport.is_nostr_relay]: Higher-level
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

    client = create_insecure_client(keys)
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
                relay, keys=keys, timeout=timeout, allow_insecure=allow_insecure,
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


@dataclass(frozen=True, slots=True)
class RelayValidationConfig:
    """Tuning parameters for relay validation timeouts.

    See Also:
        [is_nostr_relay][bigbrotr.utils.transport.is_nostr_relay]: The
            validation function that consumes this config.
    """

    suppress_stderr: bool = True
    overall_timeout_multiplier: float = 3.0
    overall_timeout_buffer: float = 15.0
    disconnect_timeout: float = 10.0


async def is_nostr_relay(
    relay: Relay,
    proxy_url: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,  # noqa: ASYNC109
    config: RelayValidationConfig | None = None,
    *,
    allow_insecure: bool = False,
) -> bool:
    """Check if a URL hosts a Nostr relay by attempting a protocol handshake.

    A relay is considered valid if it responds with EOSE to a REQ, sends
    an AUTH challenge (NIP-42), or returns a CLOSED with ``"auth-required"``.

    Args:
        relay: [Relay][bigbrotr.models.relay.Relay] to validate.
        proxy_url: SOCKS5 proxy URL (required for overlay networks).
        timeout: Timeout in seconds for connect and fetch operations.
        config: Optional validation tuning parameters (timeouts, stderr
            suppression). Uses
            [RelayValidationConfig][bigbrotr.utils.transport.RelayValidationConfig]
            defaults when ``None``.

    Returns:
        ``True`` if the relay speaks the Nostr protocol, ``False`` otherwise.

    Note:
        The overall timeout is computed as
        ``timeout * overall_timeout_multiplier + overall_timeout_buffer``
        to account for the potential SSL fallback retry in
        [connect_relay][bigbrotr.utils.transport.connect_relay]. Stderr
        suppression is enabled by default to silence verbose UniFFI
        tracebacks during batch validation.

    See Also:
        [connect_relay][bigbrotr.utils.transport.connect_relay]: Used
            internally to establish the WebSocket connection.
        [bigbrotr.services.validator.Validator][bigbrotr.services.validator.Validator]:
            Service that calls this function to promote candidates to relays.
    """
    cfg = config or RelayValidationConfig()

    logger.debug("validation_started relay=%s timeout_s=%s", relay.url, timeout)

    # Safety net: multiplier * timeout + buffer for potential SSL fallback retry
    overall_timeout = timeout * cfg.overall_timeout_multiplier + cfg.overall_timeout_buffer

    ctx = _suppress_stderr() if cfg.suppress_stderr else contextlib.nullcontext()

    with ctx:
        client = None
        try:
            async with asyncio.timeout(overall_timeout):
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
                    await asyncio.wait_for(client.disconnect(), timeout=cfg.disconnect_timeout)
