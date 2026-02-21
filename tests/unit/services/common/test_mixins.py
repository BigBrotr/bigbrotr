"""Unit tests for services.common.mixins mixin classes.

Tests:
- BatchProgressMixin - Mixin that provides a _progress attribute via __init__
- NetworkSemaphoreMixin - Mixin that initializes per-network semaphores via __init__

NOTE: The BatchProgress dataclass itself is thoroughly tested in
tests/unit/services/test_progress.py.  These tests focus exclusively
on the mixin classes that compose it.
"""

import asyncio
from unittest.mock import MagicMock

from bigbrotr.models.constants import NetworkType
from bigbrotr.services.common.mixins import BatchProgress, BatchProgressMixin, NetworkSemaphoreMixin


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
    """Minimal stand-in for BaseService that provides _config.networks."""

    def __init__(self, *, networks: MagicMock | None = None, **kwargs: object) -> None:
        self._config = MagicMock()
        self._config.networks = networks or _make_network_config()


class _TestSemaphoreMixin(NetworkSemaphoreMixin, _FakeBase):
    """Concrete class combining the mixin with the fake base."""


# =============================================================================
# BatchProgressMixin Tests
# =============================================================================


class TestBatchProgressMixinInit:
    """Tests for BatchProgressMixin automatic __init__."""

    def test_init_creates_batch_progress_instance(self) -> None:
        """__init__ assigns a BatchProgress to self._progress."""
        mixin = BatchProgressMixin()
        assert isinstance(mixin._progress, BatchProgress)

    def test_fresh_progress_has_zero_counters(self) -> None:
        """A freshly initialized progress has all counters at zero."""
        mixin = BatchProgressMixin()
        assert mixin._progress.total == 0
        assert mixin._progress.processed == 0
        assert mixin._progress.success == 0
        assert mixin._progress.failure == 0
        assert mixin._progress.chunks == 0

    def test_reset_clears_modified_counters(self) -> None:
        """Calling reset() clears accumulated counter values."""
        mixin = BatchProgressMixin()
        mixin._progress.total = 100
        mixin._progress.processed = 42

        mixin._progress.reset()
        assert mixin._progress.total == 0
        assert mixin._progress.processed == 0


class TestBatchProgressMixinComposition:
    """Tests for composing BatchProgressMixin with other classes."""

    def test_composes_with_plain_class(self) -> None:
        """Mixin works correctly when composed with a user-defined class."""

        class DummyService(BatchProgressMixin):
            pass

        svc = DummyService()
        assert isinstance(svc._progress, BatchProgress)
        svc._progress.total = 50
        assert svc._progress.remaining == 50


# =============================================================================
# NetworkSemaphoreMixin Tests
# =============================================================================


class TestNetworkSemaphoreMixinInit:
    """Tests for NetworkSemaphoreMixin automatic __init__ initialization."""

    def test_init_creates_semaphores_for_operational_networks(self) -> None:
        """__init__ creates a semaphore for each operational network."""
        mixin = _TestSemaphoreMixin()

        for nt in (NetworkType.CLEARNET, NetworkType.TOR, NetworkType.I2P, NetworkType.LOKI):
            assert nt in mixin._semaphores, f"Missing semaphore for {nt}"

    def test_excludes_non_operational_networks(self) -> None:
        """LOCAL and UNKNOWN do not get semaphores (no relays use them)."""
        mixin = _TestSemaphoreMixin()

        assert NetworkType.LOCAL not in mixin._semaphores
        assert NetworkType.UNKNOWN not in mixin._semaphores

    def test_semaphore_count_matches_operational_networks(self) -> None:
        """The number of semaphores equals the 4 operational network types."""
        mixin = _TestSemaphoreMixin()
        assert len(mixin._semaphores) == 4

    def test_semaphores_are_asyncio_semaphore_instances(self) -> None:
        """Every value in the semaphore dict is an asyncio.Semaphore."""
        mixin = _TestSemaphoreMixin()

        for nt, sem in mixin._semaphores.items():
            assert isinstance(sem, asyncio.Semaphore), f"{nt}: not a Semaphore"

    def test_semaphore_values_match_max_tasks(self) -> None:
        """Each semaphore's internal counter equals the network's max_tasks."""
        config = _make_network_config(
            clearnet_tasks=50,
            tor_tasks=10,
            i2p_tasks=5,
            loki_tasks=5,
        )
        mixin = _TestSemaphoreMixin(networks=config)

        expected = {
            NetworkType.CLEARNET: 50,
            NetworkType.TOR: 10,
            NetworkType.I2P: 5,
            NetworkType.LOKI: 5,
        }
        for nt, expected_value in expected.items():
            # asyncio.Semaphore stores the counter in _value
            assert mixin._semaphores[nt]._value == expected_value

    def test_different_networks_can_have_different_max_tasks(self) -> None:
        """Verify each network gets its own distinct max_tasks value."""
        config = _make_network_config(clearnet_tasks=100, tor_tasks=3)
        mixin = _TestSemaphoreMixin(networks=config)

        assert mixin._semaphores[NetworkType.CLEARNET]._value == 100
        assert mixin._semaphores[NetworkType.TOR]._value == 3


class TestNetworkSemaphoreMixinGetSemaphore:
    """Tests for NetworkSemaphoreMixin.get_semaphore()."""

    def test_returns_correct_semaphore_for_known_network(self) -> None:
        """get_semaphore() returns the semaphore stored for that network."""
        mixin = _TestSemaphoreMixin(networks=_make_network_config(tor_tasks=7))

        sem = mixin.get_semaphore(NetworkType.TOR)
        assert sem is mixin._semaphores[NetworkType.TOR]
        assert sem._value == 7

    def test_returns_semaphore_for_each_operational_network(self) -> None:
        """get_semaphore() returns a non-None value for every operational network."""
        mixin = _TestSemaphoreMixin()

        for nt in (NetworkType.CLEARNET, NetworkType.TOR, NetworkType.I2P, NetworkType.LOKI):
            sem = mixin.get_semaphore(nt)
            assert sem is not None, f"get_semaphore({nt}) returned None"
            assert isinstance(sem, asyncio.Semaphore)

    def test_returns_none_for_non_operational_network(self) -> None:
        """get_semaphore() returns None for LOCAL and UNKNOWN networks."""
        mixin = _TestSemaphoreMixin()

        assert mixin.get_semaphore(NetworkType.LOCAL) is None
        assert mixin.get_semaphore(NetworkType.UNKNOWN) is None


class TestNetworkSemaphoreMixinComposition:
    """Tests for composing NetworkSemaphoreMixin with other classes."""

    def test_composes_with_plain_class(self) -> None:
        """Mixin works correctly when composed with a user-defined class."""

        class DummyService(NetworkSemaphoreMixin, _FakeBase):
            pass

        svc = DummyService(networks=_make_network_config(clearnet_tasks=20))
        sem = svc.get_semaphore(NetworkType.CLEARNET)
        assert isinstance(sem, asyncio.Semaphore)
        assert sem._value == 20
