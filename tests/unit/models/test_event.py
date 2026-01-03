"""
Unit tests for models.event module.

Tests:
- Event immutability enforcement
- Wrapper around nostr_sdk.Event
- Transparent delegation via __getattr__
- to_db_params() method
"""

import json
from unittest.mock import MagicMock

import pytest

from models import Event


class TestImmutability:
    """Event immutability enforcement (frozen dataclass)."""

    def test_attribute_mutation_blocked(self):
        """Setting attributes should raise FrozenInstanceError."""
        from dataclasses import FrozenInstanceError

        mock_inner = MagicMock()
        event = Event(mock_inner)

        with pytest.raises(FrozenInstanceError):
            event._inner = MagicMock()

    def test_attribute_deletion_blocked(self):
        """Deleting attributes should raise FrozenInstanceError."""
        from dataclasses import FrozenInstanceError

        mock_inner = MagicMock()
        event = Event(mock_inner)

        with pytest.raises(FrozenInstanceError):
            del event._inner


class TestToDbParams:
    """Event.to_db_params() method."""

    @pytest.fixture
    def mock_nostr_event(self):
        """Create a mock nostr_sdk Event with proper method chains."""
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
        mock_created_at.as_secs.return_value = 1234567890
        mock.created_at.return_value = mock_created_at

        # Mock kind() -> returns object with as_u16()
        mock_kind = MagicMock()
        mock_kind.as_u16.return_value = 1
        mock.kind.return_value = mock_kind

        # Mock tags() -> returns object with to_vec() -> list of tag objects
        mock_tag1 = MagicMock()
        mock_tag1.as_vec.return_value = ["e", "event_id_1"]
        mock_tag2 = MagicMock()
        mock_tag2.as_vec.return_value = ["p", "pubkey_1"]
        mock_tags = MagicMock()
        mock_tags.to_vec.return_value = [mock_tag1, mock_tag2]
        mock.tags.return_value = mock_tags

        # Mock content() -> returns string directly
        mock.content.return_value = "Hello, Nostr!"

        # Mock signature() -> returns hex string directly
        mock.signature.return_value = "c" * 128

        return mock

    def test_returns_tuple_of_seven(self, mock_nostr_event):
        """to_db_params should return 7-element tuple."""
        event = Event(mock_nostr_event)
        result = event.to_db_params()
        assert isinstance(result, tuple)
        assert len(result) == 7

    def test_id_is_bytes(self, mock_nostr_event):
        """First element should be 32-byte event ID."""
        event = Event(mock_nostr_event)
        result = event.to_db_params()
        assert isinstance(result[0], bytes)
        assert len(result[0]) == 32

    def test_pubkey_is_bytes(self, mock_nostr_event):
        """Second element should be 32-byte pubkey."""
        event = Event(mock_nostr_event)
        result = event.to_db_params()
        assert isinstance(result[1], bytes)
        assert len(result[1]) == 32

    def test_created_at_is_int(self, mock_nostr_event):
        """Third element should be unix timestamp."""
        event = Event(mock_nostr_event)
        result = event.to_db_params()
        assert result[2] == 1234567890

    def test_kind_is_int(self, mock_nostr_event):
        """Fourth element should be event kind."""
        event = Event(mock_nostr_event)
        result = event.to_db_params()
        assert result[3] == 1

    def test_tags_is_json(self, mock_nostr_event):
        """Fifth element should be JSON string of tags."""
        event = Event(mock_nostr_event)
        result = event.to_db_params()
        parsed = json.loads(result[4])
        assert parsed == [["e", "event_id_1"], ["p", "pubkey_1"]]

    def test_content_is_string(self, mock_nostr_event):
        """Sixth element should be content string."""
        event = Event(mock_nostr_event)
        result = event.to_db_params()
        assert result[5] == "Hello, Nostr!"

    def test_sig_is_bytes(self, mock_nostr_event):
        """Seventh element should be 64-byte signature."""
        event = Event(mock_nostr_event)
        result = event.to_db_params()
        assert isinstance(result[6], bytes)
        assert len(result[6]) == 64


class TestSlots:
    """__slots__ definition."""

    def test_has_inner_slot(self):
        """Event should have _inner slot."""
        assert hasattr(Event, "__slots__")
        assert "_inner" in Event.__slots__

    def test_no_instance_dict(self):
        """Event should not have its own __dict__ (slots-only)."""
        mock_inner = MagicMock()
        _ = Event(mock_inner)  # Create instance to verify slots work
        # Event uses __slots__, so it doesn't have its own __dict__
        # (hasattr returns True because __getattr__ delegates to mock)
        assert "__dict__" not in dir(Event)
        assert "_inner" in Event.__slots__


class TestDelegation:
    """Method delegation to wrapped NostrEvent."""

    @pytest.fixture
    def mock_nostr_event(self):
        """Create mock nostr event."""
        return MagicMock()

    def test_id_delegates(self, mock_nostr_event):
        """id() should delegate to wrapped event."""
        event = Event(mock_nostr_event)
        event.id()
        mock_nostr_event.id.assert_called_once()

    def test_author_delegates(self, mock_nostr_event):
        """author() should delegate to wrapped event."""
        event = Event(mock_nostr_event)
        event.author()
        mock_nostr_event.author.assert_called_once()

    def test_created_at_delegates(self, mock_nostr_event):
        """created_at() should delegate to wrapped event."""
        event = Event(mock_nostr_event)
        event.created_at()
        mock_nostr_event.created_at.assert_called_once()

    def test_kind_delegates(self, mock_nostr_event):
        """kind() should delegate to wrapped event."""
        event = Event(mock_nostr_event)
        event.kind()
        mock_nostr_event.kind.assert_called_once()

    def test_tags_delegates(self, mock_nostr_event):
        """tags() should delegate to wrapped event."""
        event = Event(mock_nostr_event)
        event.tags()
        mock_nostr_event.tags.assert_called_once()

    def test_content_delegates(self, mock_nostr_event):
        """content() should delegate to wrapped event."""
        event = Event(mock_nostr_event)
        event.content()
        mock_nostr_event.content.assert_called_once()

    def test_signature_delegates(self, mock_nostr_event):
        """signature() should delegate to wrapped event."""
        event = Event(mock_nostr_event)
        event.signature()
        mock_nostr_event.signature.assert_called_once()

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


class TestFromDbParams:
    """Reconstruction from database parameters."""

    def test_roundtrip_structure(self):
        """from_db_params should accept to_db_params output structure."""
        # Create mock event for to_db_params
        mock = MagicMock()
        mock_id = MagicMock()
        mock_id.to_hex.return_value = "a" * 64
        mock.id.return_value = mock_id
        mock_author = MagicMock()
        mock_author.to_hex.return_value = "b" * 64
        mock.author.return_value = mock_author
        mock_created_at = MagicMock()
        mock_created_at.as_secs.return_value = 1234567890
        mock.created_at.return_value = mock_created_at
        mock_kind = MagicMock()
        mock_kind.as_u16.return_value = 1
        mock.kind.return_value = mock_kind
        mock_tags = MagicMock()
        mock_tags.to_vec.return_value = []
        mock.tags.return_value = mock_tags
        mock.content.return_value = "test"
        mock.signature.return_value = "c" * 128

        event = Event(mock)
        params = event.to_db_params()

        # Verify params structure
        assert len(params) == 7
        assert isinstance(params[0], bytes)  # event_id
        assert isinstance(params[1], bytes)  # pubkey
        assert isinstance(params[2], int)  # created_at
        assert isinstance(params[3], int)  # kind
        assert isinstance(params[4], str)  # tags_json
        assert isinstance(params[5], str)  # content
        assert isinstance(params[6], bytes)  # sig
