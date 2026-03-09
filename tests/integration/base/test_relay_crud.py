"""Integration tests for relay CRUD operations."""

from __future__ import annotations

import asyncio

import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.models import Relay


pytestmark = pytest.mark.integration


class TestRelayInsert:
    async def test_single_relay_inserted(self, brotr: Brotr) -> None:
        relay = Relay("wss://relay.example.com", discovered_at=1700000000)
        inserted = await brotr.insert_relay([relay])
        assert inserted == 1

        row = await brotr.fetchrow(
            "SELECT url, network, discovered_at FROM relay WHERE url = $1",
            "wss://relay.example.com",
        )
        assert row is not None
        assert row["url"] == "wss://relay.example.com"
        assert row["network"] == "clearnet"
        assert row["discovered_at"] == 1700000000

    async def test_batch_of_ten(self, brotr: Brotr) -> None:
        relays = [Relay(f"wss://r{i}.example.com", discovered_at=1700000000) for i in range(10)]
        inserted = await brotr.insert_relay(relays)
        assert inserted == 10

        count = await brotr.fetchval("SELECT COUNT(*) FROM relay")
        assert count == 10

    async def test_empty_batch(self, brotr: Brotr) -> None:
        inserted = await brotr.insert_relay([])
        assert inserted == 0

    async def test_duplicate_returns_zero(self, brotr: Brotr) -> None:
        relay = Relay("wss://dup.example.com", discovered_at=1700000000)
        first = await brotr.insert_relay([relay])
        second = await brotr.insert_relay([relay])
        assert first == 1
        assert second == 0

        count = await brotr.fetchval("SELECT COUNT(*) FROM relay")
        assert count == 1

    async def test_duplicate_preserves_original_discovered_at(self, brotr: Brotr) -> None:
        original_ts = 1700000000
        later_ts = 1700099999
        await brotr.insert_relay([Relay("wss://dup2.example.com", discovered_at=original_ts)])
        await brotr.insert_relay([Relay("wss://dup2.example.com", discovered_at=later_ts)])

        row = await brotr.fetchrow(
            "SELECT discovered_at FROM relay WHERE url = $1",
            "wss://dup2.example.com",
        )
        assert row is not None
        assert row["discovered_at"] == original_ts

    async def test_four_network_types(self, brotr: Brotr) -> None:
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

    async def test_explicit_port_and_path_preserved(self, brotr: Brotr) -> None:
        relay = Relay("wss://relay.example.com:9090/custom/path", discovered_at=1700000000)
        await brotr.insert_relay([relay])

        row = await brotr.fetchrow(
            "SELECT url FROM relay WHERE url = $1",
            "wss://relay.example.com:9090/custom/path",
        )
        assert row is not None
        assert row["url"] == "wss://relay.example.com:9090/custom/path"

    async def test_overlay_scheme_downgrade(self, brotr: Brotr) -> None:
        relay = Relay("wss://torhost.onion", discovered_at=1700000000)
        assert relay.url == "ws://torhost.onion"
        await brotr.insert_relay([relay])

        row = await brotr.fetchrow(
            "SELECT url FROM relay WHERE url = $1",
            "ws://torhost.onion",
        )
        assert row is not None
        assert row["url"] == "ws://torhost.onion"


class TestRelayInsertEdgeCases:
    async def test_ipv6_relay(self, brotr: Brotr) -> None:
        relay = Relay("wss://[2607:f8b0:4000::1]:8080", discovered_at=1700000000)
        await brotr.insert_relay([relay])

        row = await brotr.fetchrow(
            "SELECT url, network FROM relay WHERE url = $1",
            relay.url,
        )
        assert row is not None
        assert row["url"] == "wss://[2607:f8b0:4000::1]:8080"
        assert row["network"] == "clearnet"

    async def test_custom_non_default_port(self, brotr: Brotr) -> None:
        relay = Relay("wss://relay.example.com:8443", discovered_at=1700000000)
        await brotr.insert_relay([relay])

        row = await brotr.fetchrow(
            "SELECT url FROM relay WHERE url = $1",
            "wss://relay.example.com:8443",
        )
        assert row is not None
        assert row["url"] == "wss://relay.example.com:8443"

    async def test_trailing_path(self, brotr: Brotr) -> None:
        relay = Relay("wss://relay.example.com/nostr", discovered_at=1700000000)
        await brotr.insert_relay([relay])

        row = await brotr.fetchrow(
            "SELECT url FROM relay WHERE url = $1",
            "wss://relay.example.com/nostr",
        )
        assert row is not None

    async def test_large_batch_100(self, brotr: Brotr) -> None:
        relays = [Relay(f"wss://bulk{i}.example.com", discovered_at=1700000000) for i in range(100)]
        inserted = await brotr.insert_relay(relays)
        assert inserted == 100

        count = await brotr.fetchval("SELECT COUNT(*) FROM relay")
        assert count == 100

    async def test_url_normalization_roundtrip(self, brotr: Brotr) -> None:
        relay = Relay("WSS://RELAY.EXAMPLE.COM:443/", discovered_at=1700000000)
        await brotr.insert_relay([relay])

        row = await brotr.fetchrow(
            "SELECT url FROM relay WHERE url = $1",
            relay.url,
        )
        assert row is not None
        assert row["url"] == relay.url


class TestBrotrQueryFacade:
    async def test_fetchrow_returns_record(self, brotr: Brotr) -> None:
        relay = Relay("wss://fetchrow.example.com", discovered_at=1700000000)
        await brotr.insert_relay([relay])

        row = await brotr.fetchrow(
            "SELECT url, network, discovered_at FROM relay WHERE url = $1",
            "wss://fetchrow.example.com",
        )
        assert row is not None
        assert row["url"] == "wss://fetchrow.example.com"
        assert row["network"] == "clearnet"
        assert row["discovered_at"] == 1700000000

    async def test_fetchrow_nonexistent_returns_none(self, brotr: Brotr) -> None:
        row = await brotr.fetchrow(
            "SELECT url FROM relay WHERE url = $1",
            "wss://ghost.example.com",
        )
        assert row is None

    async def test_fetchval_count(self, brotr: Brotr) -> None:
        relays = [Relay(f"wss://val{i}.example.com", discovered_at=1700000000) for i in range(3)]
        await brotr.insert_relay(relays)

        count = await brotr.fetchval("SELECT COUNT(*) FROM relay")
        assert count == 3

    async def test_fetch_multiple_rows(self, brotr: Brotr) -> None:
        relays = [Relay(f"wss://multi{i}.example.com", discovered_at=1700000000) for i in range(5)]
        await brotr.insert_relay(relays)

        rows = await brotr.fetch("SELECT url FROM relay ORDER BY url")
        assert len(rows) == 5
        urls = [row["url"] for row in rows]
        assert urls == sorted(urls)

    async def test_execute_update(self, brotr: Brotr) -> None:
        relay = Relay("wss://update.example.com", discovered_at=1700000000)
        await brotr.insert_relay([relay])

        await brotr.execute(
            "UPDATE relay SET discovered_at = $1 WHERE url = $2",
            1700099999,
            "wss://update.example.com",
        )

        row = await brotr.fetchrow(
            "SELECT discovered_at FROM relay WHERE url = $1",
            "wss://update.example.com",
        )
        assert row is not None
        assert row["discovered_at"] == 1700099999

    async def test_transaction_commit(self, brotr: Brotr) -> None:
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

    async def test_transaction_rollback(self, brotr: Brotr) -> None:
        with pytest.raises(RuntimeError, match="rollback"):
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


class TestRelayInsertConcurrency:
    async def test_concurrent_overlapping_inserts(self, brotr: Brotr) -> None:
        batch_a = [
            Relay(f"wss://overlap{i}.example.com", discovered_at=1700000000) for i in range(5)
        ]
        batch_b = [
            Relay(f"wss://overlap{i}.example.com", discovered_at=1700000000) for i in range(3, 8)
        ]

        results = await asyncio.gather(
            brotr.insert_relay(batch_a),
            brotr.insert_relay(batch_b),
        )

        assert sum(results) == 8

        count = await brotr.fetchval("SELECT COUNT(*) FROM relay")
        assert count == 8

    async def test_same_relay_concurrent_tasks(self, brotr: Brotr) -> None:
        relay = Relay("wss://race.example.com", discovered_at=1700000000)

        results = await asyncio.gather(
            brotr.insert_relay([relay]),
            brotr.insert_relay([relay]),
        )

        assert sum(results) == 1

        count = await brotr.fetchval(
            "SELECT COUNT(*) FROM relay WHERE url = $1",
            "wss://race.example.com",
        )
        assert count == 1

    async def test_large_concurrent_batches_with_overlap(self, brotr: Brotr) -> None:
        batch_a = [Relay(f"wss://conc{i}.example.com", discovered_at=1700000000) for i in range(50)]
        batch_b = [
            Relay(f"wss://conc{i}.example.com", discovered_at=1700000000) for i in range(25, 75)
        ]

        results = await asyncio.gather(
            brotr.insert_relay(batch_a),
            brotr.insert_relay(batch_b),
        )

        assert sum(results) == 75

        count = await brotr.fetchval("SELECT COUNT(*) FROM relay")
        assert count == 75
