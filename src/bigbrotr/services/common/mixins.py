"""Reusable service mixins for BigBrotr.

All service extensions live here as mixin classes.  Future extensions
follow the same pattern: a mixin class with an ``_init_*()`` method
for lazy initialization.

See Also:
    [BaseService][bigbrotr.core.base_service.BaseService]: The base class
        that mixin classes are composed with via multiple inheritance.
    [NetworkConfig][bigbrotr.services.common.configs.NetworkConfig]:
        Provides ``max_tasks`` values consumed by
        [NetworkSemaphoreMixin][bigbrotr.services.common.mixins.NetworkSemaphoreMixin].
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from bigbrotr.models.constants import NetworkType


if TYPE_CHECKING:
    from .configs import NetworkConfig


# ---------------------------------------------------------------------------
# Batch Progress
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class BatchProgress:
    """Tracks progress of a batch processing cycle.

    All counters are reset at the start of each cycle via ``reset()``.
    Used internally by
    [BatchProgressMixin][bigbrotr.services.common.mixins.BatchProgressMixin]
    to provide ``_progress`` to services.

    Attributes:
        started_at: Timestamp when the cycle started (``time.time()``).
        total: Total items to process.
        processed: Items processed so far.
        success: Items that succeeded.
        failure: Items that failed.
        chunks: Number of chunks completed.

    Note:
        ``started_at`` uses ``time.time()`` for Unix timestamps (used in
        SQL comparisons), while ``elapsed`` uses ``time.monotonic()`` for
        accurate duration measurement unaffected by clock adjustments.

    See Also:
        [BatchProgressMixin][bigbrotr.services.common.mixins.BatchProgressMixin]:
            Mixin that exposes a ``_progress`` attribute of this type.
    """

    started_at: float = field(default=0.0)
    _monotonic_start: float = field(default=0.0, repr=False)
    total: int = field(default=0)
    processed: int = field(default=0)
    success: int = field(default=0)
    failure: int = field(default=0)
    chunks: int = field(default=0)

    def reset(self) -> None:
        """Reset all counters and set ``started_at`` to the current time."""
        self.started_at = time.time()
        self._monotonic_start = time.monotonic()
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
        return round(time.monotonic() - self._monotonic_start, 1)


class BatchProgressMixin:
    """Mixin providing batch processing progress tracking.

    Services that process items in batches compose this mixin to get
    a ``_progress`` attribute with counters and timing.

    Note:
        Call ``_init_progress()`` in ``__init__`` and ``_progress.reset()``
        at the start of each ``run()`` cycle to reset all counters.

    See Also:
        [BatchProgress][bigbrotr.services.common.mixins.BatchProgress]:
            The dataclass this mixin manages.
        [Validator][bigbrotr.services.validator.Validator],
        [Monitor][bigbrotr.services.monitor.Monitor]: Services that
            compose this mixin.

    Examples:
        ```python
        class MyService(BatchProgressMixin, BaseService[MyConfig]):
            def __init__(self, brotr, config):
                super().__init__(brotr=brotr, config=config)
                self._init_progress()

            async def run(self):
                self._progress.reset()
                ...
        ```
    """

    _progress: BatchProgress

    def _init_progress(self) -> None:
        """Initialize a fresh BatchProgress tracker."""
        self._progress = BatchProgress()


# ---------------------------------------------------------------------------
# Network Semaphore
# ---------------------------------------------------------------------------


class NetworkSemaphoreMixin:
    """Mixin providing per-network concurrency semaphores.

    Creates an ``asyncio.Semaphore`` for each
    [NetworkType][bigbrotr.models.constants.NetworkType] (clearnet, Tor,
    I2P, Lokinet) to cap the number of simultaneous connections.  This is
    especially important for overlay networks like Tor, where excessive
    concurrency degrades circuit performance.

    Call ``_init_semaphores()`` at the start of each ``run()`` cycle to pick up
    any configuration changes to ``max_tasks`` values.

    See Also:
        [NetworkConfig][bigbrotr.services.common.configs.NetworkConfig]:
            Provides ``max_tasks`` per network type.
        [Validator][bigbrotr.services.validator.Validator],
        [Monitor][bigbrotr.services.monitor.Monitor]: Services that
            compose this mixin for bounded concurrency.
    """

    _semaphores: dict[NetworkType, asyncio.Semaphore]

    def _init_semaphores(self, networks: NetworkConfig) -> None:
        """Create a semaphore for each network type from the configuration.

        Args:
            networks: [NetworkConfig][bigbrotr.services.common.configs.NetworkConfig]
                providing ``max_tasks`` per network type.
        """
        self._semaphores = {
            network: asyncio.Semaphore(networks.get(network).max_tasks)
            for network in (
                NetworkType.CLEARNET,
                NetworkType.TOR,
                NetworkType.I2P,
                NetworkType.LOKI,
            )
        }

    def _get_semaphore(self, network: NetworkType) -> asyncio.Semaphore | None:
        """Look up the concurrency semaphore for a network type.

        Args:
            network: The [NetworkType][bigbrotr.models.constants.NetworkType]
                to retrieve the semaphore for.

        Returns:
            The semaphore, or ``None`` if the network has not been initialized.
        """
        return self._semaphores.get(network)
