"""Pure helpers for the NIP-90 adapter.

This module parses request events, validates them against the shared read-core
contract, and builds NIP-90 result or feedback events. The helpers are
stateless and do not touch the network or the database directly.
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from nostr_sdk import EventBuilder, Kind, Tag

from bigbrotr.services.common.configs import ReadModelPolicy
from bigbrotr.services.common.read_models import (
    ReadableResourceEntry,
    ReadCore,
    ReadModelQuery,
    ReadModelQueryError,
    build_read_model_meta,
    read_model_query_from_job_params,
)


if TYPE_CHECKING:
    from collections.abc import Mapping

    from bigbrotr.services.common.catalog_types import QueryResult

# Minimum tag lengths for NIP-90 tag parsing
_MIN_PARAM_TAG_LEN = 3
_MIN_TAG_LEN = 2


@dataclass(frozen=True, slots=True)
class ResultEventRequest:
    """Context needed to build one NIP-90 job-result event."""

    request_kind: int
    request_event_id: str
    customer_pubkey: str
    resource_id: str


@dataclass(frozen=True, slots=True)
class PreparedJobRequest:
    """Validated NIP-90 job request ready for execution."""

    resource_id: str
    resource: ReadableResourceEntry
    query: ReadModelQuery
    price: int


@dataclass(frozen=True, slots=True)
class RejectedJobRequest:
    """Client-safe rejection produced while validating one job request."""

    error_message: str | None = None
    required_price: int | None = None
    bid: int | None = None

    def __post_init__(self) -> None:
        has_error = self.error_message is not None
        has_payment = self.required_price is not None
        if has_error == has_payment:
            raise ValueError(
                "RejectedJobRequest requires exactly one of error_message or required_price"
            )
        if self.bid is not None and self.required_price is None:
            raise ValueError("RejectedJobRequest.bid requires required_price")


@dataclass(frozen=True, slots=True)
class JobPreparationContext:
    """Pure inputs needed to validate one NIP-90 job request."""

    read_core: ReadCore
    exposure_policy: Mapping[str, ReadModelPolicy]
    default_page_size: int
    max_page_size: int


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


def prepare_job_request(
    requested_resource_id: str,
    params: Mapping[str, Any],
    *,
    context: JobPreparationContext,
) -> PreparedJobRequest | RejectedJobRequest:
    """Resolve exposure, pricing, and query parsing for one NIP-90 job request."""
    requested_resource_id = requested_resource_id.strip()
    resolved_resource = context.read_core.resolve_resource("dvm", requested_resource_id)
    if resolved_resource is None:
        return RejectedJobRequest(
            error_message=f"Invalid or disabled read model: {requested_resource_id}"
        )

    resource = resolved_resource
    resource_id = resource.resource_id
    price = context.exposure_policy.get(resource_id, ReadModelPolicy()).price
    raw_bid = params.get("bid", 0)
    bid = raw_bid if isinstance(raw_bid, int) and not isinstance(raw_bid, bool) else 0
    if price > 0 and bid < price:
        return RejectedJobRequest(required_price=price, bid=bid)

    try:
        query = read_model_query_from_job_params(
            params,
            default_page_size=context.default_page_size,
            max_page_size=context.max_page_size,
        )
    except ReadModelQueryError as e:
        return RejectedJobRequest(error_message=e.client_message)

    return PreparedJobRequest(
        resource_id=resource_id,
        resource=resource,
        query=query,
        price=price,
    )


def build_result_event(
    request: ResultEventRequest,
    result: QueryResult,
    price: int,
) -> EventBuilder:
    """Build a NIP-90 job result event (request kind + 1000).

    Args:
        request: Job request context for the result event.
        result: Query result to serialize as JSON content.
        price: Millisat price (included as ``amount`` tag if > 0).

    Returns:
        Unsigned ``EventBuilder`` ready for signing and sending.
    """
    result_kind = request.request_kind + 1000
    content = json.dumps(
        {
            "data": result.rows,
            "meta": build_read_model_meta(result, read_model_id=request.resource_id),
        },
        default=str,
    )

    tags = [
        Tag.parse(["e", request.request_event_id]),
        Tag.parse(["p", request.customer_pubkey]),
        Tag.parse(
            [
                "request",
                json.dumps({"id": request.request_event_id, "kind": request.request_kind}),
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
    read_models: list[str],
) -> EventBuilder:
    """Build a NIP-89 handler announcement event (kind 31990).

    Args:
        d_tag: Unique handler identifier for the replaceable event.
        kind: NIP-90 request kind this handler supports.
        name: Human-readable handler name.
        about: Handler description.
        read_models: List of enabled public readable-resource IDs serialized
            under the stable ``read_models`` announcement key.

    Returns:
        Unsigned ``EventBuilder`` ready for signing and sending.
    """
    tags = [
        Tag.parse(["d", d_tag]),
        Tag.parse(["k", str(kind)]),
    ]
    content = json.dumps({"name": name, "about": about, "read_models": read_models})
    return EventBuilder(Kind(31990), content).tags(tags)
