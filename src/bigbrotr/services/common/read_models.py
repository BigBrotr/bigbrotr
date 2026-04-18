"""Shared read-core plus read-model compatibility wrappers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from bigbrotr.core.brotr import Brotr
    from bigbrotr.core.logger import Logger
    from bigbrotr.services.common.catalog import Catalog
    from bigbrotr.services.common.catalog_types import QueryResult
    from bigbrotr.services.common.configs import ReadModelPolicy

from .read_model_registry import (
    READ_MODEL_REGISTRY,
    READABLE_RESOURCE_REGISTRY,
    ReadableResourceEntry,
    ReadModelEntry,
    ReadSurface,
    normalize_read_model_policies,
    normalize_readable_resource_policies,
    read_models_for_surface,
    readable_resources_for_surface,
    resolve_surface_read_model,
    resolve_surface_read_model_names,
    resolve_surface_read_models,
    resolve_surface_readable_resource,
    resolve_surface_readable_resource_names,
    resolve_surface_readable_resources,
)
from .read_model_requests import (
    ReadModelQuery,
    ReadModelQueryError,
    build_read_model_meta,
    parse_read_model_filter_string,
    read_model_query_from_http_params,
    read_model_query_from_job_params,
)


__all__ = [
    "READABLE_RESOURCE_REGISTRY",
    "READ_MODEL_REGISTRY",
    "ReadCore",
    "ReadCoreError",
    "ReadModelEntry",
    "ReadModelQuery",
    "ReadModelQueryError",
    "ReadModelSurface",
    "ReadSurface",
    "ReadableResourceEntry",
    "ReadableResourceNotFoundError",
    "build_read_model_meta",
    "normalize_read_model_policies",
    "normalize_readable_resource_policies",
    "parse_read_model_filter_string",
    "read_model_query_from_http_params",
    "read_model_query_from_job_params",
    "read_models_for_surface",
    "readable_resources_for_surface",
    "resolve_surface_read_model",
    "resolve_surface_read_model_names",
    "resolve_surface_read_models",
    "resolve_surface_readable_resource",
    "resolve_surface_readable_resource_names",
    "resolve_surface_readable_resources",
]


class ReadCoreError(ValueError):
    """Base error raised by the shared read core."""


class ReadableResourceNotFoundError(ReadCoreError):
    """Raised when one readable resource is invalid, disabled, or undiscoverable."""


class ReadCore:
    """Protocol-agnostic read core over readable-resource descriptors."""

    __slots__ = ("_catalog", "_policy_source")

    def __init__(self, *, policy_source: Callable[[], Mapping[str, ReadModelPolicy]]) -> None:
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

    def _policies(self) -> dict[str, ReadModelPolicy]:
        """Return the current resource policies as a concrete mapping."""
        return dict(self._policy_source())

    async def discover(self, brotr: Brotr, *, logger: Logger | None = None) -> None:
        """Discover catalog tables and optionally log the resulting surface size."""
        await self._catalog.discover(brotr)
        if logger is not None:
            logger.info(
                "schema_discovered",
                tables=sum(1 for t in self._catalog.tables.values() if not t.is_view),
                views=sum(1 for t in self._catalog.tables.values() if t.is_view),
            )

    def enabled_resource_ids(self, surface: ReadSurface) -> list[str]:
        """Return enabled readable-resource IDs for one public surface."""
        return resolve_surface_readable_resource_names(
            surface,
            policies=self._policies(),
            available_catalog_names=set(self._catalog.tables),
        )

    def enabled_resources(self, surface: ReadSurface) -> dict[str, ReadableResourceEntry]:
        """Return enabled readable-resource entries for one public surface."""
        return resolve_surface_readable_resources(
            surface,
            policies=self._policies(),
            available_catalog_names=set(self._catalog.tables),
        )

    def resolve_resource(self, surface: ReadSurface, name: str) -> ReadableResourceEntry | None:
        """Resolve one public readable-resource name to an enabled entry."""
        return resolve_surface_readable_resource(
            surface,
            name=name,
            policies=self._policies(),
            available_catalog_names=set(self._catalog.tables),
        )

    def require_resource(self, surface: ReadSurface, name: str) -> ReadableResourceEntry:
        """Resolve one enabled resource or raise a normalized read-core error."""
        resource = self.resolve_resource(surface, name)
        if resource is None:
            raise ReadableResourceNotFoundError(f"Invalid or disabled readable resource: {name}")
        return resource

    async def query_resource(
        self,
        brotr: Brotr,
        resource: ReadableResourceEntry,
        request: ReadModelQuery,
    ) -> QueryResult:
        """Execute one resolved readable-resource query through the shared catalog."""
        resource.validate_query(self._catalog, request)
        return await resource.query(brotr, self._catalog, request)

    async def get_resource_by_pk(
        self,
        brotr: Brotr,
        resource: ReadableResourceEntry,
        pk_values: dict[str, str],
    ) -> dict[str, Any] | None:
        """Fetch one resolved readable-resource row by primary key."""
        return await resource.get_by_pk(brotr, self._catalog, pk_values)

    def build_resource_summaries(
        self,
        surface: ReadSurface,
        *,
        route_prefix: str,
    ) -> list[dict[str, Any]]:
        """Build discovery summaries for enabled readable resources."""
        return [
            resource.summary(catalog=self._catalog, route_prefix=route_prefix)
            for _, resource in self.enabled_resources(surface).items()
        ]

    def build_resource_detail(
        self,
        surface: ReadSurface,
        name: str,
        *,
        route_prefix: str,
    ) -> dict[str, Any] | None:
        """Build the discovery detail payload for one enabled readable resource."""
        resource = self.resolve_resource(surface, name)
        if resource is None:
            return None
        return resource.detail(catalog=self._catalog, route_prefix=route_prefix)


class ReadModelSurface:
    """Compatibility wrapper over the shared read core.

    The current API and DVM stacks still speak in terms of `read models`. This
    wrapper preserves that seam while delegating all shared behavior into
    `ReadCore`.
    """

    __slots__ = ("_core",)

    def __init__(self, *, policy_source: Callable[[], Mapping[str, ReadModelPolicy]]) -> None:
        self._core = ReadCore(policy_source=policy_source)

    @property
    def core(self) -> ReadCore:
        """Return the underlying shared read core."""
        return self._core

    @property
    def catalog(self) -> Catalog:
        """Return the discovered catalog backing this public read surface."""
        return self._core.catalog

    @catalog.setter
    def catalog(self, catalog: Catalog) -> None:
        """Replace the backing catalog, mainly for tests or prebuilt surfaces."""
        self._core.catalog = catalog

    async def discover(self, brotr: Brotr, *, logger: Logger | None = None) -> None:
        """Discover catalog tables and optionally log the resulting surface size."""
        await self._core.discover(brotr, logger=logger)

    def enabled_names(self, surface: ReadSurface) -> list[str]:
        """Return enabled readable-resource IDs for one public surface."""
        return self._core.enabled_resource_ids(surface)

    def enabled_entries(self, surface: ReadSurface) -> dict[str, ReadModelEntry]:
        """Return enabled readable-resource entries for one public surface."""
        return self._core.enabled_resources(surface)

    def resolve(self, surface: ReadSurface, name: str) -> ReadModelEntry | None:
        """Resolve one public readable-resource name to an enabled entry."""
        return self._core.resolve_resource(surface, name)

    async def query_entry(
        self,
        brotr: Brotr,
        read_model: ReadModelEntry,
        request: ReadModelQuery,
    ) -> QueryResult:
        """Execute one resolved readable-resource query through the shared catalog."""
        return await self._core.query_resource(brotr, read_model, request)

    async def get_entry_by_pk(
        self,
        brotr: Brotr,
        read_model: ReadModelEntry,
        pk_values: dict[str, str],
    ) -> dict[str, Any] | None:
        """Fetch one resolved readable-resource row by primary key."""
        return await self._core.get_resource_by_pk(brotr, read_model, pk_values)

    def build_summaries(
        self,
        surface: ReadSurface,
        *,
        route_prefix: str,
    ) -> list[dict[str, Any]]:
        """Build discovery summaries for enabled readable resources."""
        return self._core.build_resource_summaries(surface, route_prefix=route_prefix)

    def build_detail(
        self,
        surface: ReadSurface,
        name: str,
        *,
        route_prefix: str,
    ) -> dict[str, Any] | None:
        """Build the discovery detail payload for one enabled readable resource."""
        return self._core.build_resource_detail(surface, name, route_prefix=route_prefix)
