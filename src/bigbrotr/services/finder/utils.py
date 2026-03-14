"""Finder service utility functions.

Helpers for relay URL extraction from Nostr event data and API responses,
and cursor-paginated streaming of event-relay rows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import aiohttp
import jmespath

from bigbrotr.services.common.types import FinderCursor
from bigbrotr.services.common.utils import parse_relay
from bigbrotr.utils.http import read_bounded_json

from .queries import scan_event_relay


if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from bigbrotr.core.brotr import Brotr
    from bigbrotr.models import Relay

    from .configs import ApiSourceConfig


async def fetch_api(
    session: aiohttp.ClientSession,
    source: ApiSourceConfig,
    max_response_size: int,
) -> list[Relay]:
    """Fetch and validate relay URLs from a single API endpoint.

    Args:
        session: Shared aiohttp ClientSession for connection pooling.
        source: API source configuration (URL, timeout, extraction params).
        max_response_size: Maximum response body size in bytes.

    Returns:
        Deduplicated list of Relay objects.
    """
    timeout = aiohttp.ClientTimeout(
        total=source.timeout,
        connect=min(source.connect_timeout, source.timeout),
        sock_read=source.timeout,
    )
    async with session.get(source.url, timeout=timeout, ssl=not source.allow_insecure) as resp:
        resp.raise_for_status()
        data = await read_bounded_json(resp, max_response_size)
        return extract_relays_from_response(data, source.expression)


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


async def stream_event_relays(
    brotr: Brotr,
    cursor: FinderCursor,
    batch_size: int,
) -> AsyncGenerator[dict[str, Any], None]:
    """Stream event-relay rows for a single relay using cursor pagination.

    Fetches rows in batches of *batch_size* via
    [scan_event_relay][bigbrotr.services.finder.queries.scan_event_relay],
    advancing the cursor after each batch. Yields individual rows.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        cursor: [FinderCursor][bigbrotr.services.common.types.FinderCursor]
            with relay URL and pagination position.
        batch_size: Maximum rows per DB query.

    Yields:
        Event-relay row dicts with ``event_id``, ``tagvalues``, ``seen_at``,
        and other event columns.
    """
    while True:
        rows = await scan_event_relay(brotr, cursor, batch_size)
        if not rows:
            break
        for row in rows:
            yield row
        last = rows[-1]
        cursor = FinderCursor(
            key=cursor.key,
            timestamp=last["seen_at"],
            id=last["event_id"].hex(),
        )
        if len(rows) < batch_size:
            break


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
