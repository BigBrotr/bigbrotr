"""LilBrotr integration tests for parity and best-effort fallback behavior."""

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


async def _refresh_contact_graph(brotr: Brotr, after: int = 0, until: int = 2_000_000_000) -> None:
    await brotr.refresh_materialized_view("events_replaceable_latest")
    for table in ["contact_lists_current", "contact_list_edges_current"]:
        await brotr.fetchval(f"SELECT {table}_refresh($1::BIGINT, $2::BIGINT)", after, until)


class TestLilBrotrAddressableFallback:
    async def test_addressable_d_tag_falls_back_to_tagvalues(self, brotr: Brotr) -> None:
        er = _event_relay(
            "a1" * 32,
            "wss://lil-fallback.example.com",
            kind=30023,
            pubkey="11" * 32,
            tags=[["d", "my-article"]],
        )
        await brotr.insert_event_relay([er], cascade=True)
        await brotr.refresh_materialized_view("events_addressable_latest")

        row = await brotr.fetchrow(
            "SELECT d_tag FROM events_addressable_latest WHERE id = $1",
            bytes.fromhex("a1" * 32),
        )
        assert row is not None
        assert row["d_tag"] == "my-article"

    async def test_first_d_tag_wins_when_multiple_d_tags_are_present(self, brotr: Brotr) -> None:
        er = _event_relay(
            "a2" * 32,
            "wss://lil-fallback.example.com",
            kind=30023,
            pubkey="12" * 32,
            tags=[["d", "first"], ["d", "second"]],
        )
        await brotr.insert_event_relay([er], cascade=True)
        await brotr.refresh_materialized_view("events_addressable_latest")

        row = await brotr.fetchrow(
            "SELECT d_tag FROM events_addressable_latest WHERE id = $1",
            bytes.fromhex("a2" * 32),
        )
        assert row is not None
        assert row["d_tag"] == "first"


class TestLilBrotrNip85Fallback:
    async def test_post_and_reply_counts_match_bigbrotr_semantics(self, brotr: Brotr) -> None:
        pubkey = "10" * 32
        ers = [
            _event_relay(
                "b0" * 32, "wss://lil-fallback.example.com", kind=1, pubkey=pubkey, tags=[]
            ),
            _event_relay(
                "b1" * 32,
                "wss://lil-fallback.example.com",
                kind=1,
                pubkey=pubkey,
                tags=[["e", "aa" * 32]],
            ),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await _refresh_nip85(brotr)

        row = await brotr.fetchrow(
            "SELECT post_count, reply_count FROM nip85_pubkey_stats WHERE pubkey = $1",
            pubkey,
        )
        assert row is not None
        assert row["post_count"] == 2
        assert row["reply_count"] == 1

    async def test_reaction_received_uses_first_p_fallback(self, brotr: Brotr) -> None:
        first_target = "22" * 32
        second_target = "33" * 32
        er = _event_relay(
            "a3" * 32,
            "wss://lil-fallback.example.com",
            kind=7,
            pubkey="11" * 32,
            tags=[["p", first_target], ["p", second_target], ["p", first_target]],
        )
        await brotr.insert_event_relay([er], cascade=True)
        await _refresh_nip85(brotr)

        first_row = await brotr.fetchrow(
            "SELECT reaction_count_recd FROM nip85_pubkey_stats WHERE pubkey = $1",
            first_target,
        )
        second_row = await brotr.fetchrow(
            "SELECT reaction_count_recd FROM nip85_pubkey_stats WHERE pubkey = $1",
            second_target,
        )
        assert first_row is not None
        assert first_row["reaction_count_recd"] == 1
        assert second_row is None or second_row["reaction_count_recd"] == 0

    async def test_report_received_uses_first_p_fallback(self, brotr: Brotr) -> None:
        first_target = "44" * 32
        second_target = "55" * 32
        er = _event_relay(
            "a4" * 32,
            "wss://lil-fallback.example.com",
            kind=1984,
            pubkey="13" * 32,
            tags=[["p", first_target], ["p", second_target]],
        )
        await brotr.insert_event_relay([er], cascade=True)
        await _refresh_nip85(brotr)

        first_row = await brotr.fetchrow(
            "SELECT report_count_recd FROM nip85_pubkey_stats WHERE pubkey = $1",
            first_target,
        )
        second_row = await brotr.fetchrow(
            "SELECT report_count_recd FROM nip85_pubkey_stats WHERE pubkey = $1",
            second_target,
        )
        assert first_row is not None
        assert first_row["report_count_recd"] == 1
        assert second_row is None or second_row["report_count_recd"] == 0

    async def test_repost_received_uses_first_e_fallback(self, brotr: Brotr) -> None:
        first_target = "a5" * 32
        second_target = "a6" * 32
        first_author = "66" * 32
        second_author = "77" * 32
        ers = [
            _event_relay(
                first_target, "wss://lil-fallback.example.com", kind=1, pubkey=first_author
            ),
            _event_relay(
                second_target, "wss://lil-fallback.example.com", kind=1, pubkey=second_author
            ),
            _event_relay(
                "a7" * 32,
                "wss://lil-fallback.example.com",
                kind=6,
                pubkey="88" * 32,
                tags=[["e", first_target], ["e", second_target]],
            ),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await _refresh_nip85(brotr)

        first_row = await brotr.fetchrow(
            "SELECT repost_count_recd FROM nip85_pubkey_stats WHERE pubkey = $1",
            first_author,
        )
        second_row = await brotr.fetchrow(
            "SELECT repost_count_recd FROM nip85_pubkey_stats WHERE pubkey = $1",
            second_author,
        )
        assert first_row is not None
        assert first_row["repost_count_recd"] == 1
        assert second_row is None or second_row["repost_count_recd"] == 0

    async def test_reaction_event_uses_last_e_fallback(self, brotr: Brotr) -> None:
        first_target = "a8" * 32
        last_target = "a9" * 32
        ers = [
            _event_relay(first_target, "wss://lil-fallback.example.com", kind=1),
            _event_relay(last_target, "wss://lil-fallback.example.com", kind=1),
            _event_relay(
                "aa" * 32,
                "wss://lil-fallback.example.com",
                kind=7,
                tags=[["e", first_target], ["e", last_target]],
            ),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await _refresh_nip85(brotr)

        first_row = await brotr.fetchrow(
            "SELECT reaction_count FROM nip85_event_stats WHERE event_id = $1",
            first_target,
        )
        last_row = await brotr.fetchrow(
            "SELECT reaction_count FROM nip85_event_stats WHERE event_id = $1",
            last_target,
        )
        assert first_row is None or first_row["reaction_count"] == 0
        assert last_row is not None
        assert last_row["reaction_count"] == 1

    async def test_comment_event_uses_last_e_without_reply_marker(self, brotr: Brotr) -> None:
        first_target = "ab" * 32
        last_target = "ac" * 32
        ers = [
            _event_relay(first_target, "wss://lil-fallback.example.com", kind=1),
            _event_relay(last_target, "wss://lil-fallback.example.com", kind=1),
            _event_relay(
                "ad" * 32,
                "wss://lil-fallback.example.com",
                kind=1,
                tags=[["e", first_target], ["e", last_target]],
            ),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await _refresh_nip85(brotr)

        first_row = await brotr.fetchrow(
            "SELECT comment_count FROM nip85_event_stats WHERE event_id = $1",
            first_target,
        )
        last_row = await brotr.fetchrow(
            "SELECT comment_count FROM nip85_event_stats WHERE event_id = $1",
            last_target,
        )
        assert first_row is None or first_row["comment_count"] == 0
        assert last_row is not None
        assert last_row["comment_count"] == 1

    async def test_topic_counts_use_tagvalues(self, brotr: Brotr) -> None:
        pubkey = "99" * 32
        ers = [
            _event_relay(
                "ae" * 32,
                "wss://lil-fallback.example.com",
                kind=1,
                pubkey=pubkey,
                tags=[["t", "bitcoin"]],
            ),
            _event_relay(
                "af" * 32,
                "wss://lil-fallback.example.com",
                kind=1,
                pubkey=pubkey,
                tags=[["t", "bitcoin"], ["t", "nostr"]],
            ),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await _refresh_nip85(brotr)

        row = await brotr.fetchrow(
            "SELECT topic_counts FROM nip85_pubkey_stats WHERE pubkey = $1",
            pubkey,
        )
        assert row is not None
        assert int(row["topic_counts"]["bitcoin"]) == 2
        assert int(row["topic_counts"]["nostr"]) == 1

    async def test_contact_graph_facts_use_tagvalues(self, brotr: Brotr) -> None:
        follower = "bd" * 32
        followed1 = "be" * 32
        followed2 = "bf" * 32
        er = _event_relay(
            "c0" * 32,
            "wss://lil-fallback.example.com",
            kind=3,
            pubkey=follower,
            tags=[["p", followed1], ["p", followed2], ["p", followed1]],
        )
        await brotr.insert_event_relay([er], cascade=True)
        await _refresh_contact_graph(brotr)

        row = await brotr.fetchrow(
            "SELECT source_event_id, follow_count "
            "FROM contact_lists_current WHERE follower_pubkey = $1",
            follower,
        )
        edges = await brotr.fetch(
            "SELECT followed_pubkey FROM contact_list_edges_current "
            "WHERE follower_pubkey = $1 ORDER BY followed_pubkey",
            follower,
        )

        assert row is not None
        assert row["source_event_id"] == "c0" * 32
        assert row["follow_count"] == 2
        assert [edge["followed_pubkey"] for edge in edges] == [followed1, followed2]

    async def test_follower_and_following_counts_use_tagvalues(self, brotr: Brotr) -> None:
        followed = "ba" * 32
        follower1 = "bb" * 32
        follower2 = "bc" * 32
        ers = [
            _event_relay(
                "b2" * 32,
                "wss://lil-fallback.example.com",
                kind=3,
                pubkey=follower1,
                tags=[["p", followed]],
            ),
            _event_relay(
                "b3" * 32,
                "wss://lil-fallback.example.com",
                kind=3,
                pubkey=follower2,
                tags=[["p", followed]],
            ),
            _event_relay(
                "b4" * 32,
                "wss://lil-fallback.example.com",
                kind=1,
                pubkey=followed,
            ),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await _refresh_nip85(brotr)
        await _refresh_contact_graph(brotr)
        await brotr.execute("SELECT nip85_follower_count_refresh()")

        followed_row = await brotr.fetchrow(
            "SELECT follower_count FROM nip85_pubkey_stats WHERE pubkey = $1",
            followed,
        )
        follower_row = await brotr.fetchrow(
            "SELECT following_count FROM nip85_pubkey_stats WHERE pubkey = $1",
            follower1,
        )
        assert followed_row is not None
        assert followed_row["follower_count"] == 2
        assert follower_row is not None
        assert follower_row["following_count"] == 1


class TestLilBrotrZapsBestEffort:
    async def test_zap_counts_use_best_effort_without_amounts(self, brotr: Brotr) -> None:
        recipient = "33" * 32
        target_event = "a4" * 32
        sender = "55" * 32
        ers = [
            _event_relay(target_event, "wss://lil-fallback.example.com", kind=1, pubkey="44" * 32),
            _event_relay(
                "a5" * 32,
                "wss://lil-fallback.example.com",
                kind=9735,
                pubkey=sender,
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
        sender_row = await brotr.fetchrow(
            "SELECT zap_count_sent, zap_amount_sent FROM nip85_pubkey_stats WHERE pubkey = $1",
            sender,
        )
        event_row = await brotr.fetchrow(
            "SELECT zap_count, zap_amount FROM nip85_event_stats WHERE event_id = $1",
            target_event,
        )
        assert pubkey_row is not None
        assert pubkey_row["zap_count_recd"] == 1
        assert pubkey_row["zap_amount_recd"] == 0
        assert sender_row is not None
        assert sender_row["zap_count_sent"] == 1
        assert sender_row["zap_amount_sent"] == 0
        assert event_row is not None
        assert event_row["zap_count"] == 1
        assert event_row["zap_amount"] == 0
