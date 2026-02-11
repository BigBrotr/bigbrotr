"""Integration tests validating database round-trips against real PostgreSQL.

These tests run against an ephemeral PostgreSQL container via testcontainers
and exercise the full stack: Python models -> Brotr -> stored procedures -> SQL.

Each test starts with a clean schema (``brotr`` fixture drops and recreates).
"""

from __future__ import annotations

import time

import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.models import EventRelay, Relay, RelayMetadata
from bigbrotr.models.constants import ServiceName
from bigbrotr.models.event import Event
from bigbrotr.models.metadata import Metadata, MetadataType
from bigbrotr.models.service_state import ServiceState, ServiceStateType
from tests.conftest import make_mock_event


pytestmark = pytest.mark.integration


# ============================================================================
# Relay CRUD
# ============================================================================


async def test_insert_and_query_relay(brotr: Brotr):
    """relay_insert() + SELECT round-trip validates schema and stored proc."""
    relay = Relay("wss://example.com", discovered_at=1700000000)
    inserted = await brotr.insert_relay([relay])
    assert inserted == 1

    rows = await brotr.fetch(
        "SELECT url, network, discovered_at FROM relay WHERE url = $1", "wss://example.com"
    )
    assert len(rows) == 1
    assert rows[0]["url"] == "wss://example.com"
    assert rows[0]["network"] == "clearnet"
    assert rows[0]["discovered_at"] == 1700000000


async def test_duplicate_relay_ignored(brotr: Brotr):
    """ON CONFLICT DO NOTHING: inserting the same relay twice doesn't raise."""
    relay = Relay("wss://dup.example.com", discovered_at=1700000000)
    first = await brotr.insert_relay([relay])
    second = await brotr.insert_relay([relay])
    assert first == 1
    assert second == 0


# ============================================================================
# Bulk Event Insert (cascade)
# ============================================================================


async def test_bulk_event_insert_cascade(brotr: Brotr):
    """event_relay_insert_cascade() creates relay + event + junction atomically."""
    relay = Relay("wss://events.example.com", discovered_at=1700000000)
    events = []
    for i in range(5):
        mock = make_mock_event(
            event_id=f"{i:064x}",
            pubkey="bb" * 32,
            created_at=1700000000 + i,
            kind=1,
            tags=[["e", "cc" * 32]],
            content=f"Test event {i}",
            sig="ee" * 64,
        )
        events.append(EventRelay(event=Event(mock), relay=relay, seen_at=1700000001 + i))

    inserted = await brotr.insert_event_relay(events, cascade=True)
    assert inserted == 5

    # Verify relay was created
    relay_rows = await brotr.fetch(
        "SELECT url FROM relay WHERE url = $1", "wss://events.example.com"
    )
    assert len(relay_rows) == 1

    # Verify events were created
    event_rows = await brotr.fetch("SELECT id FROM event")
    assert len(event_rows) == 5

    # Verify junction records
    junction_rows = await brotr.fetch("SELECT event_id, relay_url FROM event_relay")
    assert len(junction_rows) == 5


async def test_duplicate_event_id_ignored(brotr: Brotr):
    """ON CONFLICT DO NOTHING: duplicate event IDs don't raise errors."""
    relay = Relay("wss://dup-event.example.com", discovered_at=1700000000)
    mock = make_mock_event(event_id="aa" * 32, sig="ee" * 64)
    er = EventRelay(event=Event(mock), relay=relay, seen_at=1700000001)

    first = await brotr.insert_event_relay([er], cascade=True)
    second = await brotr.insert_event_relay([er], cascade=True)
    assert first == 1
    # Second insert: junction already exists, so 0 new rows
    assert second == 0


# ============================================================================
# Service State
# ============================================================================


async def test_service_state_roundtrip(brotr: Brotr):
    """service_state_upsert/get/delete: full lifecycle round-trip."""
    now = int(time.time())

    # Insert
    records = [
        ServiceState(
            service_name=ServiceName.FINDER,
            state_type=ServiceStateType.CURSOR,
            state_key="wss://example.com",
            state_value={"last_synced_at": 1700000000},
            updated_at=now,
        )
    ]
    count = await brotr.upsert_service_state(records)
    assert count == 1

    # Read back
    rows = await brotr.get_service_state(ServiceName.FINDER, ServiceStateType.CURSOR)
    assert len(rows) == 1
    assert rows[0].state_key == "wss://example.com"
    assert rows[0].state_value["last_synced_at"] == 1700000000

    # Read by specific key
    rows_single = await brotr.get_service_state(
        ServiceName.FINDER, ServiceStateType.CURSOR, key="wss://example.com"
    )
    assert len(rows_single) == 1

    # --- upsert (update) ---
    updated_records = [
        ServiceState(
            service_name=ServiceName.FINDER,
            state_type=ServiceStateType.CURSOR,
            state_key="wss://example.com",
            state_value={"last_synced_at": 1700001000},
            updated_at=now,
        )
    ]
    await brotr.upsert_service_state(updated_records)
    rows = await brotr.get_service_state(ServiceName.FINDER, ServiceStateType.CURSOR)
    assert rows[0].state_value["last_synced_at"] == 1700001000

    # Delete
    deleted = await brotr.delete_service_state(
        [ServiceName.FINDER],
        [ServiceStateType.CURSOR],
        ["wss://example.com"],
    )
    assert deleted == 1

    rows = await brotr.get_service_state(ServiceName.FINDER, ServiceStateType.CURSOR)
    assert len(rows) == 0


# ============================================================================
# Orphan Cleanup
# ============================================================================


async def test_orphan_event_delete(brotr: Brotr):
    """orphan_event_delete() removes events with no relay association."""
    relay = Relay("wss://orphan-test.example.com", discovered_at=1700000000)
    mock = make_mock_event(event_id="ff" * 32, sig="ee" * 64)
    er = EventRelay(event=Event(mock), relay=relay, seen_at=1700000001)

    await brotr.insert_event_relay([er], cascade=True)

    # Verify event exists
    events_before = await brotr.fetch("SELECT id FROM event")
    assert len(events_before) == 1

    # Delete relay (cascades to event_relay junction)
    await brotr.execute("DELETE FROM relay WHERE url = $1", "wss://orphan-test.example.com")

    # Event still exists but is now orphaned
    events_orphaned = await brotr.fetch("SELECT id FROM event")
    assert len(events_orphaned) == 1

    # Cleanup orphans
    deleted = await brotr.delete_orphan_event()
    assert deleted == 1

    events_after = await brotr.fetch("SELECT id FROM event")
    assert len(events_after) == 0


# ============================================================================
# Materialized View Refresh
# ============================================================================


async def test_event_stats_refresh(brotr: Brotr):
    """event_stats_refresh() runs without error on empty data."""
    await brotr.refresh_materialized_view("event_stats")

    rows = await brotr.fetch("SELECT * FROM event_stats")
    assert len(rows) == 1
    assert rows[0]["event_count"] == 0


# ============================================================================
# Metadata + Relay Metadata Cascade
# ============================================================================


async def test_relay_metadata_cascade(brotr: Brotr):
    """relay_metadata_insert_cascade() creates relay + metadata + junction."""
    relay = Relay("wss://meta.example.com", discovered_at=1700000000)
    metadata = Metadata(
        type=MetadataType.NIP11_INFO,
        data={"name": "Test Relay", "supported_nips": [1, 2, 9, 11]},
    )
    rm = RelayMetadata(relay=relay, metadata=metadata, generated_at=1700000001)

    inserted = await brotr.insert_relay_metadata([rm], cascade=True)
    assert inserted == 1

    # Verify relay created
    relay_rows = await brotr.fetch("SELECT url FROM relay WHERE url = $1", "wss://meta.example.com")
    assert len(relay_rows) == 1

    # Verify metadata created (content-addressed with type)
    meta_rows = await brotr.fetch("SELECT id, data, metadata_type FROM metadata")
    assert len(meta_rows) == 1
    assert meta_rows[0]["data"]["name"] == "Test Relay"
    assert meta_rows[0]["metadata_type"] == "nip11_info"

    # Verify junction
    junction_rows = await brotr.fetch(
        "SELECT relay_url, metadata_type FROM relay_metadata WHERE relay_url = $1",
        "wss://meta.example.com",
    )
    assert len(junction_rows) == 1
    assert junction_rows[0]["metadata_type"] == "nip11_info"
