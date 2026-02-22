"""
Unit tests for services.common.mixins.ChunkProgress.

Tests:
- ChunkProgress dataclass
  - Default values
  - Field assignments
  - reset() method
  - record_chunk() method
  - remaining property
  - elapsed property
"""

import time
from unittest.mock import patch

import pytest

from bigbrotr.services.common.mixins import ChunkProgress


# =============================================================================
# ChunkProgress Default Values Tests
# =============================================================================


class TestChunkProgressDefaults:
    """Tests for ChunkProgress default field values."""

    def test_default_started_at(self) -> None:
        """Test default started_at is 0.0."""
        progress = ChunkProgress()
        assert progress.started_at == 0.0

    def test_default_total(self) -> None:
        """Test default total is 0."""
        progress = ChunkProgress()
        assert progress.total == 0

    def test_default_processed(self) -> None:
        """Test default processed is 0."""
        progress = ChunkProgress()
        assert progress.processed == 0

    def test_default_succeeded(self) -> None:
        """Test default succeeded is 0."""
        progress = ChunkProgress()
        assert progress.succeeded == 0

    def test_default_failed(self) -> None:
        """Test default failed is 0."""
        progress = ChunkProgress()
        assert progress.failed == 0

    def test_default_chunks(self) -> None:
        """Test default chunks is 0."""
        progress = ChunkProgress()
        assert progress.chunks == 0


# =============================================================================
# ChunkProgress Field Assignment Tests
# =============================================================================


class TestChunkProgressFieldAssignment:
    """Tests for ChunkProgress field assignments and increments."""

    def test_assign_started_at(self) -> None:
        """Test assigning started_at."""
        progress = ChunkProgress()
        progress.started_at = 1700000000.0
        assert progress.started_at == 1700000000.0

    def test_assign_total(self) -> None:
        """Test assigning total."""
        progress = ChunkProgress()
        progress.total = 100
        assert progress.total == 100

    def test_assign_processed(self) -> None:
        """Test assigning processed."""
        progress = ChunkProgress()
        progress.processed = 50
        assert progress.processed == 50

    def test_assign_succeeded(self) -> None:
        """Test assigning succeeded."""
        progress = ChunkProgress()
        progress.succeeded = 45
        assert progress.succeeded == 45

    def test_assign_failed(self) -> None:
        """Test assigning failed."""
        progress = ChunkProgress()
        progress.failed = 5
        assert progress.failed == 5

    def test_assign_chunks(self) -> None:
        """Test assigning chunks."""
        progress = ChunkProgress()
        progress.chunks = 10
        assert progress.chunks == 10

    def test_increment_processed(self) -> None:
        """Test incrementing processed counter."""
        progress = ChunkProgress()
        progress.processed += 1
        progress.processed += 1
        assert progress.processed == 2

    def test_increment_succeeded(self) -> None:
        """Test incrementing succeeded counter."""
        progress = ChunkProgress()
        progress.succeeded += 1
        progress.succeeded += 1
        progress.succeeded += 1
        assert progress.succeeded == 3

    def test_increment_failed(self) -> None:
        """Test incrementing failed counter."""
        progress = ChunkProgress()
        progress.failed += 1
        assert progress.failed == 1


# =============================================================================
# ChunkProgress Initialization Tests
# =============================================================================


class TestChunkProgressInitialization:
    """Tests for ChunkProgress initialization with values."""

    def test_init_with_values(self) -> None:
        """Test initialization with all custom values."""
        progress = ChunkProgress(
            started_at=1700000000.0,
            total=100,
            processed=50,
            succeeded=45,
            failed=5,
            chunks=10,
        )
        assert progress.started_at == 1700000000.0
        assert progress.total == 100
        assert progress.processed == 50
        assert progress.succeeded == 45
        assert progress.failed == 5
        assert progress.chunks == 10

    def test_init_partial_values(self) -> None:
        """Test initialization with partial values (rest are defaults)."""
        progress = ChunkProgress(total=100)
        assert progress.total == 100
        assert progress.processed == 0
        assert progress.succeeded == 0


# =============================================================================
# ChunkProgress reset() Method Tests
# =============================================================================


class TestChunkProgressReset:
    """Tests for ChunkProgress.reset() method."""

    def test_reset_sets_started_at_to_current_time(self) -> None:
        """Test reset() sets started_at to current time."""
        progress = ChunkProgress()
        before = time.time()
        progress.reset()
        after = time.time()

        assert before <= progress.started_at <= after

    def test_reset_clears_total(self) -> None:
        """Test reset() sets total to 0."""
        progress = ChunkProgress(total=100)
        progress.reset()
        assert progress.total == 0

    def test_reset_clears_processed(self) -> None:
        """Test reset() sets processed to 0."""
        progress = ChunkProgress(processed=50)
        progress.reset()
        assert progress.processed == 0

    def test_reset_clears_succeeded(self) -> None:
        """Test reset() sets succeeded to 0."""
        progress = ChunkProgress(succeeded=45)
        progress.reset()
        assert progress.succeeded == 0

    def test_reset_clears_failed(self) -> None:
        """Test reset() sets failed to 0."""
        progress = ChunkProgress(failed=5)
        progress.reset()
        assert progress.failed == 0

    def test_reset_clears_chunks(self) -> None:
        """Test reset() sets chunks to 0."""
        progress = ChunkProgress(chunks=10)
        progress.reset()
        assert progress.chunks == 0

    def test_reset_clears_all_counters(self) -> None:
        """Test reset() clears all counters at once."""
        progress = ChunkProgress(
            started_at=1000.0,
            total=100,
            processed=50,
            succeeded=45,
            failed=5,
            chunks=10,
        )
        progress.reset()

        assert progress.total == 0
        assert progress.processed == 0
        assert progress.succeeded == 0
        assert progress.failed == 0
        assert progress.chunks == 0
        assert progress.started_at > 0

    def test_reset_multiple_times(self) -> None:
        """Test reset() can be called multiple times."""
        progress = ChunkProgress()

        progress.reset()
        first_started_at = progress.started_at

        time.sleep(0.01)
        progress.reset()
        second_started_at = progress.started_at

        assert second_started_at > first_started_at


# =============================================================================
# ChunkProgress record_chunk() Method Tests
# =============================================================================


class TestChunkProgressRecordChunk:
    """Tests for ChunkProgress.record_chunk() method."""

    def test_record_chunk_updates_all_counters(self) -> None:
        """Test record_chunk updates processed, succeeded, failed, and chunks."""
        progress = ChunkProgress()
        progress.record_chunk(succeeded=8, failed=2)

        assert progress.processed == 10
        assert progress.succeeded == 8
        assert progress.failed == 2
        assert progress.chunks == 1

    def test_record_chunk_accumulates(self) -> None:
        """Test record_chunk accumulates across multiple calls."""
        progress = ChunkProgress()
        progress.record_chunk(succeeded=5, failed=1)
        progress.record_chunk(succeeded=3, failed=2)

        assert progress.processed == 11
        assert progress.succeeded == 8
        assert progress.failed == 3
        assert progress.chunks == 2

    def test_record_chunk_all_succeeded(self) -> None:
        """Test record_chunk with no failures."""
        progress = ChunkProgress()
        progress.record_chunk(succeeded=10, failed=0)

        assert progress.processed == 10
        assert progress.succeeded == 10
        assert progress.failed == 0
        assert progress.chunks == 1

    def test_record_chunk_all_failed(self) -> None:
        """Test record_chunk with no successes."""
        progress = ChunkProgress()
        progress.record_chunk(succeeded=0, failed=10)

        assert progress.processed == 10
        assert progress.succeeded == 0
        assert progress.failed == 10
        assert progress.chunks == 1

    def test_record_chunk_empty(self) -> None:
        """Test record_chunk with zero items still increments chunks."""
        progress = ChunkProgress()
        progress.record_chunk(succeeded=0, failed=0)

        assert progress.processed == 0
        assert progress.chunks == 1

    def test_record_chunk_updates_remaining(self) -> None:
        """Test record_chunk correctly affects remaining calculation."""
        progress = ChunkProgress()
        progress.total = 100
        progress.record_chunk(succeeded=30, failed=10)

        assert progress.remaining == 60


# =============================================================================
# ChunkProgress remaining Property Tests
# =============================================================================


class TestChunkProgressRemaining:
    """Tests for ChunkProgress.remaining computed property."""

    def test_remaining_all_items(self) -> None:
        """Test remaining equals total when nothing processed."""
        progress = ChunkProgress(total=100, processed=0)
        assert progress.remaining == 100

    def test_remaining_some_processed(self) -> None:
        """Test remaining is total minus processed."""
        progress = ChunkProgress(total=100, processed=30)
        assert progress.remaining == 70

    def test_remaining_all_processed(self) -> None:
        """Test remaining is 0 when all processed."""
        progress = ChunkProgress(total=100, processed=100)
        assert progress.remaining == 0

    def test_remaining_default_values(self) -> None:
        """Test remaining is 0 with default values."""
        progress = ChunkProgress()
        assert progress.remaining == 0

    def test_remaining_negative_if_overprocessed(self) -> None:
        """Test remaining can be negative if processed > total."""
        progress = ChunkProgress(total=10, processed=15)
        assert progress.remaining == -5


# =============================================================================
# ChunkProgress elapsed Property Tests
# =============================================================================


class TestChunkProgressElapsed:
    """Tests for ChunkProgress.elapsed computed property."""

    def test_elapsed_returns_float(self) -> None:
        """Test elapsed returns a float."""
        progress = ChunkProgress()
        progress.reset()
        assert isinstance(progress.elapsed, float)

    def test_elapsed_increases_over_time(self) -> None:
        """Test elapsed increases as time passes."""
        progress = ChunkProgress()
        progress.reset()
        first_elapsed = progress.elapsed
        time.sleep(0.1)
        second_elapsed = progress.elapsed
        assert second_elapsed > first_elapsed

    def test_elapsed_rounded_to_one_decimal(self) -> None:
        """Test elapsed is rounded to 1 decimal place."""
        with patch("time.monotonic", return_value=1000.0):
            progress = ChunkProgress()
            progress._monotonic_start = 999.123

        with patch("time.monotonic", return_value=1000.0):
            elapsed = progress.elapsed

        # 1000.0 - 999.123 = 0.877, rounded to 0.9
        assert elapsed == 0.9

    def test_elapsed_with_zero_started_at(self) -> None:
        """Test elapsed works with default started_at of 0."""
        progress = ChunkProgress()
        assert progress.elapsed > 0

    def test_elapsed_immediately_after_reset(self) -> None:
        """Test elapsed is very small immediately after reset."""
        progress = ChunkProgress()
        progress.reset()
        elapsed = progress.elapsed
        assert elapsed < 0.5


# =============================================================================
# ChunkProgress Typical Usage Tests
# =============================================================================


class TestChunkProgressTypicalUsage:
    """Tests for ChunkProgress typical usage patterns."""

    def test_processing_workflow(self) -> None:
        """Test typical batch processing workflow."""
        progress = ChunkProgress()
        progress.reset()

        progress.total = 10
        for i in range(10):
            progress.processed += 1
            if i % 3 == 0:
                progress.failed += 1
            else:
                progress.succeeded += 1
            if i % 5 == 0:
                progress.chunks += 1

        assert progress.total == 10
        assert progress.processed == 10
        assert progress.remaining == 0
        assert progress.succeeded + progress.failed == 10

    def test_multiple_cycles(self) -> None:
        """Test multiple processing cycles with reset."""
        progress = ChunkProgress()

        # First cycle
        progress.reset()
        progress.total = 100
        progress.processed = 100
        progress.succeeded = 95
        progress.failed = 5

        assert progress.remaining == 0

        # Second cycle (reset)
        progress.reset()
        assert progress.total == 0
        assert progress.processed == 0
        assert progress.succeeded == 0
        assert progress.failed == 0

        # New data
        progress.total = 50
        progress.processed = 25
        assert progress.remaining == 25

    def test_summary_calculation(self) -> None:
        """Test calculating summary statistics."""
        progress = ChunkProgress()
        progress.reset()

        progress.total = 100
        progress.processed = 80
        progress.succeeded = 75
        progress.failed = 5
        progress.chunks = 8

        success_rate = (progress.succeeded / progress.processed) * 100
        progress_pct = (progress.processed / progress.total) * 100

        assert success_rate == pytest.approx(93.75)
        assert progress_pct == 80.0
        assert progress.remaining == 20
