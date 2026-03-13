"""Unit tests for services.common.types module.

Tests:
- Checkpoint: creation, frozen immutability, subclass inheritance
- ApiCheckpoint, MonitorCheckpoint, PublishCheckpoint: creation, isinstance
- CandidateCheckpoint: creation, failures default, frozen immutability, isinstance
- Cursor: base class, defaults, subclass inheritance
- SyncCursor: creation, frozen, isinstance
- FinderCursor: creation, frozen, isinstance
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


class TestCheckpointSubclasses:
    """Tests for ApiCheckpoint, MonitorCheckpoint, PublishCheckpoint subclasses."""

    @pytest.mark.parametrize(
        ("cls", "key"),
        [
            (ApiCheckpoint, "https://api.nostr.watch/v1/online"),
            (MonitorCheckpoint, "wss://relay.example.com"),
            (PublishCheckpoint, "announcement"),
        ],
    )
    def test_creation(self, cls: type, key: str) -> None:
        cp = cls(key=key, timestamp=1700000000)
        assert cp.key == key
        assert cp.timestamp == 1700000000

    @pytest.mark.parametrize("cls", [ApiCheckpoint, MonitorCheckpoint, PublishCheckpoint])
    def test_isinstance_checkpoint(self, cls: type) -> None:
        cp = cls(key="test", timestamp=1700000000)
        assert isinstance(cp, Checkpoint)

    @pytest.mark.parametrize("cls", [ApiCheckpoint, MonitorCheckpoint, PublishCheckpoint])
    def test_frozen(self, cls: type) -> None:
        cp = cls(key="test", timestamp=1700000000)
        with pytest.raises(FrozenInstanceError):
            cp.timestamp = 0  # type: ignore[misc]


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

    def test_creation_defaults(self) -> None:
        """Test Cursor with key only uses concrete defaults."""
        cursor = Cursor(key="wss://relay.example.com")

        assert cursor.key == "wss://relay.example.com"
        assert cursor.timestamp == 0
        assert cursor.id == "0" * 64

    def test_creation_full(self) -> None:
        """Test Cursor with all fields."""
        cursor = Cursor(key="wss://relay.example.com", timestamp=1700000000, id="aa" * 32)

        assert cursor.key == "wss://relay.example.com"
        assert cursor.timestamp == 1700000000
        assert cursor.id == "aa" * 32

    def test_partial_override_timestamp(self) -> None:
        """Test Cursor with only timestamp overridden."""
        cursor = Cursor(key="wss://relay.example.com", timestamp=1700000000)

        assert cursor.timestamp == 1700000000
        assert cursor.id == "0" * 64

    def test_partial_override_id(self) -> None:
        """Test Cursor with only id overridden."""
        cursor = Cursor(key="wss://relay.example.com", id="ff" * 32)

        assert cursor.timestamp == 0
        assert cursor.id == "ff" * 32

    def test_frozen(self) -> None:
        """Test that Cursor instances are immutable."""
        cursor = Cursor(key="wss://relay.example.com")

        with pytest.raises(FrozenInstanceError):
            cursor.timestamp = 123  # type: ignore[misc]


# ============================================================================
# Cursor Subclass Tests
# ============================================================================


class TestCursorSubclasses:
    """Tests for SyncCursor and FinderCursor dataclasses."""

    @pytest.mark.parametrize("cls", [SyncCursor, FinderCursor])
    def test_isinstance_cursor(self, cls: type) -> None:
        cursor = cls(key="wss://relay.example.com")
        assert isinstance(cursor, Cursor)

    @pytest.mark.parametrize("cls", [SyncCursor, FinderCursor])
    def test_defaults(self, cls: type) -> None:
        cursor = cls(key="wss://relay.example.com")
        assert cursor.key == "wss://relay.example.com"
        assert cursor.timestamp == 0
        assert cursor.id == "0" * 64

    @pytest.mark.parametrize("cls", [SyncCursor, FinderCursor])
    def test_full_cursor(self, cls: type) -> None:
        cursor = cls(key="wss://relay.example.com", timestamp=1700000000, id="aa" * 32)
        assert cursor.timestamp == 1700000000
        assert cursor.id == "aa" * 32

    @pytest.mark.parametrize("cls", [SyncCursor, FinderCursor])
    def test_frozen(self, cls: type) -> None:
        cursor = cls(key="wss://relay.example.com")
        with pytest.raises(FrozenInstanceError):
            cursor.timestamp = 123  # type: ignore[misc]

    def test_sync_cursor_not_finder_cursor(self) -> None:
        assert not isinstance(SyncCursor(key="x"), FinderCursor)

    def test_finder_cursor_not_sync_cursor(self) -> None:
        assert not isinstance(FinderCursor(key="x"), SyncCursor)
