"""Integration tests for foreign key constraints and cascade behavior."""

from __future__ import annotations

import asyncpg
import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.models import EventRelay, Relay, RelayMetadata
from bigbrotr.models.event import Event
from bigbrotr.models.metadata import Metadata, MetadataType
from tests.conftest import make_mock_event


pytestmark = pytest.mark.integration


def _event_relay(event_id: str, relay_url: str, seen_at: int = 1700000001) -> EventRelay:
    mock = make_mock_event(event_id=event_id, sig="ee" * 64)
    relay = Relay(relay_url, discovered_at=1700000000)
    return EventRelay(event=Event(mock), relay=relay, seen_at=seen_at)


def _relay_metadata(
    relay_url: str,
    data: dict,
    meta_type: MetadataType = MetadataType.NIP11_INFO,
    generated_at: int = 1700000001,
) -> RelayMetadata:
    relay = Relay(relay_url, discovered_at=1700000000)
    metadata = Metadata(type=meta_type, data=data)
    return RelayMetadata(relay=relay, metadata=metadata, generated_at=generated_at)


# =============================================================================
# Relay Cascade Delete → event_relay
# =============================================================================


class TestRelayCascadeToEventRelay:
    async def test_relay_delete_cascades_to_event_relay(self, brotr: Brotr) -> None:
        er = _event_relay("a1" * 32, "wss://fk-cascade1.example.com")
        await brotr.insert_event_relay([er], cascade=True)
        assert await brotr.fetchval("SELECT COUNT(*) FROM event_relay") == 1

        await brotr.execute("DELETE FROM relay WHERE url = $1", "wss://fk-cascade1.example.com")
        assert await brotr.fetchval("SELECT COUNT(*) FROM event_relay") == 0

    async def test_relay_delete_does_not_cascade_to_event(self, brotr: Brotr) -> None:
        er = _event_relay("a2" * 32, "wss://fk-cascade2.example.com")
        await brotr.insert_event_relay([er], cascade=True)

        await brotr.execute("DELETE FROM relay WHERE url = $1", "wss://fk-cascade2.example.com")
        assert await brotr.fetchval("SELECT COUNT(*) FROM event") == 1

    async def test_relay_delete_only_removes_own_junctions(self, brotr: Brotr) -> None:
        mock = make_mock_event(event_id="a3" * 32, sig="ee" * 64)
        event = Event(mock)
        relay1 = Relay("wss://fk-own1.example.com", discovered_at=1700000000)
        relay2 = Relay("wss://fk-own2.example.com", discovered_at=1700000000)
        er1 = EventRelay(event=event, relay=relay1, seen_at=1700000001)
        er2 = EventRelay(event=event, relay=relay2, seen_at=1700000001)
        await brotr.insert_event_relay([er1, er2], cascade=True)

        await brotr.execute("DELETE FROM relay WHERE url = $1", "wss://fk-own1.example.com")

        assert await brotr.fetchval("SELECT COUNT(*) FROM event_relay") == 1
        row = await brotr.fetchrow("SELECT relay_url FROM event_relay")
        assert row["relay_url"] == "wss://fk-own2.example.com"


# =============================================================================
# Relay Cascade Delete → relay_metadata
# =============================================================================


class TestRelayCascadeToRelayMetadata:
    async def test_relay_delete_cascades_to_relay_metadata(self, brotr: Brotr) -> None:
        rm = _relay_metadata("wss://fk-rm1.example.com", {"name": "Test"})
        await brotr.insert_relay_metadata([rm], cascade=True)
        assert await brotr.fetchval("SELECT COUNT(*) FROM relay_metadata") == 1

        await brotr.execute("DELETE FROM relay WHERE url = $1", "wss://fk-rm1.example.com")
        assert await brotr.fetchval("SELECT COUNT(*) FROM relay_metadata") == 0

    async def test_relay_delete_does_not_cascade_to_metadata(self, brotr: Brotr) -> None:
        rm = _relay_metadata("wss://fk-rm2.example.com", {"name": "Orphan"})
        await brotr.insert_relay_metadata([rm], cascade=True)

        await brotr.execute("DELETE FROM relay WHERE url = $1", "wss://fk-rm2.example.com")
        assert await brotr.fetchval("SELECT COUNT(*) FROM metadata") == 1

    async def test_relay_delete_only_removes_own_metadata_junctions(self, brotr: Brotr) -> None:
        relay1 = Relay("wss://fk-rmown1.example.com", discovered_at=1700000000)
        relay2 = Relay("wss://fk-rmown2.example.com", discovered_at=1700000000)
        metadata = Metadata(type=MetadataType.NIP11_INFO, data={"shared": True})
        rm1 = RelayMetadata(relay=relay1, metadata=metadata, generated_at=1700000001)
        rm2 = RelayMetadata(relay=relay2, metadata=metadata, generated_at=1700000001)
        await brotr.insert_relay_metadata([rm1, rm2], cascade=True)

        await brotr.execute("DELETE FROM relay WHERE url = $1", "wss://fk-rmown1.example.com")

        assert await brotr.fetchval("SELECT COUNT(*) FROM relay_metadata") == 1
        assert await brotr.fetchval("SELECT COUNT(*) FROM metadata") == 1


# =============================================================================
# Foreign Key Constraint Violations
# =============================================================================


class TestEventRelayForeignKeys:
    async def test_missing_relay_raises(self, brotr: Brotr) -> None:
        mock = make_mock_event(event_id="b1" * 32, sig="ee" * 64)
        event = Event(mock)
        await brotr.insert_event([event])

        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await brotr.execute(
                "INSERT INTO event_relay (event_id, relay_url, seen_at) VALUES ($1, $2, $3)",
                event.to_db_params().id,
                "wss://nonexistent.example.com",
                1700000001,
            )

    async def test_missing_event_raises(self, brotr: Brotr) -> None:
        await brotr.insert_relay([Relay("wss://fk-noev.example.com", discovered_at=1700000000)])

        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await brotr.execute(
                "INSERT INTO event_relay (event_id, relay_url, seen_at) VALUES ($1, $2, $3)",
                b"\x99" * 32,
                "wss://fk-noev.example.com",
                1700000001,
            )

    async def test_non_cascade_insert_missing_relay(self, brotr: Brotr) -> None:
        er = _event_relay("b3" * 32, "wss://fk-nc-norel.example.com")
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await brotr.insert_event_relay([er], cascade=False)

    async def test_non_cascade_insert_with_existing_fks(self, brotr: Brotr) -> None:
        er = _event_relay("b4" * 32, "wss://fk-nc-ok.example.com")
        await brotr.insert_event_relay([er], cascade=True)

        mock2 = make_mock_event(event_id="b5" * 32, sig="ee" * 64)
        event2 = Event(mock2)
        await brotr.insert_event([event2])
        er2 = EventRelay(
            event=event2,
            relay=Relay("wss://fk-nc-ok.example.com", discovered_at=1700000000),
            seen_at=1700000002,
        )
        inserted = await brotr.insert_event_relay([er2], cascade=False)
        assert inserted == 1


class TestRelayMetadataForeignKeys:
    async def test_missing_relay_raises(self, brotr: Brotr) -> None:
        metadata = Metadata(type=MetadataType.NIP11_INFO, data={"name": "No relay"})
        await brotr.insert_metadata([metadata])

        with pytest.raises(asyncpg.ForeignKeyViolationError):
            params = metadata.to_db_params()
            await brotr.execute(
                "INSERT INTO relay_metadata (relay_url, metadata_id, metadata_type, generated_at) "
                "VALUES ($1, $2, $3, $4)",
                "wss://nonexistent.example.com",
                params.id,
                params.type,
                1700000001,
            )

    async def test_missing_metadata_raises(self, brotr: Brotr) -> None:
        await brotr.insert_relay([Relay("wss://fk-nometa.example.com", discovered_at=1700000000)])

        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await brotr.execute(
                "INSERT INTO relay_metadata (relay_url, metadata_id, metadata_type, generated_at) "
                "VALUES ($1, $2, $3, $4)",
                "wss://fk-nometa.example.com",
                b"\x99" * 32,
                "nip11_info",
                1700000001,
            )

    async def test_non_cascade_insert_with_existing_fks(self, brotr: Brotr) -> None:
        relay = Relay("wss://fk-rm-nc.example.com", discovered_at=1700000000)
        metadata = Metadata(type=MetadataType.NIP11_INFO, data={"name": "Pre-inserted"})
        await brotr.insert_relay([relay])
        await brotr.insert_metadata([metadata])

        rm = RelayMetadata(relay=relay, metadata=metadata, generated_at=1700000001)
        inserted = await brotr.insert_relay_metadata([rm], cascade=False)
        assert inserted == 1


# =============================================================================
# Full Orphan Lifecycle
# =============================================================================


class TestOrphanLifecycle:
    async def test_relay_delete_then_event_orphan_cleanup(self, brotr: Brotr) -> None:
        er = _event_relay("c1" * 32, "wss://lifecycle-ev.example.com")
        await brotr.insert_event_relay([er], cascade=True)

        assert await brotr.fetchval("SELECT COUNT(*) FROM relay") == 1
        assert await brotr.fetchval("SELECT COUNT(*) FROM event") == 1
        assert await brotr.fetchval("SELECT COUNT(*) FROM event_relay") == 1

        await brotr.execute("DELETE FROM relay WHERE url = $1", "wss://lifecycle-ev.example.com")

        assert await brotr.fetchval("SELECT COUNT(*) FROM relay") == 0
        assert await brotr.fetchval("SELECT COUNT(*) FROM event_relay") == 0
        assert await brotr.fetchval("SELECT COUNT(*) FROM event") == 1

        deleted = await brotr.delete_orphan_event()
        assert deleted == 1
        assert await brotr.fetchval("SELECT COUNT(*) FROM event") == 0

    async def test_relay_delete_then_metadata_orphan_cleanup(self, brotr: Brotr) -> None:
        rm = _relay_metadata("wss://lifecycle-meta.example.com", {"name": "Lifecycle"})
        await brotr.insert_relay_metadata([rm], cascade=True)

        assert await brotr.fetchval("SELECT COUNT(*) FROM relay") == 1
        assert await brotr.fetchval("SELECT COUNT(*) FROM metadata") == 1
        assert await brotr.fetchval("SELECT COUNT(*) FROM relay_metadata") == 1

        await brotr.execute("DELETE FROM relay WHERE url = $1", "wss://lifecycle-meta.example.com")

        assert await brotr.fetchval("SELECT COUNT(*) FROM relay_metadata") == 0
        assert await brotr.fetchval("SELECT COUNT(*) FROM metadata") == 1

        deleted = await brotr.delete_orphan_metadata()
        assert deleted == 1
        assert await brotr.fetchval("SELECT COUNT(*) FROM metadata") == 0

    async def test_full_cleanup_pipeline(self, brotr: Brotr) -> None:
        er = _event_relay("c3" * 32, "wss://pipeline.example.com")
        rm = _relay_metadata("wss://pipeline.example.com", {"name": "Pipeline"})

        await brotr.insert_event_relay([er], cascade=True)
        await brotr.insert_relay_metadata([rm], cascade=True)

        await brotr.execute("DELETE FROM relay WHERE url = $1", "wss://pipeline.example.com")

        ev_deleted = await brotr.delete_orphan_event()
        meta_deleted = await brotr.delete_orphan_metadata()
        assert ev_deleted == 1
        assert meta_deleted == 1

        assert await brotr.fetchval("SELECT COUNT(*) FROM event") == 0
        assert await brotr.fetchval("SELECT COUNT(*) FROM metadata") == 0
        assert await brotr.fetchval("SELECT COUNT(*) FROM event_relay") == 0
        assert await brotr.fetchval("SELECT COUNT(*) FROM relay_metadata") == 0
