"""Integration tests for LilBrotr lightweight event storage.

LilBrotr's event_insert discards tags, content, and sig, storing only
id, pubkey, created_at, kind, and computed tagvalues. These tests verify
the lightweight storage behavior and tagvalues computation at insert time.
"""

from __future__ import annotations

import json

import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.models import EventRelay, Relay
from bigbrotr.models.event import Event
from tests.conftest import make_mock_event


pytestmark = pytest.mark.integration


# ============================================================================
# Lightweight Event Insert
# ============================================================================


class TestLightweightEventInsert:
    """Verify lilbrotr stores only core columns and computes tagvalues."""

    async def test_insert_stores_core_columns(self, brotr: Brotr):
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
            "SELECT id, pubkey, created_at, kind FROM event WHERE id = $1",
            bytes.fromhex("aa" * 32),
        )
        assert row is not None
        assert row["id"] == bytes.fromhex("aa" * 32)
        assert row["pubkey"] == bytes.fromhex("bb" * 32)
        assert row["created_at"] == 1700000000
        assert row["kind"] == 1

    async def test_tags_content_sig_not_stored(self, brotr: Brotr):
        mock = make_mock_event(event_id="ab" * 32, sig="ee" * 64)
        await brotr.insert_event([Event(mock)])

        columns = await brotr.fetch(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name = 'event' ORDER BY ordinal_position"
        )
        col_names = {row["column_name"] for row in columns}
        assert "tags" not in col_names
        assert "content" not in col_names
        assert "sig" not in col_names
        assert "tagvalues" in col_names

    async def test_tagvalues_computed_at_insert(self, brotr: Brotr):
        mock = make_mock_event(
            event_id="ac" * 32,
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
            bytes.fromhex("ac" * 32),
        )
        assert row is not None
        assert sorted(row["tagvalues"]) == ["abc123", "def456"]

    async def test_empty_tags_tagvalues_null(self, brotr: Brotr):
        mock = make_mock_event(event_id="ad" * 32, tags=[], sig="ee" * 64)
        relay = Relay("wss://empty-tags.example.com", discovered_at=1700000000)
        er = EventRelay(event=Event(mock), relay=relay, seen_at=1700000001)
        await brotr.insert_event_relay([er], cascade=True)

        row = await brotr.fetchrow(
            "SELECT tagvalues FROM event WHERE id = $1",
            bytes.fromhex("ad" * 32),
        )
        assert row is not None
        assert row["tagvalues"] is None

    async def test_cascade_stores_lightweight(self, brotr: Brotr):
        relay = Relay("wss://cascade-lw.example.com", discovered_at=1700000000)
        mock = make_mock_event(
            event_id="ae" * 32,
            tags=[["e", "val1"]],
            content="This content is discarded",
            sig="ee" * 64,
        )
        er = EventRelay(event=Event(mock), relay=relay, seen_at=1700000001)

        inserted = await brotr.insert_event_relay([er], cascade=True)
        assert inserted == 1

        assert await brotr.fetchval("SELECT COUNT(*) FROM relay") == 1
        assert await brotr.fetchval("SELECT COUNT(*) FROM event") == 1
        assert await brotr.fetchval("SELECT COUNT(*) FROM event_relay") == 1

        row = await brotr.fetchrow(
            "SELECT id, pubkey, created_at, kind, tagvalues FROM event WHERE id = $1",
            bytes.fromhex("ae" * 32),
        )
        assert row is not None
        assert row["tagvalues"] == ["val1"]

    async def test_batch_insert(self, brotr: Brotr):
        events = [Event(make_mock_event(event_id=f"{i:064x}", sig="ee" * 64)) for i in range(5)]
        inserted = await brotr.insert_event(events)
        assert inserted == 5

        count = await brotr.fetchval("SELECT COUNT(*) FROM event")
        assert count == 5

    async def test_duplicate_ignored(self, brotr: Brotr):
        mock = make_mock_event(event_id="ff" * 32, sig="ee" * 64)
        event = Event(mock)
        first = await brotr.insert_event([event])
        second = await brotr.insert_event([event])
        assert first == 1
        assert second == 0

    async def test_utility_function_available(self, brotr: Brotr):
        tags_json = json.dumps([["e", "abc"], ["p", "def"], ["relay", "skip"]])
        result = await brotr.fetchval("SELECT tags_to_tagvalues($1::jsonb)", tags_json)
        assert sorted(result) == ["abc", "def"]
