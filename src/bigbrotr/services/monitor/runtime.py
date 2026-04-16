"""Runtime helpers for monitor cycles."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Protocol

from .queries import count_relays_to_monitor
from .utils import MonitorCyclePlan


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from bigbrotr.core.brotr import Brotr
    from bigbrotr.models.constants import NetworkType

    from .configs import MonitorConfig
    from .resources import GeoReaders

    MonitorRelayCounter = Callable[[Brotr, int, list[NetworkType]], Awaitable[int]]
    MonitorUpdateGeoDatabases = Callable[[], Awaitable[None]]
    MonitorGeoReadersOpen = Callable[..., Awaitable[None]]
    MonitorClientsDisconnect = Callable[[], Awaitable[None]]
    MonitorGeoReadersClose = Callable[[], None]


class MonitorSemaphoreBudget(Protocol):
    """Subset of the semaphore manager needed by monitor cycle planning."""

    def max_concurrency(self, networks: list[NetworkType]) -> int: ...


async def build_monitor_cycle_plan(
    *,
    brotr: Brotr,
    config: MonitorConfig,
    network_semaphores: MonitorSemaphoreBudget,
    now: int | None = None,
    count_relays_fn: MonitorRelayCounter = count_relays_to_monitor,
) -> MonitorCyclePlan | None:
    """Build the relay-selection plan for one monitor cycle."""
    networks = config.networks.get_enabled_networks()
    if not networks:
        return None

    current_time = int(time.time()) if now is None else now
    monitored_before = int(current_time - config.discovery.interval)
    max_relays = config.processing.max_relays
    total = await count_relays_fn(brotr, monitored_before, networks)
    if max_relays is not None:
        total = min(total, max_relays)

    return MonitorCyclePlan(
        networks=tuple(networks),
        monitored_before=monitored_before,
        max_relays=max_relays,
        total=total,
        max_concurrency=network_semaphores.max_concurrency(networks),
        chunk_size=config.processing.chunk_size,
    )


async def open_cycle_resources(
    *,
    config: MonitorConfig,
    geo_readers: GeoReaders,
    update_geo_databases_fn: MonitorUpdateGeoDatabases,
    open_geo_readers_fn: MonitorGeoReadersOpen | None = None,
) -> None:
    """Prepare shared resources needed for one monitor cycle."""
    await update_geo_databases_fn()

    compute = config.processing.compute
    open_geo_readers = open_geo_readers_fn or geo_readers.open
    await open_geo_readers(
        city_path=config.geo.city_database_path if compute.nip66_geo else None,
        asn_path=config.geo.asn_database_path if compute.nip66_net else None,
    )


async def close_cycle_resources(
    *,
    clients_disconnect_fn: MonitorClientsDisconnect,
    geo_readers: GeoReaders,
    close_geo_readers_fn: MonitorGeoReadersClose | None = None,
) -> None:
    """Release shared resources owned by one monitor cycle."""
    await clients_disconnect_fn()
    close_geo_readers = close_geo_readers_fn or geo_readers.close
    close_geo_readers()
