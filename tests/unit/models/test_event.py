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


@pytest.fixture
def mock_nostr_event():
    """Create a mock nostr_sdk.Event with all method chains configured."""
    mock = MagicMock(spec=NostrEvent)

    mock_id = MagicMock()
    mock_id.to_hex.return_value = "a" * 64
    mock.id.return_value = mock_id

    mock_author = MagicMock()
    mock_author.to_hex.return_value = "b" * 64
    mock.author.return_value = mock_author

    mock_created_at = MagicMock()
    mock_created_at.as_secs.return_value = 1700000000
    mock.created_at.return_value = mock_created_at

    mock_kind = MagicMock()
    mock_kind.as_u16.return_value = 1
    mock.kind.return_value = mock_kind

    mock_tag1 = MagicMock()
    mock_tag1.as_vec.return_value = ["e", "c" * 64]
    mock_tag2 = MagicMock()
    mock_tag2.as_vec.return_value = ["p", "d" * 64]
    mock_tags = MagicMock()
    mock_tags.to_vec.return_value = [mock_tag1, mock_tag2]
    mock.tags.return_value = mock_tags

    mock.content.return_value = "Hello, Nostr!"
    mock.signature.return_value = "e" * 128

    return mock


@pytest.fixture
def mock_nostr_event_empty_tags():
    """Create a mock nostr_sdk.Event with no tags."""
    mock = MagicMock(spec=NostrEvent)

    mock_id = MagicMock()
    mock_id.to_hex.return_value = "f" * 64
    mock.id.return_value = mock_id

    mock_author = MagicMock()
    mock_author.to_hex.return_value = "1" * 64
    mock.author.return_value = mock_author

    mock_created_at = MagicMock()
    mock_created_at.as_secs.return_value = 1700000001
    mock.created_at.return_value = mock_created_at

    mock_kind = MagicMock()
    mock_kind.as_u16.return_value = 0
    mock.kind.return_value = mock_kind

    mock_tags = MagicMock()
    mock_tags.to_vec.return_value = []
    mock.tags.return_value = mock_tags

    mock.content.return_value = ""
    mock.signature.return_value = "2" * 128

    return mock


@pytest.fixture
def event(mock_nostr_event):
    """Create an Event instance wrapping a mock NostrEvent."""
    return Event(mock_nostr_event)


# =============================================================================
# Event Construction Tests
# =============================================================================


class TestConstruction:
    """Event construction and initialization."""

    def test_construction_with_nostr_event(self, mock_nostr_event):
        """Event can be constructed with a NostrEvent."""
        event = Event(mock_nostr_event)
        assert event._nostr_event is mock_nostr_event

    def test_construction_preserves_reference(self, mock_nostr_event):
        """Event stores reference to the original NostrEvent, not a copy."""
        event = Event(mock_nostr_event)
        assert event._nostr_event is mock_nostr_event


# =============================================================================
# Null Byte Validation Tests
# =============================================================================


class TestNullByteValidation:
    """Test rejection of events with null bytes in content or tags."""

    def test_rejects_content_with_null_byte(self, mock_nostr_event):
        """Event rejects content containing null bytes."""
        mock_nostr_event.content.return_value = "Hello\x00World"
        with pytest.raises(ValueError, match="content contains null bytes"):
            Event(mock_nostr_event)

    def test_rejects_tags_with_null_byte(self, mock_nostr_event):
        """Event rejects tags containing null bytes."""
        mock_tag = MagicMock()
        mock_tag.as_vec.return_value = ["t", "tag\x00value"]
        mock_tags = MagicMock()
        mock_tags.to_vec.return_value = [mock_tag]
        mock_nostr_event.tags.return_value = mock_tags

        with pytest.raises(ValueError, match="tags contain null bytes"):
            Event(mock_nostr_event)

    def test_accepts_content_without_null_byte(self, mock_nostr_event):
        """Event accepts content without null bytes."""
        mock_nostr_event.content.return_value = "Hello World"
        event = Event(mock_nostr_event)
        assert event.content() == "Hello World"

    def test_error_message_includes_event_id(self, mock_nostr_event):
        """Error message includes truncated event ID for debugging."""
        mock_nostr_event.content.return_value = "Bad\x00Content"
        with pytest.raises(ValueError) as exc_info:
            Event(mock_nostr_event)
        # Truncated event ID (first 16 hex chars) should appear in the error
        assert "aaaaaaaaaaaaaaaa" in str(exc_info.value)


# =============================================================================
# Immutability Tests
# =============================================================================


class TestImmutability:
    """Frozen dataclass behavior."""

    def test_attribute_mutation_blocked(self, mock_nostr_event):
        """Setting _nostr_event attribute should raise FrozenInstanceError."""
        event = Event(mock_nostr_event)
        new_mock = MagicMock()
        with pytest.raises(FrozenInstanceError):
            event._nostr_event = new_mock

    def test_attribute_deletion_blocked(self, mock_nostr_event):
        """Deleting _nostr_event attribute should raise FrozenInstanceError."""
        event = Event(mock_nostr_event)
        with pytest.raises(FrozenInstanceError):
            del event._nostr_event


# =============================================================================
# Slots Tests
# =============================================================================


class TestSlots:
    """__slots__ definition for memory efficiency."""

    def test_has_nostr_event_slot(self):
        """Event should have _nostr_event slot."""
        assert hasattr(Event, "__slots__")
        assert "_nostr_event" in Event.__slots__

    def test_no_instance_dict_in_class(self):
        """Event class should not have __dict__ in dir (uses slots)."""
        # Event uses __slots__, so it doesn't have its own __dict__ defined
        assert "__dict__" not in dir(Event)
        assert "_nostr_event" in Event.__slots__


# =============================================================================
# Delegation Tests
# =============================================================================


class TestDelegation:
    """Method delegation to wrapped NostrEvent via __getattr__."""

    def test_id_delegates(self, mock_nostr_event):
        """id() delegates to wrapped event."""
        event = Event(mock_nostr_event)
        event.id()
        assert mock_nostr_event.id.call_count >= 1

    def test_author_delegates(self, mock_nostr_event):
        """author() delegates to wrapped event."""
        event = Event(mock_nostr_event)
        event.author()
        assert mock_nostr_event.author.call_count >= 1

    def test_created_at_delegates(self, mock_nostr_event):
        """created_at() delegates to wrapped event."""
        event = Event(mock_nostr_event)
        event.created_at()
        assert mock_nostr_event.created_at.call_count >= 1

    def test_kind_delegates(self, mock_nostr_event):
        """kind() delegates to wrapped event."""
        event = Event(mock_nostr_event)
        event.kind()
        assert mock_nostr_event.kind.call_count >= 1

    def test_tags_delegates(self, mock_nostr_event):
        """tags() delegates to wrapped event."""
        event = Event(mock_nostr_event)
        event.tags()
        assert mock_nostr_event.tags.call_count >= 1

    def test_content_delegates(self, mock_nostr_event):
        """content() delegates to wrapped event."""
        event = Event(mock_nostr_event)
        event.content()
        assert mock_nostr_event.content.call_count >= 1

    def test_signature_delegates(self, mock_nostr_event):
        """signature() delegates to wrapped event."""
        event = Event(mock_nostr_event)
        event.signature()
        assert mock_nostr_event.signature.call_count >= 1

    def test_verify_delegates(self, mock_nostr_event):
        """verify() should delegate to wrapped event."""
        event = Event(mock_nostr_event)
        event.verify()
        mock_nostr_event.verify.assert_called_once()

    def test_any_method_delegates(self, mock_nostr_event):
        """Any method should delegate via __getattr__."""
        event = Event(mock_nostr_event)
        # Replace inner with an unrestricted mock to test arbitrary attribute delegation
        unrestricted = MagicMock()
        unrestricted.some_future_method.return_value = "result"
        object.__setattr__(event, "_nostr_event", unrestricted)
        result = event.some_future_method()
        assert result == "result"
        unrestricted.some_future_method.assert_called_once()

    def test_missing_attribute_raises_clear_error(self, mock_nostr_event):
        """Missing attribute raises AttributeError referencing Event, not NostrEvent."""
        event = Event(mock_nostr_event)
        # Replace inner with a spec-restricted mock so unknown attrs raise
        object.__setattr__(event, "_nostr_event", MagicMock(spec=["id", "kind", "content"]))
        with pytest.raises(AttributeError, match="'Event' object has no attribute 'nonexistent'"):
            _ = event.nonexistent


# =============================================================================
# to_db_params Tests
# =============================================================================


class TestToDbParams:
    """Event.to_db_params() serialization."""

    def test_returns_event_db_params(self, event):
        """Returns EventDbParams NamedTuple with 7 elements."""
        result = event.to_db_params()
        assert isinstance(result, EventDbParams)
        assert isinstance(result, tuple)
        assert len(result) == 7

    def test_id_is_32_bytes(self, event):
        """id is converted to 32-byte bytes from 64-char hex."""
        result = event.to_db_params()
        assert isinstance(result.id, bytes)
        assert len(result.id) == 32
        assert result.id == bytes.fromhex("a" * 64)

    def test_pubkey_is_32_bytes(self, event):
        """pubkey is converted to 32-byte bytes from 64-char hex."""
        result = event.to_db_params()
        assert isinstance(result.pubkey, bytes)
        assert len(result.pubkey) == 32
        assert result.pubkey == bytes.fromhex("b" * 64)

    def test_created_at_is_int(self, event):
        """created_at is Unix timestamp integer."""
        result = event.to_db_params()
        assert isinstance(result.created_at, int)
        assert result.created_at == 1700000000

    def test_kind_is_int(self, event):
        """kind is integer event type."""
        result = event.to_db_params()
        assert isinstance(result.kind, int)
        assert result.kind == 1

    def test_tags_is_valid_json(self, event):
        """tags is valid JSON string."""
        result = event.to_db_params()
        assert isinstance(result.tags, str)
        parsed = json.loads(result.tags)
        assert isinstance(parsed, list)
        assert parsed == [["e", "c" * 64], ["p", "d" * 64]]

    def test_content_is_string(self, event):
        """content is string."""
        result = event.to_db_params()
        assert isinstance(result.content, str)
        assert result.content == "Hello, Nostr!"

    def test_sig_is_64_bytes(self, event):
        """sig is converted to 64-byte bytes from 128-char hex."""
        result = event.to_db_params()
        assert isinstance(result.sig, bytes)
        assert len(result.sig) == 64
        assert result.sig == bytes.fromhex("e" * 128)

    def test_empty_tags(self, mock_nostr_event_empty_tags):
        """Empty tags are serialized as empty JSON array."""
        event = Event(mock_nostr_event_empty_tags)
        result = event.to_db_params()
        assert result.tags == "[]"

    def test_empty_content(self, mock_nostr_event_empty_tags):
        """Empty content is serialized as empty string."""
        event = Event(mock_nostr_event_empty_tags)
        result = event.to_db_params()
        assert result.content == ""

    def test_kind_zero(self, mock_nostr_event_empty_tags):
        """Kind 0 (metadata) is handled correctly."""
        event = Event(mock_nostr_event_empty_tags)
        result = event.to_db_params()
        assert result.kind == 0


# =============================================================================
# Edge Cases Tests
# =============================================================================


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_large_content(self):
        """Large content (100KB) is handled correctly."""
        mock = MagicMock(spec=NostrEvent)
        mock_id = MagicMock()
        mock_id.to_hex.return_value = "a" * 64
        mock.id.return_value = mock_id
        mock_author = MagicMock()
        mock_author.to_hex.return_value = "b" * 64
        mock.author.return_value = mock_author
        mock_created_at = MagicMock()
        mock_created_at.as_secs.return_value = 1700000000
        mock.created_at.return_value = mock_created_at
        mock_kind = MagicMock()
        mock_kind.as_u16.return_value = 1
        mock.kind.return_value = mock_kind
        mock_tags = MagicMock()
        mock_tags.to_vec.return_value = []
        mock.tags.return_value = mock_tags
        mock.content.return_value = "x" * 100000
        mock.signature.return_value = "e" * 128

        event = Event(mock)
        params = event.to_db_params()
        assert len(params.content) == 100000

    def test_unicode_content(self):
        """Unicode content is handled correctly."""
        mock = MagicMock(spec=NostrEvent)
        mock_id = MagicMock()
        mock_id.to_hex.return_value = "a" * 64
        mock.id.return_value = mock_id
        mock_author = MagicMock()
        mock_author.to_hex.return_value = "b" * 64
        mock.author.return_value = mock_author
        mock_created_at = MagicMock()
        mock_created_at.as_secs.return_value = 1700000000
        mock.created_at.return_value = mock_created_at
        mock_kind = MagicMock()
        mock_kind.as_u16.return_value = 1
        mock.kind.return_value = mock_kind
        mock_tags = MagicMock()
        mock_tags.to_vec.return_value = []
        mock.tags.return_value = mock_tags
        mock.content.return_value = "Hello World"
        mock.signature.return_value = "e" * 128

        event = Event(mock)
        params = event.to_db_params()
        assert params.content == "Hello World"

    def test_many_tags(self):
        """Many tags (100) are serialized correctly."""
        mock = MagicMock(spec=NostrEvent)
        mock_id = MagicMock()
        mock_id.to_hex.return_value = "a" * 64
        mock.id.return_value = mock_id
        mock_author = MagicMock()
        mock_author.to_hex.return_value = "b" * 64
        mock.author.return_value = mock_author
        mock_created_at = MagicMock()
        mock_created_at.as_secs.return_value = 1700000000
        mock.created_at.return_value = mock_created_at
        mock_kind = MagicMock()
        mock_kind.as_u16.return_value = 1
        mock.kind.return_value = mock_kind
        mock.content.return_value = "Test"
        mock.signature.return_value = "e" * 128

        mock_tags_list = []
        for i in range(100):
            tag = MagicMock()
            tag.as_vec.return_value = ["t", f"tag{i}"]
            mock_tags_list.append(tag)
        mock_tags = MagicMock()
        mock_tags.to_vec.return_value = mock_tags_list
        mock.tags.return_value = mock_tags

        event = Event(mock)
        params = event.to_db_params()
        parsed_tags = json.loads(params.tags)
        assert len(parsed_tags) == 100
        assert parsed_tags[0] == ["t", "tag0"]
        assert parsed_tags[99] == ["t", "tag99"]

    def test_complex_nested_tags(self):
        """Complex tag structures with multiple elements are handled."""
        mock = MagicMock(spec=NostrEvent)
        mock_id = MagicMock()
        mock_id.to_hex.return_value = "a" * 64
        mock.id.return_value = mock_id
        mock_author = MagicMock()
        mock_author.to_hex.return_value = "b" * 64
        mock.author.return_value = mock_author
        mock_created_at = MagicMock()
        mock_created_at.as_secs.return_value = 1700000000
        mock.created_at.return_value = mock_created_at
        mock_kind = MagicMock()
        mock_kind.as_u16.return_value = 1
        mock.kind.return_value = mock_kind
        mock.content.return_value = "Test"
        mock.signature.return_value = "e" * 128

        mock_tag = MagicMock()
        mock_tag.as_vec.return_value = ["a", "b", "c", "d", "e"]
        mock_tags = MagicMock()
        mock_tags.to_vec.return_value = [mock_tag]
        mock.tags.return_value = mock_tags

        event = Event(mock)
        params = event.to_db_params()
        parsed_tags = json.loads(params.tags)
        assert parsed_tags == [["a", "b", "c", "d", "e"]]


# =============================================================================
# Equality Tests
# =============================================================================


class TestEquality:
    """Equality behavior based on frozen dataclass."""

    def test_same_nostr_event_equal(self, mock_nostr_event):
        """Events with same inner object are equal."""
        event1 = Event(mock_nostr_event)
        event2 = Event(mock_nostr_event)
        assert event1 == event2

    def test_different_nostr_event_not_equal(self, mock_nostr_event, mock_nostr_event_empty_tags):
        """Events with different inner objects are not equal."""
        event1 = Event(mock_nostr_event)
        event2 = Event(mock_nostr_event_empty_tags)
        assert event1 != event2


# =============================================================================
# Type Validation Tests
# =============================================================================


class TestTypeValidation:
    """Runtime type validation in __post_init__."""

    def test_non_nostr_event_rejected(self):
        """_nostr_event must be a NostrEvent instance."""
        with pytest.raises(TypeError, match="_nostr_event must be an Event"):
            Event("not an event")  # type: ignore[arg-type]

    def test_none_rejected(self):
        """None is not accepted as _nostr_event."""
        with pytest.raises(TypeError, match="_nostr_event must be an Event"):
            Event(None)  # type: ignore[arg-type]

    def test_dict_rejected(self):
        """A dict is not accepted as _nostr_event."""
        with pytest.raises(TypeError, match="_nostr_event must be an Event"):
            Event({"id": "abc"})  # type: ignore[arg-type]
