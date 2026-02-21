"""Reusable service mixins for BigBrotr.

All service extensions live here as mixin classes.  Future extensions
follow the same pattern: a mixin class with an ``_init_*()`` method
for lazy initialization.

See Also:
    [BaseService][bigbrotr.core.base_service.BaseService]: The base class
        that mixin classes are composed with via multiple inheritance.
    [NetworkConfig][bigbrotr.services.common.configs.NetworkConfig]:
        Provides ``max_tasks`` values consumed by
        [NetworkSemaphoreMixin][bigbrotr.services.common.mixins.NetworkSemaphoreMixin].
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar

from bigbrotr.models.constants import NetworkType, ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType
from bigbrotr.utils.transport import broadcast_events as transport_broadcast_events


if TYPE_CHECKING:
    import geoip2.database
    from nostr_sdk import EventBuilder, Keys

    from bigbrotr.core.brotr import Brotr
    from bigbrotr.core.logger import Logger
    from bigbrotr.models import Relay

    from .configs import NetworkConfig


# ---------------------------------------------------------------------------
# Batch Progress
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class BatchProgress:
    """Tracks progress of a batch processing cycle.

    All counters are reset at the start of each cycle via ``reset()``.
    Used internally by
    [BatchProgressMixin][bigbrotr.services.common.mixins.BatchProgressMixin]
    to provide ``_progress`` to services.

    Attributes:
        started_at: Timestamp when the cycle started (``time.time()``).
        total: Total items to process.
        processed: Items processed so far.
        success: Items that succeeded.
        failure: Items that failed.
        chunks: Number of chunks completed.

    Note:
        ``started_at`` uses ``time.time()`` for Unix timestamps (used in
        SQL comparisons), while ``elapsed`` uses ``time.monotonic()`` for
        accurate duration measurement unaffected by clock adjustments.

    See Also:
        [BatchProgressMixin][bigbrotr.services.common.mixins.BatchProgressMixin]:
            Mixin that exposes a ``_progress`` attribute of this type.
    """

    started_at: float = field(default=0.0)
    _monotonic_start: float = field(default=0.0, repr=False)
    total: int = field(default=0)
    processed: int = field(default=0)
    success: int = field(default=0)
    failure: int = field(default=0)
    chunks: int = field(default=0)

    def reset(self) -> None:
        """Reset all counters and set ``started_at`` to the current time."""
        self.started_at = time.time()
        self._monotonic_start = time.monotonic()
        self.total = 0
        self.processed = 0
        self.success = 0
        self.failure = 0
        self.chunks = 0

    @property
    def remaining(self) -> int:
        """Number of items left to process."""
        return self.total - self.processed

    @property
    def elapsed(self) -> float:
        """Seconds elapsed since processing started, rounded to 1 decimal."""
        return round(time.monotonic() - self._monotonic_start, 1)


class BatchProgressMixin:
    """Mixin providing batch processing progress tracking.

    Services that process items in batches compose this mixin to get
    a ``_progress`` attribute with counters and timing.

    Note:
        Call ``_init_progress()`` in ``__init__`` and ``_progress.reset()``
        at the start of each ``run()`` cycle to reset all counters.

    See Also:
        [BatchProgress][bigbrotr.services.common.mixins.BatchProgress]:
            The dataclass this mixin manages.
        [Validator][bigbrotr.services.validator.Validator],
        [Monitor][bigbrotr.services.monitor.Monitor]: Services that
            compose this mixin.

    Examples:
        ```python
        class MyService(BatchProgressMixin, BaseService[MyConfig]):
            def __init__(self, brotr, config):
                super().__init__(brotr=brotr, config=config)
                self._init_progress()

            async def run(self):
                self._progress.reset()
                ...
        ```
    """

    _progress: BatchProgress

    # Declared for mypy -- provided by BaseService at runtime
    def set_gauge(self, name: str, value: float) -> None: ...

    def _init_progress(self) -> None:
        """Initialize a fresh BatchProgress tracker."""
        self._progress = BatchProgress()

    def emit_progress_metrics(self) -> None:
        """Emit standard Prometheus gauges for batch progress."""
        self.set_gauge("total", self._progress.total)
        self.set_gauge("processed", self._progress.processed)
        self.set_gauge("success", self._progress.success)
        self.set_gauge("failure", self._progress.failure)


# ---------------------------------------------------------------------------
# Network Semaphore
# ---------------------------------------------------------------------------


class NetworkSemaphoreMixin:
    """Mixin providing per-network concurrency semaphores.

    Creates an ``asyncio.Semaphore`` for each
    [NetworkType][bigbrotr.models.constants.NetworkType] (clearnet, Tor,
    I2P, Lokinet) to cap the number of simultaneous connections.  This is
    especially important for overlay networks like Tor, where excessive
    concurrency degrades circuit performance.

    Call ``_init_semaphores()`` at the start of each ``run()`` cycle to pick up
    any configuration changes to ``max_tasks`` values.

    See Also:
        [NetworkConfig][bigbrotr.services.common.configs.NetworkConfig]:
            Provides ``max_tasks`` per network type.
        [Validator][bigbrotr.services.validator.Validator],
        [Monitor][bigbrotr.services.monitor.Monitor]: Services that
            compose this mixin for bounded concurrency.
    """

    _semaphores: dict[NetworkType, asyncio.Semaphore]

    def _init_semaphores(self, networks: NetworkConfig) -> None:
        """Create a semaphore for each network type from the configuration.

        Args:
            networks: [NetworkConfig][bigbrotr.services.common.configs.NetworkConfig]
                providing ``max_tasks`` per network type.
        """
        self._semaphores = {
            network: asyncio.Semaphore(networks.get(network).max_tasks)
            for network in (
                NetworkType.CLEARNET,
                NetworkType.TOR,
                NetworkType.I2P,
                NetworkType.LOKI,
            )
        }

    def _get_semaphore(self, network: NetworkType) -> asyncio.Semaphore | None:
        """Look up the concurrency semaphore for a network type.

        Args:
            network: The [NetworkType][bigbrotr.models.constants.NetworkType]
                to retrieve the semaphore for.

        Returns:
            The semaphore, or ``None`` if the network has not been initialized.
        """
        return self._semaphores.get(network)


# ---------------------------------------------------------------------------
# GeoIP Reader
# ---------------------------------------------------------------------------


class GeoReaderMixin:
    """Mixin providing GeoIP database reader lifecycle management.

    Manages opening and closing of ``geoip2.database.Reader`` instances
    for city (geolocation) and ASN (network info) lookups. Reader
    initialization is offloaded to a thread to avoid blocking the event loop.

    Note:
        Call ``_init_geo_readers()`` in ``__init__`` and
        ``close_geo_readers()`` in a ``finally`` block or ``__aexit__``.

    See Also:
        [Monitor][bigbrotr.services.monitor.Monitor]: The service that
            composes this mixin for NIP-66 geo/net checks.
    """

    _geo_reader: geoip2.database.Reader | None
    _asn_reader: geoip2.database.Reader | None

    def _init_geo_readers(self) -> None:
        """Set both readers to None. Call in ``__init__``."""
        self._geo_reader = None
        self._asn_reader = None

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
            self._geo_reader = await asyncio.to_thread(geoip2_db.Reader, city_path)
        if asn_path:
            self._asn_reader = await asyncio.to_thread(geoip2_db.Reader, asn_path)

    def close_geo_readers(self) -> None:
        """Close readers and set to ``None``. Idempotent."""
        if self._geo_reader:
            self._geo_reader.close()
            self._geo_reader = None
        if self._asn_reader:
            self._asn_reader.close()
            self._asn_reader = None


# ---------------------------------------------------------------------------
# Nostr Publisher
# ---------------------------------------------------------------------------


class NostrPublisherMixin:
    """Mixin encapsulating Nostr event signing, broadcasting, and interval-gated publishing.

    Provides ``broadcast_events()`` for direct broadcasting and
    ``publish_if_due()`` for interval-gated publishing with checkpoint
    persistence. Uses ``broadcast_events`` from ``transport.py`` internally.

    Note:
        The consumer must set ``self._keys`` in ``__init__`` to a valid
        ``nostr_sdk.Keys`` instance.

    See Also:
        [Monitor][bigbrotr.services.monitor.Monitor]: The service that
            composes this mixin for Kind 0, 10166, and 30166 publishing.
        [broadcast_events][bigbrotr.utils.transport.broadcast_events]:
            The transport function wrapped by this mixin.
    """

    # Declared for mypy -- provided by BaseService at runtime
    _brotr: Brotr
    _logger: Logger
    SERVICE_NAME: ClassVar[ServiceName]

    # Own attribute -- set by consumer in __init__
    _keys: Keys

    async def broadcast_events(
        self,
        builders: list[EventBuilder],
        relays: list[Relay],
        *,
        timeout: float = 30.0,  # noqa: ASYNC109
        allow_insecure: bool = True,
    ) -> int:
        """Sign and broadcast events, returning count of successful relays.

        Wraps [broadcast_events][bigbrotr.utils.transport.broadcast_events]
        with ``self._keys``.
        """
        return await transport_broadcast_events(
            builders,
            relays,
            self._keys,
            timeout=timeout,
            allow_insecure=allow_insecure,
        )

    async def publish_if_due(  # noqa: PLR0913
        self,
        *,
        enabled: bool,
        relays: list[Relay],
        interval: int,
        state_key: str,
        builder: EventBuilder,
        event_name: str,
        timeout: float = 30.0,  # noqa: ASYNC109
    ) -> None:
        """Publish an event if enabled, relays configured, and interval elapsed.

        Checks the last publish timestamp from service_state checkpoints.
        After a successful broadcast, saves the new timestamp.
        """
        if not enabled or not relays:
            return

        results = await self._brotr.get_service_state(
            self.SERVICE_NAME,
            ServiceStateType.CHECKPOINT,
            state_key,
        )
        last_ts = results[0].state_value.get("timestamp", 0.0) if results else 0.0
        if time.time() - last_ts < interval:
            return

        sent = await self.broadcast_events([builder], relays, timeout=timeout)
        if not sent:
            self._logger.warning(f"{event_name}_failed", error="no relays reachable")
            return

        self._logger.info(f"{event_name}_published", relays=sent)
        now = time.time()
        await self._brotr.upsert_service_state([
            ServiceState(
                service_name=self.SERVICE_NAME,
                state_type=ServiceStateType.CHECKPOINT,
                state_key=state_key,
                state_value={"timestamp": now},
                updated_at=int(now),
            ),
        ])
