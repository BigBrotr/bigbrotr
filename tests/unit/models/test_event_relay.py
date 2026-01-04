"""
Unit tests for models.event_relay module.

Tests:
- EventRelay construction from Event and Relay
- to_db_params() serialization for bulk insert
- seen_at timestamp handling
- Immutability enforcement
"""

from time import time
from unittest.mock import MagicMock

import pytest

from models import Event, EventRelay, Relay
from models.event import EventDbParams


@pytest.fixture
def mock_event():
    """Create a mock Event."""
    mock = MagicMock(spec=Event)
    mock.to_db_params.return_value = EventDbParams(
        id=b"\xaa" * 32,
        pubkey=b"\xbb" * 32,
        created_at=1234567890,
        kind=1,
        tags_json='[["e","id"]]',
        content="Hello",
        sig=b"\xcc" * 64,
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
        with pytest.raises((AttributeError, TypeError)):
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
        assert result[2] == 1234567890  # created_at
        assert result[3] == 1  # kind
        assert result[4] == '[["e","id"]]'  # tags
        assert result[5] == "Hello"  # content
        assert result[6] == b"\xcc" * 64  # sig

    def test_relay_params(self, mock_event, relay):
        er = EventRelay(mock_event, relay, seen_at=9999999999)
        result = er.to_db_params()
        assert result[7] == "relay.example.com"  # url
        assert result[8] == "clearnet"  # network
        assert result[9] == 1234567890  # discovered_at

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


class TestFromDbParams:
    """Reconstruction from database parameters."""

    def test_reconstructs_relay(self):
        """from_db_params should reconstruct relay correctly."""
        er = EventRelay.from_db_params(
            event_id=b"\xaa" * 32,
            pubkey=b"\xbb" * 32,
            created_at=1234567890,
            kind=1,
            tags_json="[]",
            content="test",
            sig=b"\xcc" * 64,
            relay_url="relay.example.com",
            relay_network="clearnet",
            relay_discovered_at=1234567890,
            seen_at=9999999999,
        )
        assert er.relay.url_without_scheme == "relay.example.com"
        assert er.relay.network == "clearnet"
        assert er.seen_at == 9999999999

    def test_to_db_params_structure(self, mock_event, relay):
        """Verify to_db_params output can be used with from_db_params."""
        er = EventRelay(mock_event, relay, seen_at=1234567890)
        params = er.to_db_params()
        assert len(params) == 11
        # Verify types match from_db_params signature
        assert isinstance(params[0], bytes)  # event_id
        assert isinstance(params[1], bytes)  # pubkey
        assert isinstance(params[2], int)  # created_at
        assert isinstance(params[3], int)  # kind
        assert isinstance(params[4], str)  # tags_json
        assert isinstance(params[5], str)  # content
        assert isinstance(params[6], bytes)  # sig
        assert isinstance(params[7], str)  # relay_url
        assert isinstance(params[8], str)  # relay_network
        assert isinstance(params[9], int)  # relay_discovered_at
        assert isinstance(params[10], int)  # seen_at
