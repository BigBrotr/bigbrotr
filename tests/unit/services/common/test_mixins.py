"""Unit tests for services.common.mixins mixin classes.

Tests:
- ChunkProgressMixin - Mixin that provides a progress attribute via __init__
- NetworkSemaphores - Per-network concurrency semaphore container
- NetworkSemaphoresMixin - Mixin that provides a semaphores attribute via __init__

NOTE: The ChunkProgress dataclass itself is thoroughly tested in
tests/unit/services/test_progress.py.  These tests focus exclusively
on the mixin classes that compose it.
"""

import asyncio
from unittest.mock import MagicMock

from bigbrotr.models.constants import NetworkType
from bigbrotr.services.common.mixins import (
    ChunkProgress,
    ChunkProgressMixin,
    NetworkSemaphores,
    NetworkSemaphoresMixin,
)


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
    """Build a mock NetworkConfig with configurable max_tasks per network."""

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
# BatchProgressMixin Tests
# =============================================================================


class TestChunkProgressMixinInit:
    """Tests for ChunkProgressMixin automatic __init__."""

    def test_init_creates_chunk_progress_instance(self) -> None:
        """__init__ assigns a ChunkProgress to self.progress."""
        mixin = ChunkProgressMixin()
        assert isinstance(mixin.progress, ChunkProgress)

    def test_fresh_progress_has_zero_counters(self) -> None:
        """A freshly initialized progress has all counters at zero."""
        mixin = ChunkProgressMixin()
        assert mixin.progress.total == 0
        assert mixin.progress.processed == 0
        assert mixin.progress.succeeded == 0
        assert mixin.progress.failed == 0
        assert mixin.progress.chunks == 0

    def test_reset_clears_modified_counters(self) -> None:
        """Calling reset() clears accumulated counter values."""
        mixin = ChunkProgressMixin()
        mixin.progress.total = 100
        mixin.progress.processed = 42

        mixin.progress.reset()
        assert mixin.progress.total == 0
        assert mixin.progress.processed == 0


class TestChunkProgressMixinComposition:
    """Tests for composing ChunkProgressMixin with other classes."""

    def test_composes_with_plain_class(self) -> None:
        """Mixin works correctly when composed with a user-defined class."""

        class DummyService(ChunkProgressMixin):
            pass

        svc = DummyService()
        assert isinstance(svc.progress, ChunkProgress)
        svc.progress.total = 50
        assert svc.progress.remaining == 50


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
        """__init__ assigns a NetworkSemaphores to self.semaphores."""
        mixin = _TestSemaphoreMixin(networks=_make_network_config())
        assert isinstance(mixin.semaphores, NetworkSemaphores)

    def test_semaphores_are_functional(self) -> None:
        """Semaphores created by __init__ are usable asyncio.Semaphore instances."""
        mixin = _TestSemaphoreMixin(networks=_make_network_config())

        for nt in (NetworkType.CLEARNET, NetworkType.TOR, NetworkType.I2P, NetworkType.LOKI):
            sem = mixin.semaphores.get(nt)
            assert isinstance(sem, asyncio.Semaphore), f"{nt}: not a Semaphore"


class TestNetworkSemaphoresMixinComposition:
    """Tests for composing NetworkSemaphoresMixin with other classes."""

    def test_composes_with_plain_class(self) -> None:
        """Mixin works correctly when composed with a user-defined class."""

        class DummyService(NetworkSemaphoresMixin, _FakeBase):
            pass

        svc = DummyService(networks=_make_network_config(clearnet_tasks=20))
        sem = svc.semaphores.get(NetworkType.CLEARNET)
        assert isinstance(sem, asyncio.Semaphore)
        assert sem._value == 20
