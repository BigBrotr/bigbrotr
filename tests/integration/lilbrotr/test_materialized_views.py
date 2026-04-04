"""LilBrotr integration tests for summary-table fallback behavior."""

from __future__ import annotations

import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.models import EventRelay, Relay
from bigbrotr.models.event import Event
from tests.conftest import make_mock_event


pytestmark = pytest.mark.integration


def _event_relay(
    event_id: str,
    relay_url: str,
    *,
    kind: int = 1,
    pubkey: str = "bb" * 32,
    created_at: int = 1700000000,
    seen_at: int | None = None,
    tags: list[list[str]] | None = None,
) -> EventRelay:
    mock = make_mock_event(
        event_id=event_id,
        pubkey=pubkey,
        kind=kind,
        created_at=created_at,
        sig="ee" * 64,
        tags=tags,
    )
    relay = Relay(relay_url, discovered_at=1700000000)
    return EventRelay(event=Event(mock), relay=relay, seen_at=seen_at or created_at + 1)


async def _refresh_nip85(brotr: Brotr, after: int = 0, until: int = 2_000_000_000) -> None:
    for table in ["nip85_pubkey_stats", "nip85_event_stats"]:
        await brotr.fetchval(f"SELECT {table}_refresh($1::BIGINT, $2::BIGINT)", after, until)


class TestLilBrotrNip85Fallback:
    async def test_reaction_received_fallback_deduplicates_same_target(self, brotr: Brotr) -> None:
        author = "11" * 32
        target = "22" * 32
        er = _event_relay(
            "a1" * 32,
            "wss://lil-fallback.example.com",
            kind=7,
            pubkey=author,
            tags=[["p", target], ["p", target]],
        )
        await brotr.insert_event_relay([er], cascade=True)
        await _refresh_nip85(brotr)

        row = await brotr.fetchrow(
            "SELECT reaction_count_recd FROM nip85_pubkey_stats WHERE pubkey = $1",
            target,
        )
        assert row is not None
        assert row["reaction_count_recd"] == 1

    async def test_reaction_event_fallback_deduplicates_same_target(self, brotr: Brotr) -> None:
        target_event = "a2" * 32
        target = _event_relay(target_event, "wss://lil-fallback.example.com", kind=1)
        reaction = _event_relay(
            "a3" * 32,
            "wss://lil-fallback.example.com",
            kind=7,
            tags=[["e", target_event], ["e", target_event]],
        )
        await brotr.insert_event_relay([target, reaction], cascade=True)
        await _refresh_nip85(brotr)

        row = await brotr.fetchrow(
            "SELECT reaction_count FROM nip85_event_stats WHERE event_id = $1",
            target_event,
        )
        assert row is not None
        assert row["reaction_count"] == 1

    async def test_zaps_are_not_counted_without_persisted_tags(self, brotr: Brotr) -> None:
        recipient = "33" * 32
        target_event = "a4" * 32
        ers = [
            _event_relay(target_event, "wss://lil-fallback.example.com", kind=1, pubkey="44" * 32),
            _event_relay(
                "a5" * 32,
                "wss://lil-fallback.example.com",
                kind=9735,
                pubkey="55" * 32,
                tags=[
                    ["p", recipient],
                    ["e", target_event],
                    ["amount", "21000"],
                    ["bolt11", "lnbc21000n1qqq"],
                ],
            ),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await _refresh_nip85(brotr)

        pubkey_row = await brotr.fetchrow(
            "SELECT zap_count_recd, zap_amount_recd FROM nip85_pubkey_stats WHERE pubkey = $1",
            recipient,
        )
        event_row = await brotr.fetchrow(
            "SELECT zap_count, zap_amount FROM nip85_event_stats WHERE event_id = $1",
            target_event,
        )
        assert pubkey_row is None or (
            pubkey_row["zap_count_recd"] == 0 and pubkey_row["zap_amount_recd"] == 0
        )
        assert event_row is None or (event_row["zap_count"] == 0 and event_row["zap_amount"] == 0)
