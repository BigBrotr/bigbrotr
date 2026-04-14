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
    from bigbrotr.services.common.configs import ReadModelConfig


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
    aliases: tuple[str, ...] = ()
    surfaces: tuple[ReadSurface, ...] = ("api", "dvm")

    @property
    def all_public_ids(self) -> tuple[str, ...]:
        """Return canonical and legacy public IDs for this read model."""
        return (self.read_model_id, *self.aliases)

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
    read_model_id: str,
    catalog_name: str,
    *,
    aliases: tuple[str, ...] = (),
    surfaces: tuple[ReadSurface, ...] = ("api", "dvm"),
) -> ReadModelEntry:
    """Build one catalog-backed read model with canonical and legacy IDs."""
    return ReadModelEntry(
        read_model_id=read_model_id,
        catalog_name=catalog_name,
        backend=CatalogReadModelBackend(catalog_name),
        aliases=aliases,
        surfaces=surfaces,
    )


READ_MODEL_REGISTRY: dict[str, ReadModelEntry] = {
    "relays": _table_read_model("relays", "relay", aliases=("relay",)),
    "events": _table_read_model("events", "event", aliases=("event",)),
    "event-observations": _table_read_model(
        "event-observations",
        "event_relay",
        aliases=("event_relay",),
    ),
    "metadata-documents": _table_read_model(
        "metadata-documents",
        "metadata",
        aliases=("metadata",),
    ),
    "relay-metadata-history": _table_read_model(
        "relay-metadata-history",
        "relay_metadata",
        aliases=("relay_metadata",),
    ),
    "relay-metadata-current": _table_read_model(
        "relay-metadata-current",
        "relay_metadata_current",
        aliases=("relay_metadata_current",),
    ),
    "pubkey-stats": _table_read_model("pubkey-stats", "pubkey_stats", aliases=("pubkey_stats",)),
    "kind-stats": _table_read_model("kind-stats", "kind_stats", aliases=("kind_stats",)),
    "relay-stats": _table_read_model("relay-stats", "relay_stats", aliases=("relay_stats",)),
    "pubkey-relay-stats": _table_read_model(
        "pubkey-relay-stats",
        "pubkey_relay_stats",
        aliases=("pubkey_relay_stats",),
    ),
    "pubkey-kind-stats": _table_read_model(
        "pubkey-kind-stats",
        "pubkey_kind_stats",
        aliases=("pubkey_kind_stats",),
    ),
    "relay-kind-stats": _table_read_model(
        "relay-kind-stats",
        "relay_kind_stats",
        aliases=("relay_kind_stats",),
    ),
    "relay-software-counts": _table_read_model(
        "relay-software-counts",
        "relay_software_counts",
        aliases=("relay_software_counts",),
    ),
    "supported-nip-counts": _table_read_model(
        "supported-nip-counts",
        "supported_nip_counts",
        aliases=("supported_nip_counts",),
    ),
    "daily-counts": _table_read_model("daily-counts", "daily_counts", aliases=("daily_counts",)),
    "replaceable-events-current": _table_read_model(
        "replaceable-events-current",
        "events_replaceable_current",
        aliases=("events_replaceable_current",),
    ),
    "addressable-events-current": _table_read_model(
        "addressable-events-current",
        "events_addressable_current",
        aliases=("events_addressable_current",),
    ),
    "nip85-pubkey-stats": _table_read_model(
        "nip85-pubkey-stats",
        "nip85_pubkey_stats",
        aliases=("nip85_pubkey_stats",),
    ),
    "nip85-event-stats": _table_read_model(
        "nip85-event-stats",
        "nip85_event_stats",
        aliases=("nip85_event_stats",),
    ),
    "nip85-addressable-stats": _table_read_model(
        "nip85-addressable-stats",
        "nip85_addressable_stats",
        aliases=("nip85_addressable_stats",),
    ),
    "nip85-identifier-stats": _table_read_model(
        "nip85-identifier-stats",
        "nip85_identifier_stats",
        aliases=("nip85_identifier_stats",),
    ),
}

READ_MODEL_ALIASES: dict[str, str] = {
    public_id: entry.read_model_id
    for entry in READ_MODEL_REGISTRY.values()
    for public_id in entry.all_public_ids
}


def resolve_read_model_id(name: str) -> str | None:
    """Resolve one canonical or legacy public name to the canonical read-model ID."""
    return READ_MODEL_ALIASES.get(name)


def normalize_read_model_policies(
    policies: Mapping[str, ReadModelConfig],
    *,
    surface: ReadSurface,
) -> dict[str, ReadModelConfig]:
    """Normalize config policies onto canonical read-model IDs.

    Accepts both canonical and legacy names, but rejects conflicting duplicates
    that would collapse onto the same canonical read model.
    """
    normalized: dict[str, ReadModelConfig] = {}
    seen_names: dict[str, str] = {}
    allowed = set(read_models_for_surface(surface))

    for raw_name, policy in policies.items():
        canonical_name = resolve_read_model_id(raw_name) or raw_name
        if canonical_name in normalized:
            previous = seen_names[canonical_name]
            raise ValueError(
                f"Duplicate read model policy for {canonical_name}: {previous}, {raw_name}"
            )
        normalized[canonical_name] = policy
        seen_names[canonical_name] = raw_name

    invalid = sorted(set(normalized) - allowed)
    if invalid:
        invalid_names = ", ".join(invalid)
        allowed_names = ", ".join(sorted(allowed))
        raise ValueError(
            f"read_models contains non-public {surface.upper()} read models: "
            f"{invalid_names}. Allowed read models: {allowed_names}"
        )

    return normalized


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
    canonical_enabled = {resolve_read_model_id(name) or name for name in enabled_names}
    return {
        read_model_id: entry
        for read_model_id, entry in sorted(read_models_for_surface(surface).items())
        if entry.catalog_name in available_catalog_names and read_model_id in canonical_enabled
    }


def resolve_surface_read_models(
    surface: ReadSurface,
    *,
    policies: Mapping[str, ReadModelConfig],
    available_catalog_names: set[str],
) -> dict[str, ReadModelEntry]:
    """Resolve one public surface to enabled, discoverable read-model entries."""
    enabled_names = {name for name, policy in policies.items() if policy.enabled}
    return enabled_read_models_for_surface(
        surface,
        available_catalog_names=available_catalog_names,
        enabled_names=enabled_names,
    )


def resolve_surface_read_model(
    surface: ReadSurface,
    *,
    name: str,
    policies: Mapping[str, ReadModelConfig],
    available_catalog_names: set[str],
) -> tuple[str, ReadModelEntry] | None:
    """Resolve one public read-model name to an enabled, discoverable entry."""
    canonical_name = resolve_read_model_id(name) or name
    read_model = resolve_surface_read_models(
        surface,
        policies=policies,
        available_catalog_names=available_catalog_names,
    ).get(canonical_name)
    if read_model is None:
        return None
    return canonical_name, read_model


def resolve_surface_read_model_names(
    surface: ReadSurface,
    *,
    policies: Mapping[str, ReadModelConfig],
    available_catalog_names: set[str],
) -> list[str]:
    """Resolve one public surface to the ordered list of enabled read-model IDs."""
    return list(
        resolve_surface_read_models(
            surface,
            policies=policies,
            available_catalog_names=available_catalog_names,
        )
    )
