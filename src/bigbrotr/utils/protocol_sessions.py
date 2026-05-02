"""Session-oriented nostr client helpers behind the public protocol facade."""

from __future__ import annotations

import contextlib
import math
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, NamedTuple

from nostr_sdk import NostrSdkError, RelayUrl

from bigbrotr.models.constants import NetworkType

from .protocol_outcomes import (
    normalize_failed_relays,
    normalize_output_relay_url,
    normalize_relay_outcomes,
)
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

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "connected",
            tuple(sorted({normalize_output_relay_url(relay_url) for relay_url in self.connected})),
        )

        normalized_failed_relays: dict[str, str] = {}
        for relay_url, error in self.failed.items():
            normalized_relay_url = normalize_output_relay_url(relay_url)
            if not isinstance(error, str):
                raise TypeError(f"failed values must be str, got {type(error).__name__}")
            normalized_failed_relays[normalized_relay_url] = error
        object.__setattr__(
            self,
            "failed",
            normalize_failed_relays(normalized_failed_relays),
        )


@dataclass(frozen=True, slots=True)
class ClientSession:
    """Named multi-relay client session plus its normalized connect outcome."""

    session_id: str
    client: Client
    relay_urls: tuple[str, ...]
    connect_result: ClientConnectResult


class SharedSessionDependencies(NamedTuple):
    """Dependencies required by the shared-session client helper."""

    create_client: Callable[..., Awaitable[Client]]
    shutdown_client: Callable[[Client], Awaitable[None]]


def _normalize_session_timeout(timeout: object) -> float:
    """Return one canonical positive finite session timeout budget."""
    if isinstance(timeout, bool) or not isinstance(timeout, int | float):
        raise ValueError("timeout must be a positive finite number")
    normalized = float(timeout)
    if not math.isfinite(normalized) or normalized <= 0:
        raise ValueError("timeout must be a positive finite number")
    return normalized


def _normalize_allow_insecure(allow_insecure: object) -> bool:
    """Return one canonical insecure-transport toggle for shared sessions."""
    if not isinstance(allow_insecure, bool):
        raise ValueError("allow_insecure must be a bool")
    return allow_insecure


def _deduplicate_relays(relays: list[Relay]) -> list[Relay]:
    """Return relays with duplicate URLs removed, preserving first-seen order."""
    deduplicated: list[Relay] = []
    seen: set[str] = set()
    for relay in relays:
        if relay.url in seen:
            continue
        seen.add(relay.url)
        deduplicated.append(relay)
    return deduplicated


def _validate_session_relays(relays: list[Relay]) -> None:
    """Reject relay sets that need per-network proxy policy.

    Session helpers build one shared client and therefore only support relay
    families that can connect directly without per-network proxy policy:
    clearnet and local. Overlay relays still require per-network proxy
    configuration and cannot share this session contract.
    """
    if not relays:
        raise ValueError("multi-relay client sessions require at least one relay")

    unsupported = sorted(
        {
            relay.network.display_name
            for relay in relays
            if relay.network not in (NetworkType.CLEARNET, NetworkType.LOCAL)
        }
    )
    if unsupported:
        names = ", ".join(unsupported)
        raise ValueError(
            "multi-relay client sessions support direct relays only; "
            f"unsupported overlay networks: {names}"
        )


async def connect_client_relays(
    client: Client,
    relays: list[Relay],
    *,
    timeout: float = DEFAULT_TIMEOUT,  # noqa: ASYNC109
) -> ClientConnectResult:
    """Register relays on one shared client and normalize the connection outcome.

    This helper is intentionally limited to direct relay families
    (clearnet/local) because one shared client cannot carry the per-network
    proxy policy required by overlay relay families. Successful relay URLs are
    deduplicated and sorted so the returned connect result stays stable across
    SDK iteration order. Failed relay maps are also returned in stable lexical
    relay-url order.
    """
    normalized_timeout = _normalize_session_timeout(timeout)
    _validate_session_relays(relays)
    for relay in _deduplicate_relays(relays):
        await client.add_relay(RelayUrl.parse(relay.url))

    output = await client.try_connect(timedelta(seconds=normalized_timeout))
    connected, failed = normalize_relay_outcomes(output)
    return ClientConnectResult(connected=connected, failed=failed)


async def create_connected_client(
    relays: list[Relay],
    *,
    dependencies: SharedSessionDependencies,
    keys: Keys | None = None,
    timeout: float = DEFAULT_TIMEOUT,  # noqa: ASYNC109
    allow_insecure: bool = False,
) -> tuple[Client, ClientConnectResult]:
    """Create a shared client, register direct relays, and normalize the result.

    Overlay relay sets are rejected before client creation because a shared
    multi-relay session cannot express per-network proxy policy and should not
    allocate client resources for an unsupported contract.
    """
    normalized_timeout = _normalize_session_timeout(timeout)
    normalized_allow_insecure = _normalize_allow_insecure(allow_insecure)
    _validate_session_relays(relays)
    client = await dependencies.create_client(keys=keys, allow_insecure=normalized_allow_insecure)
    connect_result_ready = False
    try:
        result = await connect_client_relays(client, relays, timeout=normalized_timeout)
        connect_result_ready = True
        return client, result
    finally:
        if not connect_result_ready:
            with contextlib.suppress(OSError, RuntimeError, TimeoutError, NostrSdkError):
                await dependencies.shutdown_client(client)
