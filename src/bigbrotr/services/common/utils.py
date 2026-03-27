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
from typing import Any

from bigbrotr.models import Relay
from bigbrotr.models.relay import sanitize_relay_url


logger = logging.getLogger(__name__)


def parse_relay(url: str, discovered_at: int | None = None) -> Relay | None:
    """Parse a relay URL string into a Relay object.

    Strips whitespace, rejects empty/non-string input, and delegates to the
    [Relay][bigbrotr.models.relay.Relay] constructor for RFC 3986 validation
    and network detection.

    Args:
        url: Potential relay URL string.
        discovered_at: Optional Unix timestamp of first discovery.  When
            ``None`` (default), ``Relay`` uses the current time.

    Returns:
        [Relay][bigbrotr.models.relay.Relay] object if valid, ``None``
        otherwise.
    """
    if not url or not isinstance(url, str):
        return None

    try:
        url = sanitize_relay_url(url)
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
