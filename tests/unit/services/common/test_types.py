"""Unit tests for services.common.types module.

Tests:
- Candidate: creation, failures property, frozen immutability
- EventRelayCursor: valid combinations, event_id-without-seen_at rejection, frozen
- EventCursor: valid combinations, event_id-without-created_at rejection, frozen
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from bigbrotr.models import Relay
from bigbrotr.services.common.types import Candidate, EventCursor, EventRelayCursor


# ============================================================================
# Candidate Tests
# ============================================================================


class TestCandidate:
    """Tests for Candidate dataclass."""

    def test_creation(self) -> None:
        """Test basic Candidate construction."""
        relay = Relay("wss://relay.example.com")
        data = {"network": "clearnet", "failures": 3}
        candidate = Candidate(relay=relay, data=data)

        assert candidate.relay is relay
        assert candidate.data is data

    def test_failures_default(self) -> None:
        """Test failures property returns 0 when key is absent."""
        relay = Relay("wss://relay.example.com")
        candidate = Candidate(relay=relay, data={})

        assert candidate.failures == 0

    def test_failures_from_data(self) -> None:
        """Test failures property reads from data mapping."""
        relay = Relay("wss://relay.example.com")
        candidate = Candidate(relay=relay, data={"failures": 5})

        assert candidate.failures == 5

    def test_frozen(self) -> None:
        """Test that Candidate instances are immutable."""
        relay = Relay("wss://relay.example.com")
        candidate = Candidate(relay=relay, data={})

        with pytest.raises(FrozenInstanceError):
            candidate.relay = Relay("wss://other.example.com")  # type: ignore[misc]


# ============================================================================
# EventRelayCursor Tests
# ============================================================================


class TestEventRelayCursor:
    """Tests for EventRelayCursor dataclass."""

    def test_no_cursor(self) -> None:
        """Test cursor with no position (scan from beginning)."""
        cursor = EventRelayCursor(relay_url="wss://relay.example.com")

        assert cursor.relay_url == "wss://relay.example.com"
        assert cursor.seen_at is None
        assert cursor.event_id is None

    def test_timestamp_only(self) -> None:
        """Test cursor with timestamp but no event_id."""
        cursor = EventRelayCursor(relay_url="wss://relay.example.com", seen_at=1700000000)

        assert cursor.seen_at == 1700000000
        assert cursor.event_id is None

    def test_full_cursor(self) -> None:
        """Test cursor with both timestamp and event_id."""
        event_id = b"\x00" * 32
        cursor = EventRelayCursor(
            relay_url="wss://relay.example.com",
            seen_at=1700000000,
            event_id=event_id,
        )

        assert cursor.seen_at == 1700000000
        assert cursor.event_id == event_id

    def test_event_id_without_seen_at_raises(self) -> None:
        """Test that event_id without seen_at raises ValueError."""
        with pytest.raises(ValueError, match="event_id requires seen_at"):
            EventRelayCursor(relay_url="wss://relay.example.com", event_id=b"\x00" * 32)

    def test_frozen(self) -> None:
        """Test that EventRelayCursor instances are immutable."""
        cursor = EventRelayCursor(relay_url="wss://relay.example.com")

        with pytest.raises(FrozenInstanceError):
            cursor.seen_at = 123  # type: ignore[misc]


# ============================================================================
# EventCursor Tests
# ============================================================================


class TestEventCursor:
    """Tests for EventCursor dataclass."""

    def test_no_cursor(self) -> None:
        """Test cursor with no position (scan from beginning)."""
        cursor = EventCursor()

        assert cursor.created_at is None
        assert cursor.event_id is None

    def test_timestamp_only(self) -> None:
        """Test cursor with timestamp but no event_id."""
        cursor = EventCursor(created_at=1700000000)

        assert cursor.created_at == 1700000000
        assert cursor.event_id is None

    def test_full_cursor(self) -> None:
        """Test cursor with both timestamp and event_id."""
        event_id = b"\x00" * 32
        cursor = EventCursor(created_at=1700000000, event_id=event_id)

        assert cursor.created_at == 1700000000
        assert cursor.event_id == event_id

    def test_event_id_without_created_at_raises(self) -> None:
        """Test that event_id without created_at raises ValueError."""
        with pytest.raises(ValueError, match="event_id requires created_at"):
            EventCursor(event_id=b"\x00" * 32)

    def test_frozen(self) -> None:
        """Test that EventCursor instances are immutable."""
        cursor = EventCursor()

        with pytest.raises(FrozenInstanceError):
            cursor.created_at = 123  # type: ignore[misc]
