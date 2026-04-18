"""Tests for NIP-85 assertion data models."""

from __future__ import annotations

import pytest

from bigbrotr.nips.event_builders import (
    build_addressable_assertion,
    build_event_assertion,
    build_identifier_assertion,
    build_trusted_provider_list,
    build_user_assertion,
)
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
    assert public_nip85.build_user_assertion is build_user_assertion
    assert public_nip85.build_event_assertion is build_event_assertion
    assert public_nip85.build_addressable_assertion is build_addressable_assertion
    assert public_nip85.build_identifier_assertion is build_identifier_assertion
    assert public_nip85.build_trusted_provider_list is build_trusted_provider_list
    assert public_nip85.build_provider_profile.__name__ == "build_profile_event"


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

    def test_constructor_accepts_list_activity_hours(self) -> None:
        a = UserAssertion(pubkey="aa" * 32, activity_hours=[0] * 24)
        assert a.activity_hours == tuple(0 for _ in range(24))

    def test_constructor_rejects_non_string_pubkey(self) -> None:
        with pytest.raises(TypeError, match="pubkey must be a string"):
            UserAssertion(pubkey=None)  # type: ignore[arg-type]

    def test_constructor_rejects_scalar_string_top_topics(self) -> None:
        with pytest.raises(
            TypeError,
            match="top_topics must be a sequence of topic strings, not a scalar string",
        ):
            UserAssertion(pubkey="aa" * 32, top_topics="nostr")  # type: ignore[arg-type]

    def test_constructor_rejects_non_string_top_topics(self) -> None:
        with pytest.raises(TypeError, match="top_topics must contain only strings"):
            UserAssertion(pubkey="aa" * 32, top_topics=(1, "nostr"))  # type: ignore[arg-type]

    def test_constructor_rejects_invalid_activity_hours_length(self) -> None:
        with pytest.raises(
            ValueError, match="activity_hours must contain exactly 24 hourly buckets"
        ):
            UserAssertion(pubkey="aa" * 32, activity_hours=(0,) * 23)

    def test_constructor_rejects_boolean_activity_hours(self) -> None:
        with pytest.raises(
            TypeError, match="activity_hours entries must be a non-negative integer"
        ):
            UserAssertion(pubkey="aa" * 32, activity_hours=(True,) * 24)

    def test_constructor_rejects_float_activity_hours(self) -> None:
        with pytest.raises(
            TypeError, match="activity_hours entries must be a non-negative integer"
        ):
            UserAssertion(pubkey="aa" * 32, activity_hours=(1.5,) * 24)  # type: ignore[arg-type]

    def test_constructor_rejects_negative_activity_hours(self) -> None:
        with pytest.raises(ValueError, match="activity_hours entries must be >= 0"):
            UserAssertion(pubkey="aa" * 32, activity_hours=(-1,) * 24)

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"score": True}, "score must be a non-negative integer"),
            ({"score": 101}, "score must be <= 100"),
            ({"follower_count": -1}, "follower_count must be >= 0"),
            (
                {"zap_amount_recd_msats": 1.5},
                "zap_amount_recd_msats must be a non-negative integer",
            ),
        ],
    )
    def test_constructor_rejects_invalid_metric_fields(
        self,
        kwargs: dict[str, object],
        message: str,
    ) -> None:
        with pytest.raises((TypeError, ValueError), match=message):
            UserAssertion(pubkey="aa" * 32, **kwargs)


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

    def test_from_db_row_rejects_non_string_pubkey(self) -> None:
        row = {"pubkey": None}
        with pytest.raises(TypeError, match="pubkey must be a string"):
            UserAssertion.from_db_row(row)

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

    def test_topic_count_ties_sort_lexicographically(self) -> None:
        """Equal topic counts should not inherit JSONB key order."""
        row = {
            "pubkey": "cc" * 32,
            "topic_counts": {"zebra": 5, "apple": 5, "nostr": 7, "beta": 5},
            "top_topics_limit": 4,
        }
        a = UserAssertion.from_db_row(row)
        assert a.top_topics == ("nostr", "apple", "beta", "zebra")

    def test_from_db_row_rejects_non_mapping_topic_counts(self) -> None:
        row = {
            "pubkey": "cc" * 32,
            "topic_counts": [],
        }
        with pytest.raises(
            TypeError, match="topic_counts must be a mapping of topic strings to counts"
        ):
            UserAssertion.from_db_row(row)

    def test_from_db_row_rejects_non_string_topic_count_keys(self) -> None:
        row = {
            "pubkey": "cc" * 32,
            "topic_counts": {1: 7},
        }
        with pytest.raises(TypeError, match="topic_counts keys must be strings"):
            UserAssertion.from_db_row(row)

    def test_from_db_row_rejects_boolean_topic_count_values(self) -> None:
        row = {
            "pubkey": "cc" * 32,
            "topic_counts": {"nostr": True},
        }
        with pytest.raises(TypeError, match="topic_counts values must be non-negative integers"):
            UserAssertion.from_db_row(row)

    def test_from_db_row_rejects_float_topic_count_values(self) -> None:
        row = {
            "pubkey": "cc" * 32,
            "topic_counts": {"nostr": 1.5},
        }
        with pytest.raises(TypeError, match="topic_counts values must be non-negative integers"):
            UserAssertion.from_db_row(row)

    def test_from_db_row_rejects_non_integer_top_topics_limit(self) -> None:
        row = {
            "pubkey": "cc" * 32,
            "topic_counts": {"nostr": 7},
            "top_topics_limit": None,
        }
        with pytest.raises(TypeError, match="top_topics_limit must be a non-negative integer"):
            UserAssertion.from_db_row(row)

    def test_from_db_row_rejects_negative_top_topics_limit(self) -> None:
        row = {
            "pubkey": "cc" * 32,
            "topic_counts": {"nostr": 7},
            "top_topics_limit": -1,
        }
        with pytest.raises(ValueError, match="top_topics_limit must be >= 0"):
            UserAssertion.from_db_row(row)

    def test_from_db_row_rejects_invalid_activity_hours_length(self) -> None:
        row = {
            "pubkey": "cc" * 32,
            "activity_hours": [0] * 23,
        }
        with pytest.raises(
            ValueError, match="activity_hours must contain exactly 24 hourly buckets"
        ):
            UserAssertion.from_db_row(row)

    def test_from_db_row_rejects_explicit_empty_activity_hours(self) -> None:
        row = {
            "pubkey": "cc" * 32,
            "activity_hours": [],
        }
        with pytest.raises(
            ValueError, match="activity_hours must contain exactly 24 hourly buckets"
        ):
            UserAssertion.from_db_row(row)

    def test_from_db_row_rejects_boolean_activity_hours(self) -> None:
        row = {
            "pubkey": "cc" * 32,
            "activity_hours": [True] * 24,
        }
        with pytest.raises(
            TypeError, match="activity_hours entries must be a non-negative integer"
        ):
            UserAssertion.from_db_row(row)

    def test_from_db_row_rejects_float_activity_hours(self) -> None:
        row = {
            "pubkey": "cc" * 32,
            "activity_hours": [1.5] * 24,
        }
        with pytest.raises(
            TypeError, match="activity_hours entries must be a non-negative integer"
        ):
            UserAssertion.from_db_row(row)

    def test_from_db_row_rejects_negative_activity_hours(self) -> None:
        row = {
            "pubkey": "cc" * 32,
            "activity_hours": [-1] * 24,
        }
        with pytest.raises(ValueError, match="activity_hours entries must be >= 0"):
            UserAssertion.from_db_row(row)

    @pytest.mark.parametrize(
        ("row", "message"),
        [
            ({"pubkey": "cc" * 32, "score": True}, "score must be a non-negative integer"),
            ({"pubkey": "cc" * 32, "score": 101}, "score must be <= 100"),
            ({"pubkey": "cc" * 32, "follower_count": -1}, "follower_count must be >= 0"),
            (
                {"pubkey": "cc" * 32, "zap_amount_recd": 1.5},
                "zap_amount_recd_msats must be a non-negative integer",
            ),
        ],
    )
    def test_from_db_row_rejects_invalid_metric_fields(
        self,
        row: dict[str, object],
        message: str,
    ) -> None:
        with pytest.raises((TypeError, ValueError), match=message):
            UserAssertion.from_db_row(row)


class TestEventAssertionProperties:
    def test_zap_amount_sats(self) -> None:
        a = EventAssertion(event_id="ee" * 32, zap_amount_msats=42000)
        assert a.zap_amount_sats == 42

    def test_constructor_rejects_non_string_event_id(self) -> None:
        with pytest.raises(TypeError, match="event_id must be a string"):
            EventAssertion(event_id=None)  # type: ignore[arg-type]

    def test_constructor_rejects_non_string_author_pubkey(self) -> None:
        with pytest.raises(TypeError, match="author_pubkey must be a string"):
            EventAssertion(event_id="ee" * 32, author_pubkey=None)  # type: ignore[arg-type]

    def test_tags_hash_stability(self) -> None:
        a = EventAssertion(event_id="ee" * 32, comment_count=5, reaction_count=10)
        h1 = a.tags_hash()
        h2 = a.tags_hash()
        assert h1 == h2

    def test_tags_hash_tracks_author_pubkey(self) -> None:
        a1 = EventAssertion(event_id="ee" * 32, author_pubkey="aa" * 32)
        a2 = EventAssertion(event_id="ee" * 32, author_pubkey="bb" * 32)
        assert a1.tags_hash() != a2.tags_hash()

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"score": True}, "score must be a non-negative integer"),
            ({"score": 101}, "score must be <= 100"),
            ({"comment_count": -1}, "comment_count must be >= 0"),
            ({"zap_amount_msats": 1.5}, "zap_amount_msats must be a non-negative integer"),
        ],
    )
    def test_constructor_rejects_invalid_metric_fields(
        self,
        kwargs: dict[str, object],
        message: str,
    ) -> None:
        with pytest.raises((TypeError, ValueError), match=message):
            EventAssertion(event_id="ee" * 32, **kwargs)


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

    def test_from_db_row_rejects_non_string_event_id(self) -> None:
        row = {
            "event_id": None,
            "author_pubkey": "aa" * 32,
        }
        with pytest.raises(TypeError, match="event_id must be a string"):
            EventAssertion.from_db_row(row)

    def test_from_db_row_rejects_non_string_author_pubkey(self) -> None:
        row = {
            "event_id": "ff" * 32,
            "author_pubkey": None,
        }
        with pytest.raises(TypeError, match="author_pubkey must be a string"):
            EventAssertion.from_db_row(row)

    @pytest.mark.parametrize(
        ("row", "message"),
        [
            ({"event_id": "ff" * 32, "score": True}, "score must be a non-negative integer"),
            ({"event_id": "ff" * 32, "score": 101}, "score must be <= 100"),
            ({"event_id": "ff" * 32, "comment_count": -1}, "comment_count must be >= 0"),
            (
                {"event_id": "ff" * 32, "zap_amount": 1.5},
                "zap_amount_msats must be a non-negative integer",
            ),
        ],
    )
    def test_from_db_row_rejects_invalid_metric_fields(
        self,
        row: dict[str, object],
        message: str,
    ) -> None:
        with pytest.raises((TypeError, ValueError), match=message):
            EventAssertion.from_db_row(row)


class TestAddressableAssertionProperties:
    def test_from_db_row_and_zap_amount_sats(self) -> None:
        row = {
            "event_address": "30023:" + ("aa" * 32) + ":article",
            "author_pubkey": "bb" * 32,
            "score": 84,
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
        assert a.score == 84
        assert a.zap_amount_sats == 100

    def test_constructor_rejects_non_string_event_address(self) -> None:
        with pytest.raises(TypeError, match="event_address must be a string"):
            AddressableAssertion(event_address=None)  # type: ignore[arg-type]

    def test_constructor_rejects_non_string_author_pubkey(self) -> None:
        with pytest.raises(TypeError, match="author_pubkey must be a string"):
            AddressableAssertion(
                event_address="30023:" + ("aa" * 32) + ":article",
                author_pubkey=None,  # type: ignore[arg-type]
            )

    def test_tags_hash_tracks_author_pubkey(self) -> None:
        a1 = AddressableAssertion(
            event_address="30023:" + ("aa" * 32) + ":article",
            author_pubkey="bb" * 32,
        )
        a2 = AddressableAssertion(
            event_address="30023:" + ("aa" * 32) + ":article",
            author_pubkey="cc" * 32,
        )
        assert a1.tags_hash() != a2.tags_hash()

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"score": True}, "score must be a non-negative integer"),
            ({"score": 101}, "score must be <= 100"),
            ({"reaction_count": -1}, "reaction_count must be >= 0"),
            ({"zap_amount_msats": 1.5}, "zap_amount_msats must be a non-negative integer"),
        ],
    )
    def test_constructor_rejects_invalid_metric_fields(
        self,
        kwargs: dict[str, object],
        message: str,
    ) -> None:
        with pytest.raises((TypeError, ValueError), match=message):
            AddressableAssertion(
                event_address="30023:" + ("aa" * 32) + ":article",
                **kwargs,
            )

    def test_from_db_row_rejects_non_string_author_pubkey(self) -> None:
        row = {
            "event_address": "30023:" + ("aa" * 32) + ":article",
            "author_pubkey": None,
        }
        with pytest.raises(TypeError, match="author_pubkey must be a string"):
            AddressableAssertion.from_db_row(row)

    def test_from_db_row_rejects_non_string_event_address(self) -> None:
        row = {
            "event_address": None,
            "author_pubkey": "bb" * 32,
        }
        with pytest.raises(TypeError, match="event_address must be a string"):
            AddressableAssertion.from_db_row(row)

    @pytest.mark.parametrize(
        ("row", "message"),
        [
            (
                {"event_address": "30023:" + ("aa" * 32) + ":article", "score": True},
                "score must be a non-negative integer",
            ),
            (
                {"event_address": "30023:" + ("aa" * 32) + ":article", "score": 101},
                "score must be <= 100",
            ),
            (
                {"event_address": "30023:" + ("aa" * 32) + ":article", "reaction_count": -1},
                "reaction_count must be >= 0",
            ),
            (
                {"event_address": "30023:" + ("aa" * 32) + ":article", "zap_amount": 1.5},
                "zap_amount_msats must be a non-negative integer",
            ),
        ],
    )
    def test_from_db_row_rejects_invalid_metric_fields(
        self,
        row: dict[str, object],
        message: str,
    ) -> None:
        with pytest.raises((TypeError, ValueError), match=message):
            AddressableAssertion.from_db_row(row)


class TestIdentifierAssertionProperties:
    def test_from_db_row_preserves_k_tags(self) -> None:
        row = {
            "identifier": "isbn:9780140328721",
            "score": 73,
            "comment_count": 3,
            "reaction_count": 4,
            "k_tags": ["book", "isbn"],
        }

        a = IdentifierAssertion.from_db_row(row)

        assert a.identifier == "isbn:9780140328721"
        assert a.score == 73
        assert a.k_tags == ("book", "isbn")

    def test_constructor_normalizes_k_tags(self) -> None:
        a = IdentifierAssertion(
            identifier="isbn:9780140328721",
            k_tags=("isbn", "book", "isbn"),
        )
        assert a.k_tags == ("book", "isbn")

    def test_constructor_rejects_non_string_identifier(self) -> None:
        with pytest.raises(TypeError, match="identifier must be a string"):
            IdentifierAssertion(identifier=None)  # type: ignore[arg-type]

    def test_from_db_row_normalizes_k_tags(self) -> None:
        row = {
            "identifier": "isbn:9780140328721",
            "k_tags": ["isbn", "book", "isbn"],
        }

        a = IdentifierAssertion.from_db_row(row)

        assert a.k_tags == ("book", "isbn")

    def test_constructor_rejects_scalar_string_k_tags(self) -> None:
        with pytest.raises(TypeError, match="k_tags must be a sequence of tag strings"):
            IdentifierAssertion(identifier="isbn:9780140328721", k_tags="isbn")  # type: ignore[arg-type]

    def test_constructor_rejects_non_string_k_tags(self) -> None:
        with pytest.raises(TypeError, match="k_tags must contain only strings"):
            IdentifierAssertion(
                identifier="isbn:9780140328721",
                k_tags=(1, "book"),  # type: ignore[arg-type]
            )

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"score": True}, "score must be a non-negative integer"),
            ({"score": 101}, "score must be <= 100"),
            ({"comment_count": -1}, "comment_count must be >= 0"),
            ({"reaction_count": 1.5}, "reaction_count must be a non-negative integer"),
        ],
    )
    def test_constructor_rejects_invalid_metric_fields(
        self,
        kwargs: dict[str, object],
        message: str,
    ) -> None:
        with pytest.raises((TypeError, ValueError), match=message):
            IdentifierAssertion(identifier="isbn:9780140328721", **kwargs)

    def test_from_db_row_rejects_scalar_string_k_tags(self) -> None:
        row = {
            "identifier": "isbn:9780140328721",
            "k_tags": "isbn",
        }

        with pytest.raises(TypeError, match="k_tags must be a sequence of tag strings"):
            IdentifierAssertion.from_db_row(row)

    def test_from_db_row_rejects_non_string_k_tags(self) -> None:
        row = {
            "identifier": "isbn:9780140328721",
            "k_tags": [1, "book"],
        }

        with pytest.raises(TypeError, match="k_tags must contain only strings"):
            IdentifierAssertion.from_db_row(row)

    def test_from_db_row_rejects_non_string_identifier(self) -> None:
        row = {
            "identifier": None,
        }

        with pytest.raises(TypeError, match="identifier must be a string"):
            IdentifierAssertion.from_db_row(row)

    @pytest.mark.parametrize(
        ("row", "message"),
        [
            (
                {"identifier": "isbn:9780140328721", "score": True},
                "score must be a non-negative integer",
            ),
            (
                {"identifier": "isbn:9780140328721", "score": 101},
                "score must be <= 100",
            ),
            (
                {"identifier": "isbn:9780140328721", "comment_count": -1},
                "comment_count must be >= 0",
            ),
            (
                {"identifier": "isbn:9780140328721", "reaction_count": 1.5},
                "reaction_count must be a non-negative integer",
            ),
        ],
    )
    def test_from_db_row_rejects_invalid_metric_fields(
        self,
        row: dict[str, object],
        message: str,
    ) -> None:
        with pytest.raises((TypeError, ValueError), match=message):
            IdentifierAssertion.from_db_row(row)


@pytest.mark.parametrize(
    ("factory", "row"),
    [
        (UserAssertion.from_db_row, {"pubkey": "aa" * 32, "rank": 77}),
        (EventAssertion.from_db_row, {"event_id": "bb" * 32, "rank": 77}),
        (
            AddressableAssertion.from_db_row,
            {"event_address": "30023:" + ("cc" * 32) + ":article", "rank": 77},
        ),
        (
            IdentifierAssertion.from_db_row,
            {"identifier": "isbn:9780140328721", "rank": 77},
        ),
    ],
)
def test_legacy_rank_alias_is_not_used_by_nip85_rows(
    factory: object,
    row: dict[str, object],
) -> None:
    assertion = factory(row)  # type: ignore[misc]
    assert assertion.score == 0


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

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            (
                {
                    "result_kind": "30382",
                    "tag_name": "rank",
                    "service_pubkey": "4f" * 32,
                    "relay_hint": "wss://nip85.nostr.band",
                },
                "result_kind must be a non-negative integer",
            ),
            (
                {
                    "result_kind": 30382,
                    "tag_name": None,
                    "service_pubkey": "4f" * 32,
                    "relay_hint": "wss://nip85.nostr.band",
                },
                "tag_name must be a string",
            ),
            (
                {
                    "result_kind": 30382,
                    "tag_name": "rank",
                    "service_pubkey": None,
                    "relay_hint": "wss://nip85.nostr.band",
                },
                "service_pubkey must be a string",
            ),
            (
                {
                    "result_kind": 30382,
                    "tag_name": "rank",
                    "service_pubkey": "4f" * 32,
                    "relay_hint": None,
                },
                "relay_hint must be a string",
            ),
        ],
    )
    def test_rejects_invalid_field_types(self, kwargs: dict[str, object], message: str) -> None:
        with pytest.raises(TypeError, match=message):
            TrustedProviderDeclaration(**kwargs)  # type: ignore[arg-type]


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
