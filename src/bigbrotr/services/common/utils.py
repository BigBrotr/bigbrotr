"""Shared utility functions for BigBrotr services.

Provides lightweight helpers used across multiple services. Domain-specific
logic belongs in per-service ``utils.py`` modules; only truly shared
primitives live here.

See Also:
    [configs][bigbrotr.services.common.configs]: Shared Pydantic network
        configuration models.
    [queries][bigbrotr.services.common.queries]: Centralized SQL query
        functions.
    [mixins][bigbrotr.services.common.mixins]: Reusable service mixin
        classes.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, TypeVar

from bigbrotr.models import Relay
from bigbrotr.models.relay_url import normalize_relay_url


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from bigbrotr.core.brotr import Brotr


logger = logging.getLogger(__name__)
_T = TypeVar("_T")


def batch_size_for(brotr: object, record_count: int) -> int:
    """Return the configured batch size, or a safe fallback for lightweight test doubles."""
    batch_config = getattr(getattr(brotr, "config", None), "batch", None)
    max_size = getattr(batch_config, "max_size", None)
    if isinstance(max_size, int) and max_size > 0:
        return max_size
    return max(record_count, 1)


async def batched_insert(
    brotr: Brotr,
    records: list[_T],
    method: Callable[[list[_T]], Awaitable[int]],
) -> int:
    """Split ``records`` into ``batch.max_size`` chunks and sum the inserted count."""
    if not records:
        return 0
    total = 0
    batch_size = batch_size_for(brotr, len(records))
    for i in range(0, len(records), batch_size):
        total += await method(records[i : i + batch_size])
    return total


def parse_relay(
    url: str,
    discovered_at: int | None = None,
    *,
    allow_local: bool = False,
) -> Relay | None:
    """Parse a relay URL string into a Relay object.

    Strips whitespace, rejects empty/non-string input, and delegates to the
    [Relay][bigbrotr.models.relay.Relay] constructor for RFC 3986 validation
    and network detection.

    Args:
        url: Potential relay URL string.
        discovered_at: Optional Unix timestamp of first discovery.  When
            ``None`` (default), ``Relay`` uses the current time.
        allow_local: Whether local relay URLs are accepted.

    Returns:
        [Relay][bigbrotr.models.relay.Relay] object if valid, ``None``
        otherwise.
    """
    if not url or not isinstance(url, str):
        return None

    try:
        url = normalize_relay_url(url, allow_local=allow_local)
    except ValueError:
        return None

    try:
        if discovered_at is not None:
            return Relay(url, discovered_at)
        return Relay(url)
    except (ValueError, TypeError):
        return None


def parse_relay_row(row: Any) -> Relay | None:
    """Construct a Relay from a database row with network cross-check.

    Builds a [Relay][bigbrotr.models.relay.Relay] from ``row["url"]`` and
    ``row["discovered_at"]``, then verifies that the network detected from
    the URL matches ``row["network"]``.  A mismatch is logged as a warning
    (possible data integrity issue) but the relay is still returned with
    the detected network.  Returns ``None`` if the URL fails validation.

    Args:
        row: Database row with ``url``, ``network``, and ``discovered_at``.

    Returns:
        [Relay][bigbrotr.models.relay.Relay] if valid, ``None`` otherwise.
    """
    try:
        relay = Relay(row["url"], row["discovered_at"])
    except (ValueError, TypeError) as e:
        logger.warning("invalid_relay_row_skipped: %s (%s)", row["url"], e)
        return None
    if relay.network.value != row["network"]:
        logger.warning(
            "network_mismatch url=%s db=%s detected=%s",
            row["url"],
            row["network"],
            relay.network.value,
        )
    return relay
