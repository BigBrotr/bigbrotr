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
from typing import TYPE_CHECKING, Any, Self, TypeVar

from bigbrotr.models.constants import NetworkType


T = TypeVar("T")
R = TypeVar("R")


if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Sequence

    import geoip2.database

    from bigbrotr.core.logger import Logger

    from .catalog import Catalog
    from .configs import NetworksConfig, TableConfig


#: Network types that support concurrent relay connections.
OPERATIONAL_NETWORKS: tuple[NetworkType, ...] = (
    NetworkType.CLEARNET,
    NetworkType.TOR,
    NetworkType.I2P,
    NetworkType.LOKI,
)


class NetworkSemaphores:
    """Per-network concurrency semaphores.

    Creates an ``asyncio.Semaphore`` for each operational
    [NetworkType][bigbrotr.models.constants.NetworkType] (clearnet, Tor,
    I2P, Lokinet) to cap the number of simultaneous connections.

    See Also:
        [NetworksConfig][bigbrotr.services.common.configs.NetworksConfig]:
            Provides ``max_tasks`` per network type.
    """

    __slots__ = ("_map",)

    def __init__(self, networks: NetworksConfig) -> None:
        self._map: dict[NetworkType, asyncio.Semaphore] = {
            nt: asyncio.Semaphore(networks.get(nt).max_tasks) for nt in OPERATIONAL_NETWORKS
        }

    def get(self, network: NetworkType) -> asyncio.Semaphore | None:
        """Look up the concurrency semaphore for a network type.

        Returns:
            The semaphore, or ``None`` for non-operational networks
            (LOCAL, UNKNOWN).
        """
        return self._map.get(network)


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
        worker: Callable[[T], Awaitable[R | None]],
    ) -> AsyncIterator[R]:
        """Launch concurrent tasks and yield non-None results as they complete.

        Each item is processed by ``worker`` in a separate
        ``asyncio.TaskGroup`` task. Results stream through an
        ``asyncio.Queue`` so the caller can update metrics progressively.

        Workers MUST catch their own ``Exception``\\s and return
        appropriate error results (or ``None`` to skip).
        ``CancelledError`` propagates naturally through the
        ``TaskGroup``.

        Args:
            items: Items to process concurrently.
            worker: Async callable receiving a single item. Returns a
                result or ``None`` to skip.

        Yields:
            Non-None results in completion order.
        """
        queue: asyncio.Queue[R | None] = asyncio.Queue()

        async def _run_worker(item: T) -> None:
            result = await worker(item)
            if result is not None:
                await queue.put(result)

        async def _run_all() -> None:
            try:
                async with asyncio.TaskGroup() as tg:
                    for item in items:
                        tg.create_task(_run_worker(item))
            except ExceptionGroup as eg:
                for exc in eg.exceptions:
                    self._logger.error(
                        "concurrent_worker_error",
                        error=str(exc),
                        error_type=type(exc).__name__,
                    )
            finally:
                await queue.put(None)

        runner = asyncio.create_task(_run_all())
        try:
            while True:
                result = await queue.get()
                if result is None:
                    break
                yield result
        finally:
            if not runner.done():
                runner.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await runner  # ensure cancellation completes


class GeoReaders:
    """GeoIP database reader container for city and ASN lookups.

    Manages the lifecycle of ``geoip2.database.Reader`` instances.
    Reader initialization is offloaded to a thread via ``open()`` to
    avoid blocking the event loop.

    Attributes:
        city: GeoLite2-City reader for geolocation lookups, or ``None``.
        asn: GeoLite2-ASN reader for network info lookups, or ``None``.

    See Also:
        [GeoReaderMixin][bigbrotr.services.common.mixins.GeoReaderMixin]:
            Mixin that exposes a ``geo_readers`` attribute of this type.
    """

    __slots__ = ("asn", "city")

    def __init__(self) -> None:
        self.city: geoip2.database.Reader | None = None
        self.asn: geoip2.database.Reader | None = None

    async def open(
        self,
        *,
        city_path: str | None = None,
        asn_path: str | None = None,
    ) -> None:
        """Open GeoIP readers from file paths via ``asyncio.to_thread``.

        Args:
            city_path: Path to GeoLite2-City database. ``None`` to skip.
            asn_path: Path to GeoLite2-ASN database. ``None`` to skip.
        """
        import geoip2.database as geoip2_db  # noqa: PLC0415  # runtime import

        if city_path:
            self.city = await asyncio.to_thread(geoip2_db.Reader, city_path)
        if asn_path:
            self.asn = await asyncio.to_thread(geoip2_db.Reader, asn_path)

    def close(self) -> None:
        """Close readers and set to ``None``. Idempotent."""
        if self.city:
            self.city.close()
            self.city = None
        if self.asn:
            self.asn.close()
            self.asn = None


class GeoReaderMixin:
    """Mixin providing GeoIP database reader lifecycle management.

    Exposes a ``geo_readers`` attribute of type
    [GeoReaders][bigbrotr.services.common.mixins.GeoReaders].

    Note:
        Call ``geo_readers.close()`` in a ``finally`` block or ``__aexit__``.

    See Also:
        [Monitor][bigbrotr.services.monitor.Monitor]: The service that
            composes this mixin for NIP-66 geo/net checks.
    """

    geo_readers: GeoReaders

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.geo_readers = GeoReaders()


class CatalogAccessMixin:
    """Mixin providing schema catalog initialization and discovery.

    Creates a [Catalog][bigbrotr.services.common.catalog.Catalog] instance
    during ``__init__`` and discovers the database schema during
    ``__aenter__``. Also provides a ``_is_table_enabled()`` helper that
    checks table access policy from the service config.

    Services must compose this mixin with
    [BaseService][bigbrotr.core.base_service.BaseService] (which provides
    ``_brotr``, ``_logger``, and ``_config``).

    See Also:
        [Api][bigbrotr.services.api.Api],
        [Dvm][bigbrotr.services.dvm.Dvm]: Services that compose this mixin.
        [Catalog][bigbrotr.services.common.catalog.Catalog]: Schema
            introspection and query execution.
    """

    _catalog: Catalog

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        from .catalog import Catalog  # noqa: PLC0415

        self._catalog = Catalog()

    async def __aenter__(self) -> Self:
        await super().__aenter__()  # type: ignore[misc]
        await self._catalog.discover(self._brotr)  # type: ignore[attr-defined]
        self._logger.info(  # type: ignore[attr-defined]
            "schema_discovered",
            tables=sum(1 for t in self._catalog.tables.values() if not t.is_view),
            views=sum(1 for t in self._catalog.tables.values() if t.is_view),
        )
        return self

    def _is_table_enabled(self, name: str) -> bool:
        """Check whether a table is enabled per access policy (default: disabled)."""
        policy: TableConfig | None = self._config.tables.get(name)  # type: ignore[attr-defined]
        if policy is None:
            return False
        return policy.enabled
