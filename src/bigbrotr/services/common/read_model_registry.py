"""Readable-resource registry with compatibility helpers for public adapters."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from .read_model_requests import ReadModelQuery


if TYPE_CHECKING:
    from bigbrotr.core.brotr import Brotr
    from bigbrotr.services.common.catalog import Catalog
    from bigbrotr.services.common.catalog_types import QueryResult, TableSchema
    from bigbrotr.services.common.configs import ReadModelPolicy


ReadSurface = Literal["api", "dvm"]
_READ_SURFACES: tuple[ReadSurface, ...] = ("api", "dvm")
ReadableResourceKind = Literal["relation", "handler"]
ReadableResourceSchemaHandler = Callable[["Catalog", "ReadableResourceEntry"], "TableSchema"]
ReadableResourceQueryHandler = Callable[
    ["Brotr", "Catalog", "ReadableResourceEntry", ReadModelQuery],
    Awaitable["QueryResult"],
]
ReadableResourceGetByPkHandler = Callable[
    ["Brotr", "Catalog", "ReadableResourceEntry", dict[str, str]],
    Awaitable[dict[str, Any] | None],
]
ReadModelSchemaHandler = ReadableResourceSchemaHandler
ReadModelQueryHandler = ReadableResourceQueryHandler
ReadModelGetByPkHandler = ReadableResourceGetByPkHandler


def _catalog_schema_handler(catalog: Catalog, resource: ReadableResourceEntry) -> TableSchema:
    """Resolve one resource schema through the shared catalog."""
    return catalog.tables[resource.catalog_name]


async def _catalog_query_handler(
    brotr: Brotr,
    catalog: Catalog,
    resource: ReadableResourceEntry,
    request: ReadModelQuery,
) -> QueryResult:
    """Execute one relation-backed resource query through the shared catalog."""
    pagination = resource.pagination(catalog)
    effective_max_page_size = request.max_page_size
    if resource.max_page_size is not None:
        effective_max_page_size = min(effective_max_page_size, resource.max_page_size)
    return await catalog.query(
        brotr,
        resource.catalog_name,
        limit=request.limit,
        offset=request.offset,
        max_page_size=effective_max_page_size,
        filters=request.filters,
        sort=request.sort,
        include_total=request.include_total,
        cursor=request.cursor,
        prefer_keyset=pagination["supports_cursor"],
    )


async def _catalog_get_by_pk_handler(
    brotr: Brotr,
    catalog: Catalog,
    resource: ReadableResourceEntry,
    pk_values: dict[str, str],
) -> dict[str, Any] | None:
    """Execute one primary-key lookup through the shared catalog."""
    return await catalog.get_by_pk(
        brotr,
        resource.catalog_name,
        pk_values,
    )


def _default_semantic_name(resource_id: str) -> str:
    """Build a human-readable semantic name from a stable resource ID."""
    return resource_id.replace("-", " ").title()


@dataclass(frozen=True, slots=True)
class ReadableResourceEntry:
    """One readable resource exposed by one or more public adapter surfaces.

    This descriptor is the canonical internal contract for the read side. The
    public HTTP and NIP-90 transports still expose historical ``read model``
    identifiers, so compatibility aliases remain part of the API for now.
    """

    read_model_id: str
    catalog_name: str
    semantic_name: str = ""
    surfaces: tuple[ReadSurface, ...] = ("api", "dvm")
    backing_kind: ReadableResourceKind = "relation"
    default_traversal_order: tuple[str, ...] = ()
    cursor_key_fields: tuple[str, ...] = ()
    allowed_filters: tuple[str, ...] = ()
    allowed_sorts: tuple[str, ...] = ()
    supports_cursor_pagination: bool | None = None
    supports_offset_pagination: bool = True
    supports_total_opt_in: bool = True
    max_page_size: int | None = None
    schema_handler: ReadableResourceSchemaHandler = _catalog_schema_handler
    query_handler: ReadableResourceQueryHandler = _catalog_query_handler
    get_by_pk_handler: ReadableResourceGetByPkHandler = _catalog_get_by_pk_handler

    @property
    def resource_id(self) -> str:
        """Return the stable readable-resource ID."""
        return self.read_model_id

    @property
    def relation_name(self) -> str:
        """Return the backing relation name for relation-backed resources."""
        return self.catalog_name

    def schema(self, catalog: Catalog) -> TableSchema:
        """Resolve the discovered schema backing this readable resource."""
        return self.schema_handler(catalog, self)

    def _supports_cursor_pagination(self, schema: TableSchema) -> bool:
        """Return whether cursor pagination is supported for this resource."""
        if self.supports_cursor_pagination is not None:
            return self.supports_cursor_pagination
        return bool(schema.primary_key)

    def _default_traversal_terms(self, schema: TableSchema) -> list[str] | None:
        """Return the declared stable traversal order, if one exists."""
        if self.default_traversal_order:
            return list(self.default_traversal_order)
        if self._supports_cursor_pagination(schema) and schema.primary_key:
            return [f"{field}:asc" for field in schema.primary_key]
        return None

    def _cursor_fields(self, schema: TableSchema) -> list[str] | None:
        """Return the cursor key fields, if cursor pagination is supported."""
        if not self._supports_cursor_pagination(schema):
            return None
        if self.cursor_key_fields:
            return list(self.cursor_key_fields)
        if schema.primary_key:
            return list(schema.primary_key)
        return None

    def _allowed_filter_fields(self, schema: TableSchema) -> list[str]:
        """Return the allowed filter field names for this resource."""
        if self.allowed_filters:
            return list(self.allowed_filters)
        return [column.name for column in schema.columns]

    def _allowed_sort_fields(self, schema: TableSchema) -> list[str]:
        """Return the allowed sort field names for this resource."""
        if self.allowed_sorts:
            return list(self.allowed_sorts)
        return [column.name for column in schema.columns]

    def pagination(self, catalog: Catalog) -> dict[str, Any]:
        """Build the discovery-time pagination contract for this resource."""
        schema = self.schema(catalog)
        supports_cursor = self._supports_cursor_pagination(schema)
        return {
            "default_mode": "cursor" if supports_cursor else "offset",
            "supports_cursor": supports_cursor,
            "supports_offset": self.supports_offset_pagination,
            "supports_total_opt_in": self.supports_total_opt_in,
            "cursor_param": "cursor" if supports_cursor else None,
            "meta_cursor_field": "next_cursor" if supports_cursor else None,
        }

    def contract(self, catalog: Catalog) -> dict[str, Any]:
        """Return the internal readable-resource contract descriptor."""
        schema = self.schema(catalog)
        identity_fields = list(schema.primary_key)
        return {
            "id": self.resource_id,
            "name": self.semantic_name or _default_semantic_name(self.resource_id),
            "backing_kind": self.backing_kind,
            "relation_name": self.relation_name if self.backing_kind == "relation" else None,
            "identity_fields": identity_fields,
            "default_traversal_order": self._default_traversal_terms(schema),
            "cursor_key_fields": self._cursor_fields(schema),
            "allowed_filters": self._allowed_filter_fields(schema),
            "allowed_sorts": self._allowed_sort_fields(schema),
            "pagination": self.pagination(catalog),
        }

    def summary(self, *, catalog: Catalog, route_prefix: str) -> dict[str, Any]:
        """Build the public summary payload for this resource."""
        schema = self.schema(catalog)
        pagination = self.pagination(catalog)
        return {
            "id": self.resource_id,
            "path": f"{route_prefix}/{self.resource_id}",
            "field_count": len(schema.columns),
            "supports_identity_lookup": bool(schema.primary_key),
            "default_pagination_mode": pagination["default_mode"],
            "supports_cursor_pagination": pagination["supports_cursor"],
        }

    def detail(self, *, catalog: Catalog, route_prefix: str) -> dict[str, Any]:
        """Build the public detail payload for this resource."""
        schema = self.schema(catalog)
        return {
            "id": self.resource_id,
            "path": f"{route_prefix}/{self.resource_id}",
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
        return await self.query_handler(brotr, catalog, self, request)

    def validate_query(self, catalog: Catalog, request: ReadModelQuery) -> None:
        """Validate one public query against the resource contract."""
        from .catalog import CatalogError  # noqa: PLC0415
        from .catalog_planner import parse_sort  # noqa: PLC0415

        schema = self.schema(catalog)
        pagination = self.pagination(catalog)

        if request.cursor is not None and not pagination["supports_cursor"]:
            raise CatalogError("Cursor pagination is not supported for this readable resource")
        if request.offset > 0 and not pagination["supports_offset"]:
            raise CatalogError("Offset pagination is not supported for this readable resource")
        if request.include_total and not pagination["supports_total_opt_in"]:
            raise CatalogError("include_total is not supported for this readable resource")

        allowed_filters = set(self._allowed_filter_fields(schema))
        if request.filters:
            invalid_filters = sorted(set(request.filters) - allowed_filters)
            if invalid_filters:
                invalid_list = ", ".join(invalid_filters)
                raise CatalogError(
                    f"Unsupported filter fields for {self.resource_id}: {invalid_list}"
                )

        if request.sort is None:
            return

        sort_field, _ = parse_sort(request.sort)
        if sort_field not in set(self._allowed_sort_fields(schema)):
            raise CatalogError(f"Unsupported sort field for {self.resource_id}: {sort_field}")

    async def get_by_pk(
        self,
        brotr: Brotr,
        catalog: Catalog,
        pk_values: dict[str, str],
    ) -> dict[str, Any] | None:
        """Fetch one row by primary key through the shared catalog context."""
        return await self.get_by_pk_handler(brotr, catalog, self, pk_values)


ReadModelEntry = ReadableResourceEntry


def _catalog_readable_resource(
    resource_id: str,
    relation_name: str,
    *,
    semantic_name: str | None = None,
    surfaces: tuple[ReadSurface, ...] = ("api", "dvm"),
) -> ReadableResourceEntry:
    """Build one relation-backed readable-resource entry."""
    return ReadableResourceEntry(
        read_model_id=resource_id,
        catalog_name=relation_name,
        semantic_name=semantic_name or _default_semantic_name(resource_id),
        surfaces=surfaces,
    )


READABLE_RESOURCE_REGISTRY: dict[str, ReadableResourceEntry] = {
    "relays": _catalog_readable_resource("relays", "relay", semantic_name="Relays"),
    "events": _catalog_readable_resource("events", "event", semantic_name="Events"),
    "event-observations": _catalog_readable_resource(
        "event-observations",
        "event_observation",
        semantic_name="Event observations",
    ),
    "documents": _catalog_readable_resource("documents", "document", semantic_name="Documents"),
    "relay-document-history": _catalog_readable_resource(
        "relay-document-history",
        "relay_document",
        semantic_name="Relay document history",
    ),
    "relay-document-current": _catalog_readable_resource(
        "relay-document-current",
        "relay_document_current",
        semantic_name="Relay document current",
    ),
    "pubkey-stats": _catalog_readable_resource(
        "pubkey-stats",
        "pubkey_stats",
        semantic_name="Pubkey stats",
    ),
    "kind-stats": _catalog_readable_resource(
        "kind-stats",
        "kind_stats",
        semantic_name="Kind stats",
    ),
    "relay-stats": _catalog_readable_resource(
        "relay-stats",
        "relay_stats",
        semantic_name="Relay stats",
    ),
    "pubkey-relay-stats": _catalog_readable_resource(
        "pubkey-relay-stats",
        "pubkey_relay_stats",
        semantic_name="Pubkey relay stats",
    ),
    "pubkey-kind-stats": _catalog_readable_resource(
        "pubkey-kind-stats",
        "pubkey_kind_stats",
        semantic_name="Pubkey kind stats",
    ),
    "relay-kind-stats": _catalog_readable_resource(
        "relay-kind-stats",
        "relay_kind_stats",
        semantic_name="Relay kind stats",
    ),
    "relay-software-counts": _catalog_readable_resource(
        "relay-software-counts",
        "relay_software_counts",
        semantic_name="Relay software counts",
    ),
    "supported-nip-counts": _catalog_readable_resource(
        "supported-nip-counts",
        "supported_nip_counts",
        semantic_name="Supported NIP counts",
    ),
    "daily-counts": _catalog_readable_resource(
        "daily-counts",
        "daily_counts",
        semantic_name="Daily counts",
    ),
    "replaceable-events-current": _catalog_readable_resource(
        "replaceable-events-current",
        "replaceable_event_current",
        semantic_name="Replaceable events current",
    ),
    "addressable-events-current": _catalog_readable_resource(
        "addressable-events-current",
        "addressable_event_current",
        semantic_name="Addressable events current",
    ),
    "nip85-pubkey-stats": _catalog_readable_resource(
        "nip85-pubkey-stats",
        "nip85_pubkey_stats",
        semantic_name="NIP-85 pubkey stats",
    ),
    "nip85-event-stats": _catalog_readable_resource(
        "nip85-event-stats",
        "nip85_event_stats",
        semantic_name="NIP-85 event stats",
    ),
    "nip85-addressable-stats": _catalog_readable_resource(
        "nip85-addressable-stats",
        "nip85_addressable_stats",
        semantic_name="NIP-85 addressable stats",
    ),
    "nip85-identifier-stats": _catalog_readable_resource(
        "nip85-identifier-stats",
        "nip85_identifier_stats",
        semantic_name="NIP-85 identifier stats",
    ),
}
READ_MODEL_REGISTRY = READABLE_RESOURCE_REGISTRY

READABLE_RESOURCES_BY_SURFACE: dict[ReadSurface, dict[str, ReadableResourceEntry]] = {
    surface: {
        resource_id: entry
        for resource_id, entry in READABLE_RESOURCE_REGISTRY.items()
        if surface in entry.surfaces
    }
    for surface in _READ_SURFACES
}
READ_MODELS_BY_SURFACE = READABLE_RESOURCES_BY_SURFACE


def normalize_readable_resource_policies(
    policies: Mapping[str, ReadModelPolicy],
    *,
    surface: ReadSurface,
) -> dict[str, ReadModelPolicy]:
    """Validate config policies against canonical public readable-resource IDs."""
    normalized = dict(policies)
    allowed = set(readable_resources_for_surface(surface))

    invalid = sorted(set(normalized) - allowed)
    if invalid:
        invalid_names = ", ".join(invalid)
        allowed_names = ", ".join(sorted(allowed))
        raise ValueError(
            f"read_models contains non-public {surface.upper()} read models: "
            f"{invalid_names}. Allowed read models: {allowed_names}"
        )

    return normalized


def normalize_read_model_policies(
    policies: Mapping[str, ReadModelPolicy],
    *,
    surface: ReadSurface,
) -> dict[str, ReadModelPolicy]:
    """Compatibility wrapper over readable-resource policy validation."""
    return normalize_readable_resource_policies(policies, surface=surface)


def readable_resources_for_surface(surface: ReadSurface) -> dict[str, ReadableResourceEntry]:
    """Return the readable resources exposed by one public surface."""
    return dict(READABLE_RESOURCES_BY_SURFACE[surface])


def read_models_for_surface(surface: ReadSurface) -> dict[str, ReadModelEntry]:
    """Compatibility wrapper returning the readable resources for one surface."""
    return readable_resources_for_surface(surface)


def resolve_surface_readable_resources(
    surface: ReadSurface,
    *,
    policies: Mapping[str, ReadModelPolicy],
    available_catalog_names: set[str],
) -> dict[str, ReadableResourceEntry]:
    """Resolve one public surface to enabled, discoverable readable resources."""
    enabled_names = {name for name, policy in policies.items() if policy.enabled}
    return {
        resource_id: entry
        for resource_id, entry in sorted(readable_resources_for_surface(surface).items())
        if entry.catalog_name in available_catalog_names and resource_id in enabled_names
    }


def resolve_surface_read_models(
    surface: ReadSurface,
    *,
    policies: Mapping[str, ReadModelPolicy],
    available_catalog_names: set[str],
) -> dict[str, ReadModelEntry]:
    """Compatibility wrapper resolving enabled readable resources."""
    return resolve_surface_readable_resources(
        surface,
        policies=policies,
        available_catalog_names=available_catalog_names,
    )


def resolve_surface_readable_resource(
    surface: ReadSurface,
    *,
    name: str,
    policies: Mapping[str, ReadModelPolicy],
    available_catalog_names: set[str],
) -> ReadableResourceEntry | None:
    """Resolve one public readable-resource name to an enabled entry."""
    return resolve_surface_readable_resources(
        surface,
        policies=policies,
        available_catalog_names=available_catalog_names,
    ).get(name)


def resolve_surface_read_model(
    surface: ReadSurface,
    *,
    name: str,
    policies: Mapping[str, ReadModelPolicy],
    available_catalog_names: set[str],
) -> ReadModelEntry | None:
    """Compatibility wrapper for resolving one enabled readable resource."""
    return resolve_surface_readable_resource(
        surface,
        name=name,
        policies=policies,
        available_catalog_names=available_catalog_names,
    )


def resolve_surface_readable_resource_names(
    surface: ReadSurface,
    *,
    policies: Mapping[str, ReadModelPolicy],
    available_catalog_names: set[str],
) -> list[str]:
    """Resolve one public surface to the ordered list of enabled readable-resource IDs."""
    return list(
        resolve_surface_readable_resources(
            surface,
            policies=policies,
            available_catalog_names=available_catalog_names,
        )
    )


def resolve_surface_read_model_names(
    surface: ReadSurface,
    *,
    policies: Mapping[str, ReadModelPolicy],
    available_catalog_names: set[str],
) -> list[str]:
    """Compatibility wrapper for enabled readable-resource IDs."""
    return resolve_surface_readable_resource_names(
        surface,
        policies=policies,
        available_catalog_names=available_catalog_names,
    )
