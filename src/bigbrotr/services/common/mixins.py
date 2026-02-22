"""Reusable service mixins for BigBrotr.

All service extensions live here as mixin classes. Each mixin uses
cooperative multiple inheritance (``super().__init__(**kwargs)``) so
that initialization is handled automatically via the MRO — no
explicit ``_init_*()`` calls are needed in service constructors.

See Also:
    [BaseService][bigbrotr.core.base_service.BaseService]: The base class
        that mixin classes are composed with via multiple inheritance.
    [NetworkConfig][bigbrotr.services.common.configs.NetworkConfig]:
        Provides ``max_tasks`` values consumed by
        [NetworkSemaphoresMixin][bigbrotr.services.common.mixins.NetworkSemaphoresMixin].
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from bigbrotr.models.constants import NetworkType


if TYPE_CHECKING:
    import geoip2.database

    from .configs import NetworkConfig


# ---------------------------------------------------------------------------
# Chunk Progress
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ChunkProgress:
    """Tracks progress of a chunk-based processing cycle.

    All counters are reset at the start of each cycle via ``reset()``.
    Use ``record_chunk()`` after processing each chunk to update counters.

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
            Mixin that exposes a ``progress`` attribute of this type.
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

    def record_chunk(self, succeeded: int, failed: int) -> None:
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
    a ``progress`` attribute with counters and timing. Initialization
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
                self.progress.reset()
                ...
                self.progress.record_chunk(succeeded=len(ok), failed=len(err))
        ```
    """

    progress: ChunkProgress

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.progress = ChunkProgress()


# ---------------------------------------------------------------------------
# Network Semaphore
# ---------------------------------------------------------------------------

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
        [NetworkConfig][bigbrotr.services.common.configs.NetworkConfig]:
            Provides ``max_tasks`` per network type.
    """

    __slots__ = ("_map",)

    def __init__(self, networks: NetworkConfig) -> None:
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

    Exposes a ``semaphores`` attribute of type
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

    semaphores: NetworkSemaphores

    def __init__(self, **kwargs: Any) -> None:
        networks: NetworkConfig = kwargs.pop("networks")
        super().__init__(**kwargs)
        self.semaphores = NetworkSemaphores(networks)


# ---------------------------------------------------------------------------
# GeoIP Reader
# ---------------------------------------------------------------------------


class GeoReaderMixin:
    """Mixin providing GeoIP database reader lifecycle management.

    Manages opening and closing of ``geoip2.database.Reader`` instances
    for city (geolocation) and ASN (network info) lookups. Reader
    initialization is offloaded to a thread to avoid blocking the event loop.

    Note:
        Call ``close_geo_readers()`` in a ``finally`` block or ``__aexit__``.

    See Also:
        [Monitor][bigbrotr.services.monitor.Monitor]: The service that
            composes this mixin for NIP-66 geo/net checks.
    """

    city_reader: geoip2.database.Reader | None
    asn_reader: geoip2.database.Reader | None

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.city_reader = None
        self.asn_reader = None

    async def open_geo_readers(
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
            self.city_reader = await asyncio.to_thread(geoip2_db.Reader, city_path)
        if asn_path:
            self.asn_reader = await asyncio.to_thread(geoip2_db.Reader, asn_path)

    def close_geo_readers(self) -> None:
        """Close readers and set to ``None``. Idempotent."""
        if self.city_reader:
            self.city_reader.close()
            self.city_reader = None
        if self.asn_reader:
            self.asn_reader.close()
            self.asn_reader = None
