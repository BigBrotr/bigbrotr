"""Integration tests for service state operations."""

from __future__ import annotations

import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.models.constants import ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType


pytestmark = pytest.mark.integration


class TestServiceStateUpsert:
    async def test_single_upsert(self, brotr: Brotr):
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
        assert rows[0].state_key == "wss://relay.example.com"
        assert rows[0].state_value["timestamp"] == 1700000000

    async def test_batch_upsert(self, brotr: Brotr):
        states = [
            ServiceState(
                service_name=ServiceName.FINDER,
                state_type=ServiceStateType.CURSOR,
                state_key=f"wss://relay{i}.example.com",
                state_value={"ts": i},
            )
            for i in range(3)
        ]
        count = await brotr.upsert_service_state(states)
        assert count == 3

        rows = await brotr.get_service_state(ServiceName.FINDER, ServiceStateType.CURSOR)
        assert len(rows) == 3

    async def test_empty_batch(self, brotr: Brotr):
        count = await brotr.upsert_service_state([])
        assert count == 0

        total = await brotr.fetchval("SELECT count(*) FROM service_state")
        assert total == 0

    async def test_update_semantics(self, brotr: Brotr):
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

        total = await brotr.fetchval("SELECT count(*) FROM service_state")
        assert total == 1

    async def test_within_batch_dedup(self, brotr: Brotr):
        first = ServiceState(
            service_name=ServiceName.FINDER,
            state_type=ServiceStateType.CURSOR,
            state_key="wss://relay.example.com",
            state_value={"version": 1},
        )
        second = ServiceState(
            service_name=ServiceName.FINDER,
            state_type=ServiceStateType.CURSOR,
            state_key="wss://relay.example.com",
            state_value={"version": 2},
        )
        count = await brotr.upsert_service_state([first, second])
        assert count == 1

        rows = await brotr.get_service_state(
            ServiceName.FINDER, ServiceStateType.CURSOR, key="wss://relay.example.com"
        )
        assert len(rows) == 1
        assert rows[0].state_value["version"] in {1, 2}

    async def test_upsert_preserves_other_keys(self, brotr: Brotr):
        existing = ServiceState(
            service_name=ServiceName.FINDER,
            state_type=ServiceStateType.CURSOR,
            state_key="wss://existing.example.com",
            state_value={"keep": True},
        )
        await brotr.upsert_service_state([existing])

        new = ServiceState(
            service_name=ServiceName.FINDER,
            state_type=ServiceStateType.CURSOR,
            state_key="wss://new.example.com",
            state_value={"added": True},
        )
        await brotr.upsert_service_state([new])

        rows = await brotr.get_service_state(ServiceName.FINDER, ServiceStateType.CURSOR)
        assert len(rows) == 2
        keys = {r.state_key for r in rows}
        assert keys == {"wss://existing.example.com", "wss://new.example.com"}

    async def test_mixed_insert_and_update_returns_correct_count(self, brotr: Brotr):
        existing = ServiceState(
            service_name=ServiceName.FINDER,
            state_type=ServiceStateType.CURSOR,
            state_key="wss://relay0.example.com",
            state_value={"v": 1},
        )
        await brotr.upsert_service_state([existing])

        batch = [
            ServiceState(
                service_name=ServiceName.FINDER,
                state_type=ServiceStateType.CURSOR,
                state_key="wss://relay0.example.com",
                state_value={"v": 2},
            ),
            ServiceState(
                service_name=ServiceName.FINDER,
                state_type=ServiceStateType.CURSOR,
                state_key="wss://relay1.example.com",
                state_value={"v": 1},
            ),
        ]
        count = await brotr.upsert_service_state(batch)
        assert count == 2

        total = await brotr.fetchval("SELECT count(*) FROM service_state")
        assert total == 2


class TestServiceStateGet:
    async def test_get_all_ordered_by_state_key(self, brotr: Brotr):
        states = [
            ServiceState(
                service_name=ServiceName.SYNCHRONIZER,
                state_type=ServiceStateType.CURSOR,
                state_key=f"wss://relay-{c}.example.com",
                state_value={"idx": i},
            )
            for i, c in enumerate(["c", "a", "b"])
        ]
        await brotr.upsert_service_state(states)

        rows = await brotr.get_service_state(ServiceName.SYNCHRONIZER, ServiceStateType.CURSOR)
        assert len(rows) == 3
        assert rows[0].state_key == "wss://relay-a.example.com"
        assert rows[1].state_key == "wss://relay-b.example.com"
        assert rows[2].state_key == "wss://relay-c.example.com"

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
        assert rows[0].state_value["ts"] == 1

    async def test_get_nonexistent_service(self, brotr: Brotr):
        rows = await brotr.get_service_state(ServiceName.FINDER, ServiceStateType.CURSOR)
        assert rows == []

    async def test_get_nonexistent_key(self, brotr: Brotr):
        state = ServiceState(
            service_name=ServiceName.FINDER,
            state_type=ServiceStateType.CURSOR,
            state_key="wss://exists.example.com",
            state_value={"data": 1},
        )
        await brotr.upsert_service_state([state])

        rows = await brotr.get_service_state(
            ServiceName.FINDER, ServiceStateType.CURSOR, key="wss://ghost.example.com"
        )
        assert rows == []

    async def test_returned_fields_correct(self, brotr: Brotr):
        state = ServiceState(
            service_name=ServiceName.MONITOR,
            state_type=ServiceStateType.CHECKPOINT,
            state_key="last_run",
            state_value={"ts": 1700000000, "count": 42},
        )
        await brotr.upsert_service_state([state])

        rows = await brotr.get_service_state(
            ServiceName.MONITOR, ServiceStateType.CHECKPOINT, key="last_run"
        )
        assert len(rows) == 1
        row = rows[0]
        assert isinstance(row, ServiceState)
        assert row.service_name == ServiceName.MONITOR
        assert row.state_type == ServiceStateType.CHECKPOINT
        assert row.state_key == "last_run"
        assert row.state_value["ts"] == 1700000000
        assert row.state_value["count"] == 42

    async def test_nested_json_roundtrip(self, brotr: Brotr):
        nested = {
            "cursor": {"timestamp": 1700000000, "event_id": "abc123"},
            "relays": ["wss://a.com", "wss://b.com"],
            "stats": {"processed": 100, "failed": 3},
        }
        state = ServiceState(
            service_name=ServiceName.SYNCHRONIZER,
            state_type=ServiceStateType.CURSOR,
            state_key="window-state",
            state_value=nested,
        )
        await brotr.upsert_service_state([state])

        rows = await brotr.get_service_state(
            ServiceName.SYNCHRONIZER, ServiceStateType.CURSOR, key="window-state"
        )
        assert len(rows) == 1
        val = rows[0].state_value
        assert val["cursor"]["timestamp"] == 1700000000
        assert val["cursor"]["event_id"] == "abc123"
        assert list(val["relays"]) == ["wss://a.com", "wss://b.com"]
        assert val["stats"]["processed"] == 100


class TestServiceStateDelete:
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
        assert rows == []

    async def test_delete_batch(self, brotr: Brotr):
        states = [
            ServiceState(
                service_name=ServiceName.FINDER,
                state_type=ServiceStateType.CURSOR,
                state_key=f"wss://del{i}.example.com",
                state_value={"i": i},
            )
            for i in range(3)
        ]
        await brotr.upsert_service_state(states)

        deleted = await brotr.delete_service_state(
            [ServiceName.FINDER] * 3,
            [ServiceStateType.CURSOR] * 3,
            [f"wss://del{i}.example.com" for i in range(3)],
        )
        assert deleted == 3

        total = await brotr.fetchval("SELECT count(*) FROM service_state")
        assert total == 0

    async def test_delete_nonexistent(self, brotr: Brotr):
        deleted = await brotr.delete_service_state(
            [ServiceName.FINDER],
            [ServiceStateType.CURSOR],
            ["wss://ghost.example.com"],
        )
        assert deleted == 0

    async def test_delete_empty_table(self, brotr: Brotr):
        total = await brotr.fetchval("SELECT count(*) FROM service_state")
        assert total == 0

        deleted = await brotr.delete_service_state(
            [ServiceName.FINDER],
            [ServiceStateType.CURSOR],
            ["wss://nothing.example.com"],
        )
        assert deleted == 0

    async def test_delete_partial_match(self, brotr: Brotr):
        states = [
            ServiceState(
                service_name=ServiceName.FINDER,
                state_type=ServiceStateType.CURSOR,
                state_key=f"wss://relay{i}.example.com",
                state_value={"i": i},
            )
            for i in range(3)
        ]
        await brotr.upsert_service_state(states)

        deleted = await brotr.delete_service_state(
            [ServiceName.FINDER, ServiceName.FINDER],
            [ServiceStateType.CURSOR, ServiceStateType.CURSOR],
            ["wss://relay0.example.com", "wss://nonexistent.example.com"],
        )
        assert deleted == 1

        rows = await brotr.get_service_state(ServiceName.FINDER, ServiceStateType.CURSOR)
        assert len(rows) == 2


class TestServiceStateIsolation:
    async def test_different_services_same_key_isolated(self, brotr: Brotr):
        finder = ServiceState(
            service_name=ServiceName.FINDER,
            state_type=ServiceStateType.CURSOR,
            state_key="shared-key",
            state_value={"source": "finder"},
        )
        sync = ServiceState(
            service_name=ServiceName.SYNCHRONIZER,
            state_type=ServiceStateType.CURSOR,
            state_key="shared-key",
            state_value={"source": "synchronizer"},
        )
        await brotr.upsert_service_state([finder, sync])

        finder_rows = await brotr.get_service_state(ServiceName.FINDER, ServiceStateType.CURSOR)
        sync_rows = await brotr.get_service_state(ServiceName.SYNCHRONIZER, ServiceStateType.CURSOR)
        assert len(finder_rows) == 1
        assert finder_rows[0].state_value["source"] == "finder"
        assert len(sync_rows) == 1
        assert sync_rows[0].state_value["source"] == "synchronizer"

    async def test_different_state_types_same_key_isolated(self, brotr: Brotr):
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
        cp_rows = await brotr.get_service_state(ServiceName.FINDER, ServiceStateType.CHECKPOINT)
        assert len(cursor_rows) == 1
        assert cursor_rows[0].state_value["type"] == "cursor"
        assert len(cp_rows) == 1
        assert cp_rows[0].state_value["type"] == "checkpoint"

    async def test_all_service_names_storable(self, brotr: Brotr):
        states = [
            ServiceState(
                service_name=sn,
                state_type=ServiceStateType.CHECKPOINT,
                state_key="health",
                state_value={"service": sn.value},
            )
            for sn in ServiceName
        ]
        count = await brotr.upsert_service_state(states)
        assert count == len(ServiceName)

        total = await brotr.fetchval("SELECT count(*) FROM service_state")
        assert total == len(ServiceName)

    async def test_both_state_types_storable(self, brotr: Brotr):
        states = [
            ServiceState(
                service_name=ServiceName.MONITOR,
                state_type=st,
                state_key="key",
                state_value={"st": st.value},
            )
            for st in ServiceStateType
        ]
        count = await brotr.upsert_service_state(states)
        assert count == len(ServiceStateType)

    async def test_service_cannot_see_other_service_state(self, brotr: Brotr):
        state = ServiceState(
            service_name=ServiceName.FINDER,
            state_type=ServiceStateType.CURSOR,
            state_key="private-key",
            state_value={"secret": 42},
        )
        await brotr.upsert_service_state([state])

        for sn in ServiceName:
            if sn == ServiceName.FINDER:
                continue
            rows = await brotr.get_service_state(sn, ServiceStateType.CURSOR)
            assert rows == [], f"{sn.value} should not see FINDER's state"


class TestServiceStateJsonRoundTrip:
    async def test_nested_dict(self, brotr: Brotr):
        value = {"cursor": {"timestamp": 1700000000, "event_id": "abc"}}
        state = ServiceState(
            service_name=ServiceName.FINDER,
            state_type=ServiceStateType.CURSOR,
            state_key="nested",
            state_value=value,
        )
        await brotr.upsert_service_state([state])

        rows = await brotr.get_service_state(
            ServiceName.FINDER, ServiceStateType.CURSOR, key="nested"
        )
        assert rows[0].state_value["cursor"]["timestamp"] == 1700000000
        assert rows[0].state_value["cursor"]["event_id"] == "abc"

    async def test_empty_dict(self, brotr: Brotr):
        state = ServiceState(
            service_name=ServiceName.FINDER,
            state_type=ServiceStateType.CURSOR,
            state_key="empty",
            state_value={},
        )
        await brotr.upsert_service_state([state])

        rows = await brotr.get_service_state(
            ServiceName.FINDER, ServiceStateType.CURSOR, key="empty"
        )
        assert len(rows) == 1
        assert dict(rows[0].state_value) == {}

    async def test_list_values(self, brotr: Brotr):
        value = {"relays": ["wss://a.com", "wss://b.com"]}
        state = ServiceState(
            service_name=ServiceName.FINDER,
            state_type=ServiceStateType.CURSOR,
            state_key="lists",
            state_value=value,
        )
        await brotr.upsert_service_state([state])

        rows = await brotr.get_service_state(
            ServiceName.FINDER, ServiceStateType.CURSOR, key="lists"
        )
        assert list(rows[0].state_value["relays"]) == ["wss://a.com", "wss://b.com"]

    async def test_mixed_scalar_types(self, brotr: Brotr):
        value = {
            "flag": True,
            "count": 42,
            "ratio": 3.14,
            "nested": {"inner_flag": False, "inner_int": 0},
        }
        state = ServiceState(
            service_name=ServiceName.FINDER,
            state_type=ServiceStateType.CURSOR,
            state_key="scalars",
            state_value=value,
        )
        await brotr.upsert_service_state([state])

        rows = await brotr.get_service_state(
            ServiceName.FINDER, ServiceStateType.CURSOR, key="scalars"
        )
        val = rows[0].state_value
        assert val["flag"] is True
        assert val["count"] == 42
        assert val["ratio"] == 3.14
        assert val["nested"]["inner_flag"] is False
        assert val["nested"]["inner_int"] == 0

    async def test_preserves_nulls_and_empty_containers(self, brotr: Brotr):
        value = {
            "nullable": None,
            "empty_dict": {},
            "empty_list": [],
            "nested": {"inner_none": None, "inner_empty": []},
        }
        state = ServiceState(
            service_name=ServiceName.FINDER,
            state_type=ServiceStateType.CURSOR,
            state_key="preserved-json",
            state_value=value,
        )
        await brotr.upsert_service_state([state])

        rows = await brotr.get_service_state(
            ServiceName.FINDER, ServiceStateType.CURSOR, key="preserved-json"
        )
        round_tripped = rows[0].state_value
        assert round_tripped["nullable"] is None
        assert dict(round_tripped["empty_dict"]) == {}
        assert tuple(round_tripped["empty_list"]) == ()
        assert round_tripped["nested"]["inner_none"] is None
        assert tuple(round_tripped["nested"]["inner_empty"]) == ()
