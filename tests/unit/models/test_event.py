"""Unit tests for the Event model."""

import json
from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock

import pytest
from nostr_sdk import Event as NostrEvent

from bigbrotr.models.event import Event, EventDbParams


# =============================================================================
# Fixtures
# =============================================================================


def _make_mock_nostr_event(
    *,
    event_id: str = "a" * 64,
    author: str = "b" * 64,
    created_at: int = 1700000000,
    kind: int = 1,
    tags: list[list[str]] | None = None,
    content: str = "Hello, Nostr!",
    sig: str = "e" * 128,
) -> MagicMock:
    """Create a mock nostr_sdk.Event with all method chains configured."""
    mock = MagicMock(spec=NostrEvent)

    mock_id = MagicMock()
    mock_id.to_hex.return_value = event_id
    mock.id.return_value = mock_id

    mock_author = MagicMock()
    mock_author.to_hex.return_value = author
    mock.author.return_value = mock_author

    mock_created_at = MagicMock()
    mock_created_at.as_secs.return_value = created_at
    mock.created_at.return_value = mock_created_at

    mock_kind = MagicMock()
    mock_kind.as_u16.return_value = kind
    mock.kind.return_value = mock_kind

    if tags is None:
        tags = [["e", "c" * 64], ["p", "d" * 64]]
    mock_tags_list = []
    for tag in tags:
        mock_tag = MagicMock()
        mock_tag.as_vec.return_value = tag
        mock_tags_list.append(mock_tag)
    mock_tags = MagicMock()
    mock_tags.to_vec.return_value = mock_tags_list
    mock.tags.return_value = mock_tags

    mock.content.return_value = content
    mock.signature.return_value = sig

    return mock


@pytest.fixture
def mock_nostr_event():
    return _make_mock_nostr_event()


@pytest.fixture
def mock_nostr_event_empty_tags():
    return _make_mock_nostr_event(
        event_id="f" * 64,
        author="1" * 64,
        created_at=1700000001,
        kind=0,
        tags=[],
        content="",
        sig="2" * 128,
    )


@pytest.fixture
def event(mock_nostr_event):
    return Event(mock_nostr_event)


# =============================================================================
# Construction Tests
# =============================================================================


class TestConstruction:
    """Event construction and field extraction."""

    def test_construction_extracts_id(self, mock_nostr_event):
        event = Event(mock_nostr_event)
        assert event.id == "a" * 64

    def test_construction_extracts_pubkey(self, mock_nostr_event):
        event = Event(mock_nostr_event)
        assert event.pubkey == "b" * 64

    def test_construction_extracts_created_at(self, mock_nostr_event):
        event = Event(mock_nostr_event)
        assert event.created_at == 1700000000

    def test_construction_extracts_kind(self, mock_nostr_event):
        event = Event(mock_nostr_event)
        assert event.kind == 1

    def test_construction_extracts_content(self, mock_nostr_event):
        event = Event(mock_nostr_event)
        assert event.content == "Hello, Nostr!"

    def test_construction_extracts_sig(self, mock_nostr_event):
        event = Event(mock_nostr_event)
        assert event.sig == "e" * 128

    def test_construction_extracts_tags(self, mock_nostr_event):
        event = Event(mock_nostr_event)
        assert event.tags == (("e", "c" * 64), ("p", "d" * 64))

    def test_construction_does_not_retain_ffi_reference(self, mock_nostr_event):
        """InitVar means _nostr_event is not stored as a field."""
        event = Event(mock_nostr_event)
        assert not hasattr(event, "_nostr_event")


# =============================================================================
# Null Byte Validation Tests
# =============================================================================


class TestNullByteValidation:
    """Rejection of events with null bytes in content or tags."""

    def test_rejects_content_with_null_byte(self):
        mock = _make_mock_nostr_event(content="Hello\x00World")
        with pytest.raises(ValueError, match="content contains null bytes"):
            Event(mock)

    def test_rejects_tags_with_null_byte(self):
        mock = _make_mock_nostr_event(tags=[["t", "tag\x00value"]])
        with pytest.raises(ValueError, match="tags contain null bytes"):
            Event(mock)

    def test_accepts_content_without_null_byte(self, event):
        assert event.content == "Hello, Nostr!"

    def test_error_message_includes_event_id(self):
        mock = _make_mock_nostr_event(content="Bad\x00Content")
        with pytest.raises(ValueError) as exc_info:
            Event(mock)
        assert "aaaaaaaaaaaaaaaa" in str(exc_info.value)

    def test_rejects_tag_value_exceeding_max_length(self):
        long_value = "a" * (Event._MAX_TAG_VALUE_LENGTH + 1)
        mock = _make_mock_nostr_event(tags=[["r", long_value]])
        with pytest.raises(ValueError, match="tag value exceeds"):
            Event(mock)

    def test_accepts_tag_value_at_max_length(self):
        value = "a" * Event._MAX_TAG_VALUE_LENGTH
        mock = _make_mock_nostr_event(tags=[["r", value]])
        Event(mock)


# =============================================================================
# Immutability Tests
# =============================================================================


class TestImmutability:
    """Frozen dataclass behavior."""

    def test_attribute_mutation_blocked(self, event):
        with pytest.raises(FrozenInstanceError):
            event.id = "new_id"

    def test_attribute_deletion_blocked(self, event):
        with pytest.raises(FrozenInstanceError):
            del event.id


# =============================================================================
# Slots Tests
# =============================================================================


class TestSlots:
    """__slots__ definition for memory efficiency."""

    def test_has_slots(self):
        assert hasattr(Event, "__slots__")

    def test_domain_fields_in_slots(self):
        for field_name in ("id", "pubkey", "created_at", "kind", "tags", "content", "sig"):
            assert field_name in Event.__slots__

    def test_no_instance_dict(self):
        assert "__dict__" not in dir(Event)

    def test_no_nostr_event_slot(self):
        assert "_nostr_event" not in Event.__slots__


# =============================================================================
# to_db_params Tests
# =============================================================================


class TestToDbParams:
    """Event.to_db_params() serialization."""

    def test_returns_event_db_params(self, event):
        result = event.to_db_params()
        assert isinstance(result, EventDbParams)
        assert isinstance(result, tuple)
        assert len(result) == 7

    def test_id_is_32_bytes(self, event):
        result = event.to_db_params()
        assert isinstance(result.id, bytes)
        assert len(result.id) == 32
        assert result.id == bytes.fromhex("a" * 64)

    def test_pubkey_is_32_bytes(self, event):
        result = event.to_db_params()
        assert isinstance(result.pubkey, bytes)
        assert len(result.pubkey) == 32
        assert result.pubkey == bytes.fromhex("b" * 64)

    def test_created_at_is_int(self, event):
        result = event.to_db_params()
        assert isinstance(result.created_at, int)
        assert result.created_at == 1700000000

    def test_kind_is_int(self, event):
        result = event.to_db_params()
        assert isinstance(result.kind, int)
        assert result.kind == 1

    def test_tags_is_valid_json(self, event):
        result = event.to_db_params()
        assert isinstance(result.tags, str)
        parsed = json.loads(result.tags)
        assert isinstance(parsed, list)
        assert parsed == [["e", "c" * 64], ["p", "d" * 64]]

    def test_content_is_string(self, event):
        result = event.to_db_params()
        assert isinstance(result.content, str)
        assert result.content == "Hello, Nostr!"

    def test_sig_is_64_bytes(self, event):
        result = event.to_db_params()
        assert isinstance(result.sig, bytes)
        assert len(result.sig) == 64
        assert result.sig == bytes.fromhex("e" * 128)

    def test_empty_tags(self, mock_nostr_event_empty_tags):
        event = Event(mock_nostr_event_empty_tags)
        result = event.to_db_params()
        assert result.tags == "[]"

    def test_empty_content(self, mock_nostr_event_empty_tags):
        event = Event(mock_nostr_event_empty_tags)
        result = event.to_db_params()
        assert result.content == ""

    def test_kind_zero(self, mock_nostr_event_empty_tags):
        event = Event(mock_nostr_event_empty_tags)
        result = event.to_db_params()
        assert result.kind == 0

    def test_caching(self, event):
        assert event.to_db_params() is event.to_db_params()


# =============================================================================
# Edge Cases Tests
# =============================================================================


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_large_content(self):
        mock = _make_mock_nostr_event(content="x" * 100000)
        event = Event(mock)
        assert event.content == "x" * 100000

    def test_unicode_content(self):
        mock = _make_mock_nostr_event(content="Hello World")
        event = Event(mock)
        assert event.content == "Hello World"

    def test_many_tags(self):
        tags = [["t", f"tag{i}"] for i in range(100)]
        mock = _make_mock_nostr_event(tags=tags, content="Test")
        event = Event(mock)
        assert len(event.tags) == 100
        assert event.tags[0] == ("t", "tag0")
        assert event.tags[99] == ("t", "tag99")

    def test_complex_nested_tags(self):
        mock = _make_mock_nostr_event(tags=[["a", "b", "c", "d", "e"]], content="Test")
        event = Event(mock)
        assert event.tags == (("a", "b", "c", "d", "e"),)

    def test_tags_are_immutable_tuples(self):
        mock = _make_mock_nostr_event(tags=[["e", "test"]])
        event = Event(mock)
        assert isinstance(event.tags, tuple)
        assert isinstance(event.tags[0], tuple)


# =============================================================================
# Equality Tests
# =============================================================================


class TestEquality:
    """Equality behavior based on domain fields."""

    def test_same_data_equal(self, mock_nostr_event):
        event1 = Event(mock_nostr_event)
        event2 = Event(mock_nostr_event)
        assert event1 == event2

    def test_different_data_not_equal(self, mock_nostr_event, mock_nostr_event_empty_tags):
        event1 = Event(mock_nostr_event)
        event2 = Event(mock_nostr_event_empty_tags)
        assert event1 != event2

    def test_hashable(self, mock_nostr_event):
        event = Event(mock_nostr_event)
        assert hash(event) == hash(event)

    def test_same_data_same_hash(self, mock_nostr_event):
        event1 = Event(mock_nostr_event)
        event2 = Event(mock_nostr_event)
        assert hash(event1) == hash(event2)


# =============================================================================
# Repr Tests
# =============================================================================


class TestRepr:
    """String representation."""

    def test_repr_contains_id(self, event):
        assert "a" * 64 in repr(event)

    def test_repr_contains_kind(self, event):
        assert "kind=1" in repr(event)

    def test_repr_contains_created_at(self, event):
        assert "1700000000" in repr(event)


# =============================================================================
# Type Validation Tests
# =============================================================================


class TestTypeValidation:
    """Runtime type validation in __post_init__."""

    def test_non_nostr_event_rejected(self):
        with pytest.raises(TypeError, match="event must be an Event"):
            Event("not an event")  # type: ignore[arg-type]

    def test_none_rejected(self):
        with pytest.raises(TypeError, match="event must be an Event"):
            Event(None)  # type: ignore[arg-type]

    def test_dict_rejected(self):
        with pytest.raises(TypeError, match="event must be an Event"):
            Event({"id": "abc"})  # type: ignore[arg-type]
