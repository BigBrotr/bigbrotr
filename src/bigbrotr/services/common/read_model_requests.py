"""Shared request parsing and response metadata for public read models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from collections.abc import Mapping

    from .catalog import QueryResult


class ReadModelQueryError(ValueError):
    """Client-safe validation error raised while parsing public query params."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.client_message = message


@dataclass(frozen=True, slots=True)
class ReadModelQuery:
    """Normalized query request for one public read model."""

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
        if "=" not in part:
            continue
        key, _, value = part.partition("=")
        filters[key.strip()] = value.strip()
    return filters or None


def _parse_include_total(raw_value: str | None) -> bool:
    """Normalize public include-total flags from HTTP or NIP-90 inputs."""
    if raw_value is None:
        return False

    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    raise ReadModelQueryError("Invalid include_total value")


def _parse_cursor(raw_value: str | None) -> str | None:
    """Normalize optional opaque keyset cursors from public inputs."""
    if raw_value is None:
        return None

    normalized = raw_value.strip()
    return normalized or None


def read_model_query_from_http_params(
    params: Mapping[str, str],
    *,
    default_page_size: int,
    max_page_size: int,
) -> ReadModelQuery:
    """Normalize one HTTP read-model request into the shared query contract."""
    raw_params = dict(params)
    raw_cursor = raw_params.pop("cursor", None)
    try:
        limit = int(raw_params.pop("limit", default_page_size))
        offset = int(raw_params.pop("offset", 0))
    except (TypeError, ValueError) as error:
        raise ReadModelQueryError("Invalid limit or offset") from error

    sort = raw_params.pop("sort", None)
    include_total = _parse_include_total(raw_params.pop("include_total", None))
    cursor = _parse_cursor(raw_cursor)
    if cursor is not None and offset > 0:
        raise ReadModelQueryError("Cursor pagination cannot be combined with offset")

    return ReadModelQuery(
        limit=limit,
        offset=offset,
        max_page_size=max_page_size,
        filters=raw_params or None,
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
    try:
        limit = int(params.get("limit", default_page_size))
        offset = int(params.get("offset", 0))
    except (TypeError, ValueError) as error:
        raise ReadModelQueryError("Invalid limit or offset value") from error

    raw_sort = params.get("sort")
    sort = raw_sort if isinstance(raw_sort, str) and raw_sort else None
    raw_filter = params.get("filter", "")
    filter_str = raw_filter if isinstance(raw_filter, str) else ""
    cursor = _parse_cursor(params.get("cursor", None))
    if cursor is not None and offset > 0:
        raise ReadModelQueryError("Cursor pagination cannot be combined with offset")

    return ReadModelQuery(
        limit=limit,
        offset=offset,
        max_page_size=max_page_size,
        filters=parse_read_model_filter_string(filter_str),
        sort=sort,
        include_total=_parse_include_total(params.get("include_total", None)),
        cursor=cursor,
    )


def build_read_model_meta(result: QueryResult, *, read_model_id: str) -> dict[str, Any]:
    """Build the shared metadata envelope for HTTP and DVM list responses."""
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
