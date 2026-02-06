"""Batch processing progress tracking for BigBrotr services.

Provides a simple dataclass for tracking cycle progress including item
counts, timing, and chunk bookkeeping. Used by Validator, Monitor, and
other services that process items in configurable chunks.

Example::

    progress = BatchProgress()
    progress.reset()
    progress.total = 100
    progress.processed += 1
    progress.success += 1
    print(f"Remaining: {progress.remaining}, Elapsed: {progress.elapsed}s")
"""

import time
from dataclasses import dataclass, field


@dataclass
class BatchProgress:
    """Tracks progress of a batch processing cycle.

    All counters are reset at the start of each cycle via ``reset()``.

    Attributes:
        started_at: Timestamp when the cycle started.
        total: Total items to process.
        processed: Items processed so far.
        success: Items that succeeded.
        failure: Items that failed.
        chunks: Number of chunks completed.
    """

    started_at: float = field(default=0.0)
    total: int = field(default=0)
    processed: int = field(default=0)
    success: int = field(default=0)
    failure: int = field(default=0)
    chunks: int = field(default=0)

    def reset(self) -> None:
        """Reset all counters and set ``started_at`` to the current time."""
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
