"""Runtime types and helpers for ranker service cycles."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .queries import GraphSyncCheckpoint


if TYPE_CHECKING:
    from bigbrotr.core.base_service import BaseService
    from bigbrotr.services.ranker.configs import RankerConfig


_RESET_GAUGES: tuple[str, ...] = (
    "sync_batches_processed",
    "changed_followers_synced",
    "facts_stage_event_rows",
    "facts_stage_addressable_rows",
    "facts_stage_identifier_rows",
    "export_pubkey_rows",
    "export_event_rows",
    "export_addressable_rows",
    "export_identifier_rows",
    "phase_duration_cleanup_seconds",
    "phase_duration_sync_seconds",
    "phase_duration_facts_stage_seconds",
    "phase_duration_compute_seconds",
    "phase_duration_export_seconds",
    "checkpoint_lag_seconds",
    "rank_runs_failed_total",
    "duckdb_file_size_bytes",
    "graph_nodes",
    "graph_edges",
    "cycle_cutoff_sync_budget",
    "cycle_cutoff_stage_budget",
    "cycle_cutoff_export_budget",
    "cycle_cutoff_duration_budget",
    "cleanup_removed_rank_runs",
)


@dataclass(frozen=True, slots=True)
class RankRowCounts:
    """Number of rows staged or exported per NIP-85 rank subject type."""

    pubkey: int = 0
    event: int = 0
    addressable: int = 0
    identifier: int = 0

    @property
    def non_user(self) -> int:
        return self.event + self.addressable + self.identifier


@dataclass(frozen=True, slots=True)
class RankPhaseDurations:
    """Duration of each major ranker cycle phase."""

    cleanup_seconds: float = 0.0
    sync_seconds: float = 0.0
    facts_stage_seconds: float = 0.0
    compute_seconds: float = 0.0
    export_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class RankCycleResult:
    """Outcome of one ranker service cycle."""

    rank_run_id: int | None
    changed_followers_synced: int = 0
    sync_batches_processed: int = 0
    graph_nodes: int = 0
    graph_edges: int = 0
    non_user_staged: RankRowCounts = field(default_factory=RankRowCounts)
    rank_counts: RankRowCounts = field(default_factory=RankRowCounts)
    checkpoint: GraphSyncCheckpoint = field(default_factory=GraphSyncCheckpoint)
    checkpoint_lag_seconds: int = 0
    duckdb_file_size_bytes: int = 0
    rank_runs_failed_total: int = 0
    cleanup_removed_rank_runs: int = 0
    phase_durations: RankPhaseDurations = field(default_factory=RankPhaseDurations)
    cutoff_reason: str | None = None


def cycle_cutoff_reason(*, cycle_start: float, max_duration: float | None) -> str | None:
    """Return whether the whole-cycle duration budget has been reached."""
    if max_duration is not None and time.monotonic() - cycle_start >= max_duration:
        return "max_duration"
    return None


def sync_cutoff_reason(  # noqa: PLR0913
    *,
    cycle_start: float,
    batches_processed: int,
    followers_synced: int,
    max_duration: float | None,
    max_batches: int | None,
    max_followers_per_cycle: int | None,
) -> str | None:
    """Return the sync budget that should stop the graph-sync phase, if any."""
    if cutoff_reason := cycle_cutoff_reason(
        cycle_start=cycle_start,
        max_duration=max_duration,
    ):
        return cutoff_reason

    if max_batches is not None and batches_processed >= max_batches:
        return "sync_max_batches"

    if max_followers_per_cycle is not None and followers_synced >= max_followers_per_cycle:
        return "sync_max_followers_per_cycle"

    return None


def next_limited_batch_size(
    *,
    batch_size: int,
    rows_processed: int,
    max_rows: int | None,
) -> int:
    """Return the next fetch size after applying an optional row budget."""
    if max_rows is None:
        return batch_size
    return max(0, min(batch_size, max_rows - rows_processed))


def reset_cycle_metrics(service: BaseService[RankerConfig]) -> None:
    """Reset point-in-time gauges at the beginning of a ranker cycle."""
    for gauge_name in _RESET_GAUGES:
        service.set_gauge(gauge_name, 0)


def emit_cycle_metrics(
    service: BaseService[RankerConfig],
    result: RankCycleResult,
) -> None:
    """Emit cycle-level metrics from the typed result object."""
    service.set_gauge("sync_batches_processed", result.sync_batches_processed)
    service.set_gauge("changed_followers_synced", result.changed_followers_synced)
    service.set_gauge("graph_nodes", result.graph_nodes)
    service.set_gauge("graph_edges", result.graph_edges)
    service.set_gauge("facts_stage_event_rows", result.non_user_staged.event)
    service.set_gauge("facts_stage_addressable_rows", result.non_user_staged.addressable)
    service.set_gauge("facts_stage_identifier_rows", result.non_user_staged.identifier)
    service.set_gauge("export_pubkey_rows", result.rank_counts.pubkey)
    service.set_gauge("export_event_rows", result.rank_counts.event)
    service.set_gauge("export_addressable_rows", result.rank_counts.addressable)
    service.set_gauge("export_identifier_rows", result.rank_counts.identifier)
    service.set_gauge("pubkey_ranks_written", result.rank_counts.pubkey)
    service.set_gauge("non_user_ranks_written", result.rank_counts.non_user)
    service.set_gauge("phase_duration_cleanup_seconds", result.phase_durations.cleanup_seconds)
    service.set_gauge("phase_duration_sync_seconds", result.phase_durations.sync_seconds)
    service.set_gauge(
        "phase_duration_facts_stage_seconds",
        result.phase_durations.facts_stage_seconds,
    )
    service.set_gauge("phase_duration_compute_seconds", result.phase_durations.compute_seconds)
    service.set_gauge("phase_duration_export_seconds", result.phase_durations.export_seconds)
    service.set_gauge("checkpoint_lag_seconds", result.checkpoint_lag_seconds)
    service.set_gauge("rank_runs_failed_total", result.rank_runs_failed_total)
    service.set_gauge("duckdb_file_size_bytes", result.duckdb_file_size_bytes)
    service.set_gauge("cleanup_removed_rank_runs", result.cleanup_removed_rank_runs)

    cutoff_reason = result.cutoff_reason or ""
    service.set_gauge("cycle_cutoff_sync_budget", 1 if cutoff_reason.startswith("sync_") else 0)
    service.set_gauge(
        "cycle_cutoff_stage_budget",
        1 if cutoff_reason.startswith("facts_stage_") else 0,
    )
    service.set_gauge(
        "cycle_cutoff_export_budget",
        1 if cutoff_reason.startswith("export_") else 0,
    )
    service.set_gauge("cycle_cutoff_duration_budget", 1 if cutoff_reason == "max_duration" else 0)
