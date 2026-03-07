"""Unit tests for services.common.types module.

Tests:
- Checkpoint: creation, frozen immutability, subclass inheritance
- ApiCheckpoint, MonitorCheckpoint, PublishCheckpoint: creation, isinstance
- CandidateCheckpoint: creation, failures default, frozen immutability, isinstance
- Cursor: base class, both-None-or-both-set validation, subclass inheritance
- SyncCursor: valid combinations, partial cursor rejection, frozen, isinstance
- FinderCursor: valid combinations, partial cursor rejection, frozen, isinstance
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
    FinderCursor,
    MonitorCheckpoint,
    PublishCheckpoint,
    SyncCursor,
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

    def test_creation_no_position(self) -> None:
        """Test Cursor with key only (no position)."""
        cursor = Cursor(key="wss://relay.example.com")

        assert cursor.key == "wss://relay.example.com"
        assert cursor.timestamp is None
        assert cursor.id is None

    def test_creation_full(self) -> None:
        """Test Cursor with all fields."""
        event_id = b"\x00" * 32
        cursor = Cursor(key="wss://relay.example.com", timestamp=1700000000, id=event_id)

        assert cursor.key == "wss://relay.example.com"
        assert cursor.timestamp == 1700000000
        assert cursor.id == event_id

    def test_timestamp_without_id_raises(self) -> None:
        """Test that timestamp without id raises ValueError."""
        with pytest.raises(ValueError, match="must both be None or both be set"):
            Cursor(key="wss://relay.example.com", timestamp=1700000000)

    def test_id_without_timestamp_raises(self) -> None:
        """Test that id without timestamp raises ValueError."""
        with pytest.raises(ValueError, match="must both be None or both be set"):
            Cursor(key="wss://relay.example.com", id=b"\x00" * 32)

    def test_frozen(self) -> None:
        """Test that Cursor instances are immutable."""
        cursor = Cursor(key="wss://relay.example.com")

        with pytest.raises(FrozenInstanceError):
            cursor.timestamp = 123  # type: ignore[misc]


# ============================================================================
# SyncCursor Tests
# ============================================================================


class TestSyncCursor:
    """Tests for SyncCursor dataclass."""

    def test_isinstance_cursor(self) -> None:
        """Test that SyncCursor is a Cursor."""
        cursor = SyncCursor(key="wss://relay.example.com")

        assert isinstance(cursor, Cursor)

    def test_not_isinstance_finder_cursor(self) -> None:
        """Test that SyncCursor is not a FinderCursor."""
        cursor = SyncCursor(key="wss://relay.example.com")

        assert not isinstance(cursor, FinderCursor)

    def test_no_cursor(self) -> None:
        """Test cursor with no position (scan from beginning)."""
        cursor = SyncCursor(key="wss://relay.example.com")

        assert cursor.key == "wss://relay.example.com"
        assert cursor.timestamp is None
        assert cursor.id is None

    def test_full_cursor(self) -> None:
        """Test cursor with both timestamp and id."""
        event_id = b"\x00" * 32
        cursor = SyncCursor(
            key="wss://relay.example.com",
            timestamp=1700000000,
            id=event_id,
        )

        assert cursor.timestamp == 1700000000
        assert cursor.id == event_id

    def test_timestamp_without_id_raises(self) -> None:
        """Test that timestamp without id raises ValueError."""
        with pytest.raises(ValueError, match="must both be None or both be set"):
            SyncCursor(key="wss://relay.example.com", timestamp=1700000000)

    def test_id_without_timestamp_raises(self) -> None:
        """Test that id without timestamp raises ValueError."""
        with pytest.raises(ValueError, match="must both be None or both be set"):
            SyncCursor(key="wss://relay.example.com", id=b"\x00" * 32)

    def test_frozen(self) -> None:
        """Test that SyncCursor instances are immutable."""
        cursor = SyncCursor(key="wss://relay.example.com")

        with pytest.raises(FrozenInstanceError):
            cursor.timestamp = 123  # type: ignore[misc]


# ============================================================================
# FinderCursor Tests
# ============================================================================


class TestFinderCursor:
    """Tests for FinderCursor dataclass."""

    def test_isinstance_cursor(self) -> None:
        """Test that FinderCursor is a Cursor."""
        cursor = FinderCursor(key="wss://relay.example.com")

        assert isinstance(cursor, Cursor)

    def test_not_isinstance_sync_cursor(self) -> None:
        """Test that FinderCursor is not a SyncCursor."""
        cursor = FinderCursor(key="wss://relay.example.com")

        assert not isinstance(cursor, SyncCursor)

    def test_no_cursor(self) -> None:
        """Test cursor with no position (scan from beginning)."""
        cursor = FinderCursor(key="wss://relay.example.com")

        assert cursor.key == "wss://relay.example.com"
        assert cursor.timestamp is None
        assert cursor.id is None

    def test_full_cursor(self) -> None:
        """Test cursor with both timestamp and id."""
        event_id = b"\x00" * 32
        cursor = FinderCursor(key="wss://relay.example.com", timestamp=1700000000, id=event_id)

        assert cursor.timestamp == 1700000000
        assert cursor.id == event_id

    def test_timestamp_without_id_raises(self) -> None:
        """Test that timestamp without id raises ValueError."""
        with pytest.raises(ValueError, match="must both be None or both be set"):
            FinderCursor(key="wss://relay.example.com", timestamp=1700000000)

    def test_id_without_timestamp_raises(self) -> None:
        """Test that id without timestamp raises ValueError."""
        with pytest.raises(ValueError, match="must both be None or both be set"):
            FinderCursor(key="wss://relay.example.com", id=b"\x00" * 32)

    def test_frozen(self) -> None:
        """Test that FinderCursor instances are immutable."""
        cursor = FinderCursor(key="wss://relay.example.com")

        with pytest.raises(FrozenInstanceError):
            cursor.timestamp = 123  # type: ignore[misc]
