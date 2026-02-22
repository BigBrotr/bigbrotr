"""Integration tests for orphan cleanup and metadata retention procedures.

Tests exercise orphan_event_delete, orphan_metadata_delete, and
relay_metadata_delete_expired stored procedures.
"""

from __future__ import annotations

import time

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


# ============================================================================
# Relay Metadata Delete Expired
# ============================================================================


class TestRelayMetadataDeleteExpired:
    """Tests for relay_metadata_delete_expired stored procedure.

    No Brotr wrapper exists, so we call the procedure directly via fetchval.
    """

    async def test_deletes_old_snapshots(self, brotr: Brotr):
        relay = Relay("wss://expired.example.com", discovered_at=1700000000)
        metadata = Metadata(
            type=MetadataType.NIP11_INFO,
            data={"name": "Expired"},
        )
        # generated_at far in the past (year 2001)
        rm = RelayMetadata(relay=relay, metadata=metadata, generated_at=1000000000)
        await brotr.insert_relay_metadata([rm], cascade=True)

        deleted = await brotr.fetchval(
            "SELECT relay_metadata_delete_expired($1, $2)",
            86400,  # 1 day retention
            10000,
        )
        assert deleted == 1

    async def test_preserves_recent(self, brotr: Brotr):
        now = int(time.time())
        relay = Relay("wss://recent.example.com", discovered_at=1700000000)
        metadata = Metadata(type=MetadataType.NIP11_INFO, data={"name": "Recent"})
        rm = RelayMetadata(relay=relay, metadata=metadata, generated_at=now)
        await brotr.insert_relay_metadata([rm], cascade=True)

        deleted = await brotr.fetchval(
            "SELECT relay_metadata_delete_expired($1, $2)",
            86400,
            10000,
        )
        assert deleted == 0

    async def test_mixed_ages(self, brotr: Brotr):
        now = int(time.time())
        relay = Relay("wss://mixed-age.example.com", discovered_at=1700000000)
        metadata = Metadata(
            type=MetadataType.NIP11_INFO,
            data={"name": "Mixed Ages"},
        )

        old_rms = [
            RelayMetadata(
                relay=relay,
                metadata=metadata,
                generated_at=1000000000 + i,
            )
            for i in range(3)
        ]
        recent_rms = [
            RelayMetadata(
                relay=relay,
                metadata=metadata,
                generated_at=now + i,
            )
            for i in range(2)
        ]

        await brotr.insert_relay_metadata(old_rms + recent_rms, cascade=True)

        deleted = await brotr.fetchval(
            "SELECT relay_metadata_delete_expired($1, $2)",
            86400,
            10000,
        )
        assert deleted == 3

        remaining = await brotr.fetchval("SELECT COUNT(*) FROM relay_metadata")
        assert remaining == 2

    async def test_batched_deletion(self, brotr: Brotr):
        relay = Relay("wss://batched.example.com", discovered_at=1700000000)
        metadata = Metadata(
            type=MetadataType.NIP11_INFO,
            data={"name": "Batched Del"},
        )

        old_rms = [
            RelayMetadata(
                relay=relay,
                metadata=metadata,
                generated_at=1000000000 + i,
            )
            for i in range(5)
        ]
        await brotr.insert_relay_metadata(old_rms, cascade=True)

        # batch_size=2 forces 3 loop iterations: 2+2+1
        deleted = await brotr.fetchval(
            "SELECT relay_metadata_delete_expired($1, $2)",
            86400,
            2,
        )
        assert deleted == 5
