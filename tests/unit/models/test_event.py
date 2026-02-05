"""
Unit tests for models.event module.

Tests:
- Event construction from nostr_sdk.Event
- Immutability enforcement (frozen dataclass with __slots__)
- Transparent attribute delegation via __getattr__
- to_db_params() serialization for database insert
- from_db_params() deserialization from database
- EventDbParams NamedTuple structure and fields
"""

import json
from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock

import pytest

from models.event import Event, EventDbParams


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_nostr_event():
    """Create a mock nostr_sdk.Event with proper method chains.

    Configures all required method chains for Event.to_db_params():
    - id() -> to_hex() -> 64-char hex string
    - author() -> to_hex() -> 64-char hex string
    - created_at() -> as_secs() -> int timestamp
    - kind() -> as_u16() -> int event kind
    - tags() -> to_vec() -> list of mock tags with as_vec()
    - content() -> string
    - signature() -> 128-char hex string
    """
    mock = MagicMock()

    # Mock id() -> returns object with to_hex()
    mock_id = MagicMock()
    mock_id.to_hex.return_value = "a" * 64
    mock.id.return_value = mock_id

    # Mock author() -> returns object with to_hex()
    mock_author = MagicMock()
    mock_author.to_hex.return_value = "b" * 64
    mock.author.return_value = mock_author

    # Mock created_at() -> returns object with as_secs()
    mock_created_at = MagicMock()
    mock_created_at.as_secs.return_value = 1700000000
    mock.created_at.return_value = mock_created_at

    # Mock kind() -> returns object with as_u16()
    mock_kind = MagicMock()
    mock_kind.as_u16.return_value = 1
    mock.kind.return_value = mock_kind

    # Mock tags() -> returns object with to_vec() -> list of tag objects
    mock_tag1 = MagicMock()
    mock_tag1.as_vec.return_value = ["e", "c" * 64]
    mock_tag2 = MagicMock()
    mock_tag2.as_vec.return_value = ["p", "d" * 64]
    mock_tags = MagicMock()
    mock_tags.to_vec.return_value = [mock_tag1, mock_tag2]
    mock.tags.return_value = mock_tags

    # Mock content() -> returns string directly
    mock.content.return_value = "Hello, Nostr!"

    # Mock signature() -> returns hex string directly
    mock.signature.return_value = "e" * 128

    return mock


@pytest.fixture
def mock_nostr_event_empty_tags():
    """Create a mock nostr_sdk.Event with no tags."""
    mock = MagicMock()

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
# EventDbParams Tests
# =============================================================================


class TestEventDbParams:
    """Test EventDbParams NamedTuple."""

    def test_is_named_tuple(self):
        """EventDbParams is a NamedTuple with 7 fields."""
        params = EventDbParams(
            id=bytes.fromhex("a" * 64),
            pubkey=bytes.fromhex("b" * 64),
            created_at=1700000000,
            kind=1,
            tags_json='[["e", "c"]]',
            content="Test",
            sig=bytes.fromhex("e" * 128),
        )
        assert isinstance(params, tuple)
        assert len(params) == 7

    def test_field_access_by_name(self):
        """Fields are accessible by name."""
        params = EventDbParams(
            id=b"\x00" * 32,
            pubkey=b"\x01" * 32,
            created_at=1234567890,
            kind=1,
            tags_json="[]",
            content="Hello",
            sig=b"\x02" * 64,
        )
        assert params.id == b"\x00" * 32
        assert params.pubkey == b"\x01" * 32
        assert params.created_at == 1234567890
        assert params.kind == 1
        assert params.tags_json == "[]"
        assert params.content == "Hello"
        assert params.sig == b"\x02" * 64

    def test_field_access_by_index(self):
        """Fields are accessible by index."""
        params = EventDbParams(
            id=b"\xaa" * 32,
            pubkey=b"\xbb" * 32,
            created_at=9999999999,
            kind=7,
            tags_json='[["t","test"]]',
            content="Content",
            sig=b"\xcc" * 64,
        )
        assert params[0] == b"\xaa" * 32  # id
        assert params[1] == b"\xbb" * 32  # pubkey
        assert params[2] == 9999999999  # created_at
        assert params[3] == 7  # kind
        assert params[4] == '[["t","test"]]'  # tags_json
        assert params[5] == "Content"  # content
        assert params[6] == b"\xcc" * 64  # sig

    def test_immutability(self):
        """EventDbParams is immutable (NamedTuple)."""
        params = EventDbParams(
            id=b"\x00" * 32,
            pubkey=b"\x01" * 32,
            created_at=1234567890,
            kind=1,
            tags_json="[]",
            content="Hello",
            sig=b"\x02" * 64,
        )
        with pytest.raises(AttributeError):
            params.id = b"\xff" * 32


# =============================================================================
# Event Construction Tests
# =============================================================================


class TestConstruction:
    """Event construction and initialization."""

    def test_construction_with_nostr_event(self, mock_nostr_event):
        """Event can be constructed with a NostrEvent."""
        event = Event(mock_nostr_event)
        assert event._inner is mock_nostr_event

    def test_construction_preserves_reference(self, mock_nostr_event):
        """Event stores reference to the original NostrEvent."""
        event = Event(mock_nostr_event)
        # Same object, not a copy
        assert event._inner is mock_nostr_event


# =============================================================================
# Null Byte Validation Tests
# =============================================================================


class TestNullByteValidation:
    """Test rejection of events with null bytes in content."""

    def test_rejects_content_with_null_byte(self, mock_nostr_event):
        """Event rejects content containing null bytes."""
        mock_nostr_event.content.return_value = "Hello\x00World"
        with pytest.raises(ValueError, match="null bytes"):
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
        # Event ID starts with 'a' * 64, so first 16 chars are 'a' * 16
        assert "aaaaaaaaaaaaaaaa" in str(exc_info.value)


# =============================================================================
# Immutability Tests
# =============================================================================


class TestImmutability:
    """Frozen dataclass behavior."""

    def test_attribute_mutation_blocked(self, mock_nostr_event):
        """Setting _inner attribute should raise FrozenInstanceError."""
        event = Event(mock_nostr_event)
        new_mock = MagicMock()
        with pytest.raises(FrozenInstanceError):
            event._inner = new_mock

    def test_attribute_deletion_blocked(self, mock_nostr_event):
        """Deleting _inner attribute should raise FrozenInstanceError."""
        event = Event(mock_nostr_event)
        with pytest.raises(FrozenInstanceError):
            del event._inner


# =============================================================================
# Slots Tests
# =============================================================================


class TestSlots:
    """__slots__ definition for memory efficiency."""

    def test_has_inner_slot(self):
        """Event should have _inner slot."""
        assert hasattr(Event, "__slots__")
        assert "_inner" in Event.__slots__

    def test_no_instance_dict_in_class(self):
        """Event class should not have __dict__ in dir (uses slots)."""
        # Event uses __slots__, so it doesn't have its own __dict__ defined
        assert "__dict__" not in dir(Event)
        assert "_inner" in Event.__slots__


# =============================================================================
# Delegation Tests
# =============================================================================


class TestDelegation:
    """Method delegation to wrapped NostrEvent via __getattr__.

    Note: Most methods are now called twice during Event construction:
    once in __post_init__ (fail-fast to_db_params validation) and once
    when explicitly called in the test.
    """

    def test_id_delegates(self, mock_nostr_event):
        """id() should delegate to wrapped event."""
        event = Event(mock_nostr_event)
        event.id()
        # Called twice: once in __post_init__ (to_db_params), once here
        assert mock_nostr_event.id.call_count == 2

    def test_author_delegates(self, mock_nostr_event):
        """author() should delegate to wrapped event."""
        event = Event(mock_nostr_event)
        event.author()
        # Called twice: once in __post_init__ (to_db_params), once here
        assert mock_nostr_event.author.call_count == 2

    def test_created_at_delegates(self, mock_nostr_event):
        """created_at() should delegate to wrapped event."""
        event = Event(mock_nostr_event)
        event.created_at()
        # Called twice: once in __post_init__ (to_db_params), once here
        assert mock_nostr_event.created_at.call_count == 2

    def test_kind_delegates(self, mock_nostr_event):
        """kind() should delegate to wrapped event."""
        event = Event(mock_nostr_event)
        event.kind()
        # Called twice: once in __post_init__ (to_db_params), once here
        assert mock_nostr_event.kind.call_count == 2

    def test_tags_delegates(self, mock_nostr_event):
        """tags() should delegate to wrapped event."""
        event = Event(mock_nostr_event)
        event.tags()
        # Called twice: once in __post_init__ (to_db_params), once here
        assert mock_nostr_event.tags.call_count == 2

    def test_content_delegates(self, mock_nostr_event):
        """content() should delegate to wrapped event."""
        event = Event(mock_nostr_event)
        event.content()
        # Called 3x: once for null check, once in to_db_params, once here
        assert mock_nostr_event.content.call_count == 3

    def test_signature_delegates(self, mock_nostr_event):
        """signature() should delegate to wrapped event."""
        event = Event(mock_nostr_event)
        event.signature()
        # Called twice: once in __post_init__ (to_db_params), once here
        assert mock_nostr_event.signature.call_count == 2

    def test_verify_delegates(self, mock_nostr_event):
        """verify() should delegate to wrapped event."""
        event = Event(mock_nostr_event)
        event.verify()
        mock_nostr_event.verify.assert_called_once()

    def test_any_method_delegates(self, mock_nostr_event):
        """Any method should delegate via __getattr__."""
        mock_nostr_event.some_future_method.return_value = "result"
        event = Event(mock_nostr_event)
        result = event.some_future_method()
        assert result == "result"
        mock_nostr_event.some_future_method.assert_called_once()


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

    def test_tags_json_is_valid_json(self, event):
        """tags_json is valid JSON string."""
        result = event.to_db_params()
        assert isinstance(result.tags_json, str)
        parsed = json.loads(result.tags_json)
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
        assert result.tags_json == "[]"

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
# from_db_params Tests
# =============================================================================


class TestFromDbParams:
    """Event.from_db_params() deserialization."""

    def test_roundtrip_structure(self, event):
        """to_db_params output can be used with from_db_params."""
        params = event.to_db_params()

        # Verify params structure matches from_db_params signature
        assert len(params) == 7
        assert isinstance(params.id, bytes)  # event_id
        assert isinstance(params.pubkey, bytes)  # pubkey
        assert isinstance(params.created_at, int)  # created_at
        assert isinstance(params.kind, int)  # kind
        assert isinstance(params.tags_json, str)  # tags_json
        assert isinstance(params.content, str)  # content
        assert isinstance(params.sig, bytes)  # sig


# =============================================================================
# Edge Cases Tests
# =============================================================================


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_large_content(self):
        """Large content (100KB) is handled correctly."""
        mock = MagicMock()
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
        mock.content.return_value = "x" * 100000  # 100KB content
        mock.signature.return_value = "e" * 128

        event = Event(mock)
        params = event.to_db_params()
        assert len(params.content) == 100000

    def test_unicode_content(self):
        """Unicode content is handled correctly."""
        mock = MagicMock()
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
        mock = MagicMock()
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

        # Create 100 tags
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
        parsed_tags = json.loads(params.tags_json)
        assert len(parsed_tags) == 100
        assert parsed_tags[0] == ["t", "tag0"]
        assert parsed_tags[99] == ["t", "tag99"]

    def test_complex_nested_tags(self):
        """Complex tag structures with multiple elements are handled."""
        mock = MagicMock()
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

        # Tag with multiple elements
        mock_tag = MagicMock()
        mock_tag.as_vec.return_value = ["a", "b", "c", "d", "e"]
        mock_tags = MagicMock()
        mock_tags.to_vec.return_value = [mock_tag]
        mock.tags.return_value = mock_tags

        event = Event(mock)
        params = event.to_db_params()
        parsed_tags = json.loads(params.tags_json)
        assert parsed_tags == [["a", "b", "c", "d", "e"]]


# =============================================================================
# Equality Tests
# =============================================================================


class TestEquality:
    """Equality behavior based on frozen dataclass."""

    def test_same_inner_equal(self, mock_nostr_event):
        """Events with same inner object are equal."""
        event1 = Event(mock_nostr_event)
        event2 = Event(mock_nostr_event)
        assert event1 == event2

    def test_different_inner_not_equal(self, mock_nostr_event, mock_nostr_event_empty_tags):
        """Events with different inner objects are not equal."""
        event1 = Event(mock_nostr_event)
        event2 = Event(mock_nostr_event_empty_tags)
        assert event1 != event2
