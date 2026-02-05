"""
Unit tests for models.event_relay module.

Tests:
- EventRelay construction from Event and Relay
- EventRelayDbParams NamedTuple structure (11 fields)
- to_db_params() serialization for database bulk insert
- from_db_params() deserialization from database
- seen_at timestamp handling (default vs explicit)
- Immutability enforcement (frozen dataclass)
- Equality behavior
"""

from dataclasses import FrozenInstanceError
from time import time
from unittest.mock import MagicMock

import pytest

from models import Event, EventRelay, Relay
from models.event import EventDbParams
from models.event_relay import EventRelayDbParams
from models.relay import NetworkType


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_event():
    """Create a mock Event with proper to_db_params return value."""
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


@pytest.fixture
def event_relay(mock_event, relay):
    """Create an EventRelay with explicit seen_at."""
    return EventRelay(mock_event, relay, seen_at=1234567891)


# =============================================================================
# EventRelayDbParams Tests
# =============================================================================


class TestEventRelayDbParams:
    """Test EventRelayDbParams NamedTuple."""

    def test_is_named_tuple(self):
        """EventRelayDbParams is a NamedTuple with 11 fields."""
        params = EventRelayDbParams(
            event_id=b"\xaa" * 32,
            pubkey=b"\xbb" * 32,
            created_at=1234567890,
            kind=1,
            tags_json="[]",
            content="Test",
            sig=b"\xcc" * 64,
            relay_url="wss://relay.example.com",
            relay_network="clearnet",
            relay_discovered_at=1234567890,
            seen_at=1234567891,
        )
        assert isinstance(params, tuple)
        assert len(params) == 11

    def test_field_access_by_name(self):
        """Fields are accessible by name."""
        params = EventRelayDbParams(
            event_id=b"\xaa" * 32,
            pubkey=b"\xbb" * 32,
            created_at=1234567890,
            kind=1,
            tags_json='[["t","test"]]',
            content="Content",
            sig=b"\xcc" * 64,
            relay_url="wss://relay.example.com",
            relay_network="clearnet",
            relay_discovered_at=1000000000,
            seen_at=2000000000,
        )
        # Event fields
        assert params.event_id == b"\xaa" * 32
        assert params.pubkey == b"\xbb" * 32
        assert params.created_at == 1234567890
        assert params.kind == 1
        assert params.tags_json == '[["t","test"]]'
        assert params.content == "Content"
        assert params.sig == b"\xcc" * 64
        # Relay fields
        assert params.relay_url == "wss://relay.example.com"
        assert params.relay_network == "clearnet"
        assert params.relay_discovered_at == 1000000000
        # Junction field
        assert params.seen_at == 2000000000

    def test_field_access_by_index(self):
        """Fields are accessible by index."""
        params = EventRelayDbParams(
            event_id=b"\x00" * 32,
            pubkey=b"\x01" * 32,
            created_at=1234567890,
            kind=7,
            tags_json="[]",
            content="",
            sig=b"\x02" * 64,
            relay_url="wss://test.relay",
            relay_network="tor",
            relay_discovered_at=1111111111,
            seen_at=2222222222,
        )
        assert params[0] == b"\x00" * 32  # event_id
        assert params[1] == b"\x01" * 32  # pubkey
        assert params[2] == 1234567890  # created_at
        assert params[3] == 7  # kind
        assert params[4] == "[]"  # tags_json
        assert params[5] == ""  # content
        assert params[6] == b"\x02" * 64  # sig
        assert params[7] == "wss://test.relay"  # relay_url
        assert params[8] == "tor"  # relay_network
        assert params[9] == 1111111111  # relay_discovered_at
        assert params[10] == 2222222222  # seen_at

    def test_immutability(self):
        """EventRelayDbParams is immutable (NamedTuple)."""
        params = EventRelayDbParams(
            event_id=b"\xaa" * 32,
            pubkey=b"\xbb" * 32,
            created_at=1234567890,
            kind=1,
            tags_json="[]",
            content="Test",
            sig=b"\xcc" * 64,
            relay_url="wss://relay.example.com",
            relay_network="clearnet",
            relay_discovered_at=1234567890,
            seen_at=1234567891,
        )
        with pytest.raises(AttributeError):
            params.seen_at = 9999999999


# =============================================================================
# Construction Tests
# =============================================================================


class TestConstruction:
    """EventRelay construction."""

    def test_with_event_and_relay(self, mock_event, relay):
        """Constructs with Event and Relay references."""
        er = EventRelay(mock_event, relay)
        assert er.event is mock_event
        assert er.relay is relay

    def test_seen_at_defaults_to_now(self, mock_event, relay):
        """seen_at defaults to current time if not provided."""
        before = int(time())
        er = EventRelay(mock_event, relay)
        after = int(time())
        assert before <= er.seen_at <= after

    def test_seen_at_explicit(self, mock_event, relay):
        """Explicit seen_at is preserved."""
        er = EventRelay(mock_event, relay, seen_at=9999999999)
        assert er.seen_at == 9999999999

    def test_seen_at_zero(self, mock_event, relay):
        """seen_at can be zero (epoch)."""
        er = EventRelay(mock_event, relay, seen_at=0)
        assert er.seen_at == 0


# =============================================================================
# Immutability Tests
# =============================================================================


class TestImmutability:
    """Frozen dataclass behavior."""

    def test_event_mutation_blocked(self, mock_event, relay):
        """Cannot modify event attribute."""
        er = EventRelay(mock_event, relay, seen_at=1234567890)
        new_event = MagicMock(spec=Event)
        with pytest.raises(FrozenInstanceError):
            er.event = new_event

    def test_relay_mutation_blocked(self, mock_event, relay):
        """Cannot modify relay attribute."""
        er = EventRelay(mock_event, relay, seen_at=1234567890)
        new_relay = Relay("wss://other.relay", discovered_at=9999999999)
        with pytest.raises(FrozenInstanceError):
            er.relay = new_relay

    def test_seen_at_mutation_blocked(self, mock_event, relay):
        """Cannot modify seen_at attribute."""
        er = EventRelay(mock_event, relay, seen_at=1234567890)
        with pytest.raises(FrozenInstanceError):
            er.seen_at = 9999999999

    def test_new_attribute_blocked(self, mock_event, relay):
        """Cannot add new attributes."""
        er = EventRelay(mock_event, relay)
        with pytest.raises((AttributeError, TypeError, FrozenInstanceError)):
            er.new_attr = "value"


# =============================================================================
# to_db_params Tests
# =============================================================================


class TestToDbParams:
    """EventRelay.to_db_params() method."""

    def test_returns_event_relay_db_params(self, mock_event, relay):
        """Returns EventRelayDbParams NamedTuple with 11 elements."""
        er = EventRelay(mock_event, relay, seen_at=1234567890)
        result = er.to_db_params()
        assert isinstance(result, EventRelayDbParams)
        assert isinstance(result, tuple)
        assert len(result) == 11

    def test_event_params_first_seven(self, mock_event, relay):
        """First 7 elements are event parameters."""
        er = EventRelay(mock_event, relay, seen_at=1234567890)
        result = er.to_db_params()
        assert result.event_id == b"\xaa" * 32
        assert result.pubkey == b"\xbb" * 32
        assert result.created_at == 1234567890
        assert result.kind == 1
        assert result.tags_json == '[["e","id"]]'
        assert result.content == "Hello"
        assert result.sig == b"\xcc" * 64

    def test_relay_params_next_three(self, mock_event, relay):
        """Elements 8-10 are relay parameters."""
        er = EventRelay(mock_event, relay, seen_at=9999999999)
        result = er.to_db_params()
        assert result.relay_url == "wss://relay.example.com"
        assert result.relay_network == "clearnet"
        assert result.relay_discovered_at == 1234567890

    def test_seen_at_param_last(self, mock_event, relay):
        """Last element (11th) is seen_at."""
        er = EventRelay(mock_event, relay, seen_at=9999999999)
        result = er.to_db_params()
        assert result.seen_at == 9999999999

    def test_calls_event_to_db_params(self, mock_event, relay):
        """Delegates to event.to_db_params()."""
        er = EventRelay(mock_event, relay, seen_at=1234567890)
        er.to_db_params()
        # Called twice: once in __post_init__ (fail-fast), once here
        assert mock_event.to_db_params.call_count == 2

    def test_with_different_relay_networks(self, mock_event):
        """Works with different relay network types."""
        tor_relay = Relay("wss://abc123.onion", discovered_at=1234567890)
        er = EventRelay(mock_event, tor_relay, seen_at=1234567890)
        result = er.to_db_params()
        # Tor relay uses ws:// scheme
        assert result.relay_url == "ws://abc123.onion"
        assert result.relay_network == "tor"


# =============================================================================
# from_db_params Tests
# =============================================================================


class TestFromDbParams:
    """EventRelay.from_db_params() deserialization."""

    def test_reconstructs_relay(self):
        """from_db_params should reconstruct relay correctly."""
        params = EventRelayDbParams(
            event_id=b"\xaa" * 32,
            pubkey=b"\xbb" * 32,
            created_at=1234567890,
            kind=1,
            tags_json="[]",
            content="test",
            sig=b"\xcc" * 64,
            relay_url="wss://relay.example.com",
            relay_network="clearnet",
            relay_discovered_at=1234567890,
            seen_at=9999999999,
        )
        er = EventRelay.from_db_params(params)
        assert er.relay.url == "wss://relay.example.com"
        assert er.relay.network == NetworkType.CLEARNET
        assert er.relay.discovered_at == 1234567890

    def test_reconstructs_seen_at(self):
        """from_db_params preserves seen_at timestamp."""
        params = EventRelayDbParams(
            event_id=b"\xaa" * 32,
            pubkey=b"\xbb" * 32,
            created_at=1234567890,
            kind=1,
            tags_json="[]",
            content="test",
            sig=b"\xcc" * 64,
            relay_url="wss://relay.example.com",
            relay_network="clearnet",
            relay_discovered_at=1234567890,
            seen_at=9999999999,
        )
        er = EventRelay.from_db_params(params)
        assert er.seen_at == 9999999999

    def test_with_tor_relay(self):
        """from_db_params works with Tor relay."""
        params = EventRelayDbParams(
            event_id=b"\xaa" * 32,
            pubkey=b"\xbb" * 32,
            created_at=1234567890,
            kind=1,
            tags_json="[]",
            content="test",
            sig=b"\xcc" * 64,
            relay_url="ws://abc123.onion",
            relay_network="tor",
            relay_discovered_at=1234567890,
            seen_at=1234567891,
        )
        er = EventRelay.from_db_params(params)
        assert er.relay.network == NetworkType.TOR
        assert er.relay.scheme == "ws"

    def test_to_db_params_structure(self, mock_event, relay):
        """Verify to_db_params output structure matches from_db_params signature."""
        er = EventRelay(mock_event, relay, seen_at=1234567890)
        params = er.to_db_params()
        assert len(params) == 11
        # Verify types match from_db_params signature
        assert isinstance(params.event_id, bytes)
        assert isinstance(params.pubkey, bytes)
        assert isinstance(params.created_at, int)
        assert isinstance(params.kind, int)
        assert isinstance(params.tags_json, str)
        assert isinstance(params.content, str)
        assert isinstance(params.sig, bytes)
        assert isinstance(params.relay_url, str)
        assert isinstance(params.relay_network, str)
        assert isinstance(params.relay_discovered_at, int)
        assert isinstance(params.seen_at, int)


# =============================================================================
# Equality Tests
# =============================================================================


class TestEquality:
    """Equality behavior."""

    def test_equal(self, mock_event, relay):
        """EventRelays with same attributes are equal."""
        er1 = EventRelay(mock_event, relay, seen_at=1234567890)
        er2 = EventRelay(mock_event, relay, seen_at=1234567890)
        assert er1 == er2

    def test_different_seen_at(self, mock_event, relay):
        """EventRelays with different seen_at are not equal."""
        er1 = EventRelay(mock_event, relay, seen_at=1234567890)
        er2 = EventRelay(mock_event, relay, seen_at=9999999999)
        assert er1 != er2

    def test_different_relay(self, mock_event):
        """EventRelays with different relays are not equal."""
        relay1 = Relay("wss://relay1.example.com", discovered_at=1234567890)
        relay2 = Relay("wss://relay2.example.com", discovered_at=1234567890)
        er1 = EventRelay(mock_event, relay1, seen_at=1234567890)
        er2 = EventRelay(mock_event, relay2, seen_at=1234567890)
        assert er1 != er2

    def test_different_event(self, relay):
        """EventRelays with different events are not equal."""
        mock_event1 = MagicMock(spec=Event)
        mock_event1.to_db_params.return_value = EventDbParams(
            id=b"\xaa" * 32,
            pubkey=b"\xbb" * 32,
            created_at=1234567890,
            kind=1,
            tags_json="[]",
            content="Hello",
            sig=b"\xcc" * 64,
        )
        mock_event2 = MagicMock(spec=Event)
        mock_event2.to_db_params.return_value = EventDbParams(
            id=b"\xdd" * 32,
            pubkey=b"\xee" * 32,
            created_at=1234567891,
            kind=1,
            tags_json="[]",
            content="World",
            sig=b"\xff" * 64,
        )
        er1 = EventRelay(mock_event1, relay, seen_at=1234567890)
        er2 = EventRelay(mock_event2, relay, seen_at=1234567890)
        assert er1 != er2


# =============================================================================
# Edge Cases Tests
# =============================================================================


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_with_port_and_path_relay(self, mock_event):
        """Works with relay that has port and path."""
        relay = Relay("wss://relay.example.com:8080/nostr", discovered_at=1234567890)
        er = EventRelay(mock_event, relay, seen_at=1234567890)
        result = er.to_db_params()
        assert result.relay_url == "wss://relay.example.com:8080/nostr"

    def test_with_ipv6_relay(self, mock_event):
        """Works with IPv6 relay."""
        relay = Relay("wss://[2001:4860:4860::8888]", discovered_at=1234567890)
        er = EventRelay(mock_event, relay, seen_at=1234567890)
        result = er.to_db_params()
        assert result.relay_url == "wss://[2001:4860:4860::8888]"
        assert result.relay_network == "clearnet"

    def test_with_i2p_relay(self, mock_event):
        """Works with I2P relay."""
        relay = Relay("wss://relay.i2p", discovered_at=1234567890)
        er = EventRelay(mock_event, relay, seen_at=1234567890)
        result = er.to_db_params()
        assert result.relay_url == "ws://relay.i2p"
        assert result.relay_network == "i2p"

    def test_with_loki_relay(self, mock_event):
        """Works with Lokinet relay."""
        relay = Relay("wss://relay.loki", discovered_at=1234567890)
        er = EventRelay(mock_event, relay, seen_at=1234567890)
        result = er.to_db_params()
        assert result.relay_url == "ws://relay.loki"
        assert result.relay_network == "loki"
