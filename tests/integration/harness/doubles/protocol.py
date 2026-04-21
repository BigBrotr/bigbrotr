"""Named protocol-boundary doubles for integration tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from bigbrotr.utils.protocol import BroadcastClientResult, ClientConnectResult, ClientSession
from tests.integration.harness.deterministic import DEFAULT_OUTPUT_EVENT_ID


DEFAULT_PUBLISH_RELAY_URL = "wss://publish-relay.example.com"


@dataclass(slots=True)
class FakePublishClient:
    """Minimal publish client double for Assertor-facing integration tests."""

    relay_urls: tuple[str, ...] = (DEFAULT_PUBLISH_RELAY_URL,)
    failed_relays: dict[str, str] = field(default_factory=dict)
    add_relay: AsyncMock = field(init=False)
    connect: AsyncMock = field(init=False)
    try_connect: AsyncMock = field(init=False)
    unsubscribe_all: AsyncMock = field(init=False)
    force_remove_all_relays: AsyncMock = field(init=False)
    shutdown: AsyncMock = field(init=False)
    database: MagicMock = field(init=False)

    def __post_init__(self) -> None:
        connect_result = ClientConnectResult(connected=self.relay_urls, failed=self.failed_relays)
        self.add_relay = AsyncMock()
        self.connect = AsyncMock()
        self.try_connect = AsyncMock(return_value=connect_result)
        self.unsubscribe_all = AsyncMock()
        self.force_remove_all_relays = AsyncMock()
        self.shutdown = AsyncMock()
        self.database = MagicMock(return_value=SimpleNamespace(wipe=AsyncMock()))


def build_publish_session(
    client: Any,
    *,
    relay_urls: tuple[str, ...] = (DEFAULT_PUBLISH_RELAY_URL,),
    failed_relays: dict[str, str] | None = None,
    session_id: str = "assertor-publish-relays",
) -> ClientSession:
    """Build the canonical publish session used by integration protocol tests."""
    return ClientSession(
        session_id=session_id,
        client=client,
        relay_urls=relay_urls,
        connect_result=ClientConnectResult(connected=relay_urls, failed=failed_relays or {}),
    )


@dataclass(slots=True)
class BroadcastCall:
    builders: list[Any]
    clients: list[Any]


@dataclass(slots=True)
class FakeBroadcastRecorder:
    """Async recorder for publish-event calls at the protocol boundary."""

    successful_relays: tuple[str, ...] = (DEFAULT_PUBLISH_RELAY_URL,)
    failed_relays: dict[str, str] = field(default_factory=dict)
    event_id: str = DEFAULT_OUTPUT_EVENT_ID
    calls: list[BroadcastCall] = field(default_factory=list)

    async def __call__(
        self, builders: list[Any], clients: list[Any]
    ) -> list[BroadcastClientResult]:
        self.calls.append(BroadcastCall(builders=list(builders), clients=list(clients)))
        return [
            BroadcastClientResult(
                event_ids=(self.event_id,),
                successful_relays=self.successful_relays,
                failed_relays=self.failed_relays,
            )
        ]

    @property
    def published_builders(self) -> list[Any]:
        published: list[Any] = []
        for call in self.calls:
            published.extend(call.builders)
        return published
