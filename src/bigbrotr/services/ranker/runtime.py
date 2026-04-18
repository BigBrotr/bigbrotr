"""Runtime types and helpers for ranker service cycles."""

from __future__ import annotations

import math
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
    "pubkey_scores_written",
    "non_user_scores_written",
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

_VALID_CUTOFF_REASONS: frozenset[str] = frozenset(
    {
        "max_duration",
        "sync_max_batches",
        "sync_max_followers_per_cycle",
        "facts_stage_event_rows",
        "facts_stage_addressable_rows",
        "facts_stage_identifier_rows",
        "export_pubkey_max_batches",
        "export_event_max_batches",
        "export_addressable_max_batches",
        "export_identifier_max_batches",
    }
)


def _require_runtime_non_negative_int(value: object, *, field_name: str) -> int:
    """Return one canonical non-negative runtime integer value."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an int")
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return value


def _require_runtime_non_negative_float(value: object, *, field_name: str) -> float:
    """Return one canonical non-negative finite runtime float value."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a float")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    if normalized < 0.0:
        raise ValueError(f"{field_name} must be non-negative")
    return normalized


def _normalize_cycle_cutoff_reason(value: object) -> str | None:
    """Return one canonical runtime cutoff reason."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("cutoff_reason must be a str")
    if value not in _VALID_CUTOFF_REASONS:
        allowed = ", ".join(sorted(_VALID_CUTOFF_REASONS))
        raise ValueError(f"cutoff_reason must be one of: {allowed}")
    return value


@dataclass(frozen=True, slots=True)
class RankRowCounts:
    """Number of rows staged or score-exported per NIP-85 subject type."""

    pubkey: int = 0
    event: int = 0
    addressable: int = 0
    identifier: int = 0

    def __post_init__(self) -> None:
        for field_name in ("pubkey", "event", "addressable", "identifier"):
            object.__setattr__(
                self,
                field_name,
                _require_runtime_non_negative_int(
                    getattr(self, field_name),
                    field_name=field_name,
                ),
            )

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

    def __post_init__(self) -> None:
        for field_name in (
            "cleanup_seconds",
            "sync_seconds",
            "facts_stage_seconds",
            "compute_seconds",
            "export_seconds",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_runtime_non_negative_float(
                    getattr(self, field_name),
                    field_name=field_name,
                ),
            )


@dataclass(frozen=True, slots=True)
class RankCycleResult:
    """Outcome of one ranker service cycle."""

    changed_followers_synced: int = 0
    sync_batches_processed: int = 0
    graph_nodes: int = 0
    graph_edges: int = 0
    non_user_staged: RankRowCounts = field(default_factory=RankRowCounts)
    score_counts: RankRowCounts = field(default_factory=RankRowCounts)
    checkpoint: GraphSyncCheckpoint = field(default_factory=GraphSyncCheckpoint)
    checkpoint_lag_seconds: int = 0
    duckdb_file_size_bytes: int = 0
    phase_durations: RankPhaseDurations = field(default_factory=RankPhaseDurations)
    cutoff_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "changed_followers_synced",
            _require_runtime_non_negative_int(
                self.changed_followers_synced,
                field_name="changed_followers_synced",
            ),
        )
        object.__setattr__(
            self,
            "sync_batches_processed",
            _require_runtime_non_negative_int(
                self.sync_batches_processed,
                field_name="sync_batches_processed",
            ),
        )
        object.__setattr__(
            self,
            "graph_nodes",
            _require_runtime_non_negative_int(self.graph_nodes, field_name="graph_nodes"),
        )
        object.__setattr__(
            self,
            "graph_edges",
            _require_runtime_non_negative_int(self.graph_edges, field_name="graph_edges"),
        )
        object.__setattr__(
            self,
            "checkpoint_lag_seconds",
            _require_runtime_non_negative_int(
                self.checkpoint_lag_seconds,
                field_name="checkpoint_lag_seconds",
            ),
        )
        object.__setattr__(
            self,
            "duckdb_file_size_bytes",
            _require_runtime_non_negative_int(
                self.duckdb_file_size_bytes,
                field_name="duckdb_file_size_bytes",
            ),
        )
        object.__setattr__(
            self,
            "cutoff_reason",
            _normalize_cycle_cutoff_reason(self.cutoff_reason),
        )


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
    *,
    failed_runs_total: int = 0,
    cleanup_removed_runs: int = 0,
) -> None:
    """Emit cycle-level metrics from the public result plus private housekeeping."""
    failed_runs_total = _require_runtime_non_negative_int(
        failed_runs_total,
        field_name="failed_runs_total",
    )
    cleanup_removed_runs = _require_runtime_non_negative_int(
        cleanup_removed_runs,
        field_name="cleanup_removed_runs",
    )

    service.set_gauge("sync_batches_processed", result.sync_batches_processed)
    service.set_gauge("changed_followers_synced", result.changed_followers_synced)
    service.set_gauge("graph_nodes", result.graph_nodes)
    service.set_gauge("graph_edges", result.graph_edges)
    service.set_gauge("facts_stage_event_rows", result.non_user_staged.event)
    service.set_gauge("facts_stage_addressable_rows", result.non_user_staged.addressable)
    service.set_gauge("facts_stage_identifier_rows", result.non_user_staged.identifier)
    service.set_gauge("export_pubkey_rows", result.score_counts.pubkey)
    service.set_gauge("export_event_rows", result.score_counts.event)
    service.set_gauge("export_addressable_rows", result.score_counts.addressable)
    service.set_gauge("export_identifier_rows", result.score_counts.identifier)
    service.set_gauge("pubkey_scores_written", result.score_counts.pubkey)
    service.set_gauge("non_user_scores_written", result.score_counts.non_user)
    service.set_gauge("phase_duration_cleanup_seconds", result.phase_durations.cleanup_seconds)
    service.set_gauge("phase_duration_sync_seconds", result.phase_durations.sync_seconds)
    service.set_gauge(
        "phase_duration_facts_stage_seconds",
        result.phase_durations.facts_stage_seconds,
    )
    service.set_gauge("phase_duration_compute_seconds", result.phase_durations.compute_seconds)
    service.set_gauge("phase_duration_export_seconds", result.phase_durations.export_seconds)
    service.set_gauge("checkpoint_lag_seconds", result.checkpoint_lag_seconds)
    service.set_gauge("rank_runs_failed_total", failed_runs_total)
    service.set_gauge("duckdb_file_size_bytes", result.duckdb_file_size_bytes)
    service.set_gauge("cleanup_removed_rank_runs", cleanup_removed_runs)

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
