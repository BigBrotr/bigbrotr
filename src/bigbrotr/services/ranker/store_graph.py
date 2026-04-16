"""Graph/checkpoint primitives behind the ranker's private DuckDB store."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from .queries import ContactListFact, FollowEdgeFact, GraphSyncCheckpoint, RankExportRow


if TYPE_CHECKING:
    from pathlib import Path

    import duckdb


_DEFAULT_CHECKPOINT: Final[GraphSyncCheckpoint] = GraphSyncCheckpoint()
_GRAPH_CHECKPOINT_NAME: Final[str] = "graph"


@dataclass(frozen=True, slots=True)
class GraphStats:
    """Current follow-graph size in DuckDB."""

    node_count: int
    edge_count: int


def load_checkpoint_from_db(conn: duckdb.DuckDBPyConnection) -> GraphSyncCheckpoint | None:
    """Read the canonical graph-sync checkpoint row from DuckDB."""
    row = conn.execute(
        """
        SELECT source_seen_at, follower_pubkey
        FROM graph_sync_checkpoint
        WHERE checkpoint_name = ?
        """,
        [_GRAPH_CHECKPOINT_NAME],
    ).fetchone()
    if row is None:
        return None
    return GraphSyncCheckpoint(
        source_seen_at=int(row[0]),
        follower_pubkey=str(row[1]),
    )


def load_legacy_checkpoint(checkpoint_path: Path) -> GraphSyncCheckpoint:
    """Import the legacy JSON checkpoint format when it still exists on disk."""
    if not checkpoint_path.exists():
        return _DEFAULT_CHECKPOINT

    raw = json.loads(checkpoint_path.read_text())
    graph = raw.get("graph", {})
    return GraphSyncCheckpoint(
        source_seen_at=int(graph.get("source_seen_at", 0)),
        follower_pubkey=str(graph.get("follower_pubkey", "")),
    )


def upsert_checkpoint(
    conn: duckdb.DuckDBPyConnection,
    checkpoint: GraphSyncCheckpoint,
) -> None:
    """Persist the canonical graph-sync checkpoint row."""
    conn.execute(
        """
        INSERT INTO graph_sync_checkpoint (
            checkpoint_name,
            source_seen_at,
            follower_pubkey
        ) VALUES (?, ?, ?)
        ON CONFLICT (checkpoint_name) DO UPDATE SET
            source_seen_at = excluded.source_seen_at,
            follower_pubkey = excluded.follower_pubkey
        """,
        [
            _GRAPH_CHECKPOINT_NAME,
            checkpoint.source_seen_at,
            checkpoint.follower_pubkey,
        ],
    )


def ensure_node_ids(
    conn: duckdb.DuckDBPyConnection,
    pubkeys: list[str],
) -> dict[str, int]:
    """Return node ids for pubkeys, inserting any missing nodes first."""
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


def delete_followers(
    conn: duckdb.DuckDBPyConnection,
    follower_node_ids: list[int],
) -> None:
    """Delete all current edges/contact-lists owned by the provided followers."""
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


def apply_follow_graph_delta(
    conn: duckdb.DuckDBPyConnection,
    *,
    changed_lists: list[ContactListFact],
    edges: list[FollowEdgeFact],
    checkpoint: GraphSyncCheckpoint,
) -> None:
    """Apply one incremental follow-graph batch and persist the checkpoint."""
    if not changed_lists:
        upsert_checkpoint(conn, checkpoint)
        return

    pubkeys = (
        {fact.follower_pubkey for fact in changed_lists}
        | {fact.follower_pubkey for fact in edges}
        | {fact.followed_pubkey for fact in edges}
    )

    try:
        conn.execute("BEGIN TRANSACTION")
        node_ids = ensure_node_ids(conn, sorted(pubkeys))
        follower_node_ids = [node_ids[fact.follower_pubkey] for fact in changed_lists]

        delete_followers(conn, follower_node_ids)

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

        upsert_checkpoint(conn, checkpoint)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def get_graph_stats(conn: duckdb.DuckDBPyConnection) -> GraphStats:
    """Return node/edge counts over the current active follow graph."""
    node_count_row = conn.execute(_ACTIVE_NODE_COUNT_QUERY).fetchone()
    edge_count_row = conn.execute(_ACTIVE_EDGE_COUNT_QUERY).fetchone()

    node_count = int(node_count_row[0]) if node_count_row is not None else 0
    edge_count = int(edge_count_row[0]) if edge_count_row is not None else 0

    return GraphStats(node_count=node_count, edge_count=edge_count)


def get_graph_stats_for_ranking(
    conn: duckdb.DuckDBPyConnection,
    *,
    ignore_self_follows: bool,
) -> GraphStats:
    """Return node/edge counts for the effective PageRank edge set."""
    edge_query = (
        _ACTIVE_EDGE_COUNT_NO_SELF_QUERY if ignore_self_follows else _ACTIVE_EDGE_COUNT_QUERY
    )

    node_count_row = conn.execute(_ACTIVE_NODE_COUNT_QUERY).fetchone()
    edge_count_row = conn.execute(edge_query).fetchone()

    node_count = int(node_count_row[0]) if node_count_row is not None else 0
    edge_count = int(edge_count_row[0]) if edge_count_row is not None else 0

    return GraphStats(node_count=node_count, edge_count=edge_count)


def compute_pubkey_pagerank(
    conn: duckdb.DuckDBPyConnection,
    *,
    damping: float,
    iterations: int,
    ignore_self_follows: bool,
) -> None:
    """Compute deterministic PageRank over the current canonical follow graph."""
    edge_filter = "WHERE follower_node_id <> followed_node_id" if ignore_self_follows else ""

    try:
        conn.execute("BEGIN TRANSACTION")
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
    conn: duckdb.DuckDBPyConnection,
    *,
    after_subject_id: str,
    limit: int,
) -> list[RankExportRow]:
    """Fetch one deterministic export batch from the final PageRank snapshot."""
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
