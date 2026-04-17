"""Unit tests for the EventObservation model."""

from dataclasses import FrozenInstanceError
from time import time
from unittest.mock import MagicMock

import pytest

from bigbrotr.models import Event, EventObservation, Relay
from bigbrotr.models.event import EventDbParams
from bigbrotr.models.event_observation import EventObservationDbParams


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
        tags='[["e","id"]]',
        content="Hello",
        sig=b"\xcc" * 64,
    )
    return mock


@pytest.fixture
def relay():
    return Relay("wss://relay.example.com", stored_at=1234567890)


@pytest.fixture
def event_observation(mock_event, relay):
    return EventObservation(mock_event, relay, observed_at=1234567891)


# =============================================================================
# Construction Tests
# =============================================================================


class TestConstruction:
    """EventObservation construction."""

    def test_with_event_and_relay(self, mock_event, relay):
        er = EventObservation(mock_event, relay)
        assert er.event is mock_event
        assert er.relay is relay

    def test_observed_at_defaults_to_now(self, mock_event, relay):
        before = int(time())
        er = EventObservation(mock_event, relay)
        after = int(time())
        assert before <= er.observed_at <= after

    def test_observed_at_explicit(self, mock_event, relay):
        er = EventObservation(mock_event, relay, observed_at=9999999999)
        assert er.observed_at == 9999999999

    def test_observed_at_zero(self, mock_event, relay):
        er = EventObservation(mock_event, relay, observed_at=0)
        assert er.observed_at == 0


# =============================================================================
# Immutability Tests
# =============================================================================


class TestImmutability:
    """Frozen dataclass behavior."""

    def test_event_mutation_blocked(self, mock_event, relay):
        er = EventObservation(mock_event, relay, observed_at=1234567890)
        with pytest.raises(FrozenInstanceError):
            er.event = MagicMock(spec=Event)

    def test_relay_mutation_blocked(self, mock_event, relay):
        er = EventObservation(mock_event, relay, observed_at=1234567890)
        with pytest.raises(FrozenInstanceError):
            er.relay = Relay("wss://other.relay", stored_at=9999999999)

    def test_observed_at_mutation_blocked(self, mock_event, relay):
        er = EventObservation(mock_event, relay, observed_at=1234567890)
        with pytest.raises(FrozenInstanceError):
            er.observed_at = 9999999999

    def test_new_attribute_blocked(self, mock_event, relay):
        er = EventObservation(mock_event, relay)
        with pytest.raises((AttributeError, TypeError, FrozenInstanceError)):
            er.new_attr = "value"


# =============================================================================
# to_db_params Tests
# =============================================================================


class TestToDbParams:
    """EventObservation.to_db_params() method."""

    def test_returns_event_observation_db_params(self, mock_event, relay):
        er = EventObservation(mock_event, relay, observed_at=1234567890)
        result = er.to_db_params()
        assert isinstance(result, EventObservationDbParams)
        assert isinstance(result, tuple)
        assert len(result) == 11

    def test_event_params_first_seven(self, mock_event, relay):
        er = EventObservation(mock_event, relay, observed_at=1234567890)
        result = er.to_db_params()
        assert result.event_id == b"\xaa" * 32
        assert result.pubkey == b"\xbb" * 32
        assert result.created_at == 1234567890
        assert result.kind == 1
        assert result.tags == '[["e","id"]]'
        assert result.content == "Hello"
        assert result.sig == b"\xcc" * 64

    def test_relay_params_next_three(self, mock_event, relay):
        er = EventObservation(mock_event, relay, observed_at=9999999999)
        result = er.to_db_params()
        assert result.relay_url == "wss://relay.example.com"
        assert result.relay_network == "clearnet"
        assert result.relay_stored_at == 1234567890

    def test_observed_at_param_last(self, mock_event, relay):
        er = EventObservation(mock_event, relay, observed_at=9999999999)
        result = er.to_db_params()
        assert result.observed_at == 9999999999

    def test_calls_event_to_db_params(self, mock_event, relay):
        er = EventObservation(mock_event, relay, observed_at=1234567890)
        er.to_db_params()
        assert mock_event.to_db_params.call_count == 1

    def test_with_different_relay_networks(self, mock_event):
        from tests.fixtures.relays import ONION_HOST

        tor_relay = Relay(f"ws://{ONION_HOST}.onion", stored_at=1234567890)
        er = EventObservation(mock_event, tor_relay, observed_at=1234567890)
        result = er.to_db_params()
        assert result.relay_url == f"ws://{ONION_HOST}.onion"
        assert result.relay_network == "tor"

    def test_caching(self, mock_event, relay):
        er = EventObservation(mock_event, relay, observed_at=1234567890)
        assert er.to_db_params() is er.to_db_params()


# =============================================================================
# Equality Tests
# =============================================================================


class TestEquality:
    """Equality behavior."""

    def test_equal(self, mock_event, relay):
        er1 = EventObservation(mock_event, relay, observed_at=1234567890)
        er2 = EventObservation(mock_event, relay, observed_at=1234567890)
        assert er1 == er2

    def test_different_observed_at(self, mock_event, relay):
        er1 = EventObservation(mock_event, relay, observed_at=1234567890)
        er2 = EventObservation(mock_event, relay, observed_at=9999999999)
        assert er1 != er2

    def test_different_relay(self, mock_event):
        relay1 = Relay("wss://relay1.example.com", stored_at=1234567890)
        relay2 = Relay("wss://relay2.example.com", stored_at=1234567890)
        er1 = EventObservation(mock_event, relay1, observed_at=1234567890)
        er2 = EventObservation(mock_event, relay2, observed_at=1234567890)
        assert er1 != er2

    def test_different_event(self, relay):
        mock_event1 = MagicMock(spec=Event)
        mock_event1.to_db_params.return_value = EventDbParams(
            id=b"\xaa" * 32,
            pubkey=b"\xbb" * 32,
            created_at=1234567890,
            kind=1,
            tags="[]",
            content="Hello",
            sig=b"\xcc" * 64,
        )
        mock_event2 = MagicMock(spec=Event)
        mock_event2.to_db_params.return_value = EventDbParams(
            id=b"\xdd" * 32,
            pubkey=b"\xee" * 32,
            created_at=1234567891,
            kind=1,
            tags="[]",
            content="World",
            sig=b"\xff" * 64,
        )
        er1 = EventObservation(mock_event1, relay, observed_at=1234567890)
        er2 = EventObservation(mock_event2, relay, observed_at=1234567890)
        assert er1 != er2


# =============================================================================
# Edge Cases Tests
# =============================================================================


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_with_port_and_path_relay(self, mock_event):
        relay = Relay("wss://relay.example.com:8080/nostr", stored_at=1234567890)
        er = EventObservation(mock_event, relay, observed_at=1234567890)
        result = er.to_db_params()
        assert result.relay_url == "wss://relay.example.com:8080/nostr"

    def test_with_ipv6_relay(self, mock_event):
        relay = Relay("wss://[2001:4860:4860::8888]", stored_at=1234567890)
        er = EventObservation(mock_event, relay, observed_at=1234567890)
        result = er.to_db_params()
        assert result.relay_url == "wss://[2001:4860:4860::8888]"
        assert result.relay_network == "clearnet"

    def test_with_i2p_relay(self, mock_event):
        relay = Relay("ws://relay.i2p", stored_at=1234567890)
        er = EventObservation(mock_event, relay, observed_at=1234567890)
        result = er.to_db_params()
        assert result.relay_url == "ws://relay.i2p"
        assert result.relay_network == "i2p"

    def test_with_loki_relay(self, mock_event):
        from tests.fixtures.relays import LOKI_HOST

        relay = Relay(f"ws://{LOKI_HOST}.loki", stored_at=1234567890)
        er = EventObservation(mock_event, relay, observed_at=1234567890)
        result = er.to_db_params()
        assert result.relay_url == f"ws://{LOKI_HOST}.loki"
        assert result.relay_network == "loki"


# =============================================================================
# Type Validation Tests
# =============================================================================


class TestTypeValidation:
    """Runtime type validation in __post_init__."""

    def test_event_non_event_rejected(self):
        relay = Relay("wss://relay.example.com", stored_at=1234567890)
        with pytest.raises(TypeError, match="event must be an Event"):
            EventObservation(event="not an event", relay=relay, observed_at=123)  # type: ignore[arg-type]

    def test_relay_non_relay_rejected(self, mock_event):
        with pytest.raises(TypeError, match="relay must be a Relay"):
            EventObservation(event=mock_event, relay="not a relay", observed_at=123)  # type: ignore[arg-type]

    def test_observed_at_non_int_rejected(self, mock_event):
        relay = Relay("wss://relay.example.com", stored_at=1234567890)
        with pytest.raises(TypeError, match="observed_at must be an int"):
            EventObservation(event=mock_event, relay=relay, observed_at="abc")  # type: ignore[arg-type]

    def test_observed_at_bool_rejected(self, mock_event):
        relay = Relay("wss://relay.example.com", stored_at=1234567890)
        with pytest.raises(TypeError, match="observed_at must be an int"):
            EventObservation(event=mock_event, relay=relay, observed_at=True)  # type: ignore[arg-type]

    def test_observed_at_negative_rejected(self, mock_event):
        relay = Relay("wss://relay.example.com", stored_at=1234567890)
        with pytest.raises(ValueError, match="observed_at must be non-negative"):
            EventObservation(event=mock_event, relay=relay, observed_at=-1)
