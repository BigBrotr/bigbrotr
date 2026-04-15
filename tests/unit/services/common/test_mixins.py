"""Unit tests for services.common.mixins module.

Tests:
- ConcurrentStreamMixin - Concurrent item processing with streaming results
- NetworkSemaphores - Per-network concurrency semaphore container
- NetworkSemaphoresMixin - Mixin that provides a network_semaphores attribute via __init__
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from bigbrotr.models.constants import NetworkType
from bigbrotr.services.common.mixins import (
    ConcurrentStreamMixin,
    NetworkSemaphores,
    NetworkSemaphoresMixin,
)


# =============================================================================
# Helper: fake base class for ConcurrentStreamMixin tests
# =============================================================================


class _FakeConcurrentBase:
    """Minimal stand-in for BaseService with _logger."""

    def __init__(self) -> None:
        self._logger = MagicMock()


class _TestConcurrentService(ConcurrentStreamMixin, _FakeConcurrentBase):
    """Concrete class combining ConcurrentStreamMixin with fake base."""


# =============================================================================
# ConcurrentStreamMixin Tests
# =============================================================================


class TestConcurrentStreamMixinEmpty:
    async def test_empty_items_yields_nothing(self) -> None:
        svc = _TestConcurrentService()
        results = [r async for r in svc._iter_concurrent([], AsyncMock())]
        assert results == []


class TestConcurrentStreamMixinResults:
    async def test_single_item(self) -> None:
        svc = _TestConcurrentService()

        async def worker(item: int):
            yield item * 2

        results = [r async for r in svc._iter_concurrent([5], worker)]
        assert results == [10]

    async def test_multiple_items_all_returned(self) -> None:
        svc = _TestConcurrentService()

        async def worker(item: int):
            yield item * 10

        results = [r async for r in svc._iter_concurrent([1, 2, 3], worker)]
        assert sorted(results) == [10, 20, 30]

    async def test_workers_that_skip_produce_no_output(self) -> None:
        svc = _TestConcurrentService()

        async def worker(item: int):
            if item % 2 == 0:
                yield item * 2

        results = [r async for r in svc._iter_concurrent([1, 2, 3, 4], worker)]
        assert sorted(results) == [4, 8]

    async def test_workers_that_conditionally_yield(self) -> None:
        svc = _TestConcurrentService()

        async def worker(item: str):
            if item != "skip":
                yield item.upper()

        results = [r async for r in svc._iter_concurrent(["a", "skip", "b"], worker)]
        assert sorted(results) == ["A", "B"]

    async def test_results_stream_in_completion_order(self) -> None:
        svc = _TestConcurrentService()
        arrival_order: list[int] = []

        async def worker(item: int):
            await asyncio.sleep(0.01 * (3 - item))
            yield item

        async for result in svc._iter_concurrent([1, 2, 3], worker):
            arrival_order.append(result)

        assert set(arrival_order) == {1, 2, 3}
        assert arrival_order[0] == 3  # shortest sleep finishes first

    async def test_max_concurrency_limits_active_workers(self) -> None:
        svc = _TestConcurrentService()
        current = 0
        peak = 0
        lock = asyncio.Lock()

        async def worker(item: int):
            nonlocal current, peak
            async with lock:
                current += 1
                peak = max(peak, current)
            await asyncio.sleep(0.01)
            yield item
            async with lock:
                current -= 1

        results = [
            r
            async for r in svc._iter_concurrent(
                [1, 2, 3, 4, 5],
                worker,
                max_concurrency=2,
            )
        ]

        assert sorted(results) == [1, 2, 3, 4, 5]
        assert peak == 2


class TestConcurrentStreamMixinErrorHandling:
    async def test_worker_exception_logged_via_exception_group(self) -> None:
        svc = _TestConcurrentService()

        async def worker(item: int):
            raise RuntimeError(f"fail-{item}")
            yield  # pragma: no cover  — required to make this an async generator

        results = [r async for r in svc._iter_concurrent([1], worker)]
        assert results == []
        svc._logger.error.assert_called_once_with(
            "concurrent_worker_error",
            error="fail-1",
            error_type="RuntimeError",
        )

    async def test_multiple_worker_exceptions_all_logged(self) -> None:
        svc = _TestConcurrentService()

        async def worker(item: int):
            raise ValueError(f"bad-{item}")
            yield  # pragma: no cover  — required to make this an async generator

        results = [r async for r in svc._iter_concurrent([1, 2], worker)]
        assert results == []
        assert svc._logger.error.call_count == 2

    async def test_worker_catching_own_exception_returns_error_result(self) -> None:
        svc = _TestConcurrentService()

        async def worker(item: int):
            try:
                if item == 2:
                    raise OSError("network down")
                yield (item, True)
            except OSError:
                yield (item, False)

        results = [r async for r in svc._iter_concurrent([1, 2, 3], worker)]
        assert sorted(results) == [(1, True), (2, False), (3, True)]


class TestConcurrentStreamMixinCancellation:
    async def test_worker_cancelled_error_is_treated_as_empty_worker(self) -> None:
        svc = _TestConcurrentService()

        async def worker(item: int):
            raise asyncio.CancelledError
            yield  # pragma: no cover  — required to make this an async generator

        results = [r async for r in svc._iter_concurrent([1], worker)]
        assert results == []

    async def test_break_out_of_iteration_cleans_up(self) -> None:
        svc = _TestConcurrentService()
        collected: list[int] = []

        async def worker(item: int):
            await asyncio.sleep(0.01)
            yield item

        async for result in svc._iter_concurrent([1, 2, 3, 4, 5], worker):
            collected.append(result)
            if len(collected) >= 2:
                break

        assert len(collected) >= 2

    async def test_invalid_max_concurrency_raises(self) -> None:
        svc = _TestConcurrentService()

        async def worker(item: int):
            yield item

        with pytest.raises(ValueError, match="max_concurrency must be >= 1"):
            async for _ in svc._iter_concurrent([1], worker, max_concurrency=0):
                pass


# =============================================================================
# Helper: per-network mock config factory
# =============================================================================


def _make_network_config(
    *,
    clearnet_tasks: int = 50,
    tor_tasks: int = 10,
    i2p_tasks: int = 5,
    loki_tasks: int = 5,
) -> MagicMock:
    """Build a mock NetworksConfig with configurable max_tasks per network."""

    def _net_cfg(max_tasks: int) -> MagicMock:
        cfg = MagicMock()
        cfg.max_tasks = max_tasks
        return cfg

    configs = {
        NetworkType.CLEARNET: _net_cfg(clearnet_tasks),
        NetworkType.TOR: _net_cfg(tor_tasks),
        NetworkType.I2P: _net_cfg(i2p_tasks),
        NetworkType.LOKI: _net_cfg(loki_tasks),
    }

    mock = MagicMock()
    mock.get.side_effect = lambda nt: configs[nt]
    return mock


# =============================================================================
# Helper: fake base class simulating BaseService for mixin tests
# =============================================================================


class _FakeBase:
    """Minimal stand-in for BaseService (accepts and ignores extra kwargs)."""

    def __init__(self, **kwargs: object) -> None:
        pass


class _TestSemaphoreMixin(NetworkSemaphoresMixin, _FakeBase):
    """Concrete class combining the mixin with the fake base."""


# =============================================================================
# NetworkSemaphores Tests
# =============================================================================


class TestNetworkSemaphoresInit:
    """Tests for NetworkSemaphores construction."""

    def test_creates_semaphore_for_each_operational_network(self) -> None:
        """Constructor creates a semaphore for each operational network."""
        net_sems = NetworkSemaphores(_make_network_config())

        for nt in (NetworkType.CLEARNET, NetworkType.TOR, NetworkType.I2P, NetworkType.LOKI):
            assert net_sems.get(nt) is not None, f"Missing semaphore for {nt}"

    def test_semaphore_values_match_max_tasks(self) -> None:
        """Each semaphore's internal counter equals the network's max_tasks."""
        config = _make_network_config(
            clearnet_tasks=50,
            tor_tasks=10,
            i2p_tasks=5,
            loki_tasks=5,
        )
        net_sems = NetworkSemaphores(config)

        expected = {
            NetworkType.CLEARNET: 50,
            NetworkType.TOR: 10,
            NetworkType.I2P: 5,
            NetworkType.LOKI: 5,
        }
        for nt, expected_value in expected.items():
            assert net_sems.get(nt)._value == expected_value

    def test_different_networks_have_different_max_tasks(self) -> None:
        """Verify each network gets its own distinct max_tasks value."""
        config = _make_network_config(clearnet_tasks=100, tor_tasks=3)
        net_sems = NetworkSemaphores(config)

        assert net_sems.get(NetworkType.CLEARNET)._value == 100
        assert net_sems.get(NetworkType.TOR)._value == 3


class TestNetworkSemaphoresGet:
    """Tests for NetworkSemaphores.get()."""

    def test_returns_semaphore_for_operational_network(self) -> None:
        """get() returns an asyncio.Semaphore for operational networks."""
        net_sems = NetworkSemaphores(_make_network_config(tor_tasks=7))

        sem = net_sems.get(NetworkType.TOR)
        assert isinstance(sem, asyncio.Semaphore)
        assert sem._value == 7

    def test_returns_none_for_non_operational_network(self) -> None:
        """get() returns None for LOCAL and UNKNOWN networks."""
        net_sems = NetworkSemaphores(_make_network_config())

        assert net_sems.get(NetworkType.LOCAL) is None
        assert net_sems.get(NetworkType.UNKNOWN) is None


# =============================================================================
# NetworkSemaphoresMixin Tests
# =============================================================================


class TestNetworkSemaphoresMixinInit:
    """Tests for NetworkSemaphoresMixin automatic __init__ initialization."""

    def test_init_creates_network_semaphores(self) -> None:
        """__init__ assigns a NetworkSemaphores to self.network_semaphores."""
        mixin = _TestSemaphoreMixin(networks=_make_network_config())
        assert isinstance(mixin.network_semaphores, NetworkSemaphores)

    def test_semaphores_are_functional(self) -> None:
        """Semaphores created by __init__ are usable asyncio.Semaphore instances."""
        mixin = _TestSemaphoreMixin(networks=_make_network_config())

        for nt in (NetworkType.CLEARNET, NetworkType.TOR, NetworkType.I2P, NetworkType.LOKI):
            sem = mixin.network_semaphores.get(nt)
            assert isinstance(sem, asyncio.Semaphore), f"{nt}: not a Semaphore"


class TestNetworkSemaphoresMixinComposition:
    """Tests for composing NetworkSemaphoresMixin with other classes."""

    def test_composes_with_plain_class(self) -> None:
        """Mixin works correctly when composed with a user-defined class."""

        class DummyService(NetworkSemaphoresMixin, _FakeBase):
            pass

        svc = DummyService(networks=_make_network_config(clearnet_tasks=20))
        sem = svc.network_semaphores.get(NetworkType.CLEARNET)
        assert isinstance(sem, asyncio.Semaphore)
        assert sem._value == 20


# =============================================================================
# ConcurrentStreamMixin: early break cancels runner (lines 180-183)
# =============================================================================


class TestConcurrentStreamMixinRunnerCancellation:
    async def test_break_cancels_running_runner_task(self) -> None:
        svc = _TestConcurrentService()
        gate = asyncio.Event()

        async def slow_worker(item: int):
            if item == 1:
                yield item
            else:
                await gate.wait()
                yield item

        async for _result in svc._iter_concurrent([1, 2, 3], slow_worker):
            break

        await asyncio.sleep(0.01)
