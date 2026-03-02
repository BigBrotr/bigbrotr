"""Unit tests for services.common.types module.

Tests:
- Checkpoint: creation, frozen immutability, subclass inheritance
- ApiCheckpoint, MonitorCheckpoint, PublishCheckpoint: creation, isinstance
- CandidateCheckpoint: creation, failures default, frozen immutability, isinstance
- Cursor: base class, subclass inheritance
- EventRelayCursor: valid combinations, partial cursor rejection, frozen, isinstance
- EventCursor: valid combinations, partial cursor rejection, frozen, isinstance
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from bigbrotr.models.constants import NetworkType
from bigbrotr.services.common.types import (
    ApiCheckpoint,
    CandidateCheckpoint,
    Checkpoint,
    Cursor,
    EventCursor,
    EventRelayCursor,
    MonitorCheckpoint,
    PublishCheckpoint,
)


# ============================================================================
# Checkpoint Tests
# ============================================================================


class TestCheckpoint:
    """Tests for Checkpoint dataclass."""

    def test_creation(self) -> None:
        """Test basic Checkpoint construction."""
        cp = Checkpoint(key="wss://relay.example.com", timestamp=1700000000)

        assert cp.key == "wss://relay.example.com"
        assert cp.timestamp == 1700000000

    def test_frozen(self) -> None:
        """Test that Checkpoint instances are immutable."""
        cp = Checkpoint(key="wss://relay.example.com", timestamp=1700000000)

        with pytest.raises(FrozenInstanceError):
            cp.timestamp = 0  # type: ignore[misc]


# ============================================================================
# Checkpoint Subclass Tests
# ============================================================================


class TestApiCheckpoint:
    """Tests for ApiCheckpoint subclass."""

    def test_creation(self) -> None:
        """Test ApiCheckpoint construction."""
        cp = ApiCheckpoint(key="https://api.nostr.watch/v1/online", timestamp=1700000000)

        assert cp.key == "https://api.nostr.watch/v1/online"
        assert cp.timestamp == 1700000000

    def test_isinstance_checkpoint(self) -> None:
        """Test that ApiCheckpoint is a Checkpoint."""
        cp = ApiCheckpoint(key="https://api.example.com", timestamp=1700000000)

        assert isinstance(cp, Checkpoint)

    def test_not_isinstance_other_subclasses(self) -> None:
        """Test that ApiCheckpoint is not a MonitorCheckpoint or PublishCheckpoint."""
        cp = ApiCheckpoint(key="https://api.example.com", timestamp=1700000000)

        assert not isinstance(cp, MonitorCheckpoint)
        assert not isinstance(cp, PublishCheckpoint)

    def test_frozen(self) -> None:
        """Test that ApiCheckpoint instances are immutable."""
        cp = ApiCheckpoint(key="https://api.example.com", timestamp=1700000000)

        with pytest.raises(FrozenInstanceError):
            cp.timestamp = 0  # type: ignore[misc]


class TestMonitorCheckpoint:
    """Tests for MonitorCheckpoint subclass."""

    def test_creation(self) -> None:
        """Test MonitorCheckpoint construction."""
        cp = MonitorCheckpoint(key="wss://relay.example.com", timestamp=1700000000)

        assert cp.key == "wss://relay.example.com"
        assert cp.timestamp == 1700000000

    def test_isinstance_checkpoint(self) -> None:
        """Test that MonitorCheckpoint is a Checkpoint."""
        cp = MonitorCheckpoint(key="wss://relay.example.com", timestamp=1700000000)

        assert isinstance(cp, Checkpoint)

    def test_not_isinstance_other_subclasses(self) -> None:
        """Test that MonitorCheckpoint is not an ApiCheckpoint or PublishCheckpoint."""
        cp = MonitorCheckpoint(key="wss://relay.example.com", timestamp=1700000000)

        assert not isinstance(cp, ApiCheckpoint)
        assert not isinstance(cp, PublishCheckpoint)


class TestPublishCheckpoint:
    """Tests for PublishCheckpoint subclass."""

    def test_creation(self) -> None:
        """Test PublishCheckpoint construction."""
        cp = PublishCheckpoint(key="last_announcement", timestamp=1700000000)

        assert cp.key == "last_announcement"
        assert cp.timestamp == 1700000000

    def test_isinstance_checkpoint(self) -> None:
        """Test that PublishCheckpoint is a Checkpoint."""
        cp = PublishCheckpoint(key="last_announcement", timestamp=1700000000)

        assert isinstance(cp, Checkpoint)

    def test_not_isinstance_other_subclasses(self) -> None:
        """Test that PublishCheckpoint is not an ApiCheckpoint or MonitorCheckpoint."""
        cp = PublishCheckpoint(key="last_announcement", timestamp=1700000000)

        assert not isinstance(cp, ApiCheckpoint)
        assert not isinstance(cp, MonitorCheckpoint)


# ============================================================================
# CandidateCheckpoint Tests
# ============================================================================


class TestCandidateCheckpoint:
    """Tests for CandidateCheckpoint dataclass."""

    def test_creation(self) -> None:
        """Test basic CandidateCheckpoint construction."""
        candidate = CandidateCheckpoint(
            key="wss://relay.example.com",
            timestamp=1700000000,
            network=NetworkType.CLEARNET,
            failures=3,
        )

        assert candidate.key == "wss://relay.example.com"
        assert candidate.timestamp == 1700000000
        assert candidate.network == NetworkType.CLEARNET
        assert candidate.failures == 3

    def test_failures_default_zero(self) -> None:
        """Test CandidateCheckpoint defaults to zero failures."""
        candidate = CandidateCheckpoint(
            key="wss://relay.example.com",
            timestamp=1700000000,
            network=NetworkType.CLEARNET,
        )

        assert candidate.failures == 0

    def test_isinstance_checkpoint(self) -> None:
        """Test that CandidateCheckpoint is a Checkpoint."""
        candidate = CandidateCheckpoint(
            key="wss://relay.example.com",
            timestamp=1700000000,
            network=NetworkType.CLEARNET,
        )

        assert isinstance(candidate, Checkpoint)

    def test_not_isinstance_other_subclasses(self) -> None:
        """Test that CandidateCheckpoint is not an ApiCheckpoint, MonitorCheckpoint, or PublishCheckpoint."""
        candidate = CandidateCheckpoint(
            key="wss://relay.example.com",
            timestamp=1700000000,
            network=NetworkType.CLEARNET,
        )

        assert not isinstance(candidate, ApiCheckpoint)
        assert not isinstance(candidate, MonitorCheckpoint)
        assert not isinstance(candidate, PublishCheckpoint)

    def test_frozen(self) -> None:
        """Test that CandidateCheckpoint instances are immutable."""
        candidate = CandidateCheckpoint(
            key="wss://relay.example.com",
            timestamp=1700000000,
            network=NetworkType.CLEARNET,
        )

        with pytest.raises(FrozenInstanceError):
            candidate.network = NetworkType.TOR  # type: ignore[misc]


# ============================================================================
# Cursor Tests
# ============================================================================


class TestCursor:
    """Tests for Cursor base class."""

    def test_creation(self) -> None:
        """Test empty Cursor construction."""
        cursor = Cursor()

        assert isinstance(cursor, Cursor)


# ============================================================================
# EventRelayCursor Tests
# ============================================================================


class TestEventRelayCursor:
    """Tests for EventRelayCursor dataclass."""

    def test_isinstance_cursor(self) -> None:
        """Test that EventRelayCursor is a Cursor."""
        cursor = EventRelayCursor(relay_url="wss://relay.example.com")

        assert isinstance(cursor, Cursor)

    def test_not_isinstance_event_cursor(self) -> None:
        """Test that EventRelayCursor is not an EventCursor."""
        cursor = EventRelayCursor(relay_url="wss://relay.example.com")

        assert not isinstance(cursor, EventCursor)

    def test_no_cursor(self) -> None:
        """Test cursor with no position (scan from beginning)."""
        cursor = EventRelayCursor(relay_url="wss://relay.example.com")

        assert cursor.relay_url == "wss://relay.example.com"
        assert cursor.seen_at is None
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

    def test_seen_at_without_event_id_raises(self) -> None:
        """Test that seen_at without event_id raises ValueError."""
        with pytest.raises(ValueError, match="must both be None or both be set"):
            EventRelayCursor(relay_url="wss://relay.example.com", seen_at=1700000000)

    def test_event_id_without_seen_at_raises(self) -> None:
        """Test that event_id without seen_at raises ValueError."""
        with pytest.raises(ValueError, match="must both be None or both be set"):
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

    def test_isinstance_cursor(self) -> None:
        """Test that EventCursor is a Cursor."""
        cursor = EventCursor()

        assert isinstance(cursor, Cursor)

    def test_not_isinstance_event_relay_cursor(self) -> None:
        """Test that EventCursor is not an EventRelayCursor."""
        cursor = EventCursor()

        assert not isinstance(cursor, EventRelayCursor)

    def test_no_cursor(self) -> None:
        """Test cursor with no position (scan from beginning)."""
        cursor = EventCursor()

        assert cursor.created_at is None
        assert cursor.event_id is None

    def test_full_cursor(self) -> None:
        """Test cursor with both timestamp and event_id."""
        event_id = b"\x00" * 32
        cursor = EventCursor(created_at=1700000000, event_id=event_id)

        assert cursor.created_at == 1700000000
        assert cursor.event_id == event_id

    def test_created_at_without_event_id_raises(self) -> None:
        """Test that created_at without event_id raises ValueError."""
        with pytest.raises(ValueError, match="must both be None or both be set"):
            EventCursor(created_at=1700000000)

    def test_event_id_without_created_at_raises(self) -> None:
        """Test that event_id without created_at raises ValueError."""
        with pytest.raises(ValueError, match="must both be None or both be set"):
            EventCursor(event_id=b"\x00" * 32)

    def test_frozen(self) -> None:
        """Test that EventCursor instances are immutable."""
        cursor = EventCursor()

        with pytest.raises(FrozenInstanceError):
            cursor.created_at = 123  # type: ignore[misc]
