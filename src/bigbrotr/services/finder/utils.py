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

    Each tagvalue is stored with a key prefix (``"r:wss://relay.com"``).
    This function strips the prefix via :meth:`str.partition` (splitting
    only on the first ``:``, so ``wss://`` in the URL is preserved) and
    passes the raw value to ``parse_relay_url``.

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
            _, _, raw_val = val.partition(":")
            validated = parse_relay_url(raw_val)
            if validated:
                relays[validated.url] = validated

    return relays
