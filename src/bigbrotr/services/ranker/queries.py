"""Database queries for the ranker service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING


if TYPE_CHECKING:
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
