"""Integration tests for relay CRUD operations and Brotr query facade.

Tests exercise the relay_insert stored procedure via Brotr.insert_relay(),
and the generic query facade (fetch, fetchrow, fetchval, transaction).
"""

from __future__ import annotations

import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.models import Relay


pytestmark = pytest.mark.integration


# ============================================================================
# Relay Insert
# ============================================================================


class TestRelayInsert:
    """Tests for relay_insert stored procedure via Brotr.insert_relay()."""

    async def test_insert_single(self, brotr: Brotr):
        relay = Relay("wss://relay1.example.com", discovered_at=1700000000)
        inserted = await brotr.insert_relay([relay])
        assert inserted == 1

        rows = await brotr.fetch(
            "SELECT url, network, discovered_at FROM relay WHERE url = $1",
            "wss://relay1.example.com",
        )
        assert len(rows) == 1
        assert rows[0]["url"] == "wss://relay1.example.com"
        assert rows[0]["network"] == "clearnet"
        assert rows[0]["discovered_at"] == 1700000000

    async def test_insert_batch(self, brotr: Brotr):
        relays = [Relay(f"wss://relay{i}.example.com", discovered_at=1700000000) for i in range(10)]
        inserted = await brotr.insert_relay(relays)
        assert inserted == 10

        count = await brotr.fetchval("SELECT COUNT(*) FROM relay")
        assert count == 10

    async def test_insert_empty_batch(self, brotr: Brotr):
        inserted = await brotr.insert_relay([])
        assert inserted == 0

    async def test_duplicate_ignored(self, brotr: Brotr):
        relay = Relay("wss://dup.example.com", discovered_at=1700000000)
        first = await brotr.insert_relay([relay])
        second = await brotr.insert_relay([relay])
        assert first == 1
        assert second == 0

        count = await brotr.fetchval("SELECT COUNT(*) FROM relay")
        assert count == 1

    async def test_different_networks(self, brotr: Brotr):
        relays = [
            Relay("wss://clearnet.example.com", discovered_at=1700000000),
            Relay("ws://torhost.onion", discovered_at=1700000001),
            Relay("ws://i2phost.i2p", discovered_at=1700000002),
            Relay("ws://lokihost.loki", discovered_at=1700000003),
        ]
        inserted = await brotr.insert_relay(relays)
        assert inserted == 4

        rows = await brotr.fetch("SELECT url, network FROM relay ORDER BY discovered_at")
        networks = {row["url"]: row["network"] for row in rows}
        assert networks["wss://clearnet.example.com"] == "clearnet"
        assert networks["ws://torhost.onion"] == "tor"
        assert networks["ws://i2phost.i2p"] == "i2p"
        assert networks["ws://lokihost.loki"] == "loki"

    async def test_preserves_discovered_at(self, brotr: Brotr):
        ts = 1609459200  # 2021-01-01 00:00:00 UTC
        relay = Relay("wss://ts.example.com", discovered_at=ts)
        await brotr.insert_relay([relay])

        row = await brotr.fetchrow(
            "SELECT discovered_at FROM relay WHERE url = $1",
            "wss://ts.example.com",
        )
        assert row is not None
        assert row["discovered_at"] == ts


# ============================================================================
# Brotr Query Methods
# ============================================================================


class TestBrotrQueryMethods:
    """Tests for Brotr's generic query facade on a real database."""

    async def test_fetchrow_returns_record(self, brotr: Brotr):
        relay = Relay("wss://fetchrow.example.com", discovered_at=1700000000)
        await brotr.insert_relay([relay])

        row = await brotr.fetchrow(
            "SELECT url, network FROM relay WHERE url = $1",
            "wss://fetchrow.example.com",
        )
        assert row is not None
        assert row["url"] == "wss://fetchrow.example.com"
        assert row["network"] == "clearnet"

    async def test_fetchrow_no_match_returns_none(self, brotr: Brotr):
        row = await brotr.fetchrow(
            "SELECT url FROM relay WHERE url = $1",
            "wss://nonexistent.example.com",
        )
        assert row is None

    async def test_fetchval_returns_scalar(self, brotr: Brotr):
        count = await brotr.fetchval("SELECT COUNT(*) FROM relay")
        assert count == 0

    async def test_transaction_commit(self, brotr: Brotr):
        async with brotr.transaction() as conn:
            await conn.execute(
                "INSERT INTO relay (url, network, discovered_at) VALUES ($1, $2, $3)",
                "wss://txn.example.com",
                "clearnet",
                1700000000,
            )

        row = await brotr.fetchrow(
            "SELECT url FROM relay WHERE url = $1",
            "wss://txn.example.com",
        )
        assert row is not None

    async def test_transaction_rollback(self, brotr: Brotr):
        with pytest.raises(RuntimeError, match="force rollback"):
            async with brotr.transaction() as conn:
                await conn.execute(
                    "INSERT INTO relay (url, network, discovered_at) VALUES ($1, $2, $3)",
                    "wss://rollback.example.com",
                    "clearnet",
                    1700000000,
                )
                raise RuntimeError("force rollback")

        row = await brotr.fetchrow(
            "SELECT url FROM relay WHERE url = $1",
            "wss://rollback.example.com",
        )
        assert row is None
