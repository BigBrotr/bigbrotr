"""Database queries for the ranker service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal


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
class EventStatFact:
    """One event-engagement fact row loaded from ``nip85_event_stats``."""

    event_id: str
    author_pubkey: str
    comment_count: int
    quote_count: int
    repost_count: int
    reaction_count: int
    zap_count: int
    zap_amount: int


@dataclass(frozen=True, slots=True)
class AddressableStatFact:
    """One addressable-event fact row loaded from ``nip85_addressable_stats``."""

    event_address: str
    author_pubkey: str
    comment_count: int
    quote_count: int
    repost_count: int
    reaction_count: int
    zap_count: int
    zap_amount: int


@dataclass(frozen=True, slots=True)
class IdentifierStatFact:
    """One identifier-engagement fact row loaded from ``nip85_identifier_stats``."""

    identifier: str
    comment_count: int
    reaction_count: int
    k_tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RankExportRow:
    """One final rank row to snapshot-export into PostgreSQL."""

    subject_id: str
    raw_score: float
    rank: int


RankSubjectType = Literal["pubkey", "event", "addressable", "identifier"]


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

_CONTACT_LIST_SOURCE_WATERMARK_QUERY = """
SELECT COALESCE(MAX(source_seen_at), 0)
FROM contact_lists_current
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

_EVENT_STATS_QUERY = """
SELECT
    event_id,
    author_pubkey,
    comment_count,
    quote_count,
    repost_count,
    reaction_count,
    zap_count,
    zap_amount
FROM nip85_event_stats
WHERE event_id > $1
ORDER BY event_id ASC
LIMIT $2
"""

_ADDRESSABLE_STATS_QUERY = """
SELECT
    event_address,
    author_pubkey,
    comment_count,
    quote_count,
    repost_count,
    reaction_count,
    zap_count,
    zap_amount
FROM nip85_addressable_stats
WHERE event_address > $1
ORDER BY event_address ASC
LIMIT $2
"""

_IDENTIFIER_STATS_QUERY = """
SELECT
    identifier,
    comment_count,
    reaction_count,
    k_tags
FROM nip85_identifier_stats
WHERE identifier > $1
ORDER BY identifier ASC
LIMIT $2
"""

_STAGE_TABLE_NAMES: Final[dict[RankSubjectType, str]] = {
    "pubkey": "ranker_pubkey_ranks_stage",
    "event": "ranker_event_ranks_stage",
    "addressable": "ranker_addressable_ranks_stage",
    "identifier": "ranker_identifier_ranks_stage",
}

_TARGET_TABLE_NAMES: Final[dict[RankSubjectType, str]] = {
    "pubkey": "nip85_pubkey_ranks",
    "event": "nip85_event_ranks",
    "addressable": "nip85_addressable_ranks",
    "identifier": "nip85_identifier_ranks",
}

_CREATE_PUBKEY_RANK_STAGE_QUERY = """
CREATE TEMP TABLE ranker_pubkey_ranks_stage (
    subject_id TEXT PRIMARY KEY,
    raw_score DOUBLE PRECISION NOT NULL,
    rank INTEGER NOT NULL,
    computed_at BIGINT NOT NULL
) ON COMMIT DROP
"""

_CREATE_EVENT_RANK_STAGE_QUERY = """
CREATE TEMP TABLE ranker_event_ranks_stage (
    subject_id TEXT PRIMARY KEY,
    raw_score DOUBLE PRECISION NOT NULL,
    rank INTEGER NOT NULL,
    computed_at BIGINT NOT NULL
) ON COMMIT DROP
"""

_CREATE_ADDRESSABLE_RANK_STAGE_QUERY = """
CREATE TEMP TABLE ranker_addressable_ranks_stage (
    subject_id TEXT PRIMARY KEY,
    raw_score DOUBLE PRECISION NOT NULL,
    rank INTEGER NOT NULL,
    computed_at BIGINT NOT NULL
) ON COMMIT DROP
"""

_CREATE_IDENTIFIER_RANK_STAGE_QUERY = """
CREATE TEMP TABLE ranker_identifier_ranks_stage (
    subject_id TEXT PRIMARY KEY,
    raw_score DOUBLE PRECISION NOT NULL,
    rank INTEGER NOT NULL,
    computed_at BIGINT NOT NULL
) ON COMMIT DROP
"""

_CREATE_RANK_STAGE_QUERIES: Final[dict[RankSubjectType, str]] = {
    "pubkey": _CREATE_PUBKEY_RANK_STAGE_QUERY,
    "event": _CREATE_EVENT_RANK_STAGE_QUERY,
    "addressable": _CREATE_ADDRESSABLE_RANK_STAGE_QUERY,
    "identifier": _CREATE_IDENTIFIER_RANK_STAGE_QUERY,
}

_INSERT_PUBKEY_RANK_STAGE_QUERY = """
INSERT INTO ranker_pubkey_ranks_stage (subject_id, raw_score, rank, computed_at)
SELECT
    t.subject_id,
    t.raw_score,
    t.rank,
    $4
FROM UNNEST($1::TEXT[], $2::DOUBLE PRECISION[], $3::INTEGER[]) AS t(subject_id, raw_score, rank)
"""

_INSERT_EVENT_RANK_STAGE_QUERY = """
INSERT INTO ranker_event_ranks_stage (subject_id, raw_score, rank, computed_at)
SELECT
    t.subject_id,
    t.raw_score,
    t.rank,
    $4
FROM UNNEST($1::TEXT[], $2::DOUBLE PRECISION[], $3::INTEGER[]) AS t(subject_id, raw_score, rank)
"""

_INSERT_ADDRESSABLE_RANK_STAGE_QUERY = """
INSERT INTO ranker_addressable_ranks_stage (subject_id, raw_score, rank, computed_at)
SELECT
    t.subject_id,
    t.raw_score,
    t.rank,
    $4
FROM UNNEST($1::TEXT[], $2::DOUBLE PRECISION[], $3::INTEGER[]) AS t(subject_id, raw_score, rank)
"""

_INSERT_IDENTIFIER_RANK_STAGE_QUERY = """
INSERT INTO ranker_identifier_ranks_stage (subject_id, raw_score, rank, computed_at)
SELECT
    t.subject_id,
    t.raw_score,
    t.rank,
    $4
FROM UNNEST($1::TEXT[], $2::DOUBLE PRECISION[], $3::INTEGER[]) AS t(subject_id, raw_score, rank)
"""

_INSERT_RANK_STAGE_QUERIES: Final[dict[RankSubjectType, str]] = {
    "pubkey": _INSERT_PUBKEY_RANK_STAGE_QUERY,
    "event": _INSERT_EVENT_RANK_STAGE_QUERY,
    "addressable": _INSERT_ADDRESSABLE_RANK_STAGE_QUERY,
    "identifier": _INSERT_IDENTIFIER_RANK_STAGE_QUERY,
}

_DELETE_OBSOLETE_PUBKEY_RANKS_QUERY = """
DELETE FROM nip85_pubkey_ranks AS r
WHERE r.algorithm_id = $1
  AND NOT EXISTS (
      SELECT 1
      FROM ranker_pubkey_ranks_stage AS s
      WHERE s.subject_id = r.subject_id
  )
"""

_DELETE_OBSOLETE_EVENT_RANKS_QUERY = """
DELETE FROM nip85_event_ranks AS r
WHERE r.algorithm_id = $1
  AND NOT EXISTS (
      SELECT 1
      FROM ranker_event_ranks_stage AS s
      WHERE s.subject_id = r.subject_id
  )
"""

_DELETE_OBSOLETE_ADDRESSABLE_RANKS_QUERY = """
DELETE FROM nip85_addressable_ranks AS r
WHERE r.algorithm_id = $1
  AND NOT EXISTS (
      SELECT 1
      FROM ranker_addressable_ranks_stage AS s
      WHERE s.subject_id = r.subject_id
  )
"""

_DELETE_OBSOLETE_IDENTIFIER_RANKS_QUERY = """
DELETE FROM nip85_identifier_ranks AS r
WHERE r.algorithm_id = $1
  AND NOT EXISTS (
      SELECT 1
      FROM ranker_identifier_ranks_stage AS s
      WHERE s.subject_id = r.subject_id
  )
"""

_DELETE_OBSOLETE_RANKS_QUERIES: Final[dict[RankSubjectType, str]] = {
    "pubkey": _DELETE_OBSOLETE_PUBKEY_RANKS_QUERY,
    "event": _DELETE_OBSOLETE_EVENT_RANKS_QUERY,
    "addressable": _DELETE_OBSOLETE_ADDRESSABLE_RANKS_QUERY,
    "identifier": _DELETE_OBSOLETE_IDENTIFIER_RANKS_QUERY,
}

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

_UPSERT_EVENT_RANKS_QUERY = """
INSERT INTO nip85_event_ranks (algorithm_id, subject_id, raw_score, rank, computed_at)
SELECT
    $1,
    s.subject_id,
    s.raw_score,
    s.rank,
    s.computed_at
FROM ranker_event_ranks_stage AS s
ON CONFLICT (algorithm_id, subject_id) DO UPDATE SET
    raw_score = EXCLUDED.raw_score,
    rank = EXCLUDED.rank,
    computed_at = EXCLUDED.computed_at
"""

_UPSERT_ADDRESSABLE_RANKS_QUERY = """
INSERT INTO nip85_addressable_ranks (algorithm_id, subject_id, raw_score, rank, computed_at)
SELECT
    $1,
    s.subject_id,
    s.raw_score,
    s.rank,
    s.computed_at
FROM ranker_addressable_ranks_stage AS s
ON CONFLICT (algorithm_id, subject_id) DO UPDATE SET
    raw_score = EXCLUDED.raw_score,
    rank = EXCLUDED.rank,
    computed_at = EXCLUDED.computed_at
"""

_UPSERT_IDENTIFIER_RANKS_QUERY = """
INSERT INTO nip85_identifier_ranks (algorithm_id, subject_id, raw_score, rank, computed_at)
SELECT
    $1,
    s.subject_id,
    s.raw_score,
    s.rank,
    s.computed_at
FROM ranker_identifier_ranks_stage AS s
ON CONFLICT (algorithm_id, subject_id) DO UPDATE SET
    raw_score = EXCLUDED.raw_score,
    rank = EXCLUDED.rank,
    computed_at = EXCLUDED.computed_at
"""

_UPSERT_RANKS_QUERIES: Final[dict[RankSubjectType, str]] = {
    "pubkey": _UPSERT_PUBKEY_RANKS_QUERY,
    "event": _UPSERT_EVENT_RANKS_QUERY,
    "addressable": _UPSERT_ADDRESSABLE_RANKS_QUERY,
    "identifier": _UPSERT_IDENTIFIER_RANKS_QUERY,
}


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


async def get_contact_list_source_watermark(brotr: Brotr) -> int:
    """Return the latest visible ``contact_lists_current.source_seen_at`` watermark."""
    result = await brotr.fetchval(_CONTACT_LIST_SOURCE_WATERMARK_QUERY)
    return int(result) if result else 0


async def fetch_event_stats(
    brotr: Brotr,
    after_event_id: str,
    limit: int,
) -> list[EventStatFact]:
    """Fetch one deterministic batch from ``nip85_event_stats``."""
    rows = await brotr.fetch(_EVENT_STATS_QUERY, after_event_id, limit)
    return [
        EventStatFact(
            event_id=str(row["event_id"]),
            author_pubkey=str(row["author_pubkey"]),
            comment_count=int(row["comment_count"]),
            quote_count=int(row["quote_count"]),
            repost_count=int(row["repost_count"]),
            reaction_count=int(row["reaction_count"]),
            zap_count=int(row["zap_count"]),
            zap_amount=int(row["zap_amount"]),
        )
        for row in rows
    ]


async def fetch_addressable_stats(
    brotr: Brotr,
    after_event_address: str,
    limit: int,
) -> list[AddressableStatFact]:
    """Fetch one deterministic batch from ``nip85_addressable_stats``."""
    rows = await brotr.fetch(_ADDRESSABLE_STATS_QUERY, after_event_address, limit)
    return [
        AddressableStatFact(
            event_address=str(row["event_address"]),
            author_pubkey=str(row["author_pubkey"]),
            comment_count=int(row["comment_count"]),
            quote_count=int(row["quote_count"]),
            repost_count=int(row["repost_count"]),
            reaction_count=int(row["reaction_count"]),
            zap_count=int(row["zap_count"]),
            zap_amount=int(row["zap_amount"]),
        )
        for row in rows
    ]


async def fetch_identifier_stats(
    brotr: Brotr,
    after_identifier: str,
    limit: int,
) -> list[IdentifierStatFact]:
    """Fetch one deterministic batch from ``nip85_identifier_stats``."""
    rows = await brotr.fetch(_IDENTIFIER_STATS_QUERY, after_identifier, limit)
    return [
        IdentifierStatFact(
            identifier=str(row["identifier"]),
            comment_count=int(row["comment_count"]),
            reaction_count=int(row["reaction_count"]),
            k_tags=tuple(str(tag) for tag in (row["k_tags"] or [])),
        )
        for row in rows
    ]


async def create_rank_stages(
    conn: asyncpg.Connection[asyncpg.Record],
) -> None:
    """Create all per-transaction temp stage tables for rank export."""
    for subject_type in _STAGE_TABLE_NAMES:
        await conn.execute(_CREATE_RANK_STAGE_QUERIES[subject_type])


async def insert_rank_stage_batch(
    conn: asyncpg.Connection[asyncpg.Record],
    subject_type: RankSubjectType,
    rows: list[RankExportRow],
    computed_at: int,
) -> None:
    """Insert one rank batch into the temp stage table for one subject type."""
    if not rows:
        return

    await conn.execute(
        _INSERT_RANK_STAGE_QUERIES[subject_type],
        [row.subject_id for row in rows],
        [row.raw_score for row in rows],
        [row.rank for row in rows],
        computed_at,
    )


async def merge_rank_stage(
    conn: asyncpg.Connection[asyncpg.Record],
    subject_type: RankSubjectType,
    algorithm_id: str,
) -> None:
    """Replace one PostgreSQL rank snapshot for a single subject type."""
    await conn.execute(_DELETE_OBSOLETE_RANKS_QUERIES[subject_type], algorithm_id)
    await conn.execute(_UPSERT_RANKS_QUERIES[subject_type], algorithm_id)
