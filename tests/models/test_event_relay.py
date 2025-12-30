"""Tests for models.event_relay module."""

import pytest
from time import time
from unittest.mock import MagicMock

from models import Event, EventRelay, Relay


@pytest.fixture
def mock_event():
    """Create a mock Event."""
    mock = MagicMock(spec=Event)
    mock.to_db_params.return_value = (
        b"\xaa" * 32,  # id
        b"\xbb" * 32,  # pubkey
        1234567890,    # created_at
        1,             # kind
        '[["e","id"]]',  # tags
        "Hello",       # content
        b"\xcc" * 64,  # sig
    )
    return mock


@pytest.fixture
def relay():
    """Create a test Relay."""
    return Relay("wss://relay.example.com", discovered_at=1234567890)


class TestConstruction:
    """EventRelay construction."""

    def test_with_event_and_relay(self, mock_event, relay):
        er = EventRelay(mock_event, relay)
        assert er.event is mock_event
        assert er.relay is relay

    def test_seen_at_defaults_to_now(self, mock_event, relay):
        before = int(time())
        er = EventRelay(mock_event, relay)
        after = int(time())
        assert before <= er.seen_at <= after

    def test_seen_at_explicit(self, mock_event, relay):
        er = EventRelay(mock_event, relay, seen_at=9999999999)
        assert er.seen_at == 9999999999


class TestImmutability:
    """Frozen dataclass behavior."""

    def test_attribute_mutation_blocked(self, mock_event, relay):
        er = EventRelay(mock_event, relay, seen_at=1234567890)
        with pytest.raises(AttributeError):
            er.seen_at = 9999999999

    def test_new_attribute_blocked(self, mock_event, relay):
        er = EventRelay(mock_event, relay)
        with pytest.raises(AttributeError):
            er.new_attr = "value"


class TestToDbParams:
    """EventRelay.to_db_params() method."""

    def test_returns_tuple_of_eleven(self, mock_event, relay):
        er = EventRelay(mock_event, relay, seen_at=1234567890)
        result = er.to_db_params()
        assert isinstance(result, tuple)
        assert len(result) == 11  # 7 event + 3 relay + 1 seen_at

    def test_event_params(self, mock_event, relay):
        er = EventRelay(mock_event, relay, seen_at=1234567890)
        result = er.to_db_params()
        assert result[0] == b"\xaa" * 32  # id
        assert result[1] == b"\xbb" * 32  # pubkey
        assert result[2] == 1234567890    # created_at
        assert result[3] == 1             # kind
        assert result[4] == '[["e","id"]]'  # tags
        assert result[5] == "Hello"       # content
        assert result[6] == b"\xcc" * 64  # sig

    def test_relay_params(self, mock_event, relay):
        er = EventRelay(mock_event, relay, seen_at=9999999999)
        result = er.to_db_params()
        assert result[7] == "relay.example.com"  # url
        assert result[8] == "clearnet"           # network
        assert result[9] == 1234567890           # discovered_at

    def test_seen_at_param(self, mock_event, relay):
        er = EventRelay(mock_event, relay, seen_at=9999999999)
        result = er.to_db_params()
        assert result[10] == 9999999999


class TestEquality:
    """Equality behavior."""

    def test_equal(self, mock_event, relay):
        er1 = EventRelay(mock_event, relay, seen_at=1234567890)
        er2 = EventRelay(mock_event, relay, seen_at=1234567890)
        assert er1 == er2

    def test_different_seen_at(self, mock_event, relay):
        er1 = EventRelay(mock_event, relay, seen_at=1234567890)
        er2 = EventRelay(mock_event, relay, seen_at=9999999999)
        assert er1 != er2

    def test_different_relay(self, mock_event):
        relay1 = Relay("wss://relay1.example.com", discovered_at=1234567890)
        relay2 = Relay("wss://relay2.example.com", discovered_at=1234567890)
        er1 = EventRelay(mock_event, relay1, seen_at=1234567890)
        er2 = EventRelay(mock_event, relay2, seen_at=1234567890)
        assert er1 != er2
