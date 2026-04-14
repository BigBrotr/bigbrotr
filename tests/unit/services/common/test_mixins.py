"""Unit tests for services.common.mixins module.

Tests:
- ConcurrentStreamMixin - Concurrent item processing with streaming results
- NetworkSemaphores - Per-network concurrency semaphore container
- NetworkSemaphoresMixin - Mixin that provides a network_semaphores attribute via __init__
- CatalogAccessMixin - Mixin for schema catalog lifecycle and table access policy
"""

import asyncio
from typing import Self
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bigbrotr.models.constants import NetworkType
from bigbrotr.services.common.catalog import Catalog
from bigbrotr.services.common.mixins import (
    CatalogAccessMixin,
    Clients,
    ConcurrentStreamMixin,
    GeoReaders,
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
        svc._config.read_models = {}

        assert svc._is_table_enabled("relay") is False

    def test_returns_false_when_table_disabled(self) -> None:
        svc = _TestCatalogService()
        policy = MagicMock(enabled=False)
        svc._config.read_models = {"relay": policy}

        assert svc._is_table_enabled("relay") is False

    def test_returns_true_when_table_enabled(self) -> None:
        svc = _TestCatalogService()
        policy = MagicMock(enabled=True)
        svc._config.read_models = {"relay": policy}

        assert svc._is_table_enabled("relay") is True

    def test_returns_false_for_unknown_table(self) -> None:
        svc = _TestCatalogService()
        policy = MagicMock(enabled=True)
        svc._config.read_models = {"relay": policy}

        assert svc._is_table_enabled("nonexistent") is False

    def test_returns_false_for_non_public_table_even_when_enabled(self) -> None:
        svc = _TestCatalogService()
        policy = MagicMock(enabled=True)
        svc._config.read_models = {"service_state": policy}

        assert svc._is_table_enabled("service_state") is False


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


# =============================================================================
# GeoReaders Tests (lines 222-234)
# =============================================================================


class TestGeoReadersOpen:
    async def test_open_city_reader(self) -> None:
        readers = GeoReaders()
        mock_reader = MagicMock()

        with patch(
            "bigbrotr.services.common.mixins.asyncio.to_thread",
            new_callable=AsyncMock,
            return_value=mock_reader,
        ) as mock_to_thread:
            await readers.open(city_path="/data/city.mmdb")

        mock_to_thread.assert_awaited_once()
        assert readers.city is mock_reader
        assert readers.asn is None

    async def test_open_asn_reader(self) -> None:
        readers = GeoReaders()
        mock_reader = MagicMock()

        with patch(
            "bigbrotr.services.common.mixins.asyncio.to_thread",
            new_callable=AsyncMock,
            return_value=mock_reader,
        ) as mock_to_thread:
            await readers.open(asn_path="/data/asn.mmdb")

        mock_to_thread.assert_awaited_once()
        assert readers.asn is mock_reader
        assert readers.city is None

    async def test_open_both_readers(self) -> None:
        readers = GeoReaders()
        mock_city = MagicMock()
        mock_asn = MagicMock()

        with patch(
            "bigbrotr.services.common.mixins.asyncio.to_thread",
            new_callable=AsyncMock,
            side_effect=[mock_city, mock_asn],
        ):
            await readers.open(city_path="/data/city.mmdb", asn_path="/data/asn.mmdb")

        assert readers.city is mock_city
        assert readers.asn is mock_asn

    async def test_open_no_paths_does_nothing(self) -> None:
        readers = GeoReaders()

        with patch(
            "bigbrotr.services.common.mixins.asyncio.to_thread",
            new_callable=AsyncMock,
        ) as mock_to_thread:
            await readers.open()

        mock_to_thread.assert_not_awaited()
        assert readers.city is None
        assert readers.asn is None


class TestGeoReadersClose:
    def test_close_both_readers(self) -> None:
        readers = GeoReaders()
        readers.city = MagicMock()
        readers.asn = MagicMock()
        city_ref = readers.city
        asn_ref = readers.asn

        readers.close()

        city_ref.close.assert_called_once()
        asn_ref.close.assert_called_once()
        assert readers.city is None
        assert readers.asn is None

    def test_close_city_only(self) -> None:
        readers = GeoReaders()
        readers.city = MagicMock()
        city_ref = readers.city

        readers.close()

        city_ref.close.assert_called_once()
        assert readers.city is None
        assert readers.asn is None

    def test_close_asn_only(self) -> None:
        readers = GeoReaders()
        readers.asn = MagicMock()
        asn_ref = readers.asn

        readers.close()

        asn_ref.close.assert_called_once()
        assert readers.asn is None

    def test_close_no_readers_is_idempotent(self) -> None:
        readers = GeoReaders()
        readers.close()
        assert readers.city is None
        assert readers.asn is None


# =============================================================================
# Clients Tests (lines 309-359)
# =============================================================================


def _make_clients(*, allow_insecure: bool = False) -> Clients:
    mock_keys = MagicMock()
    mock_networks = MagicMock()
    net_cfg = MagicMock()
    net_cfg.timeout = 10.0
    mock_networks.get.return_value = net_cfg
    mock_networks.get_proxy_url.return_value = None
    return Clients(mock_keys, mock_networks, allow_insecure=allow_insecure)


def _make_relay(url: str = "wss://relay.example.com", network: str = "clearnet") -> MagicMock:
    relay = MagicMock()
    relay.url = url
    relay.network = network
    return relay


class TestClientsGet:
    async def test_get_connects_and_caches(self) -> None:
        clients = _make_clients()
        relay = _make_relay()
        mock_client = MagicMock()

        with patch(
            "bigbrotr.utils.protocol.connect_relay",
            new_callable=AsyncMock,
            return_value=mock_client,
        ):
            result = await clients.get(relay)
            assert result is mock_client

            result2 = await clients.get(relay)
            assert result2 is mock_client

    async def test_get_returns_none_on_connection_failure(self) -> None:
        clients = _make_clients()
        relay = _make_relay()

        with patch(
            "bigbrotr.utils.protocol.connect_relay",
            new_callable=AsyncMock,
            side_effect=OSError("connection refused"),
        ):
            result = await clients.get(relay)
            assert result is None

    async def test_get_returns_none_for_previously_failed_relay(self) -> None:
        clients = _make_clients()
        relay = _make_relay()

        with patch(
            "bigbrotr.utils.protocol.connect_relay",
            new_callable=AsyncMock,
            side_effect=TimeoutError("timed out"),
        ):
            await clients.get(relay)

        result = await clients.get(relay)
        assert result is None

    async def test_get_uses_proxy_url_and_timeout(self) -> None:
        clients = _make_clients(allow_insecure=True)
        relay = _make_relay()
        clients._networks.get_proxy_url.return_value = "socks5://tor:9050"

        with patch(
            "bigbrotr.utils.protocol.connect_relay",
            new_callable=AsyncMock,
            return_value=MagicMock(),
        ) as mock_connect:
            await clients.get(relay)

        mock_connect.assert_awaited_once_with(
            relay,
            keys=clients._keys,
            proxy_url="socks5://tor:9050",
            timeout=10.0,
            allow_insecure=True,
        )


class TestClientsGetMany:
    async def test_get_many_returns_connected_clients(self) -> None:
        clients = _make_clients()
        r1 = _make_relay("wss://r1.example.com")
        r2 = _make_relay("wss://r2.example.com")
        mock_c1 = MagicMock()
        mock_c2 = MagicMock()

        with patch(
            "bigbrotr.utils.protocol.connect_relay",
            new_callable=AsyncMock,
            side_effect=[mock_c1, mock_c2],
        ):
            result = await clients.get_many([r1, r2])

        assert result == [mock_c1, mock_c2]

    async def test_get_many_filters_failed_connections(self) -> None:
        clients = _make_clients()
        r1 = _make_relay("wss://r1.example.com")
        r2 = _make_relay("wss://r2.example.com")
        mock_c1 = MagicMock()

        with patch(
            "bigbrotr.utils.protocol.connect_relay",
            new_callable=AsyncMock,
            side_effect=[mock_c1, OSError("fail")],
        ):
            result = await clients.get_many([r1, r2])

        assert result == [mock_c1]

    async def test_get_many_empty_list(self) -> None:
        clients = _make_clients()
        result = await clients.get_many([])
        assert result == []


class TestClientsDisconnect:
    async def test_disconnect_shuts_down_all_clients(self) -> None:
        clients = _make_clients()
        r1 = _make_relay("wss://r1.example.com")
        r2 = _make_relay("wss://r2.example.com")
        mock_c1 = AsyncMock()
        mock_c2 = AsyncMock()

        with patch(
            "bigbrotr.utils.protocol.connect_relay",
            new_callable=AsyncMock,
            side_effect=[mock_c1, mock_c2],
        ):
            await clients.get(r1)
            await clients.get(r2)

        await clients.disconnect()

        mock_c1.shutdown.assert_awaited_once()
        mock_c2.shutdown.assert_awaited_once()
        assert clients._clients == {}
        assert clients._failed == set()

    async def test_disconnect_handles_shutdown_errors(self) -> None:
        clients = _make_clients()
        relay = _make_relay()
        mock_client = AsyncMock()
        mock_client.shutdown.side_effect = RuntimeError("shutdown failed")

        with patch(
            "bigbrotr.utils.protocol.connect_relay",
            new_callable=AsyncMock,
            return_value=mock_client,
        ):
            await clients.get(relay)

        await clients.disconnect()

        assert clients._clients == {}

    async def test_disconnect_clears_failed_set(self) -> None:
        clients = _make_clients()
        relay = _make_relay()

        with patch(
            "bigbrotr.utils.protocol.connect_relay",
            new_callable=AsyncMock,
            side_effect=OSError("fail"),
        ):
            await clients.get(relay)

        assert len(clients._failed) == 1
        await clients.disconnect()
        assert clients._failed == set()
