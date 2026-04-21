"""Shared-database event and event-observation storage contract tests."""

from __future__ import annotations

import asyncpg
import pytest

from bigbrotr.core.brotr import Brotr
from tests.integration.harness.builders import (
    build_event,
    build_event_observation,
    build_relay,
)
from tests.integration.harness.deterministic import DEFAULT_OBSERVED_AT, DEFAULT_STORED_AT


pytestmark = pytest.mark.integration


class TestEventInsertSemantics:
    async def test_insert_persists_event_columns_and_tags(self, brotr: Brotr) -> None:
        event = build_event(
            "aa" * 32,
            pubkey="bb" * 32,
            created_at=DEFAULT_STORED_AT,
            kind=1,
            tags=[["e", "cc" * 32], ["p", "dd" * 32]],
            content="Hello world",
        )

        inserted = await brotr.insert_event([event])
        row = await brotr.fetchrow(
            "SELECT id, pubkey, created_at, kind, tags, content, sig FROM event WHERE id = $1",
            bytes.fromhex(str(event.id)),
        )

        assert inserted == 1
        assert row is not None
        assert dict(row) == {
            "id": bytes.fromhex("aa" * 32),
            "pubkey": bytes.fromhex("bb" * 32),
            "created_at": DEFAULT_STORED_AT,
            "kind": 1,
            "tags": [["e", "cc" * 32], ["p", "dd" * 32]],
            "content": "Hello world",
            "sig": bytes.fromhex("ee" * 64),
        }

    async def test_duplicate_event_insert_is_idempotent(self, brotr: Brotr) -> None:
        event = build_event("ff" * 32)

        first_inserted = await brotr.insert_event([event])
        second_inserted = await brotr.insert_event([event])

        assert first_inserted == 1
        assert second_inserted == 0
        assert await brotr.fetchval("SELECT COUNT(*) FROM event") == 1

    @pytest.mark.parametrize(
        ("event_id", "tags", "expected_tagvalues"),
        [
            ("20" * 32, [["e", "abc123"], ["p", "def456"]], ["e:abc123", "p:def456"]),
            ("21" * 32, [["relay", "wss://skip"], ["nonce", "12345"]], []),
            ("22" * 32, [["e", "id1"], ["relay", "wss://skip"], ["p", "pk1"]], ["e:id1", "p:pk1"]),
        ],
    )
    async def test_tagvalues_are_derived_only_from_single_char_tags(
        self,
        brotr: Brotr,
        event_id: str,
        tags: list[list[str]],
        expected_tagvalues: list[str],
    ) -> None:
        event = build_event(event_id, tags=tags)

        await brotr.insert_event([event])
        tagvalues = await brotr.fetchval(
            "SELECT tagvalues FROM event WHERE id = $1",
            bytes.fromhex(str(event.id)),
        )

        assert sorted(tagvalues) == sorted(expected_tagvalues)


class TestEventObservationCascadeSemantics:
    async def test_cascade_insert_creates_relay_event_and_junction_rows(self, brotr: Brotr) -> None:
        observation = build_event_observation(
            "01" * 32,
            "wss://cascade.example.com",
            observed_at=DEFAULT_OBSERVED_AT,
            stored_at=DEFAULT_STORED_AT,
        )

        inserted = await brotr.insert_event_observation([observation], cascade=True)
        junction = await brotr.fetchrow(
            "SELECT event_id, relay_url, observed_at FROM event_observation WHERE event_id = $1",
            bytes.fromhex(str(observation.event.id)),
        )

        assert inserted == 1
        assert await brotr.fetchval("SELECT COUNT(*) FROM relay") == 1
        assert await brotr.fetchval("SELECT COUNT(*) FROM event") == 1
        assert junction is not None
        assert dict(junction) == {
            "event_id": bytes.fromhex("01" * 32),
            "relay_url": observation.relay.url,
            "observed_at": DEFAULT_OBSERVED_AT,
        }

    async def test_same_event_observed_from_multiple_relays_reuses_event_row(
        self, brotr: Brotr
    ) -> None:
        first = build_event_observation(
            "03" * 32,
            "wss://relay-a.example.com",
            observed_at=DEFAULT_OBSERVED_AT,
        )
        second = build_event_observation(
            "03" * 32,
            "wss://relay-b.example.com",
            observed_at=DEFAULT_OBSERVED_AT + 1,
        )

        first_inserted = await brotr.insert_event_observation([first], cascade=True)
        second_inserted = await brotr.insert_event_observation([second], cascade=True)

        assert first_inserted == 1
        assert second_inserted == 1
        assert await brotr.fetchval("SELECT COUNT(*) FROM event") == 1
        assert await brotr.fetchval("SELECT COUNT(*) FROM event_observation") == 2

    async def test_same_relay_batch_creates_one_relay_and_many_observations(
        self, brotr: Brotr
    ) -> None:
        observations = [
            build_event_observation(
                f"{index:064x}",
                "wss://batch.example.com",
                observed_at=DEFAULT_OBSERVED_AT + index,
                stored_at=DEFAULT_STORED_AT,
            )
            for index in range(5)
        ]

        inserted = await brotr.insert_event_observation(observations, cascade=True)

        assert inserted == 5
        assert await brotr.fetchval("SELECT COUNT(*) FROM relay") == 1
        assert await brotr.fetchval("SELECT COUNT(*) FROM event") == 5
        assert await brotr.fetchval("SELECT COUNT(*) FROM event_observation") == 5

    async def test_duplicate_cascade_observation_is_idempotent(self, brotr: Brotr) -> None:
        observation = build_event_observation(
            "04" * 32,
            "wss://dup-cascade.example.com",
            observed_at=DEFAULT_OBSERVED_AT,
        )

        first_inserted = await brotr.insert_event_observation([observation], cascade=True)
        second_inserted = await brotr.insert_event_observation([observation], cascade=True)

        assert first_inserted == 1
        assert second_inserted == 0
        assert await brotr.fetchval("SELECT COUNT(*) FROM event_observation") == 1


class TestEventObservationForeignKeySemantics:
    async def test_non_cascade_insert_requires_existing_relay_and_event(self, brotr: Brotr) -> None:
        relay = build_relay("wss://fk-exists.example.com")
        event = build_event("10" * 32)
        observation = build_event_observation(
            "10" * 32,
            relay.url,
            observed_at=DEFAULT_OBSERVED_AT,
            stored_at=relay.stored_at,
        )

        await brotr.insert_relay([relay])
        await brotr.insert_event([event])
        inserted = await brotr.insert_event_observation([observation], cascade=False)

        assert inserted == 1
        assert await brotr.fetchval("SELECT COUNT(*) FROM event_observation") == 1

    async def test_non_cascade_insert_rejects_missing_relay(self, brotr: Brotr) -> None:
        event = build_event("11" * 32)
        observation = build_event_observation(
            "11" * 32,
            "wss://missing.example.com",
            observed_at=DEFAULT_OBSERVED_AT,
        )

        await brotr.insert_event([event])

        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await brotr.insert_event_observation([observation], cascade=False)

    async def test_non_cascade_insert_rejects_missing_event(self, brotr: Brotr) -> None:
        relay = build_relay("wss://fk-event-missing.example.com")
        observation = build_event_observation(
            "12" * 32,
            relay.url,
            observed_at=DEFAULT_OBSERVED_AT,
            stored_at=relay.stored_at,
        )

        await brotr.insert_relay([relay])

        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await brotr.insert_event_observation([observation], cascade=False)
