"""Ranker service for BigBrotr."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, ClassVar

from bigbrotr.core.base_service import BaseService
from bigbrotr.models.constants import ServiceName

from .configs import RankerConfig
from .queries import (
    GraphSyncCheckpoint,
    fetch_changed_contact_lists,
    fetch_follow_edges_for_followers,
)
from .store import RankerStore


if TYPE_CHECKING:
    from bigbrotr.core.brotr import Brotr


class Ranker(BaseService[RankerConfig]):
    """Private DuckDB-backed ranker skeleton for NIP-85 pipelines."""

    SERVICE_NAME: ClassVar[ServiceName] = ServiceName.RANKER
    CONFIG_CLASS: ClassVar[type[RankerConfig]] = RankerConfig

    def __init__(self, brotr: Brotr, config: RankerConfig | None = None) -> None:
        super().__init__(brotr=brotr, config=config)
        self._config: RankerConfig
        self._store = RankerStore(
            db_path=self._config.db.path,
            checkpoint_path=self._config.db.checkpoint_path,
        )

    async def __aenter__(self) -> Ranker:
        await super().__aenter__()
        await asyncio.to_thread(self._store.ensure_initialized)
        self._logger.info(
            "duckdb_store_ready",
            algorithm_id=self._config.algorithm_id,
            path=str(self._config.db.path),
            checkpoint_path=str(self._config.db.checkpoint_path),
        )
        return self

    async def cleanup(self) -> int:
        """No-op: Phase 4 only syncs canonical follow-graph facts."""
        return 0

    async def run(self) -> None:
        """Sync the canonical follow graph from PostgreSQL into DuckDB."""
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

        graph_stats = await asyncio.to_thread(self._store.get_graph_stats)
        duckdb_file_size = await asyncio.to_thread(self._store.duckdb_file_size_bytes)

        self.set_gauge("graph_nodes", graph_stats.node_count)
        self.set_gauge("graph_edges", graph_stats.edge_count)
        self.set_gauge("changed_followers_synced", changed_followers_synced)
        self.set_gauge("pubkey_ranks_written", 0)
        self.set_gauge("non_user_ranks_written", 0)
        self.set_gauge("duckdb_file_size_bytes", duckdb_file_size)

        self._logger.info(
            "graph_sync_completed",
            algorithm_id=self._config.algorithm_id,
            graph_nodes=graph_stats.node_count,
            graph_edges=graph_stats.edge_count,
            changed_followers_synced=changed_followers_synced,
            checkpoint_seen_at=checkpoint.source_seen_at,
            checkpoint_follower_pubkey=checkpoint.follower_pubkey,
            duckdb_file_size_bytes=duckdb_file_size,
        )
