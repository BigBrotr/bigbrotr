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
import logging
import ssl
from datetime import timedelta
from typing import TYPE_CHECKING

from nostr_sdk import (
    Client,
    RelayUrl,
    uniffi_set_event_loop,
)

from bigbrotr.models.constants import NetworkType
from bigbrotr.models.relay import Relay  # noqa: TC001

from . import protocol_factory as _protocol_factory
from . import protocol_lifecycle as _protocol_lifecycle
from . import protocol_publish as _protocol_publish
from .protocol_sessions import ClientConnectResult, ClientSession
from .protocol_sessions import connect_client_relays as _connect_client_relays
from .protocol_sessions import create_connected_client as _create_connected_client
from .protocol_validation import (
    RelayValidationContext,
    RelayValidationOptions,
)
from .protocol_validation import (
    validate_relay_protocol as _validate_relay_protocol,
)
from .transport import (
    DEFAULT_TIMEOUT,
    install_nostr_sdk_stderr_filter,
    suppress_nostr_sdk_stderr,
)


if TYPE_CHECKING:
    from nostr_sdk import Keys

    from bigbrotr.services.common.configs import NetworksConfig


logger = logging.getLogger(__name__)


BroadcastClientResult = _protocol_publish.BroadcastClientResult
broadcast_events = _protocol_publish.broadcast_events
broadcast_events_detailed = _protocol_publish.broadcast_events_detailed
summarize_broadcast_results = _protocol_publish.summarize_broadcast_results
normalize_send_output = _protocol_publish.normalize_send_output
shutdown_client = _protocol_lifecycle.shutdown_client


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

    async def _connect_relay_with_networks(self, relay: Relay) -> Client:
        """Connect one relay using this manager's shared network policy."""
        if self._networks is None:
            raise RuntimeError("networks configuration required for relay-scoped clients")
        proxy_url = self._networks.get_proxy_url(relay.network)
        timeout = self._networks.get(relay.network).timeout
        return await connect_relay(
            relay,
            keys=self._keys,
            proxy_url=proxy_url,
            timeout=timeout,
            allow_insecure=self._allow_insecure,
        )

    async def get_relay_client(self, relay: Relay) -> Client | None:
        """Return one lazily connected cached client for a single relay."""
        if relay.url in self._relay_clients:
            return self._relay_clients[relay.url]
        if relay.url in self._failed_relays:
            return None

        try:
            client = await self._connect_relay_with_networks(relay)
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
    install_nostr_sdk_stderr_filter()
    return await _protocol_factory.build_client(
        keys=keys,
        proxy_url=proxy_url,
        allow_insecure=allow_insecure,
    )


async def create_connected_client(
    relays: list[Relay],
    *,
    keys: Keys | None = None,
    timeout: float = DEFAULT_TIMEOUT,  # noqa: ASYNC109
    allow_insecure: bool = False,
) -> tuple[Client, ClientConnectResult]:
    """Create a client, register relays, and connect with a normalized result."""
    return await _create_connected_client(
        relays,
        create_client_func=create_client,
        keys=keys,
        timeout=timeout,
        allow_insecure=allow_insecure,
    )


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
    *,
    keys: Keys | None,
    proxy_url: str,
    connect_timeout: float,
) -> Client:
    """Connect one overlay relay through a configured proxy."""
    client = await create_client(keys, proxy_url)
    await client.add_relay(relay_url)
    await client.connect()
    await client.wait_for_connection(timedelta(seconds=connect_timeout))

    relay_obj = await client.relay(relay_url)
    if not relay_obj.is_connected():
        await shutdown_client(client)
        raise TimeoutError(f"Connection timeout: {relay.url}")

    return client


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
        return await _connect_overlay_relay(
            relay,
            relay_url,
            keys=keys,
            proxy_url=proxy_url,
            connect_timeout=timeout,
        )

    # Clearnet: try SSL first, then fall back to insecure if allowed
    logger.debug("ssl_connecting relay=%s", relay.url)

    client = await create_client(keys)
    error_message = await _try_connect_single_relay(
        client,
        relay_url,
        connect_timeout=timeout,
    )
    if error_message is None:
        logger.debug("ssl_connected relay=%s", relay.url)
        return client

    await shutdown_client(client)
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
    error_message = await _try_connect_single_relay(
        client,
        relay_url,
        connect_timeout=timeout,
    )
    if error_message is not None:
        await shutdown_client(client)
        raise OSError(f"Connection failed (insecure): {relay.url} ({error_message})")

    logger.debug("insecure_connected relay=%s", relay.url)
    return client


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
    return await _validate_relay_protocol(
        relay,
        RelayValidationContext(
            connect_relay=connect_relay,
            shutdown_client=shutdown_client,
            suppress_stderr=suppress_nostr_sdk_stderr,
            logger=logger,
        ),
        RelayValidationOptions(
            connect_timeout=timeout,
            proxy_url=proxy_url,
            overall_timeout=overall_timeout,
            allow_insecure=allow_insecure,
        ),
    )
