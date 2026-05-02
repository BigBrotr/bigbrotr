from unittest.mock import MagicMock

import pytest

from bigbrotr.services.assertor import service as assertor_service
from tests.integration.harness.builders import build_nip11_relay_document, build_relay
from tests.integration.harness.deterministic import (
    DEFAULT_ASSOCIATED_AT,
    DEFAULT_OUTPUT_EVENT_ID,
    DEFAULT_STORED_AT,
)
from tests.integration.harness.doubles import FakeBroadcastRecorder, FakePublishClient
from tests.integration.harness.failures import AsyncOutcomePlan, patched_assertor_publish_boundary


class TestIntegrationHarnessAudit:
    async def test_assertor_publish_boundary_restores_original_symbols_across_repeated_cycles(
        self,
    ) -> None:
        original_connect_session = assertor_service.NostrClientManager.connect_session
        original_broadcast_events = assertor_service.broadcast_events

        for cycle in range(3):
            client = FakePublishClient(relay_urls=(f"wss://publish-{cycle}.example.com",))
            recorder = FakeBroadcastRecorder(
                successful_relays=(f"wss://publish-{cycle}.example.com",),
            )

            with patched_assertor_publish_boundary(client=client, broadcaster=recorder) as boundary:
                assert (
                    assertor_service.NostrClientManager.connect_session is boundary.connect_session
                )
                assert assertor_service.broadcast_events is recorder

                session = await assertor_service.NostrClientManager.connect_session(MagicMock())
                results = await assertor_service.broadcast_events(["builder"], ["client"])

            assert assertor_service.NostrClientManager.connect_session is original_connect_session
            assert assertor_service.broadcast_events is original_broadcast_events
            assert session.connect_result.connected == (f"wss://publish-{cycle}.example.com",)
            assert results[0].successful_relays == (f"wss://publish-{cycle}.example.com",)
            assert len(boundary.connect_session.calls) == 1
            assert recorder.published_builders == ["builder"]

    async def test_async_outcome_plan_exhaustion_is_explicit(self) -> None:
        plan = AsyncOutcomePlan(["once"])

        assert await plan() == "once"
        with pytest.raises(AssertionError, match="async outcome plan exhausted"):
            await plan()

    async def test_harness_defaults_stay_aligned_across_builders_and_doubles(self) -> None:
        relay = build_relay("wss://audit.example.com")
        relay_document = build_nip11_relay_document(
            "wss://audit.example.com",
            {"name": "Audit Relay"},
        )
        recorder = FakeBroadcastRecorder()

        results = await recorder(["builder"], ["client"])

        assert relay.stored_at == DEFAULT_STORED_AT
        assert relay_document.associated_at == DEFAULT_ASSOCIATED_AT
        assert results[0].event_ids == (DEFAULT_OUTPUT_EVENT_ID,)
