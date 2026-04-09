"""Database queries for the ranker service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    import asyncpg

    from bigbrotr.core.brotr import Brotr


@dataclass(frozen=True, slots=True)
class GraphSyncCheckpoint:
    """Lexicographic checkpoint for canonical follow-graph sync."""

    source_seen_at: int = 0
    follower_pubkey: str = ""


@dataclass(frozen=True, slots=True)
class ContactListFact:
    """One changed follower row from ``contact_lists_current``."""

    follower_pubkey: str
    source_event_id: str
    source_created_at: int
    source_seen_at: int
    follow_count: int


@dataclass(frozen=True, slots=True)
class FollowEdgeFact:
    """One current follow edge from ``contact_list_edges_current``."""

    follower_pubkey: str
    followed_pubkey: str
    source_event_id: str
    source_created_at: int
    source_seen_at: int


@dataclass(frozen=True, slots=True)
class PubkeyRankExportRow:
    """One final pubkey rank row to snapshot-export into PostgreSQL."""

    subject_id: str
    raw_score: float
    rank: int


_CHANGED_CONTACT_LISTS_QUERY = """
SELECT
    follower_pubkey,
    source_event_id,
    source_created_at,
    source_seen_at,
    follow_count
FROM contact_lists_current
WHERE source_seen_at > $1
   OR (source_seen_at = $1 AND follower_pubkey > $2)
ORDER BY source_seen_at ASC, follower_pubkey ASC
LIMIT $3
"""

_FOLLOW_EDGES_QUERY = """
SELECT
    follower_pubkey,
    followed_pubkey,
    source_event_id,
    source_created_at,
    source_seen_at
FROM contact_list_edges_current
WHERE follower_pubkey = ANY($1::TEXT[])
ORDER BY follower_pubkey ASC, followed_pubkey ASC
"""

_CREATE_PUBKEY_RANK_STAGE_QUERY = """
CREATE TEMP TABLE ranker_pubkey_ranks_stage (
    subject_id TEXT PRIMARY KEY,
    raw_score DOUBLE PRECISION NOT NULL,
    rank INTEGER NOT NULL,
    computed_at BIGINT NOT NULL
) ON COMMIT DROP
"""

_INSERT_PUBKEY_RANK_STAGE_QUERY = """
INSERT INTO ranker_pubkey_ranks_stage (subject_id, raw_score, rank, computed_at)
SELECT
    t.subject_id,
    t.raw_score,
    t.rank,
    $4
FROM UNNEST($1::TEXT[], $2::DOUBLE PRECISION[], $3::INTEGER[]) AS t(subject_id, raw_score, rank)
"""

_DELETE_OBSOLETE_PUBKEY_RANKS_QUERY = """
DELETE FROM nip85_pubkey_ranks AS r
WHERE r.algorithm_id = $1
  AND NOT EXISTS (
      SELECT 1
      FROM ranker_pubkey_ranks_stage AS s
      WHERE s.subject_id = r.subject_id
  )
"""

_UPSERT_PUBKEY_RANKS_QUERY = """
INSERT INTO nip85_pubkey_ranks (algorithm_id, subject_id, raw_score, rank, computed_at)
SELECT
    $1,
    s.subject_id,
    s.raw_score,
    s.rank,
    s.computed_at
FROM ranker_pubkey_ranks_stage AS s
ON CONFLICT (algorithm_id, subject_id) DO UPDATE SET
    raw_score = EXCLUDED.raw_score,
    rank = EXCLUDED.rank,
    computed_at = EXCLUDED.computed_at
"""


async def fetch_changed_contact_lists(
    brotr: Brotr,
    checkpoint: GraphSyncCheckpoint,
    limit: int,
) -> list[ContactListFact]:
    """Fetch changed followers after the last lexicographic checkpoint."""
    rows = await brotr.fetch(
        _CHANGED_CONTACT_LISTS_QUERY,
        checkpoint.source_seen_at,
        checkpoint.follower_pubkey,
        limit,
    )
    return [
        ContactListFact(
            follower_pubkey=str(row["follower_pubkey"]),
            source_event_id=str(row["source_event_id"]),
            source_created_at=int(row["source_created_at"]),
            source_seen_at=int(row["source_seen_at"]),
            follow_count=int(row["follow_count"]),
        )
        for row in rows
    ]


async def fetch_follow_edges_for_followers(
    brotr: Brotr,
    follower_pubkeys: list[str],
) -> list[FollowEdgeFact]:
    """Fetch the full current edge set for the given followers."""
    if not follower_pubkeys:
        return []

    rows = await brotr.fetch(_FOLLOW_EDGES_QUERY, follower_pubkeys)
    return [
        FollowEdgeFact(
            follower_pubkey=str(row["follower_pubkey"]),
            followed_pubkey=str(row["followed_pubkey"]),
            source_event_id=str(row["source_event_id"]),
            source_created_at=int(row["source_created_at"]),
            source_seen_at=int(row["source_seen_at"]),
        )
        for row in rows
    ]


async def create_pubkey_rank_stage(
    conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    """Create the per-transaction temp stage table for pubkey rank export."""
    await conn.execute(_CREATE_PUBKEY_RANK_STAGE_QUERY)


async def insert_pubkey_rank_stage_batch(
    conn: asyncpg.Connection[asyncpg.Record],
    rows: list[PubkeyRankExportRow],
    computed_at: int,
) -> None:
    """Insert one pubkey-rank batch into the temp stage table."""
    if not rows:
        return

    await conn.execute(
        _INSERT_PUBKEY_RANK_STAGE_QUERY,
        [row.subject_id for row in rows],
        [row.raw_score for row in rows],
        [row.rank for row in rows],
        computed_at,
    )


async def merge_pubkey_rank_stage(
    conn: asyncpg.Connection[asyncpg.Record],
    algorithm_id: str,
) -> None:
    """Replace the PostgreSQL pubkey-rank snapshot for one algorithm."""
    await conn.execute(_DELETE_OBSOLETE_PUBKEY_RANKS_QUERY, algorithm_id)
    await conn.execute(_UPSERT_PUBKEY_RANKS_QUERY, algorithm_id)
