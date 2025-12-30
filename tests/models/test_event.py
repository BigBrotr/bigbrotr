"""Tests for models.event module."""

import json
import pytest
from unittest.mock import MagicMock, patch

from models import Event


class TestImmutability:
    """Event immutability enforcement."""

    def test_attribute_mutation_blocked(self):
        with patch.object(Event, "__init__", lambda self: None):
            event = object.__new__(Event)
            object.__setattr__(event, "_frozen", True)

            with pytest.raises(AttributeError, match="immutable"):
                event.some_attr = "value"

    def test_attribute_deletion_blocked(self):
        with patch.object(Event, "__init__", lambda self: None):
            event = object.__new__(Event)
            object.__setattr__(event, "_frozen", True)
            object.__setattr__(event, "some_attr", "value")

            with pytest.raises(AttributeError, match="immutable"):
                del event.some_attr


class TestToDbParams:
    """Event.to_db_params() method."""

    @pytest.fixture
    def mock_event(self):
        """Create a mock nostr_sdk Event."""
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

        mock_tag1 = MagicMock()
        mock_tag1.as_vec.return_value = ["e", "event_id_1"]
        mock_tag2 = MagicMock()
        mock_tag2.as_vec.return_value = ["p", "pubkey_1"]
        mock_tags = MagicMock()
        mock_tags.to_vec.return_value = [mock_tag1, mock_tag2]
        mock.tags.return_value = mock_tags

        mock.content.return_value = "Hello, Nostr!"
        mock.signature.return_value = "c" * 128

        return mock

    def _make_event(self, mock):
        """Create Event with mocked parent behavior."""
        event = MagicMock(spec=Event)
        event.id = mock.id
        event.author = mock.author
        event.created_at = mock.created_at
        event.kind = mock.kind
        event.tags = mock.tags
        event.content = mock.content
        event.signature = mock.signature
        event.to_db_params = Event.to_db_params.__get__(event, Event)
        return event

    def test_returns_tuple_of_seven(self, mock_event):
        event = self._make_event(mock_event)
        result = event.to_db_params()
        assert isinstance(result, tuple)
        assert len(result) == 7

    def test_id_is_bytes(self, mock_event):
        event = self._make_event(mock_event)
        result = event.to_db_params()
        assert isinstance(result[0], bytes)
        assert len(result[0]) == 32

    def test_pubkey_is_bytes(self, mock_event):
        event = self._make_event(mock_event)
        result = event.to_db_params()
        assert isinstance(result[1], bytes)
        assert len(result[1]) == 32

    def test_created_at_is_int(self, mock_event):
        event = self._make_event(mock_event)
        result = event.to_db_params()
        assert result[2] == 1234567890

    def test_kind_is_int(self, mock_event):
        event = self._make_event(mock_event)
        result = event.to_db_params()
        assert result[3] == 1

    def test_tags_is_json(self, mock_event):
        event = self._make_event(mock_event)
        result = event.to_db_params()
        parsed = json.loads(result[4])
        assert parsed == [["e", "event_id_1"], ["p", "pubkey_1"]]

    def test_content_is_string(self, mock_event):
        event = self._make_event(mock_event)
        result = event.to_db_params()
        assert result[5] == "Hello, Nostr!"

    def test_sig_is_bytes(self, mock_event):
        event = self._make_event(mock_event)
        result = event.to_db_params()
        assert isinstance(result[6], bytes)
        assert len(result[6]) == 64


class TestSlots:
    """__slots__ definition."""

    def test_has_frozen_slot(self):
        assert hasattr(Event, "__slots__")
        assert "_frozen" in Event.__slots__
