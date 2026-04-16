"""Unit tests for the shared service-state store."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from bigbrotr.models.constants import NetworkType, ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType
from bigbrotr.services.common.state_store import (
    ServiceStateStore,
)
from bigbrotr.services.common.types import (
    ApiCheckpoint,
    CandidateCheckpoint,
    DvmRequestCursor,
    FinderCursor,
)


@pytest.fixture
def query_brotr() -> MagicMock:
    brotr = MagicMock()
    brotr.fetch = AsyncMock(return_value=[])
    brotr.get_service_state = AsyncMock(return_value=[])
    brotr.upsert_service_state = AsyncMock(return_value=0)
    brotr.delete_service_state = AsyncMock(return_value=0)
    brotr.config.batch.max_size = 2
    return brotr


class TestPayloadCodecs:
    def test_checkpoint_from_payload(self) -> None:
        checkpoint = ServiceStateStore.decode_checkpoint(
            "https://api.example.com",
            {"timestamp": 123},
            ApiCheckpoint,
        )

        assert checkpoint == ApiCheckpoint(key="https://api.example.com", timestamp=123)

    def test_cursor_from_payload(self) -> None:
        cursor = ServiceStateStore.decode_cursor(
            "wss://relay.example.com",
            {"timestamp": 456, "id": "ab" * 32},
            FinderCursor,
        )

        assert cursor == FinderCursor(
            key="wss://relay.example.com",
            timestamp=456,
            id="ab" * 32,
        )

    def test_candidate_from_payload(self) -> None:
        candidate = ServiceStateStore.decode_candidate(
            "wss://relay.example.com",
            {"timestamp": 789, "network": "tor", "failures": 3},
        )

        assert candidate == CandidateCheckpoint(
            key="wss://relay.example.com",
            timestamp=789,
            network=NetworkType.TOR,
            failures=3,
        )

    def test_candidate_state_override(self) -> None:
        state = ServiceStateStore.encode_candidate(
            CandidateCheckpoint(
                key="wss://relay.example.com",
                timestamp=10,
                network=NetworkType.CLEARNET,
                failures=1,
            ),
            timestamp=20,
            failures=2,
        )

        assert state.state_value == {"network": "clearnet", "failures": 2, "timestamp": 20}

    def test_hash_state(self) -> None:
        state = ServiceStateStore.encode_hash(
            ServiceName.ASSERTOR,
            "subject",
            "deadbeef",
            timestamp=42,
        )

        assert state == ServiceState(
            service_name=ServiceName.ASSERTOR,
            state_type=ServiceStateType.CHECKPOINT,
            state_key="subject",
            state_value={"hash": "deadbeef", "timestamp": 42},
        )


class TestServiceStateStore:
    async def test_fetch_checkpoints_preserves_order_and_defaults(
        self, query_brotr: MagicMock
    ) -> None:
        query_brotr.fetch = AsyncMock(
            return_value=[
                {"state_key": "https://api2.example.com", "state_value": {"timestamp": 200}},
                {"state_key": "https://api3.example.com", "state_value": {}},
            ]
        )

        result = await ServiceStateStore(query_brotr).fetch_checkpoints(
            ServiceName.FINDER,
            [
                "https://api1.example.com",
                "https://api2.example.com",
                "https://api3.example.com",
            ],
            ApiCheckpoint,
        )

        assert result == [
            ApiCheckpoint(key="https://api1.example.com", timestamp=0),
            ApiCheckpoint(key="https://api2.example.com", timestamp=200),
            ApiCheckpoint(key="https://api3.example.com", timestamp=0),
        ]

    async def test_fetch_cursors_preserves_order_and_defaults(self, query_brotr: MagicMock) -> None:
        query_brotr.fetch = AsyncMock(
            return_value=[
                {
                    "state_key": "job_requests",
                    "state_value": {"timestamp": 200, "id": "ab" * 32},
                },
                {
                    "state_key": "job_requests_2",
                    "state_value": {},
                },
            ]
        )

        result = await ServiceStateStore(query_brotr).fetch_cursors(
            ServiceName.DVM,
            ["job_requests", "job_requests_2", "job_requests_3"],
            DvmRequestCursor,
        )

        assert result == [
            DvmRequestCursor(key="job_requests", timestamp=200, id="ab" * 32),
            DvmRequestCursor(key="job_requests_2"),
            DvmRequestCursor(key="job_requests_3"),
        ]

    async def test_upsert_cursors_skips_zero_timestamp_when_requested(
        self, query_brotr: MagicMock
    ) -> None:
        cursors = [
            FinderCursor(key="wss://relay1.example.com"),
            FinderCursor(key="wss://relay2.example.com", timestamp=300, id="cd" * 32),
        ]

        await ServiceStateStore(query_brotr).upsert_cursors(
            ServiceName.FINDER,
            cursors,
            skip_zero_timestamp=True,
        )

        records = query_brotr.upsert_service_state.call_args.args[0]
        assert len(records) == 1
        assert records[0].state_key == "wss://relay2.example.com"

    async def test_delete_keys_batches(self, query_brotr: MagicMock) -> None:
        query_brotr.delete_service_state = AsyncMock(side_effect=[2, 1])

        deleted = await ServiceStateStore(query_brotr).delete_keys(
            ServiceName.VALIDATOR,
            ServiceStateType.CHECKPOINT,
            ["a", "b", "c"],
        )

        assert deleted == 3
        assert query_brotr.delete_service_state.await_count == 2

    async def test_delete_states_works_with_minimal_brotr_mock(self) -> None:
        brotr = MagicMock()
        del brotr.config
        brotr.delete_service_state = AsyncMock(return_value=1)

        deleted = await ServiceStateStore(brotr).delete_states(
            [
                ServiceState(
                    service_name=ServiceName.REFRESHER,
                    state_type=ServiceStateType.CHECKPOINT,
                    state_key="target",
                    state_value={"timestamp": 1},
                )
            ]
        )

        assert deleted == 1
        brotr.delete_service_state.assert_awaited_once()

    async def test_delete_states_batches(self, query_brotr: MagicMock) -> None:
        query_brotr.delete_service_state = AsyncMock(side_effect=[2, 1])

        deleted = await ServiceStateStore(query_brotr).delete_states(
            [
                ServiceState(
                    service_name=ServiceName.FINDER,
                    state_type=ServiceStateType.CURSOR,
                    state_key="a",
                    state_value={"timestamp": 1, "id": "0" * 64},
                ),
                ServiceState(
                    service_name=ServiceName.FINDER,
                    state_type=ServiceStateType.CURSOR,
                    state_key="b",
                    state_value={"timestamp": 2, "id": "1" * 64},
                ),
                ServiceState(
                    service_name=ServiceName.FINDER,
                    state_type=ServiceStateType.CURSOR,
                    state_key="c",
                    state_value={"timestamp": 3, "id": "2" * 64},
                ),
            ]
        )

        assert deleted == 3
        assert query_brotr.delete_service_state.await_count == 2

    async def test_fetch_hash_returns_string_only(self, query_brotr: MagicMock) -> None:
        query_brotr.get_service_state = AsyncMock(
            return_value=[
                ServiceState(
                    service_name=ServiceName.ASSERTOR,
                    state_type=ServiceStateType.CHECKPOINT,
                    state_key="subject",
                    state_value={"hash": "deadbeef", "timestamp": 1},
                )
            ]
        )

        assert (
            await ServiceStateStore(query_brotr).fetch_hash(ServiceName.ASSERTOR, "subject")
            == "deadbeef"
        )

    async def test_upsert_hash_delegates_to_batched_upsert(self, query_brotr: MagicMock) -> None:
        await ServiceStateStore(query_brotr).upsert_hash(
            ServiceName.ASSERTOR,
            "subject",
            "deadbeef",
            timestamp=1,
        )

        records = query_brotr.upsert_service_state.call_args.args[0]
        assert len(records) == 1
        assert records[0].state_value == {"hash": "deadbeef", "timestamp": 1}
