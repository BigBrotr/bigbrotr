"""
Unit tests for utils.progress module.

Tests:
- BatchProgress dataclass
  - Default values
  - Field assignments
  - reset() method
  - remaining property
  - elapsed property
"""

import time
from unittest.mock import patch

import pytest

from utils.progress import BatchProgress


# =============================================================================
# BatchProgress Default Values Tests
# =============================================================================


class TestBatchProgressDefaults:
    """Tests for BatchProgress default field values."""

    def test_default_started_at(self) -> None:
        """Test default started_at is 0.0."""
        progress = BatchProgress()
        assert progress.started_at == 0.0

    def test_default_total(self) -> None:
        """Test default total is 0."""
        progress = BatchProgress()
        assert progress.total == 0

    def test_default_processed(self) -> None:
        """Test default processed is 0."""
        progress = BatchProgress()
        assert progress.processed == 0

    def test_default_success(self) -> None:
        """Test default success is 0."""
        progress = BatchProgress()
        assert progress.success == 0

    def test_default_failure(self) -> None:
        """Test default failure is 0."""
        progress = BatchProgress()
        assert progress.failure == 0

    def test_default_chunks(self) -> None:
        """Test default chunks is 0."""
        progress = BatchProgress()
        assert progress.chunks == 0


# =============================================================================
# BatchProgress Field Assignment Tests
# =============================================================================


class TestBatchProgressFieldAssignment:
    """Tests for BatchProgress field assignments and increments."""

    def test_assign_started_at(self) -> None:
        """Test assigning started_at."""
        progress = BatchProgress()
        progress.started_at = 1700000000.0
        assert progress.started_at == 1700000000.0

    def test_assign_total(self) -> None:
        """Test assigning total."""
        progress = BatchProgress()
        progress.total = 100
        assert progress.total == 100

    def test_assign_processed(self) -> None:
        """Test assigning processed."""
        progress = BatchProgress()
        progress.processed = 50
        assert progress.processed == 50

    def test_assign_success(self) -> None:
        """Test assigning success."""
        progress = BatchProgress()
        progress.success = 45
        assert progress.success == 45

    def test_assign_failure(self) -> None:
        """Test assigning failure."""
        progress = BatchProgress()
        progress.failure = 5
        assert progress.failure == 5

    def test_assign_chunks(self) -> None:
        """Test assigning chunks."""
        progress = BatchProgress()
        progress.chunks = 10
        assert progress.chunks == 10

    def test_increment_processed(self) -> None:
        """Test incrementing processed counter."""
        progress = BatchProgress()
        progress.processed += 1
        progress.processed += 1
        assert progress.processed == 2

    def test_increment_success(self) -> None:
        """Test incrementing success counter."""
        progress = BatchProgress()
        progress.success += 1
        progress.success += 1
        progress.success += 1
        assert progress.success == 3

    def test_increment_failure(self) -> None:
        """Test incrementing failure counter."""
        progress = BatchProgress()
        progress.failure += 1
        assert progress.failure == 1


# =============================================================================
# BatchProgress Initialization Tests
# =============================================================================


class TestBatchProgressInitialization:
    """Tests for BatchProgress initialization with values."""

    def test_init_with_values(self) -> None:
        """Test initialization with all custom values."""
        progress = BatchProgress(
            started_at=1700000000.0,
            total=100,
            processed=50,
            success=45,
            failure=5,
            chunks=10,
        )
        assert progress.started_at == 1700000000.0
        assert progress.total == 100
        assert progress.processed == 50
        assert progress.success == 45
        assert progress.failure == 5
        assert progress.chunks == 10

    def test_init_partial_values(self) -> None:
        """Test initialization with partial values (rest are defaults)."""
        progress = BatchProgress(total=100)
        assert progress.total == 100
        assert progress.processed == 0
        assert progress.success == 0


# =============================================================================
# BatchProgress reset() Method Tests
# =============================================================================


class TestBatchProgressReset:
    """Tests for BatchProgress.reset() method."""

    def test_reset_sets_started_at_to_current_time(self) -> None:
        """Test reset() sets started_at to current time."""
        progress = BatchProgress()
        before = time.time()
        progress.reset()
        after = time.time()

        assert before <= progress.started_at <= after

    def test_reset_clears_total(self) -> None:
        """Test reset() sets total to 0."""
        progress = BatchProgress(total=100)
        progress.reset()
        assert progress.total == 0

    def test_reset_clears_processed(self) -> None:
        """Test reset() sets processed to 0."""
        progress = BatchProgress(processed=50)
        progress.reset()
        assert progress.processed == 0

    def test_reset_clears_success(self) -> None:
        """Test reset() sets success to 0."""
        progress = BatchProgress(success=45)
        progress.reset()
        assert progress.success == 0

    def test_reset_clears_failure(self) -> None:
        """Test reset() sets failure to 0."""
        progress = BatchProgress(failure=5)
        progress.reset()
        assert progress.failure == 0

    def test_reset_clears_chunks(self) -> None:
        """Test reset() sets chunks to 0."""
        progress = BatchProgress(chunks=10)
        progress.reset()
        assert progress.chunks == 0

    def test_reset_clears_all_counters(self) -> None:
        """Test reset() clears all counters at once."""
        progress = BatchProgress(
            started_at=1000.0,
            total=100,
            processed=50,
            success=45,
            failure=5,
            chunks=10,
        )
        progress.reset()

        assert progress.total == 0
        assert progress.processed == 0
        assert progress.success == 0
        assert progress.failure == 0
        assert progress.chunks == 0
        assert progress.started_at > 0

    def test_reset_multiple_times(self) -> None:
        """Test reset() can be called multiple times."""
        progress = BatchProgress()

        progress.reset()
        first_started_at = progress.started_at

        time.sleep(0.01)
        progress.reset()
        second_started_at = progress.started_at

        assert second_started_at > first_started_at


# =============================================================================
# BatchProgress remaining Property Tests
# =============================================================================


class TestBatchProgressRemaining:
    """Tests for BatchProgress.remaining computed property."""

    def test_remaining_all_items(self) -> None:
        """Test remaining equals total when nothing processed."""
        progress = BatchProgress(total=100, processed=0)
        assert progress.remaining == 100

    def test_remaining_some_processed(self) -> None:
        """Test remaining is total minus processed."""
        progress = BatchProgress(total=100, processed=30)
        assert progress.remaining == 70

    def test_remaining_all_processed(self) -> None:
        """Test remaining is 0 when all processed."""
        progress = BatchProgress(total=100, processed=100)
        assert progress.remaining == 0

    def test_remaining_default_values(self) -> None:
        """Test remaining is 0 with default values."""
        progress = BatchProgress()
        assert progress.remaining == 0

    def test_remaining_negative_if_overprocessed(self) -> None:
        """Test remaining can be negative if processed > total."""
        progress = BatchProgress(total=10, processed=15)
        assert progress.remaining == -5


# =============================================================================
# BatchProgress elapsed Property Tests
# =============================================================================


class TestBatchProgressElapsed:
    """Tests for BatchProgress.elapsed computed property."""

    def test_elapsed_returns_float(self) -> None:
        """Test elapsed returns a float."""
        progress = BatchProgress()
        progress.reset()
        assert isinstance(progress.elapsed, float)

    def test_elapsed_increases_over_time(self) -> None:
        """Test elapsed increases as time passes."""
        progress = BatchProgress()
        progress.reset()
        first_elapsed = progress.elapsed
        time.sleep(0.1)
        second_elapsed = progress.elapsed
        assert second_elapsed > first_elapsed

    def test_elapsed_rounded_to_one_decimal(self) -> None:
        """Test elapsed is rounded to 1 decimal place."""
        with patch("time.time", return_value=1000.0):
            progress = BatchProgress()
            progress.started_at = 999.123

        with patch("time.time", return_value=1000.0):
            elapsed = progress.elapsed

        # 1000.0 - 999.123 = 0.877, rounded to 0.9
        assert elapsed == 0.9

    def test_elapsed_with_zero_started_at(self) -> None:
        """Test elapsed works with default started_at of 0."""
        progress = BatchProgress()
        assert progress.elapsed > 0

    def test_elapsed_immediately_after_reset(self) -> None:
        """Test elapsed is very small immediately after reset."""
        progress = BatchProgress()
        progress.reset()
        elapsed = progress.elapsed
        assert elapsed < 0.5


# =============================================================================
# BatchProgress Typical Usage Tests
# =============================================================================


class TestBatchProgressTypicalUsage:
    """Tests for BatchProgress typical usage patterns."""

    def test_processing_workflow(self) -> None:
        """Test typical batch processing workflow."""
        progress = BatchProgress()
        progress.reset()

        progress.total = 10
        for i in range(10):
            progress.processed += 1
            if i % 3 == 0:
                progress.failure += 1
            else:
                progress.success += 1
            if i % 5 == 0:
                progress.chunks += 1

        assert progress.total == 10
        assert progress.processed == 10
        assert progress.remaining == 0
        assert progress.success + progress.failure == 10

    def test_multiple_cycles(self) -> None:
        """Test multiple processing cycles with reset."""
        progress = BatchProgress()

        # First cycle
        progress.reset()
        progress.total = 100
        progress.processed = 100
        progress.success = 95
        progress.failure = 5

        assert progress.remaining == 0

        # Second cycle (reset)
        progress.reset()
        assert progress.total == 0
        assert progress.processed == 0
        assert progress.success == 0
        assert progress.failure == 0

        # New data
        progress.total = 50
        progress.processed = 25
        assert progress.remaining == 25

    def test_summary_calculation(self) -> None:
        """Test calculating summary statistics."""
        progress = BatchProgress()
        progress.reset()

        progress.total = 100
        progress.processed = 80
        progress.success = 75
        progress.failure = 5
        progress.chunks = 8

        success_rate = (progress.success / progress.processed) * 100
        progress_pct = (progress.processed / progress.total) * 100

        assert success_rate == pytest.approx(93.75)
        assert progress_pct == 80.0
        assert progress.remaining == 20
