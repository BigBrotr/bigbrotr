"""Internal ranker service types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TypeVar

from .queries import (
    AddressableStatFact,
    EventStatFact,
    GraphSyncCheckpoint,
    IdentifierStatFact,
    RankSubjectType,
    ScoreExportRow,
)
from .runtime import (
    RankPhaseDurations,
    RankRowCounts,
    _normalize_cycle_cutoff_reason,
    _require_runtime_non_negative_int,
)


if TYPE_CHECKING:
    from collections.abc import Callable


def _require_internal_positive_int(value: object, *, field_name: str) -> int:
    """Return one canonical positive integer for internal ranker types."""
    normalized = _require_runtime_non_negative_int(value, field_name=field_name)
    if normalized == 0:
        raise ValueError(f"{field_name} must be positive")
    return normalized


@dataclass(frozen=True, slots=True)
class _GraphSyncResult:
    """Internal result of the graph sync phase."""

    checkpoint: GraphSyncCheckpoint
    changed_followers_synced: int = 0
    batches_processed: int = 0
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
            "batches_processed",
            _require_runtime_non_negative_int(
                self.batches_processed,
                field_name="batches_processed",
            ),
        )
        object.__setattr__(
            self,
            "cutoff_reason",
            _normalize_cycle_cutoff_reason(self.cutoff_reason),
        )


@dataclass(frozen=True, slots=True)
class _StageResult:
    """Internal result of the non-user fact staging phase."""

    counts: RankRowCounts
    cutoff_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "cutoff_reason",
            _normalize_cycle_cutoff_reason(self.cutoff_reason),
        )


@dataclass(frozen=True, slots=True)
class _ExportSubjectResult:
    """Internal result of staging one score subject for export."""

    rows: int = 0
    cutoff_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "rows",
            _require_runtime_non_negative_int(self.rows, field_name="rows"),
        )
        object.__setattr__(
            self,
            "cutoff_reason",
            _normalize_cycle_cutoff_reason(self.cutoff_reason),
        )


@dataclass(frozen=True, slots=True)
class _ExportResult:
    """Internal result of the snapshot export phase."""

    counts: RankRowCounts
    cutoff_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "cutoff_reason",
            _normalize_cycle_cutoff_reason(self.cutoff_reason),
        )


@dataclass(frozen=True, slots=True)
class _ExportStageSpec:
    """Internal specification for exporting one score subject type."""

    subject_type: RankSubjectType
    fetch_batch: Callable[..., list[ScoreExportRow]]


@dataclass(frozen=True, slots=True)
class _CycleBuildInput:
    """Fields needed to build the public cycle result."""

    rank_run_id: int | None
    sync_result: _GraphSyncResult
    non_user_staged: RankRowCounts = field(default_factory=RankRowCounts)
    score_counts: RankRowCounts = field(default_factory=RankRowCounts)
    cleanup_removed: int = 0
    phase_durations: RankPhaseDurations = field(default_factory=RankPhaseDurations)
    cutoff_reason: str | None = None

    def __post_init__(self) -> None:
        if self.rank_run_id is not None:
            object.__setattr__(
                self,
                "rank_run_id",
                _require_internal_positive_int(self.rank_run_id, field_name="rank_run_id"),
            )
        object.__setattr__(
            self,
            "cleanup_removed",
            _require_runtime_non_negative_int(
                self.cleanup_removed,
                field_name="cleanup_removed",
            ),
        )
        object.__setattr__(
            self,
            "cutoff_reason",
            _normalize_cycle_cutoff_reason(self.cutoff_reason),
        )


@dataclass(frozen=True, slots=True)
class _ComputeExportResult:
    """Internal result of the compute+export phase after graph sync and staging."""

    rank_run_id: int
    score_counts: RankRowCounts = field(default_factory=RankRowCounts)
    phase_durations: RankPhaseDurations = field(default_factory=RankPhaseDurations)
    cutoff_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "rank_run_id",
            _require_internal_positive_int(self.rank_run_id, field_name="rank_run_id"),
        )
        object.__setattr__(
            self,
            "cutoff_reason",
            _normalize_cycle_cutoff_reason(self.cutoff_reason),
        )


_StageFactRow = TypeVar("_StageFactRow", EventStatFact, AddressableStatFact, IdentifierStatFact)


@dataclass(frozen=True, slots=True)
class _FactStageSpec:
    """Internal specification for staging one fact stream."""

    max_rows: int | None
    budget_cutoff_reason: str
    cursor_attr: str
