"""Shared Nostr client manager implementation behind the public protocol facade."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, NamedTuple

from .protocol_sessions import ClientSession
from .transport import DEFAULT_TIMEOUT


if TYPE_CHECKING:
    import logging
    from collections.abc import Awaitable, Callable

    from nostr_sdk import Client, Keys

    from bigbrotr.models.relay import Relay
    from bigbrotr.services.common.configs import NetworksConfig
    from bigbrotr.utils.protocol_sessions import ClientConnectResult


class ProtocolManagerDependencies(NamedTuple):
    """Dependencies required by the shared Nostr client manager."""

    connect_relay: Callable[..., Awaitable[Client]]
    create_client: Callable[..., Awaitable[Client]]
    connect_client_relays: Callable[..., Awaitable[ClientConnectResult]]
    shutdown_client: Callable[[Client], Awaitable[None]]
    logger: logging.Logger


class NostrClientManager:
    """Shared lifecycle manager for nostr-sdk clients."""

    __slots__ = (
        "_allow_insecure",
        "_dependencies",
        "_failed_relays",
        "_keys",
        "_networks",
        "_relay_clients",
        "_sessions",
    )

    def __init__(
        self,
        *,
        dependencies: ProtocolManagerDependencies,
        keys: Keys | None = None,
        networks: NetworksConfig | None = None,
        allow_insecure: bool = False,
    ) -> None:
        self._dependencies = dependencies
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
        return await self._dependencies.connect_relay(
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
            self._dependencies.logger.warning(
                "connect_client_failed relay=%s error=%s",
                relay.url,
                e,
            )
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

        client = await self._dependencies.create_client(
            keys=self._keys,
            allow_insecure=self._allow_insecure,
        )
        result = await self._dependencies.connect_client_relays(
            client,
            relays,
            timeout=timeout,
        )
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
                await self._dependencies.shutdown_client(session.client)

        for client in self._relay_clients.values():
            client_id = id(client)
            if client_id in seen:
                continue
            seen.add(client_id)
            with contextlib.suppress(OSError, RuntimeError, TimeoutError):
                await self._dependencies.shutdown_client(client)

        self._sessions.clear()
        self._relay_clients.clear()
        self._failed_relays.clear()
