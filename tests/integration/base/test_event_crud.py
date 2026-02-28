"""Integration tests for event CRUD operations, cascade inserts, and tagvalues.

Tests exercise event_insert, event_relay_insert, event_relay_insert_cascade,
and tagvalues computation at insert time via tags_to_tagvalues.
"""

from __future__ import annotations

import json

import asyncpg.exceptions
import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.models import EventRelay, Relay
from bigbrotr.models.event import Event
from tests.conftest import make_mock_event


pytestmark = pytest.mark.integration


# ============================================================================
# Event Insert (direct, event table only)
# ============================================================================


class TestEventInsert:
    """Tests for event_insert stored procedure via Brotr.insert_event()."""

    async def test_insert_single(self, brotr: Brotr):
        mock = make_mock_event(
            event_id="aa" * 32,
            pubkey="bb" * 32,
            created_at=1700000000,
            kind=1,
            tags=[["e", "cc" * 32], ["p", "dd" * 32]],
            content="Hello world",
            sig="ee" * 64,
        )
        event = Event(mock)
        inserted = await brotr.insert_event([event])
        assert inserted == 1

        row = await brotr.fetchrow(
            "SELECT id, pubkey, created_at, kind, tags, content, sig FROM event WHERE id = $1",
            bytes.fromhex("aa" * 32),
        )
        assert row is not None
        assert row["id"] == bytes.fromhex("aa" * 32)
        assert row["pubkey"] == bytes.fromhex("bb" * 32)
        assert row["created_at"] == 1700000000
        assert row["kind"] == 1
        assert row["tags"] == [["e", "cc" * 32], ["p", "dd" * 32]]
        assert row["content"] == "Hello world"
        assert row["sig"] == bytes.fromhex("ee" * 64)

    async def test_insert_batch(self, brotr: Brotr):
        events = [Event(make_mock_event(event_id=f"{i:064x}", sig="ee" * 64)) for i in range(5)]
        inserted = await brotr.insert_event(events)
        assert inserted == 5

        count = await brotr.fetchval("SELECT COUNT(*) FROM event")
        assert count == 5

    async def test_insert_empty_batch(self, brotr: Brotr):
        inserted = await brotr.insert_event([])
        assert inserted == 0

    async def test_duplicate_ignored(self, brotr: Brotr):
        mock = make_mock_event(event_id="ff" * 32, sig="ee" * 64)
        event = Event(mock)
        first = await brotr.insert_event([event])
        second = await brotr.insert_event([event])
        assert first == 1
        assert second == 0


# ============================================================================
# Event-Relay Insert (cascade)
# ============================================================================


class TestEventRelayInsertCascade:
    """Tests for event_relay_insert_cascade stored procedure."""

    async def test_cascade_creates_all_rows(self, brotr: Brotr):
        relay = Relay("wss://cascade.example.com", discovered_at=1700000000)
        mock = make_mock_event(event_id="01" * 32, sig="ee" * 64)
        er = EventRelay(event=Event(mock), relay=relay, seen_at=1700000001)

        inserted = await brotr.insert_event_relay([er], cascade=True)
        assert inserted == 1

        relay_count = await brotr.fetchval(
            "SELECT COUNT(*) FROM relay WHERE url = $1",
            "wss://cascade.example.com",
        )
        assert relay_count == 1

        event_count = await brotr.fetchval(
            "SELECT COUNT(*) FROM event WHERE id = $1",
            bytes.fromhex("01" * 32),
        )
        assert event_count == 1

        junction = await brotr.fetchrow(
            "SELECT event_id, relay_url, seen_at FROM event_relay WHERE event_id = $1",
            bytes.fromhex("01" * 32),
        )
        assert junction is not None
        assert junction["relay_url"] == "wss://cascade.example.com"
        assert junction["seen_at"] == 1700000001

    async def test_cascade_batch(self, brotr: Brotr):
        relay = Relay("wss://batch.example.com", discovered_at=1700000000)
        ers = [
            EventRelay(
                event=Event(make_mock_event(event_id=f"{i:064x}", sig="ee" * 64)),
                relay=relay,
                seen_at=1700000001 + i,
            )
            for i in range(5)
        ]

        inserted = await brotr.insert_event_relay(ers, cascade=True)
        assert inserted == 5

        assert await brotr.fetchval("SELECT COUNT(*) FROM relay") == 1
        assert await brotr.fetchval("SELECT COUNT(*) FROM event") == 5
        assert await brotr.fetchval("SELECT COUNT(*) FROM event_relay") == 5

    async def test_cascade_duplicate_ignored(self, brotr: Brotr):
        relay = Relay("wss://dup-cascade.example.com", discovered_at=1700000000)
        mock = make_mock_event(event_id="02" * 32, sig="ee" * 64)
        er = EventRelay(event=Event(mock), relay=relay, seen_at=1700000001)

        first = await brotr.insert_event_relay([er], cascade=True)
        second = await brotr.insert_event_relay([er], cascade=True)
        assert first == 1
        assert second == 0

    async def test_same_event_multiple_relays(self, brotr: Brotr):
        relay1 = Relay("wss://relay-a.example.com", discovered_at=1700000000)
        relay2 = Relay("wss://relay-b.example.com", discovered_at=1700000000)
        mock = make_mock_event(event_id="03" * 32, sig="ee" * 64)
        event = Event(mock)

        er1 = EventRelay(event=event, relay=relay1, seen_at=1700000001)
        er2 = EventRelay(event=event, relay=relay2, seen_at=1700000002)

        await brotr.insert_event_relay([er1], cascade=True)
        inserted = await brotr.insert_event_relay([er2], cascade=True)
        assert inserted == 1

        assert await brotr.fetchval("SELECT COUNT(*) FROM event") == 1
        assert await brotr.fetchval("SELECT COUNT(*) FROM event_relay") == 2


# ============================================================================
# Event-Relay Insert (non-cascade, junction-only)
# ============================================================================


class TestEventRelayInsertNonCascade:
    """Tests for event_relay_insert (non-cascade, junction-only)."""

    async def test_with_existing_fks(self, brotr: Brotr):
        relay = Relay("wss://fk-exists.example.com", discovered_at=1700000000)
        await brotr.insert_relay([relay])

        mock = make_mock_event(event_id="04" * 32, sig="ee" * 64)
        event = Event(mock)
        await brotr.insert_event([event])

        er = EventRelay(event=event, relay=relay, seen_at=1700000001)
        inserted = await brotr.insert_event_relay([er], cascade=False)
        assert inserted == 1

    async def test_missing_relay_raises(self, brotr: Brotr):
        mock = make_mock_event(event_id="05" * 32, sig="ee" * 64)
        event = Event(mock)
        await brotr.insert_event([event])

        missing_relay = Relay("wss://missing.example.com", discovered_at=1700000000)
        er = EventRelay(event=event, relay=missing_relay, seen_at=1700000001)

        with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError):
            await brotr.insert_event_relay([er], cascade=False)


# ============================================================================
# Tagvalues Computation
# ============================================================================


class TestTagvaluesComputed:
    """Tests for tagvalues computation at insert time via tags_to_tagvalues."""

    async def test_extracts_single_char_keys(self, brotr: Brotr):
        mock = make_mock_event(
            event_id="06" * 32,
            tags=[
                ["e", "abc123"],
                ["p", "def456"],
                ["relay", "wss://skip.me"],
            ],
            sig="ee" * 64,
        )
        relay = Relay("wss://tags.example.com", discovered_at=1700000000)
        er = EventRelay(event=Event(mock), relay=relay, seen_at=1700000001)
        await brotr.insert_event_relay([er], cascade=True)

        row = await brotr.fetchrow(
            "SELECT tagvalues FROM event WHERE id = $1",
            bytes.fromhex("06" * 32),
        )
        assert row is not None
        assert sorted(row["tagvalues"]) == ["abc123", "def456"]

    async def test_empty_tags(self, brotr: Brotr):
        mock = make_mock_event(event_id="07" * 32, tags=[], sig="ee" * 64)
        relay = Relay("wss://empty-tags.example.com", discovered_at=1700000000)
        er = EventRelay(event=Event(mock), relay=relay, seen_at=1700000001)
        await brotr.insert_event_relay([er], cascade=True)

        row = await brotr.fetchrow(
            "SELECT tagvalues FROM event WHERE id = $1",
            bytes.fromhex("07" * 32),
        )
        assert row is not None
        assert row["tagvalues"] == []

    async def test_utility_function_directly(self, brotr: Brotr):
        tags_json = json.dumps([["e", "abc"], ["p", "def"], ["relay", "skip"]])
        result = await brotr.fetchval("SELECT tags_to_tagvalues($1::jsonb)", tags_json)
        assert sorted(result) == ["abc", "def"]
