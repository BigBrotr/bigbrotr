"""Nostr protocol client operations for BigBrotr.

Provides client factory, relay connection with SSL fallback, event
broadcasting, and relay validation. Built on top of the
WebSocket transport primitives in
[bigbrotr.utils.transport][bigbrotr.utils.transport].

Attributes:
    create_client: Client factory with optional SOCKS5 proxy and SSL override.
    NostrClientManager: Shared manager for multi-relay sessions and lazy per-relay clients.
    connect_relay: High-level helper with automatic SSL fallback.
    is_nostr_relay: Check whether a URL hosts a Nostr relay.
    broadcast_events: Sign and broadcast events to multiple relays.

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
import inspect
import logging
import os
import socket
import ssl
import sys
from dataclasses import dataclass
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
from bigbrotr.models.relay import Relay  # noqa: TC001

from .transport import DEFAULT_TIMEOUT, InsecureWebSocketTransport


if TYPE_CHECKING:
    from collections.abc import Generator

    from nostr_sdk import EventBuilder, Keys

    from bigbrotr.services.common.configs import NetworksConfig


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

    nostr-sdk's Rust FFI layer writes diagnostic output directly to the
    process stderr file descriptor from arbitrary native threads.  Because
    these writes bypass Python's I/O stack and are not associated with any
    Python thread, there is no way to selectively suppress only nostr-sdk
    output while preserving stderr from other libraries.

    Trade-off: while the suppressor is active, ALL stderr output -- including
    from unrelated libraries -- is redirected to ``/dev/null``.  This is an
    intentional choice: the alternative (e.g. dup2 tricks or pty-based
    filtering) would be significantly more complex and fragile for negligible
    benefit.

    Mitigation: the suppression scope is deliberately narrow, wrapping only
    the short ``is_nostr_relay`` validation window (connect + single event
    fetch).  Any stderr produced outside that window is unaffected.

    Multiple concurrent async tasks can enter suppression without blocking
    the event loop.  A ``threading.Lock`` would deadlock here because the
    context manager ``yield`` crosses ``await`` boundaries; instead, a
    simple reference count tracks active suppressors.
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


@dataclass(frozen=True, slots=True)
class ClientConnectResult:
    """Normalized outcome of connecting one client to multiple relays."""

    connected: tuple[str, ...]
    failed: dict[str, str]


@dataclass(frozen=True, slots=True)
class BroadcastClientResult:
    """Normalized per-client outcome of publishing one or more events."""

    event_ids: tuple[str, ...]
    successful_relays: tuple[str, ...]
    failed_relays: dict[str, str]


@dataclass(frozen=True, slots=True)
class ClientSession:
    """Connected multi-relay client session managed by NostrClientManager."""

    session_id: str
    client: Client
    relay_urls: tuple[str, ...]
    connect_result: ClientConnectResult


class NostrClientManager:
    """Shared lifecycle manager for nostr-sdk clients.

    Supports two patterns used across the codebase:

    - cached per-relay publishing clients (`get_relay_client`)
    - named multi-relay sessions (`connect_session`)
    """

    __slots__ = (
        "_allow_insecure",
        "_failed_relays",
        "_keys",
        "_networks",
        "_relay_clients",
        "_sessions",
    )

    def __init__(
        self,
        *,
        keys: Keys | None = None,
        networks: NetworksConfig | None = None,
        allow_insecure: bool = False,
    ) -> None:
        self._keys = keys
        self._networks = networks
        self._allow_insecure = allow_insecure
        self._relay_clients: dict[str, Client] = {}
        self._failed_relays: set[str] = set()
        self._sessions: dict[str, ClientSession] = {}

    async def get_relay_client(self, relay: Relay) -> Client | None:
        """Return one lazily connected client for a single relay."""
        if relay.url in self._relay_clients:
            return self._relay_clients[relay.url]
        if relay.url in self._failed_relays:
            return None
        if self._networks is None:
            raise RuntimeError("networks configuration required for relay-scoped clients")

        proxy_url = self._networks.get_proxy_url(relay.network)
        timeout = self._networks.get(relay.network).timeout
        try:
            client = await connect_relay(
                relay,
                keys=self._keys,
                proxy_url=proxy_url,
                timeout=timeout,
                allow_insecure=self._allow_insecure,
            )
        except (OSError, TimeoutError) as e:
            logger.warning("connect_client_failed relay=%s error=%s", relay.url, e)
            self._failed_relays.add(relay.url)
            return None

        self._relay_clients[relay.url] = client
        return client

    async def get_relay_clients(self, relays: list[Relay]) -> list[Client]:
        """Return connected clients for the provided relays."""
        clients: list[Client] = []
        for relay in relays:
            client = await self.get_relay_client(relay)
            if client is not None:
                clients.append(client)
        return clients

    async def connect_session(
        self,
        session_id: str,
        relays: list[Relay],
        *,
        timeout: float = DEFAULT_TIMEOUT,  # noqa: ASYNC109
    ) -> ClientSession:
        """Create or reuse a named multi-relay session."""
        relay_urls = tuple(relay.url for relay in relays)
        existing = self._sessions.get(session_id)
        if existing is not None:
            if existing.relay_urls != relay_urls:
                raise ValueError(f"session {session_id!r} already exists with different relays")
            return existing

        client = await create_client(keys=self._keys, allow_insecure=self._allow_insecure)
        result = await _connect_client_relays(client, relays, timeout=timeout)
        session = ClientSession(
            session_id=session_id,
            client=client,
            relay_urls=relay_urls,
            connect_result=result,
        )
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> ClientSession | None:
        """Return a previously opened session, if present."""
        return self._sessions.get(session_id)

    async def disconnect(self) -> None:
        """Disconnect all managed clients and clear cached state."""
        seen: set[int] = set()

        for session in self._sessions.values():
            client_id = id(session.client)
            if client_id in seen:
                continue
            seen.add(client_id)
            with contextlib.suppress(OSError, RuntimeError, TimeoutError):
                await shutdown_client(session.client)

        for client in self._relay_clients.values():
            client_id = id(client)
            if client_id in seen:
                continue
            seen.add(client_id)
            with contextlib.suppress(OSError, RuntimeError, TimeoutError):
                await shutdown_client(client)

        self._sessions.clear()
        self._relay_clients.clear()
        self._failed_relays.clear()


async def _await_if_needed(value: object) -> object:
    """Await ``value`` when it is awaitable, otherwise return it as-is."""
    if inspect.isawaitable(value):
        return await value
    return value


async def shutdown_client(client: Client) -> None:
    """Fully release a nostr-sdk Client's resources before shutdown.

    ``Client.shutdown()`` alone does not release the internal event
    database, active subscriptions, or relay connection state on the
    Rust side, causing monotonic RSS growth.  This helper performs a
    full cleanup sequence before calling ``shutdown()``.
    """
    with contextlib.suppress(Exception):
        await _await_if_needed(client.unsubscribe_all())
    with contextlib.suppress(Exception):
        await _await_if_needed(client.force_remove_all_relays())
    with contextlib.suppress(Exception):
        database = await _await_if_needed(client.database())
        await _await_if_needed(database.wipe())  # type: ignore[attr-defined]
    with contextlib.suppress(Exception):
        await _await_if_needed(client.shutdown())


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


async def _connect_client_relays(
    client: Client,
    relays: list[Relay],
    *,
    timeout: float = DEFAULT_TIMEOUT,  # noqa: ASYNC109
) -> ClientConnectResult:
    """Register relays on one client and normalize the connection outcome."""
    for relay in relays:
        await client.add_relay(RelayUrl.parse(relay.url))

    output = await client.try_connect(timedelta(seconds=timeout))
    connected = tuple(str(relay_url) for relay_url in getattr(output, "success", ()))
    failed = {
        str(relay_url): str(error) for relay_url, error in getattr(output, "failed", {}).items()
    }
    return ClientConnectResult(connected=connected, failed=failed)


async def create_connected_client(
    relays: list[Relay],
    *,
    keys: Keys | None = None,
    timeout: float = DEFAULT_TIMEOUT,  # noqa: ASYNC109
    allow_insecure: bool = False,
) -> tuple[Client, ClientConnectResult]:
    """Create a client, register relays, and connect with a normalized result."""
    client = await create_client(keys=keys, allow_insecure=allow_insecure)
    return client, await _connect_client_relays(client, relays, timeout=timeout)


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
            await shutdown_client(client)
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

    await shutdown_client(client)
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
        await shutdown_client(client)
        raise OSError(f"Connection failed (insecure): {relay.url} ({error_message})")

    logger.debug("insecure_connected relay=%s", relay.url)
    return client


async def broadcast_events(
    builders: list[EventBuilder],
    clients: list[Client],
) -> int:
    """Broadcast Nostr events to pre-connected clients.

    Each client must already be connected and configured with a signer.
    The caller is responsible for creating, connecting, and shutting down
    the clients.

    Args:
        builders: Event builders to sign and send.
        clients: Pre-connected ``Client`` instances.

    Returns:
        Number of clients that successfully received all events.
    """
    detailed_results = await broadcast_events_detailed(builders, clients)
    return sum(1 for result in detailed_results if result.successful_relays)


async def broadcast_events_detailed(
    builders: list[EventBuilder],
    clients: list[Client],
) -> list[BroadcastClientResult]:
    """Broadcast events and preserve the per-relay send semantics from nostr-sdk."""
    if not builders or not clients:
        return []

    results: list[BroadcastClientResult] = []
    for client in clients:
        try:
            event_ids: list[str] = []
            successful_relays: set[str] | None = None
            failed_relays: dict[str, str] = {}

            for builder in builders:
                output = await client.send_event_builder(builder)
                event_ids.append(str(getattr(output, "id", "")))

                builder_success = {str(relay_url) for relay_url in getattr(output, "success", ())}
                builder_failed = {
                    str(relay_url): str(error)
                    for relay_url, error in getattr(output, "failed", {}).items()
                }

                if successful_relays is None:
                    successful_relays = set(builder_success)
                else:
                    successful_relays.intersection_update(builder_success)
                failed_relays.update(builder_failed)

            results.append(
                BroadcastClientResult(
                    event_ids=tuple(event_ids),
                    successful_relays=tuple(sorted(successful_relays or ())),
                    failed_relays=failed_relays,
                )
            )
        except (OSError, TimeoutError) as e:
            logger.warning("broadcast_send_failed error=%s", e)

    return results


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
                try:
                    await asyncio.wait_for(shutdown_client(client), timeout=timeout)
                except (OSError, RuntimeError, TimeoutError) as e:
                    logger.debug("client_shutdown_error error=%s", e)
                del client
