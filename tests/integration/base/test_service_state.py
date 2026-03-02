"""Integration tests for service state persistence (upsert, get, delete).

Tests exercise service_state_upsert, service_state_get, and
service_state_delete stored procedures via Brotr methods.
"""

from __future__ import annotations

import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.models.constants import ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType


pytestmark = pytest.mark.integration


class TestServiceState:
    """Tests for service state CRUD operations."""

    async def test_upsert_and_get(self, brotr: Brotr):
        state = ServiceState(
            service_name=ServiceName.FINDER,
            state_type=ServiceStateType.CURSOR,
            state_key="wss://relay.example.com",
            state_value={"timestamp": 1700000000},
        )
        count = await brotr.upsert_service_state([state])
        assert count == 1

        rows = await brotr.get_service_state(ServiceName.FINDER, ServiceStateType.CURSOR)
        assert len(rows) == 1
        assert rows[0].service_name == ServiceName.FINDER
        assert rows[0].state_type == ServiceStateType.CURSOR
        assert rows[0].state_key == "wss://relay.example.com"
        assert rows[0].state_value["timestamp"] == 1700000000

    async def test_upsert_empty_batch(self, brotr: Brotr):
        count = await brotr.upsert_service_state([])
        assert count == 0

    async def test_upsert_update_semantics(self, brotr: Brotr):
        original = ServiceState(
            service_name=ServiceName.FINDER,
            state_type=ServiceStateType.CURSOR,
            state_key="wss://relay.example.com",
            state_value={"timestamp": 1700000000},
        )
        await brotr.upsert_service_state([original])

        updated = ServiceState(
            service_name=ServiceName.FINDER,
            state_type=ServiceStateType.CURSOR,
            state_key="wss://relay.example.com",
            state_value={"timestamp": 1700001000},
        )
        await brotr.upsert_service_state([updated])

        rows = await brotr.get_service_state(ServiceName.FINDER, ServiceStateType.CURSOR)
        assert len(rows) == 1
        assert rows[0].state_value["timestamp"] == 1700001000

    async def test_get_all_for_service_type(self, brotr: Brotr):
        states = [
            ServiceState(
                service_name=ServiceName.FINDER,
                state_type=ServiceStateType.CURSOR,
                state_key=f"wss://relay{i}.example.com",
                state_value={"ts": 1700000000 + i},
            )
            for i in range(3)
        ]
        await brotr.upsert_service_state(states)

        rows = await brotr.get_service_state(ServiceName.FINDER, ServiceStateType.CURSOR)
        assert len(rows) == 3
        # Results ordered by state_key ASC
        assert rows[0].state_key == "wss://relay0.example.com"
        assert rows[2].state_key == "wss://relay2.example.com"

    async def test_get_by_specific_key(self, brotr: Brotr):
        states = [
            ServiceState(
                service_name=ServiceName.FINDER,
                state_type=ServiceStateType.CURSOR,
                state_key=f"wss://relay{i}.example.com",
                state_value={"ts": i},
            )
            for i in range(3)
        ]
        await brotr.upsert_service_state(states)

        rows = await brotr.get_service_state(
            ServiceName.FINDER,
            ServiceStateType.CURSOR,
            key="wss://relay1.example.com",
        )
        assert len(rows) == 1
        assert rows[0].state_key == "wss://relay1.example.com"

    async def test_get_nonexistent(self, brotr: Brotr):
        rows = await brotr.get_service_state(ServiceName.FINDER, ServiceStateType.CURSOR)
        assert len(rows) == 0

    async def test_delete_single(self, brotr: Brotr):
        state = ServiceState(
            service_name=ServiceName.FINDER,
            state_type=ServiceStateType.CURSOR,
            state_key="wss://delete-me.example.com",
            state_value={"data": "value"},
        )
        await brotr.upsert_service_state([state])

        deleted = await brotr.delete_service_state(
            [ServiceName.FINDER],
            [ServiceStateType.CURSOR],
            ["wss://delete-me.example.com"],
        )
        assert deleted == 1

        rows = await brotr.get_service_state(ServiceName.FINDER, ServiceStateType.CURSOR)
        assert len(rows) == 0

    async def test_delete_nonexistent(self, brotr: Brotr):
        deleted = await brotr.delete_service_state(
            [ServiceName.FINDER],
            [ServiceStateType.CURSOR],
            ["wss://ghost.example.com"],
        )
        assert deleted == 0

    async def test_delete_batch(self, brotr: Brotr):
        states = [
            ServiceState(
                service_name=ServiceName.FINDER,
                state_type=ServiceStateType.CURSOR,
                state_key=f"wss://batch-del{i}.example.com",
                state_value={"i": i},
            )
            for i in range(3)
        ]
        await brotr.upsert_service_state(states)

        deleted = await brotr.delete_service_state(
            [ServiceName.FINDER] * 3,
            [ServiceStateType.CURSOR] * 3,
            [f"wss://batch-del{i}.example.com" for i in range(3)],
        )
        assert deleted == 3

    async def test_multiple_services_isolated(self, brotr: Brotr):
        finder_state = ServiceState(
            service_name=ServiceName.FINDER,
            state_type=ServiceStateType.CURSOR,
            state_key="shared-key",
            state_value={"source": "finder"},
        )
        sync_state = ServiceState(
            service_name=ServiceName.SYNCHRONIZER,
            state_type=ServiceStateType.CURSOR,
            state_key="shared-key",
            state_value={"source": "synchronizer"},
        )
        await brotr.upsert_service_state([finder_state, sync_state])

        finder_rows = await brotr.get_service_state(ServiceName.FINDER, ServiceStateType.CURSOR)
        sync_rows = await brotr.get_service_state(ServiceName.SYNCHRONIZER, ServiceStateType.CURSOR)
        assert len(finder_rows) == 1
        assert finder_rows[0].state_value["source"] == "finder"
        assert len(sync_rows) == 1
        assert sync_rows[0].state_value["source"] == "synchronizer"

    async def test_multiple_state_types_isolated(self, brotr: Brotr):
        cursor = ServiceState(
            service_name=ServiceName.FINDER,
            state_type=ServiceStateType.CURSOR,
            state_key="key1",
            state_value={"type": "cursor"},
        )
        checkpoint = ServiceState(
            service_name=ServiceName.FINDER,
            state_type=ServiceStateType.CHECKPOINT,
            state_key="key1",
            state_value={"type": "checkpoint"},
        )
        await brotr.upsert_service_state([cursor, checkpoint])

        cursor_rows = await brotr.get_service_state(ServiceName.FINDER, ServiceStateType.CURSOR)
        checkpoint_rows = await brotr.get_service_state(
            ServiceName.FINDER, ServiceStateType.CHECKPOINT
        )
        assert len(cursor_rows) == 1
        assert cursor_rows[0].state_value["type"] == "cursor"
        assert len(checkpoint_rows) == 1
        assert checkpoint_rows[0].state_value["type"] == "checkpoint"
