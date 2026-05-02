"""Shared-database relay storage contract tests."""

from __future__ import annotations

import asyncio

import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.models import Relay
from tests.fixtures.relays import LOKI_HOST, ONION_HOST
from tests.integration.harness.deterministic import DEFAULT_STORED_AT


pytestmark = pytest.mark.integration


class TestRelayInsertSemantics:
    async def test_insert_persists_canonical_clearnet_relay(self, brotr: Brotr) -> None:
        relay = Relay("wss://insert.example.com", stored_at=DEFAULT_STORED_AT)

        inserted = await brotr.insert_relay([relay])
        row = await brotr.fetchrow(
            "SELECT url, network, stored_at FROM relay WHERE url = $1",
            relay.url,
        )

        assert inserted == 1
        assert row is not None
        assert dict(row) == {
            "url": relay.url,
            "network": "clearnet",
            "stored_at": DEFAULT_STORED_AT,
        }

    async def test_parse_normalized_relay_is_stored_canonically(self, brotr: Brotr) -> None:
        relay = Relay.parse(" WSS://Relay.Example.Com:443/nostr?token=abc#frag ")

        inserted = await brotr.insert_relay([relay])
        row = await brotr.fetchrow(
            "SELECT url, network FROM relay WHERE url = $1",
            "wss://relay.example.com/nostr",
        )

        assert inserted == 1
        assert row is not None
        assert dict(row) == {
            "url": "wss://relay.example.com/nostr",
            "network": "clearnet",
        }

    async def test_duplicate_insert_is_idempotent_and_preserves_first_timestamp(
        self, brotr: Brotr
    ) -> None:
        first = Relay("wss://ts.example.com", stored_at=DEFAULT_STORED_AT)
        later = Relay("wss://ts.example.com", stored_at=DEFAULT_STORED_AT + 100)

        first_inserted = await brotr.insert_relay([first])
        second_inserted = await brotr.insert_relay([later])
        stored_at = await brotr.fetchval(
            "SELECT stored_at FROM relay WHERE url = $1",
            first.url,
        )

        assert first_inserted == 1
        assert second_inserted == 0
        assert stored_at == first.stored_at

    async def test_same_batch_duplicate_relays_insert_only_once(self, brotr: Brotr) -> None:
        first = Relay("wss://batch-duplicate.example.com", stored_at=DEFAULT_STORED_AT)
        second = Relay("wss://batch-distinct.example.com", stored_at=DEFAULT_STORED_AT + 1)
        duplicate = Relay("wss://batch-duplicate.example.com", stored_at=DEFAULT_STORED_AT + 2)

        inserted = await brotr.insert_relay([first, second, duplicate])
        rows = await brotr.fetch("SELECT url, stored_at FROM relay ORDER BY url")

        assert inserted == 2
        assert {row["url"]: row["stored_at"] for row in rows} == {
            first.url: first.stored_at,
            second.url: second.stored_at,
        }


class TestRelayCanonicalizationAndNetworkSemantics:
    async def test_network_variants_preserve_canonical_urls_and_network_labels(
        self, brotr: Brotr
    ) -> None:
        onion_url = f"ws://{ONION_HOST}.onion"
        loki_url = f"ws://{LOKI_HOST}.loki"
        relays = [
            Relay("wss://clearnet.example.com", stored_at=DEFAULT_STORED_AT),
            Relay(onion_url, stored_at=DEFAULT_STORED_AT + 1),
            Relay("ws://relay.i2p", stored_at=DEFAULT_STORED_AT + 2),
            Relay(loki_url, stored_at=DEFAULT_STORED_AT + 3),
        ]

        inserted = await brotr.insert_relay(relays)
        rows = await brotr.fetch("SELECT url, network FROM relay ORDER BY stored_at")

        assert inserted == 4
        assert [dict(row) for row in rows] == [
            {"url": "wss://clearnet.example.com", "network": "clearnet"},
            {"url": onion_url, "network": "tor"},
            {"url": "ws://relay.i2p", "network": "i2p"},
            {"url": loki_url, "network": "loki"},
        ]

    async def test_ipv6_relay_round_trips_through_storage(self, brotr: Brotr) -> None:
        relay = Relay("wss://[2607:f8b0:4000::1]:8080", stored_at=DEFAULT_STORED_AT)

        await brotr.insert_relay([relay])
        row = await brotr.fetchrow(
            "SELECT url, network FROM relay WHERE url = $1",
            relay.url,
        )

        assert row is not None
        assert dict(row) == {
            "url": relay.url,
            "network": "clearnet",
        }


class TestRelayConcurrencySemantics:
    async def test_concurrent_insert_converges_on_single_row(self, brotr: Brotr) -> None:
        relay = Relay("wss://concurrent.example.com", stored_at=DEFAULT_STORED_AT)

        results = await asyncio.gather(
            brotr.insert_relay([relay]),
            brotr.insert_relay([relay]),
            brotr.insert_relay([relay]),
        )
        row_count = await brotr.fetchval(
            "SELECT COUNT(*) FROM relay WHERE url = $1",
            relay.url,
        )

        assert sum(results) == 1
        assert row_count == 1
