import asyncio
from unittest.mock import MagicMock

import asyncpg
import pytest

from bigbrotr.services.assertor import service as assertor_service
from tests.integration.harness.doubles import FakePublishClient, build_broadcast_result
from tests.integration.harness.failures import (
    AsyncOutcomePlan,
    cancellation_failure,
    database_failure,
    patched_assertor_publish_boundary,
    timeout_failure,
)


class TestAsyncOutcomePlan:
    async def test_returns_sequence_and_repeats_sticky_last(self) -> None:
        plan = AsyncOutcomePlan(["first", "second"], sticky_last=True)

        assert await plan("call-1") == "first"
        assert await plan("call-2") == "second"
        assert await plan("call-3") == "second"
        assert [call.args for call in plan.calls] == [
            ("call-1",),
            ("call-2",),
            ("call-3",),
        ]

    async def test_raises_timeout_and_database_failures(self) -> None:
        plan = AsyncOutcomePlan([timeout_failure(), database_failure()])

        with pytest.raises(asyncio.TimeoutError, match="integration timeout"):
            await plan()
        with pytest.raises(asyncpg.PostgresConnectionError, match="integration database failure"):
            await plan()

    async def test_raises_cancellation_failure(self) -> None:
        plan = AsyncOutcomePlan([cancellation_failure()])

        with pytest.raises(asyncio.CancelledError, match="integration cancellation"):
            await plan()


class TestPatchedAssertorPublishBoundary:
    async def test_patches_publish_boundary_with_explicit_connect_and_broadcast_seams(self) -> None:
        client = FakePublishClient()
        broadcaster = AsyncOutcomePlan(
            [
                [
                    build_broadcast_result(
                        failed_relays={"wss://down.example.com": "timeout"},
                    )
                ]
            ]
        )

        with patched_assertor_publish_boundary(client=client, broadcaster=broadcaster) as boundary:
            session = await assertor_service.NostrClientManager.connect_session(MagicMock())
            results = await assertor_service.broadcast_events(["builder"], ["client"])

        assert session.client is client
        assert results[0].failed_relays == {"wss://down.example.com": "timeout"}
        assert len(boundary.connect_session.calls) == 1
        assert broadcaster.calls[0].args == (["builder"], ["client"])
