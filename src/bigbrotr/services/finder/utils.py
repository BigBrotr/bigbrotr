"""Finder service utility functions.

Pure helpers for relay URL extraction from Nostr event data and API responses.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import jmespath

from bigbrotr.services.common.utils import parse_relay


if TYPE_CHECKING:
    from bigbrotr.models import Relay


def extract_relays_from_response(data: Any, expression: str) -> list[Relay]:
    """Extract and validate relay URLs from a JSON API response.

    Applies *expression* to the parsed JSON *data*, filters to string
    values, validates each through
    [parse_relay][bigbrotr.services.common.utils.parse_relay],
    and returns a deduplicated list of Relay objects.

    Args:
        data: Parsed JSON response (any type).
        expression: JMESPath expression that should evaluate to a list of
            strings.

    Returns:
        Deduplicated list of [Relay][bigbrotr.models.relay.Relay] objects.
    """
    result = jmespath.search(expression, data)
    if not isinstance(result, list):
        return []
    seen: set[str] = set()
    relays: list[Relay] = []
    for item in result:
        if isinstance(item, str):
            validated = parse_relay(item)
            if validated and validated.url not in seen:
                seen.add(validated.url)
                relays.append(validated)
    return relays


def extract_relays_from_tagvalues(rows: list[dict[str, Any]]) -> list[Relay]:
    """Extract and deduplicate relay URLs from event tagvalues.

    Strips the tag prefix (everything up to the first ``:``) from each
    value and passes the remainder to ``parse_relay``.  All tag
    types are examined -- not just ``r:`` -- since relay URLs can appear
    in any tag.  Invalid values are rejected by ``parse_relay``.

    Args:
        rows: Event rows with ``tagvalues`` key (from
            ``scan_event_relay``).

    Returns:
        Deduplicated list of [Relay][bigbrotr.models.relay.Relay] objects.
    """
    seen: set[str] = set()
    relays: list[Relay] = []

    for row in rows:
        tagvalues = row.get("tagvalues")
        if not tagvalues:
            continue
        for val in tagvalues:
            if not isinstance(val, str):
                continue
            _, _, raw_val = val.partition(":")
            validated = parse_relay(raw_val)
            if validated and validated.url not in seen:
                seen.add(validated.url)
                relays.append(validated)

    return relays
