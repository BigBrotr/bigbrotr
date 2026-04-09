"""Refresher service for BigBrotr.

Periodically refreshes incremental current-state tables, incremental analytics
tables, and periodic reconciliation tasks. Target selection is fully
configuration-driven and SQL execution is constrained to the explicit registry
in [queries.py][bigbrotr.services.refresher.queries].
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

import asyncpg

from bigbrotr.core.base_service import BaseService
from bigbrotr.models.constants import ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType

from .configs import IncrementalRefreshTarget, PeriodicRefreshTarget, RefresherConfig
from .queries import (
    WatermarkSource,
    get_event_relay_watermark,
    get_incremental_target_spec,
    get_max_generated_at,
    get_max_seen_at,
    get_periodic_target_spec,
    get_relay_metadata_watermark,
    refresh_incremental_target,
    refresh_periodic_target,
)


if TYPE_CHECKING:
    from bigbrotr.core.brotr import Brotr


@dataclass(frozen=True, slots=True)
class RefreshCycleTotals:
    """Configured target totals for one cycle."""

    total: int = 0
    current: int = 0
    analytics: int = 0
    periodic: int = 0


@dataclass(frozen=True, slots=True)
class RefreshTargetResult:
    """Outcome of one configured refresher target."""

    name: str
    target_group: str
    rows: int = 0
    duration_seconds: float = 0.0
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        """Whether the target completed without an isolated target error."""
        return self.error is None


@dataclass(frozen=True, slots=True)
class RefreshCycleResult:
    """Outcome of one refresher service cycle."""

    targets_total: int = 0
    targets_current_total: int = 0
    targets_analytics_total: int = 0
    targets_periodic_total: int = 0
    targets_attempted: int = 0
    targets_refreshed: int = 0
    targets_failed: int = 0
    rows_refreshed: int = 0
    cleanup_removed_checkpoints: int = 0
    watermark_event_relay_lag_seconds: int = 0
    watermark_relay_metadata_lag_seconds: int = 0
    cutoff_reason: str | None = None
    target_results: tuple[RefreshTargetResult, ...] = ()

    @property
    def targets_skipped(self) -> int:
        """Number of configured targets not attempted because the cycle stopped early."""
        return max(0, self.targets_total - self.targets_attempted)


class Refresher(BaseService[RefresherConfig]):
    """Current-state and analytics refresh service."""

    SERVICE_NAME: ClassVar[ServiceName] = ServiceName.REFRESHER
    CONFIG_CLASS: ClassVar[type[RefresherConfig]] = RefresherConfig

    def __init__(self, brotr: Brotr, config: RefresherConfig | None = None) -> None:
        super().__init__(brotr=brotr, config=config)
        self._config: RefresherConfig
        self._last_cleanup_removed = 0

    async def cleanup(self) -> int:
        """Remove stale checkpoints for targets no longer configured."""
        if not self._config.cleanup.enabled:
            self._last_cleanup_removed = 0
            self.set_gauge("cleanup_removed_checkpoints", 0)
            return 0

        configured = {target.value for target in self._incremental_targets()}
        states = await self._brotr.get_service_state(
            ServiceName.REFRESHER,
            ServiceStateType.CHECKPOINT,
        )
        stale = [state for state in states if state.state_key not in configured]
        if not stale:
            self._last_cleanup_removed = 0
            self.set_gauge("cleanup_removed_checkpoints", 0)
            return 0

        removed = await self._brotr.delete_service_state(
            service_names=[state.service_name for state in stale],
            state_types=[state.state_type for state in stale],
            state_keys=[state.state_key for state in stale],
        )
        self._last_cleanup_removed = removed
        self.set_gauge("cleanup_removed_checkpoints", removed)
        return removed

    async def run(self) -> None:
        """Execute one refresh cycle."""
        await self.refresh()

    async def refresh(self) -> RefreshCycleResult:
        """Refresh configured targets while respecting cycle budgets."""
        cycle_start = time.monotonic()
        current_targets = self._config.current.targets
        analytics_targets = self._config.analytics.targets
        periodic_targets = self._config.periodic.enabled_targets()

        totals = RefreshCycleTotals(
            total=len(current_targets) + len(analytics_targets) + len(periodic_targets),
            current=len(current_targets),
            analytics=len(analytics_targets),
            periodic=len(periodic_targets),
        )
        self._reset_cycle_metrics(totals)

        target_results: list[RefreshTargetResult] = []
        source_checkpoints: dict[WatermarkSource, int] = {}
        cutoff_reason: str | None = None

        for target in self._incremental_targets():
            cutoff_reason = self._cycle_cutoff_reason(cycle_start, len(target_results))
            if cutoff_reason is not None:
                break

            result, source, checkpoint = await self._run_incremental_target(target)
            target_results.append(result)
            source_checkpoints[source] = max(source_checkpoints.get(source, 0), checkpoint)
            if not result.succeeded and not self._config.processing.continue_on_target_error:
                cycle_result = await self._build_cycle_result(
                    totals=totals,
                    target_results=target_results,
                    source_checkpoints=source_checkpoints,
                    cutoff_reason=None,
                )
                self._emit_cycle_metrics(cycle_result)
                raise RuntimeError(f"refresher target failed: {result.name}: {result.error}")

        if cutoff_reason is None:
            for periodic_target in periodic_targets:
                cutoff_reason = self._cycle_cutoff_reason(cycle_start, len(target_results))
                if cutoff_reason is not None:
                    break

                result = await self._run_periodic_target(periodic_target)
                target_results.append(result)
                if not result.succeeded and not self._config.processing.continue_on_target_error:
                    cycle_result = await self._build_cycle_result(
                        totals=totals,
                        target_results=target_results,
                        source_checkpoints=source_checkpoints,
                        cutoff_reason=None,
                    )
                    self._emit_cycle_metrics(cycle_result)
                    raise RuntimeError(f"refresher target failed: {result.name}: {result.error}")

        cycle_result = await self._build_cycle_result(
            totals=totals,
            target_results=target_results,
            source_checkpoints=source_checkpoints,
            cutoff_reason=cutoff_reason,
        )
        self._emit_cycle_metrics(cycle_result)
        self._logger.info(
            "refresh_completed",
            refreshed=cycle_result.targets_refreshed,
            failed=cycle_result.targets_failed,
            skipped=cycle_result.targets_skipped,
            rows=cycle_result.rows_refreshed,
            cutoff_reason=cycle_result.cutoff_reason,
        )
        return cycle_result

    def _incremental_targets(self) -> list[IncrementalRefreshTarget]:
        """Return configured incremental targets in execution order."""
        return [*self._config.current.targets, *self._config.analytics.targets]

    def _cycle_cutoff_reason(self, cycle_start: float, attempted: int) -> str | None:
        """Return the configured budget reason that should stop the cycle, if any."""
        max_targets = self._config.processing.max_targets_per_cycle
        if max_targets is not None and attempted >= max_targets:
            return "max_targets_per_cycle"

        max_duration = self._config.processing.max_duration
        if max_duration is not None and time.monotonic() - cycle_start >= max_duration:
            return "max_duration"

        return None

    async def _run_incremental_target(
        self,
        target: IncrementalRefreshTarget,
    ) -> tuple[RefreshTargetResult, WatermarkSource, int]:
        """Refresh one incremental target and return its checkpoint source."""
        spec = get_incremental_target_spec(target)
        start = time.monotonic()
        checkpoint = await self._read_checkpoint(target.value)
        until = checkpoint

        try:
            until = await self._next_watermark(spec.watermark_source, checkpoint)
            if until == checkpoint:
                rows = 0
            else:
                rows = await refresh_incremental_target(self._brotr, target, checkpoint, until)
                await self._write_checkpoint(target.value, until)

            duration = time.monotonic() - start
            self.set_gauge(f"duration_{spec.metric_key}", duration)
            self.set_gauge(f"rows_{spec.metric_key}", rows)
            self._logger.info(
                "incremental_refreshed",
                target=target.value,
                target_group=spec.target_group,
                rows=rows,
                after=checkpoint,
                until=until,
                duration_s=duration,
            )
            return (
                RefreshTargetResult(
                    name=target.value,
                    target_group=spec.target_group,
                    rows=rows,
                    duration_seconds=duration,
                ),
                spec.watermark_source,
                until,
            )
        except (asyncpg.PostgresError, OSError) as exc:
            duration = time.monotonic() - start
            self.set_gauge(f"duration_{spec.metric_key}", duration)
            self._logger.error(
                "incremental_refresh_failed",
                target=target.value,
                target_group=spec.target_group,
                error=str(exc),
                duration_s=duration,
            )
            return (
                RefreshTargetResult(
                    name=target.value,
                    target_group=spec.target_group,
                    duration_seconds=duration,
                    error=str(exc),
                ),
                spec.watermark_source,
                until,
            )

    async def _run_periodic_target(self, target: PeriodicRefreshTarget) -> RefreshTargetResult:
        """Run one periodic reconciliation task."""
        spec = get_periodic_target_spec(target)
        start = time.monotonic()
        try:
            await refresh_periodic_target(self._brotr, target)
            duration = time.monotonic() - start
            self.set_gauge(f"duration_{spec.metric_key}", duration)
            self._logger.info("periodic_refreshed", target=target.value, duration_s=duration)
            return RefreshTargetResult(
                name=target.value,
                target_group="periodic",
                duration_seconds=duration,
            )
        except (asyncpg.PostgresError, OSError) as exc:
            duration = time.monotonic() - start
            self.set_gauge(f"duration_{spec.metric_key}", duration)
            self._logger.error(
                "periodic_refresh_failed",
                target=target.value,
                error=str(exc),
                duration_s=duration,
            )
            return RefreshTargetResult(
                name=target.value,
                target_group="periodic",
                duration_seconds=duration,
                error=str(exc),
            )

    async def _build_cycle_result(
        self,
        *,
        totals: RefreshCycleTotals,
        target_results: list[RefreshTargetResult],
        source_checkpoints: dict[WatermarkSource, int],
        cutoff_reason: str | None,
    ) -> RefreshCycleResult:
        """Build a typed cycle result and compute watermark lag metrics."""
        event_lag, metadata_lag = await self._watermark_lags(source_checkpoints)
        refreshed = sum(1 for result in target_results if result.succeeded)
        failed = sum(1 for result in target_results if not result.succeeded)
        rows_refreshed = sum(result.rows for result in target_results)

        return RefreshCycleResult(
            targets_total=totals.total,
            targets_current_total=totals.current,
            targets_analytics_total=totals.analytics,
            targets_periodic_total=totals.periodic,
            targets_attempted=len(target_results),
            targets_refreshed=refreshed,
            targets_failed=failed,
            rows_refreshed=rows_refreshed,
            cleanup_removed_checkpoints=self._last_cleanup_removed,
            watermark_event_relay_lag_seconds=event_lag,
            watermark_relay_metadata_lag_seconds=metadata_lag,
            cutoff_reason=cutoff_reason,
            target_results=tuple(target_results),
        )

    async def _watermark_lags(
        self, source_checkpoints: dict[WatermarkSource, int]
    ) -> tuple[int, int]:
        """Return event and metadata source lag in seconds relative to saved checkpoints."""
        event_lag = 0
        if WatermarkSource.EVENT_RELAY in source_checkpoints:
            event_lag = max(
                0,
                await get_event_relay_watermark(self._brotr)
                - source_checkpoints[WatermarkSource.EVENT_RELAY],
            )

        metadata_lag = 0
        if WatermarkSource.RELAY_METADATA in source_checkpoints:
            metadata_lag = max(
                0,
                await get_relay_metadata_watermark(self._brotr)
                - source_checkpoints[WatermarkSource.RELAY_METADATA],
            )

        return event_lag, metadata_lag

    async def _next_watermark(self, source: WatermarkSource, after: int) -> int:
        """Return the next checkpoint watermark for one source."""
        if source == WatermarkSource.RELAY_METADATA:
            return await get_max_generated_at(self._brotr, after)
        return await get_max_seen_at(self._brotr, after)

    async def _read_checkpoint(self, target: str) -> int:
        """Read the stored checkpoint for one incremental target."""
        states = await self._brotr.get_service_state(
            ServiceName.REFRESHER,
            ServiceStateType.CHECKPOINT,
            target,
        )
        return int(states[0].state_value["timestamp"]) if states else 0

    async def _write_checkpoint(self, target: str, timestamp: int) -> None:
        """Persist the checkpoint for one successfully refreshed target."""
        await self._brotr.upsert_service_state(
            [
                ServiceState(
                    service_name=ServiceName.REFRESHER,
                    state_type=ServiceStateType.CHECKPOINT,
                    state_key=target,
                    state_value={"timestamp": timestamp},
                )
            ]
        )

    def _reset_cycle_metrics(self, totals: RefreshCycleTotals) -> None:
        """Reset point-in-time gauges at the beginning of a cycle."""
        self.set_gauge("targets_total", totals.total)
        self.set_gauge("targets_current_total", totals.current)
        self.set_gauge("targets_analytics_total", totals.analytics)
        self.set_gauge("targets_periodic_total", totals.periodic)
        self.set_gauge("targets_attempted", 0)
        self.set_gauge("targets_refreshed", 0)
        self.set_gauge("targets_failed", 0)
        self.set_gauge("targets_skipped", 0)
        self.set_gauge("rows_refreshed", 0)
        self.set_gauge("cycle_stopped_due_to_max_duration", 0)
        self.set_gauge("cycle_stopped_due_to_max_targets", 0)

    def _emit_cycle_metrics(self, result: RefreshCycleResult) -> None:
        """Emit cycle-level metrics from the typed result object."""
        self.set_gauge("targets_attempted", result.targets_attempted)
        self.set_gauge("targets_refreshed", result.targets_refreshed)
        self.set_gauge("targets_failed", result.targets_failed)
        self.set_gauge("targets_skipped", result.targets_skipped)
        self.set_gauge("rows_refreshed", result.rows_refreshed)
        self.set_gauge("cleanup_removed_checkpoints", result.cleanup_removed_checkpoints)
        self.set_gauge(
            "watermark_event_relay_lag_seconds",
            result.watermark_event_relay_lag_seconds,
        )
        self.set_gauge(
            "watermark_relay_metadata_lag_seconds",
            result.watermark_relay_metadata_lag_seconds,
        )
        self.set_gauge(
            "cycle_stopped_due_to_max_duration",
            1 if result.cutoff_reason == "max_duration" else 0,
        )
        self.set_gauge(
            "cycle_stopped_due_to_max_targets",
            1 if result.cutoff_reason == "max_targets_per_cycle" else 0,
        )
