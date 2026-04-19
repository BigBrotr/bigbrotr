"""Tests for NIP-85 assertion data models."""

from __future__ import annotations

import pytest

from bigbrotr.models.constants import EventKind
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

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"first_created_at": True}, "first_created_at must be a non-negative integer"),
            ({"last_event_at": 1.5}, "last_event_at must be a non-negative integer"),
            ({"first_created_at": -1}, "first_created_at must be >= 0"),
            (
                {"first_created_at": 200, "last_event_at": 100},
                "last_event_at must be >= first_created_at",
            ),
        ],
    )
    def test_constructor_rejects_invalid_timestamps(
        self,
        kwargs: dict[str, object],
        message: str,
    ) -> None:
        with pytest.raises((TypeError, ValueError), match=message):
            UserAssertion(pubkey="aa" * 32, **kwargs)

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

    def test_constructor_rejects_empty_pubkey(self) -> None:
        with pytest.raises(ValueError, match="pubkey must not be empty"):
            UserAssertion(pubkey="")

    def test_constructor_normalizes_hex_pubkey(self) -> None:
        assert UserAssertion(pubkey="AA" * 32).pubkey == "aa" * 32

    def test_constructor_rejects_malformed_pubkey(self) -> None:
        with pytest.raises(ValueError, match="pubkey must be a 64-character hex string"):
            UserAssertion(pubkey="abc")

    def test_constructor_rejects_scalar_string_top_topics(self) -> None:
        with pytest.raises(
            TypeError,
            match="top_topics must be a sequence of topic strings, not a scalar string",
        ):
            UserAssertion(pubkey="aa" * 32, top_topics="nostr")  # type: ignore[arg-type]

    def test_constructor_rejects_non_string_top_topics(self) -> None:
        with pytest.raises(TypeError, match="top_topics must contain only strings"):
            UserAssertion(pubkey="aa" * 32, top_topics=(1, "nostr"))  # type: ignore[arg-type]

    def test_constructor_rejects_empty_top_topics(self) -> None:
        with pytest.raises(ValueError, match="top_topics must not contain empty topic strings"):
            UserAssertion(pubkey="aa" * 32, top_topics=("nostr", ""))

    def test_constructor_rejects_duplicate_top_topics(self) -> None:
        with pytest.raises(ValueError, match="top_topics must not contain duplicate topics"):
            UserAssertion(pubkey="aa" * 32, top_topics=("nostr", "nostr"))

    def test_constructor_canonicalizes_top_topics_to_lowercase(self) -> None:
        assertion = UserAssertion(pubkey="aa" * 32, top_topics=("Bitcoin", "Nostr"))

        assert assertion.top_topics == ("bitcoin", "nostr")

    def test_constructor_rejects_case_only_duplicate_top_topics(self) -> None:
        with pytest.raises(ValueError, match="top_topics must not contain duplicate topics"):
            UserAssertion(pubkey="aa" * 32, top_topics=("Bitcoin", "bitcoin"))

    def test_constructor_rejects_mapping_top_topics(self) -> None:
        with pytest.raises(TypeError, match="top_topics must be a sequence of topic strings"):
            UserAssertion(pubkey="aa" * 32, top_topics={"nostr": 7})  # type: ignore[arg-type]

    def test_constructor_rejects_invalid_activity_hours_length(self) -> None:
        with pytest.raises(
            ValueError, match="activity_hours must contain exactly 24 hourly buckets"
        ):
            UserAssertion(pubkey="aa" * 32, activity_hours=(0,) * 23)

    def test_constructor_rejects_mapping_activity_hours(self) -> None:
        with pytest.raises(TypeError, match="activity_hours must be a sequence of hourly buckets"):
            UserAssertion(pubkey="aa" * 32, activity_hours=dict.fromkeys(range(24), 0))  # type: ignore[arg-type]

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

    def test_first_created_at_none_and_zero_produce_different_hashes(self) -> None:
        without_timestamp = UserAssertion(pubkey="aa" * 32)
        unix_epoch = UserAssertion(pubkey="aa" * 32, first_created_at=0)

        assert without_timestamp.tags_hash() != unix_epoch.tags_hash()

    def test_top_topics_with_delimiters_produce_distinct_hashes(self) -> None:
        with_comma = UserAssertion(pubkey="aa" * 32, top_topics=("alpha,beta", "gamma"))
        split_across_topics = UserAssertion(pubkey="aa" * 32, top_topics=("alpha", "beta,gamma"))

        assert with_comma.tags_hash() != split_across_topics.tags_hash()


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

    def test_from_db_row_rejects_empty_pubkey(self) -> None:
        with pytest.raises(ValueError, match="pubkey must not be empty"):
            UserAssertion.from_db_row({"pubkey": ""})

    def test_from_db_row_rejects_malformed_pubkey(self) -> None:
        with pytest.raises(ValueError, match="pubkey must be a 64-character hex string"):
            UserAssertion.from_db_row({"pubkey": "zz" * 32})

    def test_full_row(self) -> None:
        row = {
            "pubkey": "bb" * 32,
            "post_count": 100,
            "reply_count": 20,
            "reaction_count_recd": 50,
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
        }
        a = UserAssertion.from_db_row(row)
        assert a.post_count == 100
        assert a.zap_amount_recd_msats == 500000
        assert a.zap_amount_recd_sats == 500
        assert a.follower_count == 200
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

    def test_from_db_row_canonicalizes_topic_counts_to_lowercase(self) -> None:
        row = {
            "pubkey": "cc" * 32,
            "topic_counts": {"Bitcoin": 7, "Nostr": 5},
            "top_topics_limit": 2,
        }

        a = UserAssertion.from_db_row(row)

        assert a.top_topics == ("bitcoin", "nostr")

    def test_from_db_row_merges_case_variant_topic_counts_before_ranking(self) -> None:
        row = {
            "pubkey": "cc" * 32,
            "topic_counts": {"Bitcoin": 4, "bitcoin": 3, "nostr": 5},
            "top_topics_limit": 2,
        }

        a = UserAssertion.from_db_row(row)

        assert a.top_topics == ("bitcoin", "nostr")

    def test_from_db_row_rejects_non_mapping_topic_counts(self) -> None:
        row = {
            "pubkey": "cc" * 32,
            "topic_counts": [],
        }
        with pytest.raises(
            TypeError, match="topic_counts must be a mapping of topic strings to counts"
        ):
            UserAssertion.from_db_row(row)

    def test_from_db_row_rejects_duck_typed_topic_counts(self) -> None:
        class DuckTypedTopicCounts:
            def items(self) -> list[tuple[str, int]]:
                return [("nostr", 7)]

        row = {
            "pubkey": "cc" * 32,
            "topic_counts": DuckTypedTopicCounts(),
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

    def test_from_db_row_rejects_mapping_activity_hours(self) -> None:
        row = {
            "pubkey": "cc" * 32,
            "activity_hours": dict.fromkeys(range(24), 0),
        }
        with pytest.raises(TypeError, match="activity_hours must be a sequence of hourly buckets"):
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

    @pytest.mark.parametrize(
        ("row", "message"),
        [
            (
                {"pubkey": "cc" * 32, "first_created_at": True},
                "first_created_at must be a non-negative integer",
            ),
            (
                {"pubkey": "cc" * 32, "last_event_at": 1.5},
                "last_event_at must be a non-negative integer",
            ),
            (
                {"pubkey": "cc" * 32, "first_created_at": -1},
                "first_created_at must be >= 0",
            ),
            (
                {"pubkey": "cc" * 32, "first_created_at": 200, "last_event_at": 100},
                "last_event_at must be >= first_created_at",
            ),
        ],
    )
    def test_from_db_row_rejects_invalid_timestamps(
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

    def test_constructor_rejects_empty_event_id(self) -> None:
        with pytest.raises(ValueError, match="event_id must not be empty"):
            EventAssertion(event_id="")

    def test_constructor_normalizes_hex_event_id(self) -> None:
        assert EventAssertion(event_id="EE" * 32).event_id == "ee" * 32

    def test_constructor_rejects_malformed_event_id(self) -> None:
        with pytest.raises(ValueError, match="event_id must be a 64-character hex string"):
            EventAssertion(event_id="abc")

    def test_constructor_rejects_non_string_author_pubkey(self) -> None:
        with pytest.raises(TypeError, match="author_pubkey must be a string"):
            EventAssertion(event_id="ee" * 32, author_pubkey=None)  # type: ignore[arg-type]

    def test_constructor_rejects_malformed_author_pubkey(self) -> None:
        with pytest.raises(ValueError, match="author_pubkey must be a 64-character hex string"):
            EventAssertion(event_id="ee" * 32, author_pubkey="abc")

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

    def test_from_db_row_rejects_empty_event_id(self) -> None:
        with pytest.raises(ValueError, match="event_id must not be empty"):
            EventAssertion.from_db_row({"event_id": ""})

    def test_from_db_row_rejects_malformed_event_id(self) -> None:
        with pytest.raises(ValueError, match="event_id must be a 64-character hex string"):
            EventAssertion.from_db_row({"event_id": "zz" * 32})

    def test_from_db_row_rejects_non_string_author_pubkey(self) -> None:
        row = {
            "event_id": "ff" * 32,
            "author_pubkey": None,
        }
        with pytest.raises(TypeError, match="author_pubkey must be a string"):
            EventAssertion.from_db_row(row)

    def test_from_db_row_rejects_malformed_author_pubkey(self) -> None:
        with pytest.raises(ValueError, match="author_pubkey must be a 64-character hex string"):
            EventAssertion.from_db_row({"event_id": "ff" * 32, "author_pubkey": "zz" * 32})

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

    def test_constructor_rejects_empty_event_address(self) -> None:
        with pytest.raises(ValueError, match="event_address must not be empty"):
            AddressableAssertion(event_address="")

    def test_constructor_normalizes_event_address_pubkey(self) -> None:
        assertion = AddressableAssertion(event_address="30023:" + ("AA" * 32) + ":article")
        assert assertion.event_address == "30023:" + ("aa" * 32) + ":article"

    @pytest.mark.parametrize(
        ("event_address", "message"),
        [
            ("abc", "event_address must be a canonical kind:pubkey:d coordinate"),
            (
                "30023:" + ("aa" * 32) + ":",
                "event_address d value must not be empty",
            ),
            (
                "abc:" + ("aa" * 32) + ":article",
                "event_address kind must be a non-negative integer",
            ),
            (
                "030023:" + ("aa" * 32) + ":article",
                "event_address kind must be canonical",
            ),
            (
                "70000:" + ("aa" * 32) + ":article",
                "event_address kind must be <= 65535",
            ),
            (
                "1:" + ("aa" * 32) + ":article",
                "event_address kind must be a NIP-33 addressable kind",
            ),
            (
                "30023:abc:article",
                "event_address pubkey must be a 64-character hex string",
            ),
        ],
    )
    def test_constructor_rejects_malformed_event_address(
        self,
        event_address: str,
        message: str,
    ) -> None:
        with pytest.raises(ValueError, match=message):
            AddressableAssertion(event_address=event_address)

    def test_constructor_rejects_non_string_author_pubkey(self) -> None:
        with pytest.raises(TypeError, match="author_pubkey must be a string"):
            AddressableAssertion(
                event_address="30023:" + ("aa" * 32) + ":article",
                author_pubkey=None,  # type: ignore[arg-type]
            )

    def test_constructor_rejects_malformed_author_pubkey(self) -> None:
        with pytest.raises(ValueError, match="author_pubkey must be a 64-character hex string"):
            AddressableAssertion(
                event_address="30023:" + ("aa" * 32) + ":article",
                author_pubkey="abc",
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

    def test_from_db_row_rejects_malformed_author_pubkey(self) -> None:
        with pytest.raises(ValueError, match="author_pubkey must be a 64-character hex string"):
            AddressableAssertion.from_db_row(
                {
                    "event_address": "30023:" + ("aa" * 32) + ":article",
                    "author_pubkey": "zz" * 32,
                }
            )

    def test_from_db_row_rejects_non_string_event_address(self) -> None:
        row = {
            "event_address": None,
            "author_pubkey": "bb" * 32,
        }
        with pytest.raises(TypeError, match="event_address must be a string"):
            AddressableAssertion.from_db_row(row)

    def test_from_db_row_rejects_empty_event_address(self) -> None:
        with pytest.raises(ValueError, match="event_address must not be empty"):
            AddressableAssertion.from_db_row({"event_address": ""})

    @pytest.mark.parametrize(
        ("row", "message"),
        [
            (
                {"event_address": "abc"},
                "event_address must be a canonical kind:pubkey:d coordinate",
            ),
            (
                {"event_address": "30023:" + ("aa" * 32) + ":"},
                "event_address d value must not be empty",
            ),
            (
                {"event_address": "abc:" + ("aa" * 32) + ":article"},
                "event_address kind must be a non-negative integer",
            ),
            (
                {"event_address": "030023:" + ("aa" * 32) + ":article"},
                "event_address kind must be canonical",
            ),
            (
                {"event_address": "1:" + ("aa" * 32) + ":article"},
                "event_address kind must be a NIP-33 addressable kind",
            ),
            (
                {"event_address": "30023:" + ("zz" * 32) + ":article"},
                "event_address pubkey must be a 64-character hex string",
            ),
        ],
    )
    def test_from_db_row_rejects_malformed_event_address(
        self,
        row: dict[str, object],
        message: str,
    ) -> None:
        with pytest.raises(ValueError, match=message):
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

    def test_constructor_rejects_empty_identifier(self) -> None:
        with pytest.raises(ValueError, match="identifier must not be empty"):
            IdentifierAssertion(identifier="")

    @pytest.mark.parametrize(
        ("identifier", "message"),
        [
            ("isbn", "identifier must be a canonical NIP-73 scheme:value string"),
            (":9780140328721", "identifier scheme must not be empty"),
            ("isbn:", "identifier value must not be empty"),
        ],
    )
    def test_constructor_rejects_malformed_identifier(
        self,
        identifier: str,
        message: str,
    ) -> None:
        with pytest.raises(ValueError, match=message):
            IdentifierAssertion(identifier=identifier)

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

    def test_constructor_rejects_mapping_k_tags(self) -> None:
        with pytest.raises(TypeError, match="k_tags must be a sequence of tag strings"):
            IdentifierAssertion(
                identifier="isbn:9780140328721",
                k_tags={"isbn": "book"},  # type: ignore[arg-type]
            )

    def test_constructor_rejects_non_string_k_tags(self) -> None:
        with pytest.raises(TypeError, match="k_tags must contain only strings"):
            IdentifierAssertion(
                identifier="isbn:9780140328721",
                k_tags=(1, "book"),  # type: ignore[arg-type]
            )

    def test_constructor_rejects_empty_k_tags(self) -> None:
        with pytest.raises(ValueError, match="k_tags must not contain empty tag strings"):
            IdentifierAssertion(identifier="isbn:9780140328721", k_tags=("isbn", ""))

    def test_tags_hash_distinguishes_delimited_k_tags(self) -> None:
        with_comma = IdentifierAssertion(
            identifier="isbn:9780140328721",
            k_tags=("a,b", "c"),
        )
        split_across_tags = IdentifierAssertion(
            identifier="isbn:9780140328721",
            k_tags=("a", "b,c"),
        )

        assert with_comma.tags_hash() != split_across_tags.tags_hash()

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

    def test_from_db_row_rejects_mapping_k_tags(self) -> None:
        row = {
            "identifier": "isbn:9780140328721",
            "k_tags": {"isbn": "book"},
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

    def test_from_db_row_rejects_empty_k_tags(self) -> None:
        row = {
            "identifier": "isbn:9780140328721",
            "k_tags": ["isbn", ""],
        }

        with pytest.raises(ValueError, match="k_tags must not contain empty tag strings"):
            IdentifierAssertion.from_db_row(row)

    def test_from_db_row_rejects_non_string_identifier(self) -> None:
        row = {
            "identifier": None,
        }

        with pytest.raises(TypeError, match="identifier must be a string"):
            IdentifierAssertion.from_db_row(row)

    def test_from_db_row_rejects_empty_identifier(self) -> None:
        with pytest.raises(ValueError, match="identifier must not be empty"):
            IdentifierAssertion.from_db_row({"identifier": ""})

    @pytest.mark.parametrize(
        ("row", "message"),
        [
            (
                {"identifier": "isbn"},
                "identifier must be a canonical NIP-73 scheme:value string",
            ),
            (
                {"identifier": ":9780140328721"},
                "identifier scheme must not be empty",
            ),
            (
                {"identifier": "isbn:"},
                "identifier value must not be empty",
            ),
        ],
    )
    def test_from_db_row_rejects_malformed_identifier(
        self,
        row: dict[str, object],
        message: str,
    ) -> None:
        with pytest.raises(ValueError, match=message):
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
            result_kind=EventKind.NIP85_USER_ASSERTION,
            tag_name=" rank ",
            service_pubkey="4F" * 32,
            relay_hint="wss://nip85.nostr.band:443",
        )

        assert declaration.kind_tag == "30382:rank"
        assert declaration.tag_name == "rank"
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
                    "tag_name": "30382:rank",
                    "service_pubkey": "4f" * 32,
                    "relay_hint": "wss://nip85.nostr.band",
                },
                "tag_name must not contain ':'",
            ),
            (
                {
                    "result_kind": 1,
                    "tag_name": "rank",
                    "service_pubkey": "4f" * 32,
                    "relay_hint": "wss://nip85.nostr.band",
                },
                "result_kind must be a supported NIP-85 assertion kind",
            ),
            (
                {
                    "result_kind": 30382,
                    "tag_name": "",
                    "service_pubkey": "4f" * 32,
                    "relay_hint": "wss://nip85.nostr.band",
                },
                "tag_name must not be empty",
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
                    "service_pubkey": "xyz",
                    "relay_hint": "wss://nip85.nostr.band",
                },
                "service_pubkey must be a 64-character hex string",
            ),
            (
                {
                    "result_kind": 30382,
                    "tag_name": "rank",
                    "service_pubkey": "",
                    "relay_hint": "wss://nip85.nostr.band",
                },
                "service_pubkey must not be empty",
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
                    "relay_hint": "not-a-relay",
                },
                "relay_hint must be a valid relay URL",
            ),
            (
                {
                    "result_kind": 30382,
                    "tag_name": "rank",
                    "service_pubkey": "4f" * 32,
                    "relay_hint": "",
                },
                "relay_hint must not be empty",
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
        with pytest.raises((TypeError, ValueError), match=message):
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
