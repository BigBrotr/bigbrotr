"""Unit tests for services.common.mixins module.

Tests:
- NetworkSemaphores - Per-network concurrency semaphore container
- NetworkSemaphoresMixin - Mixin that provides a network_semaphores attribute via __init__
- CatalogAccessMixin - Mixin for schema catalog lifecycle and table access policy
"""

import asyncio
from typing import Self
from unittest.mock import AsyncMock, MagicMock

from bigbrotr.models.constants import NetworkType
from bigbrotr.services.common.catalog import Catalog
from bigbrotr.services.common.mixins import (
    CatalogAccessMixin,
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
