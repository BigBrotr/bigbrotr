"""Ranker service for BigBrotr."""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING, ClassVar, TypeVar

import duckdb

from bigbrotr.core.base_service import BaseService
from bigbrotr.models.constants import ServiceName

from .configs import RankerConfig
from .queries import (
    AddressableStatFact,
    EventStatFact,
    GraphSyncCheckpoint,
    IdentifierStatFact,
    RankExportRow,
    RankSubjectType,
    create_rank_stages,
    fetch_addressable_stats,
    fetch_changed_contact_lists,
    fetch_event_stats,
    fetch_follow_edges_for_followers,
    fetch_identifier_stats,
    get_contact_list_source_watermark,
    insert_rank_stage_batch,
    merge_rank_stage,
)
from .utils import RankerStore


_StoreResult = TypeVar("_StoreResult")


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from types import TracebackType

    import asyncpg

    from bigbrotr.core.brotr import Brotr


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


class Ranker(BaseService[RankerConfig]):
    """Private DuckDB-backed ranker for the NIP-85 ranking pipeline."""

    SERVICE_NAME: ClassVar[ServiceName] = ServiceName.RANKER
    CONFIG_CLASS: ClassVar[type[RankerConfig]] = RankerConfig

    def __init__(self, brotr: Brotr, config: RankerConfig | None = None) -> None:
        super().__init__(brotr=brotr, config=config)
        self._config: RankerConfig
        self._store = RankerStore(
            db_path=self._config.storage.path,
            checkpoint_path=self._config.storage.checkpoint_path,
        )
        self._store_executor: ThreadPoolExecutor | None = None

    async def __aenter__(self) -> Ranker:
        await super().__aenter__()
        try:
            await self._run_store(self._store.ensure_initialized)
        except (duckdb.Error, OSError, RuntimeError):
            executor = self._store_executor
            self._store_executor = None
            if executor is not None:
                await asyncio.to_thread(executor.shutdown, wait=True)
            raise
        self._logger.info(
            "duckdb_store_ready",
            algorithm_id=self._config.algorithm_id,
            path=str(self._config.storage.path),
            legacy_checkpoint_path=str(self._config.storage.checkpoint_path),
        )
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: TracebackType | None,
    ) -> None:
        executor = self._store_executor
        self._store_executor = None
        if executor is not None:
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(executor, self._store.close)
            finally:
                await asyncio.to_thread(executor.shutdown, wait=True)
        await super().__aexit__(_exc_type, _exc_val, _exc_tb)

    def _get_store_executor(self) -> ThreadPoolExecutor:
        executor = self._store_executor
        if executor is None:
            executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ranker-store")
            self._store_executor = executor
        return executor

    async def _run_store(
        self,
        func: Callable[..., _StoreResult],
        *args: object,
        **kwargs: object,
    ) -> _StoreResult:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._get_store_executor(),
            partial(func, *args, **kwargs),
        )

    async def cleanup(self) -> int:
        """Remove old DuckDB-local rank run records beyond retention."""
        removed = await self._run_store(
            self._store.delete_rank_runs_older_than_retention,
            self._config.cleanup.rank_runs_retention,
        )
        self.set_gauge("cleanup_removed_rank_runs", removed)
        return removed

    async def run(self) -> None:
        """Sync facts, compute 30382/30383/30384/30385 ranks, and export them."""
        await self.rank()

    async def rank(self) -> RankCycleResult:
        """Sync facts, compute 30382/30383/30384/30385 ranks, and export them."""
        cycle_start = time.monotonic()
        await self._run_store(self._store.ensure_initialized)
        self._reset_cycle_metrics()
        cycle_input = await self._run_rank_cycle_phases(cycle_start)
        result = await self._build_cycle_result(cycle_input)

        if cycle_input.cutoff_reason is None and cycle_input.rank_run_id is not None:
            self._logger.info(
                "ranker_cycle_completed",
                algorithm_id=self._config.algorithm_id,
                run_id=cycle_input.rank_run_id,
                graph_nodes=result.graph_nodes,
                graph_edges=result.graph_edges,
                changed_followers_synced=result.changed_followers_synced,
                sync_batches_processed=result.sync_batches_processed,
                event_stats_staged=result.non_user_staged.event,
                addressable_stats_staged=result.non_user_staged.addressable,
                identifier_stats_staged=result.non_user_staged.identifier,
                pubkey_ranks_written=result.rank_counts.pubkey,
                event_ranks_written=result.rank_counts.event,
                addressable_ranks_written=result.rank_counts.addressable,
                identifier_ranks_written=result.rank_counts.identifier,
                non_user_ranks_written=result.rank_counts.non_user,
                checkpoint_seen_at=result.checkpoint.source_seen_at,
                checkpoint_follower_pubkey=result.checkpoint.follower_pubkey,
                checkpoint_lag_seconds=result.checkpoint_lag_seconds,
                duckdb_file_size_bytes=result.duckdb_file_size_bytes,
            )
        return result

    async def _run_rank_cycle_phases(self, cycle_start: float) -> _CycleBuildInput:
        """Run the mutable phases of one ranker cycle and return typed build input."""
        cleanup_removed = 0
        cleanup_duration = 0.0

        sync_start = time.monotonic()
        sync_result = await self._sync_follow_graph(cycle_start)
        sync_duration = time.monotonic() - sync_start

        phase_durations = RankPhaseDurations(
            cleanup_seconds=cleanup_duration,
            sync_seconds=sync_duration,
        )
        if sync_result.cutoff_reason is not None:
            return _CycleBuildInput(
                rank_run_id=None,
                sync_result=sync_result,
                cleanup_removed=cleanup_removed,
                phase_durations=phase_durations,
                cutoff_reason=sync_result.cutoff_reason,
            )

        facts_start = time.monotonic()
        stage_result = await self._sync_non_user_stats_stage(cycle_start)
        facts_duration = time.monotonic() - facts_start
        phase_durations = RankPhaseDurations(
            cleanup_seconds=cleanup_duration,
            sync_seconds=sync_duration,
            facts_stage_seconds=facts_duration,
        )
        if stage_result.cutoff_reason is not None:
            return _CycleBuildInput(
                rank_run_id=None,
                sync_result=sync_result,
                non_user_staged=stage_result.counts,
                cleanup_removed=cleanup_removed,
                phase_durations=phase_durations,
                cutoff_reason=stage_result.cutoff_reason,
            )

        if cutoff_reason := self._cycle_cutoff_reason(cycle_start):
            return _CycleBuildInput(
                rank_run_id=None,
                sync_result=sync_result,
                non_user_staged=stage_result.counts,
                cleanup_removed=cleanup_removed,
                phase_durations=phase_durations,
                cutoff_reason=cutoff_reason,
            )

        compute_export_result = await self._compute_and_export_ranks(
            cycle_start=cycle_start,
            phase_durations=RankPhaseDurations(
                cleanup_seconds=cleanup_duration,
                sync_seconds=sync_duration,
                facts_stage_seconds=facts_duration,
            ),
        )
        if compute_export_result.cutoff_reason is not None:
            return _CycleBuildInput(
                rank_run_id=compute_export_result.rank_run_id,
                sync_result=sync_result,
                non_user_staged=stage_result.counts,
                cleanup_removed=cleanup_removed,
                phase_durations=compute_export_result.phase_durations,
                cutoff_reason=compute_export_result.cutoff_reason,
            )

        return _CycleBuildInput(
            rank_run_id=compute_export_result.rank_run_id,
            sync_result=sync_result,
            non_user_staged=stage_result.counts,
            rank_counts=compute_export_result.rank_counts,
            cleanup_removed=cleanup_removed,
            phase_durations=compute_export_result.phase_durations,
        )

    async def _compute_and_export_ranks(
        self,
        *,
        cycle_start: float,
        phase_durations: RankPhaseDurations,
    ) -> _ComputeExportResult:
        """Compute private ranks and export public snapshots for one cycle."""
        compute_start = time.monotonic()
        graph_stats = await self._run_store(
            self._store.get_graph_stats_for_ranking,
            ignore_self_follows=self._config.graph.ignore_self_follows,
        )

        rank_run = await self._run_store(
            self._store.start_rank_run,
            algorithm_id=self._config.algorithm_id,
            node_count=graph_stats.node_count,
            edge_count=graph_stats.edge_count,
        )

        try:
            await self._run_store(
                self._store.compute_pubkey_pagerank,
                damping=self._config.graph.damping,
                iterations=self._config.graph.iterations,
                ignore_self_follows=self._config.graph.ignore_self_follows,
            )
            await self._run_store(self._store.compute_non_user_ranks)
            compute_duration = time.monotonic() - compute_start
            compute_phase_durations = RankPhaseDurations(
                cleanup_seconds=phase_durations.cleanup_seconds,
                sync_seconds=phase_durations.sync_seconds,
                facts_stage_seconds=phase_durations.facts_stage_seconds,
                compute_seconds=compute_duration,
            )

            if cutoff_reason := self._cycle_cutoff_reason(cycle_start):
                await self._run_store(
                    self._store.finish_rank_run,
                    rank_run.run_id,
                    status="cutoff",
                )
                return _ComputeExportResult(
                    rank_run_id=rank_run.run_id,
                    phase_durations=compute_phase_durations,
                    cutoff_reason=cutoff_reason,
                )

            export_start = time.monotonic()
            export_result = await self._export_rank_snapshots(
                cycle_start=cycle_start,
                computed_at=int(time.time()),
            )
            export_duration = time.monotonic() - export_start
            full_phase_durations = RankPhaseDurations(
                cleanup_seconds=compute_phase_durations.cleanup_seconds,
                sync_seconds=compute_phase_durations.sync_seconds,
                facts_stage_seconds=compute_phase_durations.facts_stage_seconds,
                compute_seconds=compute_phase_durations.compute_seconds,
                export_seconds=export_duration,
            )
            if export_result.cutoff_reason is not None:
                await self._run_store(
                    self._store.finish_rank_run,
                    rank_run.run_id,
                    status="cutoff",
                )
                return _ComputeExportResult(
                    rank_run_id=rank_run.run_id,
                    phase_durations=full_phase_durations,
                    cutoff_reason=export_result.cutoff_reason,
                )

            await self._run_store(
                self._store.finish_rank_run,
                rank_run.run_id,
                status="success",
            )
            return _ComputeExportResult(
                rank_run_id=rank_run.run_id,
                rank_counts=export_result.counts,
                phase_durations=full_phase_durations,
            )
        except Exception:
            await self._run_store(
                self._store.finish_rank_run,
                rank_run.run_id,
                status="failed",
            )
            failed_total = await self._run_store(self._store.count_rank_runs, status="failed")
            self.set_gauge("rank_runs_failed_total", failed_total)
            raise

    async def _build_cycle_result(
        self,
        data: _CycleBuildInput,
    ) -> RankCycleResult:
        """Build a typed cycle result and emit the matching gauges."""
        graph_stats = await self._run_store(
            self._store.get_graph_stats_for_ranking,
            ignore_self_follows=self._config.graph.ignore_self_follows,
        )
        source_watermark = await get_contact_list_source_watermark(self._brotr)
        duckdb_file_size = await self._run_store(self._store.duckdb_file_size_bytes)
        failed_total = await self._run_store(self._store.count_rank_runs, status="failed")

        result = RankCycleResult(
            rank_run_id=data.rank_run_id,
            changed_followers_synced=data.sync_result.changed_followers_synced,
            sync_batches_processed=data.sync_result.batches_processed,
            graph_nodes=graph_stats.node_count,
            graph_edges=graph_stats.edge_count,
            non_user_staged=data.non_user_staged,
            rank_counts=data.rank_counts,
            checkpoint=data.sync_result.checkpoint,
            checkpoint_lag_seconds=max(
                0,
                source_watermark - data.sync_result.checkpoint.source_seen_at,
            ),
            duckdb_file_size_bytes=duckdb_file_size,
            rank_runs_failed_total=failed_total,
            cleanup_removed_rank_runs=data.cleanup_removed,
            phase_durations=data.phase_durations,
            cutoff_reason=data.cutoff_reason,
        )
        self._emit_cycle_metrics(result)

        if data.cutoff_reason is not None:
            self._logger.info(
                "ranker_cycle_cutoff",
                algorithm_id=self._config.algorithm_id,
                cutoff_reason=data.cutoff_reason,
                changed_followers_synced=result.changed_followers_synced,
                sync_batches_processed=result.sync_batches_processed,
                event_stats_staged=result.non_user_staged.event,
                addressable_stats_staged=result.non_user_staged.addressable,
                identifier_stats_staged=result.non_user_staged.identifier,
                checkpoint_seen_at=result.checkpoint.source_seen_at,
                checkpoint_follower_pubkey=result.checkpoint.follower_pubkey,
            )

        return result

    async def _sync_follow_graph(self, cycle_start: float) -> _GraphSyncResult:
        """Sync changed contact lists into DuckDB while respecting cycle budgets."""
        checkpoint = await self._run_store(self._store.load_checkpoint)
        changed_followers_synced = 0
        batches_processed = 0

        while True:
            cutoff_reason = self._sync_cutoff_reason(
                cycle_start,
                batches_processed,
                changed_followers_synced,
            )
            if cutoff_reason is not None:
                return _GraphSyncResult(
                    checkpoint=checkpoint,
                    changed_followers_synced=changed_followers_synced,
                    batches_processed=batches_processed,
                    cutoff_reason=cutoff_reason,
                )

            limit = self._next_limited_batch_size(
                self._config.sync.batch_size,
                changed_followers_synced,
                self._config.sync.max_followers_per_cycle,
            )
            if limit == 0:
                return _GraphSyncResult(
                    checkpoint=checkpoint,
                    changed_followers_synced=changed_followers_synced,
                    batches_processed=batches_processed,
                    cutoff_reason="sync_max_followers_per_cycle",
                )

            changed_lists = await fetch_changed_contact_lists(self._brotr, checkpoint, limit)
            if not changed_lists:
                return _GraphSyncResult(
                    checkpoint=checkpoint,
                    changed_followers_synced=changed_followers_synced,
                    batches_processed=batches_processed,
                )

            follower_pubkeys = [fact.follower_pubkey for fact in changed_lists]
            edges = await fetch_follow_edges_for_followers(self._brotr, follower_pubkeys)
            checkpoint = GraphSyncCheckpoint(
                source_seen_at=changed_lists[-1].source_seen_at,
                follower_pubkey=changed_lists[-1].follower_pubkey,
            )

            await self._run_store(
                self._store.apply_follow_graph_delta,
                changed_lists,
                edges,
                checkpoint,
            )
            changed_followers_synced += len(changed_lists)
            batches_processed += 1

            self._logger.info(
                "graph_sync_batch_applied",
                algorithm_id=self._config.algorithm_id,
                changed_followers=len(changed_lists),
                current_edges=len(edges),
                checkpoint_seen_at=checkpoint.source_seen_at,
                checkpoint_follower_pubkey=checkpoint.follower_pubkey,
            )

            if len(changed_lists) < limit:
                return _GraphSyncResult(
                    checkpoint=checkpoint,
                    changed_followers_synced=changed_followers_synced,
                    batches_processed=batches_processed,
                )

    async def _sync_non_user_stats_stage(self, cycle_start: float) -> _StageResult:
        """Reload non-user fact stages from PostgreSQL into private DuckDB."""
        await self._run_store(self._store.clear_non_user_stats_stage)

        event_rows_staged, cutoff_reason = await self._stage_event_stats(cycle_start)
        if cutoff_reason is not None:
            return _StageResult(
                counts=RankRowCounts(event=event_rows_staged),
                cutoff_reason=cutoff_reason,
            )

        addressable_rows_staged, cutoff_reason = await self._stage_addressable_stats(cycle_start)
        if cutoff_reason is not None:
            return _StageResult(
                counts=RankRowCounts(event=event_rows_staged, addressable=addressable_rows_staged),
                cutoff_reason=cutoff_reason,
            )

        identifier_rows_staged, cutoff_reason = await self._stage_identifier_stats(cycle_start)
        return _StageResult(
            counts=RankRowCounts(
                event=event_rows_staged,
                addressable=addressable_rows_staged,
                identifier=identifier_rows_staged,
            ),
            cutoff_reason=cutoff_reason,
        )

    async def _stage_event_stats(self, cycle_start: float) -> tuple[int, str | None]:
        """Stage event facts from PostgreSQL into DuckDB with a row budget."""
        return await self._stage_fact_rows(
            cycle_start=cycle_start,
            spec=_FactStageSpec(
                max_rows=self._config.facts_stage.max_event_rows,
                budget_cutoff_reason="facts_stage_event_rows",
                cursor_attr="event_id",
            ),
            fetch_rows=fetch_event_stats,
            append_stage_batch=self._store.append_event_stats_stage_batch,
        )

    async def _stage_addressable_stats(self, cycle_start: float) -> tuple[int, str | None]:
        """Stage addressable facts from PostgreSQL into DuckDB with a row budget."""
        return await self._stage_fact_rows(
            cycle_start=cycle_start,
            spec=_FactStageSpec(
                max_rows=self._config.facts_stage.max_addressable_rows,
                budget_cutoff_reason="facts_stage_addressable_rows",
                cursor_attr="event_address",
            ),
            fetch_rows=fetch_addressable_stats,
            append_stage_batch=self._store.append_addressable_stats_stage_batch,
        )

    async def _stage_identifier_stats(self, cycle_start: float) -> tuple[int, str | None]:
        """Stage identifier facts from PostgreSQL into DuckDB with a row budget."""
        return await self._stage_fact_rows(
            cycle_start=cycle_start,
            spec=_FactStageSpec(
                max_rows=self._config.facts_stage.max_identifier_rows,
                budget_cutoff_reason="facts_stage_identifier_rows",
                cursor_attr="identifier",
            ),
            fetch_rows=fetch_identifier_stats,
            append_stage_batch=self._store.append_identifier_stats_stage_batch,
        )

    async def _stage_fact_rows(
        self,
        *,
        cycle_start: float,
        spec: _FactStageSpec,
        fetch_rows: Callable[[Brotr, str, int], Awaitable[list[_StageFactRow]]],
        append_stage_batch: Callable[[list[_StageFactRow]], None],
    ) -> tuple[int, str | None]:
        """Stage one non-user fact stream from PostgreSQL into DuckDB."""
        rows_staged = 0
        after_cursor = ""
        while True:
            if cutoff_reason := self._cycle_cutoff_reason(cycle_start):
                return rows_staged, cutoff_reason
            limit = self._next_limited_batch_size(
                self._config.facts_stage.batch_size,
                rows_staged,
                spec.max_rows,
            )
            if limit == 0:
                probe_rows = await fetch_rows(self._brotr, after_cursor, 1)
                return rows_staged, spec.budget_cutoff_reason if probe_rows else None
            rows = await fetch_rows(self._brotr, after_cursor, limit)
            if not rows:
                return rows_staged, None

            await self._run_store(append_stage_batch, rows)
            rows_staged += len(rows)
            after_cursor = str(getattr(rows[-1], spec.cursor_attr))

            if len(rows) < limit:
                return rows_staged, None

    async def _export_rank_snapshots(
        self,
        *,
        cycle_start: float,
        computed_at: int,
    ) -> _ExportResult:
        """Snapshot-export all final NIP-85 rank tables into PostgreSQL."""
        async with self._brotr.transaction() as conn:
            await create_rank_stages(conn)

            counts = RankRowCounts()
            specs = self._export_stage_specs()
            for spec in specs:
                subject_result = await self._populate_rank_stage(
                    conn,
                    subject_type=spec.subject_type,
                    fetch_batch=spec.fetch_batch,
                    cycle_start=cycle_start,
                    computed_at=computed_at,
                )
                if subject_result.cutoff_reason is not None:
                    return _ExportResult(counts, subject_result.cutoff_reason)
                counts = self._with_subject_count(
                    counts,
                    spec.subject_type,
                    subject_result.rows,
                )

            for spec in specs:
                await merge_rank_stage(conn, spec.subject_type, self._config.algorithm_id)

        return _ExportResult(counts)

    def _export_stage_specs(self) -> tuple[_ExportStageSpec, ...]:
        """Return the deterministic export order for public rank snapshots."""
        return (
            _ExportStageSpec("pubkey", self._store.fetch_pubkey_rank_batch),
            _ExportStageSpec("event", self._store.fetch_event_rank_batch),
            _ExportStageSpec("addressable", self._store.fetch_addressable_rank_batch),
            _ExportStageSpec("identifier", self._store.fetch_identifier_rank_batch),
        )

    @staticmethod
    def _with_subject_count(
        counts: RankRowCounts,
        subject_type: RankSubjectType,
        rows: int,
    ) -> RankRowCounts:
        """Return updated rank row counts after exporting one subject stage."""
        if subject_type == "pubkey":
            return RankRowCounts(
                pubkey=rows,
                event=counts.event,
                addressable=counts.addressable,
                identifier=counts.identifier,
            )
        if subject_type == "event":
            return RankRowCounts(
                pubkey=counts.pubkey,
                event=rows,
                addressable=counts.addressable,
                identifier=counts.identifier,
            )
        if subject_type == "addressable":
            return RankRowCounts(
                pubkey=counts.pubkey,
                event=counts.event,
                addressable=rows,
                identifier=counts.identifier,
            )
        return RankRowCounts(
            pubkey=counts.pubkey,
            event=counts.event,
            addressable=counts.addressable,
            identifier=rows,
        )

    async def _populate_rank_stage(
        self,
        conn: asyncpg.Connection[asyncpg.Record],
        *,
        subject_type: RankSubjectType,
        fetch_batch: Callable[..., list[RankExportRow]],
        cycle_start: float,
        computed_at: int,
    ) -> _ExportSubjectResult:
        """Fill one temp export stage from the deterministic DuckDB snapshot."""
        total_rows = 0
        batches_processed = 0
        after_subject_id = ""

        while True:
            if cutoff_reason := self._cycle_cutoff_reason(cycle_start):
                return _ExportSubjectResult(rows=total_rows, cutoff_reason=cutoff_reason)
            if (
                self._config.export.max_batches_per_subject is not None
                and batches_processed >= self._config.export.max_batches_per_subject
            ):
                rows = await self._run_store(
                    fetch_batch,
                    after_subject_id=after_subject_id,
                    limit=self._config.export.batch_size,
                )
                if not rows:
                    return _ExportSubjectResult(rows=total_rows)
                return _ExportSubjectResult(
                    rows=total_rows,
                    cutoff_reason=f"export_{subject_type}_max_batches",
                )
            rows = await self._run_store(
                fetch_batch,
                after_subject_id=after_subject_id,
                limit=self._config.export.batch_size,
            )
            if not rows:
                return _ExportSubjectResult(rows=total_rows)

            await insert_rank_stage_batch(conn, subject_type, rows, computed_at)
            total_rows += len(rows)
            batches_processed += 1
            after_subject_id = rows[-1].subject_id

            if len(rows) < self._config.export.batch_size:
                return _ExportSubjectResult(rows=total_rows)

    def _cycle_cutoff_reason(self, cycle_start: float) -> str | None:
        """Return whether the whole-cycle duration budget has been reached."""
        max_duration = self._config.processing.max_duration
        if max_duration is not None and time.monotonic() - cycle_start >= max_duration:
            return "max_duration"
        return None

    def _sync_cutoff_reason(
        self,
        cycle_start: float,
        batches_processed: int,
        followers_synced: int,
    ) -> str | None:
        """Return the sync budget that should stop the graph-sync phase, if any."""
        if cutoff_reason := self._cycle_cutoff_reason(cycle_start):
            return cutoff_reason

        max_batches = self._config.sync.max_batches
        if max_batches is not None and batches_processed >= max_batches:
            return "sync_max_batches"

        max_followers = self._config.sync.max_followers_per_cycle
        if max_followers is not None and followers_synced >= max_followers:
            return "sync_max_followers_per_cycle"

        return None

    @staticmethod
    def _next_limited_batch_size(
        batch_size: int,
        rows_processed: int,
        max_rows: int | None,
    ) -> int:
        """Return the next fetch size after applying an optional row budget."""
        if max_rows is None:
            return batch_size
        return max(0, min(batch_size, max_rows - rows_processed))

    def _reset_cycle_metrics(self) -> None:
        """Reset point-in-time gauges at the beginning of a ranker cycle."""
        for gauge_name in (
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
        ):
            self.set_gauge(gauge_name, 0)

    def _emit_cycle_metrics(self, result: RankCycleResult) -> None:
        """Emit cycle-level metrics from the typed result object."""
        self.set_gauge("sync_batches_processed", result.sync_batches_processed)
        self.set_gauge("changed_followers_synced", result.changed_followers_synced)
        self.set_gauge("graph_nodes", result.graph_nodes)
        self.set_gauge("graph_edges", result.graph_edges)
        self.set_gauge("facts_stage_event_rows", result.non_user_staged.event)
        self.set_gauge("facts_stage_addressable_rows", result.non_user_staged.addressable)
        self.set_gauge("facts_stage_identifier_rows", result.non_user_staged.identifier)
        self.set_gauge("export_pubkey_rows", result.rank_counts.pubkey)
        self.set_gauge("export_event_rows", result.rank_counts.event)
        self.set_gauge("export_addressable_rows", result.rank_counts.addressable)
        self.set_gauge("export_identifier_rows", result.rank_counts.identifier)
        self.set_gauge("pubkey_ranks_written", result.rank_counts.pubkey)
        self.set_gauge("non_user_ranks_written", result.rank_counts.non_user)
        self.set_gauge("phase_duration_cleanup_seconds", result.phase_durations.cleanup_seconds)
        self.set_gauge("phase_duration_sync_seconds", result.phase_durations.sync_seconds)
        self.set_gauge(
            "phase_duration_facts_stage_seconds",
            result.phase_durations.facts_stage_seconds,
        )
        self.set_gauge("phase_duration_compute_seconds", result.phase_durations.compute_seconds)
        self.set_gauge("phase_duration_export_seconds", result.phase_durations.export_seconds)
        self.set_gauge("checkpoint_lag_seconds", result.checkpoint_lag_seconds)
        self.set_gauge("rank_runs_failed_total", result.rank_runs_failed_total)
        self.set_gauge("duckdb_file_size_bytes", result.duckdb_file_size_bytes)
        self.set_gauge("cleanup_removed_rank_runs", result.cleanup_removed_rank_runs)

        cutoff_reason = result.cutoff_reason or ""
        self.set_gauge(
            "cycle_cutoff_sync_budget",
            1 if cutoff_reason.startswith("sync_") else 0,
        )
        self.set_gauge(
            "cycle_cutoff_stage_budget",
            1 if cutoff_reason.startswith("facts_stage_") else 0,
        )
        self.set_gauge(
            "cycle_cutoff_export_budget",
            1 if cutoff_reason.startswith("export_") else 0,
        )
        self.set_gauge("cycle_cutoff_duration_budget", 1 if cutoff_reason == "max_duration" else 0)
