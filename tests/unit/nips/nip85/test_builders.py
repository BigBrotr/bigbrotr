"""Tests for NIP-85 event builder functions."""

from __future__ import annotations

from typing import Any

from bigbrotr.models.constants import EventKind
from bigbrotr.nips.event_builders import (
    build_addressable_assertion,
    build_event_assertion,
    build_identifier_assertion,
    build_user_assertion,
)
from bigbrotr.nips.nip85.data import (
    AddressableAssertion,
    EventAssertion,
    IdentifierAssertion,
    UserAssertion,
)


def _extract_tags(builder: Any) -> dict[str, list[str]]:
    """Build a tag lookup from an EventBuilder (uses nostr_sdk internals)."""
    from nostr_sdk import Keys

    keys = Keys.generate()
    event = builder.sign_with_keys(keys)
    result: dict[str, list[str]] = {}
    for tag in event.tags().to_vec():
        vec = tag.as_vec()
        if vec:
            key = vec[0]
            if key not in result:
                result[key] = []
            if len(vec) > 1:
                result[key].append(vec[1])
    return result


class TestBuildUserAssertion:
    def test_kind(self) -> None:
        a = UserAssertion(pubkey="aa" * 32, post_count=5)
        builder = build_user_assertion(a)
        from nostr_sdk import Keys

        event = builder.sign_with_keys(Keys.generate())
        assert event.kind().as_u16() == EventKind.NIP85_USER_ASSERTION

    def test_d_tag_is_pubkey(self) -> None:
        pubkey = "bb" * 32
        a = UserAssertion(pubkey=pubkey)
        tags = _extract_tags(build_user_assertion(a))
        assert tags["d"] == [pubkey]

    def test_p_tag_included(self) -> None:
        pubkey = "cc" * 32
        a = UserAssertion(pubkey=pubkey)
        tags = _extract_tags(build_user_assertion(a))
        assert pubkey in tags["p"]

    def test_zap_amount_in_sats(self) -> None:
        a = UserAssertion(pubkey="aa" * 32, zap_amount_recd_msats=21000)
        tags = _extract_tags(build_user_assertion(a))
        assert tags["zap_amt_recd"] == ["21"]

    def test_first_created_at_included(self) -> None:
        a = UserAssertion(pubkey="aa" * 32, first_created_at=1700000000)
        tags = _extract_tags(build_user_assertion(a))
        assert tags["first_created_at"] == ["1700000000"]

    def test_first_created_at_omitted_when_none(self) -> None:
        a = UserAssertion(pubkey="aa" * 32)
        tags = _extract_tags(build_user_assertion(a))
        assert "first_created_at" not in tags

    def test_topics_as_t_tags(self) -> None:
        a = UserAssertion(pubkey="aa" * 32, top_topics=("bitcoin", "nostr"))
        tags = _extract_tags(build_user_assertion(a))
        assert "bitcoin" in tags["t"]
        assert "nostr" in tags["t"]

    def test_no_topics_no_t_tags(self) -> None:
        a = UserAssertion(pubkey="aa" * 32)
        tags = _extract_tags(build_user_assertion(a))
        assert "t" not in tags

    def test_all_nip85_tags_present(self) -> None:
        a = UserAssertion(
            pubkey="aa" * 32,
            rank=89,
            post_count=100,
            reply_count=20,
            reaction_count_recd=50,
            follower_count=200,
            first_created_at=1700000000,
        )
        tags = _extract_tags(build_user_assertion(a))
        expected_keys = {
            "d",
            "p",
            "rank",
            "followers",
            "post_cnt",
            "reply_cnt",
            "reactions_cnt",
            "zap_amt_recd",
            "zap_amt_sent",
            "zap_cnt_recd",
            "zap_cnt_sent",
            "zap_avg_amt_day_recd",
            "zap_avg_amt_day_sent",
            "reports_cnt_recd",
            "reports_cnt_sent",
            "active_hours_start",
            "active_hours_end",
            "first_created_at",
        }
        assert expected_keys.issubset(set(tags.keys()))

    def test_content_is_empty(self) -> None:
        a = UserAssertion(pubkey="aa" * 32)
        from nostr_sdk import Keys

        event = build_user_assertion(a).sign_with_keys(Keys.generate())
        assert event.content() == ""


class TestBuildEventAssertion:
    def test_kind(self) -> None:
        a = EventAssertion(event_id="ee" * 32)
        from nostr_sdk import Keys

        event = build_event_assertion(a).sign_with_keys(Keys.generate())
        assert event.kind().as_u16() == EventKind.NIP85_EVENT_ASSERTION

    def test_d_tag_is_event_id(self) -> None:
        event_id = "ff" * 32
        a = EventAssertion(event_id=event_id)
        tags = _extract_tags(build_event_assertion(a))
        assert tags["d"] == [event_id]

    def test_e_tag_included(self) -> None:
        event_id = "ff" * 32
        a = EventAssertion(event_id=event_id)
        tags = _extract_tags(build_event_assertion(a))
        assert event_id in tags["e"]

    def test_rank_tag_included(self) -> None:
        a = EventAssertion(event_id="ff" * 32, rank=91)
        tags = _extract_tags(build_event_assertion(a))
        assert tags["rank"] == ["91"]

    def test_zap_amount_in_sats(self) -> None:
        a = EventAssertion(event_id="ee" * 32, zap_amount_msats=42000)
        tags = _extract_tags(build_event_assertion(a))
        assert tags["zap_amount"] == ["42"]

    def test_all_nip85_tags_present(self) -> None:
        a = EventAssertion(
            event_id="ee" * 32,
            comment_count=10,
            quote_count=3,
            repost_count=5,
            reaction_count=20,
            zap_count=2,
            zap_amount_msats=100000,
        )
        tags = _extract_tags(build_event_assertion(a))
        expected_keys = {
            "d",
            "e",
            "rank",
            "comment_cnt",
            "quote_cnt",
            "repost_cnt",
            "reaction_cnt",
            "zap_cnt",
            "zap_amount",
        }
        assert expected_keys.issubset(set(tags.keys()))


class TestBuildAddressableAssertion:
    def test_kind(self) -> None:
        a = AddressableAssertion(event_address="30023:" + ("aa" * 32) + ":article")
        from nostr_sdk import Keys

        event = build_addressable_assertion(a).sign_with_keys(Keys.generate())
        assert event.kind().as_u16() == EventKind.NIP85_ADDRESSABLE_ASSERTION

    def test_d_and_a_tags_use_event_address(self) -> None:
        event_address = "30023:" + ("ff" * 32) + ":article"
        a = AddressableAssertion(event_address=event_address, rank=77)
        tags = _extract_tags(build_addressable_assertion(a))
        assert tags["d"] == [event_address]
        assert tags["a"] == [event_address]
        assert tags["rank"] == ["77"]

    def test_all_nip85_tags_present(self) -> None:
        a = AddressableAssertion(
            event_address="30023:" + ("aa" * 32) + ":alpha",
            rank=88,
            comment_count=10,
            quote_count=3,
            repost_count=5,
            reaction_count=20,
            zap_count=2,
            zap_amount_msats=100000,
        )
        tags = _extract_tags(build_addressable_assertion(a))
        expected_keys = {
            "d",
            "a",
            "rank",
            "comment_cnt",
            "quote_cnt",
            "repost_cnt",
            "reaction_cnt",
            "zap_cnt",
            "zap_amount",
        }
        assert expected_keys.issubset(set(tags.keys()))


class TestBuildIdentifierAssertion:
    def test_kind(self) -> None:
        a = IdentifierAssertion(identifier="isbn:9780140328721")
        from nostr_sdk import Keys

        event = build_identifier_assertion(a).sign_with_keys(Keys.generate())
        assert event.kind().as_u16() == EventKind.NIP85_IDENTIFIER_ASSERTION

    def test_d_tag_and_k_tags_included(self) -> None:
        a = IdentifierAssertion(
            identifier="isbn:9780140328721",
            rank=55,
            comment_count=3,
            reaction_count=4,
            k_tags=("book", "isbn"),
        )
        tags = _extract_tags(build_identifier_assertion(a))
        assert tags["d"] == ["isbn:9780140328721"]
        assert tags["rank"] == ["55"]
        assert sorted(tags["k"]) == ["book", "isbn"]

    def test_i_tag_is_not_added_by_default(self) -> None:
        a = IdentifierAssertion(identifier="geo:41.9028,12.4964", k_tags=("place",))
        tags = _extract_tags(build_identifier_assertion(a))
        assert "i" not in tags
