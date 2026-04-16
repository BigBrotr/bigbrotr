"""Internal ranker service types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TypeVar

from .queries import (
    AddressableStatFact,
    EventStatFact,
    GraphSyncCheckpoint,
    IdentifierStatFact,
    RankExportRow,
    RankSubjectType,
)
from .runtime import RankPhaseDurations, RankRowCounts


if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True, slots=True)
class _GraphSyncResult:
    """Internal result of the graph sync phase."""

    checkpoint: GraphSyncCheckpoint
    changed_followers_synced: int = 0
    batches_processed: int = 0
    cutoff_reason: str | None = None


@dataclass(frozen=True, slots=True)
class _StageResult:
    """Internal result of the non-user fact staging phase."""

    counts: RankRowCounts
    cutoff_reason: str | None = None


@dataclass(frozen=True, slots=True)
class _ExportSubjectResult:
    """Internal result of staging one rank subject for export."""

    rows: int = 0
    cutoff_reason: str | None = None


@dataclass(frozen=True, slots=True)
class _ExportResult:
    """Internal result of the snapshot export phase."""

    counts: RankRowCounts
    cutoff_reason: str | None = None


@dataclass(frozen=True, slots=True)
class _ExportStageSpec:
    """Internal specification for exporting one rank subject type."""

    subject_type: RankSubjectType
    fetch_batch: Callable[..., list[RankExportRow]]


@dataclass(frozen=True, slots=True)
class _CycleBuildInput:
    """Fields needed to build the public cycle result."""

    rank_run_id: int | None
    sync_result: _GraphSyncResult
    non_user_staged: RankRowCounts = field(default_factory=RankRowCounts)
    rank_counts: RankRowCounts = field(default_factory=RankRowCounts)
    cleanup_removed: int = 0
    phase_durations: RankPhaseDurations = field(default_factory=RankPhaseDurations)
    cutoff_reason: str | None = None


@dataclass(frozen=True, slots=True)
class _ComputeExportResult:
    """Internal result of the compute+export phase after graph sync and staging."""

    rank_run_id: int
    rank_counts: RankRowCounts = field(default_factory=RankRowCounts)
    phase_durations: RankPhaseDurations = field(default_factory=RankPhaseDurations)
    cutoff_reason: str | None = None


_StageFactRow = TypeVar("_StageFactRow", EventStatFact, AddressableStatFact, IdentifierStatFact)


@dataclass(frozen=True, slots=True)
class _FactStageSpec:
    """Internal specification for staging one fact stream."""

    max_rows: int | None
    budget_cutoff_reason: str
    cursor_attr: str
