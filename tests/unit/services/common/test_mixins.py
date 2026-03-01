"""Unit tests for services.common.mixins module.

Tests:
- ChunkProgress - Dataclass for tracking chunk processing progress
- ChunkProgressMixin - Mixin that provides a progress attribute via __init__
- NetworkSemaphores - Per-network concurrency semaphore container
- NetworkSemaphoresMixin - Mixin that provides a network_semaphores attribute via __init__
- CatalogAccessMixin - Mixin for schema catalog lifecycle and table access policy
"""

import asyncio
import time
from typing import Self
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bigbrotr.models.constants import NetworkType
from bigbrotr.services.common.catalog import Catalog
from bigbrotr.services.common.mixins import (
    CatalogAccessMixin,
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
# BatchProgressMixin Tests
# =============================================================================


class TestChunkProgressMixinInit:
    """Tests for ChunkProgressMixin automatic __init__."""

    def test_init_creates_chunk_progress_instance(self) -> None:
        """__init__ assigns a ChunkProgress to self.chunk_progress."""
        mixin = ChunkProgressMixin()
        assert isinstance(mixin.chunk_progress, ChunkProgress)

    def test_fresh_progress_has_zero_counters(self) -> None:
        """A freshly initialized progress has all counters at zero."""
        mixin = ChunkProgressMixin()
        assert mixin.chunk_progress.total == 0
        assert mixin.chunk_progress.processed == 0
        assert mixin.chunk_progress.succeeded == 0
        assert mixin.chunk_progress.failed == 0
        assert mixin.chunk_progress.chunks == 0

    def test_reset_clears_modified_counters(self) -> None:
        """Calling reset() clears accumulated counter values."""
        mixin = ChunkProgressMixin()
        mixin.chunk_progress.total = 100
        mixin.chunk_progress.processed = 42

        mixin.chunk_progress.reset()
        assert mixin.chunk_progress.total == 0
        assert mixin.chunk_progress.processed == 0


class TestChunkProgressMixinComposition:
    """Tests for composing ChunkProgressMixin with other classes."""

    def test_composes_with_plain_class(self) -> None:
        """Mixin works correctly when composed with a user-defined class."""

        class DummyService(ChunkProgressMixin):
            pass

        svc = DummyService()
        assert isinstance(svc.chunk_progress, ChunkProgress)
        svc.chunk_progress.total = 50
        assert svc.chunk_progress.remaining == 50


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
# ChunkProgress Default Values Tests
# =============================================================================


class TestChunkProgressDefaults:
    """Tests for ChunkProgress default field values."""

    def test_default_started_at(self) -> None:
        """Test default started_at is 0.0."""
        progress = ChunkProgress()
        assert progress.started_at == 0.0

    def test_default_total(self) -> None:
        """Test default total is 0."""
        progress = ChunkProgress()
        assert progress.total == 0

    def test_default_processed(self) -> None:
        """Test default processed is 0."""
        progress = ChunkProgress()
        assert progress.processed == 0

    def test_default_succeeded(self) -> None:
        """Test default succeeded is 0."""
        progress = ChunkProgress()
        assert progress.succeeded == 0

    def test_default_failed(self) -> None:
        """Test default failed is 0."""
        progress = ChunkProgress()
        assert progress.failed == 0

    def test_default_chunks(self) -> None:
        """Test default chunks is 0."""
        progress = ChunkProgress()
        assert progress.chunks == 0


# =============================================================================
# ChunkProgress Field Assignment Tests
# =============================================================================


class TestChunkProgressFieldAssignment:
    """Tests for ChunkProgress field assignments and increments."""

    def test_assign_started_at(self) -> None:
        """Test assigning started_at."""
        progress = ChunkProgress()
        progress.started_at = 1700000000.0
        assert progress.started_at == 1700000000.0

    def test_assign_total(self) -> None:
        """Test assigning total."""
        progress = ChunkProgress()
        progress.total = 100
        assert progress.total == 100

    def test_assign_processed(self) -> None:
        """Test assigning processed."""
        progress = ChunkProgress()
        progress.processed = 50
        assert progress.processed == 50

    def test_assign_succeeded(self) -> None:
        """Test assigning succeeded."""
        progress = ChunkProgress()
        progress.succeeded = 45
        assert progress.succeeded == 45

    def test_assign_failed(self) -> None:
        """Test assigning failed."""
        progress = ChunkProgress()
        progress.failed = 5
        assert progress.failed == 5

    def test_assign_chunks(self) -> None:
        """Test assigning chunks."""
        progress = ChunkProgress()
        progress.chunks = 10
        assert progress.chunks == 10

    def test_increment_processed(self) -> None:
        """Test incrementing processed counter."""
        progress = ChunkProgress()
        progress.processed += 1
        progress.processed += 1
        assert progress.processed == 2

    def test_increment_succeeded(self) -> None:
        """Test incrementing succeeded counter."""
        progress = ChunkProgress()
        progress.succeeded += 1
        progress.succeeded += 1
        progress.succeeded += 1
        assert progress.succeeded == 3

    def test_increment_failed(self) -> None:
        """Test incrementing failed counter."""
        progress = ChunkProgress()
        progress.failed += 1
        assert progress.failed == 1


# =============================================================================
# ChunkProgress Initialization Tests
# =============================================================================


class TestChunkProgressInitialization:
    """Tests for ChunkProgress initialization with values."""

    def test_init_with_values(self) -> None:
        """Test initialization with all custom values."""
        progress = ChunkProgress(
            started_at=1700000000.0,
            total=100,
            processed=50,
            succeeded=45,
            failed=5,
            chunks=10,
        )
        assert progress.started_at == 1700000000.0
        assert progress.total == 100
        assert progress.processed == 50
        assert progress.succeeded == 45
        assert progress.failed == 5
        assert progress.chunks == 10

    def test_init_partial_values(self) -> None:
        """Test initialization with partial values (rest are defaults)."""
        progress = ChunkProgress(total=100)
        assert progress.total == 100
        assert progress.processed == 0
        assert progress.succeeded == 0


# =============================================================================
# ChunkProgress reset() Method Tests
# =============================================================================


class TestChunkProgressReset:
    """Tests for ChunkProgress.reset() method."""

    def test_reset_sets_started_at_to_current_time(self) -> None:
        """Test reset() sets started_at to current time."""
        progress = ChunkProgress()
        before = time.time()
        progress.reset()
        after = time.time()

        assert before <= progress.started_at <= after

    def test_reset_clears_total(self) -> None:
        """Test reset() sets total to 0."""
        progress = ChunkProgress(total=100)
        progress.reset()
        assert progress.total == 0

    def test_reset_clears_processed(self) -> None:
        """Test reset() sets processed to 0."""
        progress = ChunkProgress(processed=50)
        progress.reset()
        assert progress.processed == 0

    def test_reset_clears_succeeded(self) -> None:
        """Test reset() sets succeeded to 0."""
        progress = ChunkProgress(succeeded=45)
        progress.reset()
        assert progress.succeeded == 0

    def test_reset_clears_failed(self) -> None:
        """Test reset() sets failed to 0."""
        progress = ChunkProgress(failed=5)
        progress.reset()
        assert progress.failed == 0

    def test_reset_clears_chunks(self) -> None:
        """Test reset() sets chunks to 0."""
        progress = ChunkProgress(chunks=10)
        progress.reset()
        assert progress.chunks == 0

    def test_reset_clears_all_counters(self) -> None:
        """Test reset() clears all counters at once."""
        progress = ChunkProgress(
            started_at=1000.0,
            total=100,
            processed=50,
            succeeded=45,
            failed=5,
            chunks=10,
        )
        progress.reset()

        assert progress.total == 0
        assert progress.processed == 0
        assert progress.succeeded == 0
        assert progress.failed == 0
        assert progress.chunks == 0
        assert progress.started_at > 0

    def test_reset_multiple_times(self) -> None:
        """Test reset() can be called multiple times."""
        progress = ChunkProgress()

        progress.reset()
        first_started_at = progress.started_at

        time.sleep(0.01)
        progress.reset()
        second_started_at = progress.started_at

        assert second_started_at > first_started_at


# =============================================================================
# ChunkProgress record() Method Tests
# =============================================================================


class TestChunkProgressRecord:
    """Tests for ChunkProgress.record() method."""

    def test_record_updates_all_counters(self) -> None:
        """Test record updates processed, succeeded, failed, and chunks."""
        progress = ChunkProgress()
        progress.record(succeeded=8, failed=2)

        assert progress.processed == 10
        assert progress.succeeded == 8
        assert progress.failed == 2
        assert progress.chunks == 1

    def test_record_accumulates(self) -> None:
        """Test record accumulates across multiple calls."""
        progress = ChunkProgress()
        progress.record(succeeded=5, failed=1)
        progress.record(succeeded=3, failed=2)

        assert progress.processed == 11
        assert progress.succeeded == 8
        assert progress.failed == 3
        assert progress.chunks == 2

    def test_record_all_succeeded(self) -> None:
        """Test record with no failures."""
        progress = ChunkProgress()
        progress.record(succeeded=10, failed=0)

        assert progress.processed == 10
        assert progress.succeeded == 10
        assert progress.failed == 0
        assert progress.chunks == 1

    def test_record_all_failed(self) -> None:
        """Test record with no successes."""
        progress = ChunkProgress()
        progress.record(succeeded=0, failed=10)

        assert progress.processed == 10
        assert progress.succeeded == 0
        assert progress.failed == 10
        assert progress.chunks == 1

    def test_record_empty(self) -> None:
        """Test record with zero items still increments chunks."""
        progress = ChunkProgress()
        progress.record(succeeded=0, failed=0)

        assert progress.processed == 0
        assert progress.chunks == 1

    def test_record_updates_remaining(self) -> None:
        """Test record correctly affects remaining calculation."""
        progress = ChunkProgress()
        progress.total = 100
        progress.record(succeeded=30, failed=10)

        assert progress.remaining == 60


# =============================================================================
# ChunkProgress remaining Property Tests
# =============================================================================


class TestChunkProgressRemaining:
    """Tests for ChunkProgress.remaining computed property."""

    def test_remaining_all_items(self) -> None:
        """Test remaining equals total when nothing processed."""
        progress = ChunkProgress(total=100, processed=0)
        assert progress.remaining == 100

    def test_remaining_some_processed(self) -> None:
        """Test remaining is total minus processed."""
        progress = ChunkProgress(total=100, processed=30)
        assert progress.remaining == 70

    def test_remaining_all_processed(self) -> None:
        """Test remaining is 0 when all processed."""
        progress = ChunkProgress(total=100, processed=100)
        assert progress.remaining == 0

    def test_remaining_default_values(self) -> None:
        """Test remaining is 0 with default values."""
        progress = ChunkProgress()
        assert progress.remaining == 0

    def test_remaining_negative_if_overprocessed(self) -> None:
        """Test remaining can be negative if processed > total."""
        progress = ChunkProgress(total=10, processed=15)
        assert progress.remaining == -5


# =============================================================================
# ChunkProgress elapsed Property Tests
# =============================================================================


class TestChunkProgressElapsed:
    """Tests for ChunkProgress.elapsed computed property."""

    def test_elapsed_returns_float(self) -> None:
        """Test elapsed returns a float."""
        progress = ChunkProgress()
        progress.reset()
        assert isinstance(progress.elapsed, float)

    def test_elapsed_increases_over_time(self) -> None:
        """Test elapsed increases as time passes."""
        progress = ChunkProgress()
        progress.reset()
        first_elapsed = progress.elapsed
        time.sleep(0.1)
        second_elapsed = progress.elapsed
        assert second_elapsed > first_elapsed

    def test_elapsed_rounded_to_one_decimal(self) -> None:
        """Test elapsed is rounded to 1 decimal place."""
        with patch("time.monotonic", return_value=1000.0):
            progress = ChunkProgress()
            progress._monotonic_start = 999.123

        with patch("time.monotonic", return_value=1000.0):
            elapsed = progress.elapsed

        # 1000.0 - 999.123 = 0.877, rounded to 0.9
        assert elapsed == 0.9

    def test_elapsed_with_zero_started_at(self) -> None:
        """Test elapsed works with default started_at of 0."""
        progress = ChunkProgress()
        assert progress.elapsed > 0

    def test_elapsed_immediately_after_reset(self) -> None:
        """Test elapsed is very small immediately after reset."""
        progress = ChunkProgress()
        progress.reset()
        elapsed = progress.elapsed
        assert elapsed < 0.5


# =============================================================================
# ChunkProgress Typical Usage Tests
# =============================================================================


class TestChunkProgressTypicalUsage:
    """Tests for ChunkProgress typical usage patterns."""

    def test_processing_workflow(self) -> None:
        """Test typical batch processing workflow."""
        progress = ChunkProgress()
        progress.reset()

        progress.total = 10
        for i in range(10):
            progress.processed += 1
            if i % 3 == 0:
                progress.failed += 1
            else:
                progress.succeeded += 1
            if i % 5 == 0:
                progress.chunks += 1

        assert progress.total == 10
        assert progress.processed == 10
        assert progress.remaining == 0
        assert progress.succeeded + progress.failed == 10

    def test_multiple_cycles(self) -> None:
        """Test multiple processing cycles with reset."""
        progress = ChunkProgress()

        # First cycle
        progress.reset()
        progress.total = 100
        progress.processed = 100
        progress.succeeded = 95
        progress.failed = 5

        assert progress.remaining == 0

        # Second cycle (reset)
        progress.reset()
        assert progress.total == 0
        assert progress.processed == 0
        assert progress.succeeded == 0
        assert progress.failed == 0

        # New data
        progress.total = 50
        progress.processed = 25
        assert progress.remaining == 25

    def test_summary_calculation(self) -> None:
        """Test calculating summary statistics."""
        progress = ChunkProgress()
        progress.reset()

        progress.total = 100
        progress.processed = 80
        progress.succeeded = 75
        progress.failed = 5
        progress.chunks = 8

        success_rate = (progress.succeeded / progress.processed) * 100
        progress_pct = (progress.processed / progress.total) * 100

        assert success_rate == pytest.approx(93.75)
        assert progress_pct == 80.0
        assert progress.remaining == 20


# =============================================================================
# Helper: fake base class for CatalogAccessMixin tests
# =============================================================================


class _FakeCatalogBase:
    """Minimal stand-in for BaseService with _brotr, _logger, _config."""

    def __init__(self, **kwargs: object) -> None:
        self._brotr = MagicMock()
        self._logger = MagicMock()
        self._config = MagicMock()

    async def __aenter__(self) -> Self:
        return self


class _TestCatalogService(CatalogAccessMixin, _FakeCatalogBase):
    """Concrete class combining CatalogAccessMixin with the fake base."""


# =============================================================================
# CatalogAccessMixin Tests
# =============================================================================


class TestCatalogAccessMixinInit:
    """Tests for CatalogAccessMixin automatic __init__."""

    def test_init_creates_catalog_instance(self) -> None:
        svc = _TestCatalogService()
        assert isinstance(svc._catalog, Catalog)

    def test_catalog_has_no_tables_before_discovery(self) -> None:
        svc = _TestCatalogService()
        assert svc._catalog.tables == {}


class TestCatalogAccessMixinAenter:
    """Tests for CatalogAccessMixin.__aenter__ lifecycle."""

    async def test_aenter_calls_discover_with_brotr(self) -> None:
        svc = _TestCatalogService()
        svc._catalog = MagicMock()
        svc._catalog.discover = AsyncMock()
        svc._catalog.tables = {}

        await svc.__aenter__()

        svc._catalog.discover.assert_awaited_once_with(svc._brotr)

    async def test_aenter_logs_schema_discovered(self) -> None:
        svc = _TestCatalogService()
        svc._catalog = MagicMock()
        svc._catalog.discover = AsyncMock()

        table_mock = MagicMock(is_view=False)
        view_mock = MagicMock(is_view=True)
        svc._catalog.tables.values.return_value = [table_mock, table_mock, view_mock]

        await svc.__aenter__()

        svc._logger.info.assert_called_with("schema_discovered", tables=2, views=1)


class TestCatalogAccessMixinIsTableEnabled:
    """Tests for CatalogAccessMixin._is_table_enabled()."""

    def test_returns_false_when_table_not_in_config(self) -> None:
        svc = _TestCatalogService()
        svc._config.tables = {}

        assert svc._is_table_enabled("relay") is False

    def test_returns_false_when_table_disabled(self) -> None:
        svc = _TestCatalogService()
        policy = MagicMock(enabled=False)
        svc._config.tables = {"relay": policy}

        assert svc._is_table_enabled("relay") is False

    def test_returns_true_when_table_enabled(self) -> None:
        svc = _TestCatalogService()
        policy = MagicMock(enabled=True)
        svc._config.tables = {"relay": policy}

        assert svc._is_table_enabled("relay") is True

    def test_returns_false_for_unknown_table(self) -> None:
        svc = _TestCatalogService()
        policy = MagicMock(enabled=True)
        svc._config.tables = {"relay": policy}

        assert svc._is_table_enabled("nonexistent") is False
