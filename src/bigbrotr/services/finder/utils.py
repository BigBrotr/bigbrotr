"""Finder service utility functions.

Pure helpers for relay URL extraction from Nostr event data and API responses.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import jmespath

from bigbrotr.services.common.utils import parse_relay_url


if TYPE_CHECKING:
    from bigbrotr.models import Relay


def extract_urls_from_response(data: Any, expression: str = "[*]") -> list[str]:
    """Extract URL strings from a JSON API response via a JMESPath expression.

    Applies *expression* to the parsed JSON *data* and filters the result
    to only string values.  Validation (scheme, host, etc.) is left to the
    caller.

    Args:
        data: Parsed JSON response (any type).
        expression: JMESPath expression that should evaluate to a list of
            strings.  Defaults to ``[*]`` (identity on a flat list).

    Returns:
        List of extracted URL strings (may contain duplicates or invalid
        values -- the caller decides how to validate them).
    """
    result = jmespath.search(expression, data)
    if not isinstance(result, list):
        return []
    return [item for item in result if isinstance(item, str)]


def extract_relays_from_rows(rows: list[dict[str, Any]]) -> dict[str, Relay]:
    """Extract and deduplicate relay URLs from event tagvalues.

    Parses every value in each row's ``tagvalues`` array via
    ``parse_relay_url``. Values that parse as valid relay URLs become
    candidates; all others (hex IDs, pubkeys, hashtags, etc.) are
    silently discarded.

    Args:
        rows: Event rows with ``tagvalues`` key (from
            ``scan_event_relay``).

    Returns:
        Mapping of normalized relay URL to
        [Relay][bigbrotr.models.relay.Relay] for deduplication.
    """
    relays: dict[str, Relay] = {}

    for row in rows:
        tagvalues = row.get("tagvalues")
        if not tagvalues:
            continue
        for val in tagvalues:
            validated = parse_relay_url(val)
            if validated:
                relays[validated.url] = validated

    return relays
