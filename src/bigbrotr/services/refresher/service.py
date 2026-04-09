"""Refresher service for BigBrotr.

Periodically refreshes incremental current-state tables plus incremental
analytics tables. All derived state is maintained through SQL refresh
functions with caller-managed checkpoints; the service no longer depends on
separate materialized-view refresh phases.

**Refresh cycle order:**

1. Current-state tables (relay metadata, replaceable/addressable snapshots,
   canonical contact-list facts)
2. Analytics tables (metadata-derived, cross-tab, entity, and NIP-85 tables)
3. Periodic reconciliations:
   - ``rolling_windows``
   - ``relay_stats_metadata``
   - ``nip85_followers``
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, ClassVar

import asyncpg

from bigbrotr.core.base_service import BaseService
from bigbrotr.models.constants import ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType

from .configs import (
    RefresherConfig,
    resolve_analytics_table_order,
    resolve_current_table_order,
    validate_refresh_dependencies,
)
from .queries import (
    get_max_generated_at,
    get_max_seen_at,
    refresh_nip85_followers,
    refresh_relay_metadata,
    refresh_rolling_windows,
    refresh_summary,
)


if TYPE_CHECKING:
    from bigbrotr.core.brotr import Brotr


class Refresher(BaseService[RefresherConfig]):
    """Current-state and analytics refresh service."""

    SERVICE_NAME: ClassVar[ServiceName] = ServiceName.REFRESHER
    CONFIG_CLASS: ClassVar[type[RefresherConfig]] = RefresherConfig

    def __init__(self, brotr: Brotr, config: RefresherConfig | None = None) -> None:
        super().__init__(brotr=brotr, config=config)
        self._config: RefresherConfig
        self._config.refresh.current_tables = resolve_current_table_order(
            self._config.refresh.current_tables
        )
        self._config.refresh.analytics_tables = resolve_analytics_table_order(
            self._config.refresh.analytics_tables
        )
        validate_refresh_dependencies(
            self._config.refresh.current_tables,
            self._config.refresh.analytics_tables,
        )

    def _watermark_source(self, table: str) -> str:
        """Return the append-only source used to checkpoint one incremental table."""
        if table in {"relay_metadata_current", "relay_software_counts", "supported_nip_counts"}:
            return "relay_metadata"
        return "event_relay"

    async def cleanup(self) -> int:
        """Remove stale checkpoints for tables no longer configured."""
        configured = set(self._config.refresh.current_tables) | set(
            self._config.refresh.analytics_tables
        )
        states = await self._brotr.get_service_state(
            ServiceName.REFRESHER,
            ServiceStateType.CHECKPOINT,
        )
        stale = [s for s in states if s.state_key not in configured]
        if not stale:
            return 0

        return await self._brotr.delete_service_state(
            service_names=[s.service_name for s in stale],
            state_types=[s.state_type for s in stale],
            state_keys=[s.state_key for s in stale],
        )

    async def run(self) -> None:
        """Execute one refresh cycle."""
        current_tables = self._config.refresh.current_tables
        analytics_tables = self._config.refresh.analytics_tables
        periodic_tasks = [
            ("rolling_windows", refresh_rolling_windows),
            ("relay_stats_metadata", refresh_relay_metadata),
            ("nip85_followers", refresh_nip85_followers),
        ]

        total = len(current_tables) + len(analytics_tables) + len(periodic_tasks)
        refreshed = 0
        failed = 0

        self.set_gauge("targets_total", total)
        self.set_gauge("targets_refreshed", 0)
        self.set_gauge("targets_failed", 0)

        for table in current_tables:
            start = time.monotonic()
            try:
                rows = await self._refresh_incremental_table(table)
                refreshed += 1
                duration = time.monotonic() - start
                self.set_gauge(f"duration_{table}", duration)
                self._logger.info("current_refreshed", table=table, rows=rows, duration_s=duration)
            except (asyncpg.PostgresError, OSError) as exc:
                failed += 1
                self._logger.error("current_refresh_failed", table=table, error=str(exc))

        for table in analytics_tables:
            start = time.monotonic()
            try:
                rows = await self._refresh_incremental_table(table)
                refreshed += 1
                duration = time.monotonic() - start
                self.set_gauge(f"duration_{table}", duration)
                self._logger.info(
                    "analytics_refreshed",
                    table=table,
                    rows=rows,
                    duration_s=duration,
                )
            except (asyncpg.PostgresError, OSError) as exc:
                failed += 1
                self._logger.error("analytics_refresh_failed", table=table, error=str(exc))

        for label, func in periodic_tasks:
            start = time.monotonic()
            try:
                await func(self._brotr)
                refreshed += 1
                duration = time.monotonic() - start
                self.set_gauge(f"duration_{label}", duration)
                self._logger.info("periodic_refreshed", name=label, duration_s=duration)
            except (asyncpg.PostgresError, OSError) as exc:
                failed += 1
                self._logger.error("periodic_refresh_failed", name=label, error=str(exc))

        self.set_gauge("targets_refreshed", refreshed)
        self.set_gauge("targets_failed", failed)
        self._logger.info("refresh_completed", refreshed=refreshed, failed=failed)

    async def _refresh_incremental_table(self, table: str) -> int:
        """Incrementally refresh one current-state or analytics table."""
        states = await self._brotr.get_service_state(
            ServiceName.REFRESHER,
            ServiceStateType.CHECKPOINT,
            table,
        )
        after = int(states[0].state_value["timestamp"]) if states else 0

        source = self._watermark_source(table)
        if source == "relay_metadata":
            until = await get_max_generated_at(self._brotr, after)
        else:
            until = await get_max_seen_at(self._brotr, after)
        if until == after:
            return 0

        rows = await refresh_summary(self._brotr, table, after, until)

        await self._brotr.upsert_service_state(
            [
                ServiceState(
                    service_name=ServiceName.REFRESHER,
                    state_type=ServiceStateType.CHECKPOINT,
                    state_key=table,
                    state_value={"timestamp": until},
                )
            ]
        )

        return rows
