"""Ranker service for BigBrotr."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
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
class RankCycleResult:
    """Outcome of one ranker service cycle."""

    rank_run_id: int
    changed_followers_synced: int
    graph_nodes: int
    graph_edges: int
    non_user_staged: RankRowCounts
    rank_counts: RankRowCounts
    checkpoint: GraphSyncCheckpoint
    duckdb_file_size_bytes: int


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
        """No-op: the ranker manages only private DuckDB state and snapshots."""
        return 0

    async def run(self) -> None:
        """Sync facts, compute 30382/30383/30384/30385 ranks, and export them."""
        await self.rank()

    async def rank(self) -> RankCycleResult:
        """Sync facts, compute 30382/30383/30384/30385 ranks, and export them."""
        await asyncio.to_thread(self._store.ensure_initialized)

        checkpoint = await asyncio.to_thread(self._store.load_checkpoint)
        changed_followers_synced = 0

        while True:
            changed_lists = await fetch_changed_contact_lists(
                self._brotr,
                checkpoint,
                self._config.sync.batch_size,
            )
            if not changed_lists:
                break

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

            self._logger.info(
                "graph_sync_batch_applied",
                algorithm_id=self._config.algorithm_id,
                changed_followers=len(changed_lists),
                current_edges=len(edges),
                checkpoint_seen_at=checkpoint.source_seen_at,
                checkpoint_follower_pubkey=checkpoint.follower_pubkey,
            )

            if len(changed_lists) < self._config.sync.batch_size:
                break

        non_user_staged = await self._sync_non_user_stats_stage()

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
            rank_counts = await self._export_rank_snapshots(
                computed_at=int(time.time()),
            )
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
            raise

        duckdb_file_size = await asyncio.to_thread(self._store.duckdb_file_size_bytes)

        self.set_gauge("graph_nodes", graph_stats.node_count)
        self.set_gauge("graph_edges", graph_stats.edge_count)
        self.set_gauge("changed_followers_synced", changed_followers_synced)
        self.set_gauge("pubkey_ranks_written", rank_counts.pubkey)
        self.set_gauge("non_user_ranks_written", rank_counts.non_user)
        self.set_gauge("duckdb_file_size_bytes", duckdb_file_size)

        self._logger.info(
            "ranker_cycle_completed",
            algorithm_id=self._config.algorithm_id,
            run_id=rank_run.run_id,
            graph_nodes=graph_stats.node_count,
            graph_edges=graph_stats.edge_count,
            changed_followers_synced=changed_followers_synced,
            event_stats_staged=non_user_staged.event,
            addressable_stats_staged=non_user_staged.addressable,
            identifier_stats_staged=non_user_staged.identifier,
            pubkey_ranks_written=rank_counts.pubkey,
            event_ranks_written=rank_counts.event,
            addressable_ranks_written=rank_counts.addressable,
            identifier_ranks_written=rank_counts.identifier,
            non_user_ranks_written=rank_counts.non_user,
            checkpoint_seen_at=checkpoint.source_seen_at,
            checkpoint_follower_pubkey=checkpoint.follower_pubkey,
            duckdb_file_size_bytes=duckdb_file_size,
        )

        return RankCycleResult(
            rank_run_id=rank_run.run_id,
            changed_followers_synced=changed_followers_synced,
            graph_nodes=graph_stats.node_count,
            graph_edges=graph_stats.edge_count,
            non_user_staged=non_user_staged,
            rank_counts=rank_counts,
            checkpoint=checkpoint,
            duckdb_file_size_bytes=duckdb_file_size,
        )

    async def _sync_non_user_stats_stage(self) -> RankRowCounts:
        """Reload non-user fact stages from PostgreSQL into private DuckDB."""
        batch_size = self._config.facts_stage.batch_size

        await asyncio.to_thread(self._store.clear_non_user_stats_stage)

        event_rows_staged = 0
        after_event_id = ""
        while True:
            event_rows: list[EventStatFact] = await fetch_event_stats(
                self._brotr, after_event_id, batch_size
            )
            if not event_rows:
                break

            await asyncio.to_thread(self._store.append_event_stats_stage_batch, event_rows)
            event_rows_staged += len(event_rows)
            after_event_id = event_rows[-1].event_id

        addressable_rows_staged = 0
        after_event_address = ""
        while True:
            addressable_rows: list[AddressableStatFact] = await fetch_addressable_stats(
                self._brotr, after_event_address, batch_size
            )
            if not addressable_rows:
                break

            await asyncio.to_thread(
                self._store.append_addressable_stats_stage_batch,
                addressable_rows,
            )
            addressable_rows_staged += len(addressable_rows)
            after_event_address = addressable_rows[-1].event_address

        identifier_rows_staged = 0
        after_identifier = ""
        while True:
            identifier_rows: list[IdentifierStatFact] = await fetch_identifier_stats(
                self._brotr, after_identifier, batch_size
            )
            if not identifier_rows:
                break

            await asyncio.to_thread(
                self._store.append_identifier_stats_stage_batch,
                identifier_rows,
            )
            identifier_rows_staged += len(identifier_rows)
            after_identifier = identifier_rows[-1].identifier

        return RankRowCounts(
            event=event_rows_staged,
            addressable=addressable_rows_staged,
            identifier=identifier_rows_staged,
        )

    async def _export_rank_snapshots(self, *, computed_at: int) -> RankRowCounts:
        """Snapshot-export all final NIP-85 rank tables into PostgreSQL."""
        async with self._brotr.transaction() as conn:
            await create_rank_stages(conn)

            pubkey_rows = await self._populate_rank_stage(
                conn,
                subject_type="pubkey",
                fetch_batch=self._store.fetch_pubkey_rank_batch,
                computed_at=computed_at,
            )
            event_rows = await self._populate_rank_stage(
                conn,
                subject_type="event",
                fetch_batch=self._store.fetch_event_rank_batch,
                computed_at=computed_at,
            )
            addressable_rows = await self._populate_rank_stage(
                conn,
                subject_type="addressable",
                fetch_batch=self._store.fetch_addressable_rank_batch,
                computed_at=computed_at,
            )
            identifier_rows = await self._populate_rank_stage(
                conn,
                subject_type="identifier",
                fetch_batch=self._store.fetch_identifier_rank_batch,
                computed_at=computed_at,
            )

            for subject_type in ("pubkey", "event", "addressable", "identifier"):
                await merge_rank_stage(conn, subject_type, self._config.algorithm_id)

        return RankRowCounts(
            pubkey=pubkey_rows,
            event=event_rows,
            addressable=addressable_rows,
            identifier=identifier_rows,
        )

    async def _populate_rank_stage(
        self,
        conn: asyncpg.Connection[asyncpg.Record],
        *,
        subject_type: RankSubjectType,
        fetch_batch: Callable[..., list[RankExportRow]],
        computed_at: int,
    ) -> int:
        """Fill one temp export stage from the deterministic DuckDB snapshot."""
        total_rows = 0
        after_subject_id = ""

        while True:
            rows = await asyncio.to_thread(
                fetch_batch,
                after_subject_id=after_subject_id,
                limit=self._config.export.batch_size,
            )
            if not rows:
                break

            await insert_rank_stage_batch(conn, subject_type, rows, computed_at)
            total_rows += len(rows)
            after_subject_id = rows[-1].subject_id

        return total_rows
