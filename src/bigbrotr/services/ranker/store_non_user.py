"""Non-user staging/export helpers behind the ranker's private DuckDB store."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from .queries import AddressableStatFact, EventStatFact, IdentifierStatFact, RankExportRow


if TYPE_CHECKING:
    import duckdb


def clear_non_user_stats_stage(conn: duckdb.DuckDBPyConnection) -> None:
    """Reset the staged non-user facts loaded from PostgreSQL."""
    try:
        conn.execute("BEGIN TRANSACTION")
        conn.execute("DELETE FROM nip85_event_stats_stage")
        conn.execute("DELETE FROM nip85_addressable_stats_stage")
        conn.execute("DELETE FROM nip85_identifier_stats_stage")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def append_event_stats_stage_batch(
    conn: duckdb.DuckDBPyConnection,
    rows: list[EventStatFact],
) -> None:
    """Append one PostgreSQL batch into the local event-facts stage table."""
    if not rows:
        return

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


def append_addressable_stats_stage_batch(
    conn: duckdb.DuckDBPyConnection,
    rows: list[AddressableStatFact],
) -> None:
    """Append one PostgreSQL batch into the local addressable-facts stage table."""
    if not rows:
        return

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


def append_identifier_stats_stage_batch(
    conn: duckdb.DuckDBPyConnection,
    rows: list[IdentifierStatFact],
) -> None:
    """Append one PostgreSQL batch into the local identifier-facts stage table."""
    if not rows:
        return

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


def compute_non_user_ranks(conn: duckdb.DuckDBPyConnection) -> None:
    """Compute final 30383/30384/30385 ranks from the staged facts tables."""
    try:
        conn.execute("BEGIN TRANSACTION")
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


def fetch_rank_batch(
    conn: duckdb.DuckDBPyConnection,
    *,
    table_name: str,
    after_subject_id: str,
    limit: int,
) -> list[RankExportRow]:
    """Fetch one deterministic export batch from one non-user rank snapshot."""
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
