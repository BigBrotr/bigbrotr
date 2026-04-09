"""Database queries for the refresher service.

Summary table refresh queries. Each function wraps a stored procedure call
that processes a source-specific watermark range. Most summaries use
``event_relay.seen_at``; relay metadata current-state uses
``relay_metadata.generated_at``.

See Also:
    [Refresher][bigbrotr.services.refresher.Refresher]: Service that
        orchestrates these queries.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from bigbrotr.core.brotr import Brotr


async def get_max_seen_at(brotr: Brotr, after: int) -> int:
    """Return the wall-clock timestamp if new ``event_relay`` rows exist after checkpoint.

    Uses wall-clock time (not ``MAX(seen_at)``) as the upper bound to prevent
    the TOCTOU race where rows with ``seen_at`` equal to the previous checkpoint
    arrive after the checkpoint was saved. Since ``EventRelay.seen_at`` defaults
    to ``int(time.time())`` at insert time, it is always ``<=`` wall-clock, so
    the range ``(after, wall_clock]`` captures all visible rows.

    Returns ``after`` unchanged if no newer rows exist (caller should skip
    refresh).
    """
    exists = await brotr.fetchval(
        "SELECT EXISTS(SELECT 1 FROM event_relay WHERE seen_at > $1)",
        after,
    )
    if not exists:
        return after
    return int(time.time())


async def get_max_generated_at(brotr: Brotr, after: int) -> int:
    """Return wall-clock timestamp if newer ``relay_metadata`` rows exist."""
    exists = await brotr.fetchval(
        "SELECT EXISTS(SELECT 1 FROM relay_metadata WHERE generated_at > $1)",
        after,
    )
    if not exists:
        return after
    return int(time.time())


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
    """Recompute NIP-85 follower/following counts from canonical contact-list facts."""
    await brotr.execute("SELECT nip85_follower_count_refresh()")
