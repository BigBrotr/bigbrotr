"""Unit tests for services.common.mixins mixin classes.

Tests:
- BatchProgressMixin - Mixin that provides a _progress attribute
- NetworkSemaphoreMixin - Mixin that provides per-network semaphores

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
    local_tasks: int = 1,
    unknown_tasks: int = 1,
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
        NetworkType.LOCAL: _net_cfg(local_tasks),
        NetworkType.UNKNOWN: _net_cfg(unknown_tasks),
    }

    mock = MagicMock()
    mock.get.side_effect = lambda nt: configs[nt]
    return mock


# =============================================================================
# BatchProgressMixin Tests
# =============================================================================


class TestBatchProgressMixinInit:
    """Tests for BatchProgressMixin._init_progress()."""

    def test_init_progress_creates_batch_progress_instance(self) -> None:
        """_init_progress() assigns a BatchProgress to self._progress."""
        mixin = BatchProgressMixin()
        mixin._init_progress()
        assert isinstance(mixin._progress, BatchProgress)

    def test_fresh_progress_has_zero_counters(self) -> None:
        """A freshly initialized progress has all counters at zero."""
        mixin = BatchProgressMixin()
        mixin._init_progress()
        assert mixin._progress.total == 0
        assert mixin._progress.processed == 0
        assert mixin._progress.success == 0
        assert mixin._progress.failure == 0
        assert mixin._progress.chunks == 0

    def test_reinit_replaces_previous_instance(self) -> None:
        """Calling _init_progress() again creates a new BatchProgress."""
        mixin = BatchProgressMixin()
        mixin._init_progress()
        first = mixin._progress

        mixin._init_progress()
        second = mixin._progress

        assert first is not second

    def test_reinit_resets_modified_counters(self) -> None:
        """Re-initializing discards any accumulated counter values."""
        mixin = BatchProgressMixin()
        mixin._init_progress()
        mixin._progress.total = 100
        mixin._progress.processed = 42

        mixin._init_progress()
        assert mixin._progress.total == 0
        assert mixin._progress.processed == 0


class TestBatchProgressMixinComposition:
    """Tests for composing BatchProgressMixin with other classes."""

    def test_composes_with_plain_class(self) -> None:
        """Mixin works correctly when composed with a user-defined class."""

        class DummyService(BatchProgressMixin):
            def __init__(self) -> None:
                self._init_progress()

        svc = DummyService()
        assert isinstance(svc._progress, BatchProgress)
        svc._progress.total = 50
        assert svc._progress.remaining == 50


# =============================================================================
# NetworkSemaphoreMixin Tests
# =============================================================================


class TestNetworkSemaphoreMixinInit:
    """Tests for NetworkSemaphoreMixin._init_semaphores()."""

    def test_creates_entry_for_every_operational_network(self) -> None:
        """_init_semaphores() creates a semaphore for each operational network."""
        mixin = NetworkSemaphoreMixin()
        mixin._init_semaphores(_make_network_config())

        for nt in (NetworkType.CLEARNET, NetworkType.TOR, NetworkType.I2P, NetworkType.LOKI):
            assert nt in mixin._semaphores, f"Missing semaphore for {nt}"

    def test_excludes_non_operational_networks(self) -> None:
        """LOCAL and UNKNOWN do not get semaphores (no relays use them)."""
        mixin = NetworkSemaphoreMixin()
        mixin._init_semaphores(_make_network_config())

        assert NetworkType.LOCAL not in mixin._semaphores
        assert NetworkType.UNKNOWN not in mixin._semaphores

    def test_semaphore_count_matches_operational_networks(self) -> None:
        """The number of semaphores equals the 4 operational network types."""
        mixin = NetworkSemaphoreMixin()
        mixin._init_semaphores(_make_network_config())
        assert len(mixin._semaphores) == 4

    def test_semaphores_are_asyncio_semaphore_instances(self) -> None:
        """Every value in the semaphore dict is an asyncio.Semaphore."""
        mixin = NetworkSemaphoreMixin()
        mixin._init_semaphores(_make_network_config())

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
        mixin = NetworkSemaphoreMixin()
        mixin._init_semaphores(config)

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
        mixin = NetworkSemaphoreMixin()
        mixin._init_semaphores(config)

        assert mixin._semaphores[NetworkType.CLEARNET]._value == 100
        assert mixin._semaphores[NetworkType.TOR]._value == 3

    def test_reinit_replaces_old_semaphores(self) -> None:
        """Calling _init_semaphores() again replaces the entire dict."""
        mixin = NetworkSemaphoreMixin()

        config_a = _make_network_config(clearnet_tasks=50)
        mixin._init_semaphores(config_a)
        first_sem = mixin._semaphores[NetworkType.CLEARNET]

        config_b = _make_network_config(clearnet_tasks=99)
        mixin._init_semaphores(config_b)
        second_sem = mixin._semaphores[NetworkType.CLEARNET]

        assert first_sem is not second_sem
        assert second_sem._value == 99


class TestNetworkSemaphoreMixinGetSemaphore:
    """Tests for NetworkSemaphoreMixin._get_semaphore()."""

    def test_returns_correct_semaphore_for_known_network(self) -> None:
        """_get_semaphore() returns the semaphore stored for that network."""
        mixin = NetworkSemaphoreMixin()
        mixin._init_semaphores(_make_network_config(tor_tasks=7))

        sem = mixin._get_semaphore(NetworkType.TOR)
        assert sem is mixin._semaphores[NetworkType.TOR]
        assert sem._value == 7

    def test_returns_none_for_unknown_key_before_init(self) -> None:
        """_get_semaphore() returns None when _semaphores is empty."""
        mixin = NetworkSemaphoreMixin()
        mixin._semaphores = {}

        result = mixin._get_semaphore(NetworkType.CLEARNET)
        assert result is None

    def test_returns_semaphore_for_each_operational_network(self) -> None:
        """_get_semaphore() returns a non-None value for every operational network."""
        mixin = NetworkSemaphoreMixin()
        mixin._init_semaphores(_make_network_config())

        for nt in (NetworkType.CLEARNET, NetworkType.TOR, NetworkType.I2P, NetworkType.LOKI):
            sem = mixin._get_semaphore(nt)
            assert sem is not None, f"_get_semaphore({nt}) returned None"
            assert isinstance(sem, asyncio.Semaphore)

    def test_returns_none_for_non_operational_network(self) -> None:
        """_get_semaphore() returns None for LOCAL and UNKNOWN networks."""
        mixin = NetworkSemaphoreMixin()
        mixin._init_semaphores(_make_network_config())

        assert mixin._get_semaphore(NetworkType.LOCAL) is None
        assert mixin._get_semaphore(NetworkType.UNKNOWN) is None


class TestNetworkSemaphoreMixinComposition:
    """Tests for composing NetworkSemaphoreMixin with other classes."""

    def test_composes_with_plain_class(self) -> None:
        """Mixin works correctly when composed with a user-defined class."""

        class DummyService(NetworkSemaphoreMixin):
            def __init__(self, networks: MagicMock) -> None:
                self._init_semaphores(networks)

        svc = DummyService(_make_network_config(clearnet_tasks=20))
        sem = svc._get_semaphore(NetworkType.CLEARNET)
        assert isinstance(sem, asyncio.Semaphore)
        assert sem._value == 20
