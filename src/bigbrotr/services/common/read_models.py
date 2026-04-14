"""Built-in read-model registry shared by the API and DVM services.

The current public surfaces are still catalog-backed and table-shaped.
This registry makes that surface explicit while giving the services a
cleaner boundary than calling ``Catalog`` directly for every request.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol


if TYPE_CHECKING:
    from collections.abc import Mapping

    from bigbrotr.core.brotr import Brotr
    from bigbrotr.services.common.catalog import Catalog, QueryResult, TableSchema


ReadSurface = Literal["api", "dvm"]


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
    except (TypeError, ValueError) as e:
        raise ReadModelQueryError("Invalid limit or offset") from e

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
    except (TypeError, ValueError) as e:
        raise ReadModelQueryError("Invalid limit or offset value") from e

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


class ReadModelBackend(Protocol):
    """Backend capable of serving one public read model."""

    def schema(self, catalog: Catalog) -> TableSchema: ...

    async def query(
        self,
        brotr: Brotr,
        catalog: Catalog,
        request: ReadModelQuery,
    ) -> QueryResult: ...

    async def get_by_pk(
        self,
        brotr: Brotr,
        catalog: Catalog,
        pk_values: dict[str, str],
    ) -> dict[str, Any] | None: ...


@dataclass(frozen=True, slots=True)
class CatalogReadModelBackend:
    """Compatibility backend that serves one catalog-backed read model."""

    catalog_name: str

    def schema(self, catalog: Catalog) -> TableSchema:
        """Resolve the discovered schema backing this read model."""
        return catalog.tables[self.catalog_name]

    async def query(
        self,
        brotr: Brotr,
        catalog: Catalog,
        request: ReadModelQuery,
    ) -> QueryResult:
        """Execute one paginated query through the catalog compatibility backend."""
        return await catalog.query(
            brotr,
            self.catalog_name,
            limit=request.limit,
            offset=request.offset,
            max_page_size=request.max_page_size,
            filters=request.filters,
            sort=request.sort,
            include_total=request.include_total,
            cursor=request.cursor,
            prefer_keyset=True,
        )

    async def get_by_pk(
        self,
        brotr: Brotr,
        catalog: Catalog,
        pk_values: dict[str, str],
    ) -> dict[str, Any] | None:
        """Fetch one row by primary key through the catalog compatibility backend."""
        return await catalog.get_by_pk(
            brotr,
            self.catalog_name,
            pk_values,
        )


@dataclass(frozen=True, slots=True)
class ReadModelEntry:
    """One built-in read model exposed by one or more public surfaces."""

    read_model_id: str
    catalog_name: str
    backend: ReadModelBackend
    surfaces: tuple[ReadSurface, ...] = ("api", "dvm")

    def schema(self, catalog: Catalog) -> TableSchema:
        """Resolve the discovered schema backing this read model."""
        return self.backend.schema(catalog)

    async def query(
        self,
        brotr: Brotr,
        catalog: Catalog,
        request: ReadModelQuery,
    ) -> QueryResult:
        """Execute one paginated query through the registered backend."""
        return await self.backend.query(brotr, catalog, request)

    async def get_by_pk(
        self,
        brotr: Brotr,
        catalog: Catalog,
        pk_values: dict[str, str],
    ) -> dict[str, Any] | None:
        """Fetch one row by primary key through the registered backend."""
        return await self.backend.get_by_pk(brotr, catalog, pk_values)


def _table_read_model(
    name: str,
    *,
    surfaces: tuple[ReadSurface, ...] = ("api", "dvm"),
) -> ReadModelEntry:
    """Build a compatibility read model backed by one catalog table/view."""
    return ReadModelEntry(
        read_model_id=name,
        catalog_name=name,
        backend=CatalogReadModelBackend(name),
        surfaces=surfaces,
    )


READ_MODEL_REGISTRY: dict[str, ReadModelEntry] = {
    "relay": _table_read_model("relay"),
    "event": _table_read_model("event"),
    "event_relay": _table_read_model("event_relay"),
    "metadata": _table_read_model("metadata"),
    "relay_metadata": _table_read_model("relay_metadata"),
    "relay_metadata_current": _table_read_model("relay_metadata_current"),
    "pubkey_stats": _table_read_model("pubkey_stats"),
    "kind_stats": _table_read_model("kind_stats"),
    "relay_stats": _table_read_model("relay_stats"),
    "pubkey_relay_stats": _table_read_model("pubkey_relay_stats"),
    "pubkey_kind_stats": _table_read_model("pubkey_kind_stats"),
    "relay_kind_stats": _table_read_model("relay_kind_stats"),
    "relay_software_counts": _table_read_model("relay_software_counts"),
    "supported_nip_counts": _table_read_model("supported_nip_counts"),
    "daily_counts": _table_read_model("daily_counts"),
    "events_replaceable_current": _table_read_model("events_replaceable_current"),
    "events_addressable_current": _table_read_model("events_addressable_current"),
    "nip85_pubkey_stats": _table_read_model("nip85_pubkey_stats"),
    "nip85_event_stats": _table_read_model("nip85_event_stats"),
    "nip85_addressable_stats": _table_read_model("nip85_addressable_stats"),
    "nip85_identifier_stats": _table_read_model("nip85_identifier_stats"),
}


def read_models_for_surface(surface: ReadSurface) -> dict[str, ReadModelEntry]:
    """Return the built-in read models exposed by one public surface."""
    return {
        read_model_id: entry
        for read_model_id, entry in READ_MODEL_REGISTRY.items()
        if surface in entry.surfaces
    }


def enabled_read_models_for_surface(
    surface: ReadSurface,
    *,
    available_catalog_names: set[str],
    enabled_names: set[str],
) -> dict[str, ReadModelEntry]:
    """Return surface read models that are both configured and discoverable."""
    return {
        read_model_id: entry
        for read_model_id, entry in sorted(read_models_for_surface(surface).items())
        if entry.catalog_name in available_catalog_names and read_model_id in enabled_names
    }
