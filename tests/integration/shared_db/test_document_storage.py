"""Shared-database document and relay-document storage contract tests."""

from __future__ import annotations

import asyncpg
import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.models.document import DocumentType
from tests.integration.harness.builders import (
    build_document,
    build_relay,
    build_relay_document,
)
from tests.integration.harness.deterministic import DEFAULT_ASSOCIATED_AT, DEFAULT_STORED_AT


pytestmark = pytest.mark.integration


class TestDocumentInsertSemantics:
    async def test_insert_persists_content_addressed_document(self, brotr: Brotr) -> None:
        document = build_document(
            document_type=DocumentType.NIP11_INFO,
            data={"name": "Test Relay", "supported_nips": [1, 2, 11]},
        )

        inserted = await brotr.insert_document([document])
        row = await brotr.fetchrow(
            "SELECT id, type, data FROM document WHERE id = $1 AND type = $2",
            document.content_hash,
            str(document.type),
        )

        assert inserted == 1
        assert row is not None
        assert row["id"] == document.content_hash
        assert row["type"] == str(document.type)
        assert row["data"] == {"name": "Test Relay", "supported_nips": [1, 2, 11]}

    async def test_content_addressed_dedup_is_scoped_by_document_type(self, brotr: Brotr) -> None:
        first = build_document(document_type=DocumentType.NIP11_INFO, data={"value": 42})
        duplicate = build_document(document_type=DocumentType.NIP11_INFO, data={"value": 42})
        other_type = build_document(document_type=DocumentType.NIP66_RTT, data={"value": 42})

        inserted = await brotr.insert_document([first, duplicate, other_type])
        rows = await brotr.fetch("SELECT id, type FROM document ORDER BY type")

        assert first.content_hash == duplicate.content_hash == other_type.content_hash
        assert inserted == 2
        assert [dict(row) for row in rows] == [
            {"id": first.content_hash, "type": "nip11_info"},
            {"id": other_type.content_hash, "type": "nip66_rtt"},
        ]

    async def test_nested_document_data_round_trips_without_mutation(self, brotr: Brotr) -> None:
        document = build_document(
            document_type=DocumentType.NIP11_INFO,
            data={
                "limitation": {
                    "max_message_length": 65_536,
                    "max_subscriptions": 20,
                }
            },
        )

        await brotr.insert_document([document])
        data = await brotr.fetchval(
            "SELECT data FROM document WHERE id = $1 AND type = $2",
            document.content_hash,
            str(document.type),
        )

        assert data == {
            "limitation": {
                "max_message_length": 65_536,
                "max_subscriptions": 20,
            }
        }


class TestRelayDocumentCascadeSemantics:
    async def test_cascade_insert_creates_relay_document_and_junction_rows(
        self, brotr: Brotr
    ) -> None:
        relay_document = build_relay_document(
            "wss://meta-cascade.example.com",
            {"name": "Cascade Test"},
            associated_at=DEFAULT_ASSOCIATED_AT,
            stored_at=DEFAULT_STORED_AT,
        )

        inserted = await brotr.insert_relay_document([relay_document], cascade=True)
        junction = await brotr.fetchrow(
            "SELECT relay_url, document_id, role, associated_at FROM relay_document"
        )

        assert inserted == 1
        assert await brotr.fetchval("SELECT COUNT(*) FROM relay") == 1
        assert await brotr.fetchval("SELECT COUNT(*) FROM document") == 1
        assert junction is not None
        assert dict(junction) == {
            "relay_url": relay_document.relay.url,
            "document_id": relay_document.document.content_hash,
            "role": str(relay_document.document.type),
            "associated_at": DEFAULT_ASSOCIATED_AT,
        }

    async def test_same_document_reused_across_multiple_relays(self, brotr: Brotr) -> None:
        first = build_relay_document(
            "wss://meta-r1.example.com",
            {"rtt_open": 100},
            document_type=DocumentType.NIP66_RTT,
        )
        second = build_relay_document(
            "wss://meta-r2.example.com",
            {"rtt_open": 100},
            document_type=DocumentType.NIP66_RTT,
        )

        inserted = await brotr.insert_relay_document([first, second], cascade=True)

        assert inserted == 2
        assert await brotr.fetchval("SELECT COUNT(*) FROM relay") == 2
        assert await brotr.fetchval("SELECT COUNT(*) FROM document") == 1
        assert await brotr.fetchval("SELECT COUNT(*) FROM relay_document") == 2

    async def test_same_relay_document_allows_distinct_association_timestamps(
        self, brotr: Brotr
    ) -> None:
        first = build_relay_document(
            "wss://multi-ts.example.com",
            {"name": "Multi TS"},
            associated_at=DEFAULT_ASSOCIATED_AT,
        )
        second = build_relay_document(
            "wss://multi-ts.example.com",
            {"name": "Multi TS"},
            associated_at=DEFAULT_ASSOCIATED_AT + 1,
        )

        first_inserted = await brotr.insert_relay_document([first], cascade=True)
        second_inserted = await brotr.insert_relay_document([second], cascade=True)
        association_times = await brotr.fetch(
            "SELECT associated_at FROM relay_document ORDER BY associated_at"
        )

        assert first_inserted == 1
        assert second_inserted == 1
        assert [row["associated_at"] for row in association_times] == [
            DEFAULT_ASSOCIATED_AT,
            DEFAULT_ASSOCIATED_AT + 1,
        ]

    async def test_exact_duplicate_junction_is_idempotent(self, brotr: Brotr) -> None:
        relay_document = build_relay_document(
            "wss://dup-jnc.example.com",
            {"name": "Dup Junction"},
        )

        first_inserted = await brotr.insert_relay_document([relay_document], cascade=True)
        second_inserted = await brotr.insert_relay_document([relay_document], cascade=True)

        assert first_inserted == 1
        assert second_inserted == 0
        assert await brotr.fetchval("SELECT COUNT(*) FROM relay_document") == 1


class TestRelayDocumentForeignKeySemantics:
    async def test_non_cascade_insert_requires_existing_relay_and_document(
        self, brotr: Brotr
    ) -> None:
        relay = build_relay("wss://meta-fk.example.com")
        document = build_document(
            document_type=DocumentType.NIP11_INFO,
            data={"name": "FK Test"},
        )
        relay_document = build_relay_document(
            relay.url,
            document.data,
            document_type=document.type,
            associated_at=DEFAULT_ASSOCIATED_AT,
            stored_at=relay.stored_at,
        )

        await brotr.insert_relay([relay])
        await brotr.insert_document([document])
        inserted = await brotr.insert_relay_document([relay_document], cascade=False)

        assert inserted == 1
        assert await brotr.fetchval("SELECT COUNT(*) FROM relay_document") == 1

    async def test_non_cascade_insert_rejects_missing_relay(self, brotr: Brotr) -> None:
        document = build_document(
            document_type=DocumentType.NIP11_INFO,
            data={"name": "Missing Relay"},
        )
        relay_document = build_relay_document(
            "wss://no-relay.example.com",
            document.data,
            document_type=document.type,
        )

        await brotr.insert_document([document])

        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await brotr.insert_relay_document([relay_document], cascade=False)

    async def test_non_cascade_insert_rejects_missing_document(self, brotr: Brotr) -> None:
        relay = build_relay("wss://has-relay.example.com")
        relay_document = build_relay_document(
            relay.url,
            {"resolver": "8.8.8.8"},
            document_type=DocumentType.NIP66_DNS,
        )

        await brotr.insert_relay([relay])

        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await brotr.insert_relay_document([relay_document], cascade=False)
