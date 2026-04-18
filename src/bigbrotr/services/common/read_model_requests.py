"""Shared request parsing and metadata envelopes for public read adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from collections.abc import Mapping

    from .catalog_types import QueryResult


class ReadModelQueryError(ValueError):
    """Client-safe validation error raised while parsing public query params."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.client_message = message


@dataclass(frozen=True, slots=True)
class ReadModelQuery:
    """Normalized query request for one public readable-resource query."""

    limit: int
    offset: int
    max_page_size: int = 1000
    filters: dict[str, str] | None = None
    sort: str | None = None
    include_total: bool = False
    cursor: str | None = None


def parse_read_model_filter_string(filter_str: str) -> dict[str, str] | None:
    """Parse a compact comma-separated filter string into catalog-style filters."""
    if not filter_str:
        return None

    filters: dict[str, str] = {}
    for raw_part in filter_str.split(","):
        part = raw_part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ReadModelQueryError("Invalid filter value")
        key, _, value = part.partition("=")
        normalized_key = key.strip()
        if not normalized_key:
            raise ReadModelQueryError("Invalid filter value")
        filters[normalized_key] = value.strip()
    return filters or None


def _parse_include_total(raw_value: Any) -> bool:
    """Normalize public include-total flags from HTTP or NIP-90 inputs."""
    if raw_value is None:
        return False
    if isinstance(raw_value, bool):
        return raw_value
    if not isinstance(raw_value, str):
        raise ReadModelQueryError("Invalid include_total value")

    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    raise ReadModelQueryError("Invalid include_total value")


def _parse_cursor(raw_value: Any) -> str | None:
    """Normalize optional opaque keyset cursors from public inputs."""
    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise ReadModelQueryError("Invalid cursor value")

    normalized = raw_value.strip()
    return normalized or None


def _parse_sort(raw_value: Any) -> str | None:
    """Normalize optional public sort strings from HTTP or NIP-90 inputs."""
    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise ReadModelQueryError("Invalid sort value")

    normalized = raw_value.strip()
    return normalized or None


def _parse_job_filter_string(raw_value: Any) -> dict[str, str] | None:
    """Normalize compact NIP-90 filter strings before shared parsing."""
    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise ReadModelQueryError("Invalid filter value")
    return parse_read_model_filter_string(raw_value)


def _normalize_http_filters(raw_filters: Mapping[str, str]) -> dict[str, str] | None:
    """Normalize direct HTTP query filters before shared validation."""
    if not raw_filters:
        return None

    filters: dict[str, str] = {}
    for raw_key, value in raw_filters.items():
        key = raw_key.strip()
        if not key:
            raise ReadModelQueryError("Invalid filter field")
        filters[key] = value.strip()
    return filters or None


def _parse_int_param(raw_value: Any, *, error_message: str, minimum: int) -> int:
    """Normalize one public integer parameter without accepting bool aliases."""
    if isinstance(raw_value, bool):
        raise ReadModelQueryError(error_message)

    try:
        value = int(raw_value)
    except (TypeError, ValueError) as error:
        raise ReadModelQueryError(error_message) from error
    if value < minimum:
        raise ReadModelQueryError(error_message)
    return value


def read_model_query_from_http_params(
    params: Mapping[str, str],
    *,
    default_page_size: int,
    max_page_size: int,
) -> ReadModelQuery:
    """Normalize one HTTP readable-resource request into the shared query contract."""
    raw_params = dict(params)
    raw_cursor = raw_params.pop("cursor", None)
    limit = _parse_int_param(
        raw_params.pop("limit", default_page_size),
        error_message="Invalid limit or offset",
        minimum=1,
    )
    offset = _parse_int_param(
        raw_params.pop("offset", 0),
        error_message="Invalid limit or offset",
        minimum=0,
    )

    sort = _parse_sort(raw_params.pop("sort", None))
    include_total = _parse_include_total(raw_params.pop("include_total", None))
    cursor = _parse_cursor(raw_cursor)
    if cursor is not None and offset > 0:
        raise ReadModelQueryError("Cursor pagination cannot be combined with offset")

    return ReadModelQuery(
        limit=limit,
        offset=offset,
        max_page_size=max_page_size,
        filters=_normalize_http_filters(raw_params),
        sort=sort,
        include_total=include_total,
        cursor=cursor,
    )


def read_model_query_from_job_params(
    params: Mapping[str, Any],
    *,
    default_page_size: int,
    max_page_size: int,
) -> ReadModelQuery:
    """Normalize one NIP-90 job request into the shared query contract."""
    limit = _parse_int_param(
        params.get("limit", default_page_size),
        error_message="Invalid limit or offset value",
        minimum=1,
    )
    offset = _parse_int_param(
        params.get("offset", 0),
        error_message="Invalid limit or offset value",
        minimum=0,
    )

    sort = _parse_sort(params.get("sort", None))
    cursor = _parse_cursor(params.get("cursor", None))
    if cursor is not None and offset > 0:
        raise ReadModelQueryError("Cursor pagination cannot be combined with offset")

    return ReadModelQuery(
        limit=limit,
        offset=offset,
        max_page_size=max_page_size,
        filters=_parse_job_filter_string(params.get("filter", None)),
        sort=sort,
        include_total=_parse_include_total(params.get("include_total", None)),
        cursor=cursor,
    )


def build_read_model_meta(result: QueryResult, *, read_model_id: str) -> dict[str, Any]:
    """Build the shared metadata envelope for HTTP and DVM list responses.

    The meta payload intentionally keeps the historical ``read_model`` field so
    public transport contracts remain stable while the internal read core is
    resource-oriented.
    """
    meta: dict[str, Any] = {
        "limit": result.limit,
        "offset": result.offset,
        "read_model": read_model_id,
    }
    if result.total is not None:
        meta["total"] = result.total
    if result.next_cursor is not None:
        meta["next_cursor"] = result.next_cursor
    return meta
