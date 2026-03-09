"""DVM service utility functions.

Pure helpers for NIP-90 event parsing and event builder construction.
All functions are stateless — they build ``EventBuilder`` instances or
parse event data without touching the network or database.
"""

from __future__ import annotations

import contextlib
import json
from typing import TYPE_CHECKING, Any

from nostr_sdk import EventBuilder, Kind, Tag


if TYPE_CHECKING:
    from bigbrotr.services.common.catalog import QueryResult

# Minimum tag lengths for NIP-90 tag parsing
_MIN_PARAM_TAG_LEN = 3
_MIN_TAG_LEN = 2


def parse_job_params(event: Any) -> dict[str, Any]:
    """Extract NIP-90 parameters from event tags.

    Reads ``["param", key, value]`` tags and an optional ``["bid", amount]``
    tag from the event.  Invalid bid values are silently ignored.

    Args:
        event: A ``nostr_sdk.Event`` (or mock with ``.tags().to_vec()``).

    Returns:
        Dict mapping parameter names to their string values, plus an
        optional ``"bid"`` key with an integer value.
    """
    params: dict[str, Any] = {}
    for tag in event.tags().to_vec():
        values = tag.as_vec()
        if len(values) >= _MIN_PARAM_TAG_LEN and values[0] == "param":
            params[values[1]] = values[2]
        elif len(values) >= _MIN_TAG_LEN and values[0] == "bid":
            with contextlib.suppress(ValueError):
                params["bid"] = int(values[1])
    return params


def parse_query_filters(filter_str: str) -> dict[str, str] | None:
    """Parse a comma-separated filter string into a dict.

    Format: ``"column=value,column=op:value"`` where ``op`` is one of
    ``=``, ``>``, ``<``, ``>=``, ``<=``, ``ILIKE``.

    Args:
        filter_str: Raw filter string from a NIP-90 ``param`` tag.

    Returns:
        Dict of column→value pairs, or ``None`` if empty or unparsable.
    """
    if not filter_str:
        return None
    filters: dict[str, str] = {}
    for raw_part in filter_str.split(","):
        part = raw_part.strip()
        if "=" not in part:
            continue
        key, _, value = part.partition("=")
        filters[key.strip()] = value.strip()
    return filters or None


def build_result_event(
    request_kind: int,
    request_event_id: str,
    customer_pubkey: str,
    result: QueryResult,
    price: int,
) -> EventBuilder:
    """Build a NIP-90 job result event (request kind + 1000).

    Args:
        request_kind: The NIP-90 request kind (e.g. 5050).
        request_event_id: Hex ID of the request event.
        customer_pubkey: Hex pubkey of the requesting user.
        result: Query result to serialize as JSON content.
        price: Millisat price (included as ``amount`` tag if > 0).

    Returns:
        Unsigned ``EventBuilder`` ready for signing and sending.
    """
    result_kind = request_kind + 1000
    content = json.dumps(
        {
            "data": result.rows,
            "meta": {
                "total": result.total,
                "limit": result.limit,
                "offset": result.offset,
            },
        },
        default=str,
    )

    tags = [
        Tag.parse(["e", request_event_id]),
        Tag.parse(["p", customer_pubkey]),
        Tag.parse(
            [
                "request",
                json.dumps({"id": request_event_id, "kind": request_kind}),
            ]
        ),
    ]
    if price > 0:
        tags.append(Tag.parse(["amount", str(price)]))

    return EventBuilder(Kind(result_kind), content).tags(tags)


def build_error_event(
    request_event_id: str,
    customer_pubkey: str,
    error_message: str,
) -> EventBuilder:
    """Build a NIP-90 error feedback event (kind 7000).

    Args:
        request_event_id: Hex ID of the request event.
        customer_pubkey: Hex pubkey of the requesting user.
        error_message: Human-readable error description.

    Returns:
        Unsigned ``EventBuilder`` ready for signing and sending.
    """
    tags = [
        Tag.parse(["status", "error", error_message]),
        Tag.parse(["e", request_event_id]),
        Tag.parse(["p", customer_pubkey]),
    ]
    return EventBuilder(Kind(7000), "").tags(tags)


def build_payment_required_event(
    request_event_id: str,
    customer_pubkey: str,
    price: int,
) -> EventBuilder:
    """Build a NIP-90 payment-required feedback event (kind 7000).

    Args:
        request_event_id: Hex ID of the request event.
        customer_pubkey: Hex pubkey of the requesting user.
        price: Required payment in millisats.

    Returns:
        Unsigned ``EventBuilder`` ready for signing and sending.
    """
    tags = [
        Tag.parse(["status", "payment-required", f"This query costs {price} millisats"]),
        Tag.parse(["e", request_event_id]),
        Tag.parse(["p", customer_pubkey]),
        Tag.parse(["amount", str(price)]),
    ]
    return EventBuilder(Kind(7000), "").tags(tags)


def build_announcement_event(
    d_tag: str,
    kind: int,
    name: str,
    about: str,
    tables: list[str],
) -> EventBuilder:
    """Build a NIP-89 handler announcement event (kind 31990).

    Args:
        d_tag: Unique handler identifier for the replaceable event.
        kind: NIP-90 request kind this handler supports.
        name: Human-readable handler name.
        about: Handler description.
        tables: List of enabled table names.

    Returns:
        Unsigned ``EventBuilder`` ready for signing and sending.
    """
    tags = [
        Tag.parse(["d", d_tag]),
        Tag.parse(["k", str(kind)]),
    ]
    content = json.dumps({"name": name, "about": about, "tables": tables})
    return EventBuilder(Kind(31990), content).tags(tags)
