"""Private DuckDB utilities for the ranker service."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import duckdb

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


_DEFAULT_CHECKPOINT: Final[GraphSyncCheckpoint] = GraphSyncCheckpoint()


@dataclass(frozen=True, slots=True)
class GraphStats:
    """Current follow-graph size in DuckDB."""

    node_count: int
    edge_count: int


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
            node_count_row = conn.execute(_ACTIVE_NODE_COUNT_QUERY).fetchone()
            edge_count_row = conn.execute(_ACTIVE_EDGE_COUNT_QUERY).fetchone()

        node_count = int(node_count_row[0]) if node_count_row is not None else 0
        edge_count = int(edge_count_row[0]) if edge_count_row is not None else 0

        return GraphStats(node_count=node_count, edge_count=edge_count)

    def get_graph_stats_for_ranking(self, *, ignore_self_follows: bool) -> GraphStats:
        """Return graph counts for the effective edge set used by PageRank."""
        self.ensure_initialized()

        edge_query = (
            _ACTIVE_EDGE_COUNT_NO_SELF_QUERY if ignore_self_follows else _ACTIVE_EDGE_COUNT_QUERY
        )

        with duckdb.connect(str(self._db_path)) as conn:
            node_count_row = conn.execute(_ACTIVE_NODE_COUNT_QUERY).fetchone()
            edge_count_row = conn.execute(edge_query).fetchone()

        node_count = int(node_count_row[0]) if node_count_row is not None else 0
        edge_count = int(edge_count_row[0]) if edge_count_row is not None else 0

        return GraphStats(node_count=node_count, edge_count=edge_count)

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

        with duckdb.connect(str(self._db_path)) as conn:
            next_run_row = conn.execute(
                "SELECT COALESCE(MAX(run_id), 0) + 1 FROM rank_runs"
            ).fetchone()
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

        with duckdb.connect(str(self._db_path)) as conn:
            conn.execute(
                """
                UPDATE rank_runs
                SET finished_at = ?, status = ?
                WHERE run_id = ?
                """,
                [int(time.time()), status, run_id],
            )

    def compute_pubkey_pagerank(
        self,
        *,
        damping: float,
        iterations: int,
        ignore_self_follows: bool,
    ) -> None:
        """Compute deterministic PageRank over the current canonical follow graph."""
        self.ensure_initialized()

        edge_filter = "WHERE follower_node_id <> followed_node_id" if ignore_self_follows else ""

        with duckdb.connect(str(self._db_path)) as conn:
            conn.execute("BEGIN TRANSACTION")
            try:
                node_count_row = conn.execute(_ACTIVE_NODE_COUNT_QUERY).fetchone()
                node_count = int(node_count_row[0]) if node_count_row is not None else 0

                conn.execute("DELETE FROM pagerank_curr")
                conn.execute("DELETE FROM pagerank_next")

                if node_count == 0:
                    conn.execute("COMMIT")
                    return

                initial_score = 1.0 / float(node_count)
                conn.execute(_INSERT_INITIAL_PAGERANK_QUERY, [initial_score])

                dangling_mass_query = _DANGLING_MASS_QUERY.format(edge_filter=edge_filter)
                next_query = _INSERT_NEXT_PAGERANK_QUERY.format(edge_filter=edge_filter)

                for _ in range(iterations):
                    dangling_row = conn.execute(dangling_mass_query).fetchone()
                    dangling_mass = float(dangling_row[0]) if dangling_row is not None else 0.0

                    conn.execute("DELETE FROM pagerank_next")
                    conn.execute(
                        next_query,
                        [
                            1.0 - damping,
                            float(node_count),
                            damping,
                            dangling_mass,
                            float(node_count),
                            damping,
                        ],
                    )
                    conn.execute("DELETE FROM pagerank_curr")
                    conn.execute(
                        """
                        INSERT INTO pagerank_curr (node_id, raw_score)
                        SELECT node_id, raw_score
                        FROM pagerank_next
                        ORDER BY node_id
                        """
                    )

                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def fetch_pubkey_rank_batch(
        self,
        *,
        after_subject_id: str,
        limit: int,
    ) -> list[RankExportRow]:
        """Fetch one deterministic export batch from the final PageRank snapshot."""
        self.ensure_initialized()

        with duckdb.connect(str(self._db_path)) as conn:
            node_count_row = conn.execute("SELECT COUNT(*) FROM pagerank_curr").fetchone()
            node_count = int(node_count_row[0]) if node_count_row is not None else 0
            if node_count == 0:
                return []

            baseline_score = 1.0 / float(node_count)
            rows = conn.execute(
                _PUBKEY_RANK_EXPORT_QUERY,
                [baseline_score, after_subject_id, limit],
            ).fetchall()

        return [
            RankExportRow(
                subject_id=str(subject_id),
                raw_score=float(raw_score),
                rank=int(rank),
            )
            for subject_id, raw_score, rank in rows
        ]

    def clear_non_user_stats_stage(self) -> None:
        """Reset the staged non-user facts loaded from PostgreSQL."""
        self.ensure_initialized()

        with duckdb.connect(str(self._db_path)) as conn:
            conn.execute("BEGIN TRANSACTION")
            try:
                conn.execute("DELETE FROM nip85_event_stats_stage")
                conn.execute("DELETE FROM nip85_addressable_stats_stage")
                conn.execute("DELETE FROM nip85_identifier_stats_stage")
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def append_event_stats_stage_batch(self, rows: list[EventStatFact]) -> None:
        """Append one PostgreSQL batch into the local event-facts stage table."""
        if not rows:
            return

        self.ensure_initialized()

        with duckdb.connect(str(self._db_path)) as conn:
            conn.executemany(
                """
                INSERT INTO nip85_event_stats_stage (
                    event_id,
                    author_pubkey,
                    comment_count,
                    quote_count,
                    repost_count,
                    reaction_count,
                    zap_count,
                    zap_amount
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row.event_id,
                        row.author_pubkey,
                        row.comment_count,
                        row.quote_count,
                        row.repost_count,
                        row.reaction_count,
                        row.zap_count,
                        row.zap_amount,
                    )
                    for row in rows
                ],
            )

    def append_addressable_stats_stage_batch(self, rows: list[AddressableStatFact]) -> None:
        """Append one PostgreSQL batch into the local addressable-facts stage table."""
        if not rows:
            return

        self.ensure_initialized()

        with duckdb.connect(str(self._db_path)) as conn:
            conn.executemany(
                """
                INSERT INTO nip85_addressable_stats_stage (
                    event_address,
                    author_pubkey,
                    comment_count,
                    quote_count,
                    repost_count,
                    reaction_count,
                    zap_count,
                    zap_amount
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row.event_address,
                        row.author_pubkey,
                        row.comment_count,
                        row.quote_count,
                        row.repost_count,
                        row.reaction_count,
                        row.zap_count,
                        row.zap_amount,
                    )
                    for row in rows
                ],
            )

    def append_identifier_stats_stage_batch(self, rows: list[IdentifierStatFact]) -> None:
        """Append one PostgreSQL batch into the local identifier-facts stage table."""
        if not rows:
            return

        self.ensure_initialized()

        with duckdb.connect(str(self._db_path)) as conn:
            conn.executemany(
                """
                INSERT INTO nip85_identifier_stats_stage (
                    identifier,
                    comment_count,
                    reaction_count,
                    k_tags
                ) VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        row.identifier,
                        row.comment_count,
                        row.reaction_count,
                        list(row.k_tags),
                    )
                    for row in rows
                ],
            )

    def compute_non_user_ranks(self) -> None:
        """Compute final 30383/30384/30385 ranks from the staged facts tables."""
        self.ensure_initialized()

        with duckdb.connect(str(self._db_path)) as conn:
            conn.execute("BEGIN TRANSACTION")
            try:
                conn.execute("DELETE FROM nip85_event_ranks_curr")
                conn.execute("DELETE FROM nip85_addressable_ranks_curr")
                conn.execute("DELETE FROM nip85_identifier_ranks_curr")

                conn.execute(_INSERT_EVENT_RANKS_QUERY)
                conn.execute(_INSERT_ADDRESSABLE_RANKS_QUERY)
                conn.execute(_INSERT_IDENTIFIER_RANKS_QUERY)

                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

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

    def _fetch_rank_batch(
        self,
        *,
        table_name: str,
        after_subject_id: str,
        limit: int,
    ) -> list[RankExportRow]:
        self.ensure_initialized()

        with duckdb.connect(str(self._db_path)) as conn:
            rows = conn.execute(
                _RANK_BATCH_QUERIES[table_name],
                [after_subject_id, limit],
            ).fetchall()

        return [
            RankExportRow(
                subject_id=str(subject_id),
                raw_score=float(raw_score),
                rank=int(rank),
            )
            for subject_id, raw_score, rank in rows
        ]


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

_ACTIVE_NODE_COUNT_QUERY: Final[str] = """
WITH active_nodes AS (
    SELECT follower_node_id AS node_id
    FROM contact_lists_current
    UNION
    SELECT followed_node_id AS node_id
    FROM follow_edges_current
)
SELECT COUNT(*)
FROM active_nodes
"""

_ACTIVE_EDGE_COUNT_QUERY: Final[str] = """
SELECT COUNT(*)
FROM follow_edges_current
"""

_ACTIVE_EDGE_COUNT_NO_SELF_QUERY: Final[str] = """
SELECT COUNT(*)
FROM follow_edges_current
WHERE follower_node_id <> followed_node_id
"""

_INSERT_INITIAL_PAGERANK_QUERY: Final[str] = """
INSERT INTO pagerank_curr (node_id, raw_score)
WITH active_nodes AS (
    SELECT follower_node_id AS node_id
    FROM contact_lists_current
    UNION
    SELECT followed_node_id AS node_id
    FROM follow_edges_current
)
SELECT node_id, ?
FROM active_nodes
ORDER BY node_id
"""

_DANGLING_MASS_QUERY: Final[str] = """
WITH out_degree AS (
    SELECT
        follower_node_id AS node_id,
        COUNT(*) AS out_degree
    FROM follow_edges_current
    {edge_filter}
    GROUP BY follower_node_id
)
SELECT COALESCE(SUM(c.raw_score), 0.0)
FROM pagerank_curr AS c
LEFT JOIN out_degree AS o ON o.node_id = c.node_id
WHERE COALESCE(o.out_degree, 0) = 0
"""

_INSERT_NEXT_PAGERANK_QUERY: Final[str] = """
INSERT INTO pagerank_next (node_id, raw_score)
WITH out_degree AS (
    SELECT
        follower_node_id AS node_id,
        COUNT(*) AS out_degree
    FROM follow_edges_current
    {edge_filter}
    GROUP BY follower_node_id
),
inbound AS (
    SELECT
        e.followed_node_id AS node_id,
        SUM(c.raw_score / o.out_degree) AS inbound_score
    FROM follow_edges_current AS e
    INNER JOIN out_degree AS o ON o.node_id = e.follower_node_id
    INNER JOIN pagerank_curr AS c ON c.node_id = e.follower_node_id
    {edge_filter}
    GROUP BY e.followed_node_id
)
SELECT
    c.node_id,
    (? / ?) + (? * ? / ?) + (? * COALESCE(i.inbound_score, 0.0))
FROM pagerank_curr AS c
LEFT JOIN inbound AS i ON i.node_id = c.node_id
ORDER BY c.node_id
"""

_PUBKEY_RANK_EXPORT_QUERY: Final[str] = """
SELECT
    n.pubkey AS subject_id,
    p.raw_score,
    CAST(ROUND(LEAST(25 * LOG10((p.raw_score / ?) + 1), 100.0)) AS BIGINT) AS rank
FROM pagerank_curr AS p
INNER JOIN pubkey_nodes AS n ON n.node_id = p.node_id
WHERE n.pubkey > ?
ORDER BY n.pubkey ASC
LIMIT ?
"""

_RANK_BATCH_QUERIES: Final[dict[str, str]] = {
    "nip85_event_ranks_curr": """
SELECT subject_id, raw_score, rank
FROM nip85_event_ranks_curr
WHERE subject_id > ?
ORDER BY subject_id ASC
LIMIT ?
""",
    "nip85_addressable_ranks_curr": """
SELECT subject_id, raw_score, rank
FROM nip85_addressable_ranks_curr
WHERE subject_id > ?
ORDER BY subject_id ASC
LIMIT ?
""",
    "nip85_identifier_ranks_curr": """
SELECT subject_id, raw_score, rank
FROM nip85_identifier_ranks_curr
WHERE subject_id > ?
ORDER BY subject_id ASC
LIMIT ?
""",
}

_INSERT_EVENT_RANKS_QUERY: Final[str] = """
INSERT INTO nip85_event_ranks_curr (subject_id, raw_score, rank)
WITH
author_ranks AS (
    SELECT
        n.pubkey AS author_pubkey,
        CAST(
            ROUND(
                LEAST(
                    25 * LOG10((p.raw_score / (1.0 / pc.node_count)) + 1.0),
                    100.0
                )
            ) AS BIGINT
        ) AS author_rank
    FROM pagerank_curr AS p
    INNER JOIN pubkey_nodes AS n ON n.node_id = p.node_id
    CROSS JOIN (
        SELECT COUNT(*) AS node_count
        FROM pagerank_curr
    ) AS pc
    WHERE pc.node_count > 0
),
scored AS (
    SELECT
        s.event_id AS subject_id,
        (
            4.0 * LN(CAST(s.comment_count AS DOUBLE) + 1.0) +
            5.0 * LN(CAST(s.quote_count AS DOUBLE) + 1.0) +
            3.0 * LN(CAST(s.repost_count AS DOUBLE) + 1.0) +
            1.0 * LN(CAST(s.reaction_count AS DOUBLE) + 1.0) +
            3.0 * LN(CAST(s.zap_count AS DOUBLE) + 1.0) +
            2.0 * LN((CAST(s.zap_amount AS DOUBLE) / 1000.0) + 1.0)
        )
        * (0.5 + (0.5 * COALESCE(a.author_rank, 0) / 100.0)) AS raw_score
    FROM nip85_event_stats_stage AS s
    LEFT JOIN author_ranks AS a ON a.author_pubkey = s.author_pubkey
),
stats AS (
    SELECT AVG(CASE WHEN raw_score > 0.0 THEN raw_score END) AS avg_positive_raw
    FROM scored
)
SELECT
    scored.subject_id,
    scored.raw_score,
    CASE
        WHEN scored.raw_score <= 0.0 OR COALESCE(stats.avg_positive_raw, 0.0) <= 0.0 THEN 0
        ELSE CAST(
            ROUND(
                LEAST(25 * LOG10((scored.raw_score / stats.avg_positive_raw) + 1.0), 100.0)
            ) AS BIGINT
        )
    END AS rank
FROM scored
CROSS JOIN stats
ORDER BY scored.subject_id
"""

_INSERT_ADDRESSABLE_RANKS_QUERY: Final[str] = """
INSERT INTO nip85_addressable_ranks_curr (subject_id, raw_score, rank)
WITH
author_ranks AS (
    SELECT
        n.pubkey AS author_pubkey,
        CAST(
            ROUND(
                LEAST(
                    25 * LOG10((p.raw_score / (1.0 / pc.node_count)) + 1.0),
                    100.0
                )
            ) AS BIGINT
        ) AS author_rank
    FROM pagerank_curr AS p
    INNER JOIN pubkey_nodes AS n ON n.node_id = p.node_id
    CROSS JOIN (
        SELECT COUNT(*) AS node_count
        FROM pagerank_curr
    ) AS pc
    WHERE pc.node_count > 0
),
scored AS (
    SELECT
        s.event_address AS subject_id,
        (
            4.0 * LN(CAST(s.comment_count AS DOUBLE) + 1.0) +
            5.0 * LN(CAST(s.quote_count AS DOUBLE) + 1.0) +
            3.0 * LN(CAST(s.repost_count AS DOUBLE) + 1.0) +
            1.0 * LN(CAST(s.reaction_count AS DOUBLE) + 1.0) +
            3.0 * LN(CAST(s.zap_count AS DOUBLE) + 1.0) +
            2.0 * LN((CAST(s.zap_amount AS DOUBLE) / 1000.0) + 1.0)
        )
        * (0.5 + (0.5 * COALESCE(a.author_rank, 0) / 100.0)) AS raw_score
    FROM nip85_addressable_stats_stage AS s
    LEFT JOIN author_ranks AS a ON a.author_pubkey = s.author_pubkey
),
stats AS (
    SELECT AVG(CASE WHEN raw_score > 0.0 THEN raw_score END) AS avg_positive_raw
    FROM scored
)
SELECT
    scored.subject_id,
    scored.raw_score,
    CASE
        WHEN scored.raw_score <= 0.0 OR COALESCE(stats.avg_positive_raw, 0.0) <= 0.0 THEN 0
        ELSE CAST(
            ROUND(
                LEAST(25 * LOG10((scored.raw_score / stats.avg_positive_raw) + 1.0), 100.0)
            ) AS BIGINT
        )
    END AS rank
FROM scored
CROSS JOIN stats
ORDER BY scored.subject_id
"""

_INSERT_IDENTIFIER_RANKS_QUERY: Final[str] = """
INSERT INTO nip85_identifier_ranks_curr (subject_id, raw_score, rank)
WITH scored AS (
    SELECT
        s.identifier AS subject_id,
        (
            4.0 * LN(CAST(s.comment_count AS DOUBLE) + 1.0) +
            1.0 * LN(CAST(s.reaction_count AS DOUBLE) + 1.0)
        ) AS raw_score
    FROM nip85_identifier_stats_stage AS s
),
stats AS (
    SELECT AVG(CASE WHEN raw_score > 0.0 THEN raw_score END) AS avg_positive_raw
    FROM scored
)
SELECT
    scored.subject_id,
    scored.raw_score,
    CASE
        WHEN scored.raw_score <= 0.0 OR COALESCE(stats.avg_positive_raw, 0.0) <= 0.0 THEN 0
        ELSE CAST(
            ROUND(
                LEAST(25 * LOG10((scored.raw_score / stats.avg_positive_raw) + 1.0), 100.0)
            ) AS BIGINT
        )
    END AS rank
FROM scored
CROSS JOIN stats
ORDER BY scored.subject_id
"""
