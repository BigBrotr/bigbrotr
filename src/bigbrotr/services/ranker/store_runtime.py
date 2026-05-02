"""Async lifecycle wrapper for the ranker DuckDB store."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import TYPE_CHECKING, TypeVar

import duckdb


if TYPE_CHECKING:
    from collections.abc import Callable

    from .utils import RankerStore


_StoreResult = TypeVar("_StoreResult")


class RankerStoreRuntime:
    """Own the single-thread executor used to drive the ranker DuckDB store."""

    def __init__(self, store: RankerStore) -> None:
        self._store = store
        self._executor: ThreadPoolExecutor | None = None

    async def open(self) -> None:
        """Initialize the DuckDB store and clean up the executor on failure."""
        try:
            await self.run(self._store.ensure_initialized)
        except (duckdb.Error, OSError, RuntimeError):
            executor = self._executor
            self._executor = None
            if executor is not None:
                await asyncio.to_thread(executor.shutdown, wait=True)
            raise

    async def close(self) -> None:
        """Close the DuckDB store and release the dedicated executor."""
        executor = self._executor
        self._executor = None
        if executor is None:
            return
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(executor, self._store.close)
        finally:
            await asyncio.to_thread(executor.shutdown, wait=True)

    async def run(
        self,
        func: Callable[..., _StoreResult],
        *args: object,
        **kwargs: object,
    ) -> _StoreResult:
        """Execute one store operation on the dedicated single-thread executor."""
        loop = asyncio.get_running_loop()
        executor = self._executor
        if executor is None:
            executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ranker-store")
            self._executor = executor
        return await loop.run_in_executor(
            executor,
            partial(func, *args, **kwargs),
        )
