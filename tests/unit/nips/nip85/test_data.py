"""Tests for NIP-85 assertion data models."""

from __future__ import annotations

import pytest

from bigbrotr.nips.nip85.data import (
    AddressableAssertion,
    EventAssertion,
    IdentifierAssertion,
    TrustedProviderDeclaration,
    UserAssertion,
    _heatmap_window_end,
    _heatmap_window_start,
)


def test_public_package_exports_all_nip85_models() -> None:
    import bigbrotr.nips.nip85 as public_nip85

    assert public_nip85.AddressableAssertion is AddressableAssertion
    assert public_nip85.EventAssertion is EventAssertion
    assert public_nip85.IdentifierAssertion is IdentifierAssertion
    assert public_nip85.TrustedProviderDeclaration is TrustedProviderDeclaration
    assert public_nip85.UserAssertion is UserAssertion


class TestUserAssertionProperties:
    def test_zap_amount_sats_conversion(self) -> None:
        a = UserAssertion(pubkey="aa" * 32, zap_amount_recd_msats=21000)
        assert a.zap_amount_recd_sats == 21

    def test_zap_amount_sats_truncates(self) -> None:
        a = UserAssertion(pubkey="aa" * 32, zap_amount_recd_msats=999)
        assert a.zap_amount_recd_sats == 0

    def test_zap_amount_sent_sats(self) -> None:
        a = UserAssertion(pubkey="aa" * 32, zap_amount_sent_msats=5500)
        assert a.zap_amount_sent_sats == 5

    def test_days_active_with_data(self) -> None:
        a = UserAssertion(
            pubkey="aa" * 32,
            first_created_at=1000000,
            last_event_at=1000000 + 86400 * 10,
        )
        assert a.days_active == 11

    def test_days_active_same_day(self) -> None:
        a = UserAssertion(pubkey="aa" * 32, first_created_at=100, last_event_at=200)
        assert a.days_active == 1

    def test_days_active_no_data(self) -> None:
        a = UserAssertion(pubkey="aa" * 32)
        assert a.days_active == 0

    def test_zap_avg_amt_day_recd(self) -> None:
        a = UserAssertion(
            pubkey="aa" * 32,
            zap_amount_recd_msats=10000000,
            first_created_at=0,
            last_event_at=86400 * 9,
        )
        assert a.zap_avg_amt_day_recd_sats == 1000

    def test_zap_avg_amt_day_zero_days(self) -> None:
        a = UserAssertion(pubkey="aa" * 32, zap_amount_recd_msats=5000)
        assert a.zap_avg_amt_day_recd_sats == 0


class TestUserAssertionActiveHours:
    def test_all_zeros(self) -> None:
        a = UserAssertion(pubkey="aa" * 32)
        assert a.active_hours_start == 0
        assert a.active_hours_end == 8  # (0 + 8) % 24

    def test_peak_at_noon(self) -> None:
        hours = tuple(10 if 10 <= i <= 17 else 0 for i in range(24))
        a = UserAssertion(pubkey="aa" * 32, activity_hours=hours)
        assert a.active_hours_start == 10
        assert a.active_hours_end == 18

    def test_peak_wraps_midnight(self) -> None:
        hours = tuple(10 if i >= 20 or i <= 3 else 0 for i in range(24))
        a = UserAssertion(pubkey="aa" * 32, activity_hours=hours)
        assert a.active_hours_start == 20
        assert a.active_hours_end == 4


class TestUserAssertionTagsHash:
    def test_same_data_same_hash(self) -> None:
        a1 = UserAssertion(pubkey="aa" * 32, post_count=10)
        a2 = UserAssertion(pubkey="aa" * 32, post_count=10)
        assert a1.tags_hash() == a2.tags_hash()

    def test_different_data_different_hash(self) -> None:
        a1 = UserAssertion(pubkey="aa" * 32, post_count=10)
        a2 = UserAssertion(pubkey="aa" * 32, post_count=11)
        assert a1.tags_hash() != a2.tags_hash()


class TestUserAssertionFromDbRow:
    def test_minimal_row(self) -> None:
        row = {"pubkey": "aa" * 32}
        a = UserAssertion.from_db_row(row)
        assert a.pubkey == "aa" * 32
        assert a.post_count == 0

    def test_full_row(self) -> None:
        row = {
            "pubkey": "bb" * 32,
            "post_count": 100,
            "reply_count": 20,
            "reaction_count_recd": 50,
            "reaction_count_sent": 30,
            "repost_count_recd": 5,
            "repost_count_sent": 3,
            "report_count_recd": 1,
            "report_count_sent": 2,
            "zap_count_recd": 10,
            "zap_count_sent": 8,
            "zap_amount_recd": 500000,
            "zap_amount_sent": 300000,
            "first_created_at": 1700000000,
            "last_event_at": 1710000000,
            "activity_hours": list(range(24)),
            "topic_counts": {"bitcoin": 50, "nostr": 30, "lightning": 10},
            "follower_count": 200,
            "following_count": 150,
        }
        a = UserAssertion.from_db_row(row)
        assert a.post_count == 100
        assert a.zap_amount_recd_msats == 500000
        assert a.zap_amount_recd_sats == 500
        assert a.follower_count == 200
        assert a.following_count == 150
        assert a.top_topics == ("bitcoin", "nostr", "lightning")

    def test_topic_limit(self) -> None:
        row = {
            "pubkey": "cc" * 32,
            "topic_counts": {"a": 5, "b": 4, "c": 3, "d": 2, "e": 1, "f": 0},
            "top_topics_limit": 3,
        }
        a = UserAssertion.from_db_row(row)
        assert len(a.top_topics) == 3
        assert a.top_topics == ("a", "b", "c")

    def test_topic_counts_string_values_sorted_numerically(self) -> None:
        """JSONB topic counts may arrive as strings after upsert merge; sort must be numeric."""
        row = {
            "pubkey": "cc" * 32,
            "topic_counts": {"bitcoin": "10", "nostr": "2", "lightning": "100"},
            "top_topics_limit": 3,
        }
        a = UserAssertion.from_db_row(row)
        assert a.top_topics == ("lightning", "bitcoin", "nostr")


class TestEventAssertionProperties:
    def test_zap_amount_sats(self) -> None:
        a = EventAssertion(event_id="ee" * 32, zap_amount_msats=42000)
        assert a.zap_amount_sats == 42

    def test_tags_hash_stability(self) -> None:
        a = EventAssertion(event_id="ee" * 32, comment_count=5, reaction_count=10)
        h1 = a.tags_hash()
        h2 = a.tags_hash()
        assert h1 == h2


class TestEventAssertionFromDbRow:
    def test_full_row(self) -> None:
        row = {
            "event_id": "ff" * 32,
            "author_pubkey": "aa" * 32,
            "comment_count": 10,
            "quote_count": 3,
            "repost_count": 5,
            "reaction_count": 20,
            "zap_count": 2,
            "zap_amount": 100000,
        }
        a = EventAssertion.from_db_row(row)
        assert a.event_id == "ff" * 32
        assert a.comment_count == 10
        assert a.zap_amount_msats == 100000
        assert a.zap_amount_sats == 100


class TestAddressableAssertionProperties:
    def test_from_db_row_and_zap_amount_sats(self) -> None:
        row = {
            "event_address": "30023:" + ("aa" * 32) + ":article",
            "author_pubkey": "bb" * 32,
            "rank": 84,
            "comment_count": 10,
            "quote_count": 3,
            "repost_count": 5,
            "reaction_count": 20,
            "zap_count": 2,
            "zap_amount": 100000,
        }

        a = AddressableAssertion.from_db_row(row)

        assert a.event_address == "30023:" + ("aa" * 32) + ":article"
        assert a.author_pubkey == "bb" * 32
        assert a.rank == 84
        assert a.zap_amount_sats == 100


class TestIdentifierAssertionProperties:
    def test_from_db_row_preserves_k_tags(self) -> None:
        row = {
            "identifier": "isbn:9780140328721",
            "rank": 73,
            "comment_count": 3,
            "reaction_count": 4,
            "k_tags": ["book", "isbn"],
        }

        a = IdentifierAssertion.from_db_row(row)

        assert a.identifier == "isbn:9780140328721"
        assert a.rank == 73
        assert a.k_tags == ("book", "isbn")


class TestTrustedProviderDeclaration:
    def test_tag_shape_matches_kind_10040_spec(self) -> None:
        declaration = TrustedProviderDeclaration(
            result_kind=30382,
            tag_name="rank",
            service_pubkey="4f" * 32,
            relay_hint="wss://nip85.nostr.band",
        )

        assert declaration.kind_tag == "30382:rank"
        assert declaration.as_tag() == [
            "30382:rank",
            "4f" * 32,
            "wss://nip85.nostr.band",
        ]


class TestHeatmapHelpers:
    def test_empty_heatmap(self) -> None:
        assert _heatmap_window_start(tuple(0 for _ in range(24))) == 0

    @pytest.mark.parametrize(
        ("peak_start", "expected_end"),
        [(0, 8), (16, 0), (20, 4), (23, 7)],
    )
    def test_window_end_wraps(self, peak_start: int, expected_end: int) -> None:
        assert (
            _heatmap_window_end(
                tuple(
                    10 if peak_start <= i < peak_start + 8 or i < (peak_start + 8) % 24 else 0
                    for i in range(24)
                )
            )
            == expected_end
        )
