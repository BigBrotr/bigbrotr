"""Reusable service mixins for BigBrotr.

All service extensions live here as mixin classes. Each mixin uses
cooperative multiple inheritance (``super().__init__(**kwargs)``) so
that initialization is handled automatically via the MRO — no
explicit ``_init_*()`` calls are needed in service constructors.

See Also:
    [BaseService][bigbrotr.core.base_service.BaseService]: The base class
        that mixin classes are composed with via multiple inheritance.
    [NetworksConfig][bigbrotr.services.common.configs.NetworksConfig]:
        Provides ``max_tasks`` values consumed by
        [NetworkSemaphoresMixin][bigbrotr.services.common.mixins.NetworkSemaphoresMixin].
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any, TypeVar, cast

from bigbrotr.models.constants import NetworkType


T = TypeVar("T")
R = TypeVar("R")


if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Sequence

    from bigbrotr.core.logger import Logger

    from .configs import NetworksConfig


#: Network types that support concurrent relay connections.
OPERATIONAL_NETWORKS: tuple[NetworkType, ...] = (
    NetworkType.CLEARNET,
    NetworkType.TOR,
    NetworkType.I2P,
    NetworkType.LOKI,
)


_QUEUE_DONE = object()
_ITEM_DONE = object()


class NetworkSemaphores:
    """Per-network concurrency semaphores.

    Creates an ``asyncio.Semaphore`` for each operational
    [NetworkType][bigbrotr.models.constants.NetworkType] (clearnet, Tor,
    I2P, Lokinet) to cap the number of simultaneous connections.

    See Also:
        [NetworksConfig][bigbrotr.services.common.configs.NetworksConfig]:
            Provides ``max_tasks`` per network type.
    """

    __slots__ = ("_limits", "_map")

    def __init__(self, networks: NetworksConfig) -> None:
        self._limits: dict[NetworkType, int] = {
            nt: networks.get(nt).max_tasks for nt in OPERATIONAL_NETWORKS
        }
        self._map: dict[NetworkType, asyncio.Semaphore] = {
            nt: asyncio.Semaphore(limit) for nt, limit in self._limits.items()
        }

    def get(self, network: NetworkType) -> asyncio.Semaphore | None:
        """Look up the concurrency semaphore for a network type.

        Returns:
            The semaphore, or ``None`` for non-operational networks
            (LOCAL, UNKNOWN).
        """
        return self._map.get(network)

    def max_concurrency(self, enabled_networks: list[NetworkType] | None = None) -> int:
        """Return the configured total concurrency across operational networks."""
        networks = enabled_networks or list(self._limits)
        return sum(self._limits.get(network, 0) for network in networks)


class NetworkSemaphoresMixin:
    """Mixin providing per-network concurrency semaphores.

    Exposes a ``network_semaphores`` attribute of type
    [NetworkSemaphores][bigbrotr.services.common.mixins.NetworkSemaphores],
    initialized from the ``networks`` keyword argument.

    Services must pass ``networks=config.networks`` in their
    ``super().__init__()`` call.

    See Also:
        [Validator][bigbrotr.services.validator.Validator],
        [Monitor][bigbrotr.services.monitor.Monitor],
        [Synchronizer][bigbrotr.services.synchronizer.Synchronizer]:
            Services that compose this mixin for bounded concurrency.
    """

    network_semaphores: NetworkSemaphores

    def __init__(self, **kwargs: Any) -> None:
        networks: NetworksConfig = kwargs.pop("networks")
        super().__init__(**kwargs)
        self.network_semaphores = NetworkSemaphores(networks)


class ConcurrentStreamMixin:
    """Mixin providing concurrent item processing with streaming results.

    Adds ``_iter_concurrent()`` which launches ``asyncio.TaskGroup`` tasks
    and streams results through an ``asyncio.Queue`` bridge as each worker
    completes — enabling progressive metric updates instead of waiting for
    all items to finish.

    See Also:
        [Finder][bigbrotr.services.finder.Finder],
        [Synchronizer][bigbrotr.services.synchronizer.Synchronizer],
        [Monitor][bigbrotr.services.monitor.Monitor],
        [Validator][bigbrotr.services.validator.Validator]:
            Services that compose this mixin.
    """

    _logger: Logger

    async def _iter_concurrent(
        self,
        items: Sequence[T],
        worker: Callable[[T], AsyncIterator[R]],
        *,
        max_concurrency: int | None = None,
    ) -> AsyncIterator[R]:
        """Launch concurrent tasks and yield results as they are produced.

        A bounded worker pool consumes ``items`` up to ``max_concurrency``
        at a time. ``worker`` must be an async generator:
        it can yield zero or more results per item. Results stream through
        an ``asyncio.Queue`` so the caller can update metrics progressively
        as each yield arrives, without waiting for all workers to finish.

        Workers that yield nothing are silently skipped. Unhandled
        ``Exception`` subclasses inside a worker are caught by
        ``_run_worker`` and logged, so a single failing worker never
        aborts the whole group. A worker that ends with
        ``asyncio.CancelledError`` is treated like a worker that yielded
        nothing: it does not abort sibling tasks and produces no output
        for the caller.

        Args:
            items: Items to process concurrently.
            worker: Async generator callable receiving a single item.
                Yields results; yields nothing to skip.
            max_concurrency: Maximum number of worker tasks to run at once.
                ``None`` defaults to one task per input item.

        Yields:
            Results in arrival order (completion order within each worker).
        """
        if max_concurrency is not None and max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")

        work_queue: asyncio.Queue[T | object] = asyncio.Queue()
        result_queue: asyncio.Queue[object] = asyncio.Queue()
        worker_count = min(len(items), max_concurrency or len(items))

        for item in items:
            work_queue.put_nowait(item)
        for _ in range(worker_count):
            work_queue.put_nowait(_ITEM_DONE)

        async def _run_worker(item: T) -> None:
            try:
                async for result in worker(item):
                    await result_queue.put(result)
            except Exception as e:
                self._logger.error(
                    "concurrent_worker_error",
                    error=str(e),
                    error_type=type(e).__name__,
                )

        async def _worker_loop() -> None:
            while True:
                item = await work_queue.get()
                if item is _ITEM_DONE:
                    return
                await _run_worker(cast("T", item))

        async def _run_all() -> None:
            try:
                async with asyncio.TaskGroup() as tg:
                    for _ in range(worker_count):
                        tg.create_task(_worker_loop())
            finally:
                await result_queue.put(_QUEUE_DONE)

        runner = asyncio.create_task(_run_all())
        try:
            while True:
                result = await result_queue.get()
                if result is _QUEUE_DONE:
                    break
                yield cast("R", result)
        finally:
            if not runner.done():
                runner.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await runner
