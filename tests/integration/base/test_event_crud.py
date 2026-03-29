"""Integration tests for event CRUD operations."""

from __future__ import annotations

import json

import asyncpg
import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.models import EventRelay, Relay
from bigbrotr.models.event import Event
from tests.conftest import make_mock_event
from tests.fixtures.relays import ONION_HOST


pytestmark = pytest.mark.integration


class TestEventInsert:
    async def test_single_event_roundtrip(self, brotr: Brotr):
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

    async def test_batch_of_five(self, brotr: Brotr):
        events = [Event(make_mock_event(event_id=f"{i:064x}", sig="ee" * 64)) for i in range(5)]
        inserted = await brotr.insert_event(events)
        assert inserted == 5

        count = await brotr.fetchval("SELECT COUNT(*) FROM event")
        assert count == 5

    async def test_empty_batch(self, brotr: Brotr):
        inserted = await brotr.insert_event([])
        assert inserted == 0

    async def test_duplicate_ignored(self, brotr: Brotr):
        mock = make_mock_event(event_id="ff" * 32, sig="ee" * 64)
        event = Event(mock)
        first = await brotr.insert_event([event])
        second = await brotr.insert_event([event])
        assert first == 1
        assert second == 0

        count = await brotr.fetchval("SELECT COUNT(*) FROM event")
        assert count == 1

    @pytest.mark.parametrize("kind", [0, 1, 30023])
    async def test_different_kinds(self, brotr: Brotr, kind: int):
        mock = make_mock_event(event_id=f"{kind:064x}", kind=kind, sig="ee" * 64)
        event = Event(mock)
        await brotr.insert_event([event])

        row = await brotr.fetchrow(
            "SELECT kind FROM event WHERE id = $1",
            bytes.fromhex(f"{kind:064x}"),
        )
        assert row is not None
        assert row["kind"] == kind


class TestEventRelayInsertCascade:
    async def test_creates_relay_event_and_junction(self, brotr: Brotr):
        relay = Relay("wss://cascade.example.com", discovered_at=1700000000)
        mock = make_mock_event(event_id="01" * 32, sig="ee" * 64)
        er = EventRelay(event=Event(mock), relay=relay, seen_at=1700000001)

        inserted = await brotr.insert_event_relay([er], cascade=True)
        assert inserted == 1

        assert (
            await brotr.fetchval(
                "SELECT COUNT(*) FROM relay WHERE url = $1", "wss://cascade.example.com"
            )
            == 1
        )
        assert (
            await brotr.fetchval(
                "SELECT COUNT(*) FROM event WHERE id = $1", bytes.fromhex("01" * 32)
            )
            == 1
        )
        assert (
            await brotr.fetchval(
                "SELECT COUNT(*) FROM event_relay WHERE event_id = $1", bytes.fromhex("01" * 32)
            )
            == 1
        )

    async def test_junction_columns(self, brotr: Brotr):
        relay = Relay("wss://junction.example.com", discovered_at=1700000000)
        mock = make_mock_event(event_id="02" * 32, sig="ee" * 64)
        er = EventRelay(event=Event(mock), relay=relay, seen_at=1700000099)

        await brotr.insert_event_relay([er], cascade=True)

        junction = await brotr.fetchrow(
            "SELECT event_id, relay_url, seen_at FROM event_relay WHERE event_id = $1",
            bytes.fromhex("02" * 32),
        )
        assert junction is not None
        assert junction["event_id"] == bytes.fromhex("02" * 32)
        assert junction["relay_url"] == "wss://junction.example.com"
        assert junction["seen_at"] == 1700000099

    async def test_batch_same_relay(self, brotr: Brotr):
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

    async def test_same_event_two_relays(self, brotr: Brotr):
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

    async def test_duplicate_returns_zero(self, brotr: Brotr):
        relay = Relay("wss://dup-cascade.example.com", discovered_at=1700000000)
        mock = make_mock_event(event_id="04" * 32, sig="ee" * 64)
        er = EventRelay(event=Event(mock), relay=relay, seen_at=1700000001)

        first = await brotr.insert_event_relay([er], cascade=True)
        second = await brotr.insert_event_relay([er], cascade=True)
        assert first == 1
        assert second == 0

    async def test_clearnet_and_tor_in_same_batch(self, brotr: Brotr):
        clearnet = Relay("wss://clear.example.com", discovered_at=1700000000)
        tor = Relay(
            f"ws://{ONION_HOST}.onion",
            discovered_at=1700000000,
        )
        er_clear = EventRelay(
            event=Event(make_mock_event(event_id="05" * 32, sig="ee" * 64)),
            relay=clearnet,
            seen_at=1700000001,
        )
        er_tor = EventRelay(
            event=Event(make_mock_event(event_id="06" * 32, sig="ee" * 64)),
            relay=tor,
            seen_at=1700000001,
        )

        inserted = await brotr.insert_event_relay([er_clear, er_tor], cascade=True)
        assert inserted == 2

        assert await brotr.fetchval("SELECT COUNT(*) FROM relay") == 2
        assert await brotr.fetchval("SELECT COUNT(*) FROM event") == 2
        assert await brotr.fetchval("SELECT COUNT(*) FROM event_relay") == 2

    async def test_relay_network_column(self, brotr: Brotr):
        clearnet = Relay("wss://netcheck.example.com", discovered_at=1700000000)
        tor = Relay(
            f"ws://{ONION_HOST}.onion",
            discovered_at=1700000000,
        )

        er1 = EventRelay(
            event=Event(make_mock_event(event_id="07" * 32, sig="ee" * 64)),
            relay=clearnet,
            seen_at=1700000001,
        )
        er2 = EventRelay(
            event=Event(make_mock_event(event_id="08" * 32, sig="ee" * 64)),
            relay=tor,
            seen_at=1700000001,
        )
        await brotr.insert_event_relay([er1, er2], cascade=True)

        clearnet_row = await brotr.fetchrow(
            "SELECT network FROM relay WHERE url = $1", "wss://netcheck.example.com"
        )
        assert clearnet_row is not None
        assert clearnet_row["network"] == "clearnet"

        tor_row = await brotr.fetchrow("SELECT network FROM relay WHERE url = $1", tor.url)
        assert tor_row is not None
        assert tor_row["network"] == "tor"

    async def test_large_batch(self, brotr: Brotr):
        relay = Relay("wss://large.example.com", discovered_at=1700000000)
        ers = [
            EventRelay(
                event=Event(make_mock_event(event_id=f"{i:064x}", sig="ee" * 64)),
                relay=relay,
                seen_at=1700000001 + i,
            )
            for i in range(50)
        ]

        inserted = await brotr.insert_event_relay(ers, cascade=True)
        assert inserted == 50

        assert await brotr.fetchval("SELECT COUNT(*) FROM event") == 50
        assert await brotr.fetchval("SELECT COUNT(*) FROM event_relay") == 50


class TestEventRelayInsertNonCascade:
    async def test_with_existing_fks(self, brotr: Brotr):
        relay = Relay("wss://fk-exists.example.com", discovered_at=1700000000)
        await brotr.insert_relay([relay])

        mock = make_mock_event(event_id="10" * 32, sig="ee" * 64)
        event = Event(mock)
        await brotr.insert_event([event])

        er = EventRelay(event=event, relay=relay, seen_at=1700000001)
        inserted = await brotr.insert_event_relay([er], cascade=False)
        assert inserted == 1

        assert await brotr.fetchval("SELECT COUNT(*) FROM event_relay") == 1

    async def test_missing_relay_raises(self, brotr: Brotr):
        mock = make_mock_event(event_id="11" * 32, sig="ee" * 64)
        event = Event(mock)
        await brotr.insert_event([event])

        missing_relay = Relay("wss://missing.example.com", discovered_at=1700000000)
        er = EventRelay(event=event, relay=missing_relay, seen_at=1700000001)

        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await brotr.insert_event_relay([er], cascade=False)

    async def test_missing_event_raises(self, brotr: Brotr):
        relay = Relay("wss://fk-event-missing.example.com", discovered_at=1700000000)
        await brotr.insert_relay([relay])

        mock = make_mock_event(event_id="12" * 32, sig="ee" * 64)
        event = Event(mock)
        er = EventRelay(event=event, relay=relay, seen_at=1700000001)

        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await brotr.insert_event_relay([er], cascade=False)

    async def test_duplicate_junction_returns_zero(self, brotr: Brotr):
        relay = Relay("wss://dup-junction.example.com", discovered_at=1700000000)
        await brotr.insert_relay([relay])

        mock = make_mock_event(event_id="13" * 32, sig="ee" * 64)
        event = Event(mock)
        await brotr.insert_event([event])

        er = EventRelay(event=event, relay=relay, seen_at=1700000001)
        first = await brotr.insert_event_relay([er], cascade=False)
        second = await brotr.insert_event_relay([er], cascade=False)
        assert first == 1
        assert second == 0


class TestTagvalues:
    async def test_single_char_keys_extracted(self, brotr: Brotr):
        mock = make_mock_event(
            event_id="20" * 32,
            tags=[["e", "abc123"], ["p", "def456"]],
            sig="ee" * 64,
        )
        relay = Relay("wss://tags1.example.com", discovered_at=1700000000)
        er = EventRelay(event=Event(mock), relay=relay, seen_at=1700000001)
        await brotr.insert_event_relay([er], cascade=True)

        row = await brotr.fetchrow(
            "SELECT tagvalues FROM event WHERE id = $1", bytes.fromhex("20" * 32)
        )
        assert row is not None
        assert sorted(row["tagvalues"]) == ["e:abc123", "p:def456"]

    async def test_multi_char_keys_filtered(self, brotr: Brotr):
        mock = make_mock_event(
            event_id="21" * 32,
            tags=[["relay", "wss://some.url"], ["nonce", "12345"]],
            sig="ee" * 64,
        )
        relay = Relay("wss://tags2.example.com", discovered_at=1700000000)
        er = EventRelay(event=Event(mock), relay=relay, seen_at=1700000001)
        await brotr.insert_event_relay([er], cascade=True)

        row = await brotr.fetchrow(
            "SELECT tagvalues FROM event WHERE id = $1", bytes.fromhex("21" * 32)
        )
        assert row is not None
        assert row["tagvalues"] == []

    async def test_mixed_single_and_multi_char(self, brotr: Brotr):
        mock = make_mock_event(
            event_id="22" * 32,
            tags=[["e", "id1"], ["relay", "wss://skip"], ["p", "pk1"]],
            sig="ee" * 64,
        )
        relay = Relay("wss://tags3.example.com", discovered_at=1700000000)
        er = EventRelay(event=Event(mock), relay=relay, seen_at=1700000001)
        await brotr.insert_event_relay([er], cascade=True)

        row = await brotr.fetchrow(
            "SELECT tagvalues FROM event WHERE id = $1", bytes.fromhex("22" * 32)
        )
        assert row is not None
        assert sorted(row["tagvalues"]) == ["e:id1", "p:pk1"]

    async def test_empty_tags(self, brotr: Brotr):
        mock = make_mock_event(event_id="23" * 32, tags=[], sig="ee" * 64)
        relay = Relay("wss://tags4.example.com", discovered_at=1700000000)
        er = EventRelay(event=Event(mock), relay=relay, seen_at=1700000001)
        await brotr.insert_event_relay([er], cascade=True)

        row = await brotr.fetchrow(
            "SELECT tagvalues FROM event WHERE id = $1", bytes.fromhex("23" * 32)
        )
        assert row is not None
        assert row["tagvalues"] == []

    async def test_duplicate_tag_keys(self, brotr: Brotr):
        mock = make_mock_event(
            event_id="24" * 32,
            tags=[["e", "id1"], ["e", "id2"]],
            sig="ee" * 64,
        )
        relay = Relay("wss://tags5.example.com", discovered_at=1700000000)
        er = EventRelay(event=Event(mock), relay=relay, seen_at=1700000001)
        await brotr.insert_event_relay([er], cascade=True)

        row = await brotr.fetchrow(
            "SELECT tagvalues FROM event WHERE id = $1", bytes.fromhex("24" * 32)
        )
        assert row is not None
        assert sorted(row["tagvalues"]) == ["e:id1", "e:id2"]

    async def test_direct_sql_call(self, brotr: Brotr):
        tags_json = json.dumps([["e", "abc"], ["p", "def"], ["relay", "skip"]])
        result = await brotr.fetchval("SELECT tags_to_tagvalues($1::jsonb)", tags_json)
        assert sorted(result) == ["e:abc", "p:def"]


class TestEventColumnRoundTrip:
    async def test_id_bytes(self, brotr: Brotr):
        expected_id = bytes(range(32))
        mock = make_mock_event(event_id=expected_id.hex(), sig="ee" * 64)
        event = Event(mock)
        await brotr.insert_event([event])

        fetched = await brotr.fetchval("SELECT id FROM event WHERE id = $1", expected_id)
        assert fetched == expected_id

    async def test_pubkey_bytes(self, brotr: Brotr):
        expected_pk = bytes(range(32))
        mock = make_mock_event(event_id="30" * 32, pubkey=expected_pk.hex(), sig="ee" * 64)
        event = Event(mock)
        await brotr.insert_event([event])

        row = await brotr.fetchrow(
            "SELECT pubkey FROM event WHERE id = $1", bytes.fromhex("30" * 32)
        )
        assert row is not None
        assert row["pubkey"] == expected_pk

    async def test_sig_bytes(self, brotr: Brotr):
        expected_sig = bytes(range(64))
        mock = make_mock_event(event_id="31" * 32, sig=expected_sig.hex())
        event = Event(mock)
        await brotr.insert_event([event])

        row = await brotr.fetchrow("SELECT sig FROM event WHERE id = $1", bytes.fromhex("31" * 32))
        assert row is not None
        assert row["sig"] == expected_sig

    async def test_complex_tags_preserved(self, brotr: Brotr):
        tags = [
            ["e", "aa" * 32, "wss://relay.example.com", "reply"],
            ["p", "bb" * 32],
            ["t", "nostr"],
            ["d", "unique-id"],
        ]
        mock = make_mock_event(event_id="32" * 32, tags=tags, sig="ee" * 64)
        event = Event(mock)
        await brotr.insert_event([event])

        row = await brotr.fetchrow("SELECT tags FROM event WHERE id = $1", bytes.fromhex("32" * 32))
        assert row is not None
        assert row["tags"] == tags

    async def test_unicode_content(self, brotr: Brotr):
        content = "Ciao mondo! \U0001f30d \u2764\ufe0f \u00e9\u00e8\u00ea \u4f60\u597d \U0001f680"
        mock = make_mock_event(event_id="33" * 32, content=content, sig="ee" * 64)
        event = Event(mock)
        await brotr.insert_event([event])

        row = await brotr.fetchrow(
            "SELECT content FROM event WHERE id = $1", bytes.fromhex("33" * 32)
        )
        assert row is not None
        assert row["content"] == content
