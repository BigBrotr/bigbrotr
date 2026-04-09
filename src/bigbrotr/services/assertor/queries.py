"""Database queries for the Assertor service.

Reads from NIP-85 facts tables joined with rank snapshots for a specific
``algorithm_id``. The assertor stays a pure publish-layer: it only publishes
subjects that both have facts and an exported rank.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from bigbrotr.core.brotr import Brotr


_USER_QUERY = """
SELECT
    n.pubkey,
    r.rank,
    n.post_count,
    n.reply_count,
    n.reaction_count_sent,
    n.reaction_count_recd,
    n.repost_count_sent,
    n.repost_count_recd,
    n.report_count_sent,
    n.report_count_recd,
    n.zap_count_sent,
    n.zap_count_recd,
    n.zap_amount_sent,
    n.zap_amount_recd,
    n.first_created_at,
    n.activity_hours,
    n.topic_counts,
    n.follower_count,
    n.following_count,
    ps.last_event_at
FROM nip85_pubkey_stats AS n
INNER JOIN pubkey_stats AS ps ON n.pubkey = ps.pubkey
INNER JOIN nip85_pubkey_ranks AS r
    ON r.subject_id = n.pubkey
   AND r.algorithm_id = $1
WHERE ps.event_count >= $2
ORDER BY n.pubkey ASC
LIMIT $3
OFFSET $4
"""

_EVENT_QUERY = """
SELECT
    s.event_id,
    s.author_pubkey,
    r.rank,
    s.comment_count,
    s.quote_count,
    s.repost_count,
    s.reaction_count,
    s.zap_count,
    s.zap_amount
FROM nip85_event_stats AS s
INNER JOIN nip85_event_ranks AS r
    ON r.subject_id = s.event_id
   AND r.algorithm_id = $1
WHERE s.comment_count + s.quote_count + s.repost_count + s.reaction_count + s.zap_count > 0
ORDER BY s.event_id ASC
LIMIT $2
OFFSET $3
"""

_ADDRESSABLE_QUERY = """
SELECT
    s.event_address,
    s.author_pubkey,
    r.rank,
    s.comment_count,
    s.quote_count,
    s.repost_count,
    s.reaction_count,
    s.zap_count,
    s.zap_amount
FROM nip85_addressable_stats AS s
INNER JOIN nip85_addressable_ranks AS r
    ON r.subject_id = s.event_address
   AND r.algorithm_id = $1
WHERE s.comment_count + s.quote_count + s.repost_count + s.reaction_count + s.zap_count > 0
ORDER BY s.event_address ASC
LIMIT $2
OFFSET $3
"""

_IDENTIFIER_QUERY = """
SELECT
    s.identifier,
    r.rank,
    s.comment_count,
    s.reaction_count,
    s.k_tags
FROM nip85_identifier_stats AS s
INNER JOIN nip85_identifier_ranks AS r
    ON r.subject_id = s.identifier
   AND r.algorithm_id = $1
WHERE s.comment_count + s.reaction_count > 0
ORDER BY s.identifier ASC
LIMIT $2
OFFSET $3
"""


async def fetch_user_rows(
    brotr: Brotr,
    algorithm_id: str,
    min_events: int,
    limit: int,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Fetch ranked user assertion rows joined with the user rank snapshot."""
    rows = await brotr.fetch(_USER_QUERY, algorithm_id, min_events, limit, offset)
    return [dict(row) for row in rows]


async def fetch_event_rows(
    brotr: Brotr,
    algorithm_id: str,
    limit: int,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Fetch ranked event assertion rows joined with the event rank snapshot."""
    rows = await brotr.fetch(_EVENT_QUERY, algorithm_id, limit, offset)
    return [dict(row) for row in rows]


async def fetch_addressable_rows(
    brotr: Brotr,
    algorithm_id: str,
    limit: int,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Fetch ranked addressable assertion rows joined with the address rank snapshot."""
    rows = await brotr.fetch(_ADDRESSABLE_QUERY, algorithm_id, limit, offset)
    return [dict(row) for row in rows]


async def fetch_identifier_rows(
    brotr: Brotr,
    algorithm_id: str,
    limit: int,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Fetch ranked identifier assertion rows joined with the identifier rank snapshot."""
    rows = await brotr.fetch(_IDENTIFIER_QUERY, algorithm_id, limit, offset)
    return [dict(row) for row in rows]
