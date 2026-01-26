"""Batch processing progress tracking.

This module provides a dataclass for tracking progress of batch processing
operations, commonly used by services that process items in chunks.

Example:
    >>> from utils.progress import BatchProgress
    >>> progress = BatchProgress()
    >>> progress.reset()
    >>> progress.total = 100
    >>> progress.processed += 1
    >>> progress.success += 1
    >>> print(f"Remaining: {progress.remaining}, Elapsed: {progress.elapsed}s")
"""

import time
from dataclasses import dataclass, field


@dataclass
class BatchProgress:
    """Tracks progress of a batch processing operation.

    Used by services that process items in chunks to track overall progress,
    success/failure counts, and timing. All counters are reset at the start
    of each processing cycle via the reset() method.

    Attributes:
        started_at: Timestamp when processing started (set by reset()).
        total: Total number of items to process.
        processed: Number of items processed so far.
        success: Number of items that succeeded.
        failure: Number of items that failed.
        chunks: Number of chunks processed.

    Properties:
        remaining: Items left to process (total - processed).
        elapsed: Seconds elapsed since started_at, rounded to 1 decimal.

    Example:
        >>> progress = BatchProgress()
        >>> progress.reset()
        >>> progress.total = 50
        >>> for item in items:
        ...     progress.processed += 1
        ...     if process(item):
        ...         progress.success += 1
        ...     else:
        ...         progress.failure += 1
        >>> print(f"Done: {progress.success}/{progress.total} in {progress.elapsed}s")
    """

    started_at: float = field(default=0.0)
    total: int = field(default=0)
    processed: int = field(default=0)
    success: int = field(default=0)
    failure: int = field(default=0)
    chunks: int = field(default=0)

    def reset(self) -> None:
        """Reset all counters for a new processing cycle.

        Sets started_at to current time and all counters to zero.
        Call this at the beginning of each run() cycle.
        """
        self.started_at = time.time()
        self.total = 0
        self.processed = 0
        self.success = 0
        self.failure = 0
        self.chunks = 0

    @property
    def remaining(self) -> int:
        """Number of items left to process."""
        return self.total - self.processed

    @property
    def elapsed(self) -> float:
        """Seconds elapsed since processing started, rounded to 1 decimal."""
        return round(time.time() - self.started_at, 1)
