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

from utils.progress import BatchProgress


# =============================================================================
# BatchProgress Default Values Tests
# =============================================================================


class TestBatchProgressDefaults:
    """BatchProgress default values."""

    def test_default_started_at(self):
        """Default started_at is 0.0."""
        progress = BatchProgress()
        assert progress.started_at == 0.0

    def test_default_total(self):
        """Default total is 0."""
        progress = BatchProgress()
        assert progress.total == 0

    def test_default_processed(self):
        """Default processed is 0."""
        progress = BatchProgress()
        assert progress.processed == 0

    def test_default_success(self):
        """Default success is 0."""
        progress = BatchProgress()
        assert progress.success == 0

    def test_default_failure(self):
        """Default failure is 0."""
        progress = BatchProgress()
        assert progress.failure == 0

    def test_default_chunks(self):
        """Default chunks is 0."""
        progress = BatchProgress()
        assert progress.chunks == 0


# =============================================================================
# BatchProgress Field Assignment Tests
# =============================================================================


class TestBatchProgressFieldAssignment:
    """BatchProgress field assignments."""

    def test_assign_started_at(self):
        """Can assign started_at."""
        progress = BatchProgress()
        progress.started_at = 1700000000.0
        assert progress.started_at == 1700000000.0

    def test_assign_total(self):
        """Can assign total."""
        progress = BatchProgress()
        progress.total = 100
        assert progress.total == 100

    def test_assign_processed(self):
        """Can assign processed."""
        progress = BatchProgress()
        progress.processed = 50
        assert progress.processed == 50

    def test_assign_success(self):
        """Can assign success."""
        progress = BatchProgress()
        progress.success = 45
        assert progress.success == 45

    def test_assign_failure(self):
        """Can assign failure."""
        progress = BatchProgress()
        progress.failure = 5
        assert progress.failure == 5

    def test_assign_chunks(self):
        """Can assign chunks."""
        progress = BatchProgress()
        progress.chunks = 10
        assert progress.chunks == 10

    def test_increment_processed(self):
        """Can increment processed."""
        progress = BatchProgress()
        progress.processed += 1
        progress.processed += 1
        assert progress.processed == 2

    def test_increment_success(self):
        """Can increment success."""
        progress = BatchProgress()
        progress.success += 1
        progress.success += 1
        progress.success += 1
        assert progress.success == 3

    def test_increment_failure(self):
        """Can increment failure."""
        progress = BatchProgress()
        progress.failure += 1
        assert progress.failure == 1


# =============================================================================
# BatchProgress Initialization Tests
# =============================================================================


class TestBatchProgressInitialization:
    """BatchProgress initialization with values."""

    def test_init_with_values(self):
        """Can initialize with custom values."""
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

    def test_init_partial_values(self):
        """Can initialize with partial values (rest are defaults)."""
        progress = BatchProgress(total=100)
        assert progress.total == 100
        assert progress.processed == 0
        assert progress.success == 0


# =============================================================================
# BatchProgress reset() Method Tests
# =============================================================================


class TestBatchProgressReset:
    """BatchProgress.reset() method."""

    def test_reset_sets_started_at_to_current_time(self):
        """reset() sets started_at to current time."""
        progress = BatchProgress()
        before = time.time()
        progress.reset()
        after = time.time()

        assert before <= progress.started_at <= after

    def test_reset_clears_total(self):
        """reset() sets total to 0."""
        progress = BatchProgress(total=100)
        progress.reset()
        assert progress.total == 0

    def test_reset_clears_processed(self):
        """reset() sets processed to 0."""
        progress = BatchProgress(processed=50)
        progress.reset()
        assert progress.processed == 0

    def test_reset_clears_success(self):
        """reset() sets success to 0."""
        progress = BatchProgress(success=45)
        progress.reset()
        assert progress.success == 0

    def test_reset_clears_failure(self):
        """reset() sets failure to 0."""
        progress = BatchProgress(failure=5)
        progress.reset()
        assert progress.failure == 0

    def test_reset_clears_chunks(self):
        """reset() sets chunks to 0."""
        progress = BatchProgress(chunks=10)
        progress.reset()
        assert progress.chunks == 0

    def test_reset_clears_all_counters(self):
        """reset() clears all counters at once."""
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
        assert progress.started_at > 0  # Set to current time

    def test_reset_multiple_times(self):
        """reset() can be called multiple times."""
        progress = BatchProgress()

        progress.reset()
        first_started_at = progress.started_at

        time.sleep(0.01)  # Small delay to ensure different timestamp
        progress.reset()
        second_started_at = progress.started_at

        assert second_started_at > first_started_at


# =============================================================================
# BatchProgress remaining Property Tests
# =============================================================================


class TestBatchProgressRemaining:
    """BatchProgress.remaining property."""

    def test_remaining_all_items(self):
        """remaining equals total when nothing processed."""
        progress = BatchProgress(total=100, processed=0)
        assert progress.remaining == 100

    def test_remaining_some_processed(self):
        """remaining is total minus processed."""
        progress = BatchProgress(total=100, processed=30)
        assert progress.remaining == 70

    def test_remaining_all_processed(self):
        """remaining is 0 when all processed."""
        progress = BatchProgress(total=100, processed=100)
        assert progress.remaining == 0

    def test_remaining_default_values(self):
        """remaining is 0 with default values."""
        progress = BatchProgress()
        assert progress.remaining == 0

    def test_remaining_negative_if_overprocessed(self):
        """remaining can be negative if processed > total (edge case)."""
        progress = BatchProgress(total=10, processed=15)
        assert progress.remaining == -5


# =============================================================================
# BatchProgress elapsed Property Tests
# =============================================================================


class TestBatchProgressElapsed:
    """BatchProgress.elapsed property."""

    def test_elapsed_returns_float(self):
        """elapsed returns a float."""
        progress = BatchProgress()
        progress.reset()
        assert isinstance(progress.elapsed, float)

    def test_elapsed_increases_over_time(self):
        """elapsed increases as time passes."""
        progress = BatchProgress()
        progress.reset()
        first_elapsed = progress.elapsed
        time.sleep(0.1)
        second_elapsed = progress.elapsed
        assert second_elapsed > first_elapsed

    def test_elapsed_rounded_to_one_decimal(self):
        """elapsed is rounded to 1 decimal place."""
        # Mock time to get predictable values
        with patch("time.time", return_value=1000.0):
            progress = BatchProgress()
            progress.started_at = 999.123

        with patch("time.time", return_value=1000.0):
            elapsed = progress.elapsed

        # 1000.0 - 999.123 = 0.877, rounded to 0.9
        assert elapsed == 0.9

    def test_elapsed_with_zero_started_at(self):
        """elapsed works with default started_at of 0."""
        progress = BatchProgress()
        # With started_at=0, elapsed will be roughly the current time
        # Just verify it's a positive number
        assert progress.elapsed > 0

    def test_elapsed_immediately_after_reset(self):
        """elapsed is very small immediately after reset."""
        progress = BatchProgress()
        progress.reset()
        elapsed = progress.elapsed
        # Should be very close to 0 (within 0.1 seconds)
        assert elapsed < 0.5


# =============================================================================
# BatchProgress Typical Usage Tests
# =============================================================================


class TestBatchProgressTypicalUsage:
    """BatchProgress typical usage patterns."""

    def test_processing_workflow(self):
        """Test typical batch processing workflow."""
        progress = BatchProgress()
        progress.reset()

        # Simulate batch processing
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

    def test_multiple_cycles(self):
        """Test multiple processing cycles."""
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

    def test_summary_calculation(self):
        """Test calculating summary statistics."""
        progress = BatchProgress()
        progress.reset()

        progress.total = 100
        progress.processed = 80
        progress.success = 75
        progress.failure = 5
        progress.chunks = 8

        # Calculate percentages
        success_rate = (progress.success / progress.processed) * 100
        progress_pct = (progress.processed / progress.total) * 100

        assert success_rate == pytest.approx(93.75)
        assert progress_pct == 80.0
        assert progress.remaining == 20


# =============================================================================
# Import pytest for approx
# =============================================================================


import pytest  # noqa: E402
