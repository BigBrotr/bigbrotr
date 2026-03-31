"""Integration tests for HASH partitioning on event and event_relay tables."""

from __future__ import annotations

import os

import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.models import EventRelay, Relay
from bigbrotr.models.event import Event
from tests.conftest import make_mock_event


pytestmark = pytest.mark.integration

PARTITIONS = 16


def _make_event_relay(relay: Relay, index: int) -> EventRelay:
    event_id = os.urandom(32).hex()
    mock = make_mock_event(event_id=event_id, sig="ee" * 64)
    return EventRelay(event=Event(mock), relay=relay, seen_at=1700000000 + index)


class TestPartitionStructure:
    """Verify partition tables exist with correct configuration."""

    async def test_event_is_partitioned(self, brotr: Brotr) -> None:
        row = await brotr.fetchrow("SELECT relkind FROM pg_class WHERE relname = 'event'")
        assert row is not None
        assert row["relkind"] in ("p", b"p")

    async def test_event_relay_is_partitioned(self, brotr: Brotr) -> None:
        row = await brotr.fetchrow("SELECT relkind FROM pg_class WHERE relname = 'event_relay'")
        assert row is not None
        assert row["relkind"] in ("p", b"p")

    async def test_event_has_16_partitions(self, brotr: Brotr) -> None:
        count = await brotr.fetchval(
            """
            SELECT COUNT(*) FROM pg_inherits i
            JOIN pg_class p ON p.oid = i.inhparent
            WHERE p.relname = 'event'
            """
        )
        assert count == PARTITIONS

    async def test_event_relay_has_16_partitions(self, brotr: Brotr) -> None:
        count = await brotr.fetchval(
            """
            SELECT COUNT(*) FROM pg_inherits i
            JOIN pg_class p ON p.oid = i.inhparent
            WHERE p.relname = 'event_relay'
            """
        )
        assert count == PARTITIONS

    async def test_partition_names_sequential(self, brotr: Brotr) -> None:
        rows = await brotr.fetch(
            """
            SELECT c.relname FROM pg_inherits i
            JOIN pg_class c ON c.oid = i.inhrelid
            JOIN pg_class p ON p.oid = i.inhparent
            WHERE p.relname = 'event'
            """
        )
        names = sorted(
            [r["relname"] for r in rows],
            key=lambda n: int(n.split("_p")[1]),
        )
        assert names == [f"event_p{i}" for i in range(PARTITIONS)]


class TestPartitionDistribution:
    """Verify data distributes across multiple partitions."""

    async def test_events_span_multiple_partitions(self, brotr: Brotr) -> None:
        relay = Relay("wss://part-dist.example.com", discovered_at=1700000000)
        events = [_make_event_relay(relay, i) for i in range(50)]
        await brotr.insert_event_relay(events, cascade=True)

        event_parts = await brotr.fetchval("SELECT COUNT(DISTINCT tableoid::regclass) FROM event")
        er_parts = await brotr.fetchval(
            "SELECT COUNT(DISTINCT tableoid::regclass) FROM event_relay"
        )
        assert event_parts > 1
        assert er_parts > 1


class TestPartitionColocation:
    """Verify event and event_relay with the same id hash to the same partition."""

    async def test_same_id_colocated(self, brotr: Brotr) -> None:
        relay = Relay("wss://coloc.example.com", discovered_at=1700000000)
        events = [_make_event_relay(relay, i) for i in range(30)]
        await brotr.insert_event_relay(events, cascade=True)

        mismatches = await brotr.fetchval(
            """
            SELECT COUNT(*) FROM event_relay er
            JOIN event e ON e.id = er.event_id
            WHERE REPLACE(er.tableoid::regclass::text, 'event_relay_p', '')
               != REPLACE(e.tableoid::regclass::text, 'event_p', '')
            """
        )
        assert mismatches == 0
