from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from bigbrotr.core.yaml import load_yaml
from bigbrotr.services.common.catalog import Catalog, ColumnSchema, QueryResult, TableSchema
from bigbrotr.services.common.configs import ReadModelPolicy
from bigbrotr.services.common.read_models import (
    READ_MODEL_REGISTRY,
    ReadModelEntry,
    ReadModelQuery,
    ReadModelQueryError,
    ReadModelSurface,
    build_read_model_meta,
    normalize_read_model_policies,
    parse_read_model_filter_string,
    read_model_query_from_http_params,
    read_model_query_from_job_params,
    read_models_for_surface,
    resolve_surface_read_model,
    resolve_surface_read_model_names,
    resolve_surface_read_models,
)


def _configured_read_models(path: Path) -> set[str]:
    config = load_yaml(str(path))
    return set(config.get("read_models", {}))


class TestReadModelRegistry:
    def test_registry_entries_are_read_model_entry(self) -> None:
        for entry in READ_MODEL_REGISTRY.values():
            assert isinstance(entry, ReadModelEntry)

    def test_all_entries_are_catalog_compatibility_read_models(self) -> None:
        for read_model_id, entry in READ_MODEL_REGISTRY.items():
            assert entry.read_model_id == read_model_id
            assert entry.surfaces

    def test_registry_covers_all_configured_api_read_models(self) -> None:
        api_configs = (
            Path("deployments/bigbrotr/config/services/api.yaml"),
            Path("deployments/lilbrotr/config/services/api.yaml"),
        )

        configured = set().union(*(_configured_read_models(path) for path in api_configs))

        assert configured <= set(READ_MODEL_REGISTRY)

    def test_registry_covers_all_configured_dvm_read_models(self) -> None:
        dvm_configs = (
            Path("deployments/bigbrotr/config/services/dvm.yaml"),
            Path("deployments/lilbrotr/config/services/dvm.yaml"),
        )

        configured = set().union(*(_configured_read_models(path) for path in dvm_configs))

        assert configured <= set(READ_MODEL_REGISTRY)

    def test_api_surface_matches_configured_api_read_models(self) -> None:
        api_configs = (
            Path("deployments/bigbrotr/config/services/api.yaml"),
            Path("deployments/lilbrotr/config/services/api.yaml"),
        )

        expected = set().union(*(_configured_read_models(path) for path in api_configs))

        assert set(read_models_for_surface("api")) == expected

    def test_dvm_surface_matches_configured_dvm_read_models(self) -> None:
        dvm_configs = (
            Path("deployments/bigbrotr/config/services/dvm.yaml"),
            Path("deployments/lilbrotr/config/services/dvm.yaml"),
        )

        expected = set().union(*(_configured_read_models(path) for path in dvm_configs))

        assert set(read_models_for_surface("dvm")) == expected

    def test_internal_state_tables_are_not_public_read_models(self) -> None:
        assert "service_state" not in READ_MODEL_REGISTRY

    def test_resolve_surface_read_models_filters_by_config_and_catalog(self) -> None:
        enabled = resolve_surface_read_models(
            "api",
            policies={
                "relays": ReadModelPolicy(enabled=True),
                "metadata-documents": ReadModelPolicy(enabled=True),
            },
            available_catalog_names={"relay", "event"},
        )

        assert set(enabled) == {"relays"}

    def test_resolve_surface_read_models_filters_disabled_and_missing_catalog_entries(self) -> None:
        resolved = resolve_surface_read_models(
            "api",
            policies={
                "relays": ReadModelPolicy(enabled=True),
                "events": ReadModelPolicy(enabled=False),
                "metadata-documents": ReadModelPolicy(enabled=True),
            },
            available_catalog_names={"relay"},
        )

        assert set(resolved) == {"relays"}

    def test_resolve_surface_read_model_names_returns_stable_sorted_ids(self) -> None:
        resolved = resolve_surface_read_model_names(
            "dvm",
            policies={
                "events": ReadModelPolicy(enabled=True),
                "relays": ReadModelPolicy(enabled=True),
            },
            available_catalog_names={"relay", "event"},
        )

        assert resolved == ["events", "relays"]

    def test_resolve_surface_read_model_filters_out_missing_catalog_entries(self) -> None:
        resolved = resolve_surface_read_model(
            "dvm",
            name="relays",
            policies={"relays": ReadModelPolicy(enabled=True)},
            available_catalog_names={"event"},
        )

        assert resolved is None

    def test_entry_schema_uses_catalog_name(self) -> None:
        catalog = Catalog()
        catalog._tables = {
            "relay": TableSchema(
                name="relay",
                columns=(ColumnSchema(name="url", pg_type="text", nullable=False),),
                primary_key=("url",),
                is_view=False,
            )
        }

        entry = READ_MODEL_REGISTRY["relays"]

        assert entry.schema(catalog) == catalog.tables["relay"]

    async def test_entry_query_delegates_to_catalog(self) -> None:
        catalog = Catalog()
        expected = QueryResult(
            rows=[{"url": "wss://relay.example.com"}], total=1, limit=5, offset=0
        )
        catalog.query = AsyncMock(return_value=expected)  # type: ignore[method-assign]
        brotr = object()

        entry = READ_MODEL_REGISTRY["relays"]
        request = ReadModelQuery(limit=5, offset=0, max_page_size=50, filters={"url": "foo"})

        result = await entry.query(brotr, catalog, request)

        assert result == expected
        catalog.query.assert_awaited_once_with(  # type: ignore[attr-defined]
            brotr,
            "relay",
            limit=5,
            offset=0,
            max_page_size=50,
            filters={"url": "foo"},
            sort=None,
            include_total=False,
            cursor=None,
            prefer_keyset=True,
        )

    async def test_entry_get_by_pk_delegates_to_catalog(self) -> None:
        catalog = Catalog()
        expected = {"url": "wss://relay.example.com"}
        catalog.get_by_pk = AsyncMock(return_value=expected)  # type: ignore[method-assign]
        brotr = object()

        entry = READ_MODEL_REGISTRY["relays"]
        pk_values = {"url": "wss://relay.example.com"}

        result = await entry.get_by_pk(brotr, catalog, pk_values)

        assert result == expected
        catalog.get_by_pk.assert_awaited_once_with(  # type: ignore[attr-defined]
            brotr,
            "relay",
            pk_values,
        )

    async def test_entry_delegates_to_custom_handlers(self) -> None:
        schema = TableSchema(
            name="custom",
            columns=(ColumnSchema(name="id", pg_type="text", nullable=False),),
            primary_key=("id",),
            is_view=False,
        )
        expected_result = QueryResult(rows=[{"id": "row-1"}], total=1, limit=1, offset=0)
        expected_row = {"id": "row-1"}
        schema_handler = MagicMock(return_value=schema)
        query_handler = AsyncMock(return_value=expected_result)
        get_by_pk_handler = AsyncMock(return_value=expected_row)
        entry = ReadModelEntry(
            read_model_id="custom",
            catalog_name="ignored",
            schema_handler=schema_handler,
            query_handler=query_handler,
            get_by_pk_handler=get_by_pk_handler,
        )
        catalog = Catalog()
        brotr = object()
        request = ReadModelQuery(limit=1, offset=0)
        pk_values = {"id": "row-1"}

        assert entry.schema(catalog) == schema
        assert await entry.query(brotr, catalog, request) == expected_result
        assert await entry.get_by_pk(brotr, catalog, pk_values) == expected_row

        schema_handler.assert_called_once_with(catalog, entry)
        query_handler.assert_awaited_once_with(brotr, catalog, entry, request)
        get_by_pk_handler.assert_awaited_once_with(brotr, catalog, entry, pk_values)

    def test_entry_summary_uses_registered_backend_schema(self) -> None:
        catalog = Catalog()
        catalog._tables = {
            "relay": TableSchema(
                name="relay",
                columns=(
                    ColumnSchema(name="url", pg_type="text", nullable=False),
                    ColumnSchema(name="network", pg_type="text", nullable=False),
                ),
                primary_key=("url",),
                is_view=False,
            )
        }

        summary = READ_MODEL_REGISTRY["relays"].summary(catalog=catalog, route_prefix="/v1")

        assert summary == {
            "id": "relays",
            "path": "/v1/relays",
            "field_count": 2,
            "supports_identity_lookup": True,
            "default_pagination_mode": "cursor",
            "supports_cursor_pagination": True,
        }

    def test_entry_detail_uses_registered_backend_schema(self) -> None:
        catalog = Catalog()
        catalog._tables = {
            "relay_stats": TableSchema(
                name="relay_stats",
                columns=(ColumnSchema(name="url", pg_type="text", nullable=False),),
                primary_key=(),
                is_view=True,
            )
        }

        detail = READ_MODEL_REGISTRY["relay-stats"].detail(catalog=catalog, route_prefix="/v1")

        assert detail == {
            "id": "relay-stats",
            "path": "/v1/relay-stats",
            "fields": [{"name": "url", "type": "text", "nullable": False}],
            "identity_fields": [],
            "pagination": {
                "default_mode": "offset",
                "supports_cursor": False,
                "supports_offset": True,
                "supports_total_opt_in": True,
                "cursor_param": None,
                "meta_cursor_field": None,
            },
        }


class TestReadModelSurface:
    def _surface(
        self,
        *,
        policies: dict[str, ReadModelPolicy] | None = None,
        catalog: Catalog | None = None,
    ) -> ReadModelSurface:
        surface = ReadModelSurface(policy_source=lambda: policies or {})
        if catalog is not None:
            surface.catalog = catalog
        return surface

    def test_init_creates_empty_catalog(self) -> None:
        surface = self._surface()

        assert isinstance(surface.catalog, Catalog)
        assert surface.catalog.tables == {}

    async def test_discover_uses_catalog_and_logs_shape(self) -> None:
        surface = self._surface()
        catalog = MagicMock()
        catalog.discover = AsyncMock()
        table = MagicMock(is_view=False)
        view = MagicMock(is_view=True)
        catalog.tables.values.return_value = [table, table, view]
        surface.catalog = catalog
        logger = MagicMock()
        brotr = MagicMock()

        await surface.discover(brotr, logger=logger)

        catalog.discover.assert_awaited_once_with(brotr)
        logger.info.assert_called_once_with("schema_discovered", tables=2, views=1)

    def test_resolve_filters_unknown_and_disabled_read_models(self) -> None:
        catalog = Catalog()
        catalog._tables = {"relay": MagicMock()}
        disabled = self._surface(
            policies={"relays": ReadModelPolicy(enabled=False)},
            catalog=catalog,
        )
        enabled = self._surface(
            policies={"relays": ReadModelPolicy(enabled=True)},
            catalog=catalog,
        )

        assert disabled.resolve("api", "relays") is None
        assert enabled.resolve("api", "relays") is not None
        assert enabled.resolve("api", "service_state") is None

    def test_enabled_names_follow_catalog_and_policy(self) -> None:
        catalog = Catalog()
        catalog._tables = {"relay": MagicMock(), "event": MagicMock()}
        surface = self._surface(
            policies={
                "relays": ReadModelPolicy(enabled=True),
                "events": ReadModelPolicy(enabled=False),
            },
            catalog=catalog,
        )

        assert surface.enabled_names("api") == ["relays"]

    async def test_query_entry_uses_catalog_context(self) -> None:
        catalog = Catalog()
        request = ReadModelQuery(limit=10, offset=0)
        result = MagicMock()
        catalog.query = AsyncMock(return_value=result)  # type: ignore[method-assign]
        brotr = MagicMock()
        surface = self._surface(catalog=catalog)
        read_model = ReadModelEntry(
            read_model_id="relays",
            catalog_name="relay",
        )

        resolved = await surface.query_entry(brotr, read_model, request)

        assert resolved is result
        catalog.query.assert_awaited_once_with(  # type: ignore[attr-defined]
            brotr,
            "relay",
            limit=10,
            offset=0,
            max_page_size=1000,
            filters=None,
            sort=None,
            include_total=False,
            cursor=None,
            prefer_keyset=True,
        )

    async def test_get_entry_by_pk_uses_catalog_context(self) -> None:
        catalog = Catalog()
        row = {"url": "wss://relay.example.com"}
        catalog.get_by_pk = AsyncMock(return_value=row)  # type: ignore[method-assign]
        brotr = MagicMock()
        surface = self._surface(catalog=catalog)
        read_model = ReadModelEntry(
            read_model_id="relays",
            catalog_name="relay",
        )

        resolved = await surface.get_entry_by_pk(brotr, read_model, {"url": row["url"]})

        assert resolved == row
        catalog.get_by_pk.assert_awaited_once_with(  # type: ignore[attr-defined]
            brotr,
            "relay",
            {"url": row["url"]},
        )

    async def test_resolve_plus_query_entry_returns_result(self) -> None:
        catalog = Catalog()
        catalog._tables = {"relay": MagicMock()}
        result = QueryResult(rows=[], total=None, limit=5, offset=0)
        catalog.query = AsyncMock(return_value=result)  # type: ignore[method-assign]
        surface = self._surface(
            policies={"relays": ReadModelPolicy(enabled=True)},
            catalog=catalog,
        )
        read_model = surface.resolve("api", "relays")

        assert read_model is not None
        resolved = await surface.query_entry(
            MagicMock(),
            read_model,
            ReadModelQuery(limit=5, offset=0),
        )

        assert resolved == result

    async def test_resolve_plus_get_entry_by_pk_returns_row(self) -> None:
        catalog = Catalog()
        catalog._tables = {"relay": MagicMock()}
        row = {"url": "wss://relay.example.com"}
        catalog.get_by_pk = AsyncMock(return_value=row)  # type: ignore[method-assign]
        surface = self._surface(
            policies={"relays": ReadModelPolicy(enabled=True)},
            catalog=catalog,
        )
        read_model = surface.resolve("api", "relays")

        assert read_model is not None
        resolved = await surface.get_entry_by_pk(
            MagicMock(),
            read_model,
            {"url": row["url"]},
        )

        assert resolved == row

    def test_build_summaries_and_detail_use_enabled_surface(self) -> None:
        catalog = Catalog()
        catalog._tables = {
            "relay": TableSchema(
                name="relay",
                columns=(
                    ColumnSchema(name="url", pg_type="text", nullable=False),
                    ColumnSchema(name="network", pg_type="text", nullable=False),
                ),
                primary_key=("url",),
                is_view=False,
            )
        }
        surface = self._surface(
            policies={"relays": ReadModelPolicy(enabled=True)},
            catalog=catalog,
        )

        summaries = surface.build_summaries("api", route_prefix="/v1")
        detail = surface.build_detail("api", "relays", route_prefix="/v1")

        assert summaries == [
            {
                "id": "relays",
                "path": "/v1/relays",
                "field_count": 2,
                "supports_identity_lookup": True,
                "default_pagination_mode": "cursor",
                "supports_cursor_pagination": True,
            }
        ]
        assert detail == {
            "id": "relays",
            "path": "/v1/relays",
            "fields": [
                {"name": "url", "type": "text", "nullable": False},
                {"name": "network", "type": "text", "nullable": False},
            ],
            "identity_fields": ["url"],
            "pagination": {
                "default_mode": "cursor",
                "supports_cursor": True,
                "supports_offset": True,
                "supports_total_opt_in": True,
                "cursor_param": "cursor",
                "meta_cursor_field": "next_cursor",
            },
        }


class TestReadModelQueryHelpers:
    def test_parse_read_model_filter_string_empty(self) -> None:
        assert parse_read_model_filter_string("") is None

    def test_parse_read_model_filter_string_trims_and_skips_invalid_parts(self) -> None:
        assert parse_read_model_filter_string(" network = clearnet , invalid , kind = 1 ") == {
            "network": "clearnet",
            "kind": "1",
        }

    def test_read_model_query_from_http_params(self) -> None:
        query = read_model_query_from_http_params(
            {
                "limit": "25",
                "offset": "5",
                "sort": "url:asc",
                "include_total": "true",
                "network": "clearnet",
            },
            default_page_size=100,
            max_page_size=1000,
        )

        assert query == ReadModelQuery(
            limit=25,
            offset=5,
            max_page_size=1000,
            filters={"network": "clearnet"},
            sort="url:asc",
            include_total=True,
            cursor=None,
        )

    def test_read_model_query_from_http_params_invalid_limit(self) -> None:
        with pytest.raises(ReadModelQueryError, match="Invalid limit or offset"):
            read_model_query_from_http_params(
                {"limit": "oops"},
                default_page_size=100,
                max_page_size=1000,
            )

    def test_read_model_query_from_http_params_invalid_include_total(self) -> None:
        with pytest.raises(ReadModelQueryError, match="Invalid include_total value"):
            read_model_query_from_http_params(
                {"include_total": "maybe"},
                default_page_size=100,
                max_page_size=1000,
            )

    def test_read_model_query_from_http_params_with_cursor(self) -> None:
        query = read_model_query_from_http_params(
            {"cursor": "opaque-token", "limit": "20"},
            default_page_size=100,
            max_page_size=1000,
        )

        assert query == ReadModelQuery(
            limit=20,
            offset=0,
            max_page_size=1000,
            filters=None,
            sort=None,
            include_total=False,
            cursor="opaque-token",
        )

    def test_read_model_query_from_http_params_rejects_cursor_with_offset(self) -> None:
        with pytest.raises(
            ReadModelQueryError,
            match="Cursor pagination cannot be combined with offset",
        ):
            read_model_query_from_http_params(
                {"cursor": "opaque-token", "offset": "1"},
                default_page_size=100,
                max_page_size=1000,
            )

    def test_read_model_query_from_job_params(self) -> None:
        query = read_model_query_from_job_params(
            {
                "limit": "50",
                "offset": "10",
                "sort": "url:asc",
                "filter": "network=clearnet,kind=>:100",
                "include_total": "1",
            },
            default_page_size=100,
            max_page_size=1000,
        )

        assert query == ReadModelQuery(
            limit=50,
            offset=10,
            max_page_size=1000,
            filters={"network": "clearnet", "kind": ">:100"},
            sort="url:asc",
            include_total=True,
            cursor=None,
        )

    def test_read_model_query_from_job_params_invalid_offset(self) -> None:
        with pytest.raises(ReadModelQueryError, match="Invalid limit or offset value"):
            read_model_query_from_job_params(
                {"offset": "oops"},
                default_page_size=100,
                max_page_size=1000,
            )

    def test_read_model_query_from_job_params_invalid_include_total(self) -> None:
        with pytest.raises(ReadModelQueryError, match="Invalid include_total value"):
            read_model_query_from_job_params(
                {"include_total": "maybe"},
                default_page_size=100,
                max_page_size=1000,
            )

    def test_read_model_query_from_job_params_with_cursor(self) -> None:
        query = read_model_query_from_job_params(
            {"cursor": "opaque-token", "limit": "10"},
            default_page_size=100,
            max_page_size=1000,
        )

        assert query == ReadModelQuery(
            limit=10,
            offset=0,
            max_page_size=1000,
            filters=None,
            sort=None,
            include_total=False,
            cursor="opaque-token",
        )

    def test_read_model_query_from_job_params_rejects_cursor_with_offset(self) -> None:
        with pytest.raises(
            ReadModelQueryError,
            match="Cursor pagination cannot be combined with offset",
        ):
            read_model_query_from_job_params(
                {"cursor": "opaque-token", "offset": "1"},
                default_page_size=100,
                max_page_size=1000,
            )

    def test_build_read_model_meta(self) -> None:
        meta = build_read_model_meta(
            QueryResult(
                rows=[{"url": "wss://relay.example.com"}],
                total=1,
                limit=10,
                offset=0,
                next_cursor="opaque-token",
            ),
            read_model_id="relays",
        )

        assert meta == {
            "total": 1,
            "limit": 10,
            "offset": 0,
            "next_cursor": "opaque-token",
            "read_model": "relays",
        }

    def test_build_read_model_meta_omits_total_when_unavailable(self) -> None:
        meta = build_read_model_meta(
            QueryResult(
                rows=[{"url": "wss://relay.example.com"}],
                total=None,
                limit=10,
                offset=0,
            ),
            read_model_id="relays",
        )

        assert meta == {
            "limit": 10,
            "offset": 0,
            "read_model": "relays",
        }

    def test_normalize_read_model_policies_rejects_non_canonical_names(self) -> None:
        with pytest.raises(
            ValueError,
            match=r"read_models contains non-public API read models: relay, relay_stats",
        ):
            normalize_read_model_policies(
                {
                    "relay": ReadModelPolicy(enabled=True),
                    "relay_stats": ReadModelPolicy(enabled=True),
                },
                surface="api",
            )
