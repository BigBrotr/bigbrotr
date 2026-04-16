"""Integration tests for metadata CRUD operations."""

from __future__ import annotations

import asyncpg
import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.models import Relay, RelayMetadata
from bigbrotr.models.metadata import Metadata, MetadataType


pytestmark = pytest.mark.integration


class TestMetadataInsert:
    async def test_single_metadata(self, brotr: Brotr) -> None:
        metadata = Metadata(
            type=MetadataType.NIP11_INFO,
            data={"name": "Test Relay", "supported_nips": [1, 2, 11]},
        )
        inserted = await brotr.insert_metadata([metadata])
        assert inserted == 1

        row = await brotr.fetchrow("SELECT id, type, data FROM metadata")
        assert row is not None
        assert row["id"] == metadata.content_hash
        assert row["type"] == "nip11_info"
        assert row["data"]["name"] == "Test Relay"
        assert row["data"]["supported_nips"] == [1, 2, 11]

    async def test_multiple_types(self, brotr: Brotr) -> None:
        records = [
            Metadata(type=MetadataType.NIP11_INFO, data={"name": "Relay"}),
            Metadata(
                type=MetadataType.NIP66_RTT,
                data={"rtt_open": 100, "rtt_read": 50, "rtt_write": 75},
            ),
            Metadata(
                type=MetadataType.NIP66_SSL,
                data={"issuer": "Let's Encrypt", "valid": True},
            ),
        ]
        inserted = await brotr.insert_metadata(records)
        assert inserted == 3

        count = await brotr.fetchval("SELECT COUNT(*) FROM metadata")
        assert count == 3

    async def test_empty_batch(self, brotr: Brotr) -> None:
        inserted = await brotr.insert_metadata([])
        assert inserted == 0

    async def test_duplicate_ignored(self, brotr: Brotr) -> None:
        metadata = Metadata(type=MetadataType.NIP11_INFO, data={"name": "Dup Test"})
        first = await brotr.insert_metadata([metadata])
        second = await brotr.insert_metadata([metadata])
        assert first == 1
        assert second == 0

        count = await brotr.fetchval("SELECT COUNT(*) FROM metadata")
        assert count == 1

    @pytest.mark.parametrize("metadata_type", list(MetadataType))
    async def test_all_metadata_types(self, brotr: Brotr, metadata_type: MetadataType) -> None:
        metadata = Metadata(type=metadata_type, data={"test_key": metadata_type.value})
        inserted = await brotr.insert_metadata([metadata])
        assert inserted == 1

        row = await brotr.fetchrow(
            "SELECT type FROM metadata WHERE type = $1",
            metadata_type.value,
        )
        assert row is not None
        assert row["type"] == metadata_type.value

    async def test_nested_data_preserved(self, brotr: Brotr) -> None:
        metadata = Metadata(
            type=MetadataType.NIP11_INFO,
            data={"limitation": {"max_message_length": 65536, "max_subscriptions": 20}},
        )
        inserted = await brotr.insert_metadata([metadata])
        assert inserted == 1

        row = await brotr.fetchrow("SELECT data FROM metadata")
        assert row is not None
        assert row["data"]["limitation"]["max_message_length"] == 65536
        assert row["data"]["limitation"]["max_subscriptions"] == 20


class TestRelayMetadataInsertCascade:
    async def test_cascade_creates_all_rows(self, brotr: Brotr) -> None:
        relay = Relay("wss://meta-cascade.example.com", discovered_at=1700000000)
        metadata = Metadata(
            type=MetadataType.NIP11_INFO,
            data={"name": "Cascade Test"},
        )
        rm = RelayMetadata(relay=relay, metadata=metadata, generated_at=1700000001)

        inserted = await brotr.insert_relay_metadata([rm], cascade=True)
        assert inserted == 1

        relay_count = await brotr.fetchval(
            "SELECT COUNT(*) FROM relay WHERE url = $1",
            "wss://meta-cascade.example.com",
        )
        assert relay_count == 1

        meta_row = await brotr.fetchrow("SELECT id, type, data FROM metadata")
        assert meta_row is not None
        assert meta_row["type"] == "nip11_info"
        assert meta_row["data"]["name"] == "Cascade Test"

        junction = await brotr.fetchrow(
            "SELECT relay_url, metadata_id, metadata_type, generated_at FROM relay_metadata"
        )
        assert junction is not None
        assert junction["relay_url"] == "wss://meta-cascade.example.com"
        assert junction["metadata_id"] == metadata.content_hash
        assert junction["metadata_type"] == "nip11_info"
        assert junction["generated_at"] == 1700000001

    async def test_junction_columns(self, brotr: Brotr) -> None:
        relay = Relay("wss://jnc-cols.example.com", discovered_at=1700000000)
        metadata = Metadata(type=MetadataType.NIP66_GEO, data={"country": "JP"})
        rm = RelayMetadata(relay=relay, metadata=metadata, generated_at=1700000050)

        await brotr.insert_relay_metadata([rm], cascade=True)

        row = await brotr.fetchrow(
            "SELECT relay_url, metadata_id, metadata_type, generated_at FROM relay_metadata"
        )
        assert row is not None
        assert row["relay_url"] == "wss://jnc-cols.example.com"
        assert row["metadata_id"] == metadata.content_hash
        assert row["metadata_type"] == "nip66_geo"
        assert row["generated_at"] == 1700000050

    async def test_same_metadata_different_relays(self, brotr: Brotr) -> None:
        relay1 = Relay("wss://meta-r1.example.com", discovered_at=1700000000)
        relay2 = Relay("wss://meta-r2.example.com", discovered_at=1700000000)
        metadata = Metadata(type=MetadataType.NIP66_RTT, data={"rtt_open": 100})

        rm1 = RelayMetadata(relay=relay1, metadata=metadata, generated_at=1700000001)
        rm2 = RelayMetadata(relay=relay2, metadata=metadata, generated_at=1700000001)
        await brotr.insert_relay_metadata([rm1, rm2], cascade=True)

        meta_count = await brotr.fetchval("SELECT COUNT(*) FROM metadata")
        assert meta_count == 1

        relay_count = await brotr.fetchval("SELECT COUNT(*) FROM relay")
        assert relay_count == 2

        junction_count = await brotr.fetchval("SELECT COUNT(*) FROM relay_metadata")
        assert junction_count == 2

    async def test_same_relay_different_timestamps(self, brotr: Brotr) -> None:
        relay = Relay("wss://multi-ts.example.com", discovered_at=1700000000)
        metadata = Metadata(type=MetadataType.NIP11_INFO, data={"name": "Multi TS"})

        rm1 = RelayMetadata(relay=relay, metadata=metadata, generated_at=1700000001)
        rm2 = RelayMetadata(relay=relay, metadata=metadata, generated_at=1700000002)

        await brotr.insert_relay_metadata([rm1], cascade=True)
        inserted = await brotr.insert_relay_metadata([rm2], cascade=True)
        assert inserted == 1

        junction_count = await brotr.fetchval("SELECT COUNT(*) FROM relay_metadata")
        assert junction_count == 2

    async def test_duplicate_junction_ignored(self, brotr: Brotr) -> None:
        relay = Relay("wss://dup-jnc.example.com", discovered_at=1700000000)
        metadata = Metadata(type=MetadataType.NIP11_INFO, data={"name": "Dup Junction"})
        rm = RelayMetadata(relay=relay, metadata=metadata, generated_at=1700000001)

        first = await brotr.insert_relay_metadata([rm], cascade=True)
        second = await brotr.insert_relay_metadata([rm], cascade=True)
        assert first == 1
        assert second == 0

    async def test_batch_of_five(self, brotr: Brotr) -> None:
        records = []
        for i in range(5):
            relay = Relay(f"wss://batch-{i}.example.com", discovered_at=1700000000)
            metadata = Metadata(
                type=MetadataType.NIP11_INFO,
                data={"name": f"Relay {i}", "index": i},
            )
            records.append(
                RelayMetadata(relay=relay, metadata=metadata, generated_at=1700000000 + i)
            )

        inserted = await brotr.insert_relay_metadata(records, cascade=True)
        assert inserted == 5

        relay_count = await brotr.fetchval("SELECT COUNT(*) FROM relay")
        assert relay_count == 5

        meta_count = await brotr.fetchval("SELECT COUNT(*) FROM metadata")
        assert meta_count == 5

        junction_count = await brotr.fetchval("SELECT COUNT(*) FROM relay_metadata")
        assert junction_count == 5


class TestRelayMetadataInsertNonCascade:
    async def test_with_existing_fks(self, brotr: Brotr) -> None:
        relay = Relay("wss://meta-fk.example.com", discovered_at=1700000000)
        await brotr.insert_relay([relay])

        metadata = Metadata(type=MetadataType.NIP11_INFO, data={"name": "FK Test"})
        await brotr.insert_metadata([metadata])

        rm = RelayMetadata(relay=relay, metadata=metadata, generated_at=1700000001)
        inserted = await brotr.insert_relay_metadata([rm], cascade=False)
        assert inserted == 1

        junction = await brotr.fetchrow(
            "SELECT relay_url, metadata_id, metadata_type, generated_at FROM relay_metadata"
        )
        assert junction is not None
        assert junction["relay_url"] == "wss://meta-fk.example.com"
        assert junction["metadata_id"] == metadata.content_hash

    async def test_missing_relay_raises(self, brotr: Brotr) -> None:
        metadata = Metadata(type=MetadataType.NIP11_INFO, data={"name": "Missing Relay"})
        await brotr.insert_metadata([metadata])

        missing_relay = Relay("wss://no-relay.example.com", discovered_at=1700000000)
        rm = RelayMetadata(
            relay=missing_relay,
            metadata=metadata,
            generated_at=1700000001,
        )

        with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError):
            await brotr.insert_relay_metadata([rm], cascade=False)

    async def test_missing_metadata_raises(self, brotr: Brotr) -> None:
        relay = Relay("wss://has-relay.example.com", discovered_at=1700000000)
        await brotr.insert_relay([relay])

        metadata = Metadata(type=MetadataType.NIP66_DNS, data={"resolver": "8.8.8.8"})
        rm = RelayMetadata(relay=relay, metadata=metadata, generated_at=1700000001)

        with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError):
            await brotr.insert_relay_metadata([rm], cascade=False)


class TestContentAddressedDedup:
    async def test_same_data_same_type_deduped(self, brotr: Brotr) -> None:
        m1 = Metadata(type=MetadataType.NIP11_INFO, data={"name": "Dedup"})
        m2 = Metadata(type=MetadataType.NIP11_INFO, data={"name": "Dedup"})
        assert m1.content_hash == m2.content_hash

        await brotr.insert_metadata([m1])
        await brotr.insert_metadata([m2])

        count = await brotr.fetchval("SELECT COUNT(*) FROM metadata")
        assert count == 1

    async def test_same_data_different_type_both_stored(self, brotr: Brotr) -> None:
        data = {"value": 42}
        m1 = Metadata(type=MetadataType.NIP11_INFO, data=data)
        m2 = Metadata(type=MetadataType.NIP66_RTT, data=data)
        assert m1.content_hash == m2.content_hash

        await brotr.insert_metadata([m1, m2])

        count = await brotr.fetchval("SELECT COUNT(*) FROM metadata")
        assert count == 2

        rows = await brotr.fetch("SELECT type FROM metadata ORDER BY type")
        types = {row["type"] for row in rows}
        assert types == {"nip11_info", "nip66_rtt"}

    async def test_different_data_different_hash(self, brotr: Brotr) -> None:
        m1 = Metadata(type=MetadataType.NIP11_INFO, data={"name": "Alpha"})
        m2 = Metadata(type=MetadataType.NIP11_INFO, data={"name": "Beta"})
        assert m1.content_hash != m2.content_hash

        await brotr.insert_metadata([m1, m2])

        count = await brotr.fetchval("SELECT COUNT(*) FROM metadata")
        assert count == 2

    async def test_key_order_irrelevant(self, brotr: Brotr) -> None:
        m1 = Metadata(type=MetadataType.NIP11_INFO, data={"a": 1, "b": 2})
        m2 = Metadata(type=MetadataType.NIP11_INFO, data={"b": 2, "a": 1})
        assert m1.content_hash == m2.content_hash

        await brotr.insert_metadata([m1])
        inserted = await brotr.insert_metadata([m2])
        assert inserted == 0

        count = await brotr.fetchval("SELECT COUNT(*) FROM metadata")
        assert count == 1

    async def test_null_values_preserved(self, brotr: Brotr) -> None:
        m1 = Metadata(
            type=MetadataType.NIP11_INFO,
            data={"name": "test", "desc": None},
        )
        m2 = Metadata(type=MetadataType.NIP11_INFO, data={"name": "test"})
        assert m1.content_hash != m2.content_hash

        await brotr.insert_metadata([m1])
        inserted = await brotr.insert_metadata([m2])
        assert inserted == 1

        rows = await brotr.fetch(
            "SELECT data FROM metadata ORDER BY CASE WHEN data ? 'desc' THEN 0 ELSE 1 END, data->>'name'"
        )
        assert len(rows) == 2
        assert rows[0]["data"]["desc"] is None
        assert rows[0]["data"]["name"] == "test"
        assert rows[1]["data"] == {"name": "test"}

    async def test_empty_data_dict(self, brotr: Brotr) -> None:
        metadata = Metadata(type=MetadataType.NIP66_HTTP, data={})
        inserted = await brotr.insert_metadata([metadata])
        assert inserted == 1

        row = await brotr.fetchrow("SELECT data FROM metadata")
        assert row is not None
        assert row["data"] == {}

    async def test_unicode_data_preserved(self, brotr: Brotr) -> None:
        metadata = Metadata(
            type=MetadataType.NIP11_INFO,
            data={"name": "\u65e5\u672c\u8a9e\u30ea\u30ec\u30fc"},
        )
        inserted = await brotr.insert_metadata([metadata])
        assert inserted == 1

        row = await brotr.fetchrow("SELECT data FROM metadata")
        assert row is not None
        assert row["data"]["name"] == "\u65e5\u672c\u8a9e\u30ea\u30ec\u30fc"


class TestMetadataDataIntegrity:
    async def test_jsonb_operator_queryable(self, brotr: Brotr) -> None:
        metadata = Metadata(
            type=MetadataType.NIP11_INFO,
            data={"name": "Queryable Relay", "version": "1.0"},
        )
        await brotr.insert_metadata([metadata])

        name = await brotr.fetchval("SELECT data->>'name' FROM metadata")
        assert name == "Queryable Relay"

        version = await brotr.fetchval("SELECT data->>'version' FROM metadata")
        assert version == "1.0"

    async def test_content_hash_is_32_bytes(self, brotr: Brotr) -> None:
        metadata = Metadata(type=MetadataType.NIP66_NET, data={"asn": 13335})
        await brotr.insert_metadata([metadata])

        row = await brotr.fetchrow("SELECT id FROM metadata")
        assert row is not None
        assert len(row["id"]) == 32

    async def test_hash_deterministic_across_constructions(self, brotr: Brotr) -> None:
        data = {"contact": "admin@relay.com", "pubkey": "abc123", "supported_nips": [1, 11, 66]}
        m1 = Metadata(type=MetadataType.NIP11_INFO, data=data)
        m2 = Metadata(type=MetadataType.NIP11_INFO, data=data)

        assert m1.content_hash == m2.content_hash

        await brotr.insert_metadata([m1])
        inserted = await brotr.insert_metadata([m2])
        assert inserted == 0

        row = await brotr.fetchrow("SELECT id FROM metadata")
        assert row is not None
        assert row["id"] == m1.content_hash
