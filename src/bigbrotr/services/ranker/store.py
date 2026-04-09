"""Private DuckDB store for the ranker service."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import duckdb

from .queries import ContactListFact, FollowEdgeFact, GraphSyncCheckpoint


if TYPE_CHECKING:
    from pathlib import Path


_DEFAULT_CHECKPOINT: Final[GraphSyncCheckpoint] = GraphSyncCheckpoint()


@dataclass(frozen=True, slots=True)
class GraphStats:
    """Current follow-graph size in DuckDB."""

    node_count: int
    edge_count: int


class RankerStore:
    """DuckDB-backed private working store for the ranker."""

    def __init__(self, db_path: Path, checkpoint_path: Path) -> None:
        self._db_path = db_path
        self._checkpoint_path = checkpoint_path

    def ensure_initialized(self) -> None:
        """Create the DuckDB file, directories, schema, and checkpoint file."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

        with duckdb.connect(str(self._db_path)) as conn:
            for statement in _SCHEMA_STATEMENTS:
                conn.execute(statement)

        if not self._checkpoint_path.exists():
            self._write_checkpoint(_DEFAULT_CHECKPOINT)

    def load_checkpoint(self) -> GraphSyncCheckpoint:
        """Read the lexicographic follow-graph checkpoint from disk."""
        if not self._checkpoint_path.exists():
            return _DEFAULT_CHECKPOINT

        raw = json.loads(self._checkpoint_path.read_text())
        graph = raw.get("graph", {})
        return GraphSyncCheckpoint(
            source_seen_at=int(graph.get("source_seen_at", 0)),
            follower_pubkey=str(graph.get("follower_pubkey", "")),
        )

    def apply_follow_graph_delta(
        self,
        changed_lists: list[ContactListFact],
        edges: list[FollowEdgeFact],
        checkpoint: GraphSyncCheckpoint,
    ) -> None:
        """Apply one incremental follow-graph batch and persist the checkpoint."""
        if not changed_lists:
            self._write_checkpoint(checkpoint)
            return

        self.ensure_initialized()

        pubkeys = (
            {fact.follower_pubkey for fact in changed_lists}
            | {fact.follower_pubkey for fact in edges}
            | {fact.followed_pubkey for fact in edges}
        )

        with duckdb.connect(str(self._db_path)) as conn:
            conn.execute("BEGIN TRANSACTION")
            try:
                node_ids = self._ensure_node_ids(conn, sorted(pubkeys))
                follower_node_ids = [node_ids[fact.follower_pubkey] for fact in changed_lists]

                self._delete_followers(conn, follower_node_ids)

                conn.executemany(
                    """
                    INSERT INTO contact_lists_current (
                        follower_node_id,
                        source_event_id,
                        source_created_at,
                        source_seen_at,
                        follow_count
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            node_ids[fact.follower_pubkey],
                            fact.source_event_id,
                            fact.source_created_at,
                            fact.source_seen_at,
                            fact.follow_count,
                        )
                        for fact in changed_lists
                    ],
                )

                if edges:
                    conn.executemany(
                        """
                        INSERT INTO follow_edges_current (
                            follower_node_id,
                            followed_node_id
                        ) VALUES (?, ?)
                        """,
                        [
                            (node_ids[fact.follower_pubkey], node_ids[fact.followed_pubkey])
                            for fact in edges
                        ],
                    )

                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

        self._write_checkpoint(checkpoint)

    def get_graph_stats(self) -> GraphStats:
        """Return the current node/edge counts stored in DuckDB."""
        self.ensure_initialized()

        with duckdb.connect(str(self._db_path)) as conn:
            node_count_row = conn.execute("SELECT COUNT(*) FROM pubkey_nodes").fetchone()
            edge_count_row = conn.execute("SELECT COUNT(*) FROM follow_edges_current").fetchone()

        node_count = int(node_count_row[0]) if node_count_row is not None else 0
        edge_count = int(edge_count_row[0]) if edge_count_row is not None else 0

        return GraphStats(node_count=node_count, edge_count=edge_count)

    def duckdb_file_size_bytes(self) -> int:
        """Return the current DuckDB file size in bytes."""
        if not self._db_path.exists():
            return 0
        return self._db_path.stat().st_size

    def _ensure_node_ids(
        self,
        conn: duckdb.DuckDBPyConnection,
        pubkeys: list[str],
    ) -> dict[str, int]:
        if not pubkeys:
            return {}

        rows = conn.execute(
            """
            SELECT pubkey, node_id
            FROM pubkey_nodes
            WHERE pubkey = ANY(?)
            """,
            [pubkeys],
        ).fetchall()
        node_ids = {str(pubkey): int(node_id) for pubkey, node_id in rows}

        missing = [pubkey for pubkey in pubkeys if pubkey not in node_ids]
        if not missing:
            return node_ids

        next_node_row = conn.execute(
            "SELECT COALESCE(MAX(node_id), 0) + 1 FROM pubkey_nodes"
        ).fetchone()
        next_node_id = int(next_node_row[0]) if next_node_row is not None else 1
        new_rows = []
        for offset, pubkey in enumerate(missing):
            node_id = next_node_id + offset
            node_ids[pubkey] = node_id
            new_rows.append((node_id, pubkey))

        conn.executemany(
            "INSERT INTO pubkey_nodes (node_id, pubkey) VALUES (?, ?)",
            new_rows,
        )
        return node_ids

    def _delete_followers(
        self,
        conn: duckdb.DuckDBPyConnection,
        follower_node_ids: list[int],
    ) -> None:
        if not follower_node_ids:
            return

        conn.execute(
            "DELETE FROM follow_edges_current WHERE follower_node_id = ANY(?)",
            [follower_node_ids],
        )
        conn.execute(
            "DELETE FROM contact_lists_current WHERE follower_node_id = ANY(?)",
            [follower_node_ids],
        )

    def _write_checkpoint(self, checkpoint: GraphSyncCheckpoint) -> None:
        payload = {
            "graph": {
                "source_seen_at": checkpoint.source_seen_at,
                "follower_pubkey": checkpoint.follower_pubkey,
            }
        }
        self._checkpoint_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


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
)
