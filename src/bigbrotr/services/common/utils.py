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

from bigbrotr.models import Relay


def validate_relay_url(url: str) -> Relay | None:
    """Validate and normalize a relay URL string.

    Strips whitespace, rejects empty/non-string input, and delegates to the
    [Relay][bigbrotr.models.relay.Relay] constructor for RFC 3986 validation
    and network detection.

    Args:
        url: Potential relay URL string.

    Returns:
        [Relay][bigbrotr.models.relay.Relay] object if valid, ``None``
        otherwise.
    """
    if not url or not isinstance(url, str):
        return None

    url = url.strip()
    if not url:
        return None

    try:
        return Relay(url)
    except (ValueError, TypeError):
        return None


def parse_delete_result(result: str | None) -> int:
    """Extract the row count from a PostgreSQL DELETE command status string.

    PostgreSQL returns status strings like ``'DELETE 42'`` from DELETE
    commands. This function extracts the trailing integer count.

    Args:
        result: The command status string (e.g., ``'DELETE 42'``), or
            ``None`` if the command returned no status.

    Returns:
        Number of rows affected, or ``0`` if parsing fails.
    """
    if not result:
        return 0
    try:
        return int(result.split()[-1])
    except (ValueError, IndexError):
        return 0
