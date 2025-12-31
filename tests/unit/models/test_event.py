"""Tests for models.event module."""

import json
from unittest.mock import MagicMock

import pytest

from models import Event


class TestImmutability:
    """Event immutability enforcement."""

    def test_attribute_mutation_blocked(self):
        """Setting attributes should raise AttributeError."""
        mock_inner = MagicMock()
        event = Event(mock_inner)

        with pytest.raises(AttributeError, match="immutable"):
            event.some_attr = "value"

    def test_attribute_deletion_blocked(self):
        """Deleting attributes should raise AttributeError."""
        mock_inner = MagicMock()
        event = Event(mock_inner)

        with pytest.raises(AttributeError, match="immutable"):
            del event._inner


class TestToDbParams:
    """Event.to_db_params() method."""

    @pytest.fixture
    def mock_inner_event(self):
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

    def test_returns_tuple_of_seven(self, mock_inner_event):
        """to_db_params should return 7-element tuple."""
        event = Event(mock_inner_event)
        result = event.to_db_params()
        assert isinstance(result, tuple)
        assert len(result) == 7

    def test_id_is_bytes(self, mock_inner_event):
        """First element should be 32-byte event ID."""
        event = Event(mock_inner_event)
        result = event.to_db_params()
        assert isinstance(result[0], bytes)
        assert len(result[0]) == 32

    def test_pubkey_is_bytes(self, mock_inner_event):
        """Second element should be 32-byte pubkey."""
        event = Event(mock_inner_event)
        result = event.to_db_params()
        assert isinstance(result[1], bytes)
        assert len(result[1]) == 32

    def test_created_at_is_int(self, mock_inner_event):
        """Third element should be unix timestamp."""
        event = Event(mock_inner_event)
        result = event.to_db_params()
        assert result[2] == 1234567890

    def test_kind_is_int(self, mock_inner_event):
        """Fourth element should be event kind."""
        event = Event(mock_inner_event)
        result = event.to_db_params()
        assert result[3] == 1

    def test_tags_is_json(self, mock_inner_event):
        """Fifth element should be JSON string of tags."""
        event = Event(mock_inner_event)
        result = event.to_db_params()
        parsed = json.loads(result[4])
        assert parsed == [["e", "event_id_1"], ["p", "pubkey_1"]]

    def test_content_is_string(self, mock_inner_event):
        """Sixth element should be content string."""
        event = Event(mock_inner_event)
        result = event.to_db_params()
        assert result[5] == "Hello, Nostr!"

    def test_sig_is_bytes(self, mock_inner_event):
        """Seventh element should be 64-byte signature."""
        event = Event(mock_inner_event)
        result = event.to_db_params()
        assert isinstance(result[6], bytes)
        assert len(result[6]) == 64


class TestSlots:
    """__slots__ definition."""

    def test_has_inner_slot(self):
        """Event should have _inner slot for composition."""
        assert hasattr(Event, "__slots__")
        assert "_inner" in Event.__slots__

    def test_no_dict(self):
        """Event should not have __dict__ (slots-only)."""
        mock_inner = MagicMock()
        event = Event(mock_inner)
        assert not hasattr(event, "__dict__")


class TestDelegation:
    """Method delegation to inner event."""

    @pytest.fixture
    def mock_inner(self):
        """Create mock inner event."""
        return MagicMock()

    def test_id_delegates(self, mock_inner):
        """id() should delegate to inner."""
        event = Event(mock_inner)
        event.id()
        mock_inner.id.assert_called_once()

    def test_author_delegates(self, mock_inner):
        """author() should delegate to inner."""
        event = Event(mock_inner)
        event.author()
        mock_inner.author.assert_called_once()

    def test_created_at_delegates(self, mock_inner):
        """created_at() should delegate to inner."""
        event = Event(mock_inner)
        event.created_at()
        mock_inner.created_at.assert_called_once()

    def test_kind_delegates(self, mock_inner):
        """kind() should delegate to inner."""
        event = Event(mock_inner)
        event.kind()
        mock_inner.kind.assert_called_once()

    def test_tags_delegates(self, mock_inner):
        """tags() should delegate to inner."""
        event = Event(mock_inner)
        event.tags()
        mock_inner.tags.assert_called_once()

    def test_content_delegates(self, mock_inner):
        """content() should delegate to inner."""
        event = Event(mock_inner)
        event.content()
        mock_inner.content.assert_called_once()

    def test_signature_delegates(self, mock_inner):
        """signature() should delegate to inner."""
        event = Event(mock_inner)
        event.signature()
        mock_inner.signature.assert_called_once()

    def test_verify_delegates(self, mock_inner):
        """verify() should delegate to inner."""
        event = Event(mock_inner)
        event.verify()
        mock_inner.verify.assert_called_once()

    def test_inner_property(self, mock_inner):
        """inner property should return the wrapped event."""
        event = Event(mock_inner)
        assert event.inner is mock_inner
