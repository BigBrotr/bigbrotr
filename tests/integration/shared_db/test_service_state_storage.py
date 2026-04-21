"""Shared-database service-state storage contract tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.core.brotr_config import BrotrConfig
from bigbrotr.core.pool import Pool
from bigbrotr.models.constants import ServiceName
from bigbrotr.models.service_state import ServiceStateType
from tests.integration.harness.brotr import build_pool_config
from tests.integration.harness.builders import build_service_state


if TYPE_CHECKING:
    from tests.integration.harness.brotr import PgDsn


pytestmark = pytest.mark.integration


async def _get_state_from_fresh_brotr(
    pg_dsn: PgDsn,
    owner: ServiceName,
    state_type: ServiceStateType,
    *,
    key: str | None = None,
) -> list[object]:
    brotr = Brotr(pool=Pool(config=build_pool_config(pg_dsn)), config=BrotrConfig())

    async with brotr:
        return await brotr.get_service_state(owner, state_type, key=key)


class TestServiceStateUpsertAndGet:
    async def test_upsert_get_returns_rows_ordered_by_state_key(self, brotr: Brotr) -> None:
        states = [
            build_service_state(
                owner=ServiceName.SYNCHRONIZER,
                state_type=ServiceStateType.CURSOR,
                state_key=state_key,
                state_value={"key": state_key},
            )
            for state_key in (
                "wss://relay-c.example.com",
                "wss://relay-a.example.com",
                "wss://relay-b.example.com",
            )
        ]

        inserted = await brotr.upsert_service_state(states)
        rows = await brotr.get_service_state(ServiceName.SYNCHRONIZER, ServiceStateType.CURSOR)

        assert inserted == 3
        assert [row.state_key for row in rows] == [
            "wss://relay-a.example.com",
            "wss://relay-b.example.com",
            "wss://relay-c.example.com",
        ]

    async def test_upsert_updates_existing_row_without_duplicate(self, brotr: Brotr) -> None:
        original = build_service_state(
            owner=ServiceName.FINDER,
            state_type=ServiceStateType.CURSOR,
            state_key="wss://relay.example.com",
            state_value={"timestamp": 1_700_000_000},
        )
        updated = build_service_state(
            owner=ServiceName.FINDER,
            state_type=ServiceStateType.CURSOR,
            state_key="wss://relay.example.com",
            state_value={"timestamp": 1_700_001_000},
        )

        first_count = await brotr.upsert_service_state([original])
        second_count = await brotr.upsert_service_state([updated])
        rows = await brotr.get_service_state(ServiceName.FINDER, ServiceStateType.CURSOR)

        assert first_count == 1
        assert second_count == 1
        assert len(rows) == 1
        assert rows[0].state_value == {"timestamp": 1_700_001_000}

    async def test_same_key_is_isolated_by_owner_and_state_type(self, brotr: Brotr) -> None:
        finder_cursor = build_service_state(
            owner=ServiceName.FINDER,
            state_type=ServiceStateType.CURSOR,
            state_key="shared-key",
            state_value={"scope": "finder-cursor"},
        )
        finder_checkpoint = build_service_state(
            owner=ServiceName.FINDER,
            state_type=ServiceStateType.CHECKPOINT,
            state_key="shared-key",
            state_value={"scope": "finder-checkpoint"},
        )
        synchronizer_cursor = build_service_state(
            owner=ServiceName.SYNCHRONIZER,
            state_type=ServiceStateType.CURSOR,
            state_key="shared-key",
            state_value={"scope": "synchronizer-cursor"},
        )

        inserted = await brotr.upsert_service_state(
            [finder_cursor, finder_checkpoint, synchronizer_cursor]
        )

        assert inserted == 3
        assert (
            await brotr.get_service_state(
                ServiceName.FINDER,
                ServiceStateType.CURSOR,
                key="shared-key",
            )
        )[0].state_value == {"scope": "finder-cursor"}
        assert (
            await brotr.get_service_state(
                ServiceName.FINDER,
                ServiceStateType.CHECKPOINT,
                key="shared-key",
            )
        )[0].state_value == {"scope": "finder-checkpoint"}
        assert (
            await brotr.get_service_state(
                ServiceName.SYNCHRONIZER,
                ServiceStateType.CURSOR,
                key="shared-key",
            )
        )[0].state_value == {"scope": "synchronizer-cursor"}

    async def test_nested_json_round_trips_without_loss(self, brotr: Brotr) -> None:
        state = build_service_state(
            owner=ServiceName.SYNCHRONIZER,
            state_type=ServiceStateType.CURSOR,
            state_key="window-state",
            state_value={
                "cursor": {"timestamp": 1_700_000_000, "event_id": "abc123"},
                "relays": ["wss://a.com", "wss://b.com"],
                "stats": {"processed": 100, "failed": 3},
            },
        )

        await brotr.upsert_service_state([state])
        rows = await brotr.get_service_state(
            ServiceName.SYNCHRONIZER,
            ServiceStateType.CURSOR,
            key="window-state",
        )

        state_value = rows[0].state_value

        assert state_value["cursor"]["timestamp"] == 1_700_000_000
        assert state_value["cursor"]["event_id"] == "abc123"
        assert list(state_value["relays"]) == ["wss://a.com", "wss://b.com"]
        assert state_value["stats"]["processed"] == 100
        assert state_value["stats"]["failed"] == 3


class TestServiceStateDeleteAndPersistence:
    async def test_delete_removes_only_requested_keys(self, brotr: Brotr) -> None:
        states = [
            build_service_state(
                owner=ServiceName.FINDER,
                state_type=ServiceStateType.CURSOR,
                state_key=state_key,
                state_value={"state_key": state_key},
            )
            for state_key in (
                "wss://keep-a.example.com",
                "wss://delete-me.example.com",
                "wss://keep-b.example.com",
            )
        ]

        await brotr.upsert_service_state(states)
        deleted = await brotr.delete_service_state(
            [ServiceName.FINDER],
            [ServiceStateType.CURSOR],
            ["wss://delete-me.example.com"],
        )
        remaining = await brotr.get_service_state(ServiceName.FINDER, ServiceStateType.CURSOR)

        assert deleted == 1
        assert [row.state_key for row in remaining] == [
            "wss://keep-a.example.com",
            "wss://keep-b.example.com",
        ]

    async def test_state_persists_across_new_brotr_handle(
        self, brotr: Brotr, pg_dsn: PgDsn
    ) -> None:
        state = build_service_state(
            owner=ServiceName.MONITOR,
            state_type=ServiceStateType.CHECKPOINT,
            state_key="last-run",
            state_value={"ts": 1_700_000_000, "count": 42},
        )

        await brotr.upsert_service_state([state])
        rows = await _get_state_from_fresh_brotr(
            pg_dsn,
            ServiceName.MONITOR,
            ServiceStateType.CHECKPOINT,
            key="last-run",
        )

        assert len(rows) == 1
        assert rows[0].state_value == {"ts": 1_700_000_000, "count": 42}
