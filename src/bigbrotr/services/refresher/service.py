"""Refresher service for BigBrotr.

Periodically refreshes materialized views (bounded, full refresh) and
summary tables (incremental, delta-only). The incremental refresh processes
only new ``event_relay`` rows since the last checkpoint, making the refresh
cost proportional to the ingestion rate rather than the total dataset size.

**Refresh cycle order:**

1. Materialized views (``REFRESH MATERIALIZED VIEW CONCURRENTLY``)
2. Summary cross-tabs (``pubkey_kind_stats``, ``pubkey_relay_stats``,
   ``relay_kind_stats``) — must run before entity tables
3. Summary entity tables (``pubkey_stats``, ``kind_stats``, ``relay_stats``)
   — derive ``unique_*`` counts from cross-tab row counts
4. Rolling windows (``events_last_24h/7d/30d``) — periodic, scans last 30 days
5. Relay metadata (RTT, NIP-11) — periodic

See Also:
    [RefresherConfig][bigbrotr.services.refresher.RefresherConfig]:
        Configuration model for this service.
    [BaseService][bigbrotr.core.base_service.BaseService]: Abstract base
        class providing ``run()`` and ``run_forever()`` lifecycle.
"""

from __future__ import annotations

import time
from typing import ClassVar

import asyncpg

from bigbrotr.core.base_service import BaseService
from bigbrotr.models.constants import ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType

from .configs import RefresherConfig
from .queries import (
    get_max_seen_at,
    refresh_nip85_followers,
    refresh_relay_metadata,
    refresh_rolling_windows,
    refresh_summary,
)


class Refresher(BaseService[RefresherConfig]):
    """Materialized view and summary table refresh service.

    Refreshes materialized views via ``REFRESH CONCURRENTLY`` and summary
    tables via incremental stored procedures. Checkpoints are persisted in
    ``service_state`` so the service can resume after restarts.

    See Also:
        [RefresherConfig][bigbrotr.services.refresher.RefresherConfig]:
            Configuration model for this service.
    """

    SERVICE_NAME: ClassVar[ServiceName] = ServiceName.REFRESHER
    CONFIG_CLASS: ClassVar[type[RefresherConfig]] = RefresherConfig

    async def cleanup(self) -> int:
        """Remove stale checkpoints for summary tables no longer in config."""
        configured = set(self._config.refresh.summaries)
        states = await self._brotr.get_service_state(
            ServiceName.REFRESHER, ServiceStateType.CHECKPOINT
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
        matviews = self._config.refresh.matviews
        summaries = self._config.refresh.summaries
        periodic_tasks = [
            ("rolling_windows", refresh_rolling_windows),
            ("relay_stats_metadata", refresh_relay_metadata),
            ("nip85_followers", refresh_nip85_followers),
        ]
        total = len(matviews) + len(summaries) + len(periodic_tasks)
        refreshed = 0
        failed = 0

        self.set_gauge("views_total", total)
        self.set_gauge("views_refreshed", 0)
        self.set_gauge("views_failed", 0)

        # Phase 1: Materialized views (full refresh, bounded)
        for view in matviews:
            start = time.monotonic()
            try:
                await self._brotr.refresh_materialized_view(view)
                refreshed += 1
                duration = time.monotonic() - start
                self.set_gauge(f"duration_{view}", duration)
                self._logger.info("view_refreshed", view=view, duration_s=duration)
            except (asyncpg.PostgresError, OSError) as exc:
                failed += 1
                self._logger.error("view_refresh_failed", view=view, error=str(exc))

        # Phase 2: Summary tables (incremental refresh)
        for table in summaries:
            start = time.monotonic()
            try:
                rows = await self._refresh_summary(table)
                refreshed += 1
                duration = time.monotonic() - start
                self.set_gauge(f"duration_{table}", duration)
                self._logger.info("summary_refreshed", table=table, rows=rows, duration_s=duration)
            except (asyncpg.PostgresError, OSError) as exc:
                failed += 1
                self._logger.error("summary_refresh_failed", table=table, error=str(exc))

        # Phase 3: Rolling windows + relay metadata + NIP-85 followers (periodic)
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

        self.set_gauge("views_refreshed", refreshed)
        self.set_gauge("views_failed", failed)
        self._logger.info("refresh_completed", refreshed=refreshed, failed=failed)

    async def _refresh_summary(self, table: str) -> int:
        """Incremental refresh of a single summary table.

        Reads the checkpoint from ``service_state``, finds the new watermark
        from ``event_relay.seen_at``, calls the stored procedure with the
        range, and advances the checkpoint.

        Returns the number of rows affected (0 if no new data).
        """
        # Read checkpoint
        states = await self._brotr.get_service_state(
            ServiceName.REFRESHER, ServiceStateType.CHECKPOINT, table
        )
        after = int(states[0].state_value["timestamp"]) if states else 0

        # Find new watermark
        until = await get_max_seen_at(self._brotr, after)
        if until == after:
            return 0

        # Call pure SQL function with range
        rows = await refresh_summary(self._brotr, table, after, until)

        # Advance checkpoint
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
