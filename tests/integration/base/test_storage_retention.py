"""Integration tests for shared storage retention semantics."""

from __future__ import annotations

import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.models import EventObservation, Relay, RelayDocument
from bigbrotr.models.document import Document, MetadataType
from bigbrotr.models.event import Event
from tests.conftest import make_mock_event


pytestmark = pytest.mark.integration


def _event_observation(event_id: str, relay_url: str) -> EventObservation:
    mock = make_mock_event(event_id=event_id, sig="ee" * 64)
    relay = Relay(relay_url, stored_at=1_700_000_000)
    return EventObservation(event=Event(mock), relay=relay, observed_at=1_700_000_001)


def _relay_document(
    relay_url: str,
    data: dict[str, object],
    doc_type: MetadataType = MetadataType.NIP11_INFO,
    associated_at: int = 1_700_000_001,
) -> RelayDocument:
    relay = Relay(relay_url, stored_at=1_700_000_000)
    document = Document(type=doc_type, data=data)
    return RelayDocument(relay=relay, document=document, associated_at=associated_at)


class TestSharedStorageRetention:
    async def test_deleting_relay_keeps_event_storage_row(self, brotr: Brotr) -> None:
        observation = _event_observation("a1" * 32, "wss://retain-event.example.com")
        await brotr.insert_event_observation([observation], cascade=True)

        await brotr.execute("DELETE FROM relay WHERE url = $1", "wss://retain-event.example.com")

        assert await brotr.fetchval("SELECT COUNT(*) FROM relay") == 0
        assert await brotr.fetchval("SELECT COUNT(*) FROM event_observation") == 0
        assert await brotr.fetchval("SELECT COUNT(*) FROM event") == 1

    async def test_deleting_relay_keeps_document_storage_row(self, brotr: Brotr) -> None:
        relay_document = _relay_document("wss://retain-document.example.com", {"name": "Retain"})
        await brotr.insert_relay_document([relay_document], cascade=True)

        await brotr.execute("DELETE FROM relay WHERE url = $1", "wss://retain-document.example.com")

        assert await brotr.fetchval("SELECT COUNT(*) FROM relay") == 0
        assert await brotr.fetchval("SELECT COUNT(*) FROM relay_document") == 0
        assert await brotr.fetchval("SELECT COUNT(*) FROM document") == 1

    async def test_event_storage_row_remains_after_all_observations_are_removed(
        self, brotr: Brotr
    ) -> None:
        event_id = "b2" * 32
        observations = [
            _event_observation(event_id, "wss://retain-event-r1.example.com"),
            _event_observation(event_id, "wss://retain-event-r2.example.com"),
        ]
        await brotr.insert_event_observation(observations, cascade=True)

        await brotr.execute("DELETE FROM relay WHERE url = $1", "wss://retain-event-r1.example.com")
        await brotr.execute("DELETE FROM relay WHERE url = $1", "wss://retain-event-r2.example.com")

        assert await brotr.fetchval("SELECT COUNT(*) FROM event_observation") == 0
        assert (
            await brotr.fetchval(
                "SELECT COUNT(*) FROM event WHERE id = $1", bytes.fromhex(event_id)
            )
            == 1
        )

    async def test_document_storage_row_remains_after_all_relay_documents_are_removed(
        self, brotr: Brotr
    ) -> None:
        relay_document = _relay_document(
            "wss://retain-document-r1.example.com",
            {"name": "Shared"},
            associated_at=1_700_000_001,
        )
        shared_document = relay_document.document
        await brotr.insert_relay_document(
            [
                relay_document,
                RelayDocument(
                    relay=Relay("wss://retain-document-r2.example.com", stored_at=1_700_000_000),
                    document=shared_document,
                    associated_at=1_700_000_002,
                ),
            ],
            cascade=True,
        )

        await brotr.execute(
            "DELETE FROM relay WHERE url = $1", "wss://retain-document-r1.example.com"
        )
        await brotr.execute(
            "DELETE FROM relay WHERE url = $1", "wss://retain-document-r2.example.com"
        )

        assert await brotr.fetchval("SELECT COUNT(*) FROM relay_document") == 0
        assert (
            await brotr.fetchval(
                "SELECT COUNT(*) FROM document WHERE id = $1 AND type = $2",
                shared_document.content_hash,
                shared_document.type,
            )
            == 1
        )
