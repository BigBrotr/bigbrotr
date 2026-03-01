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
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Self

from bigbrotr.models.constants import NetworkType


if TYPE_CHECKING:
    import geoip2.database

    from .catalog import Catalog
    from .configs import NetworksConfig, TableConfig


@dataclass(slots=True)
class ChunkProgress:
    """Tracks progress of a chunk-based processing cycle.

    All counters are reset at the start of each cycle via ``reset()``.
    Use ``record()`` after processing each chunk to update counters.

    Attributes:
        started_at: Timestamp when the cycle started (``time.time()``).
        total: Total items to process in this cycle.
        processed: Items processed so far.
        succeeded: Items that succeeded.
        failed: Items that failed.
        chunks: Number of chunks completed.

    Note:
        ``started_at`` uses ``time.time()`` for Unix timestamps (used in
        SQL comparisons), while ``elapsed`` uses ``time.monotonic()`` for
        accurate duration measurement unaffected by clock adjustments.

    See Also:
        [ChunkProgressMixin][bigbrotr.services.common.mixins.ChunkProgressMixin]:
            Mixin that exposes a ``chunk_progress`` attribute of this type.
    """

    started_at: float = field(default=0.0)
    _monotonic_start: float = field(default=0.0, repr=False)
    total: int = field(default=0)
    processed: int = field(default=0)
    succeeded: int = field(default=0)
    failed: int = field(default=0)
    chunks: int = field(default=0)

    def reset(self) -> None:
        """Reset all counters and set ``started_at`` to the current time."""
        self.started_at = time.time()
        self._monotonic_start = time.monotonic()
        self.total = 0
        self.processed = 0
        self.succeeded = 0
        self.failed = 0
        self.chunks = 0

    def record(self, succeeded: int, failed: int) -> None:
        """Record the results of one processed chunk.

        Args:
            succeeded: Number of items that succeeded in this chunk.
            failed: Number of items that failed in this chunk.
        """
        self.processed += succeeded + failed
        self.succeeded += succeeded
        self.failed += failed
        self.chunks += 1

    @property
    def remaining(self) -> int:
        """Number of items left to process."""
        return self.total - self.processed

    @property
    def elapsed(self) -> float:
        """Seconds elapsed since processing started, rounded to 1 decimal."""
        return round(time.monotonic() - self._monotonic_start, 1)


class ChunkProgressMixin:
    """Mixin providing chunk-based processing progress tracking.

    Services that process items in chunks compose this mixin to get
    a ``chunk_progress`` attribute with counters and timing. Initialization
    is automatic via ``__init__``.

    See Also:
        [ChunkProgress][bigbrotr.services.common.mixins.ChunkProgress]:
            The dataclass this mixin manages.
        [Validator][bigbrotr.services.validator.Validator],
        [Monitor][bigbrotr.services.monitor.Monitor]: Services that
            compose this mixin.

    Examples:
        ```python
        class MyService(ChunkProgressMixin, BaseService[MyConfig]):
            async def run(self):
                self.chunk_progress.reset()
                ...
                self.chunk_progress.record(succeeded=len(ok), failed=len(err))
        ```
    """

    chunk_progress: ChunkProgress

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.chunk_progress = ChunkProgress()

    def _emit_progress_gauges(self) -> None:
        """Emit Prometheus gauges for batch progress."""
        self.set_gauge("total", self.chunk_progress.total)  # type: ignore[attr-defined]
        self.set_gauge("processed", self.chunk_progress.processed)  # type: ignore[attr-defined]
        self.set_gauge("success", self.chunk_progress.succeeded)  # type: ignore[attr-defined]
        self.set_gauge("failure", self.chunk_progress.failed)  # type: ignore[attr-defined]


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
