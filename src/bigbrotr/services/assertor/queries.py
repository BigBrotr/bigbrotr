"""Database queries for the Assertor service.

Reads from NIP-85 summary tables to build assertion data. Each function
returns raw database rows that are converted to assertion models by the
service layer.

See Also:
    [Assertor][bigbrotr.services.assertor.Assertor]: Service that
        orchestrates these queries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from bigbrotr.core.brotr import Brotr


_USER_QUERY = """
SELECT
    n.pubkey,
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
WHERE ps.event_count >= $1
ORDER BY ps.event_count DESC
LIMIT $2
OFFSET $3
"""

_EVENT_QUERY = """
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
WHERE comment_count + quote_count + repost_count + reaction_count + zap_count > 0
ORDER BY comment_count + quote_count + repost_count + reaction_count + zap_count DESC
LIMIT $1
OFFSET $2
"""


async def fetch_user_rows(
    brotr: Brotr,
    min_events: int,
    limit: int,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Fetch pubkey assertion data from nip85_pubkey_stats joined with pubkey_stats."""
    rows = await brotr.fetch(_USER_QUERY, min_events, limit, offset)
    return [dict(row) for row in rows]


async def fetch_event_rows(
    brotr: Brotr,
    limit: int,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Fetch event assertion data from nip85_event_stats."""
    rows = await brotr.fetch(_EVENT_QUERY, limit, offset)
    return [dict(row) for row in rows]
