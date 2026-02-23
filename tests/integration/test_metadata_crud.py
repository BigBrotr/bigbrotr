"""Integration tests for metadata CRUD, relay-metadata cascade, and dedup.

Tests exercise metadata_insert, relay_metadata_insert,
relay_metadata_insert_cascade, and content-addressed deduplication.
"""

from __future__ import annotations

import asyncpg.exceptions
import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.models import Relay, RelayMetadata
from bigbrotr.models.metadata import Metadata, MetadataType


pytestmark = pytest.mark.integration


# ============================================================================
# Metadata Insert (direct, metadata table only)
# ============================================================================


class TestMetadataInsert:
    """Tests for metadata_insert stored procedure via Brotr.insert_metadata()."""

    async def test_insert_single(self, brotr: Brotr):
        metadata = Metadata(
            type=MetadataType.NIP11_INFO,
            data={"name": "Test Relay", "supported_nips": [1, 2, 11]},
        )
        inserted = await brotr.insert_metadata([metadata])
        assert inserted == 1

        row = await brotr.fetchrow("SELECT id, metadata_type, data FROM metadata")
        assert row is not None
        assert row["id"] == metadata.content_hash
        assert row["metadata_type"] == "nip11_info"
        assert row["data"]["name"] == "Test Relay"
        assert row["data"]["supported_nips"] == [1, 2, 11]

    async def test_insert_multiple_types(self, brotr: Brotr):
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

    async def test_insert_empty_batch(self, brotr: Brotr):
        inserted = await brotr.insert_metadata([])
        assert inserted == 0

    async def test_duplicate_ignored(self, brotr: Brotr):
        metadata = Metadata(type=MetadataType.NIP11_INFO, data={"name": "Dup Test"})
        first = await brotr.insert_metadata([metadata])
        second = await brotr.insert_metadata([metadata])
        assert first == 1
        assert second == 0


# ============================================================================
# Relay-Metadata Insert (cascade)
# ============================================================================


class TestRelayMetadataInsertCascade:
    """Tests for relay_metadata_insert_cascade stored procedure."""

    async def test_cascade_creates_all_rows(self, brotr: Brotr):
        relay = Relay("wss://meta-cascade.example.com", discovered_at=1700000000)
        metadata = Metadata(
            type=MetadataType.NIP11_INFO,
            data={"name": "Cascade Test"},
        )
        rm = RelayMetadata(relay=relay, metadata=metadata, generated_at=1700000001)

        inserted = await brotr.insert_relay_metadata([rm], cascade=True)
        assert inserted == 1

        # Verify relay created
        relay_count = await brotr.fetchval(
            "SELECT COUNT(*) FROM relay WHERE url = $1",
            "wss://meta-cascade.example.com",
        )
        assert relay_count == 1

        # Verify metadata created with correct column names
        meta_row = await brotr.fetchrow("SELECT id, metadata_type, data FROM metadata")
        assert meta_row is not None
        assert meta_row["metadata_type"] == "nip11_info"
        assert meta_row["data"]["name"] == "Cascade Test"

        # Verify junction
        junction = await brotr.fetchrow(
            "SELECT relay_url, metadata_type, generated_at FROM relay_metadata"
        )
        assert junction is not None
        assert junction["relay_url"] == "wss://meta-cascade.example.com"
        assert junction["metadata_type"] == "nip11_info"
        assert junction["generated_at"] == 1700000001

    async def test_same_metadata_different_relays(self, brotr: Brotr):
        relay1 = Relay("wss://meta-r1.example.com", discovered_at=1700000000)
        relay2 = Relay("wss://meta-r2.example.com", discovered_at=1700000000)
        metadata = Metadata(type=MetadataType.NIP66_RTT, data={"rtt_open": 100})

        rm1 = RelayMetadata(relay=relay1, metadata=metadata, generated_at=1700000001)
        rm2 = RelayMetadata(relay=relay2, metadata=metadata, generated_at=1700000001)
        await brotr.insert_relay_metadata([rm1, rm2], cascade=True)

        # 1 metadata row (content-addressed), 2 junction rows
        meta_count = await brotr.fetchval("SELECT COUNT(*) FROM metadata")
        assert meta_count == 1

        junction_count = await brotr.fetchval("SELECT COUNT(*) FROM relay_metadata")
        assert junction_count == 2

    async def test_same_relay_different_timestamps(self, brotr: Brotr):
        relay = Relay("wss://multi-ts.example.com", discovered_at=1700000000)
        metadata = Metadata(type=MetadataType.NIP11_INFO, data={"name": "Multi TS"})

        rm1 = RelayMetadata(relay=relay, metadata=metadata, generated_at=1700000001)
        rm2 = RelayMetadata(relay=relay, metadata=metadata, generated_at=1700000002)

        await brotr.insert_relay_metadata([rm1], cascade=True)
        inserted = await brotr.insert_relay_metadata([rm2], cascade=True)
        assert inserted == 1

        junction_count = await brotr.fetchval("SELECT COUNT(*) FROM relay_metadata")
        assert junction_count == 2

    async def test_duplicate_junction_ignored(self, brotr: Brotr):
        relay = Relay("wss://dup-jnc.example.com", discovered_at=1700000000)
        metadata = Metadata(type=MetadataType.NIP11_INFO, data={"name": "Dup Junction"})
        rm = RelayMetadata(relay=relay, metadata=metadata, generated_at=1700000001)

        first = await brotr.insert_relay_metadata([rm], cascade=True)
        second = await brotr.insert_relay_metadata([rm], cascade=True)
        assert first == 1
        assert second == 0


# ============================================================================
# Relay-Metadata Insert (non-cascade, junction-only)
# ============================================================================


class TestRelayMetadataInsertNonCascade:
    """Tests for relay_metadata_insert (non-cascade, junction-only)."""

    async def test_with_existing_fks(self, brotr: Brotr):
        relay = Relay("wss://meta-fk.example.com", discovered_at=1700000000)
        await brotr.insert_relay([relay])

        metadata = Metadata(type=MetadataType.NIP11_INFO, data={"name": "FK Test"})
        await brotr.insert_metadata([metadata])

        rm = RelayMetadata(relay=relay, metadata=metadata, generated_at=1700000001)
        inserted = await brotr.insert_relay_metadata([rm], cascade=False)
        assert inserted == 1

    async def test_missing_relay_raises(self, brotr: Brotr):
        metadata = Metadata(
            type=MetadataType.NIP11_INFO,
            data={"name": "Missing Relay"},
        )
        await brotr.insert_metadata([metadata])

        missing_relay = Relay("wss://no-relay.example.com", discovered_at=1700000000)
        rm = RelayMetadata(
            relay=missing_relay,
            metadata=metadata,
            generated_at=1700000001,
        )

        with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError):
            await brotr.insert_relay_metadata([rm], cascade=False)


# ============================================================================
# Content-Addressed Deduplication
# ============================================================================


class TestContentAddressedDedup:
    """Tests for metadata content-addressed deduplication semantics."""

    async def test_same_data_same_type_same_hash(self, brotr: Brotr):
        m1 = Metadata(type=MetadataType.NIP11_INFO, data={"name": "Dedup"})
        m2 = Metadata(type=MetadataType.NIP11_INFO, data={"name": "Dedup"})
        assert m1.content_hash == m2.content_hash

        await brotr.insert_metadata([m1])
        await brotr.insert_metadata([m2])

        count = await brotr.fetchval("SELECT COUNT(*) FROM metadata")
        assert count == 1

    async def test_same_data_different_type(self, brotr: Brotr):
        data = {"value": 42}
        m1 = Metadata(type=MetadataType.NIP11_INFO, data=data)
        m2 = Metadata(type=MetadataType.NIP66_RTT, data=data)
        assert m1.content_hash == m2.content_hash

        await brotr.insert_metadata([m1, m2])

        count = await brotr.fetchval("SELECT COUNT(*) FROM metadata")
        assert count == 2

    async def test_different_data_different_hash(self, brotr: Brotr):
        m1 = Metadata(type=MetadataType.NIP11_INFO, data={"name": "Alpha"})
        m2 = Metadata(type=MetadataType.NIP11_INFO, data={"name": "Beta"})
        assert m1.content_hash != m2.content_hash

        await brotr.insert_metadata([m1, m2])

        count = await brotr.fetchval("SELECT COUNT(*) FROM metadata")
        assert count == 2

    async def test_key_order_irrelevant(self, brotr: Brotr):
        m1 = Metadata(type=MetadataType.NIP11_INFO, data={"a": 1, "b": 2})
        m2 = Metadata(type=MetadataType.NIP11_INFO, data={"b": 2, "a": 1})
        assert m1.content_hash == m2.content_hash

        await brotr.insert_metadata([m1])
        inserted = await brotr.insert_metadata([m2])
        assert inserted == 0

        count = await brotr.fetchval("SELECT COUNT(*) FROM metadata")
        assert count == 1
