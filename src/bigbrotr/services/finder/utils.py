"""Finder service utility functions.

Pure helpers for relay URL extraction from Nostr event data.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from bigbrotr.models.constants import EventKind
from bigbrotr.services.common.utils import parse_relay_url


if TYPE_CHECKING:
    from bigbrotr.models import Relay


def extract_relays_from_rows(rows: list[dict[str, Any]]) -> dict[str, Relay]:
    """Extract and deduplicate relay URLs from event rows.

    Parses relay URLs from three sources within each event row:

    - ``r`` tags: any event with ``["r", "<url>"]`` tag entries.
    - Kind 2 content: the deprecated NIP-01 recommend-relay event.
    - Kind 3 content: NIP-02 contact list with JSON relay map as keys.

    Args:
        rows: Event rows with ``kind``, ``tags``, ``content``,
            and ``seen_at`` keys (from
            ``get_events_with_relay_urls``).

    Returns:
        Mapping of normalized relay URL to
        [Relay][bigbrotr.models.relay.Relay] for deduplication.
    """
    relays: dict[str, Relay] = {}

    for row in rows:
        kind = row["kind"]
        tags = row["tags"]
        content = row["content"]

        # Extract relay URLs from tags (r-tags)
        if tags:
            for tag in tags:
                if isinstance(tag, list) and len(tag) >= 2 and tag[0] == "r":  # noqa: PLR2004
                    validated = parse_relay_url(tag[1])
                    if validated:
                        relays[validated.url] = validated

        # Kind 2: content is the relay URL (deprecated NIP)
        if kind == EventKind.RECOMMEND_RELAY and content:
            validated = parse_relay_url(content.strip())
            if validated:
                relays[validated.url] = validated

        # Kind 3: content may be JSON with relay URLs as keys
        if kind == EventKind.CONTACTS and content:
            try:
                relay_data = json.loads(content)
                if isinstance(relay_data, dict):
                    for url in relay_data:
                        validated = parse_relay_url(url)
                        if validated:
                            relays[validated.url] = validated
            except (json.JSONDecodeError, TypeError):
                pass

    return relays
