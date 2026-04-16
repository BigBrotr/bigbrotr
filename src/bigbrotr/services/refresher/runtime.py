"""Runtime result types and metrics helpers for the refresher service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from bigbrotr.core.base_service import BaseService

    from .configs import IncrementalRefreshTarget, PeriodicRefreshTarget, RefresherConfig


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


@dataclass(frozen=True, slots=True)
class RefreshCyclePlan:
    """Computed targets and budgets for one refresher cycle."""

    cycle_start: float
    totals: RefreshCycleTotals
    incremental_targets: tuple[IncrementalRefreshTarget, ...]
    periodic_targets: tuple[PeriodicRefreshTarget, ...]


def emit_cycle_metrics(
    service: BaseService[RefresherConfig],
    result: RefreshCycleResult,
) -> None:
    """Emit cycle-level refresher metrics from the typed result object."""
    service.set_gauge("targets_attempted", result.targets_attempted)
    service.set_gauge("targets_refreshed", result.targets_refreshed)
    service.set_gauge("targets_failed", result.targets_failed)
    service.set_gauge("targets_skipped", result.targets_skipped)
    service.set_gauge("rows_refreshed", result.rows_refreshed)
    service.set_gauge("cleanup_removed_checkpoints", result.cleanup_removed_checkpoints)
    service.set_gauge(
        "watermark_event_relay_lag_seconds",
        result.watermark_event_relay_lag_seconds,
    )
    service.set_gauge(
        "watermark_relay_metadata_lag_seconds",
        result.watermark_relay_metadata_lag_seconds,
    )
    service.set_gauge(
        "cycle_stopped_due_to_max_duration",
        1 if result.cutoff_reason == "max_duration" else 0,
    )
    service.set_gauge(
        "cycle_stopped_due_to_max_targets",
        1 if result.cutoff_reason == "max_targets_per_cycle" else 0,
    )
