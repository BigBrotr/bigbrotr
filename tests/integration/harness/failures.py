"""Reusable failure-injection seams for integration tests."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar
from unittest.mock import patch

import asyncpg

from bigbrotr.utils.protocol import ClientSession
from tests.integration.harness.doubles import (
    FakeBroadcastRecorder,
    FakePublishClient,
    build_publish_session,
)


OutcomeT = TypeVar("OutcomeT")


@dataclass(slots=True)
class AsyncCall:
    args: tuple[Any, ...]
    kwargs: dict[str, Any]


@dataclass(slots=True)
class AsyncOutcomePlan(Generic[OutcomeT]):
    """Async callable that replays values or raises injected failures in sequence."""

    steps: list[OutcomeT | BaseException]
    sticky_last: bool = False
    calls: list[AsyncCall] = field(default_factory=list)

    async def __call__(self, *args: Any, **kwargs: Any) -> OutcomeT:
        self.calls.append(AsyncCall(args=args, kwargs=dict(kwargs)))

        if not self.steps:
            msg = "async outcome plan exhausted"
            raise AssertionError(msg)

        outcome = self.steps[0] if self.sticky_last and len(self.steps) == 1 else self.steps.pop(0)

        if isinstance(outcome, BaseException):
            raise outcome

        return outcome


def timeout_failure(message: str = "integration timeout") -> TimeoutError:
    """Build the canonical timeout failure used by integration seams."""
    return TimeoutError(message)


def cancellation_failure(message: str = "integration cancellation") -> asyncio.CancelledError:
    """Build the canonical cancellation failure used by integration seams."""
    return asyncio.CancelledError(message)


def database_failure(
    message: str = "integration database failure",
) -> asyncpg.PostgresConnectionError:
    """Build the canonical transient database failure used by integration seams."""
    return asyncpg.PostgresConnectionError(message)


@dataclass(slots=True)
class AssertorPublishBoundary:
    client: FakePublishClient
    connect_session: AsyncOutcomePlan[ClientSession]
    broadcaster: Any


@contextmanager
def patched_assertor_publish_boundary(
    *,
    client: FakePublishClient | None = None,
    connect_session: AsyncOutcomePlan[ClientSession] | None = None,
    broadcaster: Any | None = None,
) -> Any:
    """Patch the Assertor publish boundary with explicit, reusable seams."""
    publish_client = client or FakePublishClient()
    connect_plan = connect_session or AsyncOutcomePlan(
        [
            build_publish_session(
                publish_client,
                relay_urls=publish_client.relay_urls,
                failed_relays=publish_client.failed_relays,
            )
        ],
        sticky_last=True,
    )
    broadcast_callable = broadcaster or FakeBroadcastRecorder()
    boundary = AssertorPublishBoundary(
        client=publish_client,
        connect_session=connect_plan,
        broadcaster=broadcast_callable,
    )

    with (
        patch(
            "bigbrotr.services.assertor.service.NostrClientManager.connect_session",
            new=connect_plan,
        ),
        patch(
            "bigbrotr.services.assertor.service.broadcast_events",
            new=broadcast_callable,
        ),
    ):
        yield boundary
