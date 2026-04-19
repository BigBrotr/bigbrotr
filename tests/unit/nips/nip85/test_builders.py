"""Tests for NIP-85 event builder functions."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

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
)


def _extract_tag_vectors(builder: Any) -> list[list[str]]:
    """Extract raw tag vectors from an EventBuilder."""
    from nostr_sdk import Keys

    event = builder.sign_with_keys(Keys.generate())
    return [tag.as_vec() for tag in event.tags().to_vec()]


def _extract_tags(builder: Any) -> dict[str, list[str]]:
    """Build a tag lookup from an EventBuilder (uses nostr_sdk internals)."""
    result: dict[str, list[str]] = {}
    for vec in _extract_tag_vectors(builder):
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
        a = UserAssertion(pubkey="aa" * 32, top_topics=("  Bitcoin  ", "\tNostr "))
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
            score=89,
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

    @pytest.mark.parametrize("value", [True, "aa" * 32, object()])
    def test_rejects_invalid_user_assertion_before_tag_build(self, value: object) -> None:
        with (
            patch("bigbrotr.nips.event_builders.Tag.identifier") as mock_identifier,
            patch("bigbrotr.nips.event_builders.Tag.parse") as mock_parse,
            patch("bigbrotr.nips.event_builders.EventBuilder") as mock_builder,
            pytest.raises(ValueError, match="assertion must be a UserAssertion"),
        ):
            build_user_assertion(value)  # type: ignore[arg-type]

        mock_identifier.assert_not_called()
        mock_parse.assert_not_called()
        mock_builder.assert_not_called()


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
        a = EventAssertion(event_id="ff" * 32, score=91)
        tags = _extract_tags(build_event_assertion(a))
        assert tags["rank"] == ["91"]

    def test_author_pubkey_is_emitted_as_p_tag(self) -> None:
        author_pubkey = "ab" * 32
        a = EventAssertion(event_id="ff" * 32, author_pubkey=author_pubkey)
        tags = _extract_tags(build_event_assertion(a))
        assert tags["p"] == [author_pubkey]

    def test_zap_amount_in_sats(self) -> None:
        a = EventAssertion(event_id="ee" * 32, zap_amount_msats=42000)
        tags = _extract_tags(build_event_assertion(a))
        assert tags["zap_amount"] == ["42"]

    def test_all_nip85_tags_present(self) -> None:
        a = EventAssertion(
            event_id="ee" * 32,
            author_pubkey="ab" * 32,
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
            "p",
            "rank",
            "comment_cnt",
            "quote_cnt",
            "repost_cnt",
            "reaction_cnt",
            "zap_cnt",
            "zap_amount",
        }
        assert expected_keys.issubset(set(tags.keys()))

    @pytest.mark.parametrize("value", [True, "ee" * 32, object()])
    def test_rejects_invalid_event_assertion_before_tag_build(self, value: object) -> None:
        with (
            patch("bigbrotr.nips.event_builders.Tag.identifier") as mock_identifier,
            patch("bigbrotr.nips.event_builders.Tag.parse") as mock_parse,
            patch("bigbrotr.nips.event_builders.EventBuilder") as mock_builder,
            pytest.raises(ValueError, match="assertion must be an EventAssertion"),
        ):
            build_event_assertion(value)  # type: ignore[arg-type]

        mock_identifier.assert_not_called()
        mock_parse.assert_not_called()
        mock_builder.assert_not_called()


class TestBuildAddressableAssertion:
    def test_kind(self) -> None:
        a = AddressableAssertion(event_address="30023:" + ("aa" * 32) + ":article")
        from nostr_sdk import Keys

        event = build_addressable_assertion(a).sign_with_keys(Keys.generate())
        assert event.kind().as_u16() == EventKind.NIP85_ADDRESSABLE_ASSERTION

    def test_d_and_a_tags_use_event_address(self) -> None:
        event_address = "30023:" + ("ff" * 32) + ":article"
        author_pubkey = "cd" * 32
        a = AddressableAssertion(
            event_address=event_address,
            author_pubkey=author_pubkey,
            score=77,
        )
        tags = _extract_tags(build_addressable_assertion(a))
        assert tags["d"] == [event_address]
        assert tags["a"] == [event_address]
        assert tags["p"] == [author_pubkey]
        assert tags["rank"] == ["77"]

    def test_all_nip85_tags_present(self) -> None:
        a = AddressableAssertion(
            event_address="30023:" + ("aa" * 32) + ":alpha",
            author_pubkey="cd" * 32,
            score=88,
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
            "p",
            "rank",
            "comment_cnt",
            "quote_cnt",
            "repost_cnt",
            "reaction_cnt",
            "zap_cnt",
            "zap_amount",
        }
        assert expected_keys.issubset(set(tags.keys()))

    @pytest.mark.parametrize("value", [True, "30023:" + ("aa" * 32) + ":article", object()])
    def test_rejects_invalid_addressable_assertion_before_tag_build(self, value: object) -> None:
        with (
            patch("bigbrotr.nips.event_builders.Tag.identifier") as mock_identifier,
            patch("bigbrotr.nips.event_builders.Tag.parse") as mock_parse,
            patch("bigbrotr.nips.event_builders.EventBuilder") as mock_builder,
            pytest.raises(ValueError, match="assertion must be an AddressableAssertion"),
        ):
            build_addressable_assertion(value)  # type: ignore[arg-type]

        mock_identifier.assert_not_called()
        mock_parse.assert_not_called()
        mock_builder.assert_not_called()


class TestBuildIdentifierAssertion:
    def test_kind(self) -> None:
        a = IdentifierAssertion(identifier="isbn:9780140328721")
        from nostr_sdk import Keys

        event = build_identifier_assertion(a).sign_with_keys(Keys.generate())
        assert event.kind().as_u16() == EventKind.NIP85_IDENTIFIER_ASSERTION

    def test_d_i_and_k_tags_included(self) -> None:
        a = IdentifierAssertion(
            identifier="isbn:9780140328721",
            score=55,
            comment_count=3,
            reaction_count=4,
            k_tags=("book", "isbn"),
        )
        tags = _extract_tags(build_identifier_assertion(a))
        assert tags["d"] == ["isbn:9780140328721"]
        assert tags["i"] == ["isbn:9780140328721"]
        assert tags["rank"] == ["55"]
        assert sorted(tags["k"]) == ["book", "isbn"]

    def test_identifier_assertion_normalizes_k_tag_order_before_build(self) -> None:
        a = IdentifierAssertion(
            identifier="isbn:9780140328721",
            k_tags=("isbn", "book", "isbn"),
        )
        tags = _extract_tag_vectors(build_identifier_assertion(a))
        assert ["k", "book"] in tags
        assert ["k", "isbn"] in tags
        assert tags.count(["k", "isbn"]) == 1

    @pytest.mark.parametrize("value", [True, "isbn:9780140328721", object()])
    def test_rejects_invalid_identifier_assertion_before_tag_build(self, value: object) -> None:
        with (
            patch("bigbrotr.nips.event_builders.Tag.identifier") as mock_identifier,
            patch("bigbrotr.nips.event_builders.Tag.parse") as mock_parse,
            patch("bigbrotr.nips.event_builders.EventBuilder") as mock_builder,
            pytest.raises(ValueError, match="assertion must be an IdentifierAssertion"),
        ):
            build_identifier_assertion(value)  # type: ignore[arg-type]

        mock_identifier.assert_not_called()
        mock_parse.assert_not_called()
        mock_builder.assert_not_called()


class TestBuildTrustedProviderList:
    def test_kind_public_tag_and_content(self) -> None:
        from nostr_sdk import Keys

        provider_pubkey = "4f" * 32
        relay = "wss://nip85.nostr.band"
        declaration = TrustedProviderDeclaration(
            result_kind=EventKind.NIP85_USER_ASSERTION,
            tag_name="rank",
            service_pubkey=provider_pubkey,
            relay_hint=relay,
        )

        builder = build_trusted_provider_list([declaration], content="encrypted-private-tags")
        event = builder.sign_with_keys(Keys.generate())

        assert event.kind().as_u16() == EventKind.NIP85_TRUSTED_PROVIDER_LIST
        assert event.content() == "encrypted-private-tags"
        assert [f"{EventKind.NIP85_USER_ASSERTION}:rank", provider_pubkey, relay] in [
            list(tag.as_vec()) for tag in event.tags().to_vec()
        ]

    def test_private_only_provider_list_can_have_no_public_tags(self) -> None:
        builder = build_trusted_provider_list([], content="nip44-ciphertext")

        assert _extract_tag_vectors(builder) == []

    def test_normalizes_public_declaration_order_and_duplicates(self) -> None:
        declaration_b = TrustedProviderDeclaration(
            result_kind=EventKind.NIP85_EVENT_ASSERTION,
            tag_name="rank",
            service_pubkey="5f" * 32,
            relay_hint="wss://b.example.com",
        )
        declaration_a = TrustedProviderDeclaration(
            result_kind=EventKind.NIP85_USER_ASSERTION,
            tag_name="rank",
            service_pubkey="4f" * 32,
            relay_hint="wss://a.example.com",
        )

        tag_vecs = _extract_tag_vectors(
            build_trusted_provider_list(
                [declaration_b, declaration_a, declaration_b],
                content="encrypted-private-tags",
            )
        )

        assert tag_vecs == [
            [f"{EventKind.NIP85_USER_ASSERTION}:rank", "4f" * 32, "wss://a.example.com"],
            [f"{EventKind.NIP85_EVENT_ASSERTION}:rank", "5f" * 32, "wss://b.example.com"],
        ]

    @pytest.mark.parametrize("value", [True, 1, b"ciphertext"])
    def test_rejects_non_string_content_before_event_builder(self, value: object) -> None:
        with (
            patch("bigbrotr.nips.event_builders.EventBuilder") as mock_builder,
            pytest.raises(ValueError, match="content must be a string"),
        ):
            build_trusted_provider_list([], content=value)  # type: ignore[arg-type]

        mock_builder.assert_not_called()

    @pytest.mark.parametrize("value", [True, "not-a-sequence", {"rank": "value"}])
    def test_rejects_invalid_declarations_container_before_tag_build(self, value: object) -> None:
        with (
            patch("bigbrotr.nips.event_builders.Tag.parse") as mock_parse,
            patch("bigbrotr.nips.event_builders.EventBuilder") as mock_builder,
            pytest.raises(
                ValueError,
                match="declarations must be an iterable of TrustedProviderDeclaration",
            ),
        ):
            build_trusted_provider_list(value, content="encrypted-private-tags")  # type: ignore[arg-type]

        mock_parse.assert_not_called()
        mock_builder.assert_not_called()

    @pytest.mark.parametrize("value", [[True], [object()]])
    def test_rejects_invalid_declaration_items_before_tag_build(self, value: object) -> None:
        with (
            patch("bigbrotr.nips.event_builders.Tag.parse") as mock_parse,
            patch("bigbrotr.nips.event_builders.EventBuilder") as mock_builder,
            pytest.raises(
                ValueError,
                match="declarations must contain only TrustedProviderDeclaration items",
            ),
        ):
            build_trusted_provider_list(value, content="encrypted-private-tags")  # type: ignore[arg-type]

        mock_parse.assert_not_called()
        mock_builder.assert_not_called()

    def test_rejects_duck_typed_declaration_items_before_tag_build(self) -> None:
        class DuckTypedDeclaration:
            result_kind = int(EventKind.NIP85_USER_ASSERTION)
            tag_name = "rank"
            service_pubkey = "4f" * 32
            relay_hint = "wss://fake.example.com"

            def as_tag(self) -> list[str]:
                return [
                    f"{EventKind.NIP85_USER_ASSERTION}:rank",
                    self.service_pubkey,
                    self.relay_hint,
                ]

        with (
            patch("bigbrotr.nips.event_builders.Tag.parse") as mock_parse,
            patch("bigbrotr.nips.event_builders.EventBuilder") as mock_builder,
            pytest.raises(
                ValueError,
                match="declarations must contain only TrustedProviderDeclaration items",
            ),
        ):
            build_trusted_provider_list(
                [DuckTypedDeclaration()],
                content="encrypted-private-tags",
            )

        mock_parse.assert_not_called()
        mock_builder.assert_not_called()
