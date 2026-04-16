"""Runtime surface wrapper for built-in public read models."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from bigbrotr.core.brotr import Brotr
    from bigbrotr.core.logger import Logger
    from bigbrotr.services.common.catalog import Catalog, QueryResult
    from bigbrotr.services.common.configs import ReadModelPolicy

from .read_model_registry import (
    READ_MODEL_REGISTRY,
    ReadModelEntry,
    ReadSurface,
    normalize_read_model_policies,
    read_models_for_surface,
    resolve_surface_read_model,
    resolve_surface_read_model_names,
    resolve_surface_read_models,
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
    "READ_MODEL_REGISTRY",
    "ReadModelEntry",
    "ReadModelQuery",
    "ReadModelQueryError",
    "ReadModelSurface",
    "ReadSurface",
    "build_read_model_meta",
    "normalize_read_model_policies",
    "parse_read_model_filter_string",
    "read_model_query_from_http_params",
    "read_model_query_from_job_params",
    "read_models_for_surface",
    "resolve_surface_read_model",
    "resolve_surface_read_model_names",
    "resolve_surface_read_models",
]


class ReadModelSurface:
    """Resolve and execute the public read-model surface for one service."""

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

    async def discover(self, brotr: Brotr, *, logger: Logger | None = None) -> None:
        """Discover catalog tables and optionally log the resulting surface size."""
        await self._catalog.discover(brotr)
        if logger is not None:
            logger.info(
                "schema_discovered",
                tables=sum(1 for t in self._catalog.tables.values() if not t.is_view),
                views=sum(1 for t in self._catalog.tables.values() if t.is_view),
            )

    def enabled_names(self, surface: ReadSurface) -> list[str]:
        """Return enabled read-model IDs for one public surface."""
        policies = self._policy_source()
        return resolve_surface_read_model_names(
            surface,
            policies=dict(policies) if isinstance(policies, dict) else {},
            available_catalog_names=set(self._catalog.tables),
        )

    def enabled_entries(self, surface: ReadSurface) -> dict[str, ReadModelEntry]:
        """Return enabled read-model entries for one public surface."""
        policies = self._policy_source()
        return resolve_surface_read_models(
            surface,
            policies=dict(policies) if isinstance(policies, dict) else {},
            available_catalog_names=set(self._catalog.tables),
        )

    def resolve(self, surface: ReadSurface, name: str) -> ReadModelEntry | None:
        """Resolve one public read-model name to an enabled entry for one surface."""
        policies = self._policy_source()
        return resolve_surface_read_model(
            surface,
            name=name,
            policies=dict(policies) if isinstance(policies, dict) else {},
            available_catalog_names=set(self._catalog.tables),
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
