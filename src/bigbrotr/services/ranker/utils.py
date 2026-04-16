"""Private DuckDB utilities for the ranker service."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import duckdb

from . import store_graph, store_non_user
from .queries import (
    AddressableStatFact,
    ContactListFact,
    EventStatFact,
    FollowEdgeFact,
    GraphSyncCheckpoint,
    IdentifierStatFact,
    RankExportRow,
)


if TYPE_CHECKING:
    from pathlib import Path


GraphStats = store_graph.GraphStats


@dataclass(frozen=True, slots=True)
class RankRun:
    """One ranker run tracked inside the private DuckDB store."""

    run_id: int
    algorithm_id: str
    started_at: int
    node_count: int
    edge_count: int


class RankerStore:
    """DuckDB-backed private working store for the ranker."""

    def __init__(self, db_path: Path, checkpoint_path: Path) -> None:
        self._db_path = db_path
        self._checkpoint_path = checkpoint_path
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._conn_thread_id: int | None = None

    def close(self) -> None:
        """Close the cached DuckDB connection if one is open."""
        conn = self._conn
        self._conn = None
        self._conn_thread_id = None
        if conn is not None:
            conn.close()

    def ensure_initialized(self) -> None:
        """Create the DuckDB file, directories, schema, and canonical checkpoint row."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

        conn = self._connection()
        for statement in _SCHEMA_STATEMENTS:
            conn.execute(statement)
        if store_graph.load_checkpoint_from_db(conn) is None:
            store_graph.upsert_checkpoint(
                conn,
                store_graph.load_legacy_checkpoint(self._checkpoint_path),
            )

    def load_checkpoint(self) -> GraphSyncCheckpoint:
        """Read the canonical lexicographic follow-graph checkpoint from DuckDB."""
        self.ensure_initialized()
        checkpoint = store_graph.load_checkpoint_from_db(self._connection())
        return checkpoint if checkpoint is not None else GraphSyncCheckpoint()

    def apply_follow_graph_delta(
        self,
        changed_lists: list[ContactListFact],
        edges: list[FollowEdgeFact],
        checkpoint: GraphSyncCheckpoint,
    ) -> None:
        """Apply one incremental follow-graph batch and persist the checkpoint."""
        self.ensure_initialized()
        store_graph.apply_follow_graph_delta(
            self._connection(),
            changed_lists=changed_lists,
            edges=edges,
            checkpoint=checkpoint,
        )

    def get_graph_stats(self) -> GraphStats:
        """Return the current node/edge counts stored in DuckDB."""
        self.ensure_initialized()
        return store_graph.get_graph_stats(self._connection())

    def get_graph_stats_for_ranking(self, *, ignore_self_follows: bool) -> GraphStats:
        """Return graph counts for the effective edge set used by PageRank."""
        self.ensure_initialized()
        return store_graph.get_graph_stats_for_ranking(
            self._connection(),
            ignore_self_follows=ignore_self_follows,
        )

    def duckdb_file_size_bytes(self) -> int:
        """Return the current DuckDB file size in bytes."""
        if not self._db_path.exists():
            return 0
        return self._db_path.stat().st_size

    def start_rank_run(
        self,
        *,
        algorithm_id: str,
        node_count: int,
        edge_count: int,
    ) -> RankRun:
        """Create a new DuckDB-local run record before ranking/export starts."""
        self.ensure_initialized()

        started_at = int(time.time())

        conn = self._connection()
        next_run_row = conn.execute("SELECT COALESCE(MAX(run_id), 0) + 1 FROM rank_runs").fetchone()
        run_id = int(next_run_row[0]) if next_run_row is not None else 1
        conn.execute(
            """
            INSERT INTO rank_runs (
                run_id,
                algorithm_id,
                started_at,
                status,
                node_count,
                edge_count
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [run_id, algorithm_id, started_at, "running", node_count, edge_count],
        )

        return RankRun(
            run_id=run_id,
            algorithm_id=algorithm_id,
            started_at=started_at,
            node_count=node_count,
            edge_count=edge_count,
        )

    def finish_rank_run(self, run_id: int, *, status: str) -> None:
        """Mark a tracked run as ``success`` or ``failed`` after export finishes."""
        self.ensure_initialized()

        conn = self._connection()
        conn.execute(
            """
            UPDATE rank_runs
            SET finished_at = ?, status = ?
            WHERE run_id = ?
            """,
            [int(time.time()), status, run_id],
        )

    def count_rank_runs(self, *, status: str | None = None) -> int:
        """Count local rank run records, optionally filtered by status."""
        self.ensure_initialized()

        conn = self._connection()
        if status is None:
            row = conn.execute("SELECT COUNT(*) FROM rank_runs").fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) FROM rank_runs WHERE status = ?",
                [status],
            ).fetchone()

        return int(row[0]) if row is not None else 0

    def delete_rank_runs_older_than_retention(self, retention: int | None) -> int:
        """Delete old local rank-run records beyond the configured retention."""
        if retention is None:
            return 0

        self.ensure_initialized()

        conn = self._connection()
        before_row = conn.execute("SELECT COUNT(*) FROM rank_runs").fetchone()
        before = int(before_row[0]) if before_row is not None else 0
        conn.execute(
            """
            DELETE FROM rank_runs
            WHERE run_id IN (
                SELECT run_id
                FROM (
                    SELECT
                        run_id,
                        ROW_NUMBER() OVER (ORDER BY run_id DESC) AS row_num
                    FROM rank_runs
                )
                WHERE row_num > ?
            )
            """,
            [retention],
        )
        after_row = conn.execute("SELECT COUNT(*) FROM rank_runs").fetchone()
        after = int(after_row[0]) if after_row is not None else 0

        return before - after

    def compute_pubkey_pagerank(
        self,
        *,
        damping: float,
        iterations: int,
        ignore_self_follows: bool,
    ) -> None:
        """Compute deterministic PageRank over the current canonical follow graph."""
        self.ensure_initialized()
        store_graph.compute_pubkey_pagerank(
            self._connection(),
            damping=damping,
            iterations=iterations,
            ignore_self_follows=ignore_self_follows,
        )

    def fetch_pubkey_rank_batch(
        self,
        *,
        after_subject_id: str,
        limit: int,
    ) -> list[RankExportRow]:
        """Fetch one deterministic export batch from the final PageRank snapshot."""
        self.ensure_initialized()
        return store_graph.fetch_pubkey_rank_batch(
            self._connection(),
            after_subject_id=after_subject_id,
            limit=limit,
        )

    def clear_non_user_stats_stage(self) -> None:
        """Reset the staged non-user facts loaded from PostgreSQL."""
        self.ensure_initialized()
        store_non_user.clear_non_user_stats_stage(self._connection())

    def append_event_stats_stage_batch(self, rows: list[EventStatFact]) -> None:
        """Append one PostgreSQL batch into the local event-facts stage table."""
        self.ensure_initialized()
        store_non_user.append_event_stats_stage_batch(self._connection(), rows)

    def append_addressable_stats_stage_batch(self, rows: list[AddressableStatFact]) -> None:
        """Append one PostgreSQL batch into the local addressable-facts stage table."""
        self.ensure_initialized()
        store_non_user.append_addressable_stats_stage_batch(self._connection(), rows)

    def append_identifier_stats_stage_batch(self, rows: list[IdentifierStatFact]) -> None:
        """Append one PostgreSQL batch into the local identifier-facts stage table."""
        self.ensure_initialized()
        store_non_user.append_identifier_stats_stage_batch(self._connection(), rows)

    def compute_non_user_ranks(self) -> None:
        """Compute final 30383/30384/30385 ranks from the staged facts tables."""
        self.ensure_initialized()
        store_non_user.compute_non_user_ranks(self._connection())

    def _connection(self) -> duckdb.DuckDBPyConnection:
        thread_id = threading.get_ident()
        conn = self._conn
        if conn is None:
            conn = duckdb.connect(str(self._db_path))
            self._conn = conn
            self._conn_thread_id = thread_id
            return conn
        if self._conn_thread_id != thread_id:
            raise RuntimeError("RankerStore connection must be used from a single dedicated thread")
        return conn

    def fetch_event_rank_batch(
        self,
        *,
        after_subject_id: str,
        limit: int,
    ) -> list[RankExportRow]:
        """Fetch one deterministic export batch from the final event-rank snapshot."""
        return self._fetch_rank_batch(
            table_name="nip85_event_ranks_curr",
            after_subject_id=after_subject_id,
            limit=limit,
        )

    def fetch_addressable_rank_batch(
        self,
        *,
        after_subject_id: str,
        limit: int,
    ) -> list[RankExportRow]:
        """Fetch one deterministic export batch from the final addressable snapshot."""
        return self._fetch_rank_batch(
            table_name="nip85_addressable_ranks_curr",
            after_subject_id=after_subject_id,
            limit=limit,
        )

    def fetch_identifier_rank_batch(
        self,
        *,
        after_subject_id: str,
        limit: int,
    ) -> list[RankExportRow]:
        """Fetch one deterministic export batch from the final identifier snapshot."""
        return self._fetch_rank_batch(
            table_name="nip85_identifier_ranks_curr",
            after_subject_id=after_subject_id,
            limit=limit,
        )

    def _ensure_node_ids(
        self,
        conn: duckdb.DuckDBPyConnection,
        pubkeys: list[str],
    ) -> dict[str, int]:
        return store_graph.ensure_node_ids(conn, pubkeys)

    def _delete_followers(
        self,
        conn: duckdb.DuckDBPyConnection,
        follower_node_ids: list[int],
    ) -> None:
        store_graph.delete_followers(conn, follower_node_ids)

    def _fetch_rank_batch(
        self,
        *,
        table_name: str,
        after_subject_id: str,
        limit: int,
    ) -> list[RankExportRow]:
        self.ensure_initialized()
        return store_non_user.fetch_rank_batch(
            self._connection(),
            table_name=table_name,
            after_subject_id=after_subject_id,
            limit=limit,
        )


_SCHEMA_STATEMENTS: Final[tuple[str, ...]] = (
    """
    CREATE TABLE IF NOT EXISTS pubkey_nodes (
        node_id BIGINT PRIMARY KEY,
        pubkey VARCHAR NOT NULL UNIQUE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS contact_lists_current (
        follower_node_id BIGINT PRIMARY KEY,
        source_event_id VARCHAR NOT NULL,
        source_created_at BIGINT NOT NULL,
        source_seen_at BIGINT NOT NULL,
        follow_count BIGINT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS follow_edges_current (
        follower_node_id BIGINT NOT NULL,
        followed_node_id BIGINT NOT NULL,
        PRIMARY KEY (follower_node_id, followed_node_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pagerank_curr (
        node_id BIGINT PRIMARY KEY,
        raw_score DOUBLE NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pagerank_next (
        node_id BIGINT PRIMARY KEY,
        raw_score DOUBLE NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS rank_runs (
        run_id BIGINT PRIMARY KEY,
        algorithm_id VARCHAR NOT NULL,
        started_at BIGINT NOT NULL,
        finished_at BIGINT,
        status VARCHAR NOT NULL,
        node_count BIGINT NOT NULL DEFAULT 0,
        edge_count BIGINT NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_sync_checkpoint (
        checkpoint_name VARCHAR PRIMARY KEY,
        source_seen_at BIGINT NOT NULL DEFAULT 0,
        follower_pubkey VARCHAR NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS nip85_event_stats_stage (
        event_id VARCHAR PRIMARY KEY,
        author_pubkey VARCHAR NOT NULL,
        comment_count BIGINT NOT NULL DEFAULT 0,
        quote_count BIGINT NOT NULL DEFAULT 0,
        repost_count BIGINT NOT NULL DEFAULT 0,
        reaction_count BIGINT NOT NULL DEFAULT 0,
        zap_count BIGINT NOT NULL DEFAULT 0,
        zap_amount BIGINT NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS nip85_addressable_stats_stage (
        event_address VARCHAR PRIMARY KEY,
        author_pubkey VARCHAR NOT NULL,
        comment_count BIGINT NOT NULL DEFAULT 0,
        quote_count BIGINT NOT NULL DEFAULT 0,
        repost_count BIGINT NOT NULL DEFAULT 0,
        reaction_count BIGINT NOT NULL DEFAULT 0,
        zap_count BIGINT NOT NULL DEFAULT 0,
        zap_amount BIGINT NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS nip85_identifier_stats_stage (
        identifier VARCHAR PRIMARY KEY,
        comment_count BIGINT NOT NULL DEFAULT 0,
        reaction_count BIGINT NOT NULL DEFAULT 0,
        k_tags VARCHAR[] NOT NULL DEFAULT []
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS nip85_event_ranks_curr (
        subject_id VARCHAR PRIMARY KEY,
        raw_score DOUBLE NOT NULL,
        rank BIGINT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS nip85_addressable_ranks_curr (
        subject_id VARCHAR PRIMARY KEY,
        raw_score DOUBLE NOT NULL,
        rank BIGINT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS nip85_identifier_ranks_curr (
        subject_id VARCHAR PRIMARY KEY,
        raw_score DOUBLE NOT NULL,
        rank BIGINT NOT NULL
    )
    """,
)
