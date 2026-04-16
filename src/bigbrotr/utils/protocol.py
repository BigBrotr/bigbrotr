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

import logging
from typing import TYPE_CHECKING

from nostr_sdk import (
    Client,
    RelayUrl,
    uniffi_set_event_loop,
)

from bigbrotr.models.relay import Relay  # noqa: TC001

from . import protocol_connections as _protocol_connections
from . import protocol_factory as _protocol_factory
from . import protocol_lifecycle as _protocol_lifecycle
from . import protocol_manager as _protocol_manager
from . import protocol_publish as _protocol_publish
from . import protocol_sessions as _protocol_sessions
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
ClientConnectResult = _protocol_sessions.ClientConnectResult
ClientSession = _protocol_sessions.ClientSession
_connect_client_relays = _protocol_sessions.connect_client_relays
_create_connected_client = _protocol_sessions.create_connected_client


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


class NostrClientManager(_protocol_manager.NostrClientManager):
    """Public manager facade bound to the protocol module's dynamic helpers."""

    def __init__(
        self,
        *,
        keys: Keys | None = None,
        networks: NetworksConfig | None = None,
        allow_insecure: bool = False,
    ) -> None:
        async def _shutdown_client(client: Client) -> None:
            await shutdown_client(client)

        super().__init__(
            dependencies=_protocol_manager.ProtocolManagerDependencies(
                connect_relay=lambda relay, *, keys, proxy_url, timeout, allow_insecure: (
                    connect_relay(
                        relay,
                        keys=keys,
                        proxy_url=proxy_url,
                        timeout=timeout,
                        allow_insecure=allow_insecure,
                    )
                ),
                create_client=lambda *, keys, allow_insecure: create_client(
                    keys=keys,
                    allow_insecure=allow_insecure,
                ),
                connect_client_relays=lambda client, relays, *, timeout: _connect_client_relays(
                    client,
                    relays,
                    timeout=timeout,
                ),
                shutdown_client=_shutdown_client,
                logger=logger,
            ),
            keys=keys,
            networks=networks,
            allow_insecure=allow_insecure,
        )


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
    return await _protocol_connections.connect_relay(
        relay,
        _protocol_connections.RelayConnectContext(
            create_client=create_client,
            shutdown_client=shutdown_client,
            parse_relay_url=RelayUrl.parse,
            set_event_loop=uniffi_set_event_loop,
            is_ssl_error=_is_ssl_error,
            logger=logger,
        ),
        _protocol_connections.RelayConnectOptions(
            keys=keys,
            proxy_url=proxy_url,
            timeout=timeout,
            allow_insecure=allow_insecure,
        ),
    )


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
