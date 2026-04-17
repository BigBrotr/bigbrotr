"""Integration tests for foreign key constraints and cascade behavior."""

from __future__ import annotations

import asyncpg
import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.models import EventObservation, Relay, RelayDocument
from bigbrotr.models.document import Document, DocumentType
from bigbrotr.models.event import Event
from tests.conftest import make_mock_event


pytestmark = pytest.mark.integration


def _event_observation(
    event_id: str, relay_url: str, observed_at: int = 1700000001
) -> EventObservation:
    mock = make_mock_event(event_id=event_id, sig="ee" * 64)
    relay = Relay(relay_url, stored_at=1700000000)
    return EventObservation(event=Event(mock), relay=relay, observed_at=observed_at)


def _relay_document(
    relay_url: str,
    data: dict,
    meta_type: DocumentType = DocumentType.NIP11_INFO,
    associated_at: int = 1700000001,
) -> RelayDocument:
    relay = Relay(relay_url, stored_at=1700000000)
    metadata = Document(type=meta_type, data=data)
    return RelayDocument(relay=relay, document=metadata, associated_at=associated_at)


# =============================================================================
# Relay Cascade Delete → event_observation
# =============================================================================


class TestRelayCascadeToEventObservation:
    async def test_relay_delete_cascades_to_event_observation(self, brotr: Brotr) -> None:
        er = _event_observation("a1" * 32, "wss://fk-cascade1.example.com")
        await brotr.insert_event_observation([er], cascade=True)
        assert await brotr.fetchval("SELECT COUNT(*) FROM event_observation") == 1

        await brotr.execute("DELETE FROM relay WHERE url = $1", "wss://fk-cascade1.example.com")
        assert await brotr.fetchval("SELECT COUNT(*) FROM event_observation") == 0

    async def test_relay_delete_does_not_cascade_to_event(self, brotr: Brotr) -> None:
        er = _event_observation("a2" * 32, "wss://fk-cascade2.example.com")
        await brotr.insert_event_observation([er], cascade=True)

        await brotr.execute("DELETE FROM relay WHERE url = $1", "wss://fk-cascade2.example.com")
        assert await brotr.fetchval("SELECT COUNT(*) FROM event") == 1

    async def test_relay_delete_only_removes_own_junctions(self, brotr: Brotr) -> None:
        mock = make_mock_event(event_id="a3" * 32, sig="ee" * 64)
        event = Event(mock)
        relay1 = Relay("wss://fk-own1.example.com", stored_at=1700000000)
        relay2 = Relay("wss://fk-own2.example.com", stored_at=1700000000)
        er1 = EventObservation(event=event, relay=relay1, observed_at=1700000001)
        er2 = EventObservation(event=event, relay=relay2, observed_at=1700000001)
        await brotr.insert_event_observation([er1, er2], cascade=True)

        await brotr.execute("DELETE FROM relay WHERE url = $1", "wss://fk-own1.example.com")

        assert await brotr.fetchval("SELECT COUNT(*) FROM event_observation") == 1
        row = await brotr.fetchrow("SELECT relay_url FROM event_observation")
        assert row["relay_url"] == "wss://fk-own2.example.com"


# =============================================================================
# Relay Cascade Delete → relay_document
# =============================================================================


class TestRelayCascadeToRelayDocument:
    async def test_relay_delete_cascades_to_relay_document(self, brotr: Brotr) -> None:
        rm = _relay_document("wss://fk-rm1.example.com", {"name": "Test"})
        await brotr.insert_relay_document([rm], cascade=True)
        assert await brotr.fetchval("SELECT COUNT(*) FROM relay_document") == 1

        await brotr.execute("DELETE FROM relay WHERE url = $1", "wss://fk-rm1.example.com")
        assert await brotr.fetchval("SELECT COUNT(*) FROM relay_document") == 0

    async def test_relay_delete_does_not_cascade_to_document(self, brotr: Brotr) -> None:
        rm = _relay_document("wss://fk-rm2.example.com", {"name": "Orphan"})
        await brotr.insert_relay_document([rm], cascade=True)

        await brotr.execute("DELETE FROM relay WHERE url = $1", "wss://fk-rm2.example.com")
        assert await brotr.fetchval("SELECT COUNT(*) FROM document") == 1

    async def test_relay_delete_only_removes_own_metadata_junctions(self, brotr: Brotr) -> None:
        relay1 = Relay("wss://fk-rmown1.example.com", stored_at=1700000000)
        relay2 = Relay("wss://fk-rmown2.example.com", stored_at=1700000000)
        metadata = Document(type=DocumentType.NIP11_INFO, data={"shared": True})
        rm1 = RelayDocument(relay=relay1, document=metadata, associated_at=1700000001)
        rm2 = RelayDocument(relay=relay2, document=metadata, associated_at=1700000001)
        await brotr.insert_relay_document([rm1, rm2], cascade=True)

        await brotr.execute("DELETE FROM relay WHERE url = $1", "wss://fk-rmown1.example.com")

        assert await brotr.fetchval("SELECT COUNT(*) FROM relay_document") == 1
        assert await brotr.fetchval("SELECT COUNT(*) FROM document") == 1


# =============================================================================
# Foreign Key Constraint Violations
# =============================================================================


class TestEventObservationForeignKeys:
    async def test_missing_relay_raises(self, brotr: Brotr) -> None:
        mock = make_mock_event(event_id="b1" * 32, sig="ee" * 64)
        event = Event(mock)
        await brotr.insert_event([event])

        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await brotr.execute(
                "INSERT INTO event_observation (event_id, relay_url, observed_at) VALUES ($1, $2, $3)",
                event.to_db_params().id,
                "wss://nonexistent.example.com",
                1700000001,
            )

    async def test_missing_event_raises(self, brotr: Brotr) -> None:
        await brotr.insert_relay([Relay("wss://fk-noev.example.com", stored_at=1700000000)])

        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await brotr.execute(
                "INSERT INTO event_observation (event_id, relay_url, observed_at) VALUES ($1, $2, $3)",
                b"\x99" * 32,
                "wss://fk-noev.example.com",
                1700000001,
            )

    async def test_non_cascade_insert_missing_relay(self, brotr: Brotr) -> None:
        er = _event_observation("b3" * 32, "wss://fk-nc-norel.example.com")
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await brotr.insert_event_observation([er], cascade=False)

    async def test_non_cascade_insert_with_existing_fks(self, brotr: Brotr) -> None:
        er = _event_observation("b4" * 32, "wss://fk-nc-ok.example.com")
        await brotr.insert_event_observation([er], cascade=True)

        mock2 = make_mock_event(event_id="b5" * 32, sig="ee" * 64)
        event2 = Event(mock2)
        await brotr.insert_event([event2])
        er2 = EventObservation(
            event=event2,
            relay=Relay("wss://fk-nc-ok.example.com", stored_at=1700000000),
            observed_at=1700000002,
        )
        inserted = await brotr.insert_event_observation([er2], cascade=False)
        assert inserted == 1


class TestRelayDocumentForeignKeys:
    async def test_missing_relay_raises(self, brotr: Brotr) -> None:
        metadata = Document(type=DocumentType.NIP11_INFO, data={"name": "No relay"})
        await brotr.insert_document([metadata])

        with pytest.raises(asyncpg.ForeignKeyViolationError):
            params = metadata.to_db_params()
            await brotr.execute(
                "INSERT INTO relay_document (relay_url, document_id, role, associated_at) "
                "VALUES ($1, $2, $3, $4)",
                "wss://nonexistent.example.com",
                params.id,
                params.type,
                1700000001,
            )

    async def test_missing_metadata_raises(self, brotr: Brotr) -> None:
        await brotr.insert_relay([Relay("wss://fk-nometa.example.com", stored_at=1700000000)])

        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await brotr.execute(
                "INSERT INTO relay_document (relay_url, document_id, role, associated_at) "
                "VALUES ($1, $2, $3, $4)",
                "wss://fk-nometa.example.com",
                b"\x99" * 32,
                "nip11_info",
                1700000001,
            )

    async def test_non_cascade_insert_with_existing_fks(self, brotr: Brotr) -> None:
        relay = Relay("wss://fk-rm-nc.example.com", stored_at=1700000000)
        metadata = Document(type=DocumentType.NIP11_INFO, data={"name": "Pre-inserted"})
        await brotr.insert_relay([relay])
        await brotr.insert_document([metadata])

        rm = RelayDocument(relay=relay, document=metadata, associated_at=1700000001)
        inserted = await brotr.insert_relay_document([rm], cascade=False)
        assert inserted == 1


# =============================================================================
# Storage Retention After Junction Deletion
# =============================================================================


class TestStorageRetention:
    async def test_relay_delete_keeps_event_storage_row(self, brotr: Brotr) -> None:
        er = _event_observation("c1" * 32, "wss://lifecycle-ev.example.com")
        await brotr.insert_event_observation([er], cascade=True)

        assert await brotr.fetchval("SELECT COUNT(*) FROM relay") == 1
        assert await brotr.fetchval("SELECT COUNT(*) FROM event") == 1
        assert await brotr.fetchval("SELECT COUNT(*) FROM event_observation") == 1

        await brotr.execute("DELETE FROM relay WHERE url = $1", "wss://lifecycle-ev.example.com")

        assert await brotr.fetchval("SELECT COUNT(*) FROM relay") == 0
        assert await brotr.fetchval("SELECT COUNT(*) FROM event_observation") == 0
        assert await brotr.fetchval("SELECT COUNT(*) FROM event") == 1

    async def test_relay_delete_keeps_document_storage_row(self, brotr: Brotr) -> None:
        rm = _relay_document("wss://lifecycle-meta.example.com", {"name": "Lifecycle"})
        await brotr.insert_relay_document([rm], cascade=True)

        assert await brotr.fetchval("SELECT COUNT(*) FROM relay") == 1
        assert await brotr.fetchval("SELECT COUNT(*) FROM document") == 1
        assert await brotr.fetchval("SELECT COUNT(*) FROM relay_document") == 1

        await brotr.execute("DELETE FROM relay WHERE url = $1", "wss://lifecycle-meta.example.com")

        assert await brotr.fetchval("SELECT COUNT(*) FROM relay_document") == 0
        assert await brotr.fetchval("SELECT COUNT(*) FROM document") == 1

    async def test_relay_delete_removes_only_junction_rows(self, brotr: Brotr) -> None:
        er = _event_observation("c3" * 32, "wss://pipeline.example.com")
        rm = _relay_document("wss://pipeline.example.com", {"name": "Pipeline"})

        await brotr.insert_event_observation([er], cascade=True)
        await brotr.insert_relay_document([rm], cascade=True)

        await brotr.execute("DELETE FROM relay WHERE url = $1", "wss://pipeline.example.com")

        assert await brotr.fetchval("SELECT COUNT(*) FROM event") == 1
        assert await brotr.fetchval("SELECT COUNT(*) FROM document") == 1
        assert await brotr.fetchval("SELECT COUNT(*) FROM event_observation") == 0
        assert await brotr.fetchval("SELECT COUNT(*) FROM relay_document") == 0
