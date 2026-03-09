"""Integration tests for orphan cleanup stored procedures."""

from __future__ import annotations

import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.models import EventRelay, Relay, RelayMetadata
from bigbrotr.models.event import Event
from bigbrotr.models.metadata import Metadata, MetadataType
from tests.conftest import make_mock_event


pytestmark = pytest.mark.integration


def _event_relay(event_id: str, relay_url: str) -> EventRelay:
    mock = make_mock_event(event_id=event_id, sig="ee" * 64)
    relay = Relay(relay_url, discovered_at=1700000000)
    return EventRelay(event=Event(mock), relay=relay, seen_at=1700000001)


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
# Orphan Event Delete
# =============================================================================


class TestOrphanEventDelete:
    async def test_empty_db_returns_zero(self, brotr: Brotr) -> None:
        assert await brotr.delete_orphan_event() == 0

    async def test_deletes_orphaned_after_relay_delete(self, brotr: Brotr) -> None:
        er = _event_relay("a1" * 32, "wss://orphan-ev1.example.com")
        await brotr.insert_event_relay([er], cascade=True)

        await brotr.execute("DELETE FROM relay WHERE url = $1", "wss://orphan-ev1.example.com")
        assert await brotr.fetchval("SELECT COUNT(*) FROM event") == 1
        assert await brotr.fetchval("SELECT COUNT(*) FROM event_relay") == 0

        deleted = await brotr.delete_orphan_event()
        assert deleted == 1
        assert await brotr.fetchval("SELECT COUNT(*) FROM event") == 0

    async def test_preserves_non_orphaned(self, brotr: Brotr) -> None:
        er = _event_relay("a2" * 32, "wss://keep-ev.example.com")
        await brotr.insert_event_relay([er], cascade=True)

        assert await brotr.delete_orphan_event() == 0
        assert await brotr.fetchval("SELECT COUNT(*) FROM event") == 1

    async def test_multiple_orphans(self, brotr: Brotr) -> None:
        ers = [
            _event_relay(f"{i + 10:064x}", f"wss://multi-orph-ev{i}.example.com") for i in range(5)
        ]
        await brotr.insert_event_relay(ers, cascade=True)

        for i in range(5):
            await brotr.execute(
                "DELETE FROM relay WHERE url = $1",
                f"wss://multi-orph-ev{i}.example.com",
            )

        deleted = await brotr.delete_orphan_event()
        assert deleted == 5
        assert await brotr.fetchval("SELECT COUNT(*) FROM event") == 0

    async def test_mixed_orphaned_and_non_orphaned(self, brotr: Brotr) -> None:
        er_keep = _event_relay("b1" * 32, "wss://ev-keep.example.com")
        er_orphan = _event_relay("b2" * 32, "wss://ev-orphan.example.com")
        await brotr.insert_event_relay([er_keep, er_orphan], cascade=True)

        await brotr.execute("DELETE FROM relay WHERE url = $1", "wss://ev-orphan.example.com")

        deleted = await brotr.delete_orphan_event()
        assert deleted == 1
        assert await brotr.fetchval("SELECT COUNT(*) FROM event") == 1

    async def test_event_on_multiple_relays_not_orphaned_until_all_deleted(
        self, brotr: Brotr
    ) -> None:
        mock = make_mock_event(event_id="c1" * 32, sig="ee" * 64)
        event = Event(mock)
        relay1 = Relay("wss://ev-multi-r1.example.com", discovered_at=1700000000)
        relay2 = Relay("wss://ev-multi-r2.example.com", discovered_at=1700000000)
        er1 = EventRelay(event=event, relay=relay1, seen_at=1700000001)
        er2 = EventRelay(event=event, relay=relay2, seen_at=1700000001)
        await brotr.insert_event_relay([er1, er2], cascade=True)

        await brotr.execute("DELETE FROM relay WHERE url = $1", "wss://ev-multi-r1.example.com")
        assert await brotr.delete_orphan_event() == 0

        await brotr.execute("DELETE FROM relay WHERE url = $1", "wss://ev-multi-r2.example.com")
        assert await brotr.delete_orphan_event() == 1

    async def test_idempotent_after_cleanup(self, brotr: Brotr) -> None:
        er = _event_relay("d1" * 32, "wss://ev-idemp.example.com")
        await brotr.insert_event_relay([er], cascade=True)
        await brotr.execute("DELETE FROM relay WHERE url = $1", "wss://ev-idemp.example.com")

        assert await brotr.delete_orphan_event() == 1
        assert await brotr.delete_orphan_event() == 0


# =============================================================================
# Orphan Metadata Delete
# =============================================================================


class TestOrphanMetadataDelete:
    async def test_empty_db_returns_zero(self, brotr: Brotr) -> None:
        assert await brotr.delete_orphan_metadata() == 0

    async def test_deletes_orphaned_after_relay_delete(self, brotr: Brotr) -> None:
        rm = _relay_metadata("wss://orphan-meta1.example.com", {"name": "Orphan"})
        await brotr.insert_relay_metadata([rm], cascade=True)

        await brotr.execute("DELETE FROM relay WHERE url = $1", "wss://orphan-meta1.example.com")
        assert await brotr.fetchval("SELECT COUNT(*) FROM metadata") == 1

        deleted = await brotr.delete_orphan_metadata()
        assert deleted == 1
        assert await brotr.fetchval("SELECT COUNT(*) FROM metadata") == 0

    async def test_preserves_non_orphaned(self, brotr: Brotr) -> None:
        rm = _relay_metadata(
            "wss://keep-meta.example.com", {"issuer": "CA"}, MetadataType.NIP66_SSL
        )
        await brotr.insert_relay_metadata([rm], cascade=True)

        assert await brotr.delete_orphan_metadata() == 0
        assert await brotr.fetchval("SELECT COUNT(*) FROM metadata") == 1

    async def test_shared_metadata_preserved_when_one_relay_deleted(self, brotr: Brotr) -> None:
        relay1 = Relay("wss://shared-m1.example.com", discovered_at=1700000000)
        relay2 = Relay("wss://shared-m2.example.com", discovered_at=1700000000)
        metadata = Metadata(type=MetadataType.NIP11_INFO, data={"name": "Shared"})

        rm1 = RelayMetadata(relay=relay1, metadata=metadata, generated_at=1700000001)
        rm2 = RelayMetadata(relay=relay2, metadata=metadata, generated_at=1700000001)
        await brotr.insert_relay_metadata([rm1, rm2], cascade=True)

        await brotr.execute("DELETE FROM relay WHERE url = $1", "wss://shared-m1.example.com")

        assert await brotr.delete_orphan_metadata() == 0
        assert await brotr.fetchval("SELECT COUNT(*) FROM metadata") == 1

    async def test_multiple_orphans_different_types(self, brotr: Brotr) -> None:
        rms = [
            _relay_metadata(f"wss://orph-mt{i}.example.com", {"i": i}, MetadataType.NIP66_RTT)
            for i in range(3)
        ]
        await brotr.insert_relay_metadata(rms, cascade=True)

        for i in range(3):
            await brotr.execute("DELETE FROM relay WHERE url = $1", f"wss://orph-mt{i}.example.com")

        deleted = await brotr.delete_orphan_metadata()
        assert deleted == 3

    async def test_mixed_orphaned_and_referenced(self, brotr: Brotr) -> None:
        rm_keep = _relay_metadata("wss://meta-keep.example.com", {"k": 1})
        rm_orphan = _relay_metadata(
            "wss://meta-orphan.example.com", {"k": 2}, MetadataType.NIP66_GEO
        )
        await brotr.insert_relay_metadata([rm_keep, rm_orphan], cascade=True)

        await brotr.execute("DELETE FROM relay WHERE url = $1", "wss://meta-orphan.example.com")

        deleted = await brotr.delete_orphan_metadata()
        assert deleted == 1
        assert await brotr.fetchval("SELECT COUNT(*) FROM metadata") == 1

    async def test_idempotent_after_cleanup(self, brotr: Brotr) -> None:
        rm = _relay_metadata("wss://meta-idemp.example.com", {"x": 1}, MetadataType.NIP66_DNS)
        await brotr.insert_relay_metadata([rm], cascade=True)
        await brotr.execute("DELETE FROM relay WHERE url = $1", "wss://meta-idemp.example.com")

        assert await brotr.delete_orphan_metadata() == 1
        assert await brotr.delete_orphan_metadata() == 0
