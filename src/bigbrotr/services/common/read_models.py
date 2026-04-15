"""Built-in read-model registry shared by the API and DVM services.

The current public surfaces are still catalog-backed.
This registry makes that surface explicit while giving the services a
cleaner boundary than calling ``Catalog`` directly for every request.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal


if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from bigbrotr.core.brotr import Brotr
    from bigbrotr.core.logger import Logger
    from bigbrotr.services.common.catalog import Catalog, QueryResult, TableSchema
    from bigbrotr.services.common.configs import ReadModelConfig


ReadSurface = Literal["api", "dvm"]
_READ_SURFACES: tuple[ReadSurface, ...] = ("api", "dvm")


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


class ReadModelSurface:
    """Resolve and execute the public read-model surface for one service."""

    __slots__ = ("_catalog", "_policy_source")

    def __init__(self, *, policy_source: Callable[[], Mapping[str, ReadModelConfig]]) -> None:
        from .catalog import Catalog  # noqa: PLC0415

        self._catalog = Catalog()
        self._policy_source = policy_source

    @property
    def catalog(self) -> Catalog:
        """Return the discovered catalog backing this public read surface."""
        return self._catalog

    @catalog.setter
    def catalog(self, catalog: Catalog) -> None:
        """Replace the backing catalog, mainly for tests or prebuilt surfaces."""
        self._catalog = catalog

    async def discover(self, brotr: Brotr, *, logger: Logger | None = None) -> None:
        """Discover catalog tables and optionally log the resulting surface size."""
        await self._catalog.discover(brotr)
        if logger is not None:
            logger.info(
                "schema_discovered",
                tables=sum(1 for t in self._catalog.tables.values() if not t.is_view),
                views=sum(1 for t in self._catalog.tables.values() if t.is_view),
            )

    def available_catalog_names(self) -> set[str]:
        """Return discovered catalog object names available to the public surface."""
        return set(self._catalog.tables)

    def policies(self) -> dict[str, ReadModelConfig]:
        """Return the current read-model policies from the owning service config."""
        policies = self._policy_source()
        if not isinstance(policies, dict):
            return {}
        return dict(policies)

    def is_enabled(self, name: str) -> bool:
        """Check whether a public read model is registered and enabled in config."""
        if name not in READ_MODEL_REGISTRY:
            return False
        policy = self.policies().get(name)
        return bool(policy and policy.enabled)

    def enabled_names(self, surface: ReadSurface) -> list[str]:
        """Return enabled read-model IDs for one public surface."""
        return resolve_surface_read_model_names(
            surface,
            policies=self.policies(),
            available_catalog_names=self.available_catalog_names(),
        )

    def enabled_entries(self, surface: ReadSurface) -> dict[str, ReadModelEntry]:
        """Return enabled read-model entries for one public surface."""
        return resolve_surface_read_models(
            surface,
            policies=self.policies(),
            available_catalog_names=self.available_catalog_names(),
        )

    def resolve(self, surface: ReadSurface, name: str) -> ReadModelEntry | None:
        """Resolve one public read-model name to an enabled entry for one surface."""
        return resolve_surface_read_model(
            surface,
            name=name,
            policies=self.policies(),
            available_catalog_names=self.available_catalog_names(),
        )

    async def query_entry(
        self,
        brotr: Brotr,
        read_model: ReadModelEntry,
        request: ReadModelQuery,
    ) -> QueryResult:
        """Execute one resolved read-model query through the shared catalog context."""
        return await read_model.query(brotr, self._catalog, request)

    async def get_entry_by_pk(
        self,
        brotr: Brotr,
        read_model: ReadModelEntry,
        pk_values: dict[str, str],
    ) -> dict[str, Any] | None:
        """Fetch one resolved read-model row by primary key."""
        return await read_model.get_by_pk(brotr, self._catalog, pk_values)

    async def query_enabled(
        self,
        brotr: Brotr,
        surface: ReadSurface,
        name: str,
        request: ReadModelQuery,
    ) -> QueryResult | None:
        """Resolve and execute one enabled public read model for a surface."""
        read_model = self.resolve(surface, name)
        if read_model is None:
            return None
        return await self.query_entry(brotr, read_model, request)

    async def get_enabled_row(
        self,
        brotr: Brotr,
        surface: ReadSurface,
        name: str,
        pk_values: dict[str, str],
    ) -> dict[str, Any] | None:
        """Resolve and fetch one row from an enabled public read model for a surface."""
        read_model = self.resolve(surface, name)
        if read_model is None:
            return None
        return await self.get_entry_by_pk(brotr, read_model, pk_values)

    def build_summaries(
        self,
        surface: ReadSurface,
        *,
        route_prefix: str,
    ) -> list[dict[str, Any]]:
        """Build discovery summaries for enabled public read models on one surface."""
        return [
            read_model.summary(catalog=self._catalog, route_prefix=route_prefix)
            for read_model_id, read_model in self.enabled_entries(surface).items()
        ]

    def build_detail(
        self,
        surface: ReadSurface,
        name: str,
        *,
        route_prefix: str,
    ) -> dict[str, Any] | None:
        """Build the discovery detail payload for one enabled public read model."""
        read_model = self.resolve(surface, name)
        if read_model is None:
            return None
        return read_model.detail(catalog=self._catalog, route_prefix=route_prefix)


@dataclass(frozen=True, slots=True)
class ReadModelEntry:
    """One built-in read model exposed by one or more public surfaces."""

    read_model_id: str
    catalog_name: str
    surfaces: tuple[ReadSurface, ...] = ("api", "dvm")

    def schema(self, catalog: Catalog) -> TableSchema:
        """Resolve the discovered schema backing this read model."""
        return catalog.tables[self.catalog_name]

    def pagination(self, catalog: Catalog) -> dict[str, Any]:
        """Build the discovery-time pagination contract for this read model."""
        supports_identity_lookup = bool(self.schema(catalog).primary_key)
        return {
            "default_mode": "cursor" if supports_identity_lookup else "offset",
            "supports_cursor": supports_identity_lookup,
            "supports_offset": True,
            "supports_total_opt_in": True,
            "cursor_param": "cursor" if supports_identity_lookup else None,
            "meta_cursor_field": "next_cursor" if supports_identity_lookup else None,
        }

    def summary(self, *, catalog: Catalog, route_prefix: str) -> dict[str, Any]:
        """Build the public summary payload for this read model."""
        schema = self.schema(catalog)
        pagination = self.pagination(catalog)
        return {
            "id": self.read_model_id,
            "path": f"{route_prefix}/{self.read_model_id}",
            "field_count": len(schema.columns),
            "supports_identity_lookup": bool(schema.primary_key),
            "default_pagination_mode": pagination["default_mode"],
            "supports_cursor_pagination": pagination["supports_cursor"],
        }

    def detail(self, *, catalog: Catalog, route_prefix: str) -> dict[str, Any]:
        """Build the public detail payload for this read model."""
        schema = self.schema(catalog)
        return {
            "id": self.read_model_id,
            "path": f"{route_prefix}/{self.read_model_id}",
            "fields": [
                {
                    "name": column.name,
                    "type": column.pg_type,
                    "nullable": column.nullable,
                }
                for column in schema.columns
            ],
            "identity_fields": list(schema.primary_key),
            "pagination": self.pagination(catalog),
        }

    async def query(
        self,
        brotr: Brotr,
        catalog: Catalog,
        request: ReadModelQuery,
    ) -> QueryResult:
        """Execute one paginated query through the shared catalog context."""
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
        """Fetch one row by primary key through the shared catalog context."""
        return await catalog.get_by_pk(
            brotr,
            self.catalog_name,
            pk_values,
        )


def _catalog_read_model(
    read_model_id: str,
    catalog_name: str,
    surfaces: tuple[ReadSurface, ...] = ("api", "dvm"),
) -> ReadModelEntry:
    """Build one catalog-backed read model entry."""
    return ReadModelEntry(
        read_model_id=read_model_id,
        catalog_name=catalog_name,
        surfaces=surfaces,
    )


READ_MODEL_REGISTRY: dict[str, ReadModelEntry] = {
    "relays": _catalog_read_model("relays", "relay"),
    "events": _catalog_read_model("events", "event"),
    "event-observations": _catalog_read_model("event-observations", "event_relay"),
    "metadata-documents": _catalog_read_model("metadata-documents", "metadata"),
    "relay-metadata-history": _catalog_read_model("relay-metadata-history", "relay_metadata"),
    "relay-metadata-current": _catalog_read_model(
        "relay-metadata-current",
        "relay_metadata_current",
    ),
    "pubkey-stats": _catalog_read_model("pubkey-stats", "pubkey_stats"),
    "kind-stats": _catalog_read_model("kind-stats", "kind_stats"),
    "relay-stats": _catalog_read_model("relay-stats", "relay_stats"),
    "pubkey-relay-stats": _catalog_read_model("pubkey-relay-stats", "pubkey_relay_stats"),
    "pubkey-kind-stats": _catalog_read_model("pubkey-kind-stats", "pubkey_kind_stats"),
    "relay-kind-stats": _catalog_read_model("relay-kind-stats", "relay_kind_stats"),
    "relay-software-counts": _catalog_read_model("relay-software-counts", "relay_software_counts"),
    "supported-nip-counts": _catalog_read_model("supported-nip-counts", "supported_nip_counts"),
    "daily-counts": _catalog_read_model("daily-counts", "daily_counts"),
    "replaceable-events-current": _catalog_read_model(
        "replaceable-events-current",
        "events_replaceable_current",
    ),
    "addressable-events-current": _catalog_read_model(
        "addressable-events-current",
        "events_addressable_current",
    ),
    "nip85-pubkey-stats": _catalog_read_model("nip85-pubkey-stats", "nip85_pubkey_stats"),
    "nip85-event-stats": _catalog_read_model("nip85-event-stats", "nip85_event_stats"),
    "nip85-addressable-stats": _catalog_read_model(
        "nip85-addressable-stats",
        "nip85_addressable_stats",
    ),
    "nip85-identifier-stats": _catalog_read_model(
        "nip85-identifier-stats",
        "nip85_identifier_stats",
    ),
}

READ_MODELS_BY_SURFACE: dict[ReadSurface, dict[str, ReadModelEntry]] = {
    surface: {
        read_model_id: entry
        for read_model_id, entry in READ_MODEL_REGISTRY.items()
        if surface in entry.surfaces
    }
    for surface in _READ_SURFACES
}


def normalize_read_model_policies(
    policies: Mapping[str, ReadModelConfig],
    *,
    surface: ReadSurface,
) -> dict[str, ReadModelConfig]:
    """Validate config policies against the canonical public read-model IDs."""
    normalized = dict(policies)
    allowed = set(read_models_for_surface(surface))

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
    return dict(READ_MODELS_BY_SURFACE[surface])


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
) -> ReadModelEntry | None:
    """Resolve one public read-model name to an enabled, discoverable entry."""
    return resolve_surface_read_models(
        surface,
        policies=policies,
        available_catalog_names=available_catalog_names,
    ).get(name)


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
