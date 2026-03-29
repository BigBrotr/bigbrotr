"""Integration tests for relay CRUD operations."""

from __future__ import annotations

import asyncio

import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.models import Relay
from tests.fixtures.relays import LOKI_HOST, ONION_HOST


pytestmark = pytest.mark.integration


class TestRelayInsert:
    async def test_single_relay_insert(self, brotr: Brotr) -> None:
        relay = Relay("wss://insert.example.com", discovered_at=1700000000)
        inserted = await brotr.insert_relay([relay])
        assert inserted == 1

        row = await brotr.fetchrow("SELECT url, network FROM relay WHERE url = $1", relay.url)
        assert row is not None
        assert row["url"] == "wss://insert.example.com"
        assert row["network"] == "clearnet"

    async def test_duplicate_relay_not_inserted(self, brotr: Brotr) -> None:
        relay = Relay("wss://dup.example.com", discovered_at=1700000000)
        first = await brotr.insert_relay([relay])
        assert first == 1

        second = await brotr.insert_relay([relay])
        assert second == 0

    async def test_duplicate_preserves_original_timestamp(self, brotr: Brotr) -> None:
        original_ts = 1700000000
        relay1 = Relay("wss://ts.example.com", discovered_at=original_ts)
        await brotr.insert_relay([relay1])

        later_ts = 1800000000
        relay2 = Relay("wss://ts.example.com", discovered_at=later_ts)
        await brotr.insert_relay([relay2])

        row = await brotr.fetchrow(
            "SELECT discovered_at FROM relay WHERE url = $1", "wss://ts.example.com"
        )
        assert row["discovered_at"] == original_ts

    async def test_four_network_types(self, brotr: Brotr) -> None:
        onion_url = f"ws://{ONION_HOST}.onion"
        loki_url = f"ws://{LOKI_HOST}.loki"
        relays = [
            Relay("wss://clearnet.example.com", discovered_at=1700000000),
            Relay(onion_url, discovered_at=1700000001),
            Relay("ws://i2phost.i2p", discovered_at=1700000002),
            Relay(loki_url, discovered_at=1700000003),
        ]
        inserted = await brotr.insert_relay(relays)
        assert inserted == 4

        rows = await brotr.fetch("SELECT url, network FROM relay ORDER BY discovered_at")
        networks = {row["url"]: row["network"] for row in rows}
        assert networks["wss://clearnet.example.com"] == "clearnet"
        assert networks[onion_url] == "tor"
        assert networks["ws://i2phost.i2p"] == "i2p"
        assert networks[loki_url] == "loki"

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
        onion_url = f"ws://{ONION_HOST}.onion"
        relay = Relay(onion_url, discovered_at=1700000000)
        assert relay.url == onion_url
        await brotr.insert_relay([relay])

        row = await brotr.fetchrow(
            "SELECT url FROM relay WHERE url = $1",
            onion_url,
        )
        assert row is not None
        assert row["url"] == onion_url


class TestRelayInsertEdgeCases:
    async def test_ipv6_relay(self, brotr: Brotr) -> None:
        relay = Relay("wss://[2607:f8b0:4000::1]:8080", discovered_at=1700000000)
        await brotr.insert_relay([relay])

        row = await brotr.fetchrow(
            "SELECT url, network FROM relay WHERE url = $1",
            "wss://[2607:f8b0:4000::1]:8080",
        )
        assert row is not None
        assert row["network"] == "clearnet"

    async def test_batch_insert(self, brotr: Brotr) -> None:
        relays = [Relay(f"wss://batch{i}.example.com", discovered_at=1700000000) for i in range(50)]
        inserted = await brotr.insert_relay(relays)
        assert inserted == 50

        count = await brotr.fetchval("SELECT COUNT(*) FROM relay")
        assert count == 50

    async def test_concurrent_inserts(self, brotr: Brotr) -> None:
        relay = Relay("wss://concurrent.example.com", discovered_at=1700000000)
        results = await asyncio.gather(
            brotr.insert_relay([relay]),
            brotr.insert_relay([relay]),
            brotr.insert_relay([relay]),
        )
        assert sum(results) == 1

        count = await brotr.fetchval(
            "SELECT COUNT(*) FROM relay WHERE url = $1",
            "wss://concurrent.example.com",
        )
        assert count == 1
