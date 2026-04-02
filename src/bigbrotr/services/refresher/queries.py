"""Database queries for the refresher service.

Summary table refresh queries. Each function wraps a stored procedure call
that processes a (after, until] range of ``event_relay.seen_at`` timestamps.

See Also:
    [Refresher][bigbrotr.services.refresher.Refresher]: Service that
        orchestrates these queries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from bigbrotr.core.brotr import Brotr


async def get_max_seen_at(brotr: Brotr, after: int) -> int:
    """Return the maximum ``event_relay.seen_at`` after the given timestamp.

    Returns ``after`` if no newer rows exist (caller should skip refresh).
    """
    result = await brotr.fetchval(
        "SELECT COALESCE(MAX(seen_at), $1) FROM event_relay WHERE seen_at > $1",
        after,
    )
    return int(result)


async def refresh_summary(brotr: Brotr, table: str, after: int, until: int) -> int:
    """Call ``{table}_refresh(after, until)`` and return rows affected.

    The table name is validated by the caller's config regex.
    """
    result = await brotr.fetchval(
        f"SELECT {table}_refresh($1::BIGINT, $2::BIGINT)",
        after,
        until,
    )
    return int(result) if result else 0


async def refresh_rolling_windows(brotr: Brotr) -> None:
    """Recompute rolling time-window columns for all entity summary tables."""
    await brotr.execute("SELECT rolling_windows_refresh()")


async def refresh_relay_metadata(brotr: Brotr) -> None:
    """Update RTT, NIP-11, network, and discovered_at in relay_stats."""
    await brotr.execute("SELECT relay_stats_metadata_refresh()")


async def refresh_nip85_followers(brotr: Brotr) -> None:
    """Recompute NIP-85 follower counts from latest contact lists."""
    await brotr.execute("SELECT nip85_follower_count_refresh()")
