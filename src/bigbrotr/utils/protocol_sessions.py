"""Session-oriented nostr client helpers behind the public protocol facade."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from nostr_sdk import RelayUrl

from bigbrotr.models.constants import NetworkType

from .transport import DEFAULT_TIMEOUT


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from nostr_sdk import Client, Keys

    from bigbrotr.models.relay import Relay


@dataclass(frozen=True, slots=True)
class ClientConnectResult:
    """Normalized outcome of attempting to connect one client to multiple relays."""

    connected: tuple[str, ...]
    failed: dict[str, str]


@dataclass(frozen=True, slots=True)
class ClientSession:
    """Named multi-relay client session plus its normalized connect outcome."""

    session_id: str
    client: Client
    relay_urls: tuple[str, ...]
    connect_result: ClientConnectResult


def _validate_session_relays(relays: list[Relay]) -> None:
    """Reject relay sets that need per-network proxy policy.

    Session helpers build one shared client and therefore cannot express the
    per-network proxy configuration required by overlay relays.
    """
    unsupported = sorted(
        {relay.network.display_name for relay in relays if relay.network != NetworkType.CLEARNET}
    )
    if unsupported:
        names = ", ".join(unsupported)
        raise ValueError(
            "multi-relay client sessions support clearnet relays only; "
            f"unsupported overlay networks: {names}"
        )


async def connect_client_relays(
    client: Client,
    relays: list[Relay],
    *,
    timeout: float = DEFAULT_TIMEOUT,  # noqa: ASYNC109
) -> ClientConnectResult:
    """Register relays on one shared client and normalize the connection outcome.

    This helper is intentionally limited to clearnet relays because one shared
    client cannot carry the per-network proxy policy required by overlay relay
    families.
    """
    _validate_session_relays(relays)
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
    create_client_func: Callable[..., Awaitable[Client]],
    keys: Keys | None = None,
    timeout: float = DEFAULT_TIMEOUT,  # noqa: ASYNC109
    allow_insecure: bool = False,
) -> tuple[Client, ClientConnectResult]:
    """Create a shared client, register clearnet relays, and normalize the result."""
    client = await create_client_func(keys=keys, allow_insecure=allow_insecure)
    return client, await connect_client_relays(client, relays, timeout=timeout)
