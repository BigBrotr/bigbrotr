"""Integration tests for LilBrotr lightweight event storage."""

from __future__ import annotations

import json

import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.models import EventRelay, Relay
from bigbrotr.models.event import Event
from tests.conftest import make_mock_event


pytestmark = pytest.mark.integration


class TestLightweightEventInsert:
    """Verify lilbrotr stores only core columns and computes tagvalues."""

    async def test_core_columns_stored(self, brotr: Brotr):
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

    async def test_tags_column_null(self, brotr: Brotr):
        mock = make_mock_event(
            event_id="a1" * 32,
            tags=[["e", "cc" * 32]],
            content="some content",
            sig="ee" * 64,
        )
        await brotr.insert_event([Event(mock)])

        row = await brotr.fetchrow(
            "SELECT tags FROM event WHERE id = $1",
            bytes.fromhex("a1" * 32),
        )
        assert row is not None
        assert row["tags"] is None

    async def test_content_column_null(self, brotr: Brotr):
        mock = make_mock_event(
            event_id="a2" * 32, content="This content is discarded", sig="ee" * 64
        )
        await brotr.insert_event([Event(mock)])

        row = await brotr.fetchrow(
            "SELECT content FROM event WHERE id = $1",
            bytes.fromhex("a2" * 32),
        )
        assert row is not None
        assert row["content"] is None

    async def test_sig_column_null(self, brotr: Brotr):
        mock = make_mock_event(event_id="a3" * 32, sig="ee" * 64)
        await brotr.insert_event([Event(mock)])

        row = await brotr.fetchrow(
            "SELECT sig FROM event WHERE id = $1",
            bytes.fromhex("a3" * 32),
        )
        assert row is not None
        assert row["sig"] is None

    async def test_tagvalues_computed_from_tags(self, brotr: Brotr):
        mock = make_mock_event(
            event_id="a4" * 32,
            tags=[["e", "abc123"], ["p", "def456"]],
            sig="ee" * 64,
        )
        await brotr.insert_event([Event(mock)])

        row = await brotr.fetchrow(
            "SELECT tagvalues FROM event WHERE id = $1",
            bytes.fromhex("a4" * 32),
        )
        assert row is not None
        assert sorted(row["tagvalues"]) == ["e:abc123", "p:def456"]

    async def test_batch_of_five(self, brotr: Brotr):
        events = [Event(make_mock_event(event_id=f"{i:064x}", sig="ee" * 64)) for i in range(5)]
        inserted = await brotr.insert_event(events)
        assert inserted == 5

        count = await brotr.fetchval("SELECT COUNT(*) FROM event")
        assert count == 5


class TestLightweightCascade:
    """Verify cascade insert creates relay, event, and junction with lightweight columns."""

    async def test_cascade_creates_all_three_rows(self, brotr: Brotr):
        relay = Relay("wss://cascade.example.com", discovered_at=1700000000)
        mock = make_mock_event(event_id="b1" * 32, sig="ee" * 64)
        er = EventRelay(event=Event(mock), relay=relay, seen_at=1700000001)

        inserted = await brotr.insert_event_relay([er], cascade=True)
        assert inserted == 1

        assert await brotr.fetchval("SELECT COUNT(*) FROM relay") == 1
        assert await brotr.fetchval("SELECT COUNT(*) FROM event") == 1
        assert await brotr.fetchval("SELECT COUNT(*) FROM event_relay") == 1

    async def test_cascade_event_has_lightweight_columns(self, brotr: Brotr):
        relay = Relay("wss://cascade-lw.example.com", discovered_at=1700000000)
        mock = make_mock_event(
            event_id="b2" * 32,
            tags=[["e", "val1"]],
            content="This content is discarded",
            sig="ee" * 64,
        )
        er = EventRelay(event=Event(mock), relay=relay, seen_at=1700000001)
        await brotr.insert_event_relay([er], cascade=True)

        row = await brotr.fetchrow(
            "SELECT tags, content, sig, tagvalues FROM event WHERE id = $1",
            bytes.fromhex("b2" * 32),
        )
        assert row is not None
        assert row["tags"] is None
        assert row["content"] is None
        assert row["sig"] is None
        assert row["tagvalues"] == ["e:val1"]

    async def test_duplicate_cascade_returns_zero(self, brotr: Brotr):
        relay = Relay("wss://dup-cascade.example.com", discovered_at=1700000000)
        mock = make_mock_event(event_id="b3" * 32, sig="ee" * 64)
        er = EventRelay(event=Event(mock), relay=relay, seen_at=1700000001)

        first = await brotr.insert_event_relay([er], cascade=True)
        second = await brotr.insert_event_relay([er], cascade=True)
        assert first == 1
        assert second == 0

    async def test_multiple_relays_same_event(self, brotr: Brotr):
        relay1 = Relay("wss://relay-a.example.com", discovered_at=1700000000)
        relay2 = Relay("wss://relay-b.example.com", discovered_at=1700000000)
        mock = make_mock_event(event_id="b4" * 32, sig="ee" * 64)
        event = Event(mock)

        er1 = EventRelay(event=event, relay=relay1, seen_at=1700000001)
        er2 = EventRelay(event=event, relay=relay2, seen_at=1700000002)

        await brotr.insert_event_relay([er1], cascade=True)
        inserted = await brotr.insert_event_relay([er2], cascade=True)
        assert inserted == 1

        assert await brotr.fetchval("SELECT COUNT(*) FROM event") == 1
        assert await brotr.fetchval("SELECT COUNT(*) FROM event_relay") == 2


class TestLightweightTagvalues:
    """Verify tagvalues computation in lilbrotr's lightweight insert."""

    async def test_empty_tags_produces_empty_array(self, brotr: Brotr):
        mock = make_mock_event(event_id="c1" * 32, tags=[], sig="ee" * 64)
        relay = Relay("wss://empty-tags.example.com", discovered_at=1700000000)
        er = EventRelay(event=Event(mock), relay=relay, seen_at=1700000001)
        await brotr.insert_event_relay([er], cascade=True)

        row = await brotr.fetchrow(
            "SELECT tagvalues FROM event WHERE id = $1",
            bytes.fromhex("c1" * 32),
        )
        assert row is not None
        assert row["tagvalues"] == []

    async def test_multi_char_tag_keys_filtered(self, brotr: Brotr):
        mock = make_mock_event(
            event_id="c2" * 32,
            tags=[["relay", "wss://some.url"], ["nonce", "12345"]],
            sig="ee" * 64,
        )
        relay = Relay("wss://multi-char.example.com", discovered_at=1700000000)
        er = EventRelay(event=Event(mock), relay=relay, seen_at=1700000001)
        await brotr.insert_event_relay([er], cascade=True)

        row = await brotr.fetchrow(
            "SELECT tagvalues FROM event WHERE id = $1",
            bytes.fromhex("c2" * 32),
        )
        assert row is not None
        assert row["tagvalues"] == []

    async def test_mixed_single_and_multi_char_keys(self, brotr: Brotr):
        mock = make_mock_event(
            event_id="c3" * 32,
            tags=[["e", "id1"], ["relay", "wss://skip"], ["p", "pk1"]],
            sig="ee" * 64,
        )
        relay = Relay("wss://mixed-tags.example.com", discovered_at=1700000000)
        er = EventRelay(event=Event(mock), relay=relay, seen_at=1700000001)
        await brotr.insert_event_relay([er], cascade=True)

        row = await brotr.fetchrow(
            "SELECT tagvalues FROM event WHERE id = $1",
            bytes.fromhex("c3" * 32),
        )
        assert row is not None
        assert sorted(row["tagvalues"]) == ["e:id1", "p:pk1"]

    async def test_tags_to_tagvalues_utility_function(self, brotr: Brotr):
        tags_json = json.dumps([["e", "abc"], ["p", "def"], ["relay", "skip"]])
        result = await brotr.fetchval("SELECT tags_to_tagvalues($1::jsonb)", tags_json)
        assert sorted(result) == ["e:abc", "p:def"]


class TestLightweightDedup:
    """Verify deduplication behavior in lilbrotr."""

    async def test_same_event_id_duplicate_ignored(self, brotr: Brotr):
        mock = make_mock_event(event_id="d1" * 32, content="first", sig="ee" * 64)
        event = Event(mock)
        first = await brotr.insert_event([event])
        second = await brotr.insert_event([event])
        assert first == 1
        assert second == 0

        count = await brotr.fetchval("SELECT COUNT(*) FROM event")
        assert count == 1

    async def test_different_id_same_content_both_stored(self, brotr: Brotr):
        mock1 = make_mock_event(
            event_id="d2" * 32,
            pubkey="bb" * 32,
            kind=1,
            content="identical content",
            sig="ee" * 64,
        )
        mock2 = make_mock_event(
            event_id="d3" * 32,
            pubkey="bb" * 32,
            kind=1,
            content="identical content",
            sig="ee" * 64,
        )
        await brotr.insert_event([Event(mock1)])
        inserted = await brotr.insert_event([Event(mock2)])
        assert inserted == 1

        count = await brotr.fetchval("SELECT COUNT(*) FROM event")
        assert count == 2
