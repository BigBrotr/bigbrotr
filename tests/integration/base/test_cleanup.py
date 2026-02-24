"""Integration tests for orphan cleanup stored procedures.

Tests exercise orphan_event_delete and orphan_metadata_delete stored procedures.
"""

from __future__ import annotations

import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.models import EventRelay, Relay, RelayMetadata
from bigbrotr.models.event import Event
from bigbrotr.models.metadata import Metadata, MetadataType
from tests.conftest import make_mock_event


pytestmark = pytest.mark.integration


# ============================================================================
# Orphan Event Delete
# ============================================================================


class TestOrphanEventDelete:
    """Tests for orphan_event_delete stored procedure."""

    async def test_deletes_orphaned(self, brotr: Brotr):
        relay = Relay("wss://orphan-evt.example.com", discovered_at=1700000000)
        mock = make_mock_event(event_id="a1" * 32, sig="ee" * 64)
        er = EventRelay(event=Event(mock), relay=relay, seen_at=1700000001)
        await brotr.insert_event_relay([er], cascade=True)

        # Delete relay → CASCADE removes junction, event becomes orphaned
        await brotr.execute(
            "DELETE FROM relay WHERE url = $1",
            "wss://orphan-evt.example.com",
        )

        # Event still exists but orphaned
        assert await brotr.fetchval("SELECT COUNT(*) FROM event") == 1
        assert await brotr.fetchval("SELECT COUNT(*) FROM event_relay") == 0

        deleted = await brotr.delete_orphan_event()
        assert deleted == 1
        assert await brotr.fetchval("SELECT COUNT(*) FROM event") == 0

    async def test_preserves_non_orphaned(self, brotr: Brotr):
        relay = Relay("wss://keep-evt.example.com", discovered_at=1700000000)
        mock = make_mock_event(event_id="a2" * 32, sig="ee" * 64)
        er = EventRelay(event=Event(mock), relay=relay, seen_at=1700000001)
        await brotr.insert_event_relay([er], cascade=True)

        deleted = await brotr.delete_orphan_event()
        assert deleted == 0
        assert await brotr.fetchval("SELECT COUNT(*) FROM event") == 1

    async def test_no_orphans_returns_zero(self, brotr: Brotr):
        deleted = await brotr.delete_orphan_event()
        assert deleted == 0

    async def test_multiple_orphans(self, brotr: Brotr):
        ers = []
        for i in range(3):
            relay = Relay(
                f"wss://multi-orphan{i}.example.com",
                discovered_at=1700000000,
            )
            mock = make_mock_event(event_id=f"{i + 10:064x}", sig="ee" * 64)
            ers.append(
                EventRelay(
                    event=Event(mock),
                    relay=relay,
                    seen_at=1700000001,
                )
            )

        await brotr.insert_event_relay(ers, cascade=True)

        # Delete all relays
        for i in range(3):
            await brotr.execute(
                "DELETE FROM relay WHERE url = $1",
                f"wss://multi-orphan{i}.example.com",
            )

        deleted = await brotr.delete_orphan_event()
        assert deleted == 3


# ============================================================================
# Orphan Metadata Delete
# ============================================================================


class TestOrphanMetadataDelete:
    """Tests for orphan_metadata_delete stored procedure."""

    async def test_deletes_orphaned(self, brotr: Brotr):
        relay = Relay("wss://orphan-meta.example.com", discovered_at=1700000000)
        metadata = Metadata(
            type=MetadataType.NIP11_INFO,
            data={"name": "Orphan Test"},
        )
        rm = RelayMetadata(relay=relay, metadata=metadata, generated_at=1700000001)
        await brotr.insert_relay_metadata([rm], cascade=True)

        # Delete relay → CASCADE removes junction, metadata orphaned
        await brotr.execute(
            "DELETE FROM relay WHERE url = $1",
            "wss://orphan-meta.example.com",
        )

        assert await brotr.fetchval("SELECT COUNT(*) FROM metadata") == 1

        deleted = await brotr.delete_orphan_metadata()
        assert deleted == 1
        assert await brotr.fetchval("SELECT COUNT(*) FROM metadata") == 0

    async def test_preserves_non_orphaned(self, brotr: Brotr):
        relay = Relay("wss://keep-meta.example.com", discovered_at=1700000000)
        metadata = Metadata(
            type=MetadataType.NIP66_SSL,
            data={"issuer": "Test CA"},
        )
        rm = RelayMetadata(relay=relay, metadata=metadata, generated_at=1700000001)
        await brotr.insert_relay_metadata([rm], cascade=True)

        deleted = await brotr.delete_orphan_metadata()
        assert deleted == 0
        assert await brotr.fetchval("SELECT COUNT(*) FROM metadata") == 1

    async def test_no_orphans_returns_zero(self, brotr: Brotr):
        deleted = await brotr.delete_orphan_metadata()
        assert deleted == 0

    async def test_shared_metadata_preserved(self, brotr: Brotr):
        relay1 = Relay("wss://shared-m1.example.com", discovered_at=1700000000)
        relay2 = Relay("wss://shared-m2.example.com", discovered_at=1700000000)
        metadata = Metadata(
            type=MetadataType.NIP11_INFO,
            data={"name": "Shared Meta"},
        )

        rm1 = RelayMetadata(relay=relay1, metadata=metadata, generated_at=1700000001)
        rm2 = RelayMetadata(relay=relay2, metadata=metadata, generated_at=1700000001)
        await brotr.insert_relay_metadata([rm1, rm2], cascade=True)

        # Delete one relay; metadata still referenced by the other
        await brotr.execute(
            "DELETE FROM relay WHERE url = $1",
            "wss://shared-m1.example.com",
        )

        deleted = await brotr.delete_orphan_metadata()
        assert deleted == 0
        assert await brotr.fetchval("SELECT COUNT(*) FROM metadata") == 1
