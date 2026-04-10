"""Ranker service for BigBrotr."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar

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


if TYPE_CHECKING:
    from collections.abc import Callable

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
class _CycleBuildInput:
    """Fields needed to build the public cycle result."""

    rank_run_id: int | None
    sync_result: _GraphSyncResult
    non_user_staged: RankRowCounts = field(default_factory=RankRowCounts)
    rank_counts: RankRowCounts = field(default_factory=RankRowCounts)
    cleanup_removed: int = 0
    phase_durations: RankPhaseDurations = field(default_factory=RankPhaseDurations)
    cutoff_reason: str | None = None


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

    async def __aenter__(self) -> Ranker:
        await super().__aenter__()
        await asyncio.to_thread(self._store.ensure_initialized)
        self._logger.info(
            "duckdb_store_ready",
            algorithm_id=self._config.algorithm_id,
            path=str(self._config.storage.path),
            checkpoint_path=str(self._config.storage.checkpoint_path),
        )
        return self

    async def cleanup(self) -> int:
        """Remove old DuckDB-local rank run records beyond retention."""
        removed = await asyncio.to_thread(
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
        await asyncio.to_thread(self._store.ensure_initialized)
        self._reset_cycle_metrics()

        cleanup_start = time.monotonic()
        cleanup_removed = await self.cleanup()
        cleanup_duration = time.monotonic() - cleanup_start

        sync_start = time.monotonic()
        sync_result = await self._sync_follow_graph(cycle_start)
        sync_duration = time.monotonic() - sync_start

        phase_durations = RankPhaseDurations(
            cleanup_seconds=cleanup_duration,
            sync_seconds=sync_duration,
        )
        if sync_result.cutoff_reason is not None:
            return await self._build_cycle_result(
                _CycleBuildInput(
                    rank_run_id=None,
                    sync_result=sync_result,
                    cleanup_removed=cleanup_removed,
                    phase_durations=phase_durations,
                    cutoff_reason=sync_result.cutoff_reason,
                )
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
            return await self._build_cycle_result(
                _CycleBuildInput(
                    rank_run_id=None,
                    sync_result=sync_result,
                    non_user_staged=stage_result.counts,
                    cleanup_removed=cleanup_removed,
                    phase_durations=phase_durations,
                    cutoff_reason=stage_result.cutoff_reason,
                )
            )

        if cutoff_reason := self._cycle_cutoff_reason(cycle_start):
            return await self._build_cycle_result(
                _CycleBuildInput(
                    rank_run_id=None,
                    sync_result=sync_result,
                    non_user_staged=stage_result.counts,
                    cleanup_removed=cleanup_removed,
                    phase_durations=phase_durations,
                    cutoff_reason=cutoff_reason,
                )
            )

        compute_start = time.monotonic()
        graph_stats = await asyncio.to_thread(
            self._store.get_graph_stats_for_ranking,
            ignore_self_follows=self._config.graph.ignore_self_follows,
        )

        rank_run = await asyncio.to_thread(
            self._store.start_rank_run,
            algorithm_id=self._config.algorithm_id,
            node_count=graph_stats.node_count,
            edge_count=graph_stats.edge_count,
        )

        rank_counts = RankRowCounts()
        try:
            await asyncio.to_thread(
                self._store.compute_pubkey_pagerank,
                damping=self._config.graph.damping,
                iterations=self._config.graph.iterations,
                ignore_self_follows=self._config.graph.ignore_self_follows,
            )
            await asyncio.to_thread(self._store.compute_non_user_ranks)
            compute_duration = time.monotonic() - compute_start

            if cutoff_reason := self._cycle_cutoff_reason(cycle_start):
                await asyncio.to_thread(
                    self._store.finish_rank_run,
                    rank_run.run_id,
                    status="cutoff",
                )
                phase_durations = RankPhaseDurations(
                    cleanup_seconds=cleanup_duration,
                    sync_seconds=sync_duration,
                    facts_stage_seconds=facts_duration,
                    compute_seconds=compute_duration,
                )
                return await self._build_cycle_result(
                    _CycleBuildInput(
                        rank_run_id=rank_run.run_id,
                        sync_result=sync_result,
                        non_user_staged=stage_result.counts,
                        cleanup_removed=cleanup_removed,
                        phase_durations=phase_durations,
                        cutoff_reason=cutoff_reason,
                    )
                )

            export_start = time.monotonic()
            export_result = await self._export_rank_snapshots(
                cycle_start=cycle_start,
                computed_at=int(time.time()),
            )
            export_duration = time.monotonic() - export_start
            if export_result.cutoff_reason is not None:
                await asyncio.to_thread(
                    self._store.finish_rank_run,
                    rank_run.run_id,
                    status="cutoff",
                )
                phase_durations = RankPhaseDurations(
                    cleanup_seconds=cleanup_duration,
                    sync_seconds=sync_duration,
                    facts_stage_seconds=facts_duration,
                    compute_seconds=compute_duration,
                    export_seconds=export_duration,
                )
                return await self._build_cycle_result(
                    _CycleBuildInput(
                        rank_run_id=rank_run.run_id,
                        sync_result=sync_result,
                        non_user_staged=stage_result.counts,
                        cleanup_removed=cleanup_removed,
                        phase_durations=phase_durations,
                        cutoff_reason=export_result.cutoff_reason,
                    )
                )

            rank_counts = export_result.counts
            await asyncio.to_thread(
                self._store.finish_rank_run,
                rank_run.run_id,
                status="success",
            )
        except Exception:
            await asyncio.to_thread(
                self._store.finish_rank_run,
                rank_run.run_id,
                status="failed",
            )
            failed_total = await asyncio.to_thread(self._store.count_rank_runs, status="failed")
            self.set_gauge("rank_runs_failed_total", failed_total)
            raise

        phase_durations = RankPhaseDurations(
            cleanup_seconds=cleanup_duration,
            sync_seconds=sync_duration,
            facts_stage_seconds=facts_duration,
            compute_seconds=compute_duration,
            export_seconds=export_duration,
        )
        result = await self._build_cycle_result(
            _CycleBuildInput(
                rank_run_id=rank_run.run_id,
                sync_result=sync_result,
                non_user_staged=stage_result.counts,
                rank_counts=rank_counts,
                cleanup_removed=cleanup_removed,
                phase_durations=phase_durations,
            )
        )
        self._logger.info(
            "ranker_cycle_completed",
            algorithm_id=self._config.algorithm_id,
            run_id=rank_run.run_id,
            graph_nodes=result.graph_nodes,
            graph_edges=result.graph_edges,
            changed_followers_synced=result.changed_followers_synced,
            sync_batches_processed=result.sync_batches_processed,
            event_stats_staged=result.non_user_staged.event,
            addressable_stats_staged=result.non_user_staged.addressable,
            identifier_stats_staged=result.non_user_staged.identifier,
            pubkey_ranks_written=rank_counts.pubkey,
            event_ranks_written=rank_counts.event,
            addressable_ranks_written=rank_counts.addressable,
            identifier_ranks_written=rank_counts.identifier,
            non_user_ranks_written=rank_counts.non_user,
            checkpoint_seen_at=result.checkpoint.source_seen_at,
            checkpoint_follower_pubkey=result.checkpoint.follower_pubkey,
            checkpoint_lag_seconds=result.checkpoint_lag_seconds,
            duckdb_file_size_bytes=result.duckdb_file_size_bytes,
        )
        return result

    async def _build_cycle_result(
        self,
        data: _CycleBuildInput,
    ) -> RankCycleResult:
        """Build a typed cycle result and emit the matching gauges."""
        graph_stats = await asyncio.to_thread(
            self._store.get_graph_stats_for_ranking,
            ignore_self_follows=self._config.graph.ignore_self_follows,
        )
        source_watermark = await get_contact_list_source_watermark(self._brotr)
        duckdb_file_size = await asyncio.to_thread(self._store.duckdb_file_size_bytes)
        failed_total = await asyncio.to_thread(self._store.count_rank_runs, status="failed")

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
        checkpoint = await asyncio.to_thread(self._store.load_checkpoint)
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

            await asyncio.to_thread(
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
        await asyncio.to_thread(self._store.clear_non_user_stats_stage)

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
        rows_staged = 0
        after_event_id = ""
        while True:
            if cutoff_reason := self._cycle_cutoff_reason(cycle_start):
                return rows_staged, cutoff_reason
            limit = self._next_limited_batch_size(
                self._config.facts_stage.batch_size,
                rows_staged,
                self._config.facts_stage.max_event_rows,
            )
            if limit == 0:
                probe_rows = await fetch_event_stats(self._brotr, after_event_id, 1)
                return rows_staged, "facts_stage_event_rows" if probe_rows else None
            event_rows: list[EventStatFact] = await fetch_event_stats(
                self._brotr, after_event_id, limit
            )
            if not event_rows:
                return rows_staged, None

            await asyncio.to_thread(self._store.append_event_stats_stage_batch, event_rows)
            rows_staged += len(event_rows)
            after_event_id = event_rows[-1].event_id

            if len(event_rows) < limit:
                return rows_staged, None

    async def _stage_addressable_stats(self, cycle_start: float) -> tuple[int, str | None]:
        """Stage addressable facts from PostgreSQL into DuckDB with a row budget."""
        rows_staged = 0
        after_event_address = ""
        while True:
            if cutoff_reason := self._cycle_cutoff_reason(cycle_start):
                return rows_staged, cutoff_reason
            limit = self._next_limited_batch_size(
                self._config.facts_stage.batch_size,
                rows_staged,
                self._config.facts_stage.max_addressable_rows,
            )
            if limit == 0:
                probe_rows = await fetch_addressable_stats(self._brotr, after_event_address, 1)
                return rows_staged, "facts_stage_addressable_rows" if probe_rows else None
            addressable_rows: list[AddressableStatFact] = await fetch_addressable_stats(
                self._brotr, after_event_address, limit
            )
            if not addressable_rows:
                return rows_staged, None

            await asyncio.to_thread(
                self._store.append_addressable_stats_stage_batch,
                addressable_rows,
            )
            rows_staged += len(addressable_rows)
            after_event_address = addressable_rows[-1].event_address

            if len(addressable_rows) < limit:
                return rows_staged, None

    async def _stage_identifier_stats(self, cycle_start: float) -> tuple[int, str | None]:
        """Stage identifier facts from PostgreSQL into DuckDB with a row budget."""
        rows_staged = 0
        after_identifier = ""
        while True:
            if cutoff_reason := self._cycle_cutoff_reason(cycle_start):
                return rows_staged, cutoff_reason
            limit = self._next_limited_batch_size(
                self._config.facts_stage.batch_size,
                rows_staged,
                self._config.facts_stage.max_identifier_rows,
            )
            if limit == 0:
                probe_rows = await fetch_identifier_stats(self._brotr, after_identifier, 1)
                return rows_staged, "facts_stage_identifier_rows" if probe_rows else None
            identifier_rows: list[IdentifierStatFact] = await fetch_identifier_stats(
                self._brotr, after_identifier, limit
            )
            if not identifier_rows:
                return rows_staged, None

            await asyncio.to_thread(
                self._store.append_identifier_stats_stage_batch,
                identifier_rows,
            )
            rows_staged += len(identifier_rows)
            after_identifier = identifier_rows[-1].identifier

            if len(identifier_rows) < limit:
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

            pubkey_result = await self._populate_rank_stage(
                conn,
                subject_type="pubkey",
                fetch_batch=self._store.fetch_pubkey_rank_batch,
                cycle_start=cycle_start,
                computed_at=computed_at,
            )
            if pubkey_result.cutoff_reason is not None:
                return _ExportResult(RankRowCounts(), pubkey_result.cutoff_reason)

            event_result = await self._populate_rank_stage(
                conn,
                subject_type="event",
                fetch_batch=self._store.fetch_event_rank_batch,
                cycle_start=cycle_start,
                computed_at=computed_at,
            )
            if event_result.cutoff_reason is not None:
                return _ExportResult(RankRowCounts(), event_result.cutoff_reason)

            addressable_result = await self._populate_rank_stage(
                conn,
                subject_type="addressable",
                fetch_batch=self._store.fetch_addressable_rank_batch,
                cycle_start=cycle_start,
                computed_at=computed_at,
            )
            if addressable_result.cutoff_reason is not None:
                return _ExportResult(RankRowCounts(), addressable_result.cutoff_reason)

            identifier_result = await self._populate_rank_stage(
                conn,
                subject_type="identifier",
                fetch_batch=self._store.fetch_identifier_rank_batch,
                cycle_start=cycle_start,
                computed_at=computed_at,
            )
            if identifier_result.cutoff_reason is not None:
                return _ExportResult(RankRowCounts(), identifier_result.cutoff_reason)

            for subject_type in ("pubkey", "event", "addressable", "identifier"):
                await merge_rank_stage(conn, subject_type, self._config.algorithm_id)

        return _ExportResult(
            RankRowCounts(
                pubkey=pubkey_result.rows,
                event=event_result.rows,
                addressable=addressable_result.rows,
                identifier=identifier_result.rows,
            )
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
                rows = await asyncio.to_thread(
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
            rows = await asyncio.to_thread(
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
